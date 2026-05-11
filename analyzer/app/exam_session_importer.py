import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from . import crud, schemas
from .question_matcher import ExamSessionMatchingService
from .subject_utils import normalize_subject



class BundleImportError(ValueError):
    pass


class ExamSessionBundleImportService:
    def __init__(self, matching_service: Optional[ExamSessionMatchingService] = None):
        self.matching_service = matching_service or ExamSessionMatchingService()

    def import_bundle(self, db: Session, payload: schemas.ExamSessionBundleImportRequest) -> Dict[str, Any]:

        bundle_root, manifest, questions, warnings = self._load_bundle(payload.bundle_dir)
        exam_context = manifest.get("exam_context") or {}
        student_id = self._resolve_student_id(payload.student_id, exam_context.get("student_id"))
        subject = normalize_subject(self._coalesce_text(payload.subject, exam_context.get("subject")))
        exam_date = payload.exam_date or self._parse_exam_date(exam_context.get("exam_date"))
        sheet_page_map = {
            str(sheet.get("sheet_id")): sheet.get("page_index")
            for sheet in (manifest.get("sheets") or [])
            if sheet.get("sheet_id")
        }

        question_payloads: List[schemas.ExamSessionQuestionCreate] = []
        for index, question in enumerate(questions, start=1):
            question_payloads.append(
                self._build_question_payload(
                    question=question,
                    fallback_question_no=str(index),
                    bundle_root=bundle_root,
                    manifest=manifest,
                    sheet_page_map=sheet_page_map,
                    warnings=warnings,
                )
            )

        if not question_payloads:
            raise BundleImportError("bundle 中未找到可导入的题目数据")

        exam_session_payload = schemas.ExamSessionCreate(
            tenant_id=payload.tenant_id,
            student_id=student_id,
            source_document_id=payload.source_document_id,
            exam_date=exam_date,
            subject=subject,
            parse_status="completed",
            matching_status="pending",
            analysis_status="pending",
            visibility_scope=payload.visibility_scope,
            bundle_dir=str(Path(payload.bundle_dir).resolve()),
            questions=question_payloads,
        )
        exam_session = crud.create_exam_session(db, exam_session_payload)
        match_result = None
        match_error = None
        if payload.auto_match:
            try:
                raw_match_result = self.matching_service.match_exam_session(
                    db=db,
                    exam_session_id=exam_session.id,
                    top_k=payload.match_top_k,
                    accept_threshold=payload.match_accept_threshold,
                    min_gap=payload.match_min_gap,
                )
                match_result = self._build_match_summary(raw_match_result)
            except Exception as exc:
                match_error = str(exc)
                warnings.append(f"自动匹配失败: {match_error}")
            exam_session = crud.get_exam_session(db, exam_session.id)
        return {
            "bundle_id": manifest.get("bundle_id") or bundle_root.name,
            "run_id": manifest.get("run_id") or bundle_root.name,
            "question_count": len(question_payloads),
            "warnings": warnings,
            "auto_match_requested": payload.auto_match,
            "match_result": match_result,
            "match_error": match_error,
            "exam_session": exam_session,
        }


    def _build_match_summary(self, raw_match_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": raw_match_result.get("status") or "unknown",
            "exam_session_id": raw_match_result.get("exam_session_id"),
            "matched_paper_id": raw_match_result.get("matched_paper_id"),
            "matched_question_count": int(raw_match_result.get("matched_question_count") or 0),
            "pending_review_count": int(raw_match_result.get("pending_review_count") or 0),
            "question_count": int(raw_match_result.get("question_count") or 0),
            "questions": raw_match_result.get("questions") or [],
        }

    def _load_bundle(self, bundle_dir: str) -> Tuple[Path, Dict[str, Any], List[Dict[str, Any]], List[str]]:

        bundle_root = Path(bundle_dir).expanduser().resolve()
        if not bundle_root.exists() or not bundle_root.is_dir():
            raise BundleImportError(f"bundle 目录不存在: {bundle_root}")

        manifest_path = bundle_root / "manifest.json"
        questions_path = bundle_root / "questions.json"
        legacy_metadata_path = bundle_root / "metadata.json"
        warnings: List[str] = []

        if manifest_path.exists() and questions_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            questions = json.loads(questions_path.read_text(encoding="utf-8"))
            if not isinstance(questions, list):
                raise BundleImportError("questions.json 格式错误，预期为数组")
            return bundle_root, manifest, questions, warnings

        if legacy_metadata_path.exists():
            legacy_questions = json.loads(legacy_metadata_path.read_text(encoding="utf-8"))
            if not isinstance(legacy_questions, list):
                raise BundleImportError("metadata.json 格式错误，预期为数组")
            warnings.append("Loaded legacy metadata.json; 建议升级 preprocessor 输出到 manifest/questions bundle 合同。")
            return (
                bundle_root,
                {
                    "schema_version": "legacy-metadata",
                    "bundle_id": bundle_root.name,
                    "run_id": bundle_root.name,
                    "exam_context": {},
                    "stats": {"total_questions": len(legacy_questions)},
                },
                legacy_questions,
                warnings,
            )

        raise BundleImportError(
            f"bundle 文件缺失: {bundle_root}。预期包含 manifest.json + questions.json，或兼容的 metadata.json"
        )

    def _build_question_payload(
        self,
        question: Dict[str, Any],
        fallback_question_no: str,
        bundle_root: Path,
        manifest: Dict[str, Any],
        sheet_page_map: Dict[str, Any],
        warnings: List[str],
    ) -> schemas.ExamSessionQuestionCreate:
        question_no = str(question.get("question_no") or question.get("number") or fallback_question_no)
        recognized_text = self._coalesce_text(question.get("question_text"), question.get("description"))
        review_status = "needs_review" if question.get("needs_manual_review") or not recognized_text else "pending"
        page_no = self._safe_int(sheet_page_map.get(str(question.get("sheet_id") or "")))
        question_image_path = self._resolve_asset_path(
            bundle_root,
            question.get("question_image_path") or question.get("question_image") or question.get("crop_path"),
            warnings,
            f"question_image[{question_no}]",
        )
        answer_image_path = self._resolve_asset_path(
            bundle_root,
            question.get("answer_image_path") or question.get("answer_card_image"),
            warnings,
            f"answer_image[{question_no}]",
        )
        answer_image_paths = [
            resolved
            for resolved in [
                self._resolve_asset_path(bundle_root, path, warnings, f"answer_image[{question_no}]")
                for path in (question.get("answer_image_paths") or [])
            ]
            if resolved
        ]
        complete_unit_image_path = self._resolve_asset_path(
            bundle_root,
            question.get("complete_unit_image_path"),
            warnings,
            f"complete_unit_image[{question_no}]",
        )
        parse_confidence = self._estimate_parse_confidence(question)
        student_answer_raw = self._coalesce_text(question.get("student_answer"), question.get("answer"))
        ocr_confidence = self._estimate_answer_confidence(question, student_answer_raw)

        answer_blocks_json = {
            "bundle_id": manifest.get("bundle_id"),
            "run_id": manifest.get("run_id"),
            "sheet_id": question.get("sheet_id"),
            "question_id": question.get("question_id"),
            "question_type": question.get("question_type") or question.get("type"),
            "answer_source": question.get("answer_source"),
            "answer_status": question.get("answer_status"),
            "needs_manual_review": bool(question.get("needs_manual_review")),
            "question_image_path": question_image_path,
            "answer_image_path": answer_image_path,
            "answer_image_paths": answer_image_paths,
            "complete_unit_image_path": complete_unit_image_path,
            "source_complete_unit_key": question.get("source_complete_unit_key"),
            "source_merged_number": question.get("source_merged_number"),
            "confidence": question.get("confidence") or {},
            "tags": question.get("tags") or [],
            "source": question.get("source") or {},
        }

        return schemas.ExamSessionQuestionCreate(
            source_question_no=question_no,
            recognized_text=recognized_text,
            page_no=page_no,
            parse_confidence=parse_confidence,
            review_status=review_status,
            question_image_path=question_image_path,
            student_answer_raw=student_answer_raw,
            answer_blocks_json=answer_blocks_json,
            ocr_confidence=ocr_confidence,
        )

    def _resolve_student_id(self, request_value: Optional[int], manifest_value: Any) -> int:
        candidate = request_value if request_value is not None else self._safe_int(manifest_value)
        if not candidate:
            raise BundleImportError("导入 ExamSession 时必须提供 student_id，manifest 当前未携带有效 student_id")
        return candidate

    def _parse_exam_date(self, raw_value: Any) -> Optional[date]:
        if not raw_value:
            return None
        if isinstance(raw_value, date):
            return raw_value
        text = str(raw_value).strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None

    def _estimate_parse_confidence(self, question: Dict[str, Any]) -> float:
        confidence = question.get("confidence") or {}
        score = 0.35
        if self._coalesce_text(question.get("question_text"), question.get("description")):
            score += 0.35
        if question.get("question_image_path"):
            score += 0.10
        if question.get("complete_unit_image_path"):
            score += 0.08
        if confidence.get("answer_image_count"):
            score += 0.06
        if question.get("needs_manual_review"):
            score -= 0.14
        return round(max(0.0, min(score, 0.99)), 4)

    def _estimate_answer_confidence(self, question: Dict[str, Any], student_answer_raw: Optional[str]) -> Optional[float]:
        if not student_answer_raw:
            return None
        answer_status = str(question.get("answer_status") or "").strip().lower()
        score = 0.78 if answer_status == "answered" else 0.6
        if question.get("answer_source") == "answer_card":
            score += 0.1
        if question.get("needs_manual_review"):
            score -= 0.18
        return round(max(0.0, min(score, 0.99)), 4)

    def _resolve_asset_path(
        self,
        bundle_root: Path,
        raw_path: Any,
        warnings: List[str],
        label: str,
    ) -> Optional[str]:
        if not raw_path:
            return None
        candidate = Path(str(raw_path))
        if not candidate.is_absolute():
            candidate = bundle_root / candidate
        resolved = candidate.resolve()
        if not resolved.exists():
            warnings.append(f"{label} not found: {resolved}")
        return str(resolved)

    def _safe_int(self, value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coalesce_text(self, *values: Any) -> Optional[str]:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None
