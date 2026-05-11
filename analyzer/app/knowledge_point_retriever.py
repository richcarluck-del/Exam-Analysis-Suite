import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session

from shared import models
from . import vector_db
from .config import KNOWLEDGE_POINT_BRIDGE_INDEX_MODE
from .knowledge_point_service import get_knowledge_package, get_knowledge_point


BRIDGE_STRONG_MEDIUM_TIERS = {"topic_strong", "topic_adjacent", "topic_evidence"}


def _should_index_bridge_link(link: models.KnowledgeQuestionLink) -> bool:
    """依据 KNOWLEDGE_POINT_BRIDGE_INDEX_MODE 决定该桥接是否写入检索索引。
    审核通过（approved_status="approved"）的链接在所有模式下都通过。
    """
    approved = (link.approved_status or "").lower() == "approved"
    mode = (KNOWLEDGE_POINT_BRIDGE_INDEX_MODE or "strong_medium").lower()
    if mode == "all":
        return True
    if approved:
        return True
    if mode == "approved_only":
        return False
    relation = (link.relation_type or "").strip()
    return relation in BRIDGE_STRONG_MEDIUM_TIERS


def _is_package_coverage_point(package_point: models.KnowledgePackagePoint) -> bool:
    status = (package_point.approved_status or "").strip().lower()
    relation_type = (package_point.relation_type or "").strip().lower()
    return status != "placeholder" and relation_type not in {"placeholder", "fallback", "dependency"}


KNOWLEDGE_ENTITY_TYPES = [
    "knowledge_point",
    "knowledge_package_point",
    "knowledge_package",
    "knowledge_block",
    "knowledge_atom",
    "knowledge_question_bridge",
    "knowledge_derivative",
]

BLOCK_VIEW_TYPE_MAP = {
    "definition": "kp_definition",
    "explainer": "kp_explainer",
    "summary": "kp_summary",
    "exam_focus": "kp_exam_focus",
    "expert_commentary": "kp_explainer",
    "table": "kp_table_row",
    "mindmap": "kp_mindmap_path",
    "image": "kp_source_restore",
    "formula": "kp_source_restore",
    "example_bridge": "kp_example_bridge",
    "pitfall": "kp_pitfall",
    "comparison": "kp_compare",
    "conclusion": "kp_summary",
}

ATOM_VIEW_TYPE_MAP = {
    "definition": "kp_definition",
    "property": "kp_summary",
    "theorem": "kp_summary",
    "method": "kp_explainer",
    "pitfall": "kp_pitfall",
    "comparison": "kp_compare",
    "conclusion": "kp_summary",
    "exam_pattern": "kp_exam_focus",
    "memory_tip": "kp_summary",
}


