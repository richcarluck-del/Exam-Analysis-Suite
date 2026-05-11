import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import vector_db
from .graph_db import db as graph_db
from shared.database import SessionLocal
from shared.prompt_step_config import resolve_step_prompt

logger = logging.getLogger(__name__)


LLMCaller = Callable[[List[Dict[str, str]], Dict[str, str], bool], Optional[str]]


def fallback_extract_keywords(query: str, limit: int = 6) -> List[str]:
    if not query:
        return []

    tokens = re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", query)
    keywords: List[str] = []
    seen = set()

    for token in tokens:
        normalized = token.strip()
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        keywords.append(normalized)
        if len(keywords) >= limit:
            break

    if not keywords:
        return [query.strip()]
    return keywords


def extract_keywords(
    query: str,
    llm_config: Optional[Dict[str, str]] = None,
    llm_caller: Optional[LLMCaller] = None,
    fallback_terms: Optional[Sequence[str]] = None,
    limit: int = 6,
) -> List[str]:
    keywords: List[str] = []

    if llm_config and llm_caller:
        prompt_text = None
        db = SessionLocal()
        try:
            prompt_config = resolve_step_prompt(
                db,
                "analyzer.retrieval_keyword_extraction",
                variables={"query": query},
            )
            prompt_text = prompt_config.get("prompt_text") if prompt_config else None
        finally:
            db.close()

        messages = [{"role": "user", "content": prompt_text or query}]

        try:
            llm_response = llm_caller(messages, llm_config, json_mode=True)
            payload = json.loads(llm_response or "{}")
            for item in payload.get("keywords", []):
                if isinstance(item, str) and item.strip():
                    keywords.append(item.strip())
        except Exception as exc:
            logger.warning("LLM keyword extraction failed, falling back to regex tokens: %s", exc)

    if not keywords:
        keywords = fallback_extract_keywords(query, limit=limit)

    if fallback_terms:
        existing = {item.lower() for item in keywords}
        for term in fallback_terms:
            if not isinstance(term, str):
                continue
            normalized = term.strip()
            if not normalized or normalized.lower() in existing:
                continue
            existing.add(normalized.lower())
            keywords.append(normalized)
            if len(keywords) >= limit:
                break

    return keywords[:limit]


def _truncate(text: str, max_length: int = 240) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3] + "..."


def _term_overlap_score(terms: Sequence[str], text: str) -> float:
    if not terms or not text:
        return 0.0

    lowered_text = text.lower()
    matched = 0
    for term in terms:
        if term and term.lower() in lowered_text:
            matched += 1

    return round(matched / max(len(terms), 1), 6)


def _normalize_hybrid_results(query: str, results: List[Dict[str, Any]], query_terms: Sequence[str]) -> List[Dict[str, Any]]:
    """Normalize RRF-merged hybrid_search_with_scores results for the retriever merge stage.

    Results already have: id, content, metadata, score (RRF), vector_score, text_score, source_type.
    We add keyword overlap bonus so graph results can compete fairly in _dedupe_and_rerank.
    """
    normalized: List[Dict[str, Any]] = []

    for index, item in enumerate(results, start=1):
        content = item.get("content") or ""
        metadata = item.get("metadata") or {}
        rrf_score = float(item.get("score") or 0.0)
        lexical_score = _term_overlap_score(query_terms, content)
        final_score = round((rrf_score * 0.7) + (lexical_score * 0.3), 6)

        normalized.append(
            {
                "rank": index,
                "source_type": item.get("source_type") or "vector+text",
                "source_id": item.get("id") or metadata.get("source") or f"hybrid-{index}",
                "score": final_score,
                "semantic_score": float(item.get("vector_score") or 0.0),
                "lexical_score": lexical_score,
                "vector_score": float(item.get("vector_score") or 0.0),
                "text_score": float(item.get("text_score") or 0.0),
                "content": content,
                "snippet": _truncate(content),
                "metadata": metadata,
                "citation": metadata.get("source") or item.get("id") or "unknown",
                "query": query,
            }
        )

    return normalized


def _build_graph_summary(path_nodes: Sequence[Dict[str, Any]], path_relationships: Sequence[Dict[str, Any]]) -> str:
    if not path_nodes:
        return ""

    if not path_relationships:
        return (path_nodes[0].get("name") or "")

    pieces: List[str] = []
    for relation in path_relationships:
        source_name = relation.get("from") or "?"
        relation_type = relation.get("type") or "RELATED_TO"
        target_name = relation.get("to") or "?"
        pieces.append(f"{source_name} -[{relation_type}]-> {target_name}")
    return " | ".join(pieces)


