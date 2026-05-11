from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from shared import models
from shared.llm_step_config import (
    build_llm_config,
    resolve_step_llm_config,
    _resolve_first_available_provider_and_model,
)

from .llm_client import build_image_data_url, call_llm, supports_vision_model

logger = logging.getLogger(__name__)

VISION_STEP_KEYS = ("analyzer.question_visual_observation", "analyzer.question_vlm")
REASONING_STEP_KEYS = ("analyzer.question_multimodal_reasoning", "analyzer.reasoning")


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _truncate(value: Optional[str], max_length: int = 220) -> str:
    text = _normalize_text(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_json_object(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    text = str(raw).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


class ExamSessionMultimodalService:
    def resolve_llm_configs(self, db: Session) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
        vision_llm = self._resolve_first_available_step_config(
            db,
            VISION_STEP_KEYS,
            prefer_vision_fallback=True,
        )
        reasoning_llm = self._resolve_first_available_step_config(
            db,
            REASONING_STEP_KEYS,
            prefer_vision_fallback=True,
        )
        return vision_llm, reasoning_llm

    def _resolve_first_available_step_config(
        self,
        db: Session,
        step_keys: Sequence[str],
        *,
        prefer_vision_fallback: bool,
    ) -> Optional[Dict[str, str]]:
        for step_key in step_keys:
            config = resolve_step_llm_config(
                db,
                step_key,
                allow_generic_fallback=False,
                prefer_vision_fallback=False,
            )
            if config and (
                not prefer_vision_fallback
                or supports_vision_model(config.get("model_name"))
            ):
                return config
        primary_step_key = step_keys[0]
        if prefer_vision_fallback:
            provider, model = _resolve_first_available_provider_and_model(db, prefer_vision=True)
            if provider and model:
                config = build_llm_config(provider, model)
                config["step_key"] = primary_step_key
                config["config_source"] = "generic_fallback_vision"
                return config
        return resolve_step_llm_config(
            db,
            primary_step_key,
            allow_generic_fallback=True,
            prefer_vision_fallback=prefer_vision_fallback,
        )

    def analyze_question(
        self,
        *,
        exam_session: models.ExamSession,
        exam_question: models.ExamSessionQuestion,
        attempt: Optional[models.StudentAttempt],
        matched_item: Optional[models.QuestionItem],
        knowledge_refs: Sequence[Dict[str, Any]],
        retrieval_evidence: Sequence[Dict[str, Any]],
        structural_matches: Sequence[Dict[str, Any]],
        knowledge_anchors: Sequence[Dict[str, Any]],
        match_anchor_type: str,
        baseline_correctness: str,
        baseline_mastery_level: str,
        baseline_uncertainty_reason: Optional[str],
        vision_llm_config: Optional[Dict[str, str]],
        reasoning_llm_config: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        image_paths = self._collect_image_paths(attempt)
        visual_observation = self._run_visual_observation(
            image_paths=image_paths,
            exam_question=exam_question,
            attempt=attempt,
            matched_item=matched_item,
            llm_config=vision_llm_config,
        )
        reasoning = self._run_reasoning_fusion(
            exam_session=exam_session,
            exam_question=exam_question,
            attempt=attempt,
            matched_item=matched_item,
            knowledge_refs=knowledge_refs,
            retrieval_evidence=retrieval_evidence,
            structural_matches=structural_matches,
            knowledge_anchors=knowledge_anchors,
            match_anchor_type=match_anchor_type,
            baseline_correctness=baseline_correctness,
            baseline_mastery_level=baseline_mastery_level,
            baseline_uncertainty_reason=baseline_uncertainty_reason,
            visual_observation=visual_observation,
            image_paths=image_paths,
            llm_config=reasoning_llm_config,
        )
        return self._normalize_result(
            baseline_correctness=baseline_correctness,
            baseline_mastery_level=baseline_mastery_level,
            baseline_uncertainty_reason=baseline_uncertainty_reason,
            visual_observation=visual_observation,
            reasoning=reasoning,
        )

    def _collect_image_paths(self, attempt: Optional[models.StudentAttempt]) -> List[str]:
        payload = attempt.answer_blocks_json if attempt and isinstance(attempt.answer_blocks_json, dict) else {}
        candidates: List[str] = []
        for key in ("complete_unit_image_path", "question_image_path", "answer_image_path"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        for item in payload.get("answer_image_paths") or []:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())

        seen = set()
        ordered: List[str] = []
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            try:
                resolved = str(Path(path).resolve())
            except OSError:
                continue
            if Path(resolved).is_file():
                ordered.append(resolved)
        return ordered[:3]

    def _run_visual_observation(
        self,
        *,
        image_paths: Sequence[str],
        exam_question: models.ExamSessionQuestion,
        attempt: Optional[models.StudentAttempt],
        matched_item: Optional[models.QuestionItem],
        llm_config: Optional[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        if not image_paths or not llm_config or not supports_vision_model(llm_config.get("model_name")):
            return None

        prompt = self._build_visual_prompt(
            exam_question=exam_question,
            attempt=attempt,
            matched_item=matched_item,
        )
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            content.append({"type": "image_url", "image_url": {"url": build_image_data_url(image_path)}})
        raw = call_llm([{"role": "user", "content": content}], llm_config, json_mode=True)
        parsed = _extract_json_object(raw)
        if parsed is None:
            logger.warning("Question VLM returned unparsable payload: question=%s", exam_question.id)
        return parsed

    def _build_visual_prompt(
        self,
        *,
        exam_question: models.ExamSessionQuestion,
        attempt: Optional[models.StudentAttempt],
        matched_item: Optional[models.QuestionItem],
    ) -> str:
        if matched_item:
            reference_note = "当前存在标准题锚点，但本阶段仍只做视觉观察，不直接给最终判题结论。"
            extra_instruction = ""
        else:
            reference_note = "当前未命中标准题，后续推理将需要你提供的完整题目信息来独立解题判定。"
            extra_instruction = (
                "重要：因为后续需要基于你的观察来自主解题，请务必从图中完整读取：\n"
                "7. question_full_text: 题目的完整文本（包括选项 A/B/C/D 的完整内容）；\n"
                "8. question_type: 题型（选择题/填空题/解答题等）；\n"
                "9. full_options: 如果是选择题，列出每个选项的完整文本 {\"A\": \"...\", \"B\": \"...\", ...}。\n"
            )
        return (
            "你是一名高中学科阅卷与学情诊断助手。请优先根据图片观察学生真实作答情况，"
            "不要只复述文本。输出 JSON，对字段缺失时用 null 或空数组。\n"
            "必须输出字段：observed_answer, observed_steps, visual_evidence_summary, "
            "visual_conflicts, visual_confidence, requires_manual_review"
            + (", question_full_text, question_type, full_options" if not matched_item else "") + "。\n"
            "要求：\n"
            "1. observed_answer: 从图中看到的学生答案/结论；\n"
            "2. observed_steps: 观察到的关键步骤数组；\n"
            "3. visual_evidence_summary: 2-4 句总结，说明图里看到了什么；\n"
            "4. visual_conflicts: 图像中存在的不清晰、涂改、跳步、图文冲突；\n"
            "5. visual_confidence: 0~1；\n"
            "6. requires_manual_review: 布尔值。\n"
            + extra_instruction +
            f"\n约束：{reference_note}\n"
            f"题号：{exam_question.source_question_no}\n"
            f"OCR题干：{_truncate(exam_question.recognized_text, 500)}\n"
            f"学生答案文本：{_truncate(attempt.student_answer_raw if attempt else None, 300)}\n"
            f"标准题干：{_truncate(matched_item.stem_plain_text if matched_item else None, 500)}\n"
            f"标准答案：{_truncate(matched_item.answer_text if matched_item else None, 120)}"
        )

    def _run_reasoning_fusion(
        self,
        *,
        exam_session: models.ExamSession,
        exam_question: models.ExamSessionQuestion,
        attempt: Optional[models.StudentAttempt],
        matched_item: Optional[models.QuestionItem],
        knowledge_refs: Sequence[Dict[str, Any]],
        retrieval_evidence: Sequence[Dict[str, Any]],
        structural_matches: Sequence[Dict[str, Any]],
        knowledge_anchors: Sequence[Dict[str, Any]],
        match_anchor_type: str,
        baseline_correctness: str,
        baseline_mastery_level: str,
        baseline_uncertainty_reason: Optional[str],
        visual_observation: Optional[Dict[str, Any]],
        image_paths: Sequence[str],
        llm_config: Optional[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        if not llm_config:
            return None
        use_vision = bool(image_paths) and supports_vision_model(llm_config.get("model_name"))
        print(
            f"[REASONING_STAGE] question={exam_question.source_question_no} "
            f"model={llm_config.get('model_name', 'unknown')} "
            f"use_vision={use_vision} "
            f"image_count={len(image_paths) if image_paths else 0} "
            f"first_image={image_paths[0] if image_paths else 'NONE'}",
            flush=True,
        )

        evidence_summary = [
            {
                "source_type": item.get("source_type"),
                "evidence_role": item.get("evidence_role"),
                "entity_type": (item.get("metadata") or {}).get("entity_type"),
                "knowledge_point_id": (item.get("metadata") or {}).get("knowledge_point_id"),
                "knowledge_point_name": (item.get("metadata") or {}).get("knowledge_point_name"),
                "title": item.get("title"),
                "snippet": _truncate(item.get("snippet"), 180),
                "score": item.get("score"),
            }
            for item in list(retrieval_evidence)[:5]
        ]
        knowledge_summary = [
            {
                "knowledge_point_id": item.get("knowledge_point_id"),
                "canonical_name": item.get("canonical_name"),
                "relation_type": item.get("relation_type"),
                "confidence": item.get("confidence"),
            }
            for item in list(knowledge_refs)[:4]
        ]
        structural_summary = [
            {
                "question_item_id": item.get("question_item_id"),
                "candidate_stem": _truncate(item.get("candidate_stem"), 220),
                "candidate_answer": _truncate(item.get("candidate_answer"), 120),
                "final_score": item.get("final_score"),
                "similarity_reason": item.get("similarity_reason"),
            }
            for item in list(structural_matches)[:2]
        ]
        knowledge_anchor_summary = [
            {
                "source_type": item.get("source_type"),
                "source_id": item.get("source_id"),
                "title": item.get("title"),
                "snippet": _truncate(item.get("snippet"), 180),
                "score": item.get("score"),
            }
            for item in list(knowledge_anchors)[:4]
        ]
        task_text = (
            "你已看到题目原图（包含完整题干、公式、选项和学生作答）。"
            "请先独立解题：仔细读题，给出完整的解题步骤和你的最终答案，"
            "然后把你的答案与图中学生的作答进行比对，判断对错。"
            if use_vision else
            "基于视觉观察、OCR 文本、锚点类型与检索证据，判断学生该题作答情况。"
        )
        user_payload = {
            "task": task_text,
            "rules": [
                "优先相信视觉观察，其次才是 OCR 文本。",
                "如果图像与文本冲突，请明确指出冲突。",
                "如果证据不足，必须输出 uncertain 并要求人工复核。",
                "只有在锚点类型为 exact_match 时，才能把 matched_answer 当作标准真值。",
                "如果锚点类型为 structural_match 或 knowledge_anchor（即没有标准答案）：你必须自主解答这道题（基于题目文本、学科知识），然后将你的答案与学生的 observed_answer/student_answer_raw 比对，输出 correct/incorrect/uncertain。",
                "自主解题时，相似题（structural_references）和知识锚点（knowledge_anchor_references）仅作为领域参考，不作为标准答案。",
                "如果是选择题，请先确定正确选项，再对比学生所选的选项。",
                "如果是填空题/解答题，请评估学生的答案与正确解法的匹配程度。",
                "如果你对题目解法不确定，诚实输出 uncertain 并说明原因（如：题目信息不完整、图片模糊无法读取关键数据等）。",
                "你必须在 solution_steps 中给出你的完整解题推导过程（分步骤），在 llm_answer 中给出你得到的最终答案。",
                "只输出 JSON。",
            ],
            "exam_session": {
                "exam_session_id": exam_session.id,
                "subject": exam_session.subject,
                "source_question_no": exam_question.source_question_no,
            },
            "match_anchor_type": match_anchor_type,
            "question": {
                "ocr_text": _truncate(exam_question.recognized_text, 800),
                "student_answer_raw": _truncate(attempt.student_answer_raw if attempt else None, 300),
                "matched_question_stem": _truncate(matched_item.stem_plain_text if matched_item else None, 800),
                "matched_answer": _truncate(matched_item.answer_text if matched_item else None, 120),
            },
            "structural_references": structural_summary,
            "knowledge_anchor_references": knowledge_anchor_summary,
            "visual_observation": visual_observation,
            "knowledge_points": knowledge_summary,
            "retrieval_evidence": evidence_summary,
            "baseline": {
                "correctness": baseline_correctness,
                "mastery_level": baseline_mastery_level,
                "uncertainty_reason": baseline_uncertainty_reason,
            },
            "output_schema": {
                "correctness": "correct | incorrect | uncertain",
                "mastery_level": "mastered | weak | uncertain",
                "uncertainty_reason": "string|null",
                "solution_steps": "string (你的完整解题推导过程，分步骤写出)",
                "llm_answer": "string (你解题得到的最终答案)",
                "visual_evidence_summary": "string|null",
                "text_consistency_summary": "string|null",
                "reference_usage_note": "string|null",
                "root_cause_hypothesis": "string|null",
                "study_advice": ["string"],
                "confidence_override": "0~1 number|null",
                "needs_manual_review": "boolean|null",
            },
        }
        if use_vision:
            system_content = (
                "你是一名高中学科诊断助手，你可以直接查看题目图片。"
                "请根据图片中的题目原貌（包括公式、图表、选项）自主解题。"
                "先写出完整解题步骤（solution_steps），给出你的最终答案（llm_answer），"
                "然后与学生作答比对，输出结构化 JSON。不要输出 Markdown。"
            )
            content: List[Dict[str, Any]] = [{"type": "text", "text": json.dumps(user_payload, ensure_ascii=False)}]
            for image_path in image_paths:
                content.append({"type": "image_url", "image_url": {"url": build_image_data_url(image_path)}})
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": content},
            ]
        else:
            system_content = (
                "你是一名高中学科诊断助手。请基于图像观察结果、题目文本、标准题和检索证据，"
                "输出结构化 JSON。不要输出 Markdown。"
            )
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ]
        raw = call_llm(messages, llm_config, json_mode=True)
        parsed = _extract_json_object(raw)
        if parsed is None:
            logger.warning("Analyzer reasoning returned unparsable payload: question=%s", exam_question.id)
        return parsed

    def _normalize_result(
        self,
        *,
        baseline_correctness: str,
        baseline_mastery_level: str,
        baseline_uncertainty_reason: Optional[str],
        visual_observation: Optional[Dict[str, Any]],
        reasoning: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        allowed_correctness = {"correct", "incorrect", "uncertain"}
        allowed_mastery = {"mastered", "weak", "uncertain"}

        correctness = baseline_correctness
        mastery_level = baseline_mastery_level
        uncertainty_reason = baseline_uncertainty_reason
        confidence_override = None
        analysis_mode = "text_only"

        if reasoning:
            candidate = str(reasoning.get("correctness") or "").strip().lower()
            if candidate in allowed_correctness:
                correctness = candidate
            candidate_mastery = str(reasoning.get("mastery_level") or "").strip().lower()
            if candidate_mastery in allowed_mastery:
                mastery_level = candidate_mastery
            uncertainty_reason = _normalize_text(reasoning.get("uncertainty_reason")) or uncertainty_reason
            confidence_override = _safe_float(reasoning.get("confidence_override"))
            analysis_mode = "multimodal"
        elif visual_observation:
            analysis_mode = "multimodal"

        observed_summary = None
        if isinstance(visual_observation, dict):
            observed_summary = _normalize_text(visual_observation.get("visual_evidence_summary"))
        visual_evidence_summary = (
            _normalize_text(reasoning.get("visual_evidence_summary")) if isinstance(reasoning, dict) else ""
        ) or observed_summary
        text_consistency_summary = (
            _normalize_text(reasoning.get("text_consistency_summary")) if isinstance(reasoning, dict) else ""
        ) or (
            "仅使用 OCR/标准题文本进行校验，未形成独立图文一致性结论。" if observed_summary else None
        )
        root_cause_hypothesis = (
            _normalize_text(reasoning.get("root_cause_hypothesis")) if isinstance(reasoning, dict) else ""
        ) or None
        study_advice_raw = reasoning.get("study_advice") if isinstance(reasoning, dict) else None
        study_advice = [str(item).strip() for item in study_advice_raw if str(item).strip()] if isinstance(study_advice_raw, list) else []
        solution_steps = (
            _normalize_text(reasoning.get("solution_steps")) if isinstance(reasoning, dict) else ""
        ) or None
        llm_answer = (
            _normalize_text(reasoning.get("llm_answer")) if isinstance(reasoning, dict) else ""
        ) or None

        visual_confidence = _safe_float(visual_observation.get("visual_confidence")) if isinstance(visual_observation, dict) else None
        requires_manual_review = bool(visual_observation.get("requires_manual_review")) if isinstance(visual_observation, dict) else False
        if isinstance(reasoning, dict) and reasoning.get("needs_manual_review") is not None:
            requires_manual_review = bool(reasoning.get("needs_manual_review"))

        return {
            "analysis_mode": analysis_mode,
            "correctness": correctness,
            "mastery_level": mastery_level,
            "uncertainty_reason": uncertainty_reason,
            "solution_steps": solution_steps,
            "llm_answer": llm_answer,
            "visual_evidence_summary": visual_evidence_summary,
            "text_consistency_summary": text_consistency_summary,
            "root_cause_hypothesis": root_cause_hypothesis,
            "study_advice": study_advice,
            "confidence_override": confidence_override,
            "visual_confidence": visual_confidence,
            "needs_manual_review": requires_manual_review,
        }


service = ExamSessionMultimodalService()
