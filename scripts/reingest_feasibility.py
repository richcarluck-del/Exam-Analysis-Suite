"""
评估：改摄入 + 重摄 vs 纯数据清洗 的可行性
看 3 件事：
  1) 当前活包 428/433 的源文档是否还在硬盘上 → 决定能否重摄
  2) 209 个孤立 KP 的来源（哪些历史包死了 / 它们的 KP 还有 evidence 线索吗）
  3) 重摄成本：KP id 一旦变，会断开多少下游引用
"""
from __future__ import annotations

import io
import json
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
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def kv(k, v, indent: int = 0) -> None:
    print(f"{' ' * indent}{k:<60} {v}")


# ===========================================================================
# 1. 活包的源文档还在不在
# ===========================================================================
section("1. 活包 428/433 的 source_document 是否还在硬盘")

# 先看 source_documents 真实列
cols = db.execute(text("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'source_documents' ORDER BY ordinal_position
""")).all()
kv("source_documents 列",  ", ".join(c[0] for c in cols))

rows = db.execute(text("""
    SELECT kp.id, kp.package_title, kp.source_document_id, to_jsonb(sd.*)::text
    FROM knowledge_packages kp
    LEFT JOIN source_documents sd ON sd.id = kp.source_document_id
    ORDER BY kp.id
""")).all()

import json as _json
for r in rows:
    print(f"\n[package_id={r[0]}] '{r[1]}'  (source_document_id={r[2]})")
    if r[3]:
        sd = _json.loads(r[3])
        for k, v in sd.items():
            kv(f"  {k}", v, indent=2)
        # 找出可能含路径的字段，去硬盘上找
        path_candidates = []
        for k, v in sd.items():
            if isinstance(v, str) and any(part in k.lower() for part in ("path","uri","file","name","stor","url")):
                path_candidates.append((k, v))
        if path_candidates:
            print("  → 文件存在性检查:")
            for k, v in path_candidates:
                if not v:
                    continue
                ps = []
                for base in [ROOT,
                             ROOT/"analyzer"/"uploads"/"question_bank",
                             ROOT/"analyzer"/"uploads",
                             ROOT/"analyzer"/"uploads"/"question_bank_assets"]:
                    ps.append(base / str(v).lstrip("/\\"))
                    ps.append(base / Path(str(v)).name)
                found = [str(p) for p in ps if p.exists()]
                kv(f"    {k}={v!r}", "EXISTS" if found else "MISSING", indent=4)
                for f in found[:1]:
                    kv("      at", f, indent=4)


# ===========================================================================
# 2. 209 个孤立 KP 的来源
# ===========================================================================
section("2. 209 个孤立 KP（不属于任何活包）的来源画像")

orphan_total = db.execute(text("""
    SELECT COUNT(*) FROM knowledge_points kp
    WHERE NOT EXISTS (
        SELECT 1 FROM knowledge_package_points kpp WHERE kpp.knowledge_point_id = kp.id
    )
""")).scalar()
kv("孤立 KP 总数", orphan_total)

# 这些孤立 KP 还有 provenance 吗？
orphan_with_prov = db.execute(text("""
    SELECT COUNT(DISTINCT kpp.knowledge_point_id)
    FROM knowledge_point_provenance kpp
    WHERE kpp.knowledge_point_id NOT IN (
        SELECT knowledge_point_id FROM knowledge_package_points
    )
""")).scalar()
kv("其中有 provenance 记录的", f"{orphan_with_prov} (能溯源到 block)")

# 这些孤立 KP 的 provenance 指向的 package_id 现在是否存在？
orphan_pkg_breakdown = db.execute(text("""
    SELECT
        prov.package_id,
        COUNT(DISTINCT prov.knowledge_point_id) AS kp_count,
        EXISTS(SELECT 1 FROM knowledge_packages WHERE id = prov.package_id) AS pkg_alive
    FROM knowledge_point_provenance prov
    WHERE prov.knowledge_point_id NOT IN (
        SELECT knowledge_point_id FROM knowledge_package_points
    )
    GROUP BY prov.package_id
    ORDER BY prov.package_id
""")).all()
kv("孤立 KP 按 provenance.package_id 分布", "")
for r in orphan_pkg_breakdown:
    kv(f"  package_id={r[0]}",
       f"kp_count={r[1]:>4}  package_alive={'YES' if r[2] else 'NO（已删）'}",
       indent=2)

# 孤立 KP 关联的 block 还在不在
orphan_blocks = db.execute(text("""
    SELECT COUNT(DISTINCT prov.source_id) AS block_count,
           COUNT(DISTINCT prov.source_id) FILTER (WHERE EXISTS(
               SELECT 1 FROM knowledge_blocks b WHERE b.id = prov.source_id
           )) AS alive_count
    FROM knowledge_point_provenance prov
    WHERE prov.source_kind = 'knowledge_block'
      AND prov.knowledge_point_id NOT IN (
          SELECT knowledge_point_id FROM knowledge_package_points
      )
""")).first()
kv("孤立 KP 引用的 block 总数", orphan_blocks[0])
kv("  其中 block 还活着的", orphan_blocks[1])
kv("  block 已被删除（KP 完全失依据）", orphan_blocks[0] - orphan_blocks[1])

# 孤立 KP 上还有没有 KQL 桥接（说明它仍服务于某些题）
orphan_with_kql = db.execute(text("""
    SELECT COUNT(DISTINCT kp_id) FROM (
        SELECT knowledge_point_id AS kp_id
        FROM knowledge_question_links
        WHERE knowledge_point_id NOT IN (
            SELECT knowledge_point_id FROM knowledge_package_points
        )
    ) t
""")).scalar()
kv("孤立 KP 中仍有 KQL 桥接的", orphan_with_kql)

# ===========================================================================
# 3. 如果重摄/合并 KP，会断开多少下游引用
# ===========================================================================
section("3. KP id 改变会牵连多少下游数据")

downstream = db.execute(text("""
    SELECT 'knowledge_question_links',     COUNT(*) FROM knowledge_question_links
    UNION ALL SELECT 'knowledge_blocks (knowledge_point_id 不为空)',
                              COUNT(*) FROM knowledge_blocks WHERE knowledge_point_id IS NOT NULL
    UNION ALL SELECT 'knowledge_atoms',    COUNT(*) FROM knowledge_atoms
    UNION ALL SELECT 'knowledge_package_points', COUNT(*) FROM knowledge_package_points
    UNION ALL SELECT 'knowledge_point_relations', COUNT(*) FROM knowledge_point_relations
    UNION ALL SELECT 'knowledge_point_provenance', COUNT(*) FROM knowledge_point_provenance
    UNION ALL SELECT 'knowledge_derivatives',COUNT(*) FROM knowledge_derivatives
    UNION ALL SELECT 'entity_graph_edges (KP端)',
                              COUNT(*) FROM entity_graph_edges
                              WHERE source_entity_type='knowledge_point'
                                 OR target_entity_type='knowledge_point'
    UNION ALL SELECT 'retrieval_documents (entity_type 含 KP相关)',
                              COUNT(*) FROM retrieval_documents
                              WHERE entity_type IN ('knowledge_point','knowledge_block','knowledge_atom','knowledge_question_bridge','knowledge_package')
""")).all()
kv("一旦 KP id 重建，会牵连的表 / 行数", "")
for r in downstream:
    kv(f"  {r[0]}", r[1], indent=2)

# ===========================================================================
# 4. 当前流水线产出 vs 实际入库的差距：blocks/atoms 表为何那么少？
# ===========================================================================
section("4. 摄入产出真相：blocks/atoms 入库率")

# 实际拉到的 block 总数 vs 用进 KP 的
block_stats = db.execute(text("""
    SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE knowledge_point_id IS NOT NULL) AS bound,
        COUNT(*) FILTER (WHERE package_id IS NULL) AS no_pkg,
        COUNT(DISTINCT package_id) AS pkg_count
    FROM knowledge_blocks
""")).first()
kv("knowledge_blocks 行数", block_stats[0])
kv("  其中 knowledge_point_id 已填", block_stats[1])
kv("  其中 package_id 为空", block_stats[2])
kv("  覆盖的 package 数", block_stats[3])

atom_stats = db.execute(text("""
    SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE knowledge_point_id IS NOT NULL) AS bound,
        COUNT(DISTINCT package_id) AS pkg_count,
        COUNT(DISTINCT knowledge_point_id) AS kp_count
    FROM knowledge_atoms
