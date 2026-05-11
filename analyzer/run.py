import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.database import SessionLocal
from shared.prompt_step_config import resolve_step_prompt, sync_prompt_step_configs


try:
    from analyzer.app.retriever import hybrid_search
    from analyzer.app.llm_client import call_llm, call_vlm_on_image, get_default_llm_config, supports_vision_model
except Exception as first_exc:  # pragma: no cover - defensive fallback for CLI environments
    try:
        from app.retriever import hybrid_search
        from app.llm_client import call_llm, call_vlm_on_image, get_default_llm_config, supports_vision_model
    except Exception as second_exc:  # pragma: no cover - defensive fallback for CLI environments
        hybrid_search = None
        call_llm = None
        call_vlm_on_image = None
        get_default_llm_config = None
        supports_vision_model = None
        RETRIEVER_IMPORT_ERROR = str(second_exc)
    else:
        RETRIEVER_IMPORT_ERROR = None


else:
    RETRIEVER_IMPORT_ERROR = None




EMPTY_ANSWER_VALUES = {None, "", "EMPTY"}
VLM_DISABLED_VALUES = {"0", "false", "no", "off"}
ANSWER_STATUS_VALUES = {"answered", "uncertain", "unanswered"}
CORRECTNESS_VALUES = {"correct", "incorrect", "uncertain", "unknown"}
MASTERY_LEVEL_VALUES = {"mastered", "partial", "weak", "unknown"}



def resolve_prompt_template(step_key: str, variables: Optional[Dict[str, Any]] = None) -> Optional[str]:
    db = SessionLocal()
    try:
        sync_prompt_step_configs(db)
        prompt_config = resolve_step_prompt(db, step_key, variables=variables)
    finally:
        db.close()
    return prompt_config.get("prompt_text") if prompt_config else None



