"""Audit why the knowledge graph isn't a real connected graph.
Checks: point naming consistency, edge types, missing cross-entity links."""
import sys
sys.path.insert(0, r"D:\10739\Exam-Analysis-Suite")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from collections import Counter, defaultdict
from sqlalchemy import func
from shared.database import SessionLocal
from shared.models import (
    KnowledgePoint, KnowledgePackage, KnowledgePackagePoint,
    KnowledgeBlock, KnowledgeAtom, KnowledgeQuestionLink,
    EntityGraphEdge, QuestionItem, KnowledgePointRelation,
)

db = SessionLocal()

print("=" * 70)
print("1. KNOWLEDGE POINT OVERVIEW")
print("=" * 70)
total_kps = db.query(KnowledgePoint).count()
print(f"Total knowledge_points: {total_kps}")

subjects = db.query(KnowledgePoint.subject, func.count()).group_by(KnowledgePoint.subject).all()
print(f"By subject: {[(s, c) for s, c in subjects]}")

origins = db.query(KnowledgePoint.source_origin, func.count()).group_by(KnowledgePoint.source_origin).all()
print(f"By source_origin: {[(o, c) for o, c in origins]}")

# Sample names
samples = db.query(KnowledgePoint.canonical_name, KnowledgePoint.subject, KnowledgePoint.source_origin)\
    .order_by(KnowledgePoint.id.desc()).limit(200).all()

name_counts = Counter(s[0] for s in samples if s[0])
dupes = {k: v for k, v in name_counts.items() if v > 1}
if dupes:
    print(f"Exact duplicate names (in last 200): {dupes}")
else:
    print("No exact duplicate names in last 200 KPs.")

print(f"\n{'='*70}")
print("2. PACKAGE 433 KNOWLEDGE POINTS (DeepSeek LLM extract)")
print("=" * 70)
p433_point_ids = [
    row[0] for row in
    db.query(KnowledgePackagePoint.knowledge_point_id)
    .filter(KnowledgePackagePoint.package_id == 433).all()
]
if p433_point_ids:
    kps_433 = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(p433_point_ids)).all()
    for kp in kps_433:
        print(f"  id={kp.id:>5}  name={kp.canonical_name}")

print(f"\n{'='*70}")
print("3. PACKAGE-TO-POINT LINKAGE (KnowledgePackagePoint)")
print("=" * 70)
kpp_stats = db.query(
    KnowledgePackagePoint.relation_type, func.count()
).group_by(KnowledgePackagePoint.relation_type).all()
print(f"By relation_type: {kpp_stats}")

kpp_approval = db.query(
    KnowledgePackagePoint.approved_status, func.count()
).group_by(KnowledgePackagePoint.approved_status).all()
print(f"By approved_status: {kpp_approval}")

# How many KPs shared across packages?
kp_pkg_count = db.query(
    KnowledgePackagePoint.knowledge_point_id,
    func.count(func.distinct(KnowledgePackagePoint.package_id)).label('pkg_count')
).group_by(KnowledgePackagePoint.knowledge_point_id)\
 .having(func.count(func.distinct(KnowledgePackagePoint.package_id)) > 1).all()

print(f"Knowledge points shared across >1 package: {len(kp_pkg_count)}")
if kp_pkg_count:
    for kp_id, pkg_cnt in sorted(kp_pkg_count, key=lambda x: -x[1])[:15]:
        kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
        name = kp.canonical_name if kp else "???"
        print(f"  KP id={kp_id} '{name}': used by {pkg_cnt} packages")

distinct_linked_kps = db.query(KnowledgePackagePoint.knowledge_point_id).distinct().count()
print(f"Distinct KPs linked to any package: {distinct_linked_kps}")
print(f"Orphan KPs (not linked to any package): {total_kps - distinct_linked_kps}")

print(f"\n{'='*70}")
print("4. ENTITY GRAPH EDGES — All edge patterns")
print("=" * 70)
edge_types = db.query(
    EntityGraphEdge.relation_type,
    EntityGraphEdge.source_entity_type,
    EntityGraphEdge.target_entity_type,
    func.count()
).group_by(
    EntityGraphEdge.relation_type,
    EntityGraphEdge.source_entity_type,
    EntityGraphEdge.target_entity_type,
).order_by(func.count().desc()).all()

print(f"Total EntityGraphEdge records: {sum(e[3] for e in edge_types)}")
for rt, src, tgt, cnt in edge_types:
    print(f"  {src} -[{rt}]-> {tgt}: {cnt}")

# Critical missing edges
kp_to_kp_edges = db.query(EntityGraphEdge).filter(
    EntityGraphEdge.source_entity_type == "knowledge_point",
    EntityGraphEdge.target_entity_type == "knowledge_point"
).count()
q_to_kp_edges = db.query(EntityGraphEdge).filter(
    EntityGraphEdge.source_entity_type == "question_item",
    EntityGraphEdge.target_entity_type == "knowledge_point"
).count()
print(f"\nkp→kp edges: {kp_to_kp_edges} | question→kp edges: {q_to_kp_edges}")