def _normalize_graph_results(query: str, results: List[Dict[str, Any]], query_terms: Sequence[str]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []

    for index, item in enumerate(results, start=1):
        path_nodes = item.get("path_nodes") or []
        path_relationships = item.get("path_relationships") or []
        root = item.get("root") or {}
        entity_names = [node.get("name") for node in path_nodes if node.get("name")]
        node_contexts = [node.get("context") for node in path_nodes if node.get("context")]
        summary = _build_graph_summary(path_nodes, path_relationships)
        content = "\n".join(filter(None, [summary] + node_contexts))
        graph_score = float(item.get("score") or 0.0)
        lexical_score = _term_overlap_score(query_terms, " ".join(entity_names + [content]))
        final_score = round((graph_score * 0.65) + (lexical_score * 0.35), 6)

        normalized.append(
            {
                "rank": index,
                "source_type": "graph",
                "source_id": f"graph-{index}-{root.get('name', 'entity')}",
                "score": final_score,
                "semantic_score": graph_score,
                "lexical_score": lexical_score,
                "content": content,
                "snippet": _truncate(content or summary or root.get("name", "")),
                "metadata": {
                    "keyword": item.get("keyword"),
                    "root": root,
                    "entities": entity_names,
                    "depth": item.get("depth"),
                },
                "citation": summary or root.get("name") or "graph-path",
                "path_summary": summary,
                "path_nodes": path_nodes,
                "path_relationships": path_relationships,
                "query": query,
            }
        )

    return normalized


def _dedupe_and_rerank(items: Sequence[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()

    for item in sorted(items, key=lambda current: current.get("score", 0.0), reverse=True):
        dedupe_key = (
            item.get("source_type"),
            item.get("snippet") or item.get("content") or item.get("citation"),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item)
        if len(deduped) >= top_k:
            break

    for rank, item in enumerate(deduped, start=1):
        item["rank"] = rank
    return deduped


def build_hybrid_context(results: Sequence[Dict[str, Any]], max_items: int = 5) -> str:
    if not results:
        return ""

    lines = ["基于知识库检索得到以下证据："]
    for item in list(results)[:max_items]:
        prefix = "图谱" if item.get("source_type") == "graph" else "向量"
        lines.append(
            f"[{prefix}#{item.get('rank')}] score={item.get('score', 0):.3f} source={item.get('citation')}"
        )
        snippet = item.get("snippet") or item.get("content") or ""
        if snippet:
            lines.append(f"- {snippet}")
    return "\n".join(lines)


def hybrid_search(
    query: str,
    top_k: int = 5,
    llm_config: Optional[Dict[str, str]] = None,
    llm_caller: Optional[LLMCaller] = None,
    fallback_terms: Optional[Sequence[str]] = None,
    graph_depth: int = 2,
) -> Dict[str, Any]:
    warnings: List[str] = []
    keywords = extract_keywords(
        query,
        llm_config=llm_config,
        llm_caller=llm_caller,
        fallback_terms=fallback_terms,
    )

    raw_vector_results: List[Dict[str, Any]] = []
    raw_graph_results: List[Dict[str, Any]] = []

    expanded_query = query
    if keywords:
        expanded_query = query + " " + " ".join(keywords)
    try:
        raw_hybrid_results = vector_db.db.hybrid_search_with_scores(
            query, n_results=max(top_k * 3, 8), expanded_query=expanded_query
        )
    except Exception as exc:
        warnings.append(f"混合检索不可用: {exc}")
        logger.warning("Hybrid retrieval failed: %s", exc)

    try:
        entity_index = getattr(vector_db.db, "entity_index", None)
        if entity_index is not None:
            entity_matches = entity_index.search(query, top_k=max(top_k * 2, 6))
            if entity_matches:
                raw_graph_results = graph_db.search_graph_semantic(
                    entity_matches, max_depth=graph_depth, limit=max(top_k * 3, 8)
                )
            else:
                raw_graph_results = []
        else:
            raw_graph_results = graph_db.search_graph(keywords, max_depth=graph_depth, limit=max(top_k * 3, 8))
    except Exception as exc:
        warnings.append(f"图谱检索不可用: {exc}")
        logger.warning("Graph retrieval failed: %s", exc)

    normalized_hybrid_results = _normalize_hybrid_results(query, raw_hybrid_results, keywords)
    normalized_graph_results = _normalize_graph_results(query, raw_graph_results, keywords)
    merged_results = _dedupe_and_rerank(
        [*normalized_hybrid_results, *normalized_graph_results],
        top_k=top_k,
    )

    return {
        "query": query,
        "keywords": keywords,
        "hybrid_results": normalized_hybrid_results,
        "graph_results": normalized_graph_results,
        "merged_results": merged_results,
        "context": build_hybrid_context(merged_results, max_items=top_k),
        "warnings": warnings,
    }
