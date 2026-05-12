"""
按主键上限批量删除知识点（id < max_exclusive），复用 delete_knowledge_point 级联逻辑。

用法（在仓库根目录）:
  python scripts/bulk_delete_knowledge_points_by_max_id.py --max-exclusive 1825 --execute

不加 --execute 时只打印将删除的条数与 ID 范围，不写库。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.database import SessionLocal  # noqa: E402
from shared import models  # noqa: E402
from analyzer.app.knowledge_point_service import delete_knowledge_point  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="删除 id < max_exclusive 的所有知识点")
    p.add_argument(
        "--max-exclusive",
        type=int,
        required=True,
        help="只删除主键严格小于该值的知识点（例如 1825 表示删除 id<=1824）",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="确认执行删除；省略则仅统计",
    )
    args = p.parse_args()
    max_exc = int(args.max_exclusive)

    list_session = SessionLocal()
    try:
        rows = (
            list_session.query(models.KnowledgePoint.id)
            .filter(models.KnowledgePoint.id < max_exc)
            .order_by(models.KnowledgePoint.id.asc())
            .all()
        )
        ids = [r[0] for r in rows]
    finally:
        list_session.close()

    n = len(ids)
    if n == 0:
        print(f"没有 id < {max_exc} 的知识点，无需处理。")
        return 0
    print(f"将处理 {n} 条知识点：id 自 {ids[0]} 至 {ids[-1]}（均 < {max_exc}）。")
    if not args.execute:
        print("未加 --execute，未修改数据库。加上 --execute 后执行删除。")
        return 0

    ok = 0
    failed: list[tuple[int, str]] = []
    for kid in ids:
        session = SessionLocal()
        try:
            if delete_knowledge_point(session, kid):
                ok += 1
            if ok % 50 == 0:
                print(f"  已删除 {ok}/{n} …")
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            failed.append((kid, str(exc)))
            print(f"  [失败] id={kid}: {exc}")
        finally:
            session.close()

    print(f"完成：成功 {ok}，失败 {len(failed)}。")
    if failed:
        for kid, msg in failed[:20]:
            print(f"  id={kid}: {msg}")
        if len(failed) > 20:
            print(f"  … 另有 {len(failed) - 20} 条失败未列出")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
