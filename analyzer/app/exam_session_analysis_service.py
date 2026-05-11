from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from shared import models

from .academic_graph_service import service as academic_graph_service
from .exam_session_multimodal_service import service as exam_session_multimodal_service
from .llm_client import FatalRateLimitError
from .question_matcher import service as match_service

logger = logging.getLogger(__name__)
from . import vector_db
from .graph_db import db as graph_db

QUESTION_EVIDENCE_TYPES = [
    "question_stem",
    "question_analysis",
    "question_solution",
    "question_knowledge",
    "knowledge_point",
    "knowledge_block",
    "knowledge_atom",
    "knowledge_question_bridge",
    "knowledge_derivative",
]

KNOWLEDGE_EVIDENCE_TYPES = [
    "knowledge_point",
    "knowledge_block",
    "knowledge_atom",
    "knowledge_question_bridge",
    "knowledge_derivative",
]


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_answer(value: Optional[str]) -> str:
    normalized = _normalize_text(value).upper()
    normalized = normalized.replace("（", "(").replace("）", ")")
    return normalized


def _truncate(value: Optional[str], max_length: int = 120) -> str:
    text = _normalize_text(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


_KNOWLEDGE_QUERY_STOP_TERMS = {
    "已知",
    "下列",
    "则有",
    "的是",
    "错误",
    "正确",
    "学生答案",
}


def _extract_knowledge_query_terms(value: Optional[str]) -> List[str]:
    text = _normalize_text(value)
    raw_tokens = re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", text)
    terms: List[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        normalized = token.strip()
        if not normalized or normalized in _KNOWLEDGE_QUERY_STOP_TERMS:
            continue
        if normalized.isdigit():
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(normalized)
    return terms


def _chinese_bigrams(value: str) -> set[str]:
    chars = re.findall(r"[\u4e00-\u9fff]", value or "")
    return {"".join(chars[index:index + 2]) for index in range(max(0, len(chars) - 1))}


def _score_knowledge_name(query_text: str, knowledge_name: str) -> float:
    name = re.sub(r"\s+", "", knowledge_name or "")
    query = re.sub(r"\s+", "", query_text or "")
    if not name or not query:
        return 0.0
    query_terms = _extract_knowledge_query_terms(query_text)
    name_terms = _extract_knowledge_query_terms(knowledge_name)
    score = 0.0
    if name in query:
        score += 0.55
    if name_terms:
        score += (sum(1 for term in name_terms if term in query) / len(name_terms)) * 0.35
    if query_terms:
        score += (sum(1 for term in query_terms if term in name) / len(query_terms)) * 0.35
    query_bigrams = _chinese_bigrams(query)
    name_bigrams = _chinese_bigrams(name)
    if query_bigrams and name_bigrams:
        score += (len(query_bigrams & name_bigrams) / len(name_bigrams)) * 0.28
    name_chars = set(name)
    if name_chars:
        score += (len(name_chars & set(query)) / len(name_chars)) * 0.1
    return round(min(score, 1.0), 6)


def _format_graph_relation_type(relation_type: Optional[str]) -> str:
    relation = str(relation_type or "RELATED")
    labels = {
        "PREREQUISITE": "前置",
        "CONTAINS_BLOCK": "包含章节",
        "COVERS_POINT": "覆盖知识点",
        "HAS_DERIVATIVE": "衍生",
        "RELATED": "相关",
        "RELATES_ADJACENT": "相邻",
    }
    return labels.get(relation, relation)


def _build_graph_path_text(
    *,
    root_name: str,
    path_nodes: Sequence[Dict[str, Any]],
    path_relationships: Sequence[Dict[str, Any]],
) -> Tuple[str, str, Tuple[str, ...]]:
    node_names: List[str] = []
    for node in path_nodes:
        name = _normalize_text(node.get("name"))
        if name and name not in node_names:
            node_names.append(name)
    if not node_names and root_name:
        node_names.append(root_name)

    relation_parts: List[str] = []
    for rel in path_relationships:
        src = _truncate(rel.get("from") or "?", 32)
        tgt = _truncate(rel.get("to") or "?", 32)
        relation_parts.append(f"{src} --{_format_graph_relation_type(rel.get('type'))}--> {tgt}")

    if relation_parts:
        snippet = "图谱路径：" + " | ".join(relation_parts)
    else:
        snippet = "图谱节点：" + (node_names[0] if node_names else root_name)

    if len(node_names) >= 2:
        title = f"图谱路径：{node_names[0]} -> {node_names[-1]}"
    else:
        title = f"图谱节点：{node_names[0] if node_names else root_name}"
    return title, snippet, tuple(node_names)


def _resolve_evidence_title(hit: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    for candidate in (
        metadata.get("title"),
        metadata.get("knowledge_point_name"),
        metadata.get("canonical_name"),
        metadata.get("source"),
        metadata.get("entity_type"),
        hit.get("source_type"),
    ):
        normalized = _normalize_text(candidate)
        if normalized:
            return normalized
    return "evidence"


def _build_report_evidence_candidate(
    *,
    hit: Dict[str, Any],
    bucket: str,
    role: str,
    knowledge_point_map: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    metadata = dict(hit.get("metadata") or {})
    kp_id = _safe_int(metadata.get("knowledge_point_id"))
    kp_ref = knowledge_point_map.get(kp_id) if kp_id is not None else None
    if kp_ref:
        metadata.setdefault("knowledge_point_name", kp_ref.get("canonical_name"))
        metadata.setdefault("knowledge_relation_type", kp_ref.get("relation_type"))
        metadata.setdefault("knowledge_mastery_status", kp_ref.get("mastery_status"))
    entity_type = str(metadata.get("entity_type") or "")
    base_score = _safe_float(
        hit.get("lightweight_score")
        or hit.get("score")
        or hit.get("vector_score")
        or hit.get("text_score")
    )
    entity_bonus = {
        "knowledge_question_bridge": 0.14,
        "knowledge_block": 0.1,
        "knowledge_derivative": 0.09,
        "knowledge_atom": 0.06,
        "knowledge_point_graph": 0.08,
        "question_analysis": 0.08,
        "question_solution": 0.06,
        "question_knowledge": 0.06,
        "question_stem": 0.04,
    }.get(entity_type, 0.0)
    source_bonus = {
        "vector+text": 0.05,
        "graph": 0.04,
        "text": 0.02,
        "vector": 0.02,
    }.get(str(hit.get("source_type") or ""), 0.0)
    priority = base_score + entity_bonus + source_bonus
    if kp_ref:
        priority += min(
            0.08,
            max(
                _safe_float(kp_ref.get("confidence")),
                _safe_float(kp_ref.get("relevance_score")),
            ) * 0.15,
        )
    if bucket == "graph":
        graph_depth = _safe_int(metadata.get("graph_depth")) or 0
        priority += 0.03 if graph_depth <= 1 else 0.0
    if bucket == "knowledge" and entity_type == "knowledge_question_bridge":
        priority += 0.03
    snippet = _truncate(hit.get("snippet") or hit.get("content") or "", max_length=220)
    return {
        "bucket": bucket,
        "priority": round(priority, 6),
        "source_type": str(hit.get("source_type") or "vector"),
        "source_id": str(hit.get("id") or metadata.get("entity_id") or ""),
        "title": _resolve_evidence_title(hit, metadata),
        "snippet": snippet,
        "score": round(_safe_float(hit.get("score")), 4),
        "evidence_role": role,
        "metadata": metadata,
    }


class ExamSessionAnalysisService:
    def generate_reports(
        self,
        db: Session,
        exam_session_id: int,
        *,
        sync_neo4j: bool = True,
        persist_snapshot: bool = True,
    ) -> Dict[str, Any]:
        exam_session = db.query(models.ExamSession).filter(models.ExamSession.id == exam_session_id).first()
        if not exam_session:
            raise ValueError(f"ExamSession {exam_session_id} 不存在")

        question_rows = (
            db.query(models.ExamSessionQuestion)
            .filter(models.ExamSessionQuestion.exam_session_id == exam_session_id)
            .order_by(models.ExamSessionQuestion.id.asc())
            .all()
        )
        attempt_rows = (
            db.query(models.StudentAttempt)
            .filter(models.StudentAttempt.exam_session_id == exam_session_id)
            .order_by(models.StudentAttempt.id.asc())
            .all()
        )
        attempts_by_question = {row.exam_question_id: row for row in attempt_rows}

        question_item_ids = [row.question_item_id for row in question_rows if row.question_item_id is not None]
        question_items = (
            db.query(models.QuestionItem)
            .filter(models.QuestionItem.id.in_(question_item_ids))
            .all()
            if question_item_ids
            else []
        )
        question_item_map = {row.id: row for row in question_items}

        link_rows = (
            db.query(models.KnowledgeQuestionLink, models.KnowledgePoint)
            .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgeQuestionLink.knowledge_point_id)
            .filter(models.KnowledgeQuestionLink.question_item_id.in_(question_item_ids))
            .all()
            if question_item_ids
            else []
        )
        links_by_question: Dict[int, List[Tuple[models.KnowledgeQuestionLink, models.KnowledgePoint]]] = defaultdict(list)
        for link, point in link_rows:
            links_by_question[int(link.question_item_id)].append((link, point))

        derivatives = (
            db.query(models.KnowledgeDerivative)
            .filter(models.KnowledgeDerivative.review_status == "approved")
            .all()
        )
        derivatives_by_kp: Dict[int, List[models.KnowledgeDerivative]] = defaultdict(list)
        for row in derivatives:
            derivatives_by_kp[int(row.knowledge_point_id)].append(row)

        pattern_rows = db.query(models.MistakePattern).all()
        patterns_by_category: Dict[str, models.MistakePattern] = {}
        for row in pattern_rows:
            key = (row.category or "").strip().lower()
            if key and key not in patterns_by_category:
                patterns_by_category[key] = row

        vision_llm_config, reasoning_llm_config = exam_session_multimodal_service.resolve_llm_configs(db)
        analyses: List[Dict[str, Any]] = []
        related_package_ids: set[int] = set()
        fatal_error: Optional[str] = None
        for exam_question in question_rows:
            attempt = attempts_by_question.get(exam_question.id)
            matched_item = question_item_map.get(exam_question.question_item_id) if exam_question.question_item_id else None
            match_anchors = match_service.build_anchor_pack_from_persisted_candidates(
                db,
                exam_session=exam_session,
                exam_question=exam_question,
            )
            match_anchor_type = str(match_anchors.get("primary_anchor_type") or "unanchored")
            knowledge_refs = self._merge_knowledge_refs(
                self._build_knowledge_refs(links_by_question.get(exam_question.question_item_id or -1, [])),
                self._build_knowledge_refs_from_anchor_pack(db, match_anchors),
            )
            kp_ids = [item["knowledge_point_id"] for item in knowledge_refs]
            related_package_ids.update(
                pid
                for (pid,) in db.query(models.KnowledgePackageQuestion.package_id)
                .filter(models.KnowledgePackageQuestion.question_item_id == exam_question.question_item_id)
                .all()
            )
            correctness, mastery_level, uncertainty_reason = self._infer_outcome(
                exam_question=exam_question,
                attempt=attempt,
                matched_item=matched_item,
                match_anchor_type=match_anchor_type,
            )
            evidence = self._build_retrieval_evidence(
                exam_session=exam_session,
                exam_question=exam_question,
                attempt=attempt,
                matched_item=matched_item,
                knowledge_refs=knowledge_refs,
                structural_matches=match_anchors.get("structural_matches") or [],
            )
            image_paths = exam_session_multimodal_service._collect_image_paths(attempt)
            try:
                multimodal_result = exam_session_multimodal_service.analyze_question(
                    exam_session=exam_session,
                    exam_question=exam_question,
                    attempt=attempt,
                    matched_item=matched_item,
                    knowledge_refs=knowledge_refs,
                    retrieval_evidence=evidence,
                    structural_matches=match_anchors.get("structural_matches") or [],
                    knowledge_anchors=match_anchors.get("knowledge_anchors") or [],
                    match_anchor_type=match_anchor_type,
                    baseline_correctness=correctness,
                    baseline_mastery_level=mastery_level,
                    baseline_uncertainty_reason=uncertainty_reason,
                    vision_llm_config=vision_llm_config,
                    reasoning_llm_config=reasoning_llm_config,
                )
            except FatalRateLimitError as exc:
                fatal_error = str(exc)
                logger.error("报告生成因模型限流终止: %s", exc)
                break
            correctness = multimodal_result.get("correctness") or correctness
            mastery_level = multimodal_result.get("mastery_level") or mastery_level
            uncertainty_reason = multimodal_result.get("uncertainty_reason") or uncertainty_reason
            error_pattern = self._classify_error_pattern(
                correctness=correctness,
                mastery_level=mastery_level,
                uncertainty_reason=uncertainty_reason,
                patterns_by_category=patterns_by_category,
            )
            intervention_assets = self._select_derivative_assets(
                derivatives_by_kp=derivatives_by_kp,
                knowledge_point_ids=kp_ids,
                audience="student",
                correctness=correctness,
            )
            confidence = self._compute_confidence(
                exam_question=exam_question,
                attempt=attempt,
                evidence=evidence,
                knowledge_refs=knowledge_refs,
                correctness=correctness,
            )
            model_confidence = _safe_float(multimodal_result.get("confidence_override"), fallback=0.0)
            if model_confidence > 0:
                confidence = (confidence * 0.6) + (model_confidence * 0.4)
            needs_manual_review = (
                correctness == "uncertain"
                or confidence < 0.55
                or bool(multimodal_result.get("needs_manual_review"))
            )
            if needs_manual_review and not uncertainty_reason:
                uncertainty_reason = "题目匹配或证据不足，建议人工复核"

            study_advice = multimodal_result.get("study_advice") or self._build_study_advice(
                correctness=correctness,
                knowledge_refs=knowledge_refs,
                error_pattern=error_pattern,
                intervention_assets=intervention_assets,
            )

            analysis = {
                "exam_question_id": int(exam_question.id),
                "exam_session_id": int(exam_session.id),
                "source_question_no": exam_question.source_question_no,
                "question_item_id": matched_item.id if matched_item else None,
                "match_anchor_type": match_anchor_type,
                "image_paths": image_paths,
                "match_anchor_summary": self._build_match_anchor_summary(match_anchors),
                "match_anchors": match_anchors,
                "analysis_mode": multimodal_result.get("analysis_mode"),
                "question_summary": _truncate(
                    self._pick_question_summary(
                        exam_question=exam_question,
                        matched_item=matched_item,
                        match_anchors=match_anchors,
                    ),
                    max_length=160,
                )
                or f"第 {exam_question.source_question_no} 题",
                "recognized_text": exam_question.recognized_text,
                "student_answer_raw": attempt.student_answer_raw if attempt else None,
                "correctness": correctness,
                "mastery_level": mastery_level,
                "confidence": round(confidence, 4),
                "needs_manual_review": needs_manual_review,
                "uncertainty_reason": uncertainty_reason,
                "solution_steps": multimodal_result.get("solution_steps"),
                "llm_answer": multimodal_result.get("llm_answer"),
                "visual_evidence_summary": multimodal_result.get("visual_evidence_summary"),
                "text_consistency_summary": multimodal_result.get("text_consistency_summary"),
                "knowledge_points": knowledge_refs,
                "retrieval_evidence": evidence,
                "graph_path": None,
                "error_pattern": error_pattern,
                "root_cause_hypothesis": multimodal_result.get("root_cause_hypothesis") or self._build_root_cause(
                    correctness=correctness,
                    knowledge_refs=knowledge_refs,
                    error_pattern=error_pattern,
                    uncertainty_reason=uncertainty_reason,
                ),
                "study_advice": study_advice,
                "intervention_assets": intervention_assets,
            }
            analyses.append(analysis)

        if sync_neo4j:
            for package_id in sorted(related_package_ids):
                academic_graph_service.sync_package_projection(db, int(package_id))
            academic_graph_service.sync_exam_session_state(db, exam_session.id, question_analyses=analyses)

        for analysis in analyses:
            graph_path = academic_graph_service.fetch_question_context(
                question_item_id=analysis.get("question_item_id"),
                knowledge_point_ids=[item["knowledge_point_id"] for item in analysis.get("knowledge_points") or []],
                exam_session_id=exam_session.id,
                max_depth=2,
                limit=8,
            )
            if graph_path.get("nodes") or graph_path.get("edges"):
                analysis["graph_path"] = graph_path

        knowledge_profile = self._build_knowledge_profile(db, analyses, derivatives_by_kp)
        mistake_profile = self._build_mistake_profile(analyses)
        graph_overview = self._build_graph_overview(analyses)
        student_action_plan = self._build_action_plan(
            knowledge_profile=knowledge_profile,
            mistake_profile=mistake_profile,
            analyses=analyses,
            audience="student",
        )
        teacher_action_plan = self._build_action_plan(
            knowledge_profile=knowledge_profile,
            mistake_profile=mistake_profile,
            analyses=analyses,
            audience="teacher",
        )
        parent_action_plan = self._build_action_plan(
            knowledge_profile=knowledge_profile,
            mistake_profile=mistake_profile,
            analyses=analyses,
            audience="parent",
        )

        summary = self._build_summary(exam_session, analyses, knowledge_profile)
        snapshot = None
        exam_session.analysis_status = "completed"
        if persist_snapshot:
            snapshot = models.DiagnosisSnapshot(
                student_id=exam_session.student_id,
                exam_session_id=exam_session.id,
                knowledge_profile_json=knowledge_profile,
                ability_profile_json={"question_analyses": analyses, "graph_overview": graph_overview},
                mistake_profile_json=mistake_profile,
                action_plan_json={"student": student_action_plan, "teacher": teacher_action_plan, "parent": parent_action_plan},
                llm_summary=summary.get("headline") or "AI 学情分析已生成",
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
        else:
            db.flush()

        surfaces = {
            "student": self._build_surface(
                audience="student",
                exam_session=exam_session,
                summary=summary,
                analyses=analyses,
                knowledge_profile=knowledge_profile,
                mistake_profile=mistake_profile,
                action_plan=student_action_plan,
                graph_overview=graph_overview,
            ),
            "teacher": self._build_surface(
                audience="teacher",
                exam_session=exam_session,
                summary=summary,
                analyses=analyses,
                knowledge_profile=knowledge_profile,
                mistake_profile=mistake_profile,
                action_plan=teacher_action_plan,
                graph_overview=graph_overview,
            ),
            "governance": self._build_surface(
                audience="governance",
                exam_session=exam_session,
                summary=summary,
                analyses=analyses,
                knowledge_profile=knowledge_profile,
                mistake_profile=mistake_profile,
                action_plan=parent_action_plan,
                graph_overview=graph_overview,
            ),
        }
        surfaces["teacher"]["class_breakdown"] = self._build_teacher_breakdown(analyses, knowledge_profile)
        surfaces["governance"]["governance_metrics"] = self._build_governance_metrics(
            exam_session=exam_session,
            analyses=analyses,
            knowledge_profile=knowledge_profile,
            graph_overview=graph_overview,
        )

        return {
            "exam_session_id": exam_session.id,
            "diagnosis_snapshot_id": snapshot.id if snapshot is not None else None,
            "surfaces": surfaces,
            "summary": summary,
            "fatal_error": fatal_error,
        }

    def load_report_surfaces(
        self, db: Session, exam_session_id: int
    ) -> Optional[Dict[str, Any]]:
        snapshot = (
            db.query(models.DiagnosisSnapshot)
            .filter(models.DiagnosisSnapshot.exam_session_id == exam_session_id)
            .order_by(models.DiagnosisSnapshot.generated_at.desc())
            .first()
        )
        if not snapshot:
            return None
        exam_session = db.query(models.ExamSession).filter(models.ExamSession.id == exam_session_id).first()
        if not exam_session:
            return None

        analyses = (snapshot.ability_profile_json or {}).get("question_analyses") or []
        graph_overview = (snapshot.ability_profile_json or {}).get("graph_overview") or {}
        knowledge_profile = snapshot.knowledge_profile_json or []
        mistake_profile = snapshot.mistake_profile_json or []
        action_plan_json = snapshot.action_plan_json or {}

        summary = {
            "headline": snapshot.llm_summary or "AI 学情分析已生成",
            "generated_at": str(snapshot.generated_at) if snapshot.generated_at else None,
        }

        student_action_plan = action_plan_json.get("student") or []
        teacher_action_plan = action_plan_json.get("teacher") or []
        parent_action_plan = action_plan_json.get("parent") or []

        surfaces = {
            "student": self._build_surface(
                audience="student",
                exam_session=exam_session,
                summary=summary,
                analyses=analyses,
                knowledge_profile=knowledge_profile,
                mistake_profile=mistake_profile,
                action_plan=student_action_plan,
                graph_overview=graph_overview,
            ),
            "teacher": self._build_surface(
                audience="teacher",
                exam_session=exam_session,
                summary=summary,
                analyses=analyses,
                knowledge_profile=knowledge_profile,
                mistake_profile=mistake_profile,
                action_plan=teacher_action_plan,
                graph_overview=graph_overview,
            ),
            "governance": self._build_surface(
                audience="governance",
                exam_session=exam_session,
                summary=summary,
                analyses=analyses,
                knowledge_profile=knowledge_profile,
                mistake_profile=mistake_profile,
                action_plan=parent_action_plan,
                graph_overview=graph_overview,
            ),
        }
        surfaces["teacher"]["class_breakdown"] = self._build_teacher_breakdown(analyses, knowledge_profile)
        surfaces["governance"]["governance_metrics"] = self._build_governance_metrics(
            exam_session=exam_session,
            analyses=analyses,
            knowledge_profile=knowledge_profile,
            graph_overview=graph_overview,
        )

        return {
            "exam_session_id": exam_session.id,
            "diagnosis_snapshot_id": snapshot.id,
            "surfaces": surfaces,
            "summary": summary,
            "cached": True,
        }

    def _build_knowledge_refs(
        self,
        rows: Sequence[Tuple[models.KnowledgeQuestionLink, models.KnowledgePoint]],
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        sorted_rows = sorted(
            rows,
            key=lambda item: (
                -_safe_float(item[0].relevance_score, 0.0),
                -_safe_float(item[0].confidence, 0.0),
                item[1].id,
            ),
        )
        for link, point in sorted_rows:
            relation_type = (link.relation_type or "").strip().lower()
            if relation_type == "topic_strong":
                mastery_status = "focus"
            elif relation_type == "topic_fallback":
                mastery_status = "support"
            else:
                mastery_status = "related"
            result.append(
                {
                    "knowledge_point_id": int(point.id),
                    "canonical_name": point.canonical_name,
                    "relation_type": link.relation_type,
                    "relevance_score": round(_safe_float(link.relevance_score), 4),
                    "confidence": round(_safe_float(link.confidence), 4),
                    "mastery_status": mastery_status,
                }
            )
        return result

    def _build_knowledge_refs_from_anchor_pack(
        self,
        db: Session,
        match_anchors: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        anchors = match_anchors.get("knowledge_anchors") or []
        query_text = str((match_anchors.get("diagnostics") or {}).get("query_text") or "")

        # Direct kp_id path.
        direct_kp_ids = [
            int(item["knowledge_point_id"])
            for item in anchors
            if item.get("knowledge_point_id") is not None
        ]

        # Bridge path: question_knowledge anchors carry entity_id (a question_item_id)
        # but no knowledge_point_id. Resolve via KnowledgeQuestionLink.
        bridge_qids: List[int] = []
        anchor_qid_map: Dict[int, List[Dict[str, Any]]] = {}
        for item in anchors:
            if item.get("knowledge_point_id") is not None:
                continue
            meta = item.get("metadata") or {}
            if str(meta.get("entity_type") or "").startswith("question_knowledge"):
                qid = _safe_int(meta.get("entity_id"))
                if qid is not None:
                    bridge_qids.append(qid)
                    anchor_qid_map.setdefault(qid, []).append(item)

        bridged_kp_ids: List[int] = []
        bridged_kp_names: Dict[int, str] = {}
        bridged_kp_scores: Dict[int, float] = {}
        if bridge_qids:
            bridge_links = (
                db.query(models.KnowledgeQuestionLink)
                .filter(models.KnowledgeQuestionLink.question_item_id.in_(sorted(set(bridge_qids))))
                .all()
            )
            qid_to_kp: Dict[int, List[Tuple[int, float, str]]] = {}
            for link in bridge_links:
                qid_to_kp.setdefault(int(link.question_item_id), []).append(
                    (int(link.knowledge_point_id), _safe_float(link.relevance_score) or _safe_float(link.confidence), link.relation_type or "knowledge_anchor")
                )
            for qid, items in anchor_qid_map.items():
                kp_entries = qid_to_kp.get(qid, [])
                if not kp_entries:
                    continue
                best_kp_id, best_score, relation_type = max(kp_entries, key=lambda x: x[1])
                bridged_kp_ids.append(best_kp_id)
                bridged_kp_names[best_kp_id] = f"kp:{best_kp_id}"
                anchor_best = max(_safe_float(a.get("score")) for a in items)
                bridged_kp_scores[best_kp_id] = max(bridged_kp_scores.get(best_kp_id, 0.0), anchor_best, best_score)

        all_kp_ids = sorted(set(direct_kp_ids + bridged_kp_ids))

        # Text-match fallback: when neither direct nor bridge paths produce KP ids,
        # search KnowledgePoint table by keyword overlap with the query text.
        text_match_refs: List[Dict[str, Any]] = []
        if not all_kp_ids and query_text:
            all_kps = db.query(models.KnowledgePoint).all()
            scored: List[Tuple[float, models.KnowledgePoint]] = []
            for kp in all_kps:
                kp_name = kp.canonical_name or ""
                if not kp_name:
                    continue
                score = _score_knowledge_name(query_text, kp_name)
                if score >= 0.155:
                    scored.append((score, kp))
            scored.sort(key=lambda x: (-x[0], x[1].id))
            for score, kp in scored[:4]:
                text_match_refs.append({
                    "knowledge_point_id": int(kp.id),
                    "canonical_name": kp.canonical_name,
                    "relation_type": "text_fallback",
                    "relevance_score": round(score, 4),
                    "confidence": round(score * 0.7, 4),
                    "mastery_status": "support",
                })
            # Merge text_match_refs into all_kp_ids so DB lookup includes them.
            for ref in text_match_refs:
                all_kp_ids.append(ref["knowledge_point_id"])

        if not all_kp_ids:
            return []

        points = (
            db.query(models.KnowledgePoint)
            .filter(models.KnowledgePoint.id.in_(sorted(set(all_kp_ids))))
            .all()
        )
        point_map: Dict[int, models.KnowledgePoint] = {int(point.id): point for point in points}

        refs: List[Dict[str, Any]] = []
        # Direct refs.
        for item in anchors:
            kp_id = item.get("knowledge_point_id")
            if kp_id is None:
                continue
            kp_id = int(kp_id)
            point = point_map.get(kp_id)
            refs.append(
                {
                    "knowledge_point_id": kp_id,
                    "canonical_name": point.canonical_name if point else str(item.get("title") or f"kp:{kp_id}"),
                    "relation_type": "knowledge_anchor",
                    "relevance_score": round(_safe_float(item.get("score")), 4),
                    "confidence": round(_safe_float(item.get("score")), 4),
                    "mastery_status": "anchor",
                }
            )

        # Bridged refs.
        seen_kp = {ref["knowledge_point_id"] for ref in refs}
        for kp_id in bridged_kp_ids:
            if kp_id in seen_kp:
                continue
            point = point_map.get(kp_id)
            refs.append(
                {
                    "knowledge_point_id": kp_id,
                    "canonical_name": point.canonical_name if point else bridged_kp_names.get(kp_id, f"kp:{kp_id}"),
                    "relation_type": "knowledge_anchor",
                    "relevance_score": round(bridged_kp_scores.get(kp_id, 0.0), 4),
                    "confidence": round(bridged_kp_scores.get(kp_id, 0.0), 4),
                    "mastery_status": "anchor",
                }
            )

        # Text-match fallback refs.
        for ref in text_match_refs:
            if ref["knowledge_point_id"] in seen_kp:
                continue
            # Update canonical_name from DB if available.
            point = point_map.get(ref["knowledge_point_id"])
            if point:
                ref["canonical_name"] = point.canonical_name
            refs.append(ref)
            seen_kp.add(ref["knowledge_point_id"])

        return refs

    def _merge_knowledge_refs(
        self,
        exact_refs: Sequence[Dict[str, Any]],
        anchor_refs: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: Dict[int, Dict[str, Any]] = {}
        for item in list(exact_refs) + list(anchor_refs):
            kp_id = item.get("knowledge_point_id")
            if kp_id is None:
                continue
            existing = merged.get(int(kp_id))
            score = _safe_float(item.get("confidence") or item.get("relevance_score"))
            if not existing or score > _safe_float(existing.get("confidence") or existing.get("relevance_score")):
                merged[int(kp_id)] = dict(item)
        return list(merged.values())

    def _infer_outcome(
        self,
        *,
        exam_question: models.ExamSessionQuestion,
        attempt: Optional[models.StudentAttempt],
        matched_item: Optional[models.QuestionItem],
        match_anchor_type: str,
    ) -> Tuple[str, str, Optional[str]]:
        if matched_item is None:
            if attempt is None or not _normalize_text(attempt.student_answer_raw):
                return "uncertain", "uncertain", "缺少学生答案，无法判定"
            if attempt.is_correct is True:
                return "correct", "mastered", None
            if attempt.is_correct is False:
                return "incorrect", "weak", None
            if match_anchor_type == "structural_match":
                return "uncertain", "uncertain", "未命中标准题，需 AI 自主解题判定"
            if match_anchor_type == "knowledge_anchor":
                return "uncertain", "uncertain", "未命中标准题，需 AI 结合知识锚点自主解题判定"
            return "uncertain", "uncertain", "未匹配到标准题目，需 AI 自主解题判定"
        if attempt is None or not _normalize_text(attempt.student_answer_raw):
            return "uncertain", "uncertain", "缺少学生答案"
        if attempt.is_correct is True:
            return "correct", "mastered", None
        if attempt.is_correct is False:
            return "incorrect", "weak", None
        student_answer = _normalize_answer(attempt.student_answer_raw)
        expected = _normalize_answer(matched_item.answer_text)
        if student_answer and expected:
            if student_answer == expected:
                return "correct", "mastered", None
            return "incorrect", "weak", None
        if exam_question.review_status == "needs_review":
            return "uncertain", "uncertain", "题目需要人工复核"
        return "uncertain", "uncertain", "答案或标准答案信息不足，需 AI 自主判定"

    def _build_retrieval_evidence(
        self,
        *,
        exam_session: models.ExamSession,
        exam_question: models.ExamSessionQuestion,
        attempt: Optional[models.StudentAttempt],
        matched_item: Optional[models.QuestionItem],
        knowledge_refs: Sequence[Dict[str, Any]],
        structural_matches: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        query_parts = [
            matched_item.stem_plain_text if matched_item else (
                (structural_matches[0] or {}).get("candidate_stem") if structural_matches else exam_question.recognized_text
            ),
            f"学生答案：{attempt.student_answer_raw}" if attempt and attempt.student_answer_raw else None,
        ]
        query_text = "\n".join([part for part in query_parts if part and _normalize_text(part)])
        if not _normalize_text(query_text):
            return []
        subject = exam_session.subject or (matched_item.subject if matched_item else None)
        question_hits: List[Dict[str, Any]] = []
        try:
            question_hits.extend(
                vector_db.db.hybrid_search_with_scores(
                    query_text,
                    n_results=6,
                    entity_types=QUESTION_EVIDENCE_TYPES,
                    metadata_filters={"subject": subject} if subject else None,
                )
            )
        except Exception:
            pass

        # GraphRAG: Neo4j multi-hop traversal from matched knowledge points.
        # Collects structured evidence chains (KP ↔ Question ↔ KP paths,
        # KP → Derivative, KP ← Package) that vector/text search cannot surface.
        graph_hits: List[Dict[str, Any]] = []
        kp_list = list(knowledge_refs)[:3]
        for kp in kp_list:
            kp_id = kp.get("knowledge_point_id")
            kp_name = kp.get("canonical_name")
            if not kp_id or not kp_name:
                continue
            try:
                graph_results = graph_db.search_graph([kp_name], max_depth=2, limit=4)
                logger.info(
                    "Graph traversal for KP %s (id=%s): %s results",
                    kp_name, kp_id, len(graph_results),
                )
                for gr in graph_results:
                    path_nodes = gr.get("path_nodes") or []
                    path_rels = gr.get("path_relationships") or []
                    title, snippet, node_name_tuple = _build_graph_path_text(
                        root_name=str(kp_name),
                        path_nodes=path_nodes,
                        path_relationships=path_rels,
                    )
                    node_names = list(node_name_tuple)
                    if not node_names:
                        continue
                    graph_hits.append({
                        "id": f"graph-{kp_id}-{gr.get('depth', 0)}-{hash(snippet) & 0x7FFFFFFF}",
                        "content": snippet,
                        "snippet": snippet,
                        "score": gr.get("score", 0.0),
                        "vector_score": gr.get("entity_similarity") or 0.0,
                        "text_score": 0.0,
                        "source_type": "graph",
                        "metadata": {
                            "entity_type": "knowledge_point_graph",
                            "entity_id": kp_id,
                            "knowledge_point_id": kp_id,
                            "graph_depth": gr.get("depth", 0),
                            "path_node_names": node_names,
                            "title": title,
                        },
                    })
            except Exception:
                continue

        # Targeted vector/text search by knowledge_point_id.
        targeted_hits: List[Dict[str, Any]] = []
        for kp in list(knowledge_refs)[:3]:
            kp_id = kp.get("knowledge_point_id")
            if kp_id is None:
                continue
            try:
                targeted_hits.extend(
                    vector_db.db.hybrid_search_with_scores(
                        query_text,
                        n_results=4,
                        entity_types=KNOWLEDGE_EVIDENCE_TYPES,
                        metadata_filters={"knowledge_point_id": str(kp_id)},
                    )
                )
            except Exception:
                continue
        knowledge_point_map = {
            int(item["knowledge_point_id"]): item
            for item in knowledge_refs
            if item.get("knowledge_point_id") is not None
        }

        question_candidates = [
            _build_report_evidence_candidate(
                hit=hit,
                bucket="question",
                role="question_reference",
                knowledge_point_map=knowledge_point_map,
            )
            for hit in question_hits
        ]
        knowledge_candidates = [
            _build_report_evidence_candidate(
                hit=hit,
                bucket="knowledge",
                role="knowledge_reference",
                knowledge_point_map=knowledge_point_map,
            )
            for hit in targeted_hits
        ]
        graph_candidates = [
            _build_report_evidence_candidate(
                hit=hit,
                bucket="graph",
                role="graph_path",
                knowledge_point_map=knowledge_point_map,
            )
            for hit in graph_hits
        ]

        for bucket in (question_candidates, knowledge_candidates, graph_candidates):
            bucket.sort(
                key=lambda item: (
                    -_safe_float(item.get("priority")),
                    -_safe_float(item.get("score")),
                    item.get("title") or "",
                    item.get("source_id") or "",
                )
            )

        max_items = 5
        evidence: List[Dict[str, Any]] = []
        seen_ids: set[Tuple[str, str]] = set()
        seen_snippets: set[str] = set()
        bucket_counts: Counter[str] = Counter()
        kp_counts: Counter[int] = Counter()

        def add_candidate(candidate: Dict[str, Any], *, relaxed: bool = False) -> bool:
            metadata = candidate.get("metadata") or {}
            dedupe_key = (str(candidate.get("source_type") or ""), str(candidate.get("source_id") or ""))
            snippet_key = _normalize_text(candidate.get("snippet"))[:160]
            if dedupe_key in seen_ids:
                return False
            if snippet_key and snippet_key in seen_snippets:
                return False

            bucket = str(candidate.get("bucket") or "")
            kp_id = _safe_int(metadata.get("knowledge_point_id"))
            if bucket == "graph" and bucket_counts.get("graph", 0) >= 1:
                return False
            if not relaxed:
                if bucket_counts.get(bucket, 0) >= 2:
                    return False
                if kp_id is not None and kp_counts.get(kp_id, 0) >= 1 and bucket == "knowledge":
                    return False

            seen_ids.add(dedupe_key)
            if snippet_key:
                seen_snippets.add(snippet_key)
            bucket_counts[bucket] += 1
            if kp_id is not None:
                kp_counts[kp_id] += 1
            evidence.append(
                {
                    "source_type": str(candidate.get("source_type") or "vector"),
                    "source_id": str(candidate.get("source_id") or ""),
                    "title": str(candidate.get("title") or "evidence"),
                    "snippet": str(candidate.get("snippet") or ""),
                    "score": round(_safe_float(candidate.get("score")), 4),
                    "evidence_role": str(candidate.get("evidence_role") or "reference"),
                    "metadata": metadata,
                }
            )
            return True

        if matched_item is None and knowledge_candidates:
            seed_order = [knowledge_candidates, graph_candidates, question_candidates]
        else:
            seed_order = [question_candidates, knowledge_candidates, graph_candidates]

        for bucket in seed_order:
            for candidate in bucket:
                if add_candidate(candidate):
                    break
            if len(evidence) >= max_items:
                return evidence

        preferred_knowledge = 2 if knowledge_candidates else 0
        while bucket_counts.get("knowledge", 0) < preferred_knowledge and len(evidence) < max_items:
            if not any(add_candidate(candidate) for candidate in knowledge_candidates):
                break

        if graph_candidates and bucket_counts.get("graph", 0) == 0 and len(evidence) < max_items:
            for candidate in graph_candidates:
                if add_candidate(candidate):
                    break

        all_candidates = question_candidates + knowledge_candidates + graph_candidates
        all_candidates.sort(
            key=lambda item: (
                -_safe_float(item.get("priority")),
                -_safe_float(item.get("score")),
                item.get("title") or "",
                item.get("source_id") or "",
            )
        )
        for candidate in all_candidates:
            if len(evidence) >= max_items:
                break
            add_candidate(candidate)

        if len(evidence) < max_items:
            for candidate in all_candidates:
                if len(evidence) >= max_items:
                    break
                add_candidate(candidate, relaxed=True)

        return evidence

    def _pick_question_summary(
        self,
        *,
        exam_question: models.ExamSessionQuestion,
        matched_item: Optional[models.QuestionItem],
        match_anchors: Dict[str, Any],
    ) -> str:
        if exam_question.recognized_text:
            return exam_question.recognized_text
        if matched_item and matched_item.stem_plain_text:
            return matched_item.stem_plain_text
        structural_matches = match_anchors.get("structural_matches") or []
        if structural_matches and structural_matches[0].get("candidate_stem"):
            return structural_matches[0]["candidate_stem"]
        return ""

    def _build_match_anchor_summary(self, match_anchors: Dict[str, Any]) -> str:
        anchor_type = str(match_anchors.get("primary_anchor_type") or "unanchored")
        if anchor_type == "exact_match":
            exact = match_anchors.get("exact_match") or {}
            return f"已命中标准题，匹配分 {round(_safe_float(exact.get('final_score')), 4)}。"
        if anchor_type == "structural_match":
            structural = (match_anchors.get("structural_matches") or [{}])[0]
            return (
                f"未命中标准题，已回退到相似题参考；"
                f"最高相似分 {round(_safe_float(structural.get('final_score')), 4)}。"
            )
        if anchor_type == "knowledge_anchor":
            return f"未命中标准题，已回退到 {len(match_anchors.get('knowledge_anchors') or [])} 条知识锚点。"
        diagnostics = match_anchors.get("diagnostics") or {}
        return f"未找到可用锚点，原因：{diagnostics.get('exact_failure_reason') or 'unknown'}。"

    def _classify_error_pattern(
        self,
        *,
        correctness: str,
        mastery_level: str,
        uncertainty_reason: Optional[str],
        patterns_by_category: Dict[str, models.MistakePattern],
    ) -> Optional[Dict[str, Any]]:
        if correctness == "correct":
            return None
        if correctness == "uncertain":
            code = "UNCERTAIN_REVIEW"
            name = "待人工复核"
            category = "review"
            if uncertainty_reason and "匹配" in uncertainty_reason:
                code, name, category = "MATCHING_UNCERTAIN", "匹配不确定", "matching"
        else:
            code = "CONCEPT_CONFUSION"
            name = "概念混淆"
            category = "concept"
            if mastery_level == "weak":
                code, name, category = "KNOWLEDGE_GAP", "知识漏洞", "knowledge"
        row = patterns_by_category.get(category)
        return {
            "code": row.code if row else code,
            "name": row.name if row else name,
            "category": row.category if row else category,
            "description": row.description if row else uncertainty_reason,
        }

    def _select_derivative_assets(
        self,
        *,
        derivatives_by_kp: Dict[int, List[models.KnowledgeDerivative]],
        knowledge_point_ids: Sequence[int],
        audience: str,
        correctness: str,
    ) -> List[Dict[str, Any]]:
        preferred_types = ["common_pitfalls", "comparison", "concept_explainer"] if correctness == "incorrect" else [
            "exam_cheatsheet",
            "concept_explainer",
            "memory_tip",
        ]
        assets: List[Dict[str, Any]] = []
        for kp_id in knowledge_point_ids:
            rows = derivatives_by_kp.get(int(kp_id), [])
            audience_rows = [row for row in rows if row.target_audience == audience] or rows
            for dtype in preferred_types:
                row = next((item for item in audience_rows if item.derivative_type == dtype), None)
                if not row:
                    continue
                content = row.generated_content or {}
                assets.append(
                    {
                        "asset_type": row.derivative_type,
                        "asset_id": int(row.id),
                        "title": str(content.get("title") or row.derivative_type),
                        "audience": row.target_audience,
                        "summary": str(content.get("summary") or "")[:180] or None,
                        "content": content,
                    }
                )
                break
            if len(assets) >= 4:
                break
        return assets

    def _compute_confidence(
        self,
        *,
        exam_question: models.ExamSessionQuestion,
        attempt: Optional[models.StudentAttempt],
        evidence: Sequence[Dict[str, Any]],
        knowledge_refs: Sequence[Dict[str, Any]],
        correctness: str,
    ) -> float:
        score = 0.25
        score += min(0.25, _safe_float(exam_question.match_confidence, 0.0) * 0.25)
        if attempt:
            score += min(0.18, _safe_float(attempt.ocr_confidence, 0.0) * 0.18)
        if evidence:
            score += 0.16
        if knowledge_refs:
            score += min(0.16, max(_safe_float(item.get("confidence"), 0.0) for item in knowledge_refs) * 0.16)
        if correctness in {"correct", "incorrect"}:
            score += 0.12
        return max(0.0, min(score, 0.99))

    def _build_study_advice(
        self,
        *,
        correctness: str,
        knowledge_refs: Sequence[Dict[str, Any]],
        error_pattern: Optional[Dict[str, Any]],
        intervention_assets: Sequence[Dict[str, Any]],
    ) -> List[str]:
        kp_names = [item["canonical_name"] for item in knowledge_refs[:3]]
        if correctness == "correct":
            base = "保持当前解题思路，优先巩固已掌握题型。"
        elif correctness == "incorrect":
            base = f"优先回看 {'、'.join(kp_names) if kp_names else '相关知识点'} 的概念与例题。"
        else:
            base = "先完成人工复核或标准题匹配，再给出正式学习建议。"
        tips = [base]
        if error_pattern and error_pattern.get("name"):
            tips.append(f"本题主要风险模式：{error_pattern['name']}。")
        if intervention_assets:
            tips.append(f"建议先阅读《{intervention_assets[0]['title']}》后再做 1-2 道同类题。")
        return tips

    def _build_root_cause(
        self,
        *,
        correctness: str,
        knowledge_refs: Sequence[Dict[str, Any]],
        error_pattern: Optional[Dict[str, Any]],
        uncertainty_reason: Optional[str],
    ) -> str:
        kp_names = [item["canonical_name"] for item in knowledge_refs[:2]]
        if correctness == "uncertain":
            return uncertainty_reason or "证据不足，暂无法形成稳定根因判断。"
        if correctness == "correct":
            return f"学生对 {'、'.join(kp_names) if kp_names else '目标知识'} 掌握较稳。"
        return (
            f"该题涉及 {'、'.join(kp_names) if kp_names else '目标知识点'}，"
            f"当前更像是「{(error_pattern or {}).get('name') or '知识漏洞'}」导致的失分。"
        )

    def _build_knowledge_profile(
        self,
        db: Session,
        analyses: Sequence[Dict[str, Any]],
        derivatives_by_kp: Dict[int, List[models.KnowledgeDerivative]],
    ) -> List[Dict[str, Any]]:
        stats: Dict[int, Dict[str, Any]] = {}
        for analysis in analyses:
            status = analysis.get("correctness")
            for kp in analysis.get("knowledge_points") or []:
                entry = stats.setdefault(
                    int(kp["knowledge_point_id"]),
                    {
                        "knowledge_point_id": int(kp["knowledge_point_id"]),
                        "canonical_name": kp["canonical_name"],
                        "total_questions": 0,
                        "correct_questions": 0,
                        "incorrect_questions": 0,
                        "uncertain_questions": 0,
                        "weighted_score": 0.0,
                    },
                )
                entry["total_questions"] += 1
                entry["weighted_score"] += _safe_float(kp.get("relevance_score"), 0.6)
                if status == "correct":
                    entry["correct_questions"] += 1
                elif status == "incorrect":
                    entry["incorrect_questions"] += 1
                else:
                    entry["uncertain_questions"] += 1

        relation_rows = db.query(models.KnowledgePointRelation).all()
        prerequisites: Dict[int, List[int]] = defaultdict(list)
        confusions: Dict[int, List[int]] = defaultdict(list)
        for row in relation_rows:
            rel = (row.relation_type or "").lower()
            if "pre" in rel:
                prerequisites[int(row.source_knowledge_point_id)].append(int(row.target_knowledge_point_id))
            if "confus" in rel or "compare" in rel:
                confusions[int(row.source_knowledge_point_id)].append(int(row.target_knowledge_point_id))

        profile: List[Dict[str, Any]] = []
        for kp_id, entry in stats.items():
            total = max(1, int(entry["total_questions"]))
            accuracy = round(entry["correct_questions"] / total, 4)
            if entry["incorrect_questions"] >= entry["correct_questions"] and entry["incorrect_questions"] > 0:
                mastery_status = "weak"
            elif entry["uncertain_questions"] > entry["correct_questions"]:
                mastery_status = "uncertain"
            else:
                mastery_status = "mastered" if accuracy >= 0.7 else "developing"
            entry.update(
                {
                    "accuracy": accuracy,
                    "mastery_status": mastery_status,
                    "prerequisite_of": prerequisites.get(kp_id, [])[:5],
                    "easy_to_confuse_with": confusions.get(kp_id, [])[:5],
                    "recommended_assets": self._select_derivative_assets(
                        derivatives_by_kp=derivatives_by_kp,
                        knowledge_point_ids=[kp_id],
                        audience="student",
                        correctness="incorrect" if mastery_status == "weak" else "correct",
                    ),
                }
            )
            profile.append(entry)
        return sorted(
            profile,
            key=lambda item: (item["mastery_status"] == "weak", -item["weighted_score"]),
            reverse=True,
        )

    def _build_mistake_profile(self, analyses: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for analysis in analyses:
            pattern = analysis.get("error_pattern") or {}
            code = pattern.get("code")
            if not code:
                continue
            entry = grouped.setdefault(
                code,
                {
                    "code": code,
                    "name": pattern.get("name") or code,
                    "category": pattern.get("category") or "unknown",
                    "count": 0,
                    "question_nos": [],
                    "related_knowledge_points": [],
                    "suggested_assets": [],
                },
            )
            entry["count"] += 1
            entry["question_nos"].append(analysis["source_question_no"])
            for kp in analysis.get("knowledge_points") or []:
                if kp["knowledge_point_id"] not in entry["related_knowledge_points"]:
                    entry["related_knowledge_points"].append(kp["knowledge_point_id"])
            for asset in analysis.get("intervention_assets") or []:
                if asset not in entry["suggested_assets"]:
                    entry["suggested_assets"].append(asset)
        return sorted(grouped.values(), key=lambda item: (-item["count"], item["code"]))

    def _build_graph_overview(self, analyses: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        path_count = 0
        node_count = 0
        edge_count = 0
        for analysis in analyses:
            path = analysis.get("graph_path") or {}
            if path.get("nodes") or path.get("edges"):
                path_count += 1
                node_count += len(path.get("nodes") or [])
                edge_count += len(path.get("edges") or [])
        return {
            "question_with_graph_paths": path_count,
            "graph_node_hits": node_count,
            "graph_edge_hits": edge_count,
        }

    def _build_action_plan(
        self,
        *,
        knowledge_profile: Sequence[Dict[str, Any]],
        mistake_profile: Sequence[Dict[str, Any]],
        analyses: Sequence[Dict[str, Any]],
        audience: str,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        weak_points = [item for item in knowledge_profile if item.get("mastery_status") in {"weak", "uncertain"}][:3]
        for point in weak_points:
            items.append(
                {
                    "title": f"优先修复：{point['canonical_name']}",
                    "description": (
                        f"该知识点在本卷出现 {point['total_questions']} 次，"
                        f"正确率 {round(point['accuracy'] * 100)}%。"
                    ),
                    "priority": "high",
                    "target_knowledge_point_ids": [point["knowledge_point_id"]],
                    "assets": point.get("recommended_assets") or [],
                }
            )
        if mistake_profile:
            top = mistake_profile[0]
            items.append(
                {
                    "title": f"错因治理：{top['name']}",
                    "description": f"该错因在 {top['count']} 道题上出现，建议形成专项复盘。",
                    "priority": "high" if audience in {"teacher", "governance"} else "medium",
                    "target_knowledge_point_ids": top.get("related_knowledge_points") or [],
                    "assets": top.get("suggested_assets") or [],
                }
            )
        manual_review = [item for item in analyses if item.get("needs_manual_review")]
        if manual_review:
            items.append(
                {
                    "title": "人工复核优先队列",
                    "description": f"当前仍有 {len(manual_review)} 道题证据不足或匹配不稳，建议优先核验。",
                    "priority": "high",
                    "target_knowledge_point_ids": [],
                    "assets": [],
                }
            )
        return items[:5]

    def _build_summary(
        self,
        exam_session: models.ExamSession,
        analyses: Sequence[Dict[str, Any]],
        knowledge_profile: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        total = len(analyses)
        correct = sum(1 for item in analyses if item.get("correctness") == "correct")
        incorrect = sum(1 for item in analyses if item.get("correctness") == "incorrect")
        uncertain = sum(1 for item in analyses if item.get("correctness") == "uncertain")
        evidence_ready = sum(1 for item in analyses if item.get("retrieval_evidence"))
        graph_ready = sum(1 for item in analyses if item.get("graph_path"))
        confidence_avg = round(sum(_safe_float(item.get("confidence")) for item in analyses) / max(1, total), 4)
        weak_count = sum(1 for item in knowledge_profile if item.get("mastery_status") == "weak")
        exact_anchor_count = sum(1 for item in analyses if item.get("match_anchor_type") == "exact_match")
        structural_anchor_count = sum(1 for item in analyses if item.get("match_anchor_type") == "structural_match")
        knowledge_anchor_count = sum(1 for item in analyses if item.get("match_anchor_type") == "knowledge_anchor")
        return {
            "headline": f"本次试卷共分析 {total} 题，其中正确 {correct} 题、错误 {incorrect} 题。",
            "exam_session_id": exam_session.id,
            "student_id": exam_session.student_id,
            "subject": exam_session.subject,
            "matched_paper_id": exam_session.matched_paper_id,
            "total_questions": total,
            "correct_questions": correct,
            "incorrect_questions": incorrect,
            "uncertain_questions": uncertain,
            "accuracy": round(correct / max(1, total), 4),
            "average_confidence": confidence_avg,
            "evidence_ready_questions": evidence_ready,
            "graph_ready_questions": graph_ready,
            "weak_knowledge_points": weak_count,
            "exact_match_rate": round(exact_anchor_count / max(1, total), 4),
            "structural_anchor_rate": round(structural_anchor_count / max(1, total), 4),
            "knowledge_anchor_rate": round(knowledge_anchor_count / max(1, total), 4),
        }

    def _build_surface(
        self,
        *,
        audience: str,
        exam_session: models.ExamSession,
        summary: Dict[str, Any],
        analyses: Sequence[Dict[str, Any]],
        knowledge_profile: Sequence[Dict[str, Any]],
        mistake_profile: Sequence[Dict[str, Any]],
        action_plan: Sequence[Dict[str, Any]],
        graph_overview: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "exam_session_id": exam_session.id,
            "audience": audience,
            "generated_at": datetime.utcnow(),
            "summary": summary,
            "question_analyses": list(analyses),
            "knowledge_profile": list(knowledge_profile),
            "mistake_profile": list(mistake_profile),
            "action_plan": list(action_plan),
            "graph_overview": graph_overview,
        }

    def _build_teacher_breakdown(
        self,
        analyses: Sequence[Dict[str, Any]],
        knowledge_profile: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        weak_questions = [item["source_question_no"] for item in analyses if item.get("correctness") == "incorrect"]
        uncertain_questions = [item["source_question_no"] for item in analyses if item.get("needs_manual_review")]
        return {
            "weak_question_nos": weak_questions,
            "manual_review_question_nos": uncertain_questions,
            "top_weak_knowledge_points": [
                {
                    "knowledge_point_id": item["knowledge_point_id"],
                    "canonical_name": item["canonical_name"],
                    "accuracy": item["accuracy"],
                }
                for item in knowledge_profile
                if item.get("mastery_status") in {"weak", "uncertain"}
            ][:5],
        }

    def _build_governance_metrics(
        self,
        *,
        exam_session: models.ExamSession,
        analyses: Sequence[Dict[str, Any]],
        knowledge_profile: Sequence[Dict[str, Any]],
        graph_overview: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "exam_session_id": exam_session.id,
            "matching_completed": exam_session.matching_status == "completed",
            "analysis_completed": exam_session.analysis_status == "completed",
            "question_count": len(analyses),
            "knowledge_point_coverage": len(knowledge_profile),
            "manual_review_rate": round(
                sum(1 for item in analyses if item.get("needs_manual_review")) / max(1, len(analyses)),
                4,
            ),
            "graph_ready_rate": round(
                _safe_float(graph_overview.get("question_with_graph_paths"), 0.0) / max(1, len(analyses)),
                4,
            ),
            "evidence_ready_rate": round(
                sum(1 for item in analyses if item.get("retrieval_evidence")) / max(1, len(analyses)),
                4,
            ),
            "exact_match_rate": round(
                sum(1 for item in analyses if item.get("match_anchor_type") == "exact_match") / max(1, len(analyses)),
                4,
            ),
            "structural_anchor_rate": round(
                sum(1 for item in analyses if item.get("match_anchor_type") == "structural_match") / max(1, len(analyses)),
                4,
            ),
            "knowledge_anchor_rate": round(
                sum(1 for item in analyses if item.get("match_anchor_type") == "knowledge_anchor") / max(1, len(analyses)),
                4,
            ),
        }


service = ExamSessionAnalysisService()
