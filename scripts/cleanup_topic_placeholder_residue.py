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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", type=int, action="append")
    ap.add_argument("--source-document-id", type=int, action="append")
    ap.add_argument("--package-title-like", action="append")
    ap.add_argument("--apply", action="store_true", help="执行写库；默认 dry-run 回滚")
    ap.add_argument("--reproject", action="store_true", help="apply 时顺带重投影 package 图谱")
    args = ap.parse_args()

    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    service = KnowledgePointIngestionService()
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
            title = (
                session.query(models.KnowledgePackage.package_title)
                .filter(models.KnowledgePackage.id == package_id)
                .scalar()
            ) or ""
            summary = service.reconcile_topic_placeholder_residue(session, package_id)
            reprojection = None
            if args.apply and args.reproject:
                reprojection = project_package(session, package_id, respect_flag=False)
            results.append(
                {
                    "package_id": package_id,
                    "package_title": str(title),
                    "summary": summary,
                    "reprojection": reprojection,
                }
            )
            print(f"package={package_id} title={title}\n  summary={summary}")
            if reprojection is not None:
                print(f"  reprojection={reprojection}")

        if args.apply:
            session.commit()
        else:
            session.rollback()

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUT_DIR / f"cleanup_topic_placeholder_residue_{stamp}.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {out_path}")
        if not args.apply:
            print("dry-run only: add --apply to persist changes")
    finally:
        session.close()


if __name__ == "__main__":
    main()
