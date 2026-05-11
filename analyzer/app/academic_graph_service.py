from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from shared import models

from . import knowledge_graph_projection as kg_projection
from .graph_db import db as graph_db

logger = logging.getLogger(__name__)


ENTITY_LABELS = {
    "knowledge_point": "KnowledgePoint",
    "knowledge_package": "KnowledgePackage",
    "knowledge_block": "KnowledgeBlock",
    "knowledge_atom": "KnowledgeAtom",
    "knowledge_derivative": "KnowledgeDerivative",
    "question_item": "Question",
    "student": "Student",
    "exam_session": "ExamSession",
    "mistake_pattern": "MistakePattern",
    "strategy_card": "StrategyCard",
}


def _node_key(entity_type: str, entity_id: Any) -> str:
    return f"{entity_type}:{entity_id}"


def _sanitize_rel_type(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", (value or "").strip().upper())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "RELATED"


class AcademicGraphService:
    def _merge_node(self, *, label: str, entity_key: str, properties: Dict[str, Any]) -> int:
        query = (
            f"MERGE (n:{label} {{entity_key: $entity_key}}) "
            "SET n += $properties "
            "RETURN 1 AS written"
        )
        rows = graph_db.run_query(query, {"entity_key": entity_key, "properties": properties})
        return 1 if rows else 0

    def _merge_relationship(
        self,
        *,
        from_label: str,
        from_key: str,
        to_label: str,
        to_key: str,
        rel_type: str,
        properties: Dict[str, Any],
    ) -> int:
        safe_rel = _sanitize_rel_type(rel_type)
        query = (
            f"MATCH (a:{from_label} {{entity_key: $from_key}}) "
            f"MATCH (b:{to_label} {{entity_key: $to_key}}) "
            f"MERGE (a)-[r:{safe_rel}]->(b) "
            "SET r += $properties "
            "RETURN 1 AS written"
        )
        rows = graph_db.run_query(
            query,
            {"from_key": from_key, "to_key": to_key, "properties": properties},
        )
        return 1 if rows else 0

    def _build_entity_properties(self, db: Session, entity_type: str, entity_id: int) -> Tuple[str, Dict[str, Any]]:
        label = ENTITY_LABELS.get(entity_type, "Resource")
        payload: Dict[str, Any] = {
            "entity_key": _node_key(entity_type, entity_id),
            "entity_type": entity_type,
            "entity_id": int(entity_id),
        }
        if entity_type == "knowledge_point":
            row = db.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == entity_id).first()
            if row:
                payload.update(
                    {
                        "name": row.canonical_name,
                        "subject": row.subject,
                        "grade": row.grade_scope,
                        "review_status": row.review_status,
                    }
                )
        elif entity_type == "knowledge_package":
            row = db.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == entity_id).first()
            if row:
                payload.update(
                    {
                        "name": row.package_title,
                        "subject": row.subject,
                        "grade": row.grade,
                        "review_status": row.review_status,
                    }
                )
        elif entity_type == "knowledge_block":
            row = db.query(models.KnowledgeBlock).filter(models.KnowledgeBlock.id == entity_id).first()
            if row:
                payload.update(
                    {
                        "name": row.section_path or f"block:{row.id}",
                        "block_role": row.block_role,
                        "package_id": row.package_id,
                    }
                )
        elif entity_type == "knowledge_atom":
            row = db.query(models.KnowledgeAtom).filter(models.KnowledgeAtom.id == entity_id).first()
            if row:
                payload.update(
                    {
                        "name": (row.canonical_text or "")[:120] or f"atom:{row.id}",
                        "atom_type": row.atom_type,
                        "package_id": row.package_id,
                    }
                )
        elif entity_type == "knowledge_derivative":
            row = db.query(models.KnowledgeDerivative).filter(models.KnowledgeDerivative.id == entity_id).first()
            if row:
                content = row.generated_content or {}
                payload.update(
                    {
                        "name": str(content.get("title") or row.derivative_type),
                        "derivative_type": row.derivative_type,
                        "target_audience": row.target_audience,
                        "review_status": row.review_status,
                    }
                )
        elif entity_type == "question_item":
            row = db.query(models.QuestionItem).filter(models.QuestionItem.id == entity_id).first()
            if row:
                payload.update(
                    {
                        "name": (row.stem_plain_text or "")[:120] or f"question:{row.id}",
                        "subject": row.subject,
                        "grade": row.grade,
                        "question_type": row.question_type,
                    }
                )
        return label, payload

    def sync_package_projection(self, db: Session, package_id: int) -> Dict[str, Any]:
        kg_projection.project_package(db, package_id, respect_flag=False)
        edges = kg_projection.list_edges_for_package(db, package_id, limit=5000)
        synced_nodes = 0
        synced_relationships = 0
        seen_nodes = set()
        for edge in edges:
            src_type = str(edge.get("source_entity_type") or "")
            tgt_type = str(edge.get("target_entity_type") or "")
            src_id = int(edge.get("source_entity_id"))
            tgt_id = int(edge.get("target_entity_id"))
            for entity_type, entity_id in ((src_type, src_id), (tgt_type, tgt_id)):
                key = (entity_type, entity_id)
                if key in seen_nodes:
                    continue
                seen_nodes.add(key)
                label, props = self._build_entity_properties(db, entity_type, entity_id)
                synced_nodes += self._merge_node(label=label, entity_key=props["entity_key"], properties=props)

            src_label, src_props = self._build_entity_properties(db, src_type, src_id)
            tgt_label, tgt_props = self._build_entity_properties(db, tgt_type, tgt_id)
            rel_props = {
                "relation_type": edge.get("relation_type"),
                "weight_score": edge.get("weight_score"),
                "confidence": edge.get("confidence"),
                "source_origin": edge.get("source_origin"),
                "evidence_json": json.dumps(edge.get("evidence") or {}, ensure_ascii=False),
            }
            synced_relationships += self._merge_relationship(
                from_label=src_label,
                from_key=src_props["entity_key"],
                to_label=tgt_label,
                to_key=tgt_props["entity_key"],
                rel_type=str(edge.get("relation_type") or "RELATED"),
                properties=rel_props,
            )

        # Derivative relationships are part of the learning intervention chain.
        point_ids = {
            pid
            for (pid,) in db.query(models.KnowledgePackagePoint.knowledge_point_id)
            .filter(models.KnowledgePackagePoint.package_id == package_id)
            .all()
        }
        if point_ids:
            derivatives = (
                db.query(models.KnowledgeDerivative)
                .filter(models.KnowledgeDerivative.knowledge_point_id.in_(list(point_ids)))
                .all()
            )
            for row in derivatives:
                kp_label, kp_props = self._build_entity_properties(db, "knowledge_point", int(row.knowledge_point_id))
                d_label, d_props = self._build_entity_properties(db, "knowledge_derivative", int(row.id))
                synced_nodes += self._merge_node(label=kp_label, entity_key=kp_props["entity_key"], properties=kp_props)
                synced_nodes += self._merge_node(label=d_label, entity_key=d_props["entity_key"], properties=d_props)
                synced_relationships += self._merge_relationship(
                    from_label=kp_label,
                    from_key=kp_props["entity_key"],
                    to_label=d_label,
                    to_key=d_props["entity_key"],
                    rel_type="HAS_DERIVATIVE",
                    properties={
                        "relation_type": "has_derivative",
                        "target_audience": row.target_audience,
                        "review_status": row.review_status,
                    },
                )

        return {
            "status": "ok",
            "package_id": package_id,
            "synced_nodes": synced_nodes,
            "synced_relationships": synced_relationships,
            "scope": "knowledge_package",
        }

    def sync_all_knowledge_projection(self, db: Session) -> Dict[str, Any]:
        package_ids = [pid for (pid,) in db.query(models.KnowledgePackage.id).order_by(models.KnowledgePackage.id.asc()).all()]
        total_nodes = 0
        total_relationships = 0
        for package_id in package_ids:
            result = self.sync_package_projection(db, int(package_id))
            total_nodes += int(result.get("synced_nodes") or 0)
            total_relationships += int(result.get("synced_relationships") or 0)
        return {
            "status": "ok",
            "package_count": len(package_ids),
            "synced_nodes": total_nodes,
            "synced_relationships": total_relationships,
            "scope": "all_knowledge_packages",
        }

    def sync_exam_session_state(
        self,
        db: Session,
        exam_session_id: int,
        *,
        question_analyses: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        exam_session = db.query(models.ExamSession).filter(models.ExamSession.id == exam_session_id).first()
        if not exam_session:
            raise ValueError(f"ExamSession {exam_session_id} 不存在")

        synced_nodes = 0
        synced_relationships = 0

        student_key = _node_key("student", exam_session.student_id)
        synced_nodes += self._merge_node(
            label=ENTITY_LABELS["student"],
            entity_key=student_key,
            properties={
                "entity_key": student_key,
                "entity_type": "student",
                "entity_id": int(exam_session.student_id),
                "name": f"student:{exam_session.student_id}",
            },
        )
        session_key = _node_key("exam_session", exam_session.id)
        synced_nodes += self._merge_node(
            label=ENTITY_LABELS["exam_session"],
            entity_key=session_key,
            properties={
                "entity_key": session_key,
                "entity_type": "exam_session",
                "entity_id": int(exam_session.id),
                "subject": exam_session.subject,
                "matched_paper_id": exam_session.matched_paper_id,
                "analysis_status": exam_session.analysis_status,
            },
        )
        synced_relationships += self._merge_relationship(
            from_label=ENTITY_LABELS["student"],
            from_key=student_key,
            to_label=ENTITY_LABELS["exam_session"],
            to_key=session_key,
            rel_type="TOOK",
            properties={"relation_type": "took"},
        )

        analyses_by_exam_question = {
            int(item.get("exam_question_id")): item for item in (question_analyses or []) if item.get("exam_question_id") is not None
        }
        questions = (
            db.query(models.ExamSessionQuestion)
            .filter(models.ExamSessionQuestion.exam_session_id == exam_session_id)
            .order_by(models.ExamSessionQuestion.id.asc())
            .all()
        )
        for row in questions:
            if row.question_item_id:
                q_label, q_props = self._build_entity_properties(db, "question_item", int(row.question_item_id))
                synced_nodes += self._merge_node(label=q_label, entity_key=q_props["entity_key"], properties=q_props)
                synced_relationships += self._merge_relationship(
                    from_label=ENTITY_LABELS["exam_session"],
                    from_key=session_key,
                    to_label=q_label,
                    to_key=q_props["entity_key"],
                    rel_type="HAS_QUESTION",
                    properties={
                        "relation_type": "has_question",
                        "source_question_no": row.source_question_no,
                        "match_confidence": float(row.match_confidence or 0.0) if row.match_confidence is not None else None,
                    },
                )
            analysis = analyses_by_exam_question.get(int(row.id))
            if not analysis:
                continue
            for kp in analysis.get("knowledge_points") or []:
                kp_id = kp.get("knowledge_point_id")
                if kp_id is None:
                    continue
                kp_label, kp_props = self._build_entity_properties(db, "knowledge_point", int(kp_id))
                synced_nodes += self._merge_node(label=kp_label, entity_key=kp_props["entity_key"], properties=kp_props)
                if row.question_item_id:
                    q_label, q_props = self._build_entity_properties(db, "question_item", int(row.question_item_id))
                    synced_relationships += self._merge_relationship(
                        from_label=q_label,
                        from_key=q_props["entity_key"],
                        to_label=kp_label,
                        to_key=kp_props["entity_key"],
                        rel_type="TESTS",
                        properties={
                            "relation_type": "tests",
                            "relevance_score": kp.get("relevance_score"),
                            "confidence": kp.get("confidence"),
                            "exam_session_id": exam_session_id,
                        },
                    )
                mastery = str(kp.get("mastery_status") or analysis.get("mastery_level") or "UNCERTAIN").upper()
                if mastery == "MASTERED":
                    rel_name = "MASTERED"
                elif mastery == "WEAK":
                    rel_name = "WEAK_ON"
                else:
                    rel_name = "UNCERTAIN_ON"
                synced_relationships += self._merge_relationship(
                    from_label=ENTITY_LABELS["student"],
                    from_key=student_key,
                    to_label=kp_label,
                    to_key=kp_props["entity_key"],
                    rel_type=rel_name,
                    properties={
                        "relation_type": rel_name.lower(),
                        "exam_session_id": exam_session_id,
                        "source_question_no": row.source_question_no,
                        "confidence": analysis.get("confidence"),
                    },
                )
            error_pattern = analysis.get("error_pattern") or {}
            if error_pattern.get("code"):
                ep_key = _node_key("mistake_pattern", error_pattern["code"])
                synced_nodes += self._merge_node(
                    label=ENTITY_LABELS["mistake_pattern"],
                    entity_key=ep_key,
                    properties={
                        "entity_key": ep_key,
                        "entity_type": "mistake_pattern",
                        "entity_id": error_pattern["code"],
                        "name": error_pattern.get("name") or error_pattern["code"],
                        "category": error_pattern.get("category"),
                    },
                )
                if row.question_item_id:
                    q_key = _node_key("question_item", row.question_item_id)
                    synced_relationships += self._merge_relationship(
                        from_label=ENTITY_LABELS["question_item"],
                        from_key=q_key,
                        to_label=ENTITY_LABELS["mistake_pattern"],
                        to_key=ep_key,
                        rel_type="TRIGGERED_ERROR",
                        properties={
                            "relation_type": "triggered_error",
                            "exam_session_id": exam_session_id,
                            "source_question_no": row.source_question_no,
                        },
                    )

        return {
            "status": "ok",
            "exam_session_id": exam_session_id,
            "synced_nodes": synced_nodes,
            "synced_relationships": synced_relationships,
            "scope": "exam_session_state",
        }

    def fetch_question_context(
        self,
        *,
        question_item_id: Optional[int] = None,
        knowledge_point_ids: Optional[Sequence[int]] = None,
        exam_session_id: Optional[int] = None,
        max_depth: int = 2,
        limit: int = 8,
    ) -> Dict[str, Any]:
        keys: List[str] = []
        if question_item_id is not None:
            keys.append(_node_key("question_item", question_item_id))
        for kp_id in knowledge_point_ids or []:
            keys.append(_node_key("knowledge_point", kp_id))
        if exam_session_id is not None:
            keys.append(_node_key("exam_session", exam_session_id))
        if not keys:
            return {"summary": "", "nodes": [], "edges": []}

        depth = max(1, min(int(max_depth), 3))
        query = f"""
        UNWIND $keys AS entityKey
        MATCH (root {{entity_key: entityKey}})
        OPTIONAL MATCH path=(root)-[*1..{depth}]-(other)
        WITH root, path
        ORDER BY CASE WHEN path IS NULL THEN 0 ELSE length(path) END ASC
        LIMIT $limit
        RETURN root, path
        """
        rows = graph_db.run_query(query, {"keys": keys, "limit": int(limit)})
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        summaries: List[str] = []
        for record in rows:
            root = record.get("root")
            path = record.get("path")
            if root:
                rprops = dict(root)
                nodes[rprops.get("entity_key")] = {
                    "node_type": rprops.get("entity_type") or "resource",
                    "node_id": str(rprops.get("entity_key") or ""),
                    "label": str(rprops.get("name") or rprops.get("entity_key") or ""),
                    "properties": rprops,
                }
            if path is None:
                continue
            for node in path.nodes:
                props = dict(node)
                nodes[props.get("entity_key")] = {
                    "node_type": props.get("entity_type") or "resource",
                    "node_id": str(props.get("entity_key") or ""),
                    "label": str(props.get("name") or props.get("entity_key") or ""),
                    "properties": props,
                }
            for rel in path.relationships:
                start_key = rel.start_node.get("entity_key")
                end_key = rel.end_node.get("entity_key")
                rel_type = type(rel).__name__ or "RELATED"
                edge_payload = {
                    "relation_type": rel_type.lower(),
                    "from_node_id": str(start_key or ""),
                    "to_node_id": str(end_key or ""),
                    "weight": rel.get("weight_score"),
                    "confidence": rel.get("confidence"),
                }
                edges.append(edge_payload)
                start_name = rel.start_node.get("name") or start_key
                end_name = rel.end_node.get("name") or end_key
                summaries.append(f"{start_name} -[{rel_type.lower()}]-> {end_name}")
        summary = "；".join(summaries[:5])
        return {
            "summary": summary,
            "nodes": list(nodes.values()),
            "edges": edges[: max(1, int(limit) * 2)],
        }


service = AcademicGraphService()
