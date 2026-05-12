"""KP 清洗前/后关键指标快照与对比。

  采集：python scripts/kp_cleanup_compare.py snapshot --tag before
        python scripts/kp_cleanup_compare.py snapshot --tag after
  对比：python scripts/kp_cleanup_compare.py diff
"""
from __future__ import annotations

import argparse
import io
import json
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

OUT = ROOT / "scripts" / "_out"
OUT.mkdir(parents=True, exist_ok=True)


def snapshot(tag: str) -> Path:
    eng = create_engine(DATABASE_URL, pool_pre_ping=True)
    metrics: dict = {"tag": tag, "ts": datetime.now().isoformat(), "pg": {}, "neo4j": {}}
    with eng.begin() as conn:
        m = metrics["pg"]
        m["knowledge_points"] = conn.execute(text("SELECT COUNT(*) FROM knowledge_points")).scalar()
        m["knowledge_points_in_active_pkg"] = conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT kp.id) FROM knowledge_points kp
                JOIN knowledge_package_points pp ON pp.knowledge_point_id = kp.id
                """,
            ),
        ).scalar()
        m["knowledge_points_orphan"] = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM knowledge_points kp
                WHERE NOT EXISTS (SELECT 1 FROM knowledge_package_points pp WHERE pp.knowledge_point_id = kp.id)
                """,
            ),
        ).scalar()
        m["knowledge_blocks"] = conn.execute(text("SELECT COUNT(*) FROM knowledge_blocks")).scalar()
        m["knowledge_atoms"] = conn.execute(text("SELECT COUNT(*) FROM knowledge_atoms")).scalar()
        m["knowledge_question_links"] = conn.execute(text("SELECT COUNT(*) FROM knowledge_question_links")).scalar()
        m["knowledge_package_points"] = conn.execute(text("SELECT COUNT(*) FROM knowledge_package_points")).scalar()
        m["entity_graph_edges"] = conn.execute(text("SELECT COUNT(*) FROM entity_graph_edges")).scalar()
        m["ege_relates_strong"] = conn.execute(
            text("SELECT COUNT(*) FROM entity_graph_edges WHERE relation_type='relates_strong'"),
        ).scalar()
        m["ege_dangling_kp_source"] = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM entity_graph_edges ege
                WHERE ege.source_entity_type='knowledge_point'
                  AND NOT EXISTS (SELECT 1 FROM knowledge_points p WHERE p.id = ege.source_entity_id)
                """,
            ),
        ).scalar()
        m["ege_dangling_kp_target"] = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM entity_graph_edges ege
                WHERE ege.target_entity_type='knowledge_point'
                  AND NOT EXISTS (SELECT 1 FROM knowledge_points p WHERE p.id = ege.target_entity_id)
                """,
            ),
        ).scalar()
        m["ege_dangling_question_target"] = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM entity_graph_edges ege
                WHERE ege.target_entity_type='question_item'
                  AND NOT EXISTS (SELECT 1 FROM question_items q WHERE q.id = ege.target_entity_id)
                """,
            ),
        ).scalar()
        m["retrieval_documents_kp_related"] = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM retrieval_documents
                WHERE entity_type IN ('knowledge_point','knowledge_block','knowledge_atom',
                                      'knowledge_question_bridge','knowledge_package')
                """,
            ),
        ).scalar()
        m["embedding_points"] = conn.execute(text("SELECT COUNT(*) FROM embedding_points")).scalar()
        m["distinct_kp_referenced_by_kql"] = conn.execute(
            text("SELECT COUNT(DISTINCT knowledge_point_id) FROM knowledge_question_links"),
        ).scalar()

    try:
        from analyzer.app.graph_db import db as graph_db

        rows = graph_db.run_query("MATCH (k:KnowledgePoint) RETURN count(k) AS n") or [{"n": 0}]
        metrics["neo4j"]["KnowledgePoint_count"] = int(rows[0].get("n") or 0)
        rows = graph_db.run_query("MATCH (q:Question) RETURN count(q) AS n") or [{"n": 0}]
        metrics["neo4j"]["Question_count"] = int(rows[0].get("n") or 0)
        rows = (
            graph_db.run_query("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n ORDER BY n DESC")
            or []
        )
        metrics["neo4j"]["rel_types"] = {r["t"]: int(r["n"]) for r in rows}
        rows = (
            graph_db.run_query(
                """
                MATCH (k:KnowledgePoint)
                WHERE k.entity_id IS NOT NULL
                RETURN collect(k.entity_id) AS ids LIMIT 1
                """,
            )
            or [{"ids": []}]
        )
        ids = list(rows[0].get("ids") or [])
        metrics["neo4j"]["distinct_kp_entity_ids"] = len(set(int(x) for x in ids if x is not None))
    except Exception as exc:
        metrics["neo4j"]["error"] = str(exc)

    path = OUT / f"kp_cleanup_metrics_{tag}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)
    print(f"[snapshot:{tag}] → {path}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return path


def diff() -> None:
    before = OUT / "kp_cleanup_metrics_before.json"
    after = OUT / "kp_cleanup_metrics_after.json"
    if not (before.exists() and after.exists()):
        sys.exit("缺少 before/after 快照，请先用 snapshot --tag before|after 采集")
    a = json.loads(before.read_text(encoding="utf-8"))
    b = json.loads(after.read_text(encoding="utf-8"))

    def fmt(x):
        return f"{x:>12}" if isinstance(x, (int, float)) else f"{x!s:>12}"

    keys = sorted(set(list(a["pg"].keys()) + list(b["pg"].keys())))
    print("PG 指标")
    print(f"{'metric':<40} {'before':>12} {'after':>12} {'Δ':>12}")
    print("-" * 80)
    for k in keys:
        av = a["pg"].get(k)
        bv = b["pg"].get(k)
        diff_v = (bv - av) if isinstance(av, int) and isinstance(bv, int) else ""
        print(f"{k:<40} {fmt(av)} {fmt(bv)} {fmt(diff_v)}")

    print()
    nkeys = sorted(
        set(list(a.get("neo4j", {}).keys()) + list(b.get("neo4j", {}).keys())) - {"rel_types", "error"},
    )
    print("Neo4j 指标")
    print(f"{'metric':<40} {'before':>12} {'after':>12} {'Δ':>12}")
    print("-" * 80)
    for k in nkeys:
        av = a.get("neo4j", {}).get(k)
        bv = b.get("neo4j", {}).get(k)
        diff_v = (bv - av) if isinstance(av, int) and isinstance(bv, int) else ""
        print(f"{k:<40} {fmt(av)} {fmt(bv)} {fmt(diff_v)}")

    rel_a = a.get("neo4j", {}).get("rel_types", {}) or {}
    rel_b = b.get("neo4j", {}).get("rel_types", {}) or {}
    rkeys = sorted(set(list(rel_a.keys()) + list(rel_b.keys())))
    print("\nNeo4j 关系类型")
    print(f"{'rel_type':<40} {'before':>12} {'after':>12} {'Δ':>12}")
    print("-" * 80)
    for k in rkeys:
        av = rel_a.get(k, 0)
        bv = rel_b.get(k, 0)
        print(f"{k:<40} {fmt(av)} {fmt(bv)} {fmt(bv - av)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("snapshot")
    sp.add_argument("--tag", required=True, choices=["before", "after"])
    sub.add_parser("diff")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        snapshot(args.tag)
    elif args.cmd == "diff":
        diff()


if __name__ == "__main__":
    main()
