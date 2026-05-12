"""Repeat package KP-KP re-extraction and compare stability across runs."""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
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

from sqlalchemy import and_, or_
from sqlalchemy.orm import aliased, sessionmaker

from analyzer.app.knowledge_graph_projection import project_package
from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService
from scripts.reextract_package_kp_relations import (
    OUT_DIR,
    _delete_existing_llm_relations,
    _package_block_ids,
    _package_scoped_point_ids,
    _package_title,
    _resolve_package_ids,
)
from shared import models
from shared.database import engine


def _safe_print(message: str) -> None:
    try:
        print(message)
    except ValueError:
        try:
            fallback = getattr(sys, "__stderr__", None) or sys.stderr
            if hasattr(fallback, "buffer"):
                fallback.buffer.write((str(message) + "\n").encode("utf-8", errors="ignore"))
                fallback.flush()
            else:
                raise ValueError("no fallback buffer")
        except Exception:
            pass


def _scoped_relation_rows(session, package_id: int) -> list[dict[str, Any]]:
    point_ids = _package_scoped_point_ids(session, package_id)
    block_ids = _package_block_ids(session, package_id)
    if not point_ids and not block_ids:
        return []

    S = aliased(models.KnowledgePoint)
    T = aliased(models.KnowledgePoint)
    predicates = []
    if block_ids:
        predicates.append(
            and_(
                models.KnowledgePointRelation.source_origin == "llm",
                models.KnowledgePointRelation.evidence_block_id.in_(block_ids),
            )
        )
    if point_ids:
        predicates.append(
            and_(
                models.KnowledgePointRelation.source_origin == "llm",
                models.KnowledgePointRelation.evidence_block_id.is_(None),
                models.KnowledgePointRelation.source_knowledge_point_id.in_(point_ids),
                models.KnowledgePointRelation.target_knowledge_point_id.in_(point_ids),
            )
        )
    rows = (
        session.query(
            models.KnowledgePointRelation.id,
            S.canonical_name.label("source_name"),
            models.KnowledgePointRelation.relation_type,
            T.canonical_name.label("target_name"),
            models.KnowledgePointRelation.confidence,
            models.KnowledgePointRelation.evidence_block_id,
        )
        .join(S, S.id == models.KnowledgePointRelation.source_knowledge_point_id)
        .join(T, T.id == models.KnowledgePointRelation.target_knowledge_point_id)
        .filter(or_(*predicates))
        .order_by(models.KnowledgePointRelation.id.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "relation_id": int(row.id),
                "source": str(row.source_name or ""),
                "relation_type": str(row.relation_type or ""),
                "target": str(row.target_name or ""),
                "confidence": float(row.confidence or 0.0),
                "evidence_block_id": int(row.evidence_block_id) if row.evidence_block_id is not None else None,
            }
        )
    return out


def _relation_signature(row: dict[str, Any]) -> str:
    return (
        f"{row.get('source','')}|{row.get('relation_type','')}|"
        f"{row.get('target','')}|block={row.get('evidence_block_id')}"
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def main() -> None:
    ap = argparse.ArgumentParser(description="Repeat KP-KP extraction for one package and compare stability.")
    ap.add_argument("--package-id", type=int, action="append", help="KnowledgePackage id")
    ap.add_argument("--source-document-id", type=int, action="append", help="Resolve latest package for source document id")
    ap.add_argument("--package-title-like", action="append", help="Resolve package by unique title keyword")
    ap.add_argument("--runs", type=int, default=3, help="Number of repeat runs; default 3")
    ap.add_argument("--reproject", action="store_true", help="Reproject package graph after each run")
    args = ap.parse_args()

    session_factory = sessionmaker(bind=engine)
    service = KnowledgePointIngestionService()
    session = session_factory()
    try:
        package_ids = _resolve_package_ids(
            session,
            package_ids=args.package_id,
            source_document_ids=args.source_document_id,
            title_keywords=args.package_title_like,
        )
        if len(package_ids) != 1:
            raise SystemExit("Repeat compare supports exactly one resolved package at a time")
        package_id = int(package_ids[0])
        package_title = _package_title(session, package_id)
        run_reports: list[dict[str, Any]] = []
        signature_counter: Counter[str] = Counter()

        for run_index in range(1, max(1, args.runs) + 1):
            package = session.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == package_id).first()
            if package is None:
                raise SystemExit(f"KnowledgePackage {package_id} not found")

            purity_summary = service._reclassify_package_point_purity(session, package_id)
            session.flush()
            deleted = _delete_existing_llm_relations(session, package_id)
            package_point_links = service._refresh_package_point_links_map(session, package_id)
            summary = service._extract_kp_relations_with_llm(session, package, package_point_links)
            if (summary or {}).get("status") != "ok":
                session.rollback()
                raise RuntimeError(f"KP-KP extraction failed on run {run_index}: {summary}")
            debug_payload = summary.pop("debug_payload", None) if isinstance(summary, dict) else None
            if args.reproject:
                project_package(session, package_id, respect_flag=False)
            session.commit()

            rows = _scoped_relation_rows(session, package_id)
            signatures = [_relation_signature(row) for row in rows]
            signature_counter.update(signatures)

            debug_path = None
            if debug_payload is not None:
                debug_path = OUT_DIR / (
                    f"kp_relation_repeat_compare_debug_pkg{package_id}_run{run_index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                )
                debug_path.write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            run_reports.append(
                {
                    "run_index": run_index,
                    "package_id": package_id,
                    "package_title": package_title,
                    "purity_summary": purity_summary,
                    "deleted_existing_llm_relations": deleted,
                    "extract_summary": summary,
                    "relation_count": len(rows),
                    "relations": rows,
                    "relation_signatures": signatures,
                    "debug_artifact_path": str(debug_path) if debug_path else None,
                }
            )
            _safe_print(
                f"run={run_index} package={package_id} relations={len(rows)} "
                f"inserted={summary.get('inserted')} rejected={summary.get('rule_rejected')}"
            )

        pairwise: list[dict[str, Any]] = []
        for i in range(len(run_reports)):
            for j in range(i + 1, len(run_reports)):
                a = set(run_reports[i]["relation_signatures"])
                b = set(run_reports[j]["relation_signatures"])
                pairwise.append(
                    {
                        "run_a": run_reports[i]["run_index"],
                        "run_b": run_reports[j]["run_index"],
                        "jaccard": round(_jaccard(a, b), 4),
                        "intersection": len(a & b),
                        "union": len(a | b),
                    }
                )

        stable_threshold = len(run_reports)
        stable_relations = sorted(sig for sig, count in signature_counter.items() if count == stable_threshold)
        volatile_relations = [
            {"signature": sig, "seen_in_runs": count}
            for sig, count in signature_counter.most_common()
            if count < stable_threshold
        ]
        summary = {
            "package_id": package_id,
            "package_title": package_title,
            "runs": len(run_reports),
            "relation_count_by_run": [item["relation_count"] for item in run_reports],
            "stable_relation_count": len(stable_relations),
            "volatile_relation_count": len(volatile_relations),
            "pairwise_jaccard": pairwise,
        }
        payload = {
            "summary": summary,
            "stable_relations": stable_relations,
            "volatile_relations": volatile_relations,
            "runs": run_reports,
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUT_DIR / f"kp_relation_repeat_compare_pkg{package_id}_{ts}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _safe_print(f"JSON report: {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