def _normalize_text(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_text(value)
    try:
        return _normalize_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except TypeError:
        return _normalize_text(str(value))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _build_vector_id(entity_type: str, entity_id: int, content_hash: str) -> str:
    digest = _hash_text(f"{entity_type}:{entity_id}:{content_hash}")[:24]
    return f"knowledge:{entity_type}:{entity_id}:{digest}"


def _compact_parts(parts: Iterable[Any]) -> str:
    normalized_parts = [_normalize_text(part) for part in parts if _normalize_text(part)]
    return "\n".join(normalized_parts)


def _serialize_point_text(point: models.KnowledgePoint) -> str:
    aliases = point.aliases_json if isinstance(point.aliases_json, list) else []
    return _compact_parts(
        [
            point.canonical_name,
            f"别名：{'；'.join(str(item) for item in aliases if str(item).strip())}" if aliases else None,
            point.canonical_summary,
            f"前置要求：{point.prerequisite_summary}" if point.prerequisite_summary else None,
            f"常见混淆：{_json_text(point.common_confusions_json)}" if point.common_confusions_json else None,
        ]
    )


def _serialize_package_text(package: models.KnowledgePackage) -> str:
    return _compact_parts(
        [
            package.package_title,
            package.summary_text,
            _json_text(package.outline_json),
        ]
    )


def _serialize_block_text(block: models.KnowledgeBlock) -> str:
    return _compact_parts(
        [
            block.section_path,
            block.normalized_text,
            block.raw_text,
            _json_text(block.rich_content_json),
        ]
    )


def _serialize_atom_text(atom: models.KnowledgeAtom) -> str:
    return _compact_parts(
        [
            atom.canonical_text,
            _json_text(atom.normalized_json),
            atom.formula_signature,
        ]
    )


def _serialize_question_bridge_text(
    point: models.KnowledgePoint,
    link: models.KnowledgeQuestionLink,
    question: models.QuestionItem,
) -> str:
    return _compact_parts(
        [
            f"知识点：{point.canonical_name}",
            f"题目关联：{link.relation_type}",
            f"切入点：{link.entry_point_text}" if link.entry_point_text else None,
            f"题干：{question.stem_plain_text}",
            f"答案：{question.answer_text}" if question.answer_text else None,
            f"解析摘要：{question.solution_summary}" if question.solution_summary else None,
        ]
    )


def _new_retrieval_document(
    tenant_id: Optional[int],
    entity_type: str,
    entity_id: int,
    text: str,
    metadata: Dict[str, Any],
) -> Optional[models.RetrievalDocument]:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return None
    content_hash = _hash_text(normalized_text)
    metadata_payload = {key: _stringify(value) for key, value in metadata.items() if value is not None and _stringify(value) != ""}
    metadata_payload["entity_type"] = entity_type
    metadata_payload["entity_id"] = _stringify(entity_id)
    metadata_payload["vector_id"] = _build_vector_id(entity_type, entity_id, content_hash)
    return models.RetrievalDocument(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        text_for_bm25=normalized_text,
        text_for_embedding=normalized_text,
        metadata_json=metadata_payload,
        is_active=True,
        content_hash=content_hash,
    )


def _delete_existing_documents(db: Session, retrieval_documents: Sequence[models.RetrievalDocument]) -> None:
    retrieval_ids = [item.id for item in retrieval_documents]
    if not retrieval_ids:
        return

    embedding_rows = (
        db.query(models.EmbeddingPoint)
        .filter(models.EmbeddingPoint.retrieval_document_id.in_(retrieval_ids))
        .all()
    )
    vector_ids = [row.point_id for row in embedding_rows if row.point_id]
    if not vector_ids:
        vector_ids = [
            str((item.metadata_json or {}).get("vector_id") or "")
            for item in retrieval_documents
            if (item.metadata_json or {}).get("vector_id")
        ]
    if vector_ids:
        vector_db.db.delete_documents(vector_ids)

    db.query(models.EmbeddingPoint).filter(models.EmbeddingPoint.retrieval_document_id.in_(retrieval_ids)).delete(
        synchronize_session=False
    )
    db.query(models.RetrievalDocument).filter(models.RetrievalDocument.id.in_(retrieval_ids)).delete(
        synchronize_session=False
    )
    db.flush()


def purge_knowledge_point_retrieval_documents(db: Session, knowledge_point_id: int) -> int:
    """Remove retrieval_documents / embedding_points (and vector backend) for a knowledge point
    and its child blocks, atoms, and question-bridge rows. Does not commit."""
    point = get_knowledge_point(db, knowledge_point_id)
    if not point:
        return 0

    blocks = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeBlock.id.asc())
        .all()
    )
    atoms = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeAtom.id.asc())
        .all()
    )
    link_rows = (
        db.query(models.KnowledgeQuestionLink, models.QuestionItem)
        .join(models.QuestionItem, models.QuestionItem.id == models.KnowledgeQuestionLink.question_item_id)
        .filter(models.KnowledgeQuestionLink.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeQuestionLink.id.asc())
        .all()
    )

    predicates = [
        (models.RetrievalDocument.entity_type == "knowledge_point") & (models.RetrievalDocument.entity_id == point.id),
    ]
    block_ids = [item.id for item in blocks]
    if block_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_block") & models.RetrievalDocument.entity_id.in_(block_ids)
        )
    atom_ids = [item.id for item in atoms]
    if atom_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_atom") & models.RetrievalDocument.entity_id.in_(atom_ids)
        )
    link_ids = [link.id for link, _ in link_rows]
    if link_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_question_bridge")
            & models.RetrievalDocument.entity_id.in_(link_ids)
        )

    existing_documents = db.query(models.RetrievalDocument).filter(or_(*predicates)).all()
    n = len(existing_documents)
    _delete_existing_documents(db, existing_documents)
    return n


