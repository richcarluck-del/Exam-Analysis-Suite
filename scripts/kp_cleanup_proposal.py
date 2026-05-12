"""
B：历史 KP 降级清单 dry-run（只读，不改库）。

决策逻辑见 `kp_cleanup_common.py`；本脚本仅负责写入 CSV/Markdown 报告。
"""
from __future__ import annotations

import csv
import io
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import kp_cleanup_common as kcc

load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
db = Session()

OUT_DIR = SCRIPTS / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_PATH = OUT_DIR / f"kp_cleanup_proposal_{TS}.csv"
MD_PATH = OUT_DIR / f"kp_cleanup_proposal_{TS}.md"


def section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def kv(k: str, v: object, indent: int = 0) -> None:
    print(f"{' ' * indent}{k:<54} {v}")


decisions, action_counter, kp_total = kcc.build_kp_cleanup_decisions(db)

print("[1/2] 写 CSV …")
with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(decisions[0].keys()))
    writer.writeheader()
    writer.writerows(decisions)

print("[2/2] 写 Markdown …")
descriptions = {
    "DELETE_ORPHAN": "孤立 KP，可直接 DELETE",
    "DELETE_EMPTY_IN_PKG": "在活包但完全空壳，建议 DELETE 或先送审",
    "MERGE_INTO_CANONICAL": "并入簇代表，原名进 aliases",
    "KEEP_AS_CANONICAL": "簇代表，保留",
    "DEMOTE_TO_ATOM": "改为 knowledge_atom 挂到父 KP 下",
    "KEEP": "真正的概念名词，独立保留",
}

md_lines: list[str] = []
md_lines.append(f"# KP 清洗建议清单（dry-run · {TS}）\n")
md_lines.append(f"- 知识点总数：**{kp_total}**")
md_lines.append("- 报告类型：**只读 dry-run**，不修改任何数据\n")
md_lines.append("## 决策汇总\n")
md_lines.append("| 动作 | 数量 | 占比 | 含义 |")
md_lines.append("|------|-----:|-----:|------|")
for act, cnt in action_counter.most_common():
    md_lines.append(f"| `{act}` | {cnt} | {cnt * 100 / kp_total:.1f}% | {descriptions.get(act, '')} |")
md_lines.append(f"| **合计** | **{kp_total}** | 100% |  |\n")

n_delete = action_counter["DELETE_ORPHAN"] + action_counter["DELETE_EMPTY_IN_PKG"]
n_merge = action_counter["MERGE_INTO_CANONICAL"]
n_demote = action_counter["DEMOTE_TO_ATOM"]
n_keep = action_counter["KEEP"] + action_counter["KEEP_AS_CANONICAL"]
md_lines.append("## 清洗后预计形态\n")
md_lines.append(f"- **直接删除**：{n_delete} 条")
md_lines.append(f"- **合并进簇代表**：{n_merge} 条（变成代表的 alias）")
md_lines.append(f"- **降级为 atom**：{n_demote} 条")
md_lines.append(f"- **保留为 KP**：**{n_keep}** 条")
md_lines.append(
    f"- 即：`knowledge_points` 预计从 {kp_total} 行 → ≈ **{n_keep}** 行 （{n_keep * 100 / kp_total:.0f}%）\n",
)

md_lines.append("## 风险与人工 review 项\n")
high_risk = [
    d
    for d in decisions
    if d["proposed_action"] == "MERGE_INTO_CANONICAL" and (int(d["kql_count"]) > 0 or int(d["block_count"]) > 0)
]
md_lines.append(
    f"- **MERGE 中带承载的 KP**：{len(high_risk)} 条 — "
    "合并时必须迁移 KQL/block 引用到 canonical，否则会断证据链",
)
no_parent_demote = [
    d for d in decisions if d["proposed_action"] == "DEMOTE_TO_ATOM" and not d["proposed_parent_kp_id"]
]
md_lines.append(f"- **DEMOTE 但没找到父 KP**：{len(no_parent_demote)} 条 — 本次 common 已实现幸存者池兜底，仍建议抽样核对")
low_sim_demote = [
    d
    for d in decisions
    if d["proposed_action"] == "DEMOTE_TO_ATOM"
    and d["parent_similarity"]
    and float(d["parent_similarity"]) < 0.30
]
md_lines.append(f"- **DEMOTE 父 KP 相似度 < 0.30**：{len(low_sim_demote)} 条 — 建议人工确认")

