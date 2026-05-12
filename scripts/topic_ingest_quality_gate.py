from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

def _ensure_utf8_stdio() -> None:
    try:
        base_stdout = getattr(sys, "__stdout__", None) or sys.stdout
        base_stderr = getattr(sys, "__stderr__", None) or sys.stderr
        if getattr(sys.stdout, "encoding", None) != "utf-8" and hasattr(base_stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(base_stdout.buffer, encoding="utf-8")
        if getattr(sys.stderr, "encoding", None) != "utf-8" and hasattr(base_stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(base_stderr.buffer, encoding="utf-8")
    except Exception:
        pass


_ensure_utf8_stdio()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import sessionmaker

from analyzer.app.graph_db import db as neo4j_db
from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService
from analyzer.app.package_point_purity import reclassify_package_point_purity
from scripts.kp_relations_package_audit import _audit_package as audit_kp_relations
from scripts.topic_ingest_health_audit import Thresholds, _audit_package as audit_topic_health
from shared import models
from shared.database import engine


OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class GateThresholds:
    min_question_link_coverage: float = 0.95
    min_questions: int = 5
    min_points: int = 3
    min_grounded_llm_kp_relations: int = 1
    min_retrieval_docs: int = 1
    require_full_embeddings: bool = True
    max_placeholder_package_points: int = 0
    max_placeholder_blocks: int = 0
    max_placeholder_atoms: int = 0
    max_placeholder_provenance: int = 0
    max_projectable_unprojected_relations: int = 0
    min_neo4j_relationships: int = 1


def _stable_hash(payload: object) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _resolve_package_ids(
    session,
    package_ids: list[int] | None,
    source_document_ids: list[int] | None,
    title_keywords: list[str] | None,
) -> list[int]:
    resolved: list[int] = []

    for package_id in package_ids or []:
        exists = (
            session.query(models.KnowledgePackage.id)
            .filter(models.KnowledgePackage.id == package_id)
            .scalar()
        )
        if not exists:
            raise SystemExit(f"KnowledgePackage {package_id} not found")
        resolved.append(int(package_id))

    for source_document_id in source_document_ids or []:
        rows = (
            session.query(models.KnowledgePackage.id)
            .filter(models.KnowledgePackage.source_document_id == source_document_id)
            .order_by(models.KnowledgePackage.id.desc())
            .all()
        )
        if not rows:
            raise SystemExit(f"No KnowledgePackage found for source_document_id={source_document_id}")
        resolved.append(int(rows[0][0]))

    for keyword in title_keywords or []:
        rows = (
            session.query(models.KnowledgePackage.id, models.KnowledgePackage.package_title)
            .filter(models.KnowledgePackage.package_title.ilike(f"%{keyword}%"))
            .order_by(models.KnowledgePackage.id.desc())
            .all()
        )
        if not rows:
            raise SystemExit(f"No KnowledgePackage title matched keyword={keyword!r}")
        if len(rows) > 1:
            pairs = ", ".join(f"{pid}:{title}" for pid, title in rows[:8])
            raise SystemExit(
                f"Keyword {keyword!r} matched multiple packages; refine it or pass --package-id explicitly: {pairs}"
            )
        resolved.append(int(rows[0][0]))

    deduped: list[int] = []
    seen: set[int] = set()
    for package_id in resolved:
        if package_id not in seen:
            deduped.append(package_id)
            seen.add(package_id)
    if not deduped:
        raise SystemExit("Provide at least one of --package-id, --source-document-id, or --package-title-like")
    return deduped


def _placeholder_residue_summary(session, package_id: int, service: KnowledgePointIngestionService) -> dict[str, int]:
    package_point_rows = (
        session.query(models.KnowledgePackagePoint.id, models.KnowledgePoint.canonical_name)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .all()
    )
    placeholder_package_points = [
        int(row[0])
        for row in package_point_rows
        if service._is_placeholder_point_name(row[1])
    ]

    placeholder_blocks = (
        session.query(models.KnowledgeBlock.id, models.KnowledgePoint.canonical_name)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgeBlock.knowledge_point_id)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .all()
    )
    placeholder_atoms = (
        session.query(models.KnowledgeAtom.id, models.KnowledgePoint.canonical_name)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgeAtom.knowledge_point_id)
        .filter(models.KnowledgeAtom.package_id == package_id)
        .all()
    )
    placeholder_provenance = (
        session.query(models.KnowledgePointProvenance.id, models.KnowledgePoint.canonical_name)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePointProvenance.knowledge_point_id)
        .filter(models.KnowledgePointProvenance.package_id == package_id)
        .all()
    )

    return {
        "package_points": len(placeholder_package_points),
        "blocks": sum(1 for _, name in placeholder_blocks if service._is_placeholder_point_name(name)),
        "atoms": sum(1 for _, name in placeholder_atoms if service._is_placeholder_point_name(name)),
        "provenance": sum(1 for _, name in placeholder_provenance if service._is_placeholder_point_name(name)),
    }


