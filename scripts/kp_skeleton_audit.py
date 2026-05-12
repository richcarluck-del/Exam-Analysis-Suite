"""
专门面向「知识点骨架」的审计。
回答：知识点为什么连不成网？是命名碎片化？粒度问题？还是结构性缺失？

不依赖任何先前的文档结论，只看实证。
"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter, defaultdict
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
    print(f"{' ' * indent}{k:<54} {v}")


# ===========================================================================
# 0. 准备：把 271 个 KP 全量拉到内存
# ===========================================================================
all_kps = db.execute(text("""
    SELECT id, canonical_name, subject, grade_scope, knowledge_type,
           coalesce(canonical_summary,'') AS summary,
           source_origin, created_at
    FROM knowledge_points
    ORDER BY id
""")).all()

kp_by_id = {row[0]: row for row in all_kps}
names = [(row[0], (row[1] or "").strip()) for row in all_kps]

section("0. 知识点表的字段使用情况（再确认）")
kv("KP 总数", len(all_kps))
kv("knowledge_type 分布",
   dict(Counter([row[4] for row in all_kps])))
kv("source_origin 分布",
   dict(Counter([row[6] for row in all_kps])))

# ===========================================================================
# 1. 名字「形态」分布：用正则探测命名风格
# ===========================================================================
section("1. KP 名字的语言形态画像")

# 1.1 长度分布
lengths = [len(name) for _, name in names]
buckets = Counter()
for L in lengths:
    if L <= 4: buckets["1-4 字（极短）"] += 1
    elif L <= 8: buckets["5-8 字（标准）"] += 1
    elif L <= 14: buckets["9-14 字（偏长）"] += 1
    elif L <= 24: buckets["15-24 字（描述句）"] += 1
    else: buckets["25+ 字（长句）"] += 1
kv("名字长度分布", "")
for k, v in sorted(buckets.items()):
    kv(f"  {k}", v, indent=2)

# 1.2 命名风格分类（基于结构特征的启发式）
patterns = {
    "纯名词（短，无标点无公式）": re.compile(r"^[\u4e00-\u9fff]{2,8}$"),
    "动词性（含「的」/「与」/「及」+操作词）": re.compile(r"(的判定|的运算|的计算|的求解|的应用|的判断|的化简|的证明)"),
    "句式（含「在/对于/根据/通过」）": re.compile(r"^(在|对于|根据|通过|当|若)"),
    "含括号补充说明": re.compile(r"[（(].*?[）)]"),
    "含 LaTeX/Unicode 数学符号": re.compile(r"[∀∃∈∉⊆⊇⊂⊃∪∩⇒⇔≤≥≠≈±∑∏∫√∞₀-₉⁰-⁹]"),
    "含 ASCII 公式片段（如 p⇒q, f(x)）": re.compile(r"[a-zA-Z]\([a-zA-Z]+\)|[a-zA-Z]\s*[=≤≥<>⇒⇔]\s*[a-zA-Z0-9]"),
    "含逗号/分号（多概念叠加）": re.compile(r"[，,；;]"),
    "含「方法/思路/技巧/规律/规则」": re.compile(r"(方法|思路|技巧|规律|规则|步骤|策略)"),
    "含「关系/性质/特点/特征」": re.compile(r"(关系|性质|特点|特征|结构)"),
    "含「定义/概念」": re.compile(r"(定义|概念)"),
    "含「公式/定理」": re.compile(r"(公式|定理|法则)"),
    "含「与/和/或」复合": re.compile(r"[与和或]"),
    "含「（如…）」举例式": re.compile(r"（如|（包括|（即|（属于"),
}

style_counts = {}
style_examples = {}
for label, pat in patterns.items():
    matched = []
    for kid, name in names:
        if pat.search(name):
            matched.append((kid, name))
    style_counts[label] = len(matched)
    style_examples[label] = matched[:3]

kv("命名风格命中数（同一名字可能命中多条）", "")
for k, v in sorted(style_counts.items(), key=lambda x: -x[1]):
    kv(f"  {k}", f"{v}  ({v*100/len(names):.0f}%)", indent=2)
print()
print("[每种风格的样例（各 3 条）]")
for label, examples in style_examples.items():
    if examples:
        print(f"\n  ◆ {label}")
        for kid, name in examples:
            print(f"     #{kid}  {name}")

# ===========================================================================
# 2. 同概念碎片化：再深一层（不仅 trigram，还看「核心词」共现）
# ===========================================================================
section("2. 同概念碎片化：核心词聚类")

# 抽核心词：去掉所有标点/符号/长括号注释后的最短主体
def extract_core(name: str) -> str:
    n = re.sub(r"[（(][^）)]*[）)]", "", name)        # 去括号注释
    n = re.sub(r"[，,；;].*$", "", n)                   # 截掉逗号后的延续
    n = re.sub(r"(的判定|的运算|的计算|的求解|的应用|的判断|的化简|的证明|的概念|的定义|的方法|的思路|的规则|的规律)$", "", n)
    n = re.sub(r"[\s]+", "", n)
    n = re.sub(r"[∀∃∈∉⊆⊇⊂⊃∪∩⇒⇔≤≥≠≈]", "", n)
    return n

cores = defaultdict(list)
for kid, name in names:
    if not name:
        continue
    cores[extract_core(name)].append((kid, name))

# 只看簇内 ≥ 2 条
fragmented = [(core, members) for core, members in cores.items() if len(members) >= 2]
kv("可识别的「同核心词簇」数", len(fragmented))
kv("被卷入碎片化的 KP 总数",
   sum(len(m) for _, m in fragmented))
kv("最大簇大小", max((len(m) for _, m in fragmented), default=0))

# 列出前 10 大簇
sorted_clusters = sorted(fragmented, key=lambda x: -len(x[1]))
print("\n[前 12 大「同核心词簇」]")
for core, members in sorted_clusters[:12]:
    print(f"  ◆ 核心词='{core}'  ({len(members)} 条)")
    for kid, name in members[:8]:
        print(f"     #{kid}  {name}")
    if len(members) > 8:
        print(f"     ... 还有 {len(members)-8} 条")

# ===========================================================================
# 3. 粒度乱：同一文档里既有「概念定义」又有「解题方法」也有「考点速记」
# ===========================================================================
section("3. KP 粒度类型自动归类（基于命名特征）")

def classify_grain(name: str) -> str:
    """根据名字推断 KP 是哪一类（概念 / 方法 / 题型 / 规则 / 公式 / 描述）"""
    if re.search(r"(的定义|的概念|的含义|什么是)", name):
        return "概念定义"
    if re.search(r"(公式|定理|法则)", name):
        return "公式定理"
    if re.search(r"(方法|思路|步骤|策略|技巧)", name):
        return "解题方法"
    if re.search(r"(性质|特点|特征|规律)", name):
        return "性质规律"
    if re.search(r"(判定|判断|辨析|识别|证明)", name):
        return "判定/识别"
    if re.search(r"(运算|计算|求解|化简|求|解)", name):
        return "运算/计算"
    if re.search(r"(应用|结合|综合)", name):
        return "应用/综合"
    if re.search(r"(易错|误区|陷阱|注意|常见错)", name):
        return "易错点"
    if re.search(r"(关系|结构|分类)", name):
        return "结构关系"
    if re.search(r"[∀∃∈⊆⊇⇒⇔]", name) or re.search(r"[a-zA-Z]\([a-zA-Z]+\)", name):
        return "符号公式型"
    return "纯概念名词"

grain_dist = Counter()
grain_samples = defaultdict(list)
for kid, name in names:
    g = classify_grain(name)
    grain_dist[g] += 1
    if len(grain_samples[g]) < 4:
        grain_samples[g].append((kid, name))

kv("KP 粒度类型分布", "")
for g, n in grain_dist.most_common():
    kv(f"  {g}", f"{n}  ({n*100/len(names):.0f}%)", indent=2)

print("\n[每类样例]")
for g, samples in grain_samples.items():
    print(f"\n  ◆ {g}")
    for kid, name in samples:
        print(f"     #{kid}  {name}")

# ===========================================================================
# 4. 同包内的「重复抽取」：同一概念被多次写入
# ===========================================================================
section("4. 包内重复抽取检验（同一概念被同一 LLM run 多次写入）")

per_pkg = db.execute(text("""
    SELECT pp.package_id, kp.id, kp.canonical_name
    FROM knowledge_package_points pp
    JOIN knowledge_points kp ON kp.id = pp.knowledge_point_id
    ORDER BY pp.package_id, kp.id