def _persist_retrieval_documents(
    db: Session,
    retrieval_documents: Sequence[models.RetrievalDocument],
    target_type: str,
    target_id: int,
) -> Dict[str, Any]:
    if not retrieval_documents:
        return {
            "indexed_documents": 0,
            "target_type": target_type,
            "target_id": target_id,
            **vector_db.db.backend_summary,
        }

    for retrieval_document in retrieval_documents:
        db.add(retrieval_document)
    db.flush()

    payload = [
        {
            "document": retrieval_document.text_for_embedding,
            "metadata": dict(retrieval_document.metadata_json or {}),
            "id": str((retrieval_document.metadata_json or {}).get("vector_id") or retrieval_document.id),
        }
        for retrieval_document in retrieval_documents
    ]
    sync_result = vector_db.db.upsert_retrieval_documents(payload)

    for retrieval_document in retrieval_documents:
        db.add(
            models.EmbeddingPoint(
                retrieval_document_id=retrieval_document.id,
                backend_type=sync_result["vector_backend"],
                point_id=str((retrieval_document.metadata_json or {}).get("vector_id") or retrieval_document.id),
                model_name=sync_result["embedding_model"],
                vector_dim=sync_result["vector_dim"],
                content_hash=retrieval_document.content_hash,
            )
        )

    db.commit()
    return {
        "indexed_documents": len(retrieval_documents),
        "target_type": target_type,
        "target_id": target_id,
        **sync_result,
    }


def sync_knowledge_point_retrieval(db: Session, knowledge_point_id: int) -> Dict[str, Any]:
    point = get_knowledge_point(db, knowledge_point_id)
    if not point:
        raise ValueError("Knowledge point not found")

    blocks = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeBlock.id.asc())
        .all()
    )
    atoms = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeAtom.id.asc())
        .all()
    )
    link_rows = (
        db.query(models.KnowledgeQuestionLink, models.QuestionItem)
        .join(models.QuestionItem, models.QuestionItem.id == models.KnowledgeQuestionLink.question_item_id)
        .filter(models.KnowledgeQuestionLink.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeQuestionLink.id.asc())
        .all()
    )

    predicates = [
        (models.RetrievalDocument.entity_type == "knowledge_point") & (models.RetrievalDocument.entity_id == point.id),
    ]
    block_ids = [item.id for item in blocks]
    if block_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_block") & models.RetrievalDocument.entity_id.in_(block_ids)
        )
    atom_ids = [item.id for item in atoms]
    if atom_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_atom") & models.RetrievalDocument.entity_id.in_(atom_ids)
        )
    link_ids = [link.id for link, _ in link_rows]
    if link_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_question_bridge")
            & models.RetrievalDocument.entity_id.in_(link_ids)
        )

    existing_documents = db.query(models.RetrievalDocument).filter(or_(*predicates)).all()
    metadata_scoped_documents = []
    metadata_candidates = (
        db.query(models.RetrievalDocument)
        .filter(
            models.RetrievalDocument.entity_type.in_(
                [
                    "knowledge_package",
                    "knowledge_package_point",
                    "knowledge_block",
                    "knowledge_atom",
                    "knowledge_question_bridge",
                ]
            )
        )
        .all()
    )
    for item in metadata_candidates:
        metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
        if str(metadata.get("package_id") or "") == str(package.id):
            metadata_scoped_documents.append(item)
    existing_documents = list({item.id: item for item in [*existing_documents, *metadata_scoped_documents]}.values())
    _delete_existing_documents(db, existing_documents)

    retrieval_documents: List[models.RetrievalDocument] = []
    point_document = _new_retrieval_document(
        tenant_id=point.tenant_id,
        entity_type="knowledge_point",
        entity_id=point.id,
        text=_serialize_point_text(point),
        metadata={
            "source": f"knowledge_point:{point.id}",
            "knowledge_point_id": point.id,
            "knowledge_point_name": point.canonical_name,
            "subject": point.subject,
            "grade": point.grade_scope,
            "view_type": "kp_summary",
            "title": point.canonical_name,
            "review_status": point.review_status,
        },
    )
    if point_document:
        retrieval_documents.append(point_document)

    for block in blocks:
        block_document = _new_retrieval_document(
            tenant_id=point.tenant_id,
            entity_type="knowledge_block",
            entity_id=block.id,
            text=_serialize_block_text(block),
            metadata={
                "source": f"knowledge_block:{block.id}",
                "knowledge_point_id": point.id,
                "knowledge_point_name": point.canonical_name,
                "package_id": block.package_id,
                "subject": point.subject,
                "grade": point.grade_scope,
                "block_role": block.block_role,
                "view_type": BLOCK_VIEW_TYPE_MAP.get(block.block_role, "kp_source_restore"),
                "title": block.section_path or point.canonical_name,
                "source_page_no": block.source_page_no,
                "section_path": block.section_path,
            },
        )
        if block_document:
            retrieval_documents.append(block_document)

    for atom in atoms:
        atom_document = _new_retrieval_document(
            tenant_id=point.tenant_id,
            entity_type="knowledge_atom",
            entity_id=atom.id,
            text=_serialize_atom_text(atom),
            metadata={
                "source": f"knowledge_atom:{atom.id}",
                "knowledge_point_id": point.id,
                "knowledge_point_name": point.canonical_name,
                "package_id": atom.package_id,
                "subject": point.subject,
                "grade": point.grade_scope,
                "atom_type": atom.atom_type,
                "view_type": ATOM_VIEW_TYPE_MAP.get(atom.atom_type, "kp_summary"),
                "title": point.canonical_name,
                "review_status": atom.review_status,
            },
        )
        if atom_document:
            retrieval_documents.append(atom_document)

    for link, question in link_rows:
        if not _should_index_bridge_link(link):
            continue
        tier_label = (
            "strong" if (link.relation_type or "") == "topic_strong"
            else ("weak" if (link.relation_type or "") == "topic_fallback" else "medium")
        )
        bridge_document = _new_retrieval_document(
            tenant_id=point.tenant_id,
            entity_type="knowledge_question_bridge",
            entity_id=link.id,
            text=_serialize_question_bridge_text(point, link, question),
            metadata={
                "source": f"knowledge_question_bridge:{link.id}",
                "knowledge_point_id": point.id,
                "knowledge_point_name": point.canonical_name,
                "question_item_id": question.id,
                "subject": question.subject or point.subject,
                "grade": question.grade or point.grade_scope,
                "block_role": "example_bridge",
                "view_type": "kp_example_bridge",
                "title": point.canonical_name,
                "relation_type": link.relation_type,
                "relevance_score": link.relevance_score,
                "confidence": link.confidence,
                "approved_status": link.approved_status,
                "bridge_tier": tier_label,
            },
        )
        if bridge_document:
            retrieval_documents.append(bridge_document)

    return _persist_retrieval_documents(db, retrieval_documents, target_type="knowledge_point", target_id=point.id)


