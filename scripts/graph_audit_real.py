"""
独立的图谱真实数据审计脚本。
直接读 PostgreSQL + Neo4j 的真实数据，不复用文档结论。
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 强制 UTF-8 输出，避免 Windows GBK 控制台对 ↔ 等字符报错
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

# 将项目根加入 path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "exam123456")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def kv(label: str, value, indent: int = 0) -> None:
    pad = " " * indent
    print(f"{pad}{label:<48} {value}")


def main() -> None:
    print("Database:", DATABASE_URL)
    print("Neo4j   :", NEO4J_URI)

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # ============================================================
        # A. 基础规模
        # ============================================================
        section("A. 数据规模（PostgreSQL）")
        scalars = {}
        for table in [
            "knowledge_points",
            "knowledge_packages",
            "knowledge_blocks",
            "knowledge_atoms",
            "knowledge_package_points",
            "knowledge_package_questions",
            "knowledge_question_links",
            "knowledge_point_relations",
            "entity_graph_edges",
            "question_items",
            "knowledge_derivatives",
        ]:
            try:
                n = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
            except Exception as exc:
                n = f"ERR: {exc}"
            scalars[table] = n
            kv(table, n)

        # ============================================================
        # B. EntityGraphEdge 结构画像
        # ============================================================
        section("B. EntityGraphEdge 边类型分布")
        rows = db.execute(text("""
            SELECT source_entity_type, target_entity_type, relation_type,
                   COUNT(*) AS cnt,
                   COUNT(*) FILTER (WHERE source_origin = 'business_projection') AS biz,
                   COUNT(*) FILTER (WHERE source_origin = 'llm_extraction')      AS llm
            FROM entity_graph_edges
            GROUP BY source_entity_type, target_entity_type, relation_type
            ORDER BY cnt DESC
        """)).all()
        kv("(src_type, tgt_type, relation)", "  cnt  biz  llm")
        for r in rows:
            label = f"{r[0]:>20} -[{r[2]:<22}]-> {r[1]:<18}"
            kv(label, f"{r[3]:>5} {r[4]:>4} {r[5]:>4}")

        # ============================================================
        # C. KP 之间的边（独立验证）
        # ============================================================
        section("C. 知识点↔知识点 边（独立验证）")
        kp_kp_edges = db.execute(text("""
            SELECT relation_type, COUNT(*)
            FROM entity_graph_edges
            WHERE source_entity_type = 'knowledge_point'
              AND target_entity_type = 'knowledge_point'
            GROUP BY relation_type
        """)).all()
        if kp_kp_edges:
            for r in kp_kp_edges:
                kv(r[0], r[1])
        else:
            kv("knowledge_point -> knowledge_point edges", "0 条")

        kpr_count = db.execute(text("SELECT COUNT(*) FROM knowledge_point_relations")).scalar() or 0
        kv("knowledge_point_relations 表", kpr_count)

        # ============================================================
        # D. 题目↔知识点 桥接 vs 图谱边
        # ============================================================
        section("D. 题↔知识点 桥接数据 vs 图谱边")

        # 桥接表里实际有多少条
        kql_total = db.execute(text("SELECT COUNT(*) FROM knowledge_question_links")).scalar() or 0
        kql_distinct_q = db.execute(text("SELECT COUNT(DISTINCT question_item_id) FROM knowledge_question_links")).scalar() or 0
        kql_distinct_kp = db.execute(text("SELECT COUNT(DISTINCT knowledge_point_id) FROM knowledge_question_links")).scalar() or 0
        kql_relation_dist = db.execute(text("""
            SELECT relation_type, COUNT(*)
            FROM knowledge_question_links
            GROUP BY relation_type
            ORDER BY COUNT(*) DESC
        """)).all()
        kql_approved = db.execute(text("""
            SELECT approved_status, COUNT(*)
            FROM knowledge_question_links
            GROUP BY approved_status
        """)).all()

        kv("KnowledgeQuestionLink 总数", kql_total)
        kv("涉及题目数 (distinct question_item_id)", kql_distinct_q)
        kv("涉及知识点数 (distinct knowledge_point_id)", kql_distinct_kp)
        kv("relation_type 分布", "")
        for r in kql_relation_dist:
            kv(f"  {r[0]}", r[1], indent=2)
        kv("approved_status 分布", "")
        for r in kql_approved:
            kv(f"  {r[0]}", r[1], indent=2)

        # 图谱中 question_item -> knowledge_point 方向的边
        q_kp = db.execute(text("""
            SELECT relation_type, COUNT(*)
            FROM entity_graph_edges
            WHERE source_entity_type = 'question_item'
              AND target_entity_type = 'knowledge_point'
            GROUP BY relation_type
        """)).all()
        kv("EntityGraphEdge: question_item -> knowledge_point", "")
        if q_kp:
            for r in q_kp:
                kv(f"  {r[0]}", r[1], indent=2)
        else:
            kv("  (none)", "0 条", indent=2)

        # 反方向 knowledge_point -> question_item
        kp_q = db.execute(text("""
            SELECT relation_type, COUNT(*)
            FROM entity_graph_edges
            WHERE source_entity_type = 'knowledge_point'
              AND target_entity_type = 'question_item'
            GROUP BY relation_type
        """)).all()
        kv("EntityGraphEdge: knowledge_point -> question_item", "")
        for r in kp_q:
            kv(f"  {r[0]}", r[1], indent=2)

        # ============================================================
        # E. 知识点元数据完整性
        # ============================================================
        section("E. 知识点元数据完整性")

        kp_total = scalars.get("knowledge_points", 0) or 0
        for col in ["subject", "grade_scope", "canonical_summary", "prerequisite_summary"]:
            n_null = db.execute(text(f"""
                SELECT COUNT(*) FROM knowledge_points
                WHERE {col} IS NULL OR length(trim({col}::text)) = 0
            """)).scalar() or 0
            ratio = (n_null / kp_total * 100) if kp_total else 0
            kv(f"{col} 为空", f"{n_null} / {kp_total}  ({ratio:.1f}%)")

        # aliases_json 为空（[]) 的占比
        alias_empty = db.execute(text("""
            SELECT COUNT(*) FROM knowledge_points
            WHERE aliases_json IS NULL
               OR aliases_json::text IN ('[]', 'null', '""')
        """)).scalar() or 0
        kv("aliases_json 为空", f"{alias_empty} / {kp_total}  ({alias_empty/kp_total*100 if kp_total else 0:.1f}%)")

        # 来源：有几条来自 LLM 链路？
        origin_dist = db.execute(text("""
            SELECT source_origin, COUNT(*)
            FROM knowledge_points
            GROUP BY source_origin
            ORDER BY COUNT(*) DESC
        """)).all()
        kv("source_origin 分布", "")
        for r in origin_dist:
            kv(f"  {r[0]}", r[1], indent=2)

        # ============================================================
        # F. 跨包共享 / 孤立
        # ============================================================
        section("F. 包覆盖与孤立知识点")

        kp_per_package = db.execute(text("""
            SELECT package_id, COUNT(*) AS n
            FROM knowledge_package_points
            GROUP BY package_id
            ORDER BY package_id
        """)).all()
        kv("各包覆盖 KP 数", "")
        for r in kp_per_package:
            kv(f"  package_id={r[0]}", r[1], indent=2)

        # 跨包共享：一个 KP 出现在多少个包里
        cross = db.execute(text("""
            SELECT shared_count, kp_count FROM (
                SELECT shared_count, COUNT(*) AS kp_count
                FROM (
                    SELECT knowledge_point_id, COUNT(DISTINCT package_id) AS shared_count
                    FROM knowledge_package_points
                    GROUP BY knowledge_point_id
                ) t
                GROUP BY shared_count
            ) s
            ORDER BY shared_count
        """)).all()
        kv("KP 出现于包数的分布", "")
        for r in cross:
            kv(f"  出现于 {r[0]} 个包的 KP", r[1], indent=2)

        orphan = db.execute(text("""
            SELECT COUNT(*) FROM knowledge_points kp
            WHERE NOT EXISTS (
                SELECT 1 FROM knowledge_package_points kpp
                WHERE kpp.knowledge_point_id = kp.id
            )
        """)).scalar() or 0
        kv("未挂任何包的 KP（孤立）", f"{orphan} / {kp_total}  ({orphan/kp_total*100 if kp_total else 0:.1f}%)")

        # ============================================================
        # G. 命名碎片化（实证而非例子）
        # ============================================================
        section("G. 命名碎片化与潜在重复")

        # 1) 直接重复名（包含字符串包含关系）
        # 用一个简单的 normalize：去空格/标点/全半角
        normalized = db.execute(text("""
            SELECT id, canonical_name,
                   regexp_replace(regexp_replace(canonical_name, '[\s\(\)（）【】\[\]:：,，。\.\-—_/\\\\]+', '', 'g'),
                                  '[∀∃⇒⇔⇐]', '', 'g') AS norm,
                   subject, source_origin
            FROM knowledge_points
        """)).all()

        norm_groups: dict[str, list] = defaultdict(list)
        for row in normalized:
            norm_groups[(row[2] or "").lower()].append((row[0], row[1]))

        same_norm = [(k, v) for k, v in norm_groups.items() if len(v) > 1]
        kv("normalize 后名字完全相同的 KP 簇数", len(same_norm))
        kv("这些簇里的 KP 总条目", sum(len(v) for _, v in same_norm))
        kv("举例（前 5 簇）", "")
        for k, v in same_norm[:5]:
            ids = ", ".join(f"#{vid}({vname})" for vid, vname in v[:6])
            kv(f"  norm='{k[:40]}'", ids, indent=2)

        # 2) 子串包含关系（如 '充要条件' ⊂ '充要条件的等价表示p⇔q'）
        # 仅看较短名是否是较长名的真子串，并且都来自 LLM
        rows_llm = [r for r in normalized if (r[4] or "") in {"llm", "llm_extract", "llm_extraction"}]
        names = [(r[0], (r[1] or "").strip()) for r in rows_llm]
        substr_pairs = 0
        substr_examples: list[tuple] = []
        # 简单 O(n^2)，n ≤ 几百时可接受
        for i in range(len(names)):
            for j in range(len(names)):
                if i == j:
                    continue
                a_id, a_name = names[i]
                b_id, b_name = names[j]
                if not a_name or not b_name:
                    continue
                if len(a_name) >= 2 and len(a_name) < len(b_name) and a_name in b_name:
                    substr_pairs += 1
                    if len(substr_examples) < 8:
                        substr_examples.append((a_id, a_name, b_id, b_name))
        kv("LLM KP 中 a.name 是 b.name 真子串的对数", substr_pairs)
        kv("举例（短 ⊂ 长）", "")
        for a_id, a_name, b_id, b_name in substr_examples:
            kv(f"  #{a_id} '{a_name}'  ⊂  #{b_id} '{b_name}'", "", indent=2)

        # ============================================================
        # H. 题目侧：被桥接、未被桥接占比
        # ============================================================
        section("H. 题目桥接覆盖度")
        q_total = scalars.get("question_items", 0) or 0
        q_with_bridge = db.execute(text("""
            SELECT COUNT(DISTINCT question_item_id)
            FROM knowledge_question_links
        """)).scalar() or 0
        kv("题目总数 question_items", q_total)
        kv("被任何桥接命中的题目数", q_with_bridge)
        if q_total:
            kv("桥接覆盖率", f"{q_with_bridge/q_total*100:.1f}%")

        # 包内题目数 vs 被桥接的题目数
        per_package_q = db.execute(text("""
            SELECT pq.package_id,
                   COUNT(DISTINCT pq.question_item_id) AS in_pkg,
                   COUNT(DISTINCT kql.question_item_id) AS bridged
            FROM knowledge_package_questions pq
            LEFT JOIN knowledge_question_links kql
                   ON kql.question_item_id = pq.question_item_id
            GROUP BY pq.package_id
            ORDER BY pq.package_id
        """)).all()
        kv("各包：包内题目 / 被桥接题目", "")
        for r in per_package_q:
            kv(f"  package_id={r[0]}", f"in_pkg={r[1]}, bridged={r[2]}", indent=2)

        # ============================================================
        # I. Neo4j 实际状态
        # ============================================================
        section("I. Neo4j 当前图")
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            with driver.session(database=NEO4J_DB) as ses:
                node_total = ses.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                rel_total  = ses.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
                kv("Neo4j 节点总数", node_total)
                kv("Neo4j 关系总数", rel_total)

                kv("节点标签分布", "")
                for rec in ses.run("CALL db.labels() YIELD label "
                                   "CALL { WITH label MATCH (n) WHERE label IN labels(n) RETURN count(n) AS c } "
                                   "RETURN label, c ORDER BY c DESC"):
                    kv(f"  {rec['label']}", rec['c'], indent=2)

                kv("关系类型分布", "")
                for rec in ses.run("CALL db.relationshipTypes() YIELD relationshipType "
                                   "CALL { WITH relationshipType MATCH ()-[r]->() WHERE type(r) = relationshipType RETURN count(r) AS c } "
                                   "RETURN relationshipType, c ORDER BY c DESC"):
                    kv(f"  {rec['relationshipType']}", rec['c'], indent=2)

                # 是否存在 KP↔KP / Q→KP 路径
                kp_kp_neo = ses.run("MATCH (a:KnowledgePoint)-[r]->(b:KnowledgePoint) RETURN count(r) AS c").single()["c"]
                q_kp_neo = ses.run("MATCH (q:Question)-[r]->(k:KnowledgePoint) RETURN count(r) AS c").single()["c"]
                kp_q_neo = ses.run("MATCH (k:KnowledgePoint)-[r]->(q:Question) RETURN count(r) AS c").single()["c"]
                kv("Neo4j 中 KP→KP 边", kp_kp_neo)
                kv("Neo4j 中 Question→KP 边", q_kp_neo)
                kv("Neo4j 中 KP→Question 边", kp_q_neo)

                # 探索：随机选一个 KP，看它的 1 跳邻居都是什么类型
                sample = ses.run("""
                    MATCH (k:KnowledgePoint)-[r]-(other)
                    WITH k, labels(other) AS lbls, type(r) AS t
                    RETURN labels(k)[0] AS src, t AS rel, lbls AS tgt, count(*) AS c
                    ORDER BY c DESC LIMIT 12
                """).data()
                kv("KP 周围 1 跳邻居类型分布", "")
                for rec in sample:
                    kv(f"  KP -[{rec['rel']}]- {rec['tgt']}", rec['c'], indent=2)

            driver.close()
        except Exception as exc:
            kv("Neo4j 查询失败", str(exc))

        # ============================================================
        # J. 输出 JSON 摘要（便于其它工具消费）
        # ============================================================
        section("J. 摘要 JSON")
        summary = {
            "scalars": scalars,
            "kp_kp_edges_in_pg": dict((r[0], r[1]) for r in kp_kp_edges) if kp_kp_edges else {},
            "kpr_count": kpr_count,
            "kql": {
                "total": kql_total,
                "distinct_questions": kql_distinct_q,
                "distinct_kps": kql_distinct_kp,
                "relation_dist": dict((r[0], r[1]) for r in kql_relation_dist),
                "approved_dist": dict((r[0], r[1]) for r in kql_approved),
            },
            "graph_q_kp_edges": dict((r[0], r[1]) for r in q_kp),
            "graph_kp_q_edges": dict((r[0], r[1]) for r in kp_q),
            "kp_orphan": orphan,
            "kp_total": kp_total,
            "kp_per_package": [(r[0], r[1]) for r in kp_per_package],
            "name_collision_clusters": len(same_norm),
            "name_substring_pairs": substr_pairs,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    finally:
        db.close()


if __name__ == "__main__":
    main()
