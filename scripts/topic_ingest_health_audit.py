"""Audit topic ingestion health across PG retrieval and graph projection.

The script is read-only. It is meant to be run after each topic ingestion batch
before treating the topic graph as report-ready.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
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

from dotenv import load_dotenv
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, sessionmaker

load_dotenv(ROOT / ".env")

from shared import models
from sqlalchemy import create_engine


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

KNOWLEDGE_DOC_TYPES = {
    "knowledge_package",
    "knowledge_point",
    "knowledge_package_point",
    "knowledge_block",
    "knowledge_atom",
    "knowledge_question_bridge",
    "knowledge_derivative",
}

MAIN_ENTITY_MODELS = {
    "knowledge_package": models.KnowledgePackage,
    "knowledge_point": models.KnowledgePoint,
    "knowledge_block": models.KnowledgeBlock,
    "knowledge_atom": models.KnowledgeAtom,
    "question_item": models.QuestionItem,
}


@dataclass
class Thresholds:
    min_points: int = 3
    min_questions: int = 5
    min_question_link_coverage: float = 0.75
    min_retrieval_docs: int = 1
    max_pending_ratio: float = 0.20


@dataclass
class PackageAudit:
    package_id: int
    title: str
    parse_status: str | None
    review_status: str | None
    counts: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, dict[str, int]] = field(default_factory=dict)
    retrieval_docs_by_type: dict[str, int] = field(default_factory=dict)
    embedding_points: int = 0
    graph_edges_by_pattern: dict[str, int] = field(default_factory=dict)
    graph_degree: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _status_counts(rows: list[Any], field_name: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        value = getattr(row, field_name, None)
        counter[str(value or "NULL")] += 1
    return dict(sorted(counter.items()))


def _ratio(part: int, whole: int) -> float:
    return float(part) / float(whole) if whole else 0.0


def _as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _package_id_from_doc(doc: models.RetrievalDocument) -> int | None:
    metadata = dict(doc.metadata_json or {})
    package_id = _as_int(metadata.get("package_id"))
    if package_id is not None:
        return package_id
    if doc.entity_type == "knowledge_package":
        return int(doc.entity_id)
    return None


def _knowledge_doc_predicate():
    return or_(
        models.RetrievalDocument.entity_type.in_(sorted(KNOWLEDGE_DOC_TYPES)),
        models.RetrievalDocument.metadata_json["entity_type"].as_string().in_(sorted(KNOWLEDGE_DOC_TYPES)),
    )


def _knowledge_docs_for_package(db: Session, package_id: int) -> list[models.RetrievalDocument]:
    docs = (
        db.query(models.RetrievalDocument)
        .filter(models.RetrievalDocument.is_active.is_(True))
        .filter(_knowledge_doc_predicate())
        .all()
    )
    return [doc for doc in docs if _package_id_from_doc(doc) == package_id]


def _edge_pattern(edge: models.EntityGraphEdge) -> str:
    return (
        f"{edge.source_entity_type}-[{edge.relation_type}]->"
        f"{edge.target_entity_type}"
    )


def _package_edges(
    db: Session,
    package_id: int,
    point_ids: set[int],
    question_ids: set[int],
    block_ids: set[int],
    atom_ids: set[int],
) -> list[models.EntityGraphEdge]:
    predicates = [
        and_(
            models.EntityGraphEdge.source_entity_type == "knowledge_package",
            models.EntityGraphEdge.source_entity_id == package_id,
        )
    ]
    if point_ids:
        predicates.append(
            and_(
                models.EntityGraphEdge.source_entity_type == "knowledge_point",
                models.EntityGraphEdge.source_entity_id.in_(list(point_ids)),
                models.EntityGraphEdge.target_entity_type == "knowledge_point",
                models.EntityGraphEdge.target_entity_id.in_(list(point_ids)),
            )
        )
    if point_ids and question_ids:
        predicates.extend(
            [
                and_(
                    models.EntityGraphEdge.source_entity_type == "knowledge_point",
                    models.EntityGraphEdge.source_entity_id.in_(list(point_ids)),
                    models.EntityGraphEdge.target_entity_type == "question_item",
                    models.EntityGraphEdge.target_entity_id.in_(list(question_ids)),
                ),
                and_(
                    models.EntityGraphEdge.source_entity_type == "question_item",
                    models.EntityGraphEdge.source_entity_id.in_(list(question_ids)),
                    models.EntityGraphEdge.target_entity_type == "knowledge_point",
                    models.EntityGraphEdge.target_entity_id.in_(list(point_ids)),
                ),
            ]
        )
    if point_ids and block_ids:
        predicates.append(
            and_(
                models.EntityGraphEdge.source_entity_type == "knowledge_point",
                models.EntityGraphEdge.source_entity_id.in_(list(point_ids)),
                models.EntityGraphEdge.target_entity_type == "knowledge_block",
                models.EntityGraphEdge.target_entity_id.in_(list(block_ids)),
            )
        )
    if point_ids and atom_ids:
        predicates.append(
            and_(
                models.EntityGraphEdge.source_entity_type == "knowledge_point",
                models.EntityGraphEdge.source_entity_id.in_(list(point_ids)),
                models.EntityGraphEdge.target_entity_type == "knowledge_atom",
                models.EntityGraphEdge.target_entity_id.in_(list(atom_ids)),
            )
        )
    return db.query(models.EntityGraphEdge).filter(or_(*predicates)).all()


def _dangling_edge_counts(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity_type, model in MAIN_ENTITY_MODELS.items():
        source_ids = {
            int(row[0])
            for row in db.query(models.EntityGraphEdge.source_entity_id)
            .filter(models.EntityGraphEdge.source_entity_type == entity_type)
            .distinct()
            .all()
        }
        target_ids = {
            int(row[0])
            for row in db.query(models.EntityGraphEdge.target_entity_id)
            .filter(models.EntityGraphEdge.target_entity_type == entity_type)
            .distinct()
            .all()
        }
        edge_ids = source_ids | target_ids
        if not edge_ids:
            counts[entity_type] = 0
            continue
        alive_ids = {
            int(row[0])
            for row in db.query(model.id)
            .filter(model.id.in_(list(edge_ids)))
            .all()
        }
        counts[entity_type] = len(edge_ids - alive_ids)
    return counts


def _audit_package(db: Session, package: models.KnowledgePackage, thresholds: Thresholds) -> PackageAudit:
    package_id = int(package.id)
    package_points = (
        db.query(models.KnowledgePackagePoint)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .all()
    )
    point_ids = {int(row.knowledge_point_id) for row in package_points if row.knowledge_point_id is not None}
    blocks = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .all()
    )
    atoms = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.package_id == package_id)
        .all()
    )
    package_questions = (
        db.query(models.KnowledgePackageQuestion)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .all()
    )
    question_ids = {
        int(row.question_item_id)
        for row in package_questions
        if row.question_item_id is not None
    }
    question_links = []
    if question_ids:
        question_links = (
            db.query(models.KnowledgeQuestionLink)
            .filter(models.KnowledgeQuestionLink.question_item_id.in_(list(question_ids)))
            .all()
        )
    block_ids = {int(row.id) for row in blocks}
    kp_relations = []
    if point_ids:
        kp_relations = (
            db.query(models.KnowledgePointRelation)
            .filter(models.KnowledgePointRelation.source_knowledge_point_id.in_(list(point_ids)))
            .filter(models.KnowledgePointRelation.target_knowledge_point_id.in_(list(point_ids)))
            .all()
        )

    docs = _knowledge_docs_for_package(db, package_id)
    doc_ids = [int(doc.id) for doc in docs]
    embedding_points = 0
    if doc_ids:
        embedding_points = (
            db.query(models.EmbeddingPoint)
            .filter(models.EmbeddingPoint.retrieval_document_id.in_(doc_ids))
            .count()
        )

    atom_ids = {int(row.id) for row in atoms}
    edges = _package_edges(db, package_id, point_ids, question_ids, block_ids, atom_ids)
    edge_patterns = Counter(_edge_pattern(edge) for edge in edges)

    linked_question_ids = {int(row.question_item_id) for row in question_links if row.question_item_id is not None}
    linked_point_ids = {int(row.knowledge_point_id) for row in question_links if row.knowledge_point_id is not None}
    kp_kp_edges = [
        edge
        for edge in edges
        if edge.source_entity_type == "knowledge_point" and edge.target_entity_type == "knowledge_point"
    ]
    kp_edge_degree: Counter[int] = Counter()
    for edge in kp_kp_edges:
        kp_edge_degree[int(edge.source_entity_id)] += 1
        kp_edge_degree[int(edge.target_entity_id)] += 1

    no_question_link_points = sorted(point_ids - linked_point_ids)
    no_kp_relation_points = sorted(pid for pid in point_ids if kp_edge_degree[pid] == 0)
    question_link_coverage = _ratio(len(linked_question_ids & question_ids), len(question_ids))

    audit = PackageAudit(
        package_id=package_id,
        title=package.package_title,
        parse_status=package.parse_status,
        review_status=package.review_status,
        counts={
            "points": len(point_ids),
            "blocks": len(blocks),
            "atoms": len(atoms),
            "questions": len(question_ids),
            "question_links": len(question_links),
            "kp_relations": len(kp_relations),
            "graph_edges": len(edges),
            "retrieval_docs": len(docs),
        },
        statuses={
            "package_points": _status_counts(package_points, "approved_status"),
            "package_questions": _status_counts(package_questions, "approved_status"),
            "question_links": _status_counts(question_links, "approved_status"),
            "kp_relations": _status_counts(kp_relations, "approved_status"),
            "atoms": _status_counts(atoms, "review_status"),
        },
        retrieval_docs_by_type=dict(sorted(Counter(doc.entity_type for doc in docs).items())),
        embedding_points=int(embedding_points),
        graph_edges_by_pattern=dict(sorted(edge_patterns.items())),
        graph_degree={
            "question_link_coverage": round(question_link_coverage, 4),
            "kp_kp_edges": len(kp_kp_edges),
            "points_without_question_links": no_question_link_points,
            "points_without_kp_relations": no_kp_relation_points,
        },
    )

    if package.parse_status != "success":
        audit.warnings.append(f"package parse_status={package.parse_status}")
    if package.review_status != "published":
        audit.warnings.append(f"package review_status={package.review_status}; not production-approved")
    if len(point_ids) < thresholds.min_points:
        audit.warnings.append(f"low point count: {len(point_ids)} < {thresholds.min_points}")
    if len(question_ids) < thresholds.min_questions:
        audit.warnings.append(f"low question count: {len(question_ids)} < {thresholds.min_questions}")
    if question_ids and question_link_coverage < thresholds.min_question_link_coverage:
        audit.warnings.append(
            f"low question-link coverage: {question_link_coverage:.1%} < "
            f"{thresholds.min_question_link_coverage:.1%}"
        )
    if len(docs) < thresholds.min_retrieval_docs:
        audit.warnings.append("missing active knowledge retrieval docs")
    if doc_ids and embedding_points < len(docs):
        audit.warnings.append(f"embedding coverage gap: {embedding_points}/{len(docs)}")
    if point_ids and len(kp_kp_edges) == 0:
        audit.warnings.append("no projected KP-KP graph edges for package points")
    if no_question_link_points:
        audit.warnings.append(f"{len(no_question_link_points)} package points have no question links")
    if no_kp_relation_points:
        audit.warnings.append(f"{len(no_kp_relation_points)} package points have no KP-KP relation edge")

    pending_tables = {
        "package_points": package_points,
        "package_questions": package_questions,
        "question_links": question_links,
        "kp_relations": kp_relations,
    }
    for table_name, rows in pending_tables.items():
        if not rows:
            continue
        pending = sum(1 for row in rows if (getattr(row, "approved_status", "") or "").lower() == "pending")
        pending_ratio = _ratio(pending, len(rows))
        if pending_ratio > thresholds.max_pending_ratio:
            audit.warnings.append(
                f"{table_name} pending ratio {pending_ratio:.1%} > {thresholds.max_pending_ratio:.1%}"
            )
    return audit


def _print_summary(audits: list[PackageAudit], dangling_counts: dict[str, int]) -> None:
    print("\n[Topic ingest health]")
    print(f"packages={len(audits)}")
    print(f"dangling_edge_entity_ids={json.dumps(dangling_counts, ensure_ascii=False, sort_keys=True)}")
    for item in audits:
        status = "OK" if not item.warnings else "WARN"
        counts = item.counts
        print(
            f"\npackage_id={item.package_id} {status} "
            f"points={counts['points']} blocks={counts['blocks']} atoms={counts['atoms']} "
            f"questions={counts['questions']} qlinks={counts['question_links']} "
            f"kp_rels={counts['kp_relations']} edges={counts['graph_edges']} "
            f"retrieval_docs={counts['retrieval_docs']} embeddings={item.embedding_points} "
            f"title={item.title}"
        )
        print(f"  package={item.parse_status}/{item.review_status}")
        print(f"  statuses={json.dumps(item.statuses, ensure_ascii=False, sort_keys=True)}")
        print(f"  retrieval_by_type={json.dumps(item.retrieval_docs_by_type, ensure_ascii=False, sort_keys=True)}")
        print(f"  graph_degree={json.dumps(item.graph_degree, ensure_ascii=False, sort_keys=True)}")
        if item.warnings:
            for warning in item.warnings:
                print(f"  ! {warning}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only topic ingestion health audit")
    ap.add_argument("--package-id", type=int, action="append", help="Only audit selected package id; repeatable")
    ap.add_argument("--json-out", default=None, help="Optional JSON output path")
    ap.add_argument("--min-question-link-coverage", type=float, default=0.75)
    ap.add_argument("--max-pending-ratio", type=float, default=0.20)
    args = ap.parse_args()

    thresholds = Thresholds(
        min_question_link_coverage=args.min_question_link_coverage,
        max_pending_ratio=args.max_pending_ratio,
    )

    db = SessionLocal()
    try:
        query = db.query(models.KnowledgePackage).order_by(models.KnowledgePackage.id.asc())
        if args.package_id:
            query = query.filter(models.KnowledgePackage.id.in_(args.package_id))
        packages = query.all()
        audits = [_audit_package(db, package, thresholds) for package in packages]
        dangling_counts = _dangling_edge_counts(db)
        _print_summary(audits, dangling_counts)

        payload = {
            "package_count": len(audits),
            "dangling_edge_entity_ids": dangling_counts,
            "packages": [
                {
                    "package_id": item.package_id,
                    "title": item.title,
                    "parse_status": item.parse_status,
                    "review_status": item.review_status,
                    "counts": item.counts,
                    "statuses": item.statuses,
                    "retrieval_docs_by_type": item.retrieval_docs_by_type,
                    "embedding_points": item.embedding_points,
                    "graph_edges_by_pattern": item.graph_edges_by_pattern,
                    "graph_degree": item.graph_degree,
                    "warnings": item.warnings,
                }
                for item in audits
            ],
        }
        if args.json_out:
            out_path = Path(args.json_out)
            if not out_path.is_absolute():
                out_path = ROOT / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\njson_out={out_path}")
        return 1 if any(item.warnings for item in audits) or any(dangling_counts.values()) else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