""")).all()

pkg_to_names: dict[int, list] = defaultdict(list)
for pkg_id, kp_id, name in per_pkg:
    pkg_to_names[pkg_id].append((kp_id, name))

for pkg_id, items in pkg_to_names.items():
    print(f"\n[package_id={pkg_id}] 共 {len(items)} 个 KP")
    # 包内核心词聚类
    core_groups = defaultdict(list)
    for kid, name in items:
        core_groups[extract_core(name)].append((kid, name))
    dup = [(c, m) for c, m in core_groups.items() if len(m) >= 2]
    if dup:
        print(f"  包内同核心词簇数: {len(dup)}")
        for c, m in sorted(dup, key=lambda x: -len(x[1]))[:6]:
            print(f"    ◆ '{c}' ({len(m)} 条)")
            for kid, name in m:
                print(f"       #{kid}  {name}")
    else:
        print("  包内无同核心词簇（说明 LLM 在本包内未重复抽取同一概念）")

# ===========================================================================
# 5. 跨包：428 vs 433 是否真的没有任何概念交集
# ===========================================================================
section("5. 跨包概念交集（按核心词，而非按 KP id）")

names_428 = {extract_core(n) for _, n in pkg_to_names.get(428, [])}
names_433 = {extract_core(n) for _, n in pkg_to_names.get(433, [])}
common = names_428 & names_433
kv("包 428 核心词集合大小", len(names_428))
kv("包 433 核心词集合大小", len(names_433))
kv("核心词层面的交集", len(common))
if common:
    print("\n[共享的概念核心词]")
    for c in sorted(common):
        print(f"  - {c}")

# ===========================================================================
# 6. KP 是否有"上位词/学科分类"作为骨架
# ===========================================================================
section("6. taxonomy（学科分类骨架）使用情况")

tax_total = db.execute(text("SELECT COUNT(*) FROM taxonomy_nodes")).scalar() or 0
kv("taxonomy_nodes 总数", tax_total)
if tax_total:
    by_type = db.execute(text("""
        SELECT taxonomy_type, COUNT(*) FROM taxonomy_nodes GROUP BY taxonomy_type
    """)).all()
    for r in by_type:
        kv(f"  taxonomy_type={r[0]}", r[1], indent=2)

kp_with_tax = db.execute(text("""
    SELECT COUNT(*) FROM knowledge_points
    WHERE primary_taxonomy_node_id IS NOT NULL
