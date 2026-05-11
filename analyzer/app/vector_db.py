from __future__ import annotations

import logging
import math
import os
import re
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None


from .config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_DB_PATH,
    EMBEDDING_MODEL_NAME,
    OPENSEARCH_INDEX_NAME,
    OPENSEARCH_PASSWORD,
    OPENSEARCH_URL,
    OPENSEARCH_USERNAME,
    OPENSEARCH_VERIFY_CERTS,
    QDRANT_API_KEY,
    QDRANT_COLLECTION_NAME,
    QDRANT_PREFER_GRPC,
    QDRANT_URL,
    TEXT_SEARCH_BACKEND,
    VECTOR_SEARCH_BACKEND,
)

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
except Exception:
    chromadb = None
    ChromaSettings = None

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qdrant_models
except Exception:
    QdrantClient = None
    qdrant_models = None

try:
    from opensearchpy import OpenSearch
    from opensearchpy.helpers import bulk as opensearch_bulk
except Exception:
    OpenSearch = None
    opensearch_bulk = None

logger = logging.getLogger(__name__)


_QUERY_SYMBOL_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    ("∈", " 属于 "),
    ("∉", " 不属于 "),
    ("∪", " 并集 "),
    ("∩", " 交集 "),
    ("∁", " 补集 "),
    ("∀", " 全称量词 "),
    ("∃", " 存在量词 "),
    ("⇒", " 推出 "),
    ("⇔", " 等价 "),
    ("⊆", " 子集 "),
    ("⊂", " 真子集 "),
    ("≥", " 大于等于 "),
    ("≤", " 小于等于 "),
    ("≠", " 不等于 "),
    ("N+", " 正整数 "),
    ("N*", " 自然数 "),
    ("R", " 实数集 "),
)

_QUESTION_PREFIX_PATTERN = re.compile(r"^\s*\d+\s*[\.\．、\)]\s*")
_QUESTION_TYPE_PATTERN = re.compile(r"[\(\[（【]\s*(多选|单选|填空|判断|解答|用结论)\s*[\)\]）】]")
_QUESTION_NOISE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"下列结论[正确错误]*的是"),
    re.compile(r"则下列结论[正确错误]*的是"),
    re.compile(r"下列说法[正确错误]*的是"),
    re.compile(r"则有"),
    re.compile(r"则"),
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default=%s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default=%s", name, raw, default)
        return default


