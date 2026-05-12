"""Show what a knowledge package contributed to Neo4j graph."""
import sys
sys.path.insert(0, r"D:\10739\Exam-Analysis-Suite")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from collections import Counter
from shared.database import SessionLocal
from shared.models import EntityGraphEdge, KnowledgePackage

PACKAGE_ID = 433

db = SessionLocal()

# 1. Package info
pkg = db.query(KnowledgePackage).filter(KnowledgePackage.id == PACKAGE_ID).first()
if not pkg:
    print(f"Package {PACKAGE_ID} not found")
    sys.exit(1)

print(f"=== Package {PACKAGE_ID}: {pkg.package_title} ===")

# 2. EntityGraphEdge stats from PG
edges = (
    db.query(EntityGraphEdge)
    .filter(EntityGraphEdge.source_entity_type == "knowledge_package",
            EntityGraphEdge.source_entity_id == PACKAGE_ID)
    .all()
)

print(f"\n--- EntityGraphEdge (from PG, where source=knowledge_package:{PACKAGE_ID}) ---")
print(f"Total edges: {len(edges)}")

rel_types = Counter(e.relation_type for e in edges)
target_types = Counter(e.target_entity_type for e in edges)

print(f"By relation type: {dict(rel_types)}")
print(f"By target entity type: {dict(target_types)}")

for rel_type in sorted(rel_types):
    print(f"\n  [{rel_type}] ({rel_types[rel_type]} edges):")
    for e in edges:
        if e.relation_type == rel_type:
            print(f"    → {e.target_entity_type}:{e.target_entity_id}  (weight={e.weight_score}, confidence={e.confidence})")

# 3. Also show "incoming" edges (where package is the target)
incoming = (
    db.query(EntityGraphEdge)
    .filter(EntityGraphEdge.target_entity_type == "knowledge_package",
            EntityGraphEdge.target_entity_id == PACKAGE_ID)
    .all()
)
if incoming:
    print(f"\n--- Incoming edges (target=knowledge_package:{PACKAGE_ID}): {len(incoming)} ---")
    for e in incoming:
        print(f"  {e.source_entity_type}:{e.source_entity_id} -[{e.relation_type}]-> package:{PACKAGE_ID}")

# 4. Neo4j direct query
from analyzer.app.graph_db import db as graph_db

print(f"\n--- Neo4j: nodes related to package {PACKAGE_ID} ---")
pkg_key = f"knowledge_package:{PACKAGE_ID}"

# Count nodes
node_result = graph_db.run_query(
    "MATCH (n:KnowledgePackage {entity_key: $key}) "
    "OPTIONAL MATCH (n)-[r]-(related) "
    "WHERE related.entity_type IS NOT NULL "
    "RETURN DISTINCT related.entity_type AS entity_type, "
    "labels(related) AS labels, "
    "related.entity_id AS entity_id, "
    "related.name AS name "
    "ORDER BY related.entity_type, related.entity_id",
    {"key": pkg_key}
)

type_counts = Counter()
for rec in node_result:
    etype = rec.get("entity_type") or "unknown"
    type_counts[etype] += 1

print(f"Connected node types: {dict(type_counts)}")
print(f"Total connected nodes: {sum(type_counts.values())}")

for rec in node_result[:50]:
    etype = rec.get("entity_type") or "unknown"
    eid = rec.get("entity_id") or "?"
    name = (rec.get("name") or "")[:80]
    print(f"  {etype}:{eid}  name={name}")

# Count relationships
rel_result = graph_db.run_query(
    "MATCH (n:KnowledgePackage {entity_key: $key})-[r]-(related) "
    "RETURN type(r) AS rel_type, COUNT(r) AS cnt "
    "ORDER BY rel_type",
    {"key": pkg_key}
)

rel_counts = {r.get("rel_type"): r.get("cnt") for r in rel_result}
print(f"\nRelationship breakdown: {rel_counts}")
print(f"Total relationships: {sum(rel_counts.values())}")

# Count nodes created by this package (including non-package nodes)
all_nodes = graph_db.run_query(
    "MATCH (n:KnowledgePackage {entity_key: $key})-[r]-(related) "
    "RETURN COUNT(DISTINCT related) AS cnt",
    {"key": pkg_key}
)
print(f"Distinct related Neo4j nodes: {all_nodes[0].get('cnt') if all_nodes else 0}")

db.close()
