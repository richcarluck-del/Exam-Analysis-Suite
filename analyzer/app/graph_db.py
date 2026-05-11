import logging
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

from .config import NEO4J_DB, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

logger = logging.getLogger(__name__)

# Labels in the actual Neo4j schema
ENTRY_LABELS = ["KnowledgePoint"]
TRAVERSAL_LABELS = {"KnowledgePoint", "KnowledgeBlock", "KnowledgeDerivative", "KnowledgePackage"}


def _graph_score(path_nodes: List[Dict[str, Any]], depth: int, entity_similarity: Optional[float] = None) -> float:
    """Calibrated graph result scoring.

    Two dimensions:
      1. Relevance — semantic similarity to query, or keyword overlap as fallback
      2. Closeness — shorter paths are more directly connected (depth penalty)

    With semantic similarity (preferred):
      score = similarity * 0.65 + closeness * 0.35
    Without (keyword fallback):
      score = keyword_overlap * 0.50 + closeness * 0.50
    """
    closeness = 1.0 / (depth + 1)
    if entity_similarity is not None:
        return round(entity_similarity * 0.65 + closeness * 0.35, 6)

    node_count = max(len(path_nodes), 1)
    keyword_hits = sum(1 for node in path_nodes if (node.get("name") or "").strip())
    overlap_ratio = min(1.0, keyword_hits / node_count) if node_count > 0 else 0.0
    return round(overlap_ratio * 0.50 + closeness * 0.50, 6)


