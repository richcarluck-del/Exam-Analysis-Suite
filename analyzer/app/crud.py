import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared import models
from . import schemas, security
from .question_matcher import service as match_service


def _resolve_storage_path(storage_url: str) -> Path:
    normalized_storage_url = storage_url[7:] if storage_url.startswith("file://") else storage_url
    candidate = Path(normalized_storage_url)
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def _calculate_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_user_by_phone_number(db: Session, phone_number: str):
    return db.query(models.User).filter(models.User.phone_number == phone_number).first()


def create_user(db: Session, user: schemas.UserCreate):
    hashed_password = security.get_password_hash(user.password)
    db_user = models.User(phone_number=user.phone_number, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def create_api_provider(db: Session, provider: schemas.APIProviderCreate):
    db_provider = db.query(models.APIProvider).filter(models.APIProvider.name == provider.name).first()
    encrypted_key = security.encrypt_api_key(provider.api_key)

    if db_provider:
        db_provider.api_url = str(provider.api_url)
        db_provider.encrypted_api_key = encrypted_key
    else:
        db_provider = models.APIProvider(
            name=provider.name,
            api_url=str(provider.api_url),
            encrypted_api_key=encrypted_key,
        )
        db.add(db_provider)

    db.commit()
    db.refresh(db_provider)
    return db_provider


def get_api_providers(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.APIProvider).offset(skip).limit(limit).all()


def create_llm_model(db: Session, model: schemas.LLMModelCreate, provider_id: int):
    db_model = models.LLMModel(**model.dict(), provider_id=provider_id)
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    return db_model


def get_llm_models(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.LLMModel).offset(skip).limit(limit).all()


def get_all_llm_models_with_provider(db: Session):
    return db.query(models.LLMModel).join(models.APIProvider).all()


def create_prompt(db: Session, prompt: schemas.PromptCreate):
    db_prompt = models.Prompt(**prompt.dict())
    db.add(db_prompt)
    db.commit()
    db.refresh(db_prompt)
    return db_prompt


def get_prompts(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Prompt).offset(skip).limit(limit).all()


def create_prompt_version(db: Session, version: schemas.PromptVersionCreate, prompt_id: int):
    db_version = models.PromptVersion(**version.dict(), prompt_id=prompt_id)
    db.add(db_version)
    db.commit()
    db.refresh(db_version)
    return db_version


def create_content_source(db: Session, content_source: schemas.ContentSourceCreate):
    db_source = models.ContentSource(**content_source.dict(exclude_none=True))
    db.add(db_source)
    db.commit()
    db.refresh(db_source)
    return db_source


def get_content_source(db: Session, source_id: int):
    return db.query(models.ContentSource).filter(models.ContentSource.id == source_id).first()


def get_content_sources(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.ContentSource).order_by(models.ContentSource.id.desc()).offset(skip).limit(limit).all()


def create_source_document(db: Session, document: schemas.SourceDocumentCreate):
    payload = document.dict(exclude_none=True)
    storage_path = _resolve_storage_path(payload["storage_url"])

    file_name = payload.get("file_name") or storage_path.name
    raw_file_ext = payload.get("file_ext") or storage_path.suffix
    normalized_ext = raw_file_ext.lower() if raw_file_ext else ""
    if normalized_ext and not normalized_ext.startswith("."):
        normalized_ext = f".{normalized_ext}"

    title = payload.get("title") or Path(file_name).stem
    mime_type = payload.get("mime_type") or mimetypes.guess_type(file_name)[0]

    payload["file_name"] = file_name
    payload["file_ext"] = normalized_ext.lstrip(".")
    payload["mime_type"] = mime_type
    payload["title"] = title

    if not payload.get("file_sha256") and storage_path.exists() and storage_path.is_file():
        payload["file_sha256"] = _calculate_file_sha256(storage_path)

    db_document = models.SourceDocument(**payload)
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    return db_document


def get_source_document(db: Session, document_id: int):
    return db.query(models.SourceDocument).filter(models.SourceDocument.id == document_id).first()


def get_source_documents(db: Session, skip: int = 0, limit: int = 100):
    return (
        db.query(models.SourceDocument)
        .order_by(models.SourceDocument.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_exam_session(db: Session, payload: schemas.ExamSessionCreate):
    exam_session = models.ExamSession(
        tenant_id=payload.tenant_id,
        student_id=payload.student_id,
        source_document_id=payload.source_document_id,
        exam_date=payload.exam_date,
        subject=payload.subject,
        parse_status=payload.parse_status,
        matching_status=payload.matching_status,
        analysis_status=payload.analysis_status,
        visibility_scope=payload.visibility_scope,
        bundle_dir=payload.bundle_dir,
    )
    db.add(exam_session)
    db.flush()

    for question_payload in payload.questions:
        exam_question = models.ExamSessionQuestion(
            exam_session_id=exam_session.id,
            source_question_no=question_payload.source_question_no,
            page_no=question_payload.page_no,
            recognized_text=question_payload.recognized_text,
            parse_confidence=question_payload.parse_confidence,
            review_status=question_payload.review_status,
        )
        db.add(exam_question)
        db.flush()

        if question_payload.question_image_path:
            asset = models.Asset(
                tenant_id=exam_session.tenant_id,
                owner_type="exam_question",
                owner_id=exam_question.id,
                asset_role="question_crop",
                storage_url=question_payload.question_image_path,
                page_no=question_payload.page_no,
                caption_text=f"exam_session_question:{question_payload.source_question_no}",
            )
            db.add(asset)
            db.flush()
            exam_question.question_crop_asset_id = asset.id

        if (
            question_payload.student_answer_raw is not None
            or question_payload.answer_blocks_json is not None
            or question_payload.ocr_confidence is not None
        ):
            db.add(
                models.StudentAttempt(
                    exam_session_id=exam_session.id,
                    exam_question_id=exam_question.id,
                    student_id=exam_session.student_id,
                    student_answer_raw=question_payload.student_answer_raw,
                    answer_blocks_json=question_payload.answer_blocks_json,
                    ocr_confidence=question_payload.ocr_confidence,
                )
            )

    db.commit()
    return get_exam_session(db, exam_session.id)


def get_exam_session(db: Session, exam_session_id: int):
    return db.query(models.ExamSession).filter(models.ExamSession.id == exam_session_id).first()


def get_exam_sessions(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.ExamSession).order_by(models.ExamSession.id.desc()).offset(skip).limit(limit).all()


def build_exam_session_match_views(db: Session, exam_session_id: int) -> List[Dict[str, Any]]:
    exam_session = get_exam_session(db, exam_session_id)
    if not exam_session:
        return []
    questions = (
        db.query(models.ExamSessionQuestion)
        .filter(models.ExamSessionQuestion.exam_session_id == exam_session_id)
        .order_by(models.ExamSessionQuestion.id.asc())
        .all()
    )
    if not questions:
        return []

    exam_question_ids = [question.id for question in questions]
    attempts = (
        db.query(models.StudentAttempt)
        .filter(models.StudentAttempt.exam_question_id.in_(exam_question_ids))
        .all()
    )
    attempt_map = {attempt.exam_question_id: attempt for attempt in attempts}

    match_rows = (
        db.query(models.QuestionMatchResult)
        .filter(models.QuestionMatchResult.exam_question_id.in_(exam_question_ids))
        .order_by(models.QuestionMatchResult.exam_question_id.asc(), models.QuestionMatchResult.final_score.desc())
        .all()
    )
    candidate_ids = list({row.candidate_question_id for row in match_rows})
    candidate_map = {
        item.id: item
        for item in db.query(models.QuestionItem).filter(models.QuestionItem.id.in_(candidate_ids)).all()
    } if candidate_ids else {}

    grouped_candidates: Dict[int, List[Dict[str, Any]]] = {}
    for row in match_rows:
        candidate = candidate_map.get(row.candidate_question_id)
        grouped_candidates.setdefault(row.exam_question_id, []).append(
            {
                "match_result_id": row.id,
                "candidate_question_id": row.candidate_question_id,
                "match_type": row.match_type,
                "text_score": _to_float(row.text_score),
                "vector_score": _to_float(row.vector_score),
                "overlap_score": None,
                "formula_score": _to_float(row.formula_score),
                "final_score": _to_float(row.final_score),
                "accepted": bool(row.accepted),
                "paper_id": None,
                "similarity_reason": None,
                "candidate_subject": candidate.subject if candidate else None,
                "candidate_grade": candidate.grade if candidate else None,
                "candidate_question_type": candidate.question_type if candidate else None,
                "candidate_stem": candidate.stem_plain_text if candidate else None,
                "candidate_answer": candidate.answer_text if candidate else None,
            }
        )

    views: List[Dict[str, Any]] = []
    for question in questions:
        attempt = attempt_map.get(question.id)
        views.append(
            {
                "exam_question_id": question.id,
                "source_question_no": question.source_question_no,
                "recognized_text": question.recognized_text,
                "question_item_id": question.question_item_id,
                "match_confidence": _to_float(question.match_confidence),
                "review_status": question.review_status,
                "student_attempt": {
                    "id": attempt.id,
                    "exam_session_id": attempt.exam_session_id,
                    "exam_question_id": attempt.exam_question_id,
                    "question_item_id": attempt.question_item_id,
                    "student_id": attempt.student_id,
                    "student_answer_raw": attempt.student_answer_raw,
                    "answer_blocks_json": attempt.answer_blocks_json,
                    "is_correct": attempt.is_correct,
                    "score_earned": _to_float(attempt.score_earned),
                    "time_spent_seconds": attempt.time_spent_seconds,
                    "teacher_mark_json": attempt.teacher_mark_json,
                    "ocr_confidence": _to_float(attempt.ocr_confidence),
                } if attempt else None,
                "candidates": grouped_candidates.get(question.id, []),
                "match_anchors": match_service.build_anchor_pack_from_persisted_candidates(
                    db,
                    exam_session=exam_session,
                    exam_question=question,
                ),
            }
        )
    return views