def _grounded_llm_relation_count(session, package_id: int) -> int:
    block_ids = [
        int(block_id)
        for (block_id,) in session.query(models.KnowledgeBlock.id)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .all()
        if block_id is not None
    ]
    if not block_ids:
        return 0
    return int(
        session.query(models.KnowledgePointRelation)
        .filter(
            models.KnowledgePointRelation.source_origin == "llm",
            models.KnowledgePointRelation.evidence_block_id.in_(block_ids),
        )
        .count()
    )


def _purity_stability(session, package_id: int) -> dict[str, Any]:
    hashes: list[str] = []
    runs: list[dict[str, Any]] = []
    for _ in range(2):
        result = reclassify_package_point_purity(session, package_id, apply=False)
        payload = {
            "core": result["core"],
            "adjacent": result["adjacent"],
            "dependency": result["dependency"],
            "placeholder": result.get("placeholder", 0),
            "changed": result["changed"],
            "reason_counts": result["reason_counts"],
            "rows": result["rows"],
        }
        runs.append(payload)
        hashes.append(_stable_hash(payload))
        session.rollback()
    return {
        "stable": len(set(hashes)) == 1,
        "hashes": hashes,
        "summary": runs[0],
    }


def _neo4j_projection_summary(package_id: int) -> dict[str, Any]:
    package_key = f"knowledge_package:{package_id}"
    try:
        package_rows = neo4j_db.run_query(
            "MATCH (n {entity_key: $entity_key}) RETURN count(n) AS count",
            {"entity_key": package_key},
        )
        rel_rows = neo4j_db.run_query(
            "MATCH (n {entity_key: $entity_key})-[r]-() RETURN count(r) AS count",
            {"entity_key": package_key},
        )
        node_count = int(package_rows[0]["count"]) if package_rows else 0
        relationship_count = int(rel_rows[0]["count"]) if rel_rows else 0
        return {
            "status": "ok",
            "package_node_exists": node_count > 0,
            "package_node_count": node_count,
            "relationship_count": relationship_count,
        }
    except Exception as exc:
        return {
            "status": "error",
            "reason": str(exc),
            "package_node_exists": False,
            "package_node_count": 0,
            "relationship_count": 0,
        }


