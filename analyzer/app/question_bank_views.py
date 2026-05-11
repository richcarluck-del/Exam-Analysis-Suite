import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared import models
from .config import NORMALIZED_DOCUMENTS_DIR, QUESTION_BANK_ASSET_DIR, QUESTION_BANK_UPLOAD_DIR


_STATIC_MAPPINGS = [
    (Path(QUESTION_BANK_ASSET_DIR).resolve(), "/static/question-bank/assets"),
    (Path(NORMALIZED_DOCUMENTS_DIR).resolve(), "/static/question-bank/normalized"),
    (Path(QUESTION_BANK_UPLOAD_DIR).resolve(), "/static/question-bank/uploads"),
]


def to_public_url(storage_url: Optional[str]) -> Optional[str]:
    if not storage_url:
        return None
    if storage_url.startswith(("http://", "https://", "/static/")):
        return storage_url

    normalized_storage_url = storage_url[7:] if storage_url.startswith("file://") else storage_url
    candidate = Path(normalized_storage_url)
    try:
        candidate = candidate.resolve()
    except Exception:
        candidate = candidate.absolute()

    for base_dir, public_prefix in _STATIC_MAPPINGS:
        try:
            relative_path = candidate.relative_to(base_dir)
            return f"{public_prefix}/{relative_path.as_posix()}"
        except ValueError:
            continue
    return None


# Word/OMML 线性化常见把集合「使得」竖线写成普通斜杠：{x/x^2…} → {x|x^2…}
_SET_BUILDER_X_SOLIDUS_RE = re.compile(r"x\s*/\s*(?=x[\^²₂\u207f\u2080-\u2089])")


def _normalize_set_builder_solidus_in_text(text: str) -> str:
    if not text or "/" not in text:
        return text
    return _SET_BUILDER_X_SOLIDUS_RE.sub("x|", text)


def _decorate_render_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_decorate_render_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    decorated = {key: _decorate_render_payload(value) for key, value in payload.items()}
    storage_url = decorated.get("storage_url")
    public_url = to_public_url(storage_url) if isinstance(storage_url, str) else None
    if public_url:
        decorated["public_url"] = public_url
        if decorated.get("type") == "image":
            decorated["src"] = public_url
    if decorated.get("type") == "text" and isinstance(decorated.get("text"), str):
        decorated["text"] = _normalize_set_builder_solidus_in_text(decorated["text"])
    return decorated


def _serialize_asset(asset: models.Asset) -> Dict[str, Any]:
    return {
        "id": asset.id,
        "asset_role": asset.asset_role,
        "storage_url": asset.storage_url,
        "public_url": to_public_url(asset.storage_url),
        "thumbnail_url": asset.thumbnail_url,
        "page_no": asset.page_no,
        "width": asset.width,
        "height": asset.height,
        "bbox": asset.bbox,
        "ocr_text": asset.ocr_text,
        "caption_text": asset.caption_text,
        "file_hash": asset.file_hash,
    }


def _serialize_formula(formula: models.Formula) -> Dict[str, Any]:
    return {
        "id": formula.id,
        "block_id": formula.block_id,
        "source_type": formula.source_type,
        "latex_text": formula.latex_text,
        "mathml_text": formula.mathml_text,
        "linear_text": formula.linear_text,
        "normalized_signature": formula.normalized_signature,
        "asset_id": formula.asset_id,
    }


def _serialize_option(option: models.QuestionOption) -> Dict[str, Any]:
    return {
        "id": option.id,
        "option_key": option.option_key,
        "option_text": option.option_text,
        "formula_id": option.formula_id,
        "asset_id": option.asset_id,
        "display_order": option.display_order,
        "is_correct": option.is_correct,
    }


def _serialize_block(block: models.QuestionBlock) -> Dict[str, Any]:
    return {
        "id": block.id,
        "block_order": block.block_order,
        "block_role": block.block_role,
        "content_format": block.content_format,
        "text_content": block.text_content,
        "rich_content_json": _decorate_render_payload(block.rich_content_json),
        "formula_id": block.formula_id,
        "asset_id": block.asset_id,
        "parent_block_id": block.parent_block_id,
        "is_primary": bool(block.is_primary),
    }