def sync_knowledge_package_retrieval(db: Session, package_id: int) -> Dict[str, Any]:
    package = get_knowledge_package(db, package_id)
    if not package:
        raise ValueError("Knowledge package not found")

    blocks = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .order_by(models.KnowledgeBlock.id.asc())
        .all()
    )
    atoms = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.package_id == package_id)
        .order_by(models.KnowledgeAtom.id.asc())
        .all()
    )
    all_package_point_rows = (
        db.query(models.KnowledgePackagePoint, models.KnowledgePoint)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .order_by(models.KnowledgePackagePoint.order_in_package.asc().nullslast(), models.KnowledgePackagePoint.id.asc())
        .all()
    )
    package_point_rows = [row for row in all_package_point_rows if _is_package_coverage_point(row[0])]
    package_question_ids = [
        row[0]
        for row in db.query(models.KnowledgePackageQuestion.question_item_id)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .all()
    ]
    link_rows = []
    if package_question_ids:
        link_rows = (
            db.query(models.KnowledgeQuestionLink, models.KnowledgePoint, models.QuestionItem)
            .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgeQuestionLink.knowledge_point_id)
            .join(models.QuestionItem, models.QuestionItem.id == models.KnowledgeQuestionLink.question_item_id)
            .filter(models.KnowledgeQuestionLink.question_item_id.in_(package_question_ids))
            .order_by(models.KnowledgeQuestionLink.id.asc())
            .all()
        )

    predicates = [
        (models.RetrievalDocument.entity_type == "knowledge_package") & (models.RetrievalDocument.entity_id == package.id),
    ]
    package_point_ids = [row.id for row, _ in all_package_point_rows]
    if package_point_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_package_point")
            & models.RetrievalDocument.entity_id.in_(package_point_ids)
        )
    block_ids = [item.id for item in blocks]
    if block_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_block") & models.RetrievalDocument.entity_id.in_(block_ids)
        )
    atom_ids = [item.id for item in atoms]
    if atom_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_atom") & models.RetrievalDocument.entity_id.in_(atom_ids)
        )
    link_ids = [link.id for link, _, _ in link_rows]
    if link_ids:
        predicates.append(
            (models.RetrievalDocument.entity_type == "knowledge_question_bridge")
            & models.RetrievalDocument.entity_id.in_(link_ids)
        )
    existing_documents = db.query(models.RetrievalDocument).filter(or_(*predicates)).all()
    _delete_existing_documents(db, existing_documents)

    retrieval_documents: List[models.RetrievalDocument] = []
    package_document = _new_retrieval_document(
        tenant_id=package.tenant_id,
        entity_type="knowledge_package",
        entity_id=package.id,
        text=_serialize_package_text(package),
        metadata={
            "source": f"knowledge_package:{package.id}",
            "package_id": package.id,
            "package_title": package.package_title,
            "source_document_id": package.source_document_id,
            "subject": package.subject,
            "grade": package.grade,
            "view_type": "kp_summary",
            "title": package.package_title,
            "review_status": package.review_status,
        },
    )
    if package_document:
        retrieval_documents.append(package_document)

    point_names = {
        point.id: point.canonical_name
        for _, point in package_point_rows
    }

    for package_point, point in package_point_rows:
        point_document = _new_retrieval_document(
            tenant_id=package.tenant_id or point.tenant_id,
            entity_type="knowledge_package_point",
            entity_id=package_point.id,
            text=_compact_parts(
                [
                    f"专题：{package.package_title}",
                    f"知识点：{point.canonical_name}",
                    _serialize_point_text(point),
                    f"包内关系：{package_point.relation_type}",
                ]
            ),
            metadata={
                "source": f"knowledge_package_point:{package_point.id}",
                "package_id": package.id,
                "package_title": package.package_title,
                "knowledge_point_id": point.id,
                "knowledge_point_name": point.canonical_name,
                "subject": package.subject or point.subject,
                "grade": package.grade or point.grade_scope,
                "view_type": "kp_summary",
                "title": point.canonical_name,
                "relation_type": package_point.relation_type,
                "weight_score": package_point.weight_score,
                "confidence": package_point.confidence,
                "approved_status": package_point.approved_status,
                "review_status": point.review_status,
            },
        )
        if point_document:
            retrieval_documents.append(point_document)

    for block in blocks:
        block_document = _new_retrieval_document(
            tenant_id=package.tenant_id,
            entity_type="knowledge_block",
            entity_id=block.id,
            text=_serialize_block_text(block),
            metadata={
                "source": f"knowledge_block:{block.id}",
                "package_id": package.id,
                "package_title": package.package_title,
                "knowledge_point_id": block.knowledge_point_id,
                "knowledge_point_name": point_names.get(block.knowledge_point_id),
                "subject": package.subject,
                "grade": package.grade,
                "block_role": block.block_role,
                "view_type": BLOCK_VIEW_TYPE_MAP.get(block.block_role, "kp_source_restore"),
                "title": block.section_path or package.package_title,
                "source_page_no": block.source_page_no,
                "section_path": block.section_path,
            },
        )
        if block_document:
            retrieval_documents.append(block_document)

    for atom in atoms:
        point_name = point_names.get(atom.knowledge_point_id)
        atom_document = _new_retrieval_document(
            tenant_id=package.tenant_id,
            entity_type="knowledge_atom",
            entity_id=atom.id,
            text=_serialize_atom_text(atom),
            metadata={
                "source": f"knowledge_atom:{atom.id}",
                "package_id": package.id,
                "package_title": package.package_title,
                "knowledge_point_id": atom.knowledge_point_id,
                "knowledge_point_name": point_name,
                "subject": package.subject,
                "grade": package.grade,
                "atom_type": atom.atom_type,
                "view_type": ATOM_VIEW_TYPE_MAP.get(atom.atom_type, "kp_summary"),
                "title": point_name or package.package_title,
                "review_status": atom.review_status,
            },
        )
        if atom_document:
            retrieval_documents.append(atom_document)

    for link, point, question in link_rows:
        if point.id not in point_names:
            continue
        if not _should_index_bridge_link(link):
            continue
        tier_label = (
            "strong" if (link.relation_type or "") == "topic_strong"
            else ("weak" if (link.relation_type or "") == "topic_fallback" else "medium")
        )
        bridge_document = _new_retrieval_document(
            tenant_id=package.tenant_id or point.tenant_id,
            entity_type="knowledge_question_bridge",
            entity_id=link.id,
            text=_compact_parts(
                [
                    f"专题：{package.package_title}",
                    _serialize_question_bridge_text(point, link, question),
                ]
            ),
            metadata={
                "source": f"knowledge_question_bridge:{link.id}",
                "package_id": package.id,
                "package_title": package.package_title,
                "knowledge_point_id": point.id,
                "knowledge_point_name": point.canonical_name,
                "question_item_id": question.id,
                "subject": question.subject or package.subject or point.subject,
                "grade": question.grade or package.grade or point.grade_scope,
                "block_role": "example_bridge",
                "view_type": "kp_example_bridge",
                "title": point.canonical_name,
                "relation_type": link.relation_type,
                "relevance_score": link.relevance_score,
                "confidence": link.confidence,
                "approved_status": link.approved_status,
                "bridge_tier": tier_label,
            },
        )
        if bridge_document:
            retrieval_documents.append(bridge_document)

    return _persist_retrieval_documents(db, retrieval_documents, target_type="knowledge_package", target_id=package.id)


