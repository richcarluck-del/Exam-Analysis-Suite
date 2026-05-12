"""
对第一轮 audit 留下的几个可疑差异做钻取：

1. KQL.topic_strong = 208 但 EntityGraphEdge.relates_strong (KP→Q) = 887  →  差 679
   - 投影代码 _collect_edges_for_package 应该只把 KQL 投到 EGE，量级应一致
   - 钻：EGE 里这 887 条边的 question_item_id 是哪些？涉及多少 KP？还能在 KQL 里找到吗？

2. 图谱里 relates_strong 边数 = 887 ≫ 文档说的"反向边"。是不是历史包/已删除包留下的脏边？
   - 钻：按图边的 source_kp 是否仍在 knowledge_package_points / knowledge_points
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

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
db = Session()


def section(title: str) -> None:
    print("\n" + "#" * 78)
    print("# " + title)
    print("#" * 78)


def kv(label, value, indent: int = 0) -> None:
    print(f"{' ' * indent}{label:<60} {value}")


# ------------------------------------------------------------------
# 1. relates_strong 887 条 vs KQL 208 条 的差异
# ------------------------------------------------------------------
section("1. EGE.relates_strong 边的来源核查（应来自 KQL 投影）")

ege_strong_total = db.execute(text("""
    SELECT COUNT(*) FROM entity_graph_edges
    WHERE source_entity_type='knowledge_point'
      AND target_entity_type='question_item'
      AND relation_type='relates_strong'
""")).scalar()
kv("EGE relates_strong (KP->Q) 总数", ege_strong_total)

# 1.1 看 evidence_json 里有没有 question_link_id
ege_with_link_id = db.execute(text("""
    SELECT COUNT(*) FROM entity_graph_edges
    WHERE source_entity_type='knowledge_point'
      AND target_entity_type='question_item'
      AND relation_type='relates_strong'
      AND (evidence_json::jsonb) ? 'question_link_id'
""")).scalar()
kv("其中 evidence_json 含 question_link_id 的", ege_with_link_id)

# 1.2 这些 edge 的 question_link_id，能不能在 KQL 表里找到？
hits = db.execute(text("""
    SELECT
        SUM(CASE WHEN kql.id IS NOT NULL THEN 1 ELSE 0 END) AS hit,
        SUM(CASE WHEN kql.id IS NULL THEN 1 ELSE 0 END)     AS miss
    FROM entity_graph_edges ege
    LEFT JOIN knowledge_question_links kql
           ON kql.id = ((ege.evidence_json::jsonb)->>'question_link_id')::int
    WHERE ege.source_entity_type='knowledge_point'
      AND ege.target_entity_type='question_item'
      AND ege.relation_type='relates_strong'
      AND (ege.evidence_json::jsonb) ? 'question_link_id'
""")).first()
kv("EGE.question_link_id → KQL 命中条数",  hits[0])
kv("EGE.question_link_id → KQL miss 条数", hits[1])

# 1.3 这些边的 source_kp_id 与 target_q_id pair 与 KQL 比
pair_diff = db.execute(text("""
    WITH ege AS (
        SELECT source_entity_id AS kp_id, target_entity_id AS q_id
        FROM entity_graph_edges
        WHERE source_entity_type='knowledge_point'
          AND target_entity_type='question_item'
          AND relation_type='relates_strong'
    ),
    kql AS (
        SELECT knowledge_point_id AS kp_id, question_item_id AS q_id
        FROM knowledge_question_links
        WHERE relation_type='topic_strong'
    )
    SELECT
        (SELECT COUNT(*) FROM ege)                                                  AS ege_pairs,
        (SELECT COUNT(*) FROM kql)                                                  AS kql_pairs,
        (SELECT COUNT(*) FROM ege e WHERE EXISTS (SELECT 1 FROM kql k WHERE k.kp_id=e.kp_id AND k.q_id=e.q_id)) AS ege_match_kql,
        (SELECT COUNT(*) FROM kql k WHERE EXISTS (SELECT 1 FROM ege e WHERE e.kp_id=k.kp_id AND e.q_id=k.q_id)) AS kql_match_ege