def build_question_detail(
    db: Session,
    question_item: models.QuestionItem,
    paper_question: Optional[models.PaperQuestion] = None,
) -> Dict[str, Any]:
    question_blocks = (
        db.query(models.QuestionBlock)
        .filter(models.QuestionBlock.question_item_id == question_item.id)
        .order_by(models.QuestionBlock.block_order.asc())
        .all()
    )
    question_options = (
        db.query(models.QuestionOption)
        .filter(models.QuestionOption.question_item_id == question_item.id)
        .order_by(models.QuestionOption.display_order.asc())
        .all()
    )
    formulas = (
        db.query(models.Formula)
        .filter(models.Formula.question_item_id == question_item.id)
        .order_by(models.Formula.id.asc())
        .all()
    )
    assets = (
        db.query(models.Asset)
        .filter(models.Asset.owner_type == "question_item")
        .filter(models.Asset.owner_id == question_item.id)
        .order_by(models.Asset.id.asc())
        .all()
    )

    if paper_question is None:
        paper_question = (
            db.query(models.PaperQuestion)
            .filter(models.PaperQuestion.question_item_id == question_item.id)
            .order_by(models.PaperQuestion.id.asc())
            .first()
        )

    return {
        "question_item_id": question_item.id,
        "created_at": question_item.created_at.isoformat() if getattr(question_item, "created_at", None) else None,
        "updated_at": question_item.updated_at.isoformat() if getattr(question_item, "updated_at", None) else None,
        "paper_question_id": paper_question.id if paper_question else None,
        "paper_id": paper_question.paper_id if paper_question else None,
        "question_no": paper_question.question_no if paper_question else None,
        "display_order": paper_question.display_order if paper_question else None,
        "page_no": paper_question.page_no if paper_question else None,
        "anchor_bbox": paper_question.anchor_bbox if paper_question else None,
        "subject": question_item.subject,
        "grade": question_item.grade,
        "question_type": question_item.question_type,
        "stem_plain_text": question_item.stem_plain_text,
        "answer_text": question_item.answer_text,
        "solution_summary": question_item.solution_summary,
        "has_formula": bool(question_item.has_formula),
        "has_figure": bool(question_item.has_figure),
        "blocks": [_serialize_block(block) for block in question_blocks],
        "options": [_serialize_option(option) for option in question_options],
        "formulas": [_serialize_formula(formula) for formula in formulas],
        "assets": [_serialize_asset(asset) for asset in assets],
    }


def get_question_detail(db: Session, question_item_id: int) -> Optional[Dict[str, Any]]:
    question_item = db.query(models.QuestionItem).filter(models.QuestionItem.id == question_item_id).first()
    if not question_item:
        return None
    return build_question_detail(db, question_item)


def get_paper_detail(db: Session, paper_id: int) -> Optional[Dict[str, Any]]:
    paper = db.query(models.Paper).filter(models.Paper.id == paper_id).first()
    if not paper:
        return None

    source_document = paper.source_document
    paper_questions = (
        db.query(models.PaperQuestion)
        .filter(models.PaperQuestion.paper_id == paper.id)
        .order_by(models.PaperQuestion.display_order.asc(), models.PaperQuestion.id.asc())
        .all()
    )
    question_ids = [row.question_item_id for row in paper_questions if row.question_item_id]
    question_map = {}
    if question_ids:
        question_map = {
            item.id: item
            for item in db.query(models.QuestionItem).filter(models.QuestionItem.id.in_(question_ids)).all()
        }

    questions = [
        build_question_detail(db, question_map[row.question_item_id], row)
        for row in paper_questions
        if row.question_item_id in question_map
    ]

    return {
        "paper_id": paper.id,
        "source_document_id": paper.source_document_id,
        "title": paper.title,
        "subject": paper.subject,
        "grade": paper.grade,
        "year": paper.year,
        "region": paper.region,
        "total_questions": paper.total_questions,
        "normalized_docx_url": source_document.normalized_docx_url if source_document else None,
        "normalized_docx_public_url": to_public_url(source_document.normalized_docx_url) if source_document else None,
        "normalized_pdf_url": source_document.normalized_pdf_url if source_document else None,
        "normalized_pdf_public_url": to_public_url(source_document.normalized_pdf_url) if source_document else None,
        "questions": questions,
    }


def get_source_document_paper_detail(db: Session, source_document_id: int) -> Optional[Dict[str, Any]]:
    papers = (
        db.query(models.Paper)
        .filter(models.Paper.source_document_id == source_document_id)
        .order_by(models.Paper.id.asc())
        .all()
    )
    if not papers:
        return None

    paper_payloads = [get_paper_detail(db, p.id) for p in papers if p]
    first = paper_payloads[0] if paper_payloads else None
    if not first:
        return None

    merged_questions: List[Dict[str, Any]] = []
    for payload in paper_payloads:
        if not payload:
            continue
        for q in payload.get("questions") or []:
            row = dict(q)
            row["source_paper_id"] = payload.get("paper_id")
            row["source_paper_title"] = payload.get("title")
            row["knowledge_package_id"] = None
            paper_id_val = payload.get("paper_id")
            if paper_id_val:
                pobj = db.query(models.Paper).filter(models.Paper.id == paper_id_val).first()
                if pobj and getattr(pobj, "knowledge_package_id", None):
                    row["knowledge_package_id"] = pobj.knowledge_package_id
            merged_questions.append(row)

    out = dict(first)
    out["papers"] = paper_payloads
    out["paper_count"] = len(paper_payloads)
    out["questions"] = merged_questions
    out["total_questions"] = len(merged_questions)
    return out