def _normalize_query_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _huggingface_cache_root() -> Path:
    custom_home = os.getenv("HF_HOME")
    if custom_home:
        return Path(custom_home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _cached_model_snapshot(model_name: str) -> Optional[str]:
    normalized = model_name.strip().replace("/", "--")
    if not normalized:
        return None
    snapshots_dir = _huggingface_cache_root() / f"models--{normalized}" / "snapshots"
    if not snapshots_dir.exists():
        return None
    snapshots = [item for item in snapshots_dir.iterdir() if item.is_dir()]
    if not snapshots:
        return None
    latest = max(snapshots, key=lambda item: item.stat().st_mtime)
    return str(latest)


def _query_terms(query_text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{1,}", _normalize_query_whitespace(query_text))
    terms: List[str] = []
    seen: set[str] = set()
    for token in tokens:
        normalized = token.strip()
        if len(normalized) <= 1 and not normalized.isdigit():
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(normalized)
    return terms


def _lightweight_overlap_score(query_terms: Sequence[str], text: str) -> float:
    lowered = str(text or "").lower()
    if not query_terms or not lowered:
        return 0.0
    matched = 0
    for term in query_terms:
        if term.lower() in lowered:
            matched += 1
    return matched / max(len(query_terms), 1)


def _lightweight_rerank_hits(
    query_text: str,
    hits: Sequence[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    query_terms = _query_terms(query_text)
    ranked: List[Dict[str, Any]] = []
    entity_weight = {
        "knowledge_point": 1.18,
        "knowledge_package_point": 1.12,
        "knowledge_block": 1.04,
        "knowledge_atom": 1.02,
        "knowledge_question_bridge": 0.98,
    }
    view_bonus = {
        "kp_definition": 0.08,
        "kp_summary": 0.05,
        "kp_example_bridge": -0.03,
    }
    for index, item in enumerate(hits):
        current = dict(item)
        metadata = dict(current.get("metadata") or {})
        entity_type = str(metadata.get("entity_type") or "")
        title = " ".join(
            part for part in [
                metadata.get("title"),
                metadata.get("knowledge_point_name"),
                metadata.get("package_title"),
            ] if part
        )
        content = str(current.get("content") or "")
        base_score = float(current.get("score") or 0.0)
        title_overlap = _lightweight_overlap_score(query_terms, title)
        content_overlap = _lightweight_overlap_score(query_terms, content[:800])
        source_boost = entity_weight.get(entity_type, 1.0)
        bonus = view_bonus.get(str(metadata.get("view_type") or ""), 0.0)
        lightweight_score = round(
            (base_score * source_boost)
            + (title_overlap * 0.22)
            + (content_overlap * 0.12)
            + bonus,
            6,
        )
        current["lightweight_score"] = lightweight_score
        current["lightweight_rank_features"] = {
            "base_score": round(base_score, 6),
            "title_overlap": round(title_overlap, 6),
            "content_overlap": round(content_overlap, 6),
            "entity_weight": round(source_boost, 3),
            "view_bonus": round(bonus, 3),
        }
        ranked.append(current)
    ranked.sort(
        key=lambda item: (
            -float(item.get("lightweight_score") or 0.0),
            -float(item.get("score") or 0.0),
            str((item.get("metadata") or {}).get("entity_type") or ""),
            str(item.get("id") or ""),
        )
    )
    return ranked[:top_k]


def _clean_query_for_recall(query_text: str) -> Dict[str, Any]:
    raw_query = _normalize_query_whitespace(query_text)
    if not raw_query:
        return {"query": "", "variants": []}

    variants: List[str] = [raw_query]
    trimmed = _QUESTION_PREFIX_PATTERN.sub("", raw_query)
    trimmed = _QUESTION_TYPE_PATTERN.sub(" ", trimmed)
    trimmed = _normalize_query_whitespace(trimmed)
    if trimmed and trimmed != raw_query:
        variants.append(trimmed)

    symbol_expanded = trimmed or raw_query
    for needle, replacement in _QUERY_SYMBOL_REPLACEMENTS:
        symbol_expanded = symbol_expanded.replace(needle, replacement)
    symbol_expanded = re.sub(r"[{}=,:;，。；：()\[\]（）【】]+", " ", symbol_expanded)
    symbol_expanded = _normalize_query_whitespace(symbol_expanded)
    if symbol_expanded and symbol_expanded not in variants:
        variants.append(symbol_expanded)

    content_focused = symbol_expanded
    for pattern in _QUESTION_NOISE_PATTERNS:
        content_focused = pattern.sub(" ", content_focused)
    content_focused = re.sub(r"\s+", " ", content_focused).strip(" .，。；;：:")
    if len(re.sub(r"\W+", "", content_focused, flags=re.UNICODE)) >= 4 and content_focused not in variants:
        variants.append(content_focused)

    unique_variants: List[str] = []
    seen: set[str] = set()
    for item in variants:
        normalized = _normalize_query_whitespace(item)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_variants.append(normalized)
    return {
        "query": " ".join(unique_variants),
        "variants": unique_variants,
    }


def _select_vector_query(query_plan: Dict[str, Any], fallback_query: str, max_chars: int) -> str:
    candidates = list(query_plan.get("variants") or [])
    if not candidates:
        return _normalize_query_whitespace(fallback_query)[:max_chars]

    def _score(text: str) -> Tuple[int, int, int]:
        cleaned = _normalize_query_whitespace(text)
        terms = _query_terms(cleaned)
        semantic_markers = sum(
            1
            for marker in ("属于", "并集", "交集", "补集", "子集", "真子集", "全称量词", "存在量词", "不等于", "大于等于", "小于等于")
            if marker in cleaned
        )
        return (semantic_markers, len(terms), len(cleaned))

    best = max(candidates, key=_score)
    normalized = _normalize_query_whitespace(best)
    if len(normalized) <= max_chars:
        return normalized
    shortened = normalized[:max_chars].rstrip()
    split_at = max(shortened.rfind(" "), shortened.rfind("，"), shortened.rfind(","))
    if split_at >= max_chars * 0.6:
        shortened = shortened[:split_at]
    return shortened.strip()


def _call_with_timeout(label: str, timeout_seconds: float, func, fallback):
    """Run a backend call with a best-effort timeout.

    Python cannot forcibly kill a running worker thread; on timeout we stop
    waiting and let the caller decide whether to disable that branch for the
    remainder of the process.
    """
    if timeout_seconds <= 0:
        started = time.perf_counter()
        return func(), (time.perf_counter() - started) * 1000.0, False, None

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"{label}-timeout")
    future = executor.submit(func)
    started = time.perf_counter()
    try:
        result = future.result(timeout=timeout_seconds)
        return result, (time.perf_counter() - started) * 1000.0, False, None
    except TimeoutError:
        future.cancel()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return fallback, elapsed_ms, True, f"{label} timed out after {timeout_seconds:.2f}s"
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return fallback, elapsed_ms, False, str(exc)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _await_future_result(
    label: str,
    future: Future,
    started_at: float,
    timeout_seconds: float,
    fallback,
):
    """Await a pre-submitted future with a timeout measured from submission time."""
    if timeout_seconds <= 0:
        try:
            result = future.result()
            return result, (time.perf_counter() - started_at) * 1000.0, False, None
        except Exception as exc:
            return fallback, (time.perf_counter() - started_at) * 1000.0, False, str(exc)

    elapsed_seconds = time.perf_counter() - started_at
    remaining_seconds = timeout_seconds - elapsed_seconds
    if remaining_seconds <= 0 and not future.done():
        future.cancel()
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        return fallback, elapsed_ms, True, f"{label} timed out after {timeout_seconds:.2f}s"

    try:
        result = future.result(timeout=max(remaining_seconds, 0.0))
        return result, (time.perf_counter() - started_at) * 1000.0, False, None
    except TimeoutError:
        future.cancel()
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        return fallback, elapsed_ms, True, f"{label} timed out after {timeout_seconds:.2f}s"
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        return fallback, elapsed_ms, False, str(exc)


class EmbeddingProvider:
    def __init__(self, model_name: str):
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers 未安装，无法初始化向量嵌入模型")
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        self._vector_dim: Optional[int] = None
        self._query_cache: "OrderedDict[str, List[float]]" = OrderedDict()
        self._cache_lock = Lock()
        self._cache_max_size = max(16, _env_int("QUERY_EMBED_CACHE_SIZE", 128))

    @property
    def vector_dim(self) -> int:
        if self._vector_dim is None:
            self._vector_dim = len(self.embed_text("dimension_probe"))
        return self._vector_dim

    def embed_text(self, text: str) -> List[float]:
        normalized = _normalize_query_whitespace(text)
        if normalized:
            with self._cache_lock:
                cached = self._query_cache.get(normalized)
                if cached is not None:
                    self._query_cache.move_to_end(normalized)
                    return list(cached)
        vector = self.embed_texts([text])[0]
        if normalized:
            with self._cache_lock:
                self._query_cache[normalized] = list(vector)
                self._query_cache.move_to_end(normalized)
                while len(self._query_cache) > self._cache_max_size:
                    self._query_cache.popitem(last=False)
        return vector

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def warm_up(self) -> None:
        self.embed_text("warmup")


class RerankerProvider:
    """Cross-encoder reranker for precision refinement after hybrid recall.

    Uses bge-reranker-v2-m3 with bounded max_length to keep CPU memory stable.
    Documents are truncated per-token by the model tokenizer; the max_length cap
    prevents the O(n * seq_len^2) attention matrix from exploding on CPU.
    """

    MAX_LENGTH = 1024          # per-document token cap for the cross-encoder
    PREDICT_BATCH_SIZE = 8     # score at most this many pairs per forward pass

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", model_source: Optional[str] = None):
        from sentence_transformers import CrossEncoder
        self.model_name = model_name
        self.model_source = model_source or model_name
        self._model: Optional[CrossEncoder] = None
        self._init_error: Optional[str] = None
        try:
            self._model = CrossEncoder(
                self.model_source,
                max_length=self.MAX_LENGTH,
                device="cpu",
            )
            logger.info(
                "Reranker model '%s' loaded from '%s' (max_length=%s, device=cpu)",
                model_name, self.model_source, self.MAX_LENGTH,
            )
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning("Reranker model '%s' unavailable from '%s': %s", model_name, self.model_source, exc)

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Rerank candidates by cross-encoder relevance. Falls back to original order if unavailable."""
        if not self._model or not candidates:
            return candidates[:top_k]

        try:
            documents = [c.get("content") or "" for c in candidates]
            pairs = [(query, doc) for doc in documents]

            # Score in micro-batches so a single oversized forward pass never OOMs
            all_scores: List[float] = []
            for batch_start in range(0, len(pairs), self.PREDICT_BATCH_SIZE):
                batch = pairs[batch_start : batch_start + self.PREDICT_BATCH_SIZE]
                batch_scores = self._model.predict(
                    batch, show_progress_bar=False,
                )
                if hasattr(batch_scores, "tolist"):
                    batch_scores = batch_scores.tolist()
                all_scores.extend(float(s) for s in batch_scores)

            for i, c in enumerate(candidates):
                c["reranker_score"] = round(all_scores[i], 6)
            candidates.sort(key=lambda x: x.get("reranker_score", 0.0), reverse=True)
            return candidates[:top_k]
        except Exception as exc:
            logger.warning("Rerank failed, returning original order: %s", exc)
            return candidates[:top_k]


class GraphEntityIndex:
    """Semantic entity lookup backed by Qdrant.

    Stores entity (name, context) embeddings so graph search can start from
    semantically relevant nodes instead of relying on CONTAINS substring matching.
    """

    COLLECTION_NAME = "knowledge_entities"

    def __init__(self, embedding_provider: EmbeddingProvider):
        if QdrantClient is None:
            raise RuntimeError("qdrant-client 未安装，无法初始化实体向量索引")
        self.embedding_provider = embedding_provider
        self._client = QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            prefer_grpc=QDRANT_PREFER_GRPC,
            trust_env=False,
            check_compatibility=False,
        )
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            self._client.get_collection(self.COLLECTION_NAME)
        except Exception:
            self._client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=qdrant_models.VectorParams(
                    size=self.embedding_provider.vector_dim,
                    distance=qdrant_models.Distance.COSINE,
                ),
            )

    def upsert_entities(self, entities: List[Dict[str, str]]) -> None:
        """Index entity names for semantic lookup. Each dict needs 'name' (unique key) and 'context'."""
        if not entities:
            return
        names = [e["name"] for e in entities]
        ids = [str(uuid.uuid5(uuid.NAMESPACE_DNS, f"entity:{name}")) for name in names]
        embeddings = self.embedding_provider.embed_texts(names)
        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[
                qdrant_models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={"name": e["name"], "context": e.get("context", "")},
                )
                for point_id, embedding, e in zip(ids, embeddings, entities)
            ],
        )

    def search(
        self,
        query_text: str,
        top_k: int = 10,
        min_score: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """Find semantically closest entity names for a query."""
        query_vector = self.embedding_provider.embed_text(query_text)
        results = self._client.search(
            collection_name=self.COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=min_score,
        )
        return [
            {
                "name": hit.payload.get("name", ""),
                "context": hit.payload.get("context", ""),
                "score": round(hit.score, 6),
            }
            for hit in results
        ]


class NoopVectorBackend:
    backend_type = "disabled"

    def __init__(self, reason: str):
        self.reason = reason
        self.embedding_model_name = None
        self.last_search_debug: Dict[str, Any] = {"backend": "disabled", "error": reason}

    @property
    def vector_dim(self) -> int:
        return 0

    def upsert_documents(self, documents: Sequence[str], metadatas: Sequence[Dict[str, Any]], ids: Sequence[str]) -> None:
        del documents, metadatas, ids
        raise RuntimeError(self.reason)

    def delete_documents(self, ids: Sequence[str]) -> None:
        del ids

    def search_with_scores(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        del query_text, n_results, entity_types, metadata_filters
        self.last_search_debug = {"backend": "disabled", "error": self.reason}
        return []

    def clear_collection(self) -> None:
        return None


class ChromaVectorBackend:

    backend_type = "chroma"

    def __init__(self, embedding_provider: EmbeddingProvider, path: str, collection_name: str):
        if chromadb is None or ChromaSettings is None:
            raise RuntimeError("chromadb 未安装，无法启用 Chroma 向量后端")
        self.embedding_provider = embedding_provider
        self.embedding_model_name = embedding_provider.model_name
        self.client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self.last_search_debug: Dict[str, Any] = {}
        logger.info("Connected to Chroma collection '%s' at '%s'", collection_name, path)

    @property
    def vector_dim(self) -> int:
        return self.embedding_provider.vector_dim

    def upsert_documents(self, documents: Sequence[str], metadatas: Sequence[Dict[str, Any]], ids: Sequence[str]) -> None:
        embeddings = self.embedding_provider.embed_texts(documents)
        self.collection.upsert(
            documents=list(documents),
            embeddings=embeddings,
            metadatas=list(metadatas),
            ids=list(ids),
        )

    def delete_documents(self, ids: Sequence[str]) -> None:
        if ids:
            self.collection.delete(ids=list(ids))

    def search_with_scores(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        total_started = time.perf_counter()
        embed_started = time.perf_counter()
        query_embedding = self.embedding_provider.embed_text(query_text)
        embed_ms = (time.perf_counter() - embed_started) * 1000.0
        backend_started = time.perf_counter()
        raw_results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        backend_ms = (time.perf_counter() - backend_started) * 1000.0
        documents = raw_results.get("documents", [[]])[0]
        metadatas = raw_results.get("metadatas", [[]])[0]
        distances = raw_results.get("distances", [[]])[0]
        ids = raw_results.get("ids", [[]])[0] if raw_results.get("ids") else [None] * len(documents)
        hits: List[Dict[str, Any]] = []
        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            if not _matches_metadata(metadata, entity_types=entity_types, metadata_filters=metadata_filters):
                continue
            distance = float(distances[index]) if index < len(distances) else 1.0
            vector_score = round(1 / (1 + max(distance, 0.0)), 6)
            result_id = ids[index] if index < len(ids) else None
            hits.append(
                {
                    "id": result_id,
                    "content": document,
                    "metadata": metadata,
                    "distance": distance,
                    "score": vector_score,
                    "vector_score": vector_score,
                    "text_score": 0.0,
                    "source_type": "vector",
                }
            )
        self.last_search_debug = {
            "backend": self.backend_type,
            "embedding_ms": round(embed_ms, 3),
            "backend_ms": round(backend_ms, 3),
            "total_ms": round((time.perf_counter() - total_started) * 1000.0, 3),
            "raw_hits": len(documents),
            "filtered_hits": len(hits),
        }
        return hits

    def clear_collection(self) -> None:
        all_items = self.collection.get()
        ids_to_delete = all_items.get("ids") or []
        if ids_to_delete:
            self.collection.delete(ids=ids_to_delete)


class QdrantVectorBackend:
    backend_type = "qdrant"

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        url: str,
        api_key: Optional[str],
        collection_name: str,
        prefer_grpc: bool,
    ):
        if QdrantClient is None or qdrant_models is None:
            raise RuntimeError("qdrant-client 未安装，无法启用 Qdrant 向量后端")
        self.embedding_provider = embedding_provider
        self.embedding_model_name = embedding_provider.model_name
        self.collection_name = collection_name
        self.client = QdrantClient(
            url=url,
            api_key=api_key,
            prefer_grpc=prefer_grpc,
            trust_env=False,
            check_compatibility=False,
        )
        self.last_search_debug: Dict[str, Any] = {}
        self._ensure_collection()
        logger.info("Connected to Qdrant collection '%s' at '%s'", collection_name, url)

    @property
    def vector_dim(self) -> int:
        return self.embedding_provider.vector_dim

    @staticmethod
    def _to_point_id(id_str: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, id_str))

    def _ensure_collection(self) -> None:
        try:
            self.client.get_collection(self.collection_name)
        except Exception:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=qdrant_models.VectorParams(
                    size=self.embedding_provider.vector_dim,
                    distance=qdrant_models.Distance.COSINE,
                ),
            )

    def upsert_documents(self, documents: Sequence[str], metadatas: Sequence[Dict[str, Any]], ids: Sequence[str]) -> None:
        if not documents:
            return
        embeddings = self.embedding_provider.embed_texts(documents)
        points = []
        for index, document in enumerate(documents):
            metadata = dict(metadatas[index] if index < len(metadatas) else {})
            metadata["content"] = document
            points.append(
                qdrant_models.PointStruct(
                    id=self._to_point_id(ids[index]),
                    vector=embeddings[index],
                    payload=metadata,
                )
            )
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)

    def delete_documents(self, ids: Sequence[str]) -> None:
        if not ids:
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qdrant_models.PointIdsList(points=[self._to_point_id(item) for item in ids]),
            wait=True,
        )

    def search_with_scores(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        total_started = time.perf_counter()
        embed_started = time.perf_counter()
        query_embedding = self.embedding_provider.embed_text(query_text)
        embed_ms = (time.perf_counter() - embed_started) * 1000.0
        query_filter = _build_qdrant_filter(entity_types=entity_types, metadata_filters=metadata_filters)
        backend_started = time.perf_counter()
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=n_results,
            with_payload=True,
            query_filter=query_filter,
        )
        backend_ms = (time.perf_counter() - backend_started) * 1000.0
        hits: List[Dict[str, Any]] = []
        for item in results:
            payload = dict(item.payload or {})
            content = str(payload.pop("content", "") or "")
            vector_score = round(float(item.score or 0.0), 6)
            hits.append(
                {
                    "id": str(item.id),
                    "content": content,
                    "metadata": payload,
                    "distance": round(max(0.0, 1.0 - vector_score), 6),
                    "score": vector_score,
                    "vector_score": vector_score,
                    "text_score": 0.0,
                    "source_type": "vector",
                }
            )
        self.last_search_debug = {
            "backend": self.backend_type,
            "embedding_ms": round(embed_ms, 3),
            "backend_ms": round(backend_ms, 3),
            "total_ms": round((time.perf_counter() - total_started) * 1000.0, 3),
            "raw_hits": len(results),
            "filtered_hits": len(hits),
            "used_filter": query_filter is not None,
        }
        return hits

    def clear_collection(self) -> None:
        self.client.delete_collection(self.collection_name)
        self._ensure_collection()


class OpenSearchTextBackend:
    backend_type = "opensearch"

    def __init__(
        self,
        url: str,
        index_name: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_certs: bool = False,
    ):
        if OpenSearch is None:
            raise RuntimeError("opensearch-py 未安装，无法启用 OpenSearch 全文检索后端")
        http_auth = (username, password) if username else None
        self.index_name = index_name
        self.client = OpenSearch(
            hosts=[url],
            http_auth=http_auth,
            use_ssl=str(url).startswith("https://"),
            verify_certs=verify_certs,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
        )
        self.last_search_debug: Dict[str, Any] = {}
        self._ensure_index()
        logger.info("Connected to OpenSearch index '%s' at '%s'", index_name, url)

    def _ensure_index(self) -> None:
        if self.client.indices.exists(index=self.index_name):
            self._update_index_mapping()
            return
        mapping = {
            "settings": {
                "analysis": {
                    "analyzer": {
                        "default": {
                            "type": "smartcn",
                        },
                    }
                }
            },
            "mappings": {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "title": {"type": "text", "analyzer": "smartcn"},
                    "package_title": {"type": "text", "analyzer": "smartcn"},
                    "knowledge_point_name": {"type": "text", "analyzer": "smartcn"},
                    "content": {
                        "type": "text",
                        "analyzer": "smartcn",
                    },
                    "entity_type": {"type": "keyword"},
                    "entity_id": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "source_document_id": {"type": "keyword"},
                    "paper_id": {"type": "keyword"},
                    "question_no": {"type": "keyword"},
                    "subject": {"type": "keyword"},
                    "grade": {"type": "keyword"},
                    "block_role": {"type": "keyword"},
                    "view_type": {"type": "keyword"},
                    "knowledge_point_id": {"type": "keyword"},
                    "relation_type": {"type": "keyword"},
                }
            },
        }
        self.client.indices.create(index=self.index_name, body=mapping)

    def _update_index_mapping(self) -> None:
        """Add new fields to existing index mapping without recreating."""
        new_fields = {
            "title": {"type": "text", "analyzer": "smartcn"},
            "package_title": {"type": "text", "analyzer": "smartcn"},
            "knowledge_point_name": {"type": "text", "analyzer": "smartcn"},
            "view_type": {"type": "keyword"},
            "knowledge_point_id": {"type": "keyword"},
            "relation_type": {"type": "keyword"},
        }
        try:
            current = self.client.indices.get_mapping(index=self.index_name)
            props = list(current.values())[0].get("mappings", {}).get("properties", {})
        except Exception:
            return
        fields_to_add = {k: v for k, v in new_fields.items() if k not in props}
        if fields_to_add:
            self.client.indices.put_mapping(
                index=self.index_name,
                body={"properties": fields_to_add},
            )
            logger.info("OpenSearch mapping updated: %s", list(fields_to_add.keys()))

    def upsert_records(self, records: Sequence[Dict[str, Any]]) -> None:
        if not records:
            return
        actions = []
        for record in records:
            document = _build_search_document(record)
            action = {
                "_op_type": "index",
                "_index": self.index_name,
                "_id": document["doc_id"],
                "_source": document,
            }
            actions.append(action)
        if opensearch_bulk is not None:
            opensearch_bulk(self.client, actions, refresh=True)
            return
        for action in actions:
            self.client.index(index=self.index_name, id=action["_id"], body=action["_source"], refresh=True)

    def delete_documents(self, ids: Sequence[str]) -> None:
        if not ids:
            return
        actions = [{"_op_type": "delete", "_index": self.index_name, "_id": str(item)} for item in ids]
        if opensearch_bulk is not None:
            opensearch_bulk(self.client, actions, refresh=True, raise_on_error=False)
            return
        for action in actions:
            try:
                self.client.delete(index=self.index_name, id=action["_id"], refresh=True)
            except Exception:
                logger.debug("OpenSearch document already absent: %s", action["_id"])

    def search_with_scores(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        total_started = time.perf_counter()
        query_plan = _clean_query_for_recall(query_text)
        recall_query = query_plan["query"] or _normalize_query_whitespace(query_text)
        filters: List[Dict[str, Any]] = []
        if entity_types:
            filters.append({"terms": {"entity_type": list(entity_types)}})
        for key, value in (metadata_filters or {}).items():
            if isinstance(value, (list, tuple, set)):
                normalized = [_normalize_metadata_value(v) for v in value]
                normalized = [v for v in normalized if v not in (None, "")]
                if normalized:
                    filters.append({"terms": {key: normalized}})
            else:
                normalized = _normalize_metadata_value(value)
                if normalized in (None, ""):
                    continue
                filters.append({"term": {key: normalized}})
        should_queries: List[Dict[str, Any]] = []
        for index, variant in enumerate(query_plan["variants"] or [recall_query]):
            should_queries.append(
                {
                    "multi_match": {
                        "query": variant,
                        "fields": [
                            "title^9",
                            "knowledge_point_name^8",
                            "package_title^5",
                            "content^4",
                            "question_no^2",
                            "subject^2",
                            "grade",
                            "block_role",
                            "relation_type",
                        ],
                        "type": "best_fields",
                        "boost": 1.0 if index == 0 else 0.72,
                    }
                }
            )
        body = {
            "size": n_results,
            "query": {
                "function_score": {
                    "query": {
                        "bool": {
                            "must": should_queries[:1],
                            "should": should_queries[1:],
                            "minimum_should_match": 0,
                            "filter": filters,
                        }
                    },
                    "functions": [
                        {"filter": {"term": {"entity_type": "knowledge_point"}}, "weight": 2.2},
                        {"filter": {"term": {"entity_type": "knowledge_package_point"}}, "weight": 1.9},
                        {"filter": {"term": {"entity_type": "knowledge_block"}}, "weight": 1.45},
                        {"filter": {"term": {"entity_type": "knowledge_atom"}}, "weight": 1.3},
                        {"filter": {"term": {"entity_type": "knowledge_question_bridge"}}, "weight": 1.1},
                        {"filter": {"term": {"view_type": "kp_definition"}}, "weight": 1.25},
                        {"filter": {"term": {"view_type": "kp_summary"}}, "weight": 1.15},
                        {"filter": {"term": {"view_type": "kp_example_bridge"}}, "weight": 0.92},
                    ],
                    "score_mode": "sum",
                    "boost_mode": "multiply",
                }
            },
        }
        search_started = time.perf_counter()
        response = self.client.search(index=self.index_name, body=body)
        search_ms = (time.perf_counter() - search_started) * 1000.0
        raw_hits = response.get("hits", {}).get("hits", [])
        hits: List[Dict[str, Any]] = []
        for item in raw_hits:
            source = item.get("_source") or {}
            raw_score = float(item.get("_score") or 0.0)
            text_score = round(math.tanh(raw_score / 10.0), 6)
            metadata = {
                "source": source.get("source") or "",
                "entity_type": source.get("entity_type") or "",
                "entity_id": source.get("entity_id") or "",
                "source_document_id": source.get("source_document_id") or "",
                "paper_id": source.get("paper_id") or "",
                "question_no": source.get("question_no") or "",
                "subject": source.get("subject") or "",
                "grade": source.get("grade") or "",
                "block_role": source.get("block_role") or "",
                "view_type": source.get("view_type") or "",
                "knowledge_point_id": source.get("knowledge_point_id") or "",
                "title": source.get("title") or "",
                "package_title": source.get("package_title") or "",
                "knowledge_point_name": source.get("knowledge_point_name") or "",
                "relation_type": source.get("relation_type") or "",
            }
            hits.append(
                {
                    "id": str(item.get("_id") or source.get("doc_id") or ""),
                    "content": source.get("content") or "",
                    "metadata": metadata,
                    "distance": None,
                    "score": text_score,
                    "vector_score": 0.0,
                    "text_score": text_score,
                    "source_type": "text",
                }
            )
        self.last_search_debug = {
            "backend": self.backend_type,
            "search_ms": round(search_ms, 3),
            "total_ms": round((time.perf_counter() - total_started) * 1000.0, 3),
            "raw_hits": len(raw_hits),
            "filtered_hits": len(hits),
            "query_variant_count": len(query_plan["variants"]),
        }
        return hits

    def clear_index(self) -> None:
        if self.client.indices.exists(index=self.index_name):
            self.client.delete_by_query(index=self.index_name, body={"query": {"match_all": {}}}, refresh=True)


class SearchIndexDB:
    def __init__(self):
        self.embedding_model_name = EMBEDDING_MODEL_NAME
        self.vector_backend_error: Optional[str] = None
        self.embedding_provider: Optional[EmbeddingProvider] = None
        self._embedding_warmup_started = False
        self.reranker: Optional[RerankerProvider] = None
        self._reranker_lock = Lock()
        self._reranker_model_name = os.getenv("HYBRID_RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3").strip() or "BAAI/bge-reranker-v2-m3"
        self._reranker_model_source = _cached_model_snapshot(self._reranker_model_name) or self._reranker_model_name
        self._reranker_loading = False
        self._reranker_preload_error: Optional[str] = None
        self.entity_index: Optional[GraphEntityIndex] = None
        self.hybrid_vector_timeout_seconds = _env_float("HYBRID_VECTOR_TIMEOUT_SECONDS", 8.0)
        self.hybrid_text_timeout_seconds = _env_float("HYBRID_TEXT_TIMEOUT_SECONDS", 8.0)
        self.hybrid_vector_grace_ms = _env_float("HYBRID_VECTOR_GRACE_MS", 35.0)
        self.hybrid_vector_query_max_chars = max(24, _env_int("HYBRID_VECTOR_QUERY_MAX_CHARS", 96))
        self.hybrid_rerank_timeout_seconds = _env_float("HYBRID_RERANK_TIMEOUT_SECONDS", 3.0)
        self.hybrid_rerank_max_candidates = max(4, _env_int("HYBRID_RERANK_MAX_CANDIDATES", 12))
        self.hybrid_rerank_enabled = _env_bool("HYBRID_RERANK_ENABLED", False)
        self.hybrid_lightweight_rerank_enabled = _env_bool("HYBRID_LIGHTWEIGHT_RERANK_ENABLED", True)
        self.disable_vector_after_timeout = _env_bool("HYBRID_DISABLE_VECTOR_AFTER_TIMEOUT", True)
        self._vector_disabled_reason: Optional[str] = None
        self.last_hybrid_diagnostics: Dict[str, Any] = {}
        try:
            self.embedding_provider = EmbeddingProvider(EMBEDDING_MODEL_NAME)
            self._start_embedding_warmup()
            self.vector_backend = self._build_vector_backend()
            self.embedding_model_name = self.embedding_provider.model_name
            self.entity_index = GraphEntityIndex(self.embedding_provider)
            if self.hybrid_rerank_enabled and self._reranker_model_source != self._reranker_model_name:
                self._start_reranker_preload()
        except Exception as exc:
            self.vector_backend_error = str(exc)
            logger.warning("Vector backend disabled: %s", exc)
            self.vector_backend = NoopVectorBackend(str(exc))
        self.text_backend = self._build_text_backend()

    def _start_embedding_warmup(self) -> None:
        if self._embedding_warmup_started or self.embedding_provider is None:
            return
        self._embedding_warmup_started = True

        def _runner() -> None:
            try:
                self.embedding_provider.warm_up()
                logger.info("Embedding provider warm-up completed")
            except Exception as exc:
                logger.warning("Embedding provider warm-up failed: %s", exc)

        Thread(target=_runner, name="embedding-warmup", daemon=True).start()

    def _start_reranker_preload(self) -> None:
        with self._reranker_lock:
            if self.reranker is not None or self._reranker_loading:
                return
            self._reranker_loading = True
            self._reranker_preload_error = None

        def _runner() -> None:
            try:
                provider = self._build_reranker_provider()
                with self._reranker_lock:
                    self.reranker = provider if provider.is_available else None
                    if provider.is_available:
                        self._reranker_preload_error = None
                    else:
                        self._reranker_preload_error = "reranker unavailable after preload"
                    self._reranker_loading = False
            except Exception as exc:
                with self._reranker_lock:
                    self._reranker_loading = False
                    self._reranker_preload_error = str(exc)
                logger.warning("Reranker preload failed: %s", exc)

        Thread(target=_runner, name="reranker-preload", daemon=True).start()

    def _build_reranker_provider(self) -> RerankerProvider:
        return RerankerProvider(
            model_name=self._reranker_model_name,
            model_source=self._reranker_model_source,
        )

    def _get_reranker(self, wait_for_ready: bool = True) -> Optional[RerankerProvider]:
        provider = self.reranker
        if provider is not None:
            return provider if provider.is_available else None
        with self._reranker_lock:
            provider = self.reranker
            if provider is not None:
                return provider if provider.is_available else None
            if self._reranker_loading:
                return None
            if not wait_for_ready:
                self._start_reranker_preload()
                return None
            self._reranker_loading = True
        try:
            provider = self._build_reranker_provider()
        except Exception as exc:
            with self._reranker_lock:
                self._reranker_loading = False
                self._reranker_preload_error = str(exc)
            logger.warning("Reranker load failed: %s", exc)
            return None
        with self._reranker_lock:
            self._reranker_loading = False
            self.reranker = provider if provider.is_available else None
            self._reranker_preload_error = None if provider.is_available else "reranker unavailable after synchronous load"
        return provider if provider.is_available else None


    @property
    def backend_summary(self) -> Dict[str, Optional[str]]:
        return {
            "vector_backend": getattr(self.vector_backend, "backend_type", None),
            "text_backend": getattr(self.text_backend, "backend_type", None) if self.text_backend else None,
            "embedding_model": self.embedding_model_name,
        }

    @property
    def index_backend_label(self) -> str:
        labels = [self.vector_backend.backend_type]
        if self.text_backend:
            labels.append(self.text_backend.backend_type)
        return "+".join(labels)

    def _build_vector_backend(self):
        if self.embedding_provider is None:
            return NoopVectorBackend("嵌入模型不可用，向量检索已禁用")

        requested = (VECTOR_SEARCH_BACKEND or "").strip().lower()
        if requested == "qdrant":
            try:
                return QdrantVectorBackend(
                    embedding_provider=self.embedding_provider,
                    url=QDRANT_URL,
                    api_key=QDRANT_API_KEY,
                    collection_name=QDRANT_COLLECTION_NAME,
                    prefer_grpc=QDRANT_PREFER_GRPC,
                )
            except Exception as exc:
                logger.warning("Qdrant backend unavailable, falling back to Chroma: %s", exc)
        return ChromaVectorBackend(
            embedding_provider=self.embedding_provider,
            path=CHROMA_DB_PATH,
            collection_name=CHROMA_COLLECTION_NAME,
        )


    def _build_text_backend(self):
        requested = (TEXT_SEARCH_BACKEND or "").strip().lower()
        if requested != "opensearch":
            return None
        try:
            return OpenSearchTextBackend(
                url=OPENSEARCH_URL,
                index_name=OPENSEARCH_INDEX_NAME,
                username=OPENSEARCH_USERNAME,
                password=OPENSEARCH_PASSWORD,
                verify_certs=OPENSEARCH_VERIFY_CERTS,
            )
        except Exception as exc:
            logger.warning("OpenSearch backend unavailable, lexical search disabled: %s", exc)
            return None

    def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]) -> None:
        self.upsert_documents(documents=documents, metadatas=metadatas, ids=ids)

    def upsert_documents(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]) -> None:
        if not documents:
            return
        self.vector_backend.upsert_documents(documents=documents, metadatas=metadatas, ids=ids)

    def upsert_retrieval_documents(self, records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        if not records:
            return {
                "indexed_count": 0,
                "vector_backend": self.vector_backend.backend_type,
                "text_backend": self.text_backend.backend_type if self.text_backend else None,
                "vector_dim": self.vector_backend.vector_dim,
            }
        documents = [str(record.get("document") or "") for record in records]
        metadatas = [dict(record.get("metadata") or {}) for record in records]
        ids = [str(record.get("id")) for record in records]
        self.vector_backend.upsert_documents(documents=documents, metadatas=metadatas, ids=ids)
        if self.text_backend:
            self.text_backend.upsert_records(records)
        return {
            "indexed_count": len(records),
            "vector_backend": self.vector_backend.backend_type,
            "text_backend": self.text_backend.backend_type if self.text_backend else None,
            "vector_dim": self.vector_backend.vector_dim,
            "embedding_model": self.embedding_model_name,
        }

    def delete_documents(self, ids: List[str]) -> None:
        if not ids:
            return
        self.vector_backend.delete_documents(ids=ids)
        if self.text_backend:
            self.text_backend.delete_documents(ids=ids)

    def search(
        self,
        query_text: str,
        n_results: int = 5,
        include: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        del include
        hits = self.search_with_scores(query_text=query_text, n_results=n_results)
        if not hits:
            return None
        return {
            "ids": [[item.get("id") for item in hits]],
            "documents": [[item.get("content") for item in hits]],
            "metadatas": [[item.get("metadata") for item in hits]],
            "distances": [[item.get("distance") for item in hits]],
        }

    def search_with_scores(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return self.vector_backend.search_with_scores(
            query_text=query_text,
            n_results=n_results,
            entity_types=entity_types,
            metadata_filters=metadata_filters,
        )

    def _hybrid_search_core(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        expanded_query: Optional[str] = None,
        enable_rerank: Optional[bool] = None,
        enable_lightweight_rerank: Optional[bool] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Hybrid search core with parallel recall and optional rerank.

        Args:
            query_text: Original user query (used for reranker so it scores against real intent).
            expanded_query: Optional LLM-expanded query for vector/text recall.
                           When provided, recall uses this; rerank still uses query_text.
        """
        query_plan = _clean_query_for_recall(expanded_query or query_text)
        recall_query = query_plan["query"] or (expanded_query or query_text)
        vector_query = _select_vector_query(query_plan, recall_query, self.hybrid_vector_query_max_chars)
        recall_size = max(n_results * 6, 30)
        total_started = time.perf_counter()
        rerank_enabled = self.hybrid_rerank_enabled if enable_rerank is None else bool(enable_rerank)
        lightweight_rerank_enabled = (
            self.hybrid_lightweight_rerank_enabled
            if enable_lightweight_rerank is None
            else bool(enable_lightweight_rerank)
        )
        diagnostics: Dict[str, Any] = {
            "query_text": query_text,
            "recall_query": recall_query,
            "vector_query": vector_query,
            "query_variants": query_plan["variants"],
            "n_results": n_results,
            "recall_size": recall_size,
            "branches": {
                "vector": {
                    "enabled": not bool(self._vector_disabled_reason),
                    "status": "disabled" if self._vector_disabled_reason else "pending",
                    "elapsed_ms": 0.0,
                    "hit_count": 0,
                    "error": self._vector_disabled_reason,
                },
                "text": {
                    "enabled": self.text_backend is not None,
                    "status": "disabled" if self.text_backend is None else "pending",
                    "elapsed_ms": 0.0,
                    "hit_count": 0,
                    "error": None,
                },
                "rerank": {
                    "enabled": rerank_enabled,
                    "status": "disabled",
                    "elapsed_ms": 0.0,
                    "input_count": 0,
                    "output_count": 0,
                    "error": None,
                },
                "lightweight_rerank": {
                    "enabled": lightweight_rerank_enabled,
                    "status": "disabled",
                    "elapsed_ms": 0.0,
                    "input_count": 0,
                    "output_count": 0,
                    "error": None,
                },
            },
        }
        vector_hits: List[Dict[str, Any]] = []
        text_hits: List[Dict[str, Any]] = []
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hybrid-search")
        try:
            vector_future: Optional[Future] = None
            vector_started: Optional[float] = None
            if self._vector_disabled_reason:
                logger.warning("Hybrid vector branch skipped: %s", self._vector_disabled_reason)
            else:
                vector_started = time.perf_counter()
                vector_future = executor.submit(
                    self.search_with_scores,
                    query_text=vector_query,
                    n_results=recall_size,
                    entity_types=entity_types,
                    metadata_filters=metadata_filters,
                )

            text_future: Optional[Future] = None
            text_started: Optional[float] = None
            if self.text_backend:
                text_started = time.perf_counter()
                text_future = executor.submit(
                    self.text_backend.search_with_scores,
                    query_text=recall_query,
                    n_results=recall_size,
                    entity_types=entity_types,
                    metadata_filters=metadata_filters,
                )

            if text_future is not None and text_started is not None:
                text_hits, text_ms, text_timed_out, text_error = _await_future_result(
                    "hybrid_text",
                    text_future,
                    text_started,
                    self.hybrid_text_timeout_seconds,
                    [],
                )
                diagnostics["branches"]["text"].update(
                    {
                        "status": "timeout" if text_timed_out else ("error" if text_error else "ok"),
                        "elapsed_ms": round(text_ms, 3),
                        "hit_count": len(text_hits),
                        "error": text_error,
                        "details": getattr(self.text_backend, "last_search_debug", None),
                    }
                )
                if text_timed_out:
                    logger.warning("Hybrid text branch timeout: %.1f ms query=%r", text_ms, recall_query[:80])
                elif text_error:
                    logger.warning("Hybrid text branch failed after %.1f ms: %s", text_ms, text_error)
                else:
                    logger.info("Hybrid text branch returned %d hits in %.1f ms", len(text_hits), text_ms)

            if vector_future is not None and vector_started is not None:
                should_return_text_fallback = bool(text_hits) and not vector_future.done()
                if should_return_text_fallback and self.hybrid_vector_grace_ms > 0:
                    grace_seconds = self.hybrid_vector_grace_ms / 1000.0
                    try:
                        vector_hits = vector_future.result(timeout=grace_seconds)
                        vector_ms = (time.perf_counter() - vector_started) * 1000.0
                        diagnostics["branches"]["vector"].update(
                            {
                                "status": "ok_after_grace",
                                "elapsed_ms": round(vector_ms, 3),
                                "hit_count": len(vector_hits),
                                "error": None,
                                "details": getattr(self.vector_backend, "last_search_debug", None),
                            }
                        )
                        should_return_text_fallback = False
                        logger.info(
                            "Hybrid vector branch finished during %.1f ms grace window: hits=%d total=%.1f ms",
                            self.hybrid_vector_grace_ms,
                            len(vector_hits),
                            vector_ms,
                        )
                    except TimeoutError:
                        should_return_text_fallback = True
                    except Exception as exc:
                        vector_ms = (time.perf_counter() - vector_started) * 1000.0
                        diagnostics["branches"]["vector"].update(
                            {
                                "status": "error",
                                "elapsed_ms": round(vector_ms, 3),
                                "hit_count": 0,
                                "error": str(exc),
                            }
                        )
                        should_return_text_fallback = False
                        logger.warning("Hybrid vector branch failed during grace wait after %.1f ms: %s", vector_ms, exc)
                if should_return_text_fallback:
                    vector_ms = (time.perf_counter() - vector_started) * 1000.0
                    diagnostics["branches"]["vector"].update(
                        {
                            "status": "skipped_after_text_ready",
                            "elapsed_ms": round(vector_ms, 3),
                            "hit_count": 0,
                            "error": "text branch returned first; vector branch left pending",
                        }
                    )
                    vector_future.cancel()
                    logger.warning(
                        "Hybrid vector branch still pending after text returned in %.1f ms; "
                        "serving text fallback for query=%r",
                        diagnostics["branches"]["text"]["elapsed_ms"],
                        recall_query[:80],
                    )
                else:
                    vector_hits, vector_ms, vector_timed_out, vector_error = _await_future_result(
                        "hybrid_vector",
                        vector_future,
                        vector_started,
                        self.hybrid_vector_timeout_seconds,
                        [],
                    )
                    diagnostics["branches"]["vector"].update(
                        {
                            "status": "timeout" if vector_timed_out else ("error" if vector_error else "ok"),
                            "elapsed_ms": round(vector_ms, 3),
                            "hit_count": len(vector_hits),
                            "error": vector_error,
                            "details": getattr(self.vector_backend, "last_search_debug", None),
                        }
                    )
                    if vector_timed_out:
                        logger.warning("Hybrid vector branch timeout: %.1f ms query=%r", vector_ms, recall_query[:80])
                        if self.disable_vector_after_timeout:
                            self._vector_disabled_reason = vector_error or "hybrid vector branch timed out"
                    elif vector_error:
                        logger.warning("Hybrid vector branch failed after %.1f ms: %s", vector_ms, vector_error)
                    else:
                        logger.info("Hybrid vector branch returned %d hits in %.1f ms", len(vector_hits), vector_ms)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        merged_hits = _merge_hits(vector_hits, text_hits)
        diagnostics["merge"] = {
            "vector_hits": len(vector_hits),
            "text_hits": len(text_hits),
            "merged_hits": len(merged_hits),
        }
        if lightweight_rerank_enabled and merged_hits:
            lightweight_started = time.perf_counter()
            merged_hits = _lightweight_rerank_hits(recall_query, merged_hits, len(merged_hits))
            lightweight_ms = (time.perf_counter() - lightweight_started) * 1000.0
            diagnostics["branches"]["lightweight_rerank"].update(
                {
                    "status": "ok",
                    "elapsed_ms": round(lightweight_ms, 3),
                    "input_count": diagnostics["merge"]["merged_hits"],
                    "output_count": len(merged_hits),
                }
            )
        else:
            diagnostics["branches"]["lightweight_rerank"].update(
                {
                    "status": "disabled" if not lightweight_rerank_enabled else "skipped",
                    "output_count": len(merged_hits),
                    "error": None if lightweight_rerank_enabled else "lightweight rerank disabled",
                }
            )
        rerank_candidates = merged_hits[: max(n_results, self.hybrid_rerank_max_candidates)]
        diagnostics["branches"]["rerank"]["candidate_limit"] = max(n_results, self.hybrid_rerank_max_candidates)
        reranker_provider = self._get_reranker(wait_for_ready=False) if rerank_enabled and rerank_candidates else None
        diagnostics["branches"]["rerank"]["enabled"] = rerank_enabled and reranker_provider is not None
        if rerank_enabled and reranker_provider and rerank_candidates:
            diagnostics["branches"]["rerank"]["status"] = "pending"
            diagnostics["branches"]["rerank"]["input_count"] = len(rerank_candidates)
            if self.hybrid_rerank_timeout_seconds > 0:
                reranked_hits, rerank_ms, rerank_timed_out, rerank_error = _call_with_timeout(
                    "hybrid_rerank",
                    self.hybrid_rerank_timeout_seconds,
                    lambda: reranker_provider.rerank(recall_query, list(rerank_candidates), n_results),
                    rerank_candidates[:n_results],
                )
                merged_hits = reranked_hits
                diagnostics["branches"]["rerank"].update(
                    {
                        "status": "timeout" if rerank_timed_out else ("error" if rerank_error else "ok"),
                        "elapsed_ms": round(rerank_ms, 3),
                        "output_count": len(merged_hits),
                        "error": rerank_error,
                    }
                )
                if rerank_timed_out:
                    logger.warning("Hybrid rerank timeout: %.1f ms query=%r", rerank_ms, recall_query[:80])
                elif rerank_error:
                    logger.warning("Hybrid rerank failed after %.1f ms: %s", rerank_ms, rerank_error)
                else:
                    logger.info("Hybrid rerank completed in %.1f ms", rerank_ms)
            else:
                rerank_started = time.perf_counter()
                merged_hits = reranker_provider.rerank(recall_query, list(rerank_candidates), n_results)
                rerank_ms = (time.perf_counter() - rerank_started) * 1000.0
                diagnostics["branches"]["rerank"].update(
                    {
                        "status": "ok",
                        "elapsed_ms": round(rerank_ms, 3),
                        "output_count": len(merged_hits),
                    }
                )
                logger.info("Hybrid rerank completed in %.1f ms", rerank_ms)
        else:
            merged_hits = merged_hits[:n_results]
            diagnostics["branches"]["rerank"].update(
                {
                    "status": "disabled" if not rerank_enabled else "skipped",
                    "output_count": len(merged_hits),
                    "error": None if reranker_provider is not None else ("rerank disabled for this search" if not rerank_enabled else "reranker warming up or unavailable"),
                }
            )
        diagnostics["returned_hits"] = len(merged_hits)
        diagnostics["total_ms"] = round((time.perf_counter() - total_started) * 1000.0, 3)
        self.last_hybrid_diagnostics = diagnostics
        logger.info(
            "Hybrid search completed: vector_hits=%d text_hits=%d returned=%d total_ms=%.1f",
            len(vector_hits),
            len(text_hits),
            len(merged_hits),
            diagnostics["total_ms"],
        )
        return merged_hits, diagnostics

    def hybrid_search_with_scores(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        expanded_query: Optional[str] = None,
        enable_rerank: Optional[bool] = None,
        enable_lightweight_rerank: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        hits, _ = self._hybrid_search_core(
            query_text=query_text,
            n_results=n_results,
            entity_types=entity_types,
            metadata_filters=metadata_filters,
            expanded_query=expanded_query,
            enable_rerank=enable_rerank,
            enable_lightweight_rerank=enable_lightweight_rerank,
        )
        return hits

    def hybrid_search_with_debug(
        self,
        query_text: str,
        n_results: int = 5,
        entity_types: Optional[Sequence[str]] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        expanded_query: Optional[str] = None,
        enable_rerank: Optional[bool] = None,
        enable_lightweight_rerank: Optional[bool] = None,
    ) -> Dict[str, Any]:
        hits, diagnostics = self._hybrid_search_core(
            query_text=query_text,
            n_results=n_results,
            entity_types=entity_types,
            metadata_filters=metadata_filters,
            expanded_query=expanded_query,
            enable_rerank=enable_rerank,
            enable_lightweight_rerank=enable_lightweight_rerank,
        )
        return {"hits": hits, "diagnostics": diagnostics}

    def clear_collection(self) -> None:
        self.vector_backend.clear_collection()
        if self.text_backend:
            self.text_backend.clear_index()

    def ensure_entity_index(self) -> int:
        """Sync Neo4j entities into the Qdrant entity collection. Returns count indexed."""
        if not self.entity_index:
            return 0
        try:
            from .graph_db import db as graph_db
            entities = graph_db.get_all_entity_names()
            if entities:
                self.entity_index.upsert_entities(entities)
                logger.info("Entity index synced: %d entities", len(entities))
            return len(entities)
        except Exception as exc:
            logger.warning("Entity index sync failed: %s", exc)
            return 0


def _normalize_metadata_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _matches_metadata(
    metadata: Dict[str, Any],
    entity_types: Optional[Sequence[str]] = None,
    metadata_filters: Optional[Dict[str, Any]] = None,
) -> bool:
    if entity_types and str(metadata.get("entity_type") or "") not in set(entity_types):
        return False
    for key, value in (metadata_filters or {}).items():
        expected = _normalize_metadata_value(value)
        if expected is None:
            continue
        actual = _normalize_metadata_value(metadata.get(key))
        if actual != expected:
            return False
    return True


def _build_search_document(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    return {
        "doc_id": str(record.get("id") or ""),
        "content": str(record.get("document") or ""),
        "title": str(metadata.get("title") or ""),
        "package_title": str(metadata.get("package_title") or ""),
        "knowledge_point_name": str(metadata.get("knowledge_point_name") or ""),
        "source": str(metadata.get("source") or ""),
        "entity_type": str(metadata.get("entity_type") or ""),
        "entity_id": str(metadata.get("entity_id") or ""),
        "source_document_id": str(metadata.get("source_document_id") or ""),
        "paper_id": str(metadata.get("paper_id") or ""),
        "question_no": str(metadata.get("question_no") or ""),
        "subject": str(metadata.get("subject") or ""),
        "grade": str(metadata.get("grade") or ""),
        "block_role": str(metadata.get("block_role") or ""),
        "view_type": str(metadata.get("view_type") or ""),
        "knowledge_point_id": str(metadata.get("knowledge_point_id") or ""),
        "relation_type": str(metadata.get("relation_type") or ""),
    }


def _build_qdrant_filter(
    entity_types: Optional[Sequence[str]] = None,
    metadata_filters: Optional[Dict[str, Any]] = None,
):
    if qdrant_models is None:
        return None
    conditions = []
    if entity_types:
        conditions.append(
            qdrant_models.FieldCondition(
                key="entity_type",
                match=qdrant_models.MatchAny(any=list(entity_types)),
            )
        )
    for key, value in (metadata_filters or {}).items():
        if isinstance(value, (list, tuple, set)):
            normalized = [_normalize_metadata_value(v) for v in value]
            normalized = [v for v in normalized if v is not None]
            if normalized:
                conditions.append(
                    qdrant_models.FieldCondition(
                        key=key,
                        match=qdrant_models.MatchAny(any=normalized),
                    )
                )
        else:
            normalized = _normalize_metadata_value(value)
            if normalized is None:
                continue
            conditions.append(
                qdrant_models.FieldCondition(
                    key=key,
                    match=qdrant_models.MatchValue(value=normalized),
                )
            )
    if not conditions:
        return None
    return qdrant_models.Filter(must=conditions)


def _merge_hits(vector_hits: Sequence[Dict[str, Any]], text_hits: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """RRF (Reciprocal Rank Fusion) merge of vector and text search results.

    Uses rank-based fusion so scores from heterogeneous backends are comparable.
    K=60 follows the original RRF paper's recommendation.
    """
    K: float = 60.0

    def _dedupe_key(hit: Dict[str, Any]) -> Tuple[str, str]:
        metadata = hit.get("metadata") or {}
        # source + entity_type uniquely identifies a document across both backends
        # (the id field differs because Qdrant and text index use different UUID formulas)
        return (
            str(metadata.get("source") or ""),
            str(metadata.get("entity_type") or ""),
        )

    # Build per-source rank maps (1-indexed)
    vector_ranks: Dict[Tuple[str, str], int] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        key = _dedupe_key(hit)
        if key not in vector_ranks:
            vector_ranks[key] = rank

    text_ranks: Dict[Tuple[str, str], int] = {}
    for rank, hit in enumerate(text_hits, start=1):
        key = _dedupe_key(hit)
        if key not in text_ranks:
            text_ranks[key] = rank

    # Collect unique documents with metadata
    all_docs: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for hit in list(vector_hits) + list(text_hits):
        key = _dedupe_key(hit)
        if key not in all_docs:
            all_docs[key] = {
                "id": hit.get("id"),
                "content": hit.get("content") or "",
                "metadata": hit.get("metadata") or {},
                "distance": hit.get("distance"),
                "source_types": [],
            }
        current = all_docs[key]
        if not current.get("content") and hit.get("content"):
            current["content"] = hit.get("content")
        if current.get("distance") is None and hit.get("distance") is not None:
            current["distance"] = hit.get("distance")
        source_type = str(hit.get("source_type") or "unknown")
        if source_type not in current["source_types"]:
            current["source_types"].append(source_type)

    # Compute RRF scores
    merged_hits: List[Dict[str, Any]] = []
    for key, doc in all_docs.items():
        vec_contrib = (1.0 / (K + vector_ranks[key])) if key in vector_ranks else 0.0
        text_contrib = (1.0 / (K + text_ranks[key])) if key in text_ranks else 0.0
        rrf_score = vec_contrib + text_contrib

        merged_hits.append({
            "id": doc["id"],
            "content": doc["content"],
            "metadata": doc["metadata"],
            "distance": doc["distance"],
            "score": round(rrf_score, 6),
            "vector_score": round(vec_contrib, 6),
            "text_score": round(text_contrib, 6),
            "source_type": "+".join(doc["source_types"]) or "hybrid",
        })

    merged_hits.sort(key=lambda current: float(current.get("score") or 0.0), reverse=True)
    return merged_hits


db = SearchIndexDB()
