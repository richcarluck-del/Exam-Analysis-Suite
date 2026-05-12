"""Benchmark knowledge retrieval with vector, graph expansion, and RRF fusion.

Ground truth is derived from KnowledgeQuestionLink: each query is a real
question stem and expected KP ids are the KPs linked to that question.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from shared import models
from shared.database import engine
from analyzer.app import vector_db
from analyzer.app.knowledge_point_retriever import KNOWLEDGE_ENTITY_TYPES
from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService


OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

KP_KP_REL_TYPES = {"prerequisite", "specializes", "equivalent", "related"}
KNOWLEDGE_RETRIEVAL_ENTITY_TYPES = [
    "knowledge_point",
    "knowledge_package_point",
    "knowledge_package",
    "knowledge_block",
    "knowledge_atom",
    "knowledge_derivative",
]


def _trim_text(value: str, max_chars: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def _is_valid_kp(point: models.KnowledgePoint | None) -> bool:
    if not point:
        return False
    return KnowledgePointIngestionService._is_relation_extraction_candidate(point, None)


def _build_cases(session, *, package_id: int | None, max_cases: int, min_expected: int) -> list[dict[str, Any]]:
    query = (
        session.query(
            models.QuestionItem.id,
            models.QuestionItem.stem_plain_text,
            models.KnowledgeQuestionLink.knowledge_point_id,
            models.KnowledgePackageQuestion.package_id,
        )
        .join(models.KnowledgeQuestionLink, models.KnowledgeQuestionLink.question_item_id == models.QuestionItem.id)
        .outerjoin(models.KnowledgePackageQuestion, models.KnowledgePackageQuestion.question_item_id == models.QuestionItem.id)
        .order_by(models.QuestionItem.id.asc(), models.KnowledgeQuestionLink.id.asc())
    )
    if package_id is not None:
        query = query.filter(models.KnowledgePackageQuestion.package_id == package_id)

    point_cache: dict[int, models.KnowledgePoint | None] = {}
    grouped: dict[int, dict[str, Any]] = {}
    for question_id, stem, kp_id, pkg_id in query.all():
        point_cache.setdefault(kp_id, session.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == kp_id).first())
        if not _is_valid_kp(point_cache[kp_id]):
            continue
        row = grouped.setdefault(
            int(question_id),
            {
                "question_id": int(question_id),
                "package_id": int(pkg_id) if pkg_id is not None else None,
                "query": _trim_text(stem, 260),
                "expected_kp_ids": [],
            },
        )
        if int(kp_id) not in row["expected_kp_ids"]:
            row["expected_kp_ids"].append(int(kp_id))

    cases = [
        row
        for row in grouped.values()
        if len(row["query"]) >= 12 and len(row["expected_kp_ids"]) >= min_expected
    ]
    return cases[:max_cases]


def _kp_id_from_hit(hit: dict[str, Any]) -> int | None:
    metadata = hit.get("metadata") or {}
    entity_type = str(metadata.get("entity_type") or "")
    entity_id = metadata.get("entity_id")
    kp_id = metadata.get("knowledge_point_id")
    value = kp_id if kp_id not in (None, "") else (entity_id if entity_type == "knowledge_point" else None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    compact = "".join(str(text or "").split())
    if not compact:
        return set()
    if len(compact) <= n:
        return {compact}
    return {compact[index : index + n] for index in range(len(compact) - n + 1)}


def _pg_text_ranked_kps(
    session,
    query: str,
    *,
    top_k: int,
    entity_types: list[str],
) -> tuple[list[int], list[dict[str, Any]]]:
    query_grams = _char_ngrams(query)
    if not query_grams:
        return [], []
    rows = session.query(models.RetrievalDocument).filter(models.RetrievalDocument.is_active.is_(True)).all()
    scored: dict[int, dict[str, Any]] = {}
    for row in rows:
        metadata = dict(row.metadata_json or {})
        entity_type = str(metadata.get("entity_type") or "")
        if entity_type not in entity_types:
            continue
        kp_value = metadata.get("knowledge_point_id")
        if not kp_value and entity_type == "knowledge_point":
            kp_value = row.entity_id
        try:
            kp_id = int(kp_value)
        except (TypeError, ValueError):
            continue
        doc_grams = _char_ngrams(row.text_for_embedding or row.text_for_bm25 or "")
        if not doc_grams:
            continue
        score = len(query_grams & doc_grams) / max(len(query_grams), 1)
        if score <= 0:
            continue
        current = scored.get(kp_id)
        if current is None or score > current["score"]:
            scored[kp_id] = {
                "kp_id": kp_id,
                "score": round(score, 6),
                "entity_type": entity_type,
                "title": metadata.get("title") or metadata.get("knowledge_point_name") or "",
            }
    ranked_items = sorted(scored.values(), key=lambda item: (-item["score"], item["kp_id"]))[:top_k]
    return [int(item["kp_id"]) for item in ranked_items], ranked_items


def _hybrid_ranked_kps(
    query: str,
    *,
    top_k: int,
    entity_types: list[str],
    enable_rerank: bool | None = None,
    enable_lightweight_rerank: bool | None = None,
) -> tuple[list[int], list[dict[str, Any]], dict[str, Any]]:
    probe = vector_db.db.hybrid_search_with_debug(
        query_text=query,
        n_results=max(top_k * 4, top_k),
        entity_types=entity_types,
        metadata_filters=None,
        expanded_query=None,
        enable_rerank=enable_rerank,
        enable_lightweight_rerank=enable_lightweight_rerank,
    )
    raw_results = probe.get("hits") or []
    diagnostics = probe.get("diagnostics") or {}
    ranked: list[int] = []
    snippets: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw_results:
        kp_id = _kp_id_from_hit(item)
        if kp_id is None or kp_id in seen:
            continue
        seen.add(kp_id)
        ranked.append(kp_id)
        metadata = item.get("metadata") or {}
        snippets.append(
            {
                "kp_id": kp_id,
                "score": round(float(item.get("score") or 0.0), 6),
                "entity_type": metadata.get("entity_type"),
                "title": metadata.get("title") or metadata.get("knowledge_point_name") or "",
            }
        )
        if len(ranked) >= top_k:
            break
    return ranked, snippets, diagnostics


def _recall_ranked_kps(
    session,
    query: str,
    *,
    top_k: int,
    backend: str,
    entity_types: list[str],
    enable_rerank: bool | None = None,
    enable_lightweight_rerank: bool | None = None,
) -> tuple[list[int], list[dict[str, Any]], dict[str, Any]]:
    if backend == "pg_text":
        ranked, debug = _pg_text_ranked_kps(session, query, top_k=top_k, entity_types=entity_types)
        return ranked, debug, {}
    if backend == "hybrid":
        return _hybrid_ranked_kps(
            query,
            top_k=top_k,
            entity_types=entity_types,
            enable_rerank=enable_rerank,
            enable_lightweight_rerank=enable_lightweight_rerank,
        )
    raise ValueError(f"Unsupported recall backend: {backend}")


def _graph_expand_kps(session, seed_kp_ids: list[int], *, top_k: int) -> list[int]:
    if not seed_kp_ids:
        return []
    seed_rank = {kp_id: index + 1 for index, kp_id in enumerate(seed_kp_ids)}
    rows = (
        session.query(models.EntityGraphEdge)
        .filter(
            models.EntityGraphEdge.source_entity_type == "knowledge_point",
            models.EntityGraphEdge.target_entity_type == "knowledge_point",
            models.EntityGraphEdge.relation_type.in_(KP_KP_REL_TYPES),
        )
        .filter(
            (models.EntityGraphEdge.source_entity_id.in_(seed_kp_ids))
            | (models.EntityGraphEdge.target_entity_id.in_(seed_kp_ids))
        )
        .all()
    )
    scored: dict[int, float] = defaultdict(float)
    for row in rows:
        source_id = int(row.source_entity_id)
        target_id = int(row.target_entity_id)
        if source_id in seed_rank:
            neighbor_id = target_id
            rank = seed_rank[source_id]
        elif target_id in seed_rank:
            neighbor_id = source_id
            rank = seed_rank[target_id]
        else:
            continue
        if neighbor_id in seed_rank:
            continue
        try:
            weight = float(row.weight_score or row.confidence or 0.5)
        except (TypeError, ValueError):
            weight = 0.5
        scored[neighbor_id] += weight / rank
    return [kp_id for kp_id, _ in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:top_k]]


def _rrf_fuse(vector_ranked: list[int], graph_ranked: list[int], *, top_k: int, rrf_k: int = 60) -> list[int]:
    scores: dict[int, float] = defaultdict(float)
    for rank, kp_id in enumerate(vector_ranked, start=1):
        scores[kp_id] += 1.0 / (rrf_k + rank)
    for rank, kp_id in enumerate(graph_ranked, start=1):
        scores[kp_id] += 1.0 / (rrf_k + rank)
    return [kp_id for kp_id, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]]


def _metrics(ranked: list[int], expected: set[int]) -> dict[str, float]:
    first_rank = None
    for index, kp_id in enumerate(ranked, start=1):
        if kp_id in expected:
            first_rank = index
            break
    return {
        "hit@1": 1.0 if ranked[:1] and ranked[0] in expected else 0.0,
        "hit@5": 1.0 if any(kp_id in expected for kp_id in ranked[:5]) else 0.0,
        "hit@10": 1.0 if any(kp_id in expected for kp_id in ranked[:10]) else 0.0,
        "mrr": (1.0 / first_rank) if first_rank else 0.0,
    }


def _mean_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {"hit@1": 0.0, "hit@5": 0.0, "hit@10": 0.0, "mrr": 0.0}
    keys = rows[0].keys()
    return {key: round(sum(row[key] for row in rows) / len(rows), 4) for key in keys}


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Retrieval Benchmark",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- case_count: {report['case_count']}",
        f"- top_k: {report['params']['top_k']}",
        f"- graph_seed_top_k: {report['params']['graph_seed_top_k']}",
        f"- recall_backend: {report['params']['recall_backend']}",
        "",
        "## Summary",
        "",
        "| route | hit@1 | hit@5 | hit@10 | mrr |",
        "|---|---:|---:|---:|---:|",
    ]
    for route, metrics in report["summary"].items():
        lines.append(
            f"| {route} | {metrics['hit@1']:.4f} | {metrics['hit@5']:.4f} | {metrics['hit@10']:.4f} | {metrics['mrr']:.4f} |"
        )
    lines.extend(["", "## Cases", ""])
    for item in report["cases"]:
        lines.append(
            f"- q#{item['question_id']} expected={item['expected_kp_ids']} "
            f"recall={item['metrics']['recall']} graph={item['metrics']['graph']} fusion={item['metrics']['fusion']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", type=int, default=None, help="只评估指定专题包内题目")
    ap.add_argument("--max-cases", type=int, default=30, help="最多评估多少道已桥接题")
    ap.add_argument("--min-expected", type=int, default=1, help="每道题至少需要多少个 ground-truth KP")
    ap.add_argument("--top-k", type=int, default=10, help="每条路线输出 top K KP")
    ap.add_argument("--recall-backend", choices=["pg_text", "hybrid"], default="pg_text", help="召回后端：pg_text 为快速文本基线；hybrid 使用现有向量+文本索引")
    ap.add_argument("--graph-seed-top-k", type=int, default=5, help="图谱扩展使用向量路线前 N 个 KP 作为起点")
    ap.add_argument("--disable-rerank", action="store_true", help="hybrid 召回时跳过 rerank，便于排查召回链路")
    ap.add_argument("--disable-lightweight-rerank", action="store_true", help="hybrid 召回时跳过轻量重排，便于对比")
    ap.add_argument("--exclude-bridge", action="store_true", help="评估时排除 knowledge_question_bridge，观察纯知识文档召回")
    ap.add_argument("--out", type=Path, default=None, help="输出 JSON 路径；默认写入 scripts/_out")
    args = ap.parse_args()
    entity_types = list(KNOWLEDGE_RETRIEVAL_ENTITY_TYPES)
    if not args.exclude_bridge:
        entity_types.append("knowledge_question_bridge")

    Session = sessionmaker(bind=engine)
    session = Session()
    cases = _build_cases(
        session,
        package_id=args.package_id,
        max_cases=args.max_cases,
        min_expected=args.min_expected,
    )
    if not cases:
        raise SystemExit("没有可评估 case：请先确认 KnowledgeQuestionLink 已生成。")
    print(f"Loaded cases: {len(cases)}", flush=True)

    evaluated: list[dict[str, Any]] = []
    metric_buckets: dict[str, list[dict[str, float]]] = {"recall": [], "graph": [], "fusion": []}

    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] question_id={case['question_id']}", flush=True)
        expected = set(case["expected_kp_ids"])
        recall_ranked, recall_debug, recall_diagnostics = _recall_ranked_kps(
            session,
            case["query"],
            top_k=args.top_k,
            backend=args.recall_backend,
            entity_types=entity_types,
            enable_rerank=False if args.disable_rerank else None,
            enable_lightweight_rerank=False if args.disable_lightweight_rerank else None,
        )
        graph_ranked = _graph_expand_kps(session, recall_ranked[: args.graph_seed_top_k], top_k=args.top_k)
        fusion_ranked = _rrf_fuse(recall_ranked, graph_ranked, top_k=args.top_k)

        metrics = {
            "recall": _metrics(recall_ranked, expected),
            "graph": _metrics(graph_ranked, expected),
            "fusion": _metrics(fusion_ranked, expected),
        }
        for route, route_metrics in metrics.items():
            metric_buckets[route].append(route_metrics)

        evaluated.append(
            {
                **case,
                "recall_ranked_kp_ids": recall_ranked,
                "graph_ranked_kp_ids": graph_ranked,
                "fusion_ranked_kp_ids": fusion_ranked,
                "recall_debug": recall_debug,
                "recall_diagnostics": recall_diagnostics,
                "metrics": metrics,
            }
        )

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "case_count": len(evaluated),
        "params": {
            "package_id": args.package_id,
            "max_cases": args.max_cases,
            "min_expected": args.min_expected,
            "top_k": args.top_k,
            "graph_seed_top_k": args.graph_seed_top_k,
            "recall_backend": args.recall_backend,
            "disable_rerank": args.disable_rerank,
            "disable_lightweight_rerank": args.disable_lightweight_rerank,
            "entity_types": entity_types,
        },
        "summary": {route: _mean_metrics(rows) for route, rows in metric_buckets.items()},
        "cases": evaluated,
    }

    default_name = (
        f"retrieval_benchmark_{args.recall_backend}"
        f"{'_nobridge' if args.exclude_bridge else ''}"
        f"{'_norerank' if args.disable_rerank else ''}"
        f"{'_nolight' if args.disable_lightweight_rerank else ''}"
        f"_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    )
    out_path = args.out or OUT_DIR / f"{default_name}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    _write_markdown(report, md_path)

    print("\nSummary:", flush=True)
    for route, metrics in report["summary"].items():
        print(f"  {route:<8} hit@1={metrics['hit@1']:.4f} hit@5={metrics['hit@5']:.4f} hit@10={metrics['hit@10']:.4f} mrr={metrics['mrr']:.4f}", flush=True)
    print(f"\nJSON: {out_path}", flush=True)
    print(f"MD  : {md_path}", flush=True)

    session.close()


if __name__ == "__main__":
    main()