""")).first()
kv("knowledge_atoms 行数", atom_stats[0])
kv("  其中 knowledge_point_id 已填", atom_stats[1])
kv("  覆盖的 package 数", atom_stats[2])
kv("  覆盖的 KP 数", atom_stats[3])

# 当前活包内的 KP 中有多少还能从 block 里"重建出原文"
recoverable = db.execute(text("""
    SELECT pp.package_id, COUNT(DISTINCT pp.knowledge_point_id) AS total_kp,
           COUNT(DISTINCT pp.knowledge_point_id) FILTER (
               WHERE EXISTS (SELECT 1 FROM knowledge_blocks b
                             WHERE b.knowledge_point_id = pp.knowledge_point_id)
           ) AS with_block
    FROM knowledge_package_points pp
    GROUP BY pp.package_id
    ORDER BY pp.package_id
""")).all()
kv("活包内 KP 有原文承载的占比", "")
for r in recoverable:
    pct = r[2] * 100 / r[1] if r[1] else 0
    kv(f"  package {r[0]}", f"{r[2]} / {r[1]}  ({pct:.0f}%)", indent=2)

# ===========================================================================
# 5. KQL 桥接引用的 KP 中有多少在活包内
# ===========================================================================
section("5. 285 条 KQL 桥接的 KP 是否仍是活的")

kql_kp_alive = db.execute(text("""
    SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE knowledge_point_id IN (
            SELECT knowledge_point_id FROM knowledge_package_points
        )) AS kp_in_active_pkg,
        COUNT(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM knowledge_points p WHERE p.id = knowledge_point_id
        )) AS kp_exists
    FROM knowledge_question_links
""")).first()
kv("KQL 总数",                     kql_kp_alive[0])
kv("  其中 KP 在活包内的",          kql_kp_alive[1])
kv("  其中 KP 仍存在于 knowledge_points 表",  kql_kp_alive[2])

db.close()
print("\n--- DONE ---")