md_lines.append("\n---\n## 明细（按动作分组）\n")
order = ["KEEP_AS_CANONICAL", "MERGE_INTO_CANONICAL", "DEMOTE_TO_ATOM", "KEEP", "DELETE_EMPTY_IN_PKG", "DELETE_ORPHAN"]

for act in order:
    bucket = [d for d in decisions if d["proposed_action"] == act]
    if not bucket:
        continue
    md_lines.append(f"\n### `{act}` — {len(bucket)} 条\n")
    if act == "MERGE_INTO_CANONICAL":
        by_cluster: dict[str | int, list] = defaultdict(list)
        for d in bucket:
            by_cluster[d["cluster_canonical_id"]].append(d)
        for canon_id, members in sorted(by_cluster.items(), key=lambda x: -len(x[1])):
            canon = next((x for x in decisions if x["id"] == int(str(canon_id))), None)
            canon_name = canon["name"] if canon else "?"
            md_lines.append(f"\n#### 簇 → 代表 #{canon_id} `{canon_name}` （并入 {len(members)} 条）\n")
            md_lines.append("| 被合并 KP | 原名 | KQL | block | atom |")
            md_lines.append("|----:|------|----:|----:|----:|")
            for m in members:
                md_lines.append(
                    f"| #{m['id']} | {m['name']} | {m['kql_count']} | {m['block_count']} | {m['atom_count']} |",
                )
    elif act == "DEMOTE_TO_ATOM":
        md_lines.append("| KP | 原名 | 粒度 | 建议父 KP | 相似度 | KQL | block | atom |")
        md_lines.append("|----:|------|------|------|----:|----:|----:|----:|")
        for d in sorted(bucket, key=lambda x: -float(x["parent_similarity"] or 0)):
            pdisp = (
                f"#{d['proposed_parent_kp_id']} `{d['proposed_parent_kp_name']}`"
                if d["proposed_parent_kp_id"]
                else "**未找到 — 需人工指定**"
            )
            md_lines.append(
                f"| #{d['id']} | {d['name']} | {d['grain_class']} | {pdisp} | "
                f"{d['parent_similarity']} | {d['kql_count']} | {d['block_count']} | {d['atom_count']} |",
            )
    elif act in ("DELETE_ORPHAN", "DELETE_EMPTY_IN_PKG"):
        md_lines.append("| KP | 原名 | 粒度 | 在活包 | 包 | provenance |")
        md_lines.append("|----:|------|------|------|------|----:|")
        for d in bucket:
            md_lines.append(
                f"| #{d['id']} | {d['name']} | {d['grain_class']} | "
                f"{d['in_active_pkg']} | {d['active_pkg_ids']} | {d['provenance_count']} |",
            )
    else:
        md_lines.append("| KP | 名 | 粒度 | 簇大小 | block | atom | KQL |")
        md_lines.append("|----:|------|------|----:|----:|----:|----:|")
        for d in sorted(bucket, key=lambda x: -int(x["cluster_size"])):
            md_lines.append(
                f"| #{d['id']} | {d['name']} | {d['grain_class']} | "
                f"{d['cluster_size']} | {d['block_count']} | {d['atom_count']} | {d['kql_count']} |",
            )

with MD_PATH.open("w", encoding="utf-8") as fh:
    fh.write("\n".join(md_lines))

section("控制台汇总")
kv("KP 总数", kp_total)
for act, cnt in action_counter.most_common():
    kv(act, f"{cnt} ({cnt * 100 / kp_total:.1f}%)", indent=0)
kv("估算保留 KP 数", n_keep)
print(f"\nCSV: {CSV_PATH}")
print(f"MD : {MD_PATH}")

db.close()
print("\n--- DONE ---")