class GraphDB:
    def __init__(self, uri: str, user: str, password: str, database: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database

    def close(self) -> None:
        self._driver.close()

    def run_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Any]:
        with self._driver.session(database=self._database) as session:
            result = session.run(query, parameters)
            return [record for record in result]

    def add_entities_and_relationships(self, data: Dict[str, Any]) -> None:
        """Upsert KnowledgePoint nodes and RELATES_* relationships.

        This is the canonical write path — the actual schema uses KnowledgePoint
        and Question labels (not the legacy Entity label).
        """
        with self._driver.session(database=self._database) as session:
            for entity in data.get("entities", []):
                session.run(
                    "MERGE (n:KnowledgePoint {name: $name}) "
                    "SET n.context = COALESCE($context, n.context, '')",
                    name=entity["name"],
                    context=entity.get("context", ""),
                )

            for rel in data.get("relationships", []):
                session.run(
                    "MATCH (a:KnowledgePoint {name: $source}) "
                    "MATCH (b:KnowledgePoint {name: $target}) "
                    "MERGE (a)-[r:RELATES_ADJACENT {type: $type}]->(b)",
                    source=rel["source"],
                    target=rel["target"],
                    type=rel.get("type", "RELATES_ADJACENT"),
                )

    def _traverse(
        self,
        entity_names: List[str],
        entity_scores: Dict[str, float],
        max_depth: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Multi-hop traversal from matched KnowledgePoint nodes.

        Traverses bidirectionally across all relationship types, collecting
        KnowledgePoint, KnowledgeBlock, KnowledgeDerivative nodes.
        """
        if not entity_names:
            return []

        depth = max(1, min(int(max_depth), 3))
        query = """
        UNWIND $entity_names AS ename
        MATCH (root:KnowledgePoint {name: ename})
        OPTIONAL MATCH path = (root)-[*1..%d]-(related)
        WHERE ANY(label IN labels(related) WHERE label IN $traversal_labels)
        WITH ename, root, path
        ORDER BY CASE WHEN path IS NULL THEN 0 ELSE length(path) END ASC
        RETURN ename,
               root { .name, .context } AS root,
               CASE WHEN path IS NULL THEN [root { .name, .context }]
                    ELSE [node IN nodes(path)
                          WHERE ANY(lbl IN labels(node) WHERE lbl IN $traversal_labels)
                            AND node.name IS NOT NULL
                          | node { .name, .context }]
               END AS path_nodes,
               CASE WHEN path IS NULL THEN []
                    ELSE [rel IN relationships(path) | {
                        type: type(rel),
                        from: startNode(rel).name,
                        to: endNode(rel).name
                    }]
               END AS path_relationships,
               CASE WHEN path IS NULL THEN 0 ELSE length(path) END AS depth
        LIMIT $limit
        """ % depth

        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(
                    query,
                    entity_names=entity_names,
                    traversal_labels=list(TRAVERSAL_LABELS),
                    limit=limit,
                )
                rows = [record.data() for record in result]
        except Exception as exc:
            logger.warning("Graph traversal failed: %s", exc)
            return []

        seen = set()
        results: List[Dict[str, Any]] = []
        for row in rows:
            path_nodes = row.get("path_nodes") or []
            path_relationships = row.get("path_relationships") or []
            path_signature = (
                row.get("ename"),
                tuple(node.get("name") for node in path_nodes),
                tuple(
                    (rel.get("from"), rel.get("type"), rel.get("to"))
                    for rel in path_relationships
                ),
            )
            if path_signature in seen:
                continue
            seen.add(path_signature)

            depth_value = int(row.get("depth") or 0)
            similarity = entity_scores.get(row.get("ename"))
            score = _graph_score(path_nodes, depth_value, similarity)
            results.append(
                {
                    "keyword": row.get("ename"),
                    "root": row.get("root") or {},
                    "path_nodes": path_nodes,
                    "path_relationships": path_relationships,
                    "depth": depth_value,
                    "score": score,
                    "entity_similarity": similarity,
                }
            )
        return results

    def search_graph_semantic(
        self,
        entity_matches: List[Dict[str, Any]],
        max_depth: int = 2,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Semantic entity lookup → multi-hop traversal.

        entity_matches: list of {name, score} from GraphEntityIndex.search().
        """
        entity_names = [m["name"] for m in entity_matches if m.get("name")]
        entity_scores = {m["name"]: m.get("score", 0.0) for m in entity_matches}
        return self._traverse(entity_names, entity_scores, max_depth, limit)

    def search_graph(
        self, keywords: List[str], max_depth: int = 2, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Fallback keyword-based graph search on KnowledgePoint nodes."""
        normalized_keywords = [k.strip() for k in keywords if k and k.strip()]
        if not normalized_keywords:
            return []

        depth = max(1, min(int(max_depth), 3))
        query = """
        UNWIND $keywords AS keyword
        MATCH (root:KnowledgePoint)
        WHERE toLower(root.name) CONTAINS toLower(keyword)
        OPTIONAL MATCH path = (root)-[*1..%d]-(related)
        WHERE ANY(label IN labels(related) WHERE label IN $traversal_labels)
        WITH keyword, root, path
        ORDER BY CASE WHEN path IS NULL THEN 0 ELSE length(path) END ASC
        RETURN keyword,
               root { .name, .context } AS root,
               CASE WHEN path IS NULL THEN [root { .name, .context }]
                    ELSE [node IN nodes(path)
                          WHERE ANY(lbl IN labels(node) WHERE lbl IN $traversal_labels)
                            AND node.name IS NOT NULL
                          | node { .name, .context }]
               END AS path_nodes,
               CASE WHEN path IS NULL THEN []
                    ELSE [rel IN relationships(path) | {
                        type: type(rel),
                        from: startNode(rel).name,
                        to: endNode(rel).name
                    }]
               END AS path_relationships,
               CASE WHEN path IS NULL THEN 0 ELSE length(path) END AS depth
        LIMIT $limit
        """ % depth

        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(
                    query,
                    keywords=normalized_keywords,
                    traversal_labels=list(TRAVERSAL_LABELS),
                    limit=limit,
                )
                rows = [record.data() for record in result]
        except Exception as exc:
            logger.warning("Graph keyword search failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            path_nodes = row.get("path_nodes") or []
            path_relationships = row.get("path_relationships") or []
            path_signature = (
                row.get("keyword"),
                tuple(node.get("name") for node in path_nodes),
                tuple(
                    (rel.get("from"), rel.get("type"), rel.get("to"))
                    for rel in path_relationships
                ),
            )
            if path_signature in seen:
                continue
            seen.add(path_signature)

            depth_value = int(row.get("depth") or 0)
            score = _graph_score(path_nodes, depth_value, entity_similarity=None)
            results.append(
                {
                    "keyword": row.get("keyword"),
                    "root": row.get("root") or {},
                    "path_nodes": path_nodes,
                    "path_relationships": path_relationships,
                    "depth": depth_value,
                    "score": score,
                    "entity_similarity": None,
                }
            )
        return results

    def get_all_entity_names(self) -> List[Dict[str, str]]:
        """Fetch all indexable entity names from the knowledge graph.

        Pulls KnowledgePoint names (primary retrieval targets) and
        KnowledgeBlock names (secondary, for topic coverage).
        """
        entities: List[Dict[str, str]] = []
        try:
            with self._driver.session(database=self._database) as session:
                result = session.run(
                    "MATCH (n:KnowledgePoint) "
                    "WHERE n.name IS NOT NULL AND n.name <> '' "
                    "RETURN n.name AS name, "
                    "COALESCE(n.context, '') AS context"
                )
                for record in result:
                    entities.append({
                        "name": record.get("name", ""),
                        "context": record.get("context", "") or "",
                    })

                result2 = session.run(
                    "MATCH (n:KnowledgeBlock) "
                    "WHERE n.name IS NOT NULL AND n.name <> '' "
                    "RETURN n.name AS name, "
                    "COALESCE(n.context, '') AS context"
                )
                for record in result2:
                    name = record.get("name", "")
                    if not any(e["name"] == name for e in entities):
                        entities.append({
                            "name": name,
                            "context": record.get("context", "") or "",
                        })
        except Exception as exc:
            logger.warning("Failed to fetch entity names: %s", exc)
        return entities


db = GraphDB(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DB)
