"""Smoke test for ingest-time KP-KP LLM relation extraction.

Default is dry-run: relations are flushed by the ingestion service and then
rolled back. Use --apply to commit the newly extracted relations.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from shared import models
from shared.database import engine
from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService


load_dotenv(ROOT / ".env")


def _pick_package_id(session, requested_id: int | None, min_points: int) -> int:
    if requested_id is not None:
        return int(requested_id)

    row = (
        session.query(
            models.KnowledgePackagePoint.package_id,
            func.count(models.KnowledgePackagePoint.knowledge_point_id).label("kp_count"),
        )
        .group_by(models.KnowledgePackagePoint.package_id)
        .having(func.count(models.KnowledgePackagePoint.knowledge_point_id) >= min_points)
        .order_by(models.KnowledgePackagePoint.package_id.desc())
        .first()
    )
    if not row:
        raise SystemExit(f"未找到知识点数 >= {min_points} 的 KnowledgePackage")
    return int(row.package_id)


def _load_package_links(
    session,
    package_id: int,
    limit: int | None,
    *,
    include_placeholders: bool,
) -> dict[int, models.KnowledgePackagePoint]:
    query = (
        session.query(models.KnowledgePackagePoint)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .order_by(models.KnowledgePackagePoint.order_in_package.asc().nullslast(), models.KnowledgePackagePoint.id.asc())
    )
    rows = query.all()
    result: dict[int, models.KnowledgePackagePoint] = {}
    service = KnowledgePointIngestionService()
    for row in rows:
        point = session.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == row.knowledge_point_id).first()
        if not point:
            continue
        if not include_placeholders and not service._is_relation_extraction_candidate(point, row):
            continue
        result[int(row.knowledge_point_id)] = row
        if limit and len(result) >= limit:
            break
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", type=int, default=None, help="指定要测试的 KnowledgePackage id；默认取最近的可用包")
    ap.add_argument("--min-points", type=int, default=2, help="自动选包时要求的最少 KP 数")
    ap.add_argument("--limit", type=int, default=12, help="只取包内前 N 个 KP 发给 LLM；0 表示全量")
    ap.add_argument("--include-placeholders", action="store_true", help="包含未归类/llm_pending 等占位 KP；默认过滤")
    ap.add_argument("--apply", action="store_true", help="提交 LLM 新增关系；默认回滚")
    args = ap.parse_args()

    Session = sessionmaker(bind=engine)
    session = Session()
    package_id = _pick_package_id(session, args.package_id, args.min_points)
    package = session.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == package_id).first()
    if not package:
        raise SystemExit(f"KnowledgePackage {package_id} 不存在")

    links = _load_package_links(
        session,
        package_id,
        None if args.limit == 0 else args.limit,
        include_placeholders=args.include_placeholders,
    )
    if len(links) < 2:
        raise SystemExit(f"package_id={package_id} 有效 KP 数不足 2 个")

    print(f"Smoke package_id={package_id} title={package.package_title!r} kp_count={len(links)}")

    messages: list[str] = []

    def notify(message: str) -> None:
        messages.append(message)
        print(message)

    service = KnowledgePointIngestionService()
    try:
        summary = service._extract_kp_relations_with_llm(
            session,
            package,
            links,
            progress_callback=notify,
        )
        if args.apply:
            session.commit()
            action = "committed"
        else:
            session.rollback()
            action = "rolled_back"
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(f"\nsummary={summary}")
    print(f"action={action}")


if __name__ == "__main__":
    main()