print(f"\n{'='*70}")
print("5. KnowledgePointRelation — KP-to-KP relationships")
print("=" * 70)
kpr_count = db.query(KnowledgePointRelation).count()
print(f"Total KnowledgePointRelation records: {kpr_count}")
if kpr_count > 0:
    kpr_types = db.query(
        KnowledgePointRelation.relation_type, func.count()
    ).group_by(KnowledgePointRelation.relation_type).all()
    print(f"By relation_type: {kpr_types}")
    kpr_approval = db.query(
        KnowledgePointRelation.approved_status, func.count()
    ).group_by(KnowledgePointRelation.approved_status).all()
    print(f"By approved_status: {kpr_approval}")
    # Show a few examples
    print("Samples:")
    for rel in db.query(KnowledgePointRelation).limit(10).all():
        src = db.query(KnowledgePoint).filter(KnowledgePoint.id == rel.source_knowledge_point_id).first()
        tgt = db.query(KnowledgePoint).filter(KnowledgePoint.id == rel.target_knowledge_point_id).first()
        print(f"  '{src.canonical_name if src else '?'}' -[{rel.relation_type}]-> '{tgt.canonical_name if tgt else '?'}'")

print(f"\n{'='*70}")
print("6. KnowledgeQuestionLink — Question-to-Point bridge")
print("=" * 70)
qlinks = db.query(KnowledgeQuestionLink).count()
print(f"Total KnowledgeQuestionLink records: {qlinks}")
if qlinks > 0:
    distinct_q = db.query(KnowledgeQuestionLink.question_item_id).distinct().count()
    distinct_kp = db.query(KnowledgeQuestionLink.knowledge_point_id).distinct().count()
    print(f"Distinct questions bridged: {distinct_q}")
    print(f"Distinct knowledge points linked: {distinct_kp}")

    # Check: are bridge links reflected in EntityGraphEdge?
    bridge_in_edges = db.query(EntityGraphEdge).filter(
        EntityGraphEdge.relation_type == "tests",
        EntityGraphEdge.source_entity_type == "question_item",
    ).count()
    print(f"question→kp EntityGraphEdge records: {bridge_in_edges}")
    print(f"BRIDGE GAP: {qlinks} bridge records vs {bridge_in_edges} graph edges")

print(f"\n{'='*70}")
print("7. NAMING ANALYSIS — Cross-package consistency")
print("=" * 70)

# Get ALL knowledge points
all_kps = db.query(KnowledgePoint.id, KnowledgePoint.canonical_name, KnowledgePoint.subject,
                   KnowledgePoint.source_origin).all()

# Check for exact name collisions across different IDs
name_to_ids = defaultdict(list)
for kp in all_kps:
    name_to_ids[kp.canonical_name].append(kp.id)
name_dupes = {k: v for k, v in name_to_ids.items() if len(v) > 1}
print(f"KP names duplicated across different IDs: {len(name_dupes)}")
if name_dupes:
    print("Examples of duplicate names:")
    for name, ids in sorted(name_dupes.items())[:15]:
        for kp_id in ids:
            kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
            print(f"  '{name}' id={kp_id} source={kp.source_origin}")

# Check "families" of similar names (same prefix)
prefix3 = defaultdict(list)
for kp in all_kps:
    key = kp.canonical_name[:3] if len(kp.canonical_name) >= 3 else kp.canonical_name
    prefix3[key].append(kp.canonical_name)

similar_groups = {k: list(set(v)) for k, v in prefix3.items() if len(set(v)) >= 3}
print(f"\nName prefix groups (>3 KPs sharing first 3 chars): {len(similar_groups)}")
for prefix, names in sorted(similar_groups.items())[:12]:
    print(f"  prefix='{prefix}': {names}")

# Check LLM vs non-LLM naming patterns
llm_ids = [kp[0] for kp in all_kps if kp[3] in ('model', 'llm')]
rule_ids = [kp[0] for kp in all_kps if kp[3] not in ('model', 'llm')]
llm_names = [kp[1] for kp in all_kps if kp[3] in ('model', 'llm')]
rule_names = [kp[1] for kp in all_kps if kp[3] not in ('model', 'llm')]

print(f"\nLLM-origin KPs: {len(llm_ids)} ({len(set(llm_names))} unique names)")
print(f"Rule/original KPs: {len(rule_ids)} ({len(set(rule_names))} unique names)")

if llm_names:
    avg_len_llm = sum(len(n) for n in llm_names) / len(llm_names)
    print(f"LLM KP avg name length: {avg_len_llm:.1f} chars")
if rule_names:
    avg_len_rule = sum(len(n) for n in rule_names) / len(rule_names)
    print(f"Rule KP avg name length: {avg_len_rule:.1f} chars")

# Cross-origin name overlap
llm_name_set = set(llm_names)
rule_name_set = set(rule_names)
shared_names = llm_name_set & rule_name_set
print(f"\nNames appearing in BOTH LLM and rule KPs: {len(shared_names)}")
if shared_names:
    print("  (these WOULD connect if they were a single KP entity):")
    for n in sorted(shared_names)[:20]:
        print(f"    '{n}'")

print(f"\n{'='*70}")
print("8. PACKAGE COUNT & DATA VOLUME")
print("=" * 70)
pkg_count = db.query(KnowledgePackage).count()
print(f"Total knowledge packages: {pkg_count}")
block_count = db.query(KnowledgeBlock).count()
print(f"Total knowledge blocks: {block_count}")
atom_count = db.query(KnowledgeAtom).count()
print(f"Total knowledge atoms: {atom_count}")

db.close()
print("\n=== AUDIT COMPLETE ===")
