"""清洗 entity_graph_edges 的"悬空"边：source/target 指向已不存在的实体。

  这些是历史脏数据——之前 sync_package_projection 做 MERGE 但没有 garbage collect。
  本脚本在单事务里把所有"两端有任一端找不到底层实体"的边删掉。

  默认 dry-run；--apply 才真删。
"""
from __future__ import annotations

import argparse
import io
import os
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

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# entity_type → 真实表名/主键列；任何 EGE 行只要一端无法 LEFT JOIN 上就是悬空
SOURCE_TABLES = {
    "knowledge_point": ("knowledge_points", "id"),
    "knowledge_package": ("knowledge_packages", "id"),
    "knowledge_block": ("knowledge_blocks", "id"),
    "knowledge_atom": ("knowledge_atoms", "id"),
    "knowledge_derivative": ("knowledge_derivatives", "id"),
    "question_item": ("question_items", "id"),
    "exam_session": ("exam_sessions", "id"),
    "student": (None, None),  # 没有专门表，跳过校验（视为活）
    "mistake_pattern": ("mistake_patterns", "id"),
    "strategy_card": ("strategy_cards", "id"),
}


def build_dangling_clause(side: str) -> str:
    """side ∈ {'source','target'}; 生成 EGE.<side>_entity_(type|id) 与 N 张表 LEFT JOIN 的过滤。

    一个 EGE 行被判定悬空：side_entity_type ∈ 已知类型 且 该类型对应表里查不到该 id。
    student 类型缺表，认为始终活。
    """
    et = f"{side}_entity_type"
    eid = f"{side}_entity_id"
    parts: list[str] = []
    for kind, (table, pk) in SOURCE_TABLES.items():
        if table is None:
            continue
        parts.append(
            f"({et} = '{kind}' AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.{pk} = ege.{eid}))"
        )
    return "(" + " OR ".join(parts) + ")"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真删（默认仅 dry-run）")
    ap.add_argument("--rollback-log", type=Path, default=None, help="rollback JSONL 路径")
    args = ap.parse_args()
    dry = not args.apply

    src_clause = build_dangling_clause("source")
    tgt_clause = build_dangling_clause("target")
    where = f"({src_clause} OR {tgt_clause})"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rb_path = args.rollback_log or (ROOT / "scripts" / "_out" / f"ege_dangling_rollback_{ts}.jsonl")
    rb_path.parent.mkdir(parents=True, exist_ok=True)

    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM entity_graph_edges ege WHERE {where}")).scalar()
        print(f"悬空 EGE 边总数：{total}")
        breakdown = conn.execute(
            text(
                f"""
                SELECT relation_type, source_entity_type, target_entity_type, COUNT(*) AS n
                FROM entity_graph_edges ege
                WHERE {where}
                GROUP BY relation_type, source_entity_type, target_entity_type
                ORDER BY n DESC
                LIMIT 20
                """,
            ),
        ).all()
        print("\n[Top 20 分布]")
        for r in breakdown:
            print(f"  {r[0]:<24} {r[1]:>20} → {r[2]:<20} {r[3]:>6}")

    if dry or total == 0:
        if total == 0:
            print("\n（无悬空边，无需操作）")
        else:
            print("\n（dry-run：未删；加 --apply 真删）")
        return

    import json

    print("\n开始删除（单事务）…")
    with engine.begin() as conn:
        snapshot_ids = list(
            conn.execute(text(f"SELECT id FROM entity_graph_edges ege WHERE {where}")).scalars().all(),
        )
        print(f"  待删 EGE id 数：{len(snapshot_ids)}")
        # 写 rollback 快照（id 列表 + 关键字段）
        snap_rows = (
            conn.execute(
                text(
                    f"""
                    SELECT id, source_entity_type, source_entity_id,
                           target_entity_type, target_entity_id,
                           relation_type, weight_score::float AS weight,
                           confidence::float AS confidence, source_origin
                    FROM entity_graph_edges ege WHERE {where}
                    """,
                ),
            )
            .mappings()
            .all()
        )
        with rb_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"undo_hint": "reinsert_entity_graph_edges_dangling", "rows": [dict(x) for x in snap_rows]},
                    ensure_ascii=False,
                    default=str,
                )
                + "\n",
            )

        deleted = conn.execute(text(f"DELETE FROM entity_graph_edges ege WHERE {where}")).rowcount
        print(f"  实删行数：{deleted}")

    print(f"\nRollback 日志：{rb_path}")
    print("--- DONE ---")


if __name__ == "__main__":
    main()