""")).first()
kv("EGE strong (kp,q) 对子数",            pair_diff[0])
kv("KQL strong (kp,q) 对子数",            pair_diff[1])
kv("EGE 中能在 KQL 找到对子的边",          pair_diff[2])
kv("KQL 中能在 EGE 找到对子的边",          pair_diff[3])

# 1.4 EGE 中那些找不到 KQL 对子的边长啥样
orphan_examples = db.execute(text("""
    SELECT ege.id, ege.source_entity_id, ege.target_entity_id,
           ege.evidence_json::text, ege.source_origin, ege.created_at
    FROM entity_graph_edges ege
    WHERE ege.source_entity_type='knowledge_point'
      AND ege.target_entity_type='question_item'
      AND ege.relation_type='relates_strong'
      AND NOT EXISTS (
          SELECT 1 FROM knowledge_question_links kql
          WHERE kql.knowledge_point_id = ege.source_entity_id
            AND kql.question_item_id   = ege.target_entity_id
            AND kql.relation_type      = 'topic_strong'
      )
    ORDER BY ege.created_at DESC
    LIMIT 5
""")).all()
print("\n[orphan EGE.relates_strong 示例（KQL 找不到对应 pair）]")
for r in orphan_examples:
    print(f"  edge#{r[0]}  kp={r[1]}  q={r[2]}  origin={r[4]}  created={r[5]}")
    print(f"    evidence: {r[3][:200]}")

# ------------------------------------------------------------------
# 2. 图谱里的 KP 节点是不是仍然存在
# ------------------------------------------------------------------
section("2. EGE 里引用的实体是否还活着")

stale = db.execute(text("""
    SELECT
      (SELECT COUNT(*) FROM entity_graph_edges ege
        WHERE ege.source_entity_type='knowledge_point'
          AND NOT EXISTS (SELECT 1 FROM knowledge_points kp WHERE kp.id = ege.source_entity_id)) AS dangling_src_kp,
      (SELECT COUNT(*) FROM entity_graph_edges ege
        WHERE ege.target_entity_type='knowledge_point'
          AND NOT EXISTS (SELECT 1 FROM knowledge_points kp WHERE kp.id = ege.target_entity_id)) AS dangling_tgt_kp,
      (SELECT COUNT(*) FROM entity_graph_edges ege
        WHERE ege.target_entity_type='question_item'
          AND NOT EXISTS (SELECT 1 FROM question_items q WHERE q.id = ege.target_entity_id)) AS dangling_q,
      (SELECT COUNT(*) FROM entity_graph_edges ege
        WHERE ege.source_entity_type='knowledge_package'
          AND NOT EXISTS (SELECT 1 FROM knowledge_packages p WHERE p.id = ege.source_entity_id)) AS dangling_pkg
""")).first()
kv("EGE.source kp 不在 knowledge_points 里", stale[0])
kv("EGE.target kp 不在 knowledge_points 里", stale[1])
kv("EGE.target q 不在 question_items 里",    stale[2])
kv("EGE.source pkg 不在 knowledge_packages 里", stale[3])

# 当前哪些 package_id 还活着 vs EGE 里出现的 package_id
alive = db.execute(text("SELECT id FROM knowledge_packages ORDER BY id")).scalars().all()
ege_pkgs = db.execute(text("""
    SELECT DISTINCT source_entity_id FROM entity_graph_edges WHERE source_entity_type='knowledge_package'
    UNION
    SELECT DISTINCT ((evidence_json::jsonb)->>'package_id')::int FROM entity_graph_edges
        WHERE (evidence_json::jsonb) ? 'package_id'
