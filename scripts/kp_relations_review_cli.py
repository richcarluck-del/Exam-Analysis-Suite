"""Review pending KP-KP relations.

Interactive mode lists recent pending relations and lets the reviewer approve,
reject, or skip each one. Bulk mode is useful for trusted seed data, e.g.:

  python scripts/kp_relations_review_cli.py --bulk-source-origin cold_start --to-status approved --apply
"""

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

from sqlalchemy.orm import aliased, sessionmaker

from shared import models
from shared.database import engine


OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _query_relations(session, *, status: str, source_origin: str | None, limit: int):
    src = aliased(models.KnowledgePoint)
    tgt = aliased(models.KnowledgePoint)
    query = (
        session.query(models.KnowledgePointRelation, src.canonical_name, tgt.canonical_name)
        .join(src, src.id == models.KnowledgePointRelation.source_knowledge_point_id)
        .join(tgt, tgt.id == models.KnowledgePointRelation.target_knowledge_point_id)
        .filter(models.KnowledgePointRelation.approved_status == status)
        .order_by(models.KnowledgePointRelation.id.asc())
    )
    if source_origin:
        query = query.filter(models.KnowledgePointRelation.source_origin == source_origin)
    if limit:
        query = query.limit(limit)
    return query.all()


def _write_rollback(rows: list[models.KnowledgePointRelation], rollback_path: Path) -> None:
    with rollback_path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(
                json.dumps(
                    {
                        "ts": datetime.now().isoformat(),
                        "undo_hint": "restore_knowledge_point_relation_status",
                        "relation_id": int(row.id),
                        "approved_status": row.approved_status,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _print_relation(index: int, total: int, rel: models.KnowledgePointRelation, src_name: str, tgt_name: str) -> None:
    print(
        f"\n[{index}/{total}] #{rel.id} "
        f"{src_name} -[{rel.relation_type}]-> {tgt_name} "
        f"strength={rel.strength_score} conf={rel.confidence} "
        f"origin={rel.source_origin} status={rel.approved_status}"
    )


def _bulk_update(session, *, source_origin: str, from_status: str, to_status: str, apply: bool) -> int:
    rows = (
        session.query(models.KnowledgePointRelation)
        .filter(
            models.KnowledgePointRelation.source_origin == source_origin,
            models.KnowledgePointRelation.approved_status == from_status,
        )
        .order_by(models.KnowledgePointRelation.id.asc())
        .all()
    )
    print(f"匹配关系：{len(rows)} 条 source_origin={source_origin!r} {from_status!r} -> {to_status!r}")
    if not rows:
        return 0
    if not apply:
        print("dry-run：未写库；加 --apply 真写。")
        return 0

    rollback_path = OUT_DIR / f"kp_relations_review_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    _write_rollback(rows, rollback_path)
    for row in rows:
        row.approved_status = to_status
    session.commit()
    print(f"已更新：{len(rows)} 条")
    print(f"Rollback 日志：{rollback_path}")
    return len(rows)


def _interactive_review(session, *, status: str, source_origin: str | None, limit: int) -> None:
    rows = _query_relations(session, status=status, source_origin=source_origin, limit=limit)
    print(f"待审核关系：{len(rows)} 条")
    if not rows:
        return

    desired_status_by_id: dict[int, str] = {}
    for index, (rel, src_name, tgt_name) in enumerate(rows, start=1):
        _print_relation(index, len(rows), rel, src_name, tgt_name)
        action = input("[a]pprove / [r]eject / [s]kip / [q]uit: ").strip().lower()
        if action in {"q", "quit"}:
            break
        if action in {"a", "approve"}:
            desired_status_by_id[int(rel.id)] = "approved"
        elif action in {"r", "reject"}:
            desired_status_by_id[int(rel.id)] = "rejected"
        else:
            continue

    if not desired_status_by_id:
        print("无状态变更。")
        session.rollback()
        return

    rollback_path = OUT_DIR / f"kp_relations_review_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    rows_to_update = (
        session.query(models.KnowledgePointRelation)
        .filter(models.KnowledgePointRelation.id.in_(desired_status_by_id.keys()))
        .all()
    )
    _write_rollback(rows_to_update, rollback_path)
    for row in rows_to_update:
        row.approved_status = desired_status_by_id[int(row.id)]
    session.commit()
    print(f"已提交状态变更：{len(rows_to_update)} 条")
    print(f"Rollback 日志：{rollback_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="pending", help="交互审核时筛选的状态，默认 pending")
    ap.add_argument("--source-origin", default=None, help="交互审核时筛选 source_origin")
    ap.add_argument("--limit", type=int, default=20, help="交互审核最大条数，0 表示不限")
    ap.add_argument("--bulk-source-origin", default=None, help="批量更新某个 source_origin 的关系")
    ap.add_argument("--from-status", default="pending", help="批量更新的原状态")
    ap.add_argument("--to-status", choices=["approved", "rejected", "pending"], default="approved", help="批量更新的目标状态")
    ap.add_argument("--apply", action="store_true", help="批量模式提交写库；无此参数为 dry-run")
    args = ap.parse_args()

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        if args.bulk_source_origin:
            _bulk_update(
                session,
                source_origin=args.bulk_source_origin,
                from_status=args.from_status,
                to_status=args.to_status,
                apply=args.apply,
            )
        else:
            _interactive_review(
                session,
                status=args.status,
                source_origin=args.source_origin,
                limit=args.limit,
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()