def _package_failures(
    *,
    package_id: int,
    title: str,
    health: Any,
    purity: dict[str, Any],
    placeholder_residue: dict[str, int],
    grounded_llm_relations: int,
    relation_audit: dict[str, Any],
    neo4j_projection: dict[str, Any],
    thresholds: GateThresholds,
) -> list[str]:
    failures: list[str] = []

    if (health.parse_status or "") != "success":
        failures.append(f"parse_status={health.parse_status}")
    if health.counts.get("points", 0) < thresholds.min_points:
        failures.append(f"points {health.counts.get('points', 0)} < {thresholds.min_points}")
    if health.counts.get("questions", 0) < thresholds.min_questions:
        failures.append(f"questions {health.counts.get('questions', 0)} < {thresholds.min_questions}")

    coverage = float(health.graph_degree.get("question_link_coverage", 0.0) or 0.0)
    if health.counts.get("questions", 0) > 0 and coverage < thresholds.min_question_link_coverage:
        failures.append(
            f"question_link_coverage {coverage:.1%} < {thresholds.min_question_link_coverage:.1%}"
        )

    retrieval_docs = int(health.counts.get("retrieval_docs", 0) or 0)
    if retrieval_docs < thresholds.min_retrieval_docs:
        failures.append(f"retrieval_docs {retrieval_docs} < {thresholds.min_retrieval_docs}")
    if thresholds.require_full_embeddings and retrieval_docs > 0 and int(health.embedding_points) < retrieval_docs:
        failures.append(f"embedding_points {health.embedding_points} < retrieval_docs {retrieval_docs}")

    if not purity["stable"]:
        failures.append("package_point_purity unstable across 2 runs")

    if placeholder_residue["package_points"] > thresholds.max_placeholder_package_points:
        failures.append(
            f"placeholder package_points {placeholder_residue['package_points']} > {thresholds.max_placeholder_package_points}"
        )
    if placeholder_residue["blocks"] > thresholds.max_placeholder_blocks:
        failures.append(f"placeholder blocks {placeholder_residue['blocks']} > {thresholds.max_placeholder_blocks}")
    if placeholder_residue["atoms"] > thresholds.max_placeholder_atoms:
        failures.append(f"placeholder atoms {placeholder_residue['atoms']} > {thresholds.max_placeholder_atoms}")
    if placeholder_residue["provenance"] > thresholds.max_placeholder_provenance:
        failures.append(
            f"placeholder provenance {placeholder_residue['provenance']} > {thresholds.max_placeholder_provenance}"
        )

    if grounded_llm_relations < thresholds.min_grounded_llm_kp_relations:
        failures.append(
            f"grounded_llm_kp_relations {grounded_llm_relations} < {thresholds.min_grounded_llm_kp_relations}"
        )

    projectable = int(relation_audit["summary"].get("projectable", 0) or 0)
    projected = int(relation_audit["summary"].get("projected", 0) or 0)
    unprojected = max(projectable - projected, 0)
    if unprojected > thresholds.max_projectable_unprojected_relations:
        failures.append(
            f"projectable_unprojected_relations {unprojected} > {thresholds.max_projectable_unprojected_relations}"
        )

    if neo4j_projection.get("status") != "ok":
        failures.append(f"neo4j_projection status={neo4j_projection.get('status')} reason={neo4j_projection.get('reason')}")
    else:
        if not neo4j_projection.get("package_node_exists"):
            failures.append("neo4j_package_node_missing")
        if int(neo4j_projection.get("relationship_count", 0) or 0) < thresholds.min_neo4j_relationships:
            failures.append(
                f"neo4j_relationship_count {neo4j_projection.get('relationship_count', 0)} < {thresholds.min_neo4j_relationships}"
            )

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="Pass/fail gate for topic package ingestion quality")
    ap.add_argument("--package-id", type=int, action="append")
    ap.add_argument("--source-document-id", type=int, action="append")
    ap.add_argument("--package-title-like", action="append")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--min-question-link-coverage", type=float, default=0.95)
    ap.add_argument("--min-grounded-llm-kp-relations", type=int, default=1)
    ap.add_argument("--min-retrieval-docs", type=int, default=1)
    ap.add_argument("--min-questions", type=int, default=5)
    ap.add_argument("--min-points", type=int, default=3)
    ap.add_argument("--min-neo4j-relationships", type=int, default=1)
    ap.add_argument("--allow-embedding-gap", action="store_true")
    args = ap.parse_args()

    thresholds = GateThresholds(
        min_question_link_coverage=args.min_question_link_coverage,
        min_grounded_llm_kp_relations=args.min_grounded_llm_kp_relations,
        min_retrieval_docs=args.min_retrieval_docs,
        min_questions=args.min_questions,
        min_points=args.min_points,
        min_neo4j_relationships=args.min_neo4j_relationships,
        require_full_embeddings=not args.allow_embedding_gap,
    )

    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    service = KnowledgePointIngestionService()
    try:
        package_ids = _resolve_package_ids(
            session,
            package_ids=args.package_id,
            source_document_ids=args.source_document_id,
            title_keywords=args.package_title_like,
        )

        payload_packages: list[dict[str, Any]] = []
        any_failures = False
        for package_id in package_ids:
            package = (
                session.query(models.KnowledgePackage)
                .filter(models.KnowledgePackage.id == package_id)
                .first()
            )
            if not package:
                raise SystemExit(f"KnowledgePackage {package_id} not found")

            health = audit_topic_health(
                session,
                package,
                Thresholds(
                    min_points=thresholds.min_points,
                    min_questions=thresholds.min_questions,
                    min_question_link_coverage=thresholds.min_question_link_coverage,
                    min_retrieval_docs=thresholds.min_retrieval_docs,
                    max_pending_ratio=1.0,
                ),
            )
            purity = _purity_stability(session, package_id)
            placeholder_residue = _placeholder_residue_summary(session, package_id, service)
            grounded_llm_relations = _grounded_llm_relation_count(session, package_id)
            relation_audit = audit_kp_relations(session, package_id)
            neo4j_projection = _neo4j_projection_summary(package_id)
            failures = _package_failures(
                package_id=package_id,
                title=str(package.package_title or ""),
                health=health,
                purity=purity,
                placeholder_residue=placeholder_residue,
                grounded_llm_relations=grounded_llm_relations,
                relation_audit=relation_audit,
                neo4j_projection=neo4j_projection,
                thresholds=thresholds,
            )
            any_failures = any_failures or bool(failures)
            row = {
                "package_id": package_id,
                "package_title": package.package_title,
                "failures": failures,
                "health_counts": dict(health.counts),
                "health_graph_degree": dict(health.graph_degree),
                "retrieval_docs_by_type": dict(health.retrieval_docs_by_type),
                "embedding_points": int(health.embedding_points),
                "purity_stability": purity,
                "placeholder_residue": placeholder_residue,
                "grounded_llm_kp_relations": grounded_llm_relations,
                "relation_audit_summary": dict(relation_audit["summary"]),
                "neo4j_projection": neo4j_projection,
            }
            payload_packages.append(row)

            status = "PASS" if not failures else "FAIL"
            print(
                f"package={package_id} {status} "
                f"points={health.counts.get('points', 0)} "
                f"questions={health.counts.get('questions', 0)} "
                f"question_link_coverage={health.graph_degree.get('question_link_coverage', 0.0)} "
                f"retrieval_docs={health.counts.get('retrieval_docs', 0)} "
                f"embeddings={health.embedding_points} "
                f"grounded_llm_kp_relations={grounded_llm_relations} "
                f"neo4j_relationships={neo4j_projection.get('relationship_count', 0)} "
                f"title={package.package_title}"
            )
            print(
                f"  purity=stable:{purity['stable']} "
                f"core={purity['summary']['core']} adjacent={purity['summary']['adjacent']} "
                f"dependency={purity['summary']['dependency']} placeholder={purity['summary'].get('placeholder', 0)}"
            )
            print(f"  placeholder_residue={placeholder_residue}")
            print(f"  relation_summary={relation_audit['summary']}")
            print(f"  neo4j_projection={neo4j_projection}")
            if failures:
                for failure in failures:
                    print(f"  ! {failure}")

        payload = {
            "thresholds": asdict(thresholds),
            "package_count": len(payload_packages),
            "packages": payload_packages,
        }

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(args.json_out) if args.json_out else (OUT_DIR / f"topic_ingest_quality_gate_{stamp}.json")
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {out_path}")
        return 1 if any_failures else 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