def main():


    parser = argparse.ArgumentParser(description="Analyzer module for Exam Analysis Suite.")
    parser.add_argument("--bundle-dir", help="Directory containing `manifest.json` and `questions.json`.")
    parser.add_argument("--input-dir", help="Backward-compatible alias of --bundle-dir.")
    parser.add_argument("--output-dir", required=True, help="Directory to save the analysis outputs.")
    args = parser.parse_args()

    bundle_dir = os.path.abspath(args.bundle_dir or args.input_dir or "")
    if not bundle_dir:
        parser.error("Please specify --bundle-dir or --input-dir.")

    print("--- Analyzer Module ---")
    print(f"Bundle directory: {bundle_dir}")
    print(f"Output directory: {args.output_dir}")

    manifest, questions, load_warnings = load_bundle(bundle_dir)
    print(f"Successfully loaded bundle with {len(questions)} questions.")

    vlm_config = get_vlm_config()
    reasoning_llm_config = get_reasoning_llm_config()

    question_analyses = [
        build_question_analysis(question, bundle_dir, vlm_config, reasoning_llm_config)
        for question in questions
    ]
    report = build_analysis_report(manifest, question_analyses, load_warnings)



    os.makedirs(args.output_dir, exist_ok=True)
    question_analyses_path = os.path.join(args.output_dir, "question_analyses.json")
    report_path = os.path.join(args.output_dir, "analysis_report.json")

    with open(question_analyses_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "bundle_id": manifest.get("bundle_id"),
                "generated_at": report["generated_at"],
                "questions": question_analyses,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Question analyses saved to: {question_analyses_path}")
    print(f"Analysis report saved to: {report_path}")


def load_bundle(bundle_dir: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    questions_path = os.path.join(bundle_dir, "questions.json")
    legacy_metadata_path = os.path.join(bundle_dir, "metadata.json")

    if os.path.exists(manifest_path) and os.path.exists(questions_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        with open(questions_path, "r", encoding="utf-8") as f:
            questions = json.load(f)
        return manifest, questions, []

    if os.path.exists(legacy_metadata_path):
        with open(legacy_metadata_path, "r", encoding="utf-8") as f:
            legacy_questions = json.load(f)
        manifest = {
            "schema_version": "legacy-metadata",
            "bundle_id": os.path.basename(bundle_dir),
            "run_id": os.path.basename(bundle_dir),
            "exam_context": {},
            "stats": {"total_questions": len(legacy_questions)},
        }
        return manifest, legacy_questions, ["Loaded legacy `metadata.json`. Please upgrade preprocessor output to bundle contract."]

    raise FileNotFoundError(
        f"Bundle files not found under: {bundle_dir}. Expected `manifest.json` + `questions.json`."
    )


def build_question_analysis(
    question: Dict[str, Any],
    bundle_dir: str,
    vlm_config: Optional[Dict[str, str]] = None,
    reasoning_llm_config: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    question_no = question.get("question_no") or question.get("number") or "UNKNOWN"
    answer_status = question.get("answer_status") or infer_answer_status(question)
    student_answer = question.get("student_answer", question.get("answer"))
    needs_manual_review = bool(question.get("needs_manual_review"))
    question_text = question.get("question_text") or question.get("description")
    question_image_path = question.get("question_image_path") or question.get("question_image") or question.get("crop_path")
    answer_image_path = question.get("answer_image_path") or question.get("answer_card_image")
    complete_unit_image_path = question.get("complete_unit_image_path")
    risk_level = infer_risk_level(answer_status, needs_manual_review)
    retrieval_query = build_retrieval_query(question_text, student_answer)
    retrieval_snapshot = build_retrieval_snapshot(
        retrieval_query,
        question.get("tags") or [],
        question.get("question_type") or question.get("type"),
        llm_config=reasoning_llm_config,
    )

    vlm_snapshot = build_vlm_snapshot(
        question=question,
        bundle_dir=bundle_dir,
        retrieval_snapshot=retrieval_snapshot,
        llm_config=vlm_config,
    )
    final_conclusion = build_final_conclusion(
        question=question,
        retrieval_snapshot=retrieval_snapshot,
        vlm_snapshot=vlm_snapshot,
        llm_config=reasoning_llm_config,
    )

    observations: List[str] = []

    if answer_status == "answered":
        observations.append("题目存在学生作答，可进入知识检索与判因阶段。")
    elif answer_status == "uncertain":
        observations.append("检测到答题区域，但答案未可靠结构化，建议补 OCR 或人工复核。")
    else:
        observations.append("未检测到明确作答，后续可结合缺考/漏答规则处理。")

    if needs_manual_review:
        observations.append("当前题目标记为需要人工复核。")

    if retrieval_snapshot["status"] == "success":
        observations.append(
            f"已完成混合检索，召回 {retrieval_snapshot['merged_hit_count']} 条候选证据，涉及 {retrieval_snapshot['graph_entity_count']} 个图谱实体。"
        )
    elif retrieval_snapshot["status"] == "unavailable":
        observations.append("当前环境未启用混合检索模块，保留检索计划供后续执行。")
    elif retrieval_snapshot["status"] == "skipped":
        observations.append("缺少可检索题干，暂跳过混合检索。")
    elif retrieval_snapshot["status"] == "empty":
        observations.append("已执行混合检索，但当前知识库未返回可用证据。")

    if vlm_snapshot["status"] == "success":
        observations.append("已基于完整单元图片完成题级 VLM 观察，可继续生成错因与讲解。")
    elif vlm_snapshot["status"] == "unavailable":
        observations.append("当前环境未启用题级 VLM 分析，已保留图片路径供后续执行。")
    elif vlm_snapshot["status"] == "skipped":
        observations.append("当前题目缺少可用完整单元图片，暂跳过题级 VLM 分析。")
    elif vlm_snapshot["status"] == "failed":
        observations.append("题级 VLM 分析执行失败，建议复查模型配置或图片资产。")

    if final_conclusion["status"] == "success":
        mode_label = "LLM 融合" if final_conclusion.get("generation_mode") == "llm" else "规则融合"
        observations.append(f"已输出最终逐题结论（{mode_label}）。")
    else:
        observations.append("当前题目尚未生成最终逐题结论。")

    for warning in retrieval_snapshot.get("warnings") or []:
        observations.append(f"检索警告：{warning}")
    for warning in vlm_snapshot.get("warnings") or []:
        observations.append(f"VLM 警告：{warning}")
    for warning in final_conclusion.get("warnings") or []:
        observations.append(f"结论警告：{warning}")

    analysis_status = "pending_manual_review" if needs_manual_review else combine_analysis_status(
        retrieval_snapshot,
        vlm_snapshot,
        final_conclusion,
    )

    return {
        "question_no": question_no,
        "question_id": question.get("question_id"),
        "question_type": question.get("question_type") or question.get("type"),
        "student_answer": student_answer,
        "answer_source": question.get("answer_source"),
        "answer_status": answer_status,
        "needs_manual_review": needs_manual_review,
        "analysis_status": analysis_status,
        "risk_level": risk_level,
        "preliminary_judgement": build_preliminary_judgement(
            answer_status,
            needs_manual_review,
            retrieval_snapshot,
            vlm_snapshot,
            final_conclusion,
        ),
        "retrieval_plan": {
            "vector_query": retrieval_query,
            "graph_entities": retrieval_snapshot.get("graph_entities") or [],
            "knowledge_tags_hint": question.get("tags") or [],
            "keywords": retrieval_snapshot.get("keywords") or [],
        },
        "retrieval_result": retrieval_snapshot,
        "vlm_plan": {
            "analysis_image_path": vlm_snapshot.get("analysis_image_path"),
            "uses_complete_unit_image": vlm_snapshot.get("uses_complete_unit_image", False),
            "supports_vision_model": vlm_snapshot.get("supports_vision_model", False),
            "retrieval_context_supplied": bool(retrieval_snapshot.get("context")),
        },
        "vlm_result": vlm_snapshot,
        "final_conclusion": final_conclusion,
        "evidence": {
            "question_text": question_text,
            "question_image_path": question_image_path,
            "answer_image_path": answer_image_path,
            "answer_image_paths": question.get("answer_image_paths") or [],
            "complete_unit_image_path": complete_unit_image_path,
            "confidence": question.get("confidence") or {},
        },
        "observations": observations,
        "next_action": determine_next_action(needs_manual_review, retrieval_snapshot, vlm_snapshot, final_conclusion),
    }




def build_retrieval_query(question_text: Optional[str], student_answer: Any) -> str:
    parts: List[str] = []
    if question_text:
        parts.append(str(question_text).strip())
    if student_answer not in EMPTY_ANSWER_VALUES:
        parts.append(f"学生答案：{student_answer}")
    return "\n".join(part for part in parts if part)


def build_retrieval_snapshot(
    query: str,
    tags: List[str],
    question_type: Optional[str],
    llm_config: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:

    fallback_terms: List[str] = []
    if question_type:
        fallback_terms.append(str(question_type))
    fallback_terms.extend(str(tag) for tag in tags if isinstance(tag, str) and tag.strip())

    if not query:
        return {
            "status": "skipped",
            "query": query,
            "keywords": [],
            "graph_entities": [],
            "graph_entity_count": 0,
            "merged_hit_count": 0,
            "top_results": [],
            "context": "",
            "warnings": [],
        }

    if hybrid_search is None:
        return {
            "status": "unavailable",
            "query": query,
            "keywords": [],
            "graph_entities": [],
            "graph_entity_count": 0,
            "merged_hit_count": 0,
            "top_results": [],
            "context": "",
            "warnings": [RETRIEVER_IMPORT_ERROR] if RETRIEVER_IMPORT_ERROR else [],
        }

    retrieval = hybrid_search(
        query,
        top_k=3,
        fallback_terms=fallback_terms,
        graph_depth=2,
    )
    graph_entities = collect_graph_entities(retrieval.get("graph_results") or [])
    top_results = [
        {
            "rank": item.get("rank"),
            "source_type": item.get("source_type"),
            "score": item.get("score"),
            "citation": item.get("citation"),
            "snippet": item.get("snippet"),
        }
        for item in retrieval.get("merged_results") or []
    ]
    status = "success" if top_results else "empty"

    return {
        "status": status,
        "query": query,
        "keywords": retrieval.get("keywords") or [],
        "graph_entities": graph_entities,
        "graph_entity_count": len(graph_entities),
        "merged_hit_count": len(top_results),
        "top_results": top_results,
        "context": retrieval.get("context") or "",
        "warnings": retrieval.get("warnings") or [],
    }



def get_vlm_config() -> Optional[Dict[str, str]]:
    if not is_vlm_enabled() or get_default_llm_config is None:
        return None
    return get_default_llm_config(prefer_vision=True)



def get_reasoning_llm_config(vlm_config: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    if get_default_llm_config is not None:
        text_config = get_default_llm_config(prefer_vision=False)
        if text_config:
            return text_config
    return vlm_config




def is_vlm_enabled() -> bool:

    flag = os.getenv("ANALYZER_ENABLE_VLM", "1").strip().lower()
    return flag not in VLM_DISABLED_VALUES



def build_vlm_snapshot(
    question: Dict[str, Any],
    bundle_dir: str,
    retrieval_snapshot: Dict[str, Any],
    llm_config: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    image_relative_path = (
        question.get("complete_unit_image_path")
        or question.get("question_image_path")
        or question.get("question_image")
        or question.get("crop_path")
    )
    uses_complete_unit_image = bool(question.get("complete_unit_image_path"))
    image_path = resolve_bundle_asset_path(bundle_dir, image_relative_path)

    base_snapshot = {
        "status": "skipped",
        "analysis_image_path": image_relative_path,
        "analysis_image_abspath": image_path,
        "uses_complete_unit_image": uses_complete_unit_image,
        "supports_vision_model": False,
        "question_summary": None,
        "answer_observation": None,
        "answer_status_assessment": None,
        "correctness": None,
        "knowledge_points": [],
        "suspected_error_causes": [],
        "reasoning_basis": [],
        "recommended_next_action": None,
        "confidence": None,
        "warnings": [],
    }

    if not image_path or not os.path.exists(image_path):
        base_snapshot["warnings"].append("缺少可用的完整单元图片或题目图片。")
        return base_snapshot

    if not is_vlm_enabled():
        base_snapshot["status"] = "unavailable"
        base_snapshot["warnings"].append("环境变量 ANALYZER_ENABLE_VLM 已关闭题级 VLM 分析。")
        return base_snapshot

    if not llm_config or call_vlm_on_image is None:
        base_snapshot["status"] = "unavailable"
        base_snapshot["warnings"].append("未找到可用的视觉模型配置。")
        return base_snapshot

    model_supports_vision = bool(supports_vision_model and supports_vision_model(llm_config.get("model_name")))
    base_snapshot["supports_vision_model"] = model_supports_vision
    if not model_supports_vision:
        base_snapshot["status"] = "unavailable"
        base_snapshot["warnings"].append(f"当前默认模型 `{llm_config.get('model_name')}` 不是视觉模型。")
        return base_snapshot

    prompt = build_vlm_prompt(question, retrieval_snapshot)
    try:
        response = call_vlm_on_image(
            image_path=image_path,
            prompt=prompt,
            llm_config=llm_config,
            json_mode=True,
        )
        if not response:
            raise ValueError("VLM returned empty response")
        payload = json.loads(response)
    except Exception as exc:
        base_snapshot["status"] = "failed"
        base_snapshot["warnings"].append(str(exc))
        return base_snapshot

    base_snapshot.update(
        {
            "status": "success",
            "question_summary": payload.get("question_summary"),
            "answer_observation": payload.get("answer_observation"),
            "answer_status_assessment": payload.get("answer_status_assessment"),
            "correctness": payload.get("correctness"),
            "knowledge_points": normalize_string_list(payload.get("knowledge_points")),
            "suspected_error_causes": normalize_string_list(payload.get("suspected_error_causes")),
            "reasoning_basis": normalize_string_list(payload.get("reasoning_basis")),
            "recommended_next_action": payload.get("recommended_next_action"),
            "confidence": normalize_confidence(payload.get("confidence")),
        }
    )
    return base_snapshot



def build_final_conclusion(
    question: Dict[str, Any],
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
    llm_config: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    rule_based = build_rule_based_final_conclusion(question, retrieval_snapshot, vlm_snapshot)

    if question.get("needs_manual_review"):
        rule_based["status"] = "skipped"
        rule_based["summary"] = "题目结构或答案识别存在不确定性，需人工复核后再输出最终逐题结论。"
        rule_based["mastery_level"] = "unknown"
        rule_based["recommended_next_action"] = "manual_review"
        return rule_based

    if call_llm is None:
        rule_based["warnings"].append("当前环境未加载文本 LLM 客户端，已降级为规则融合结论。")
        return rule_based

    if not llm_config:
        rule_based["warnings"].append("未找到可用文本模型配置，已降级为规则融合结论。")
        return rule_based

    prompt = build_final_conclusion_prompt(question, retrieval_snapshot, vlm_snapshot, rule_based)
    response = call_llm([{"role": "user", "content": prompt}], llm_config=llm_config, json_mode=True)
    if not response:
        rule_based["warnings"].append("文本模型未返回有效内容，已降级为规则融合结论。")
        return rule_based

    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        rule_based["warnings"].append("文本模型返回的不是合法 JSON，已降级为规则融合结论。")
        return rule_based

    return merge_final_conclusion_payload(rule_based, payload)



def build_rule_based_final_conclusion(
    question: Dict[str, Any],
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    answer_status = normalize_enum(vlm_snapshot.get("answer_status_assessment"), ANSWER_STATUS_VALUES) or normalize_enum(
        question.get("answer_status") or infer_answer_status(question),
        ANSWER_STATUS_VALUES,
        default="unanswered",
    )
    correctness = normalize_enum(vlm_snapshot.get("correctness"), CORRECTNESS_VALUES)
    if not correctness:
        if answer_status == "uncertain":
            correctness = "uncertain"
        elif answer_status == "unanswered":
            correctness = "unknown"
        else:
            correctness = "unknown"

    knowledge_points = unique_strings(
        normalize_string_list(vlm_snapshot.get("knowledge_points"))
        + normalize_string_list(retrieval_snapshot.get("graph_entities"))
        + normalize_string_list(retrieval_snapshot.get("keywords")),
        limit=6,
    )
    error_causes = unique_strings(
        normalize_string_list(vlm_snapshot.get("suspected_error_causes")) or derive_default_error_causes(
            correctness,
            answer_status,
            knowledge_points,
        ),
        limit=4,
    )
    supporting_evidence = unique_strings(
        normalize_string_list(vlm_snapshot.get("reasoning_basis")) + extract_retrieval_evidence(retrieval_snapshot),
        limit=5,
    )
    confidence = normalize_confidence(vlm_snapshot.get("confidence"))
    recommended_next_action = (
        normalize_text(vlm_snapshot.get("recommended_next_action"))
        or derive_recommended_next_action(answer_status, correctness, retrieval_snapshot, vlm_snapshot)
    )
    mastery_level = infer_mastery_level(correctness, answer_status, confidence)
    explanation = build_rule_based_explanation(
        question=question,
        answer_status=answer_status,
        correctness=correctness,
        knowledge_points=knowledge_points,
        retrieval_snapshot=retrieval_snapshot,
        vlm_snapshot=vlm_snapshot,
    )
    study_advice = build_rule_based_study_advice(
        answer_status=answer_status,
        correctness=correctness,
        knowledge_points=knowledge_points,
        retrieval_snapshot=retrieval_snapshot,
    )
    summary = build_rule_based_summary(answer_status, correctness, mastery_level, knowledge_points)

    evidence_sources: List[str] = []
    if retrieval_snapshot.get("status") in {"success", "empty"}:
        evidence_sources.append("retrieval")
    if vlm_snapshot.get("status") == "success":
        evidence_sources.append("vlm")

    return {
        "status": "success",
        "generation_mode": "rule_based",
        "summary": summary,
        "answer_status": answer_status,
        "correctness": correctness,
        "mastery_level": mastery_level,
        "knowledge_points": knowledge_points,
        "error_causes": error_causes,
        "explanation": explanation,
        "study_advice": study_advice,
        "supporting_evidence": supporting_evidence,
        "recommended_next_action": recommended_next_action,
        "confidence": confidence,
        "evidence_sources": evidence_sources,
        "warnings": [],
    }



def build_final_conclusion_prompt(
    question: Dict[str, Any],
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
    rule_based: Dict[str, Any],
) -> str:
    prompt_payload = {
        "question_no": question.get("question_no") or question.get("number") or "UNKNOWN",
        "question_type": question.get("question_type") or question.get("type"),
        "question_text": question.get("question_text") or question.get("description") or "",
        "student_answer": question.get("student_answer", question.get("answer")),
        "structured_answer_status": question.get("answer_status") or infer_answer_status(question),
        "retrieval_result": {
            "status": retrieval_snapshot.get("status"),
            "keywords": retrieval_snapshot.get("keywords") or [],
            "graph_entities": retrieval_snapshot.get("graph_entities") or [],
            "top_results": retrieval_snapshot.get("top_results") or [],
            "warnings": retrieval_snapshot.get("warnings") or [],
        },
        "vlm_result": {
            "status": vlm_snapshot.get("status"),
            "question_summary": vlm_snapshot.get("question_summary"),
            "answer_observation": vlm_snapshot.get("answer_observation"),
            "answer_status_assessment": vlm_snapshot.get("answer_status_assessment"),
            "correctness": vlm_snapshot.get("correctness"),
            "knowledge_points": vlm_snapshot.get("knowledge_points") or [],
            "suspected_error_causes": vlm_snapshot.get("suspected_error_causes") or [],
            "reasoning_basis": vlm_snapshot.get("reasoning_basis") or [],
            "recommended_next_action": vlm_snapshot.get("recommended_next_action"),
            "confidence": vlm_snapshot.get("confidence"),
            "warnings": vlm_snapshot.get("warnings") or [],
        },
        "rule_based_draft": rule_based,
    }
    prompt_lines = [
        "你是一名试卷分析助手。请把检索结果 retrieval_result 与题级 VLM 观察 vlm_result 融合成最终逐题结论。",
        "只允许依据提供的证据作答；如果证据不足，请保留 uncertain 或 unknown，不要臆造标准答案。",
        "请只返回 JSON 对象，不要输出额外说明。",
        "JSON schema:",
        '{"summary":"","answer_status":"answered|uncertain|unanswered","correctness":"correct|incorrect|uncertain|unknown","mastery_level":"mastered|partial|weak|unknown","knowledge_points":[""],"error_causes":[""],"explanation":"","study_advice":[""],"supporting_evidence":[""],"recommended_next_action":"","confidence":0.0}',
        "输入数据：",
        json.dumps(prompt_payload, ensure_ascii=False, indent=2),
    ]
    return "\n".join(prompt_lines)



def merge_final_conclusion_payload(rule_based: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(rule_based)
    merged.update(
        {
            "status": "success",
            "generation_mode": "llm",
            "summary": normalize_text(payload.get("summary")) or rule_based.get("summary"),
            "answer_status": normalize_enum(payload.get("answer_status"), ANSWER_STATUS_VALUES, rule_based.get("answer_status")),
            "correctness": normalize_enum(payload.get("correctness"), CORRECTNESS_VALUES, rule_based.get("correctness")),
            "mastery_level": normalize_enum(payload.get("mastery_level"), MASTERY_LEVEL_VALUES, rule_based.get("mastery_level")),
            "knowledge_points": unique_strings(
                normalize_string_list(payload.get("knowledge_points")) + (rule_based.get("knowledge_points") or []),
                limit=6,
            ),
            "error_causes": unique_strings(
                normalize_string_list(payload.get("error_causes")) + (rule_based.get("error_causes") or []),
                limit=4,
            ),
            "explanation": normalize_text(payload.get("explanation")) or rule_based.get("explanation"),
            "study_advice": unique_strings(
                normalize_string_list(payload.get("study_advice")) + (rule_based.get("study_advice") or []),
                limit=4,
            ),
            "supporting_evidence": unique_strings(
                normalize_string_list(payload.get("supporting_evidence")) + (rule_based.get("supporting_evidence") or []),
                limit=6,
            ),
            "recommended_next_action": normalize_text(payload.get("recommended_next_action")) or rule_based.get("recommended_next_action"),
            "confidence": normalize_confidence(payload.get("confidence")) if payload.get("confidence") is not None else rule_based.get("confidence"),
            "warnings": rule_based.get("warnings") or [],
        }
    )
    return merged



def derive_default_error_causes(correctness: str, answer_status: str, knowledge_points: List[str]) -> List[str]:
    if answer_status == "unanswered":
        return ["当前题目未识别到明确作答，可能存在漏答、未完成或图片信息不足。"]
    if answer_status == "uncertain":
        return ["当前作答结构化结果不稳定，需先补强识别或人工核对后再定位具体错因。"]
    if correctness == "incorrect" and knowledge_points:
        return [f"对“{knowledge_points[0]}”的理解或应用可能存在偏差。"]
    if correctness == "incorrect":
        return ["当前作答与相关知识点的标准用法可能存在偏差，建议结合题干重新核对解题过程。"]
    if correctness == "uncertain":
        return ["现有证据尚不足以确认正误，需补充标准答案或更清晰的作答信息。"]
    return []



def extract_retrieval_evidence(retrieval_snapshot: Dict[str, Any]) -> List[str]:
    evidence: List[str] = []
    for item in retrieval_snapshot.get("top_results") or []:
        citation = normalize_text(item.get("citation"))
        snippet = normalize_text(item.get("snippet"))
        if citation and snippet:
            evidence.append(f"{citation}: {snippet}")
        elif citation:
            evidence.append(citation)
        elif snippet:
            evidence.append(snippet)
        if len(evidence) >= 3:
            break
    return evidence



def build_rule_based_summary(
    answer_status: str,
    correctness: str,
    mastery_level: str,
    knowledge_points: List[str],
) -> str:
    knowledge_text = f"，重点涉及“{'、'.join(knowledge_points[:3])}”" if knowledge_points else ""
    if answer_status == "unanswered":
        return f"该题当前未识别到明确作答，暂无法判断正误{knowledge_text}。"
    if correctness == "correct":
        return f"该题初步判断为作答正确，相关知识点掌握度为 {mastery_level}{knowledge_text}。"
    if correctness == "incorrect":
        return f"该题初步判断为作答有误，相关知识点掌握度为 {mastery_level}{knowledge_text}。"
    if correctness == "uncertain":
        return f"该题暂无法稳定判断正误，相关知识点掌握度先记为 {mastery_level}{knowledge_text}。"
    return f"该题当前证据不足，暂不输出明确正误结论{knowledge_text}。"



def build_rule_based_explanation(
    question: Dict[str, Any],
    answer_status: str,
    correctness: str,
    knowledge_points: List[str],
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
) -> str:
    parts: List[str] = []
    question_summary = normalize_text(vlm_snapshot.get("question_summary"))
    answer_observation = normalize_text(vlm_snapshot.get("answer_observation"))
    if question_summary:
        parts.append(f"题目理解：{question_summary}")
    elif question.get("question_text"):
        parts.append(f"题干补充：{str(question.get('question_text')).strip()}")
    if answer_observation:
        parts.append(f"作答观察：{answer_observation}")

    if answer_status == "unanswered":
        parts.append("当前未识别到明确作答，因此只能先按未作答/漏答样本处理。")
    elif correctness == "correct":
        parts.append("综合图片观察与检索证据，当前更倾向于判定学生作答正确。")
    elif correctness == "incorrect":
        parts.append("综合图片观察与检索证据，当前更倾向于判定学生作答存在偏差。")
    elif correctness == "uncertain":
        parts.append("现有图片与检索证据仍不足以稳定确认正误，需要补充更多依据。")
    else:
        parts.append("当前缺少足够证据，暂不输出明确正误判断。")

    if knowledge_points:
        parts.append(f"关联知识点：{'、'.join(knowledge_points[:3])}。")

    retrieval_evidence = extract_retrieval_evidence(retrieval_snapshot)
    if retrieval_evidence:
        parts.append(f"检索参考：{retrieval_evidence[0]}")

    return "".join(part if part.endswith("。") else f"{part}。" for part in parts if part)



def build_rule_based_study_advice(
    answer_status: str,
    correctness: str,
    knowledge_points: List[str],
    retrieval_snapshot: Dict[str, Any],
) -> List[str]:
    advice: List[str] = []
    primary_knowledge = knowledge_points[0] if knowledge_points else None

    if answer_status == "unanswered":
        advice.append("先独立补做本题，再核对题目要求与关键步骤。")
    elif correctness == "incorrect":
        if primary_knowledge:
            advice.append(f"优先回顾“{primary_knowledge}”的定义、公式或典型例题，再重做本题。")
        advice.append("对照标准思路检查自己是在审题、概念理解还是步骤执行上出现偏差。")
    elif correctness == "correct":
        if primary_knowledge:
            advice.append(f"保持对“{primary_knowledge}”的掌握，可追加一到两道同类题巩固。")
        else:
            advice.append("当前题目表现较好，可继续用同类型题保持熟练度。")
    else:
        advice.append("补充更清晰的作答信息或标准答案后，再做一次针对性判断。")

    if retrieval_snapshot.get("status") == "success" and retrieval_snapshot.get("top_results"):
        advice.append("结合召回到的知识片段复盘本题，确认相关概念与解题路径是否一致。")

    return unique_strings(advice, limit=3)



def infer_mastery_level(correctness: str, answer_status: str, confidence: Optional[float]) -> str:
    if answer_status == "unanswered":
        return "unknown"
    if correctness == "correct":
        return "partial" if confidence is not None and confidence < 0.6 else "mastered"
    if correctness == "incorrect":
        return "weak"
    if correctness == "uncertain":
        return "partial"
    return "unknown"



def derive_recommended_next_action(
    answer_status: str,
    correctness: str,
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
) -> str:
    if answer_status == "unanswered":
        return "补做本题并确认是否存在漏答。"
    if correctness == "incorrect":
        return "回看相关知识点后重做本题，并核对关键步骤。"
    if correctness == "uncertain":
        return "补充标准答案或更清晰的作答图像后再次分析。"
    if correctness == "correct":
        return "记录为已掌握题型，可追加同类题巩固。"
    if vlm_snapshot.get("status") == "success" or retrieval_snapshot.get("status") == "success":
        return "保留当前分析快照，待补充更多证据后更新结论。"
    return "补充知识库证据或图片后重新分析。"



def normalize_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None



def normalize_enum(value: Any, allowed_values: set, default: Optional[str] = None) -> Optional[str]:
    normalized = normalize_text(value)
    if not normalized:
        return default
    lowered = normalized.lower()
    if lowered in allowed_values:
        return lowered
    return default



def unique_strings(values: List[Any], limit: Optional[int] = None) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in values:
        text = normalize_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return result



def build_vlm_prompt(question: Dict[str, Any], retrieval_snapshot: Dict[str, Any]) -> str:

    question_text = str(question.get("question_text") or "").strip() or "无"
    student_answer = question.get("student_answer")
    retrieval_context = retrieval_snapshot.get("context") or "无"
    answer_status = question.get("answer_status") or infer_answer_status(question)
    prompt = resolve_prompt_template(
        "analyzer.question_vlm",
        variables={
            "question_text": question_text,
            "student_answer": student_answer if student_answer not in EMPTY_ANSWER_VALUES else "无",
            "answer_status": answer_status,
            "retrieval_context": retrieval_context,
        },
    )
    return prompt or question_text




def resolve_bundle_asset_path(bundle_dir: str, asset_path: Optional[str]) -> Optional[str]:
    if not asset_path:
        return None
    if os.path.isabs(asset_path):
        return asset_path
    return os.path.normpath(os.path.join(bundle_dir, asset_path))



def normalize_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
    return normalized



def normalize_confidence(value: Any) -> Optional[float]:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return round(confidence, 4)



def collect_graph_entities(graph_results: List[Dict[str, Any]]) -> List[str]:

    entities: List[str] = []
    seen = set()

    for item in graph_results:
        metadata = item.get("metadata") or {}
        for entity in metadata.get("entities") or []:
            if not entity or entity in seen:
                continue
            seen.add(entity)
            entities.append(entity)
    return entities


def retrieval_snapshot_to_status(retrieval_snapshot: Dict[str, Any]) -> str:
    status = retrieval_snapshot.get("status")
    if status == "success":
        return "retrieval_context_ready"
    if status == "empty":
        return "ready_for_rag"
    if status == "unavailable":
        return "ready_for_rag"
    return "ready_for_rag"



def combine_analysis_status(
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
    final_conclusion: Optional[Dict[str, Any]] = None,
) -> str:
    if (final_conclusion or {}).get("status") == "success":
        return "question_conclusion_ready"
    if vlm_snapshot.get("status") == "success":
        return "vlm_analysis_ready"
    return retrieval_snapshot_to_status(retrieval_snapshot)



def determine_next_action(
    needs_manual_review: bool,
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
    final_conclusion: Optional[Dict[str, Any]] = None,
) -> str:
    if needs_manual_review:
        return "manual_review"
    if (final_conclusion or {}).get("status") == "success":
        return "completed"
    if vlm_snapshot.get("status") == "success":
        return "finalize_question_analysis"
    if retrieval_snapshot.get("status") == "success":
        return "generate_reasoning"
    if retrieval_snapshot.get("status") == "empty":
        return "expand_knowledge_base"
    return "rag_and_graph_analysis"




def build_analysis_report(
    manifest: Dict[str, Any],
    question_analyses: List[Dict[str, Any]],
    load_warnings: List[str],
) -> Dict[str, Any]:
    total_questions = len(question_analyses)
    answered = sum(1 for item in question_analyses if item.get("answer_status") == "answered")
    unanswered = sum(1 for item in question_analyses if item.get("answer_status") == "unanswered")
    uncertain = sum(1 for item in question_analyses if item.get("answer_status") == "uncertain")
    manual_review = sum(1 for item in question_analyses if item.get("needs_manual_review"))
    retrieval_ready = sum(1 for item in question_analyses if item.get("analysis_status") == "retrieval_context_ready")
    retrieval_hits = sum(1 for item in question_analyses if (item.get("retrieval_result") or {}).get("merged_hit_count", 0) > 0)
    vlm_ready = sum(1 for item in question_analyses if item.get("analysis_status") == "vlm_analysis_ready")
    vlm_hits = sum(1 for item in question_analyses if (item.get("vlm_result") or {}).get("status") == "success")
    final_ready = sum(1 for item in question_analyses if (item.get("final_conclusion") or {}).get("status") == "success")
    correct_questions = sum(1 for item in question_analyses if (item.get("final_conclusion") or {}).get("correctness") == "correct")
    incorrect_questions = sum(1 for item in question_analyses if (item.get("final_conclusion") or {}).get("correctness") == "incorrect")
    weak_mastery_questions = sum(1 for item in question_analyses if (item.get("final_conclusion") or {}).get("mastery_level") == "weak")


    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    warnings = list(load_warnings) + list(manifest.get("warnings") or [])
    retrieval_warnings = [
        warning
        for item in question_analyses
        for warning in (item.get("retrieval_result") or {}).get("warnings") or []
    ]
    vlm_warnings = [
        warning
        for item in question_analyses
        for warning in (item.get("vlm_result") or {}).get("warnings") or []
    ]
    conclusion_warnings = [
        warning
        for item in question_analyses
        for warning in (item.get("final_conclusion") or {}).get("warnings") or []
    ]
    warnings.extend(sorted(set(retrieval_warnings + vlm_warnings + conclusion_warnings)))


    return {
        "status": "success",
        "analysis_mode": "bundle_contract_hybrid_retrieval_vlm_conclusion",
        "message": "Bundle consumed successfully. Retrieval context, question-level VLM snapshots, and fused per-question conclusions have been prepared.",

        "generated_at": generated_at,
        "bundle_id": manifest.get("bundle_id"),
        "run_id": manifest.get("run_id"),
        "schema_version": manifest.get("schema_version"),
        "exam_context": manifest.get("exam_context") or {},
        "input_stats": manifest.get("stats") or {},
        "summary": {
            "total_questions": total_questions,
            "answered_questions": answered,
            "unanswered_questions": unanswered,
            "uncertain_questions": uncertain,
            "manual_review_questions": manual_review,
            "ready_for_rag_questions": total_questions - manual_review,
            "retrieval_context_ready_questions": retrieval_ready,
            "retrieval_hit_questions": retrieval_hits,
            "vlm_analysis_ready_questions": vlm_ready,
            "vlm_success_questions": vlm_hits,
            "final_conclusion_ready_questions": final_ready,
            "correct_questions": correct_questions,
            "incorrect_questions": incorrect_questions,
            "weak_mastery_questions": weak_mastery_questions,
            "completion_rate": round(answered / total_questions, 4) if total_questions else 0,

        },
        "outputs": {
            "question_analyses_file": "question_analyses.json",
            "report_file": "analysis_report.json",
        },
        "manual_review_question_nos": [
            item.get("question_no") for item in question_analyses if item.get("needs_manual_review")
        ],
        "warnings": warnings,
    }



def infer_answer_status(question: Dict[str, Any]) -> str:
    answer = question.get("student_answer") or question.get("answer")
    if answer not in EMPTY_ANSWER_VALUES:
        return "answered"
    if question.get("answer_image_path") or question.get("answer_image_paths"):
        return "uncertain"
    return "unanswered"


def infer_risk_level(answer_status: str, needs_manual_review: bool) -> str:
    if needs_manual_review or answer_status == "uncertain":
        return "high"
    if answer_status == "unanswered":
        return "medium"
    return "low"


def build_preliminary_judgement(
    answer_status: str,
    needs_manual_review: bool,
    retrieval_snapshot: Dict[str, Any],
    vlm_snapshot: Dict[str, Any],
    final_conclusion: Optional[Dict[str, Any]] = None,
) -> str:
    if needs_manual_review:
        return "题目结构或答案识别存在不确定性，暂不进入正式学情判断。"
    if (final_conclusion or {}).get("status") == "success":
        return final_conclusion.get("summary") or "已生成最终逐题结论。"
    if vlm_snapshot.get("status") == "success":
        return "已基于完整单元图片完成题级 VLM 观察，并结合检索证据进入判因整理阶段。"
    if retrieval_snapshot.get("status") == "success":
        return "已完成图谱+向量混合检索，可继续进入判因与答案生成。"
    if answer_status == "answered":
        return "已具备进入 RAG + 知识图谱分析的基础条件。"
    if answer_status == "uncertain":
        return "检测到作答痕迹，但需要先补强答案结构化。"
    return "当前题目未识别到明确作答，可按未作答样本处理。"




if __name__ == "__main__":
    main()
