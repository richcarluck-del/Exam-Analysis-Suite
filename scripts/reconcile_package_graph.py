"""Rebuild entity_graph_edges for one or more knowledge packages."""

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

from sqlalchemy import or_
from sqlalchemy.orm import sessionmaker

from analyzer.app.knowledge_graph_projection import project_package
from shared import models
from shared.database import engine


OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

COVERAGE_RELATION_TYPES = {"core", "adjacent"}


def _coverage_point_ids(session, package_id: int) -> list[int]:
    rows = (
        session.query(models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .filter(models.KnowledgePackagePoint.relation_type.in_(sorted(COVERAGE_RELATION_TYPES)))
        .all()
    )
    return [int(point_id) for (point_id,) in rows if point_id is not None]


def _kp_kp_edge_count_touching_coverage(session, package_id: int) -> int:
    point_ids = _coverage_point_ids(session, package_id)
    if not point_ids:
        return 0
    return int(
        session.query(models.EntityGraphEdge)
        .filter(models.EntityGraphEdge.source_entity_type == "knowledge_point")
        .filter(models.EntityGraphEdge.target_entity_type == "knowledge_point")
        .filter(
            or_(
                models.EntityGraphEdge.source_entity_id.in_(point_ids),
                models.EntityGraphEdge.target_entity_id.in_(point_ids),
            )
        )
        .count()
    )


def _package_title(session, package_id: int) -> str:
    title = (
        session.query(models.KnowledgePackage.package_title)
        .filter(models.KnowledgePackage.id == package_id)
        .scalar()
    )
    if not title:
        raise ValueError(f"KnowledgePackage {package_id} not found")
    return str(title)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", type=int, action="append", required=True, help="KnowledgePackage id")
    ap.add_argument(
        "--respect-flag",
        action="store_true",
        help="Respect KNOWLEDGE_GRAPH_ENABLED. Default is to force maintenance reconcile.",
    )
    args = ap.parse_args()

    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    results: list[dict] = []
    try:
        for package_id in args.package_id:
            title = _package_title(session, package_id)
            before_kp_kp = _kp_kp_edge_count_touching_coverage(session, package_id)
            result = project_package(session, package_id, respect_flag=args.respect_flag)
            after_kp_kp = _kp_kp_edge_count_touching_coverage(session, package_id)
            row = {
                "package_id": package_id,
                "package_title": title,
                "before_kp_kp_edges_touching_coverage": before_kp_kp,
                "after_kp_kp_edges_touching_coverage": after_kp_kp,
                **result,
            }
            results.append(row)
            print(
                f"package={package_id} title={title}\n"
                f"  before_kp_kp_edges_touching_coverage={before_kp_kp}\n"
                f"  after_kp_kp_edges_touching_coverage={after_kp_kp}\n"
                f"  deleted={result.get('deleted')} inserted={result.get('inserted')} edge_count={result.get('edge_count')}\n"
            )

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUT_DIR / f"reconcile_package_graph_{ts}.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