""")).scalar() or 0
kv("knowledge_points.primary_taxonomy_node_id 不为空", kp_with_tax)

# ===========================================================================
# 7. 别名/同义词字典：是否在维护
# ===========================================================================
section("7. 别名 / 同义词字段")

alias_used = db.execute(text("""
    SELECT COUNT(*) FROM knowledge_points
    WHERE aliases_json IS NOT NULL
      AND aliases_json::text NOT IN ('[]','null','""')
""")).scalar() or 0
kv("aliases_json 非空的 KP 数", alias_used)

confusion_used = db.execute(text("""
    SELECT COUNT(*) FROM knowledge_points
    WHERE common_confusions_json IS NOT NULL
      AND common_confusions_json::text NOT IN ('[]','null','""')
""")).scalar() or 0
kv("common_confusions_json 非空的 KP 数", confusion_used)

# ===========================================================================
# 8. 知识点是否绑定到 evidence（block）：作为"信息载体"
# ===========================================================================
section("8. KP 与 evidence 的实际绑定")

# 8.1 KnowledgePointProvenance 表
prov_count = db.execute(text("SELECT COUNT(*) FROM knowledge_point_provenance")).scalar() or 0
kv("knowledge_point_provenance 行数", prov_count)
if prov_count:
    kp_with_prov = db.execute(text("""
        SELECT COUNT(DISTINCT knowledge_point_id) FROM knowledge_point_provenance
    """)).scalar() or 0
    kv("有 provenance 记录的 KP 数", kp_with_prov)
    by_kind = db.execute(text("""
        SELECT source_kind, COUNT(*) FROM knowledge_point_provenance GROUP BY source_kind
    """)).all()
    for r in by_kind:
        kv(f"  source_kind={r[0]}", r[1], indent=2)

# 8.2 KP 上挂的 block 文本质量
print()
sample = db.execute(text("""
    SELECT kp.id, kp.canonical_name, b.id, b.block_role, length(coalesce(b.normalized_text, b.raw_text, ''))
    FROM knowledge_points kp
    JOIN knowledge_blocks b ON b.knowledge_point_id = kp.id
    ORDER BY kp.id
    LIMIT 10
""")).all()
print("[KP 实际挂载的 block 抽样]")
for r in sample:
    print(f"  KP#{r[0]} '{r[1][:30]}'  →  block#{r[2]} role={r[3]} text_len={r[4]}")

# ===========================================================================
# 9. 第一批 30 个 KP 全量列出，肉眼可见的「形形色色」
# ===========================================================================
section("9. 包 433 的全部 38 个 KP（肉眼检视）")
items_433 = pkg_to_names.get(433, [])
for kid, name in items_433:
    grain = classify_grain(name)
    print(f"  [{grain:<10}]  #{kid:<6}  {name}")

db.close()
print("\n--- DONE ---")