""")).scalars().all()
kv("knowledge_packages 表中活着的 package_id", list(alive))
kv("EGE 中引用过的 package_id", sorted([p for p in ege_pkgs if p is not None]))

# ------------------------------------------------------------------
# 3. KP 命名重复进一步：用 trigram 找 ratio≥0.6 的相似名（不是子串）
# ------------------------------------------------------------------
section("3. KP 命名相似度（pg_trgm 模糊去重视角）")

try:
    db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    db.commit()
    rows = db.execute(text("""
        SELECT a.id, a.canonical_name, b.id, b.canonical_name,
               similarity(a.canonical_name, b.canonical_name) AS sim
        FROM knowledge_points a, knowledge_points b
        WHERE a.id < b.id
          AND a.canonical_name % b.canonical_name
          AND similarity(a.canonical_name, b.canonical_name) >= 0.55
        ORDER BY sim DESC
        LIMIT 20
    """)).all()
    kv("trigram 相似度>=0.55 的 KP 对数（前20）", len(rows))
    for r in rows:
        print(f"  sim={float(r[4]):.2f}  #{r[0]:<5} '{r[1][:30]}'  ~~  #{r[2]:<5} '{r[3][:30]}'")
except Exception as exc:
    print(f"pg_trgm 不可用: {exc}")

# 全量统计：>=0.55 的对数
try:
    total_pairs = db.execute(text("""
        SELECT COUNT(*) FROM knowledge_points a, knowledge_points b
        WHERE a.id < b.id
          AND similarity(a.canonical_name, b.canonical_name) >= 0.55
    """)).scalar()
    kv("trigram sim>=0.55 的 KP 对总数", total_pairs)
    total_pairs_high = db.execute(text("""
        SELECT COUNT(*) FROM knowledge_points a, knowledge_points b
        WHERE a.id < b.id
          AND similarity(a.canonical_name, b.canonical_name) >= 0.75
    """)).scalar()
    kv("trigram sim>=0.75 的 KP 对总数（疑似同概念）", total_pairs_high)
except Exception as exc:
    print(f"统计失败: {exc}")

# ------------------------------------------------------------------
# 4. KP 文本承载到底有多空
# ------------------------------------------------------------------
section("4. KP 文本字段实际承载（不是单纯 NULL，而是真实信息量）")

rows = db.execute(text("""
    SELECT id, canonical_name,
           length(coalesce(canonical_summary,'')) AS summary_len,
           length(coalesce(prerequisite_summary,'')) AS prereq_len,
           CASE
             WHEN aliases_json IS NULL THEN 0
             WHEN aliases_json::text IN ('[]','null','""') THEN 0
             ELSE jsonb_array_length(aliases_json::jsonb)
           END AS alias_n
    FROM knowledge_points
    LIMIT 5
""")).all()
print("[抽样 5 条 KP 文本承载]")
for r in rows:
    print(f"  #{r[0]} '{r[1][:30]}'  summary={r[2]} prereq={r[3]} alias_n={r[4]}")

# blocks/atoms 是否真实有内容承载这些 KP
kp_with_block = db.execute(text("""
    SELECT COUNT(DISTINCT knowledge_point_id) FROM knowledge_blocks WHERE knowledge_point_id IS NOT NULL
""")).scalar()
kp_with_atom = db.execute(text("""
    SELECT COUNT(DISTINCT knowledge_point_id) FROM knowledge_atoms WHERE knowledge_point_id IS NOT NULL
""")).scalar()
kv("有至少 1 个 block 的 KP 数", kp_with_block)
kv("有至少 1 个 atom 的 KP 数",  kp_with_atom)
kv("既无 block 又无 atom 的 KP 数（图谱里只有名字的 KP）",
   db.execute(text("""
       SELECT COUNT(*) FROM knowledge_points kp
       WHERE NOT EXISTS (SELECT 1 FROM knowledge_blocks b WHERE b.knowledge_point_id = kp.id)
         AND NOT EXISTS (SELECT 1 FROM knowledge_atoms  a WHERE a.knowledge_point_id = kp.id)
   """)).scalar()
)

# ------------------------------------------------------------------
# 5. 当前两个活包到底链了多少题、与 KP 的关系覆盖度
# ------------------------------------------------------------------
section("5. 当前活包真实覆盖度（428 / 433）")

for pkg_id in [428, 433]:
    print(f"\n[package_id={pkg_id}]")
    rows = db.execute(text("""
        SELECT 'package_questions' AS layer, COUNT(*) FROM knowledge_package_questions WHERE package_id=:p
        UNION ALL
        SELECT 'package_points',           COUNT(*) FROM knowledge_package_points    WHERE package_id=:p
        UNION ALL
        SELECT 'blocks',                   COUNT(*) FROM knowledge_blocks            WHERE package_id=:p
        UNION ALL
        SELECT 'atoms',                    COUNT(*) FROM knowledge_atoms             WHERE package_id=:p
    """), {"p": pkg_id}).all()
    for r in rows:
        kv(r[0], r[1], indent=2)
    # KQL 桥接覆盖：本包内题目 中有 KQL 的占比
    rows = db.execute(text("""
        SELECT
          (SELECT COUNT(DISTINCT pq.question_item_id) FROM knowledge_package_questions pq WHERE pq.package_id=:p)            AS in_pkg,
          (SELECT COUNT(DISTINCT kql.question_item_id)
             FROM knowledge_question_links kql
             JOIN knowledge_package_questions pq
               ON pq.question_item_id = kql.question_item_id
             WHERE pq.package_id=:p)                                                                                          AS bridged
    """), {"p": pkg_id}).first()
    kv("题目数 in_pkg",   rows[0], indent=2)
    kv("被 KQL 桥接题数", rows[1], indent=2)

db.close()