def _trim_snippet(text: str, max_length: int = 220) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3] + "..."


def search_knowledge_documents(
    db: Session,
    query: str,
    top_k: int = 5,
    subject: Optional[str] = None,
    grade: Optional[str] = None,
    package_id: Optional[int] = None,
    knowledge_point_id: Optional[int] = None,
    view_types: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    metadata_filters: Dict[str, Any] = {}
    if subject:
        metadata_filters["subject"] = subject
    if grade:
        metadata_filters["grade"] = grade
    if view_types:
        metadata_filters["view_type"] = list(view_types)

    # LLM query expansion for short/vague queries
    from .llm_client import call_llm as _call_llm, get_default_llm_config as _get_llm_cfg
    from .retriever import extract_keywords as _extract_keywords
    llm_config = _get_llm_cfg(prefer_vision=False)
    keywords = _extract_keywords(query, llm_config=llm_config, llm_caller=_call_llm)
    expanded_query = (query + " " + " ".join(keywords)) if keywords else None

    # package_id / knowledge_point_id require DB lookups → stay as post-filter
    package_point_ids: Set[str] = set()
    if package_id is not None:
        package_point_ids = {
            str(item.knowledge_point_id)
            for item in db.query(models.KnowledgePackagePoint)
            .filter(models.KnowledgePackagePoint.package_id == package_id)
            .all()
            if _is_package_coverage_point(item)
        }

    raw_results = vector_db.db.hybrid_search_with_scores(
        query_text=query,
        n_results=max(top_k * 3, top_k),
        entity_types=KNOWLEDGE_ENTITY_TYPES,
        metadata_filters=metadata_filters or None,
        expanded_query=expanded_query,
    )

    results: List[Dict[str, Any]] = []
    expected_package_id = str(package_id) if package_id is not None else None
    expected_point_id = str(knowledge_point_id) if knowledge_point_id is not None else None

    for item in raw_results:
        metadata = dict(item.get("metadata") or {})
        entity_type = str(metadata.get("entity_type") or "")
        entity_id = _stringify(metadata.get("entity_id") or "")
        current_package_id = _stringify(metadata.get("package_id") or "")
        current_point_id = _stringify(metadata.get("knowledge_point_id") or "")

        if expected_point_id is not None and expected_point_id not in {entity_id, current_point_id}:
            continue
        if expected_package_id is not None:
            if entity_type == "knowledge_point":
                if entity_id not in package_point_ids:
                    continue
            elif current_package_id != expected_package_id and current_point_id not in package_point_ids:
                continue

        content = str(item.get("content") or "")
        results.append(
            {
                "doc_id": str(item.get("id") or ""),
                "entity_type": entity_type,
                "entity_id": int(entity_id) if entity_id.isdigit() else None,
                "score": round(float(item.get("score") or 0.0), 6),
                "reranker_score": round(float(item.get("reranker_score")), 6) if item.get("reranker_score") is not None else None,
                "vector_score": round(float(item.get("vector_score") or 0.0), 6),
                "text_score": round(float(item.get("text_score") or 0.0), 6),
                "source_type": str(item.get("source_type") or "hybrid"),
                "title": _stringify(metadata.get("title") or metadata.get("knowledge_point_name") or metadata.get("package_title") or ""),
                "snippet": _trim_snippet(content),
                "content": content,
                "metadata": metadata,
            }
        )
        if len(results) >= top_k:
            break

    return {
        "query": query,
        "keywords": keywords,
        "expanded_query": expanded_query,
        "results": results,
        "applied_filters": {
            "subject": subject,
            "grade": grade,
            "package_id": package_id,
            "knowledge_point_id": knowledge_point_id,
            "view_types": list(view_types) if view_types else [],
        },
        "backends": vector_db.db.backend_summary,
    }
