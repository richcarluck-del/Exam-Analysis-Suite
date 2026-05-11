from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker

from shared import models
from analyzer.app.package_point_purity import reclassify_package_point_purity
from shared.database import engine


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", type=int, action="append")
    parser.add_argument("--source-document-id", type=int, action="append")
    parser.add_argument("--package-title-like", action="append")
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        package_ids = _resolve_package_ids(
            session,
            package_ids=args.package_id,
            source_document_ids=args.source_document_id,
            title_keywords=args.package_title_like,
        )
        print(f"resolved_packages={package_ids}")
        for package_id in package_ids:
            hashes: list[str] = []
            summaries: list[dict] = []
            for _ in range(max(1, args.rounds)):
                result = reclassify_package_point_purity(session, package_id, apply=False)
                summaries.append(
                    {
                        "package_id": result["package_id"],
                        "core": result["core"],
                        "adjacent": result["adjacent"],
                        "dependency": result["dependency"],
                        "changed": result["changed"],
                        "reason_counts": result["reason_counts"],
                        "rows": result["rows"],
                    }
                )
                hashes.append(_stable_hash(summaries[-1]))
                session.rollback()
            stable = len(set(hashes)) == 1
            print(
                f"package={package_id} stable={stable} rounds={len(hashes)} "
                f"hashes={hashes}"
            )
            if not stable:
                raise SystemExit(f"purity regression unstable for package {package_id}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
