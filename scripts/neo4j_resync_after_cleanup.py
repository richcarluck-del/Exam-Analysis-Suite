"""KP 清洗后的 Neo4j 同步：

  1) 把 Neo4j 中 entity_id 已不存在于 PG knowledge_points 的 KnowledgePoint 节点 DETACH DELETE。
  2) 把 Neo4j 中 entity_id 已不存在于 PG question_items 的 Question 节点 DETACH DELETE。
  3) 调 academic_graph_service.sync_all_knowledge_projection 把幸存 KP 的关系投影写回 Neo4j。

只读+受控写。失败抛错。
"""
from __future__ import annotations

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

load_dotenv(ROOT / ".env")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from analyzer.app import academic_graph_service as ags
from analyzer.app.graph_db import db as graph_db

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
db = Session()


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# 1. 收集 PG 现存 id
section("1. 抓取 PG 中仍存在的 KnowledgePoint / Question id 集合")
alive_kp_ids = {int(r[0]) for r in db.execute(text("SELECT id FROM knowledge_points")).all()}
alive_q_ids = {int(r[0]) for r in db.execute(text("SELECT id FROM question_items")).all()}
print(f"  knowledge_points = {len(alive_kp_ids)}")
print(f"  question_items = {len(alive_q_ids)}")

# 2. Neo4j 中 KP / Question 节点
section("2. 找出 Neo4j 中需 DETACH DELETE 的孤儿节点")
kp_neo_rows = (
    graph_db.run_query("MATCH (k:KnowledgePoint) RETURN coalesce(k.entity_id, -1) AS eid") or []
)
kp_neo_ids = [int(r["eid"]) for r in kp_neo_rows if r.get("eid") not in (None, "")]
kp_to_drop = sorted(set(kp_neo_ids) - alive_kp_ids)
print(f"  Neo4j KnowledgePoint 节点数 = {len(kp_neo_ids)}")
print(f"  其中 entity_id 已不在 PG = {len(kp_to_drop)} 条")
if kp_to_drop:
    print(f"  示例 IDs：{kp_to_drop[:10]}{' ...' if len(kp_to_drop) > 10 else ''}")

q_neo_rows = graph_db.run_query("MATCH (q:Question) RETURN coalesce(q.entity_id, -1) AS eid") or []
q_neo_ids = [int(r["eid"]) for r in q_neo_rows if r.get("eid") not in (None, "")]
q_to_drop = sorted(set(q_neo_ids) - alive_q_ids)
print(f"  Neo4j Question 节点数 = {len(q_neo_ids)}")
print(f"  其中 entity_id 已不在 PG = {len(q_to_drop)} 条")

# 3. DETACH DELETE
section("3. 删除 Neo4j 孤儿节点")
if kp_to_drop:
    rows = graph_db.run_query(
        "MATCH (k:KnowledgePoint) WHERE k.entity_id IN $ids DETACH DELETE k RETURN count(*) AS n",
        {"ids": kp_to_drop},
    )
    print(f"  KnowledgePoint 删除 {rows[0]['n'] if rows else 0} 节点")
else:
    print("  KnowledgePoint 无需删除")
if q_to_drop:
    rows = graph_db.run_query(
        "MATCH (q:Question) WHERE q.entity_id IN $ids DETACH DELETE q RETURN count(*) AS n",
        {"ids": q_to_drop},
    )
    print(f"  Question 删除 {rows[0]['n'] if rows else 0} 节点")
else:
    print("  Question 无需删除")

# 4. 顺手再清掉 entity_id 为 NULL 的孤节点（历史脏节点）
section("4. 清理 entity_id 缺失或 -1 的孤节点")
rows = graph_db.run_query(
    """
    MATCH (n) WHERE (n.entity_id IS NULL OR n.entity_id = -1)
      AND any(lbl IN labels(n) WHERE lbl IN
        ['KnowledgePoint','Question','KnowledgePackage','KnowledgeBlock','KnowledgeAtom','KnowledgeDerivative'])
    DETACH DELETE n RETURN count(*) AS n
    """,
)
print(f"  删除孤节点 {rows[0]['n'] if rows else 0} 个")

# 5a. 在 MERGE 重投影之前，先清掉所有"知识图骨干"关系，避免旧 EGE 行已删但 Neo4j 残留
section("5a. 清掉知识骨干旧关系（避免 MERGE 后老边残留）")
backbone_rels = [
    "RELATES_STRONG",
    "RELATES_ADJACENT",
    "RELATES_FALLBACK",
    "INCLUDES_QUESTION",
    "COVERS_POINT",
    "CONTAINS_BLOCK",
    "CONTAINS_ATOM",
    "HAS_DERIVATIVE",
]
for rel in backbone_rels:
    rows = graph_db.run_query(
        f"MATCH ()-[r:{rel}]->() DELETE r RETURN count(*) AS n",
    )
    print(f"  -:{rel:<22} 删除 {rows[0]['n'] if rows else 0} 边")
rows = graph_db.run_query(
    """
    MATCH (:Question)-[r:TESTS]->(:KnowledgePoint)
    WHERE r.source_origin = 'business_projection'
    DELETE r RETURN count(*) AS n
    """,
)
print(f"  -:{'TESTS(business)':<22} 删除 {rows[0]['n'] if rows else 0} 边")
rows = graph_db.run_query(
    """
    MATCH (:KnowledgePoint)-[r]->(:KnowledgePoint)
    WHERE r.source_origin = 'business_projection'
    DELETE r RETURN count(*) AS n
    """,
)
print(f"  -:{'KP-KP(business)':<22} 删除 {rows[0]['n'] if rows else 0} 边")

# 5b. 让 academic_graph_service 按 PG 现状重投影（MERGE 重建/补齐边）
section("5b. sync_all_knowledge_projection（按 PG 重建 Neo4j 关系）")
service = ags.AcademicGraphService()
result = service.sync_all_knowledge_projection(db)
print(f"  package_count={result.get('package_count')}")
print(f"  synced_nodes={result.get('synced_nodes')}")
print(f"  synced_relationships={result.get('synced_relationships')}")

# 6. 报告新状态
section("6. 重建后 Neo4j 状态")
rel_rows = (
    graph_db.run_query("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n ORDER BY n DESC") or []
)
print(f"  KnowledgePoint = {graph_db.run_query('MATCH (k:KnowledgePoint) RETURN count(k) AS n')[0]['n']}")
print(f"  Question       = {graph_db.run_query('MATCH (q:Question) RETURN count(q) AS n')[0]['n']}")
for r in rel_rows:
    print(f"    {r['t']:<24} {r['n']}")

db.close()
print("\n--- DONE ---")
