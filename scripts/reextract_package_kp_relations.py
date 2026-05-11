"""Re-extract grounded KP-KP relations for one or more packages."""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import and_, or_
from sqlalchemy.orm import sessionmaker

from analyzer.app.knowledge_graph_projection import project_package
from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService
from shared import models
from shared.database import engine


OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


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


def _package_title(session, package_id: int) -> str:
    title = (
        session.query(models.KnowledgePackage.package_title)
        .filter(models.KnowledgePackage.id == package_id)
        .scalar()
    )
    if not title:
        raise ValueError(f"KnowledgePackage {package_id} not found")
    return str(title)


def _package_point_ids(session, package_id: int) -> list[int]:
    rows = (
        session.query(models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .all()
    )
    return [int(point_id) for (point_id,) in rows if point_id is not None]


def _package_scoped_point_ids(session, package_id: int) -> list[int]:
    point_ids = set(_package_point_ids(session, package_id))
    point_ids.update(
        int(point_id)
        for (point_id,) in session.query(models.KnowledgeBlock.knowledge_point_id)
        .filter(
            models.KnowledgeBlock.package_id == package_id,
            models.KnowledgeBlock.knowledge_point_id.isnot(None),
        )
        .all()
        if point_id is not None
    )
    point_ids.update(
        int(point_id)
        for (point_id,) in session.query(models.KnowledgeAtom.knowledge_point_id)
        .filter(models.KnowledgeAtom.package_id == package_id)
        .all()
        if point_id is not None
    )
    point_ids.update(
        int(point_id)
        for (point_id,) in session.query(models.KnowledgePointProvenance.knowledge_point_id)
        .filter(models.KnowledgePointProvenance.package_id == package_id)
        .all()
        if point_id is not None
    )
    return sorted(point_ids)


def _package_block_ids(session, package_id: int) -> list[int]:
    rows = (
        session.query(models.KnowledgeBlock.id)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .all()
    )
    return [int(block_id) for (block_id,) in rows if block_id is not None]


def _scoped_llm_relation_count(session, package_id: int) -> int:
    point_ids = _package_scoped_point_ids(session, package_id)
    block_ids = _package_block_ids(session, package_id)
    if not point_ids and not block_ids:
        return 0
    predicates = []
    if block_ids:
        predicates.append(models.KnowledgePointRelation.evidence_block_id.in_(block_ids))
    if point_ids:
        predicates.append(
            and_(
                models.KnowledgePointRelation.source_origin == "llm",
                models.KnowledgePointRelation.evidence_block_id.is_(None),
                models.KnowledgePointRelation.source_knowledge_point_id.in_(point_ids),
                models.KnowledgePointRelation.target_knowledge_point_id.in_(point_ids),
            )
        )
    return int(
        session.query(models.KnowledgePointRelation)
        .filter(or_(*predicates))
        .count()
    )


def _scoped_grounded_llm_relation_count(session, package_id: int) -> int:
    block_ids = _package_block_ids(session, package_id)
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


def _delete_existing_llm_relations(session, package_id: int) -> int:
    point_ids = _package_scoped_point_ids(session, package_id)
    block_ids = _package_block_ids(session, package_id)
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
    if not predicates:
        return 0
    deleted = int(
        session.query(models.KnowledgePointRelation)
        .filter(or_(*predicates))
        .delete(synchronize_session=False)
        or 0
    )
    session.flush()
    return deleted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", type=int, action="append", help="KnowledgePackage id")
    ap.add_argument("--source-document-id", type=int, action="append", help="Resolve latest package for source_documents.id")
    ap.add_argument("--package-title-like", action="append", help="Resolve package by unique title keyword")
    ap.add_argument("--delete-existing-llm", action="store_true", help="Delete package-scoped LLM KP-KP relations before re-extract")
    ap.add_argument("--reproject", action="store_true", help="Reproject package graph after re-extract")
    args = ap.parse_args()

    session_factory = sessionmaker(bind=engine)
    service = KnowledgePointIngestionService()
    session = session_factory()
    results: list[dict] = []
    try:
        package_ids = _resolve_package_ids(
            session,
            package_ids=args.package_id,
            source_document_ids=args.source_document_id,
            title_keywords=args.package_title_like,
        )
        print(f"resolved_packages={package_ids}")
        for package_id in package_ids:
            title = _package_title(session, package_id)
            package = session.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == package_id).first()
            before_total = _scoped_llm_relation_count(session, package_id)
            before_grounded = _scoped_grounded_llm_relation_count(session, package_id)
            deleted = 0
            purity_summary = service._reclassify_package_point_purity(session, package_id)
            session.flush()
            if args.delete_existing_llm:
                deleted = _delete_existing_llm_relations(session, package_id)

            package_point_links = service._refresh_package_point_links_map(session, package_id)
            summary = service._extract_kp_relations_with_llm(session, package, package_point_links)
            if (summary or {}).get("status") != "ok":
                session.rollback()
                raise RuntimeError(f"KP-KP re-extract failed for package {package_id}: {summary}")
            reprojection = None
            if args.reproject:
                reprojection = project_package(session, package_id, respect_flag=False)
            session.commit()

            after_total = _scoped_llm_relation_count(session, package_id)
            after_grounded = _scoped_grounded_llm_relation_count(session, package_id)
            row = {
                "package_id": package_id,
                "package_title": title,
                "before_total_scoped_llm_relations": before_total,
                "before_grounded_scoped_llm_relations": before_grounded,
                "purity_summary": purity_summary,
                "deleted_existing_llm_relations": deleted,
                "extract_summary": summary,
                "reprojection": reprojection,
                "after_total_scoped_llm_relations": after_total,
                "after_grounded_scoped_llm_relations": after_grounded,
            }
            results.append(row)
            print(
                f"package={package_id} title={title}\n"
                f"  before_total={before_total} before_grounded={before_grounded}\n"
                f"  purity_summary={purity_summary}\n"
                f"  deleted_existing={deleted}\n"
                f"  extract_summary={summary}\n"
                f"  after_total={after_total} after_grounded={after_grounded}\n"
            )
            if reprojection is not None:
                print(f"  reprojection={reprojection}\n")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUT_DIR / f"reextract_package_kp_relations_{ts}.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
