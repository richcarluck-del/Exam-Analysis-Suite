from collections import OrderedDict
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from shared import models
from . import knowledge_point_schemas as schemas
from .knowledge_point_dedup import get_or_create_knowledge_point


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_source_document(db: Session, source_document_id: int) -> Optional[models.SourceDocument]:
    return db.query(models.SourceDocument).filter(models.SourceDocument.id == source_document_id).first()


def get_question_item(db: Session, question_item_id: int) -> Optional[models.QuestionItem]:
    return db.query(models.QuestionItem).filter(models.QuestionItem.id == question_item_id).first()


def get_knowledge_point(db: Session, knowledge_point_id: int) -> Optional[models.KnowledgePoint]:
    return db.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == knowledge_point_id).first()


def delete_knowledge_point(db: Session, knowledge_point_id: int) -> bool:
    """Delete a knowledge point: derivatives RAG, KP RAG, relations, links, atoms, package links, then KP.

    Returns True if the knowledge point existed and was deleted.
    """
    if get_knowledge_point(db, knowledge_point_id) is None:
        return False
    from .knowledge_derivative import _remove_derivative_retrieval
    from .knowledge_point_retriever import purge_knowledge_point_retrieval_documents

    drows = (
        db.query(models.KnowledgeDerivative.id)
        .filter(models.KnowledgeDerivative.knowledge_point_id == knowledge_point_id)
        .all()
    )
    for (der_id,) in drows:
        _remove_derivative_retrieval(db, der_id)
    db.query(models.KnowledgeDerivative).filter(
        models.KnowledgeDerivative.knowledge_point_id == knowledge_point_id
    ).delete(synchronize_session=False)

    purge_knowledge_point_retrieval_documents(db, knowledge_point_id)

    db.query(models.KnowledgePointRelation).filter(
        or_(
            models.KnowledgePointRelation.source_knowledge_point_id == knowledge_point_id,
            models.KnowledgePointRelation.target_knowledge_point_id == knowledge_point_id,
        )
    ).delete(synchronize_session=False)
    db.query(models.KnowledgeQuestionLink).filter(
        models.KnowledgeQuestionLink.knowledge_point_id == knowledge_point_id
    ).delete(synchronize_session=False)
    db.query(models.KnowledgeAtom).filter(
        models.KnowledgeAtom.knowledge_point_id == knowledge_point_id
    ).delete(synchronize_session=False)
    db.query(models.KnowledgePackagePoint).filter(
        models.KnowledgePackagePoint.knowledge_point_id == knowledge_point_id
    ).delete(synchronize_session=False)
    db.query(models.KnowledgeBlock).filter(
        models.KnowledgeBlock.knowledge_point_id == knowledge_point_id
    ).update({"knowledge_point_id": None}, synchronize_session=False)
    db.query(models.KnowledgePointProvenance).filter(
        models.KnowledgePointProvenance.knowledge_point_id == knowledge_point_id
    ).delete(synchronize_session=False)
    db.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == knowledge_point_id).delete(
        synchronize_session=False
    )
    db.commit()
    return True


def get_knowledge_package(db: Session, package_id: int) -> Optional[models.KnowledgePackage]:
    return db.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == package_id).first()


def create_knowledge_point(db: Session, payload: schemas.KnowledgePointCreate) -> models.KnowledgePoint:
    data = payload.dict(exclude_none=True)
    db_point = get_or_create_knowledge_point(
        db,
        canonical_name=data.pop("canonical_name"),
        subject=data.pop("subject", None),
        grade_scope=data.pop("grade_scope", None),
        source_origin=data.pop("source_origin", "human"),
        tenant_id=data.pop("tenant_id", None),
        extra_fields=data,
    )
    db.commit()
    db.refresh(db_point)
    return db_point


def _knowledge_points_filtered_query(
    db: Session,
    *,
    subject: Optional[str] = None,
    review_status: Optional[str] = None,
    taxonomy_node_id: Optional[int] = None,
    knowledge_point_id: Optional[int] = None,
):
    query = db.query(models.KnowledgePoint).order_by(models.KnowledgePoint.id.desc())
    if subject:
        query = query.filter(models.KnowledgePoint.subject == subject)
    if review_status:
        query = query.filter(models.KnowledgePoint.review_status == review_status)
    if taxonomy_node_id is not None:
        query = query.filter(models.KnowledgePoint.primary_taxonomy_node_id == taxonomy_node_id)
    if knowledge_point_id is not None:
        query = query.filter(models.KnowledgePoint.id == knowledge_point_id)
    return query


def count_knowledge_points(
    db: Session,
    subject: Optional[str] = None,
    review_status: Optional[str] = None,
    taxonomy_node_id: Optional[int] = None,
    knowledge_point_id: Optional[int] = None,
) -> int:
    return _knowledge_points_filtered_query(
        db,
        subject=subject,
        review_status=review_status,
        taxonomy_node_id=taxonomy_node_id,
        knowledge_point_id=knowledge_point_id,
    ).count()


def list_knowledge_points(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    subject: Optional[str] = None,
    review_status: Optional[str] = None,
    taxonomy_node_id: Optional[int] = None,
    knowledge_point_id: Optional[int] = None,
) -> List[models.KnowledgePoint]:
    return _knowledge_points_filtered_query(
        db,
        subject=subject,
        review_status=review_status,
        taxonomy_node_id=taxonomy_node_id,
        knowledge_point_id=knowledge_point_id,
    ).offset(skip).limit(limit).all()


def create_knowledge_package(db: Session, payload: schemas.KnowledgePackageCreate) -> models.KnowledgePackage:
    db_package = models.KnowledgePackage(**payload.dict(exclude_none=True))
    db.add(db_package)
    db.commit()
    db.refresh(db_package)
    return db_package


def list_knowledge_packages(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    subject: Optional[str] = None,
    source_document_id: Optional[int] = None,
    review_status: Optional[str] = None,
) -> List[models.KnowledgePackage]:
    query = db.query(models.KnowledgePackage).order_by(models.KnowledgePackage.id.desc())
    if subject:
        query = query.filter(models.KnowledgePackage.subject == subject)
    if source_document_id is not None:
        query = query.filter(models.KnowledgePackage.source_document_id == source_document_id)
    if review_status:
        query = query.filter(models.KnowledgePackage.review_status == review_status)
    return query.offset(skip).limit(limit).all()


def create_package_point_link(
    db: Session,
    package_id: int,
    payload: schemas.KnowledgePackagePointCreate,
) -> models.KnowledgePackagePoint:
    db_link = models.KnowledgePackagePoint(package_id=package_id, **payload.dict(exclude_none=True))
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link


def create_package_block(
    db: Session,
    package_id: int,
    payload: schemas.KnowledgeBlockCreate,
) -> models.KnowledgeBlock:
    db_block = models.KnowledgeBlock(package_id=package_id, **payload.dict(exclude_none=True))
    db.add(db_block)
    db.commit()
    db.refresh(db_block)
    return db_block


def create_knowledge_atom(
    db: Session,
    knowledge_point_id: int,
    payload: schemas.KnowledgeAtomCreate,
) -> models.KnowledgeAtom:
    db_atom = models.KnowledgeAtom(knowledge_point_id=knowledge_point_id, **payload.dict(exclude_none=True))
    db.add(db_atom)
    db.commit()
    db.refresh(db_atom)
    return db_atom


def create_knowledge_question_link(
    db: Session,
    knowledge_point_id: int,
    payload: schemas.KnowledgeQuestionLinkCreate,
) -> models.KnowledgeQuestionLink:
    db_link = models.KnowledgeQuestionLink(knowledge_point_id=knowledge_point_id, **payload.dict(exclude_none=True))
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link


def create_knowledge_point_relation(
    db: Session,
    source_knowledge_point_id: int,
    payload: schemas.KnowledgePointRelationCreate,
) -> models.KnowledgePointRelation:
    db_relation = models.KnowledgePointRelation(
        source_knowledge_point_id=source_knowledge_point_id,
        **payload.dict(exclude_none=True),
    )
    db.add(db_relation)
    db.commit()
    db.refresh(db_relation)
    return db_relation


def _serialize_knowledge_point(point: models.KnowledgePoint) -> Dict[str, Any]:
    return {
        "id": point.id,
        "tenant_id": point.tenant_id,
        "primary_taxonomy_node_id": point.primary_taxonomy_node_id,
        "subject": point.subject,
        "grade_scope": point.grade_scope,
        "canonical_name": point.canonical_name,
        "aliases_json": point.aliases_json,
        "knowledge_type": point.knowledge_type,
        "importance_level": point.importance_level,
        "difficulty_band": point.difficulty_band,
        "exam_frequency": point.exam_frequency,
        "canonical_summary": point.canonical_summary,
        "learning_objectives_json": point.learning_objectives_json,
        "prerequisite_summary": point.prerequisite_summary,
        "common_confusions_json": point.common_confusions_json,
        "source_origin": point.source_origin,
        "review_status": point.review_status,
        "version_no": point.version_no,
        "is_active": point.is_active,
        "created_at": point.created_at,
        "updated_at": point.updated_at,
    }


def _serialize_knowledge_package(package: models.KnowledgePackage) -> Dict[str, Any]:
    return {
        "id": package.id,
        "source_document_id": package.source_document_id,
        "tenant_id": package.tenant_id,
        "package_title": package.package_title,
        "package_type": package.package_type,
        "subject": package.subject,
        "grade": package.grade,
        "page_range_json": package.page_range_json,
        "outline_json": package.outline_json,
        "summary_text": package.summary_text,
        "parse_status": package.parse_status,
        "review_status": package.review_status,
        "version_no": package.version_no,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
    }


def _serialize_knowledge_block(block: models.KnowledgeBlock) -> Dict[str, Any]:
    return {
        "id": block.id,
        "package_id": block.package_id,
        "knowledge_point_id": block.knowledge_point_id,
        "parent_block_id": block.parent_block_id,
        "block_order": block.block_order,
        "section_path": block.section_path,
        "block_role": block.block_role,
        "content_format": block.content_format,
        "raw_text": block.raw_text,
        "normalized_text": block.normalized_text,
        "rich_content_json": block.rich_content_json,
        "source_page_no": block.source_page_no,
        "anchor_bbox_json": block.anchor_bbox_json,
        "source_anchor_json": block.source_anchor_json,
        "asset_id": block.asset_id,
        "source_origin": block.source_origin,
        "confidence": _to_float(block.confidence),
        "is_primary": block.is_primary,
        "created_at": block.created_at,
        "updated_at": block.updated_at,
    }


def _serialize_knowledge_atom(atom: models.KnowledgeAtom) -> Dict[str, Any]:
    return {
        "id": atom.id,
        "knowledge_point_id": atom.knowledge_point_id,
        "package_id": atom.package_id,
        "atom_type": atom.atom_type,
        "canonical_text": atom.canonical_text,
        "normalized_json": atom.normalized_json,
        "formula_signature": atom.formula_signature,
        "importance_level": atom.importance_level,
        "difficulty_band": atom.difficulty_band,
        "evidence_block_id": atom.evidence_block_id,
        "source_origin": atom.source_origin,
        "confidence": _to_float(atom.confidence),
        "review_status": atom.review_status,
        "created_at": atom.created_at,
        "updated_at": atom.updated_at,
    }


def _serialize_question_link_row(
    link: models.KnowledgeQuestionLink,
    question: models.QuestionItem,
) -> Dict[str, Any]:
    return {
        "id": link.id,
        "question_item_id": question.id,
        "question_stem": question.stem_plain_text,
        "relation_type": link.relation_type,
        "relevance_score": _to_float(link.relevance_score),
        "entry_point_text": link.entry_point_text,
        "confidence": _to_float(link.confidence),
        "approved_status": link.approved_status,
    }


def _is_package_coverage_link(link: models.KnowledgePackagePoint) -> bool:
    status = (link.approved_status or "").strip().lower()
    relation_type = (link.relation_type or "").strip().lower()
    return status != "placeholder" and relation_type not in {"placeholder", "fallback", "dependency"}


def list_knowledge_point_question_links(
    db: Session,
    knowledge_point_id: int,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    query = (
        db.query(models.KnowledgeQuestionLink, models.QuestionItem)
        .join(models.QuestionItem, models.QuestionItem.id == models.KnowledgeQuestionLink.question_item_id)
        .filter(models.KnowledgeQuestionLink.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeQuestionLink.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return [_serialize_question_link_row(link, question) for link, question in query.all()]


def list_package_related_questions(
    db: Session,
    package_id: int,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    rows = (
        db.query(models.KnowledgePackagePoint, models.KnowledgePoint, models.KnowledgeQuestionLink, models.QuestionItem)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePackagePoint.knowledge_point_id)
        .join(models.KnowledgeQuestionLink, models.KnowledgeQuestionLink.knowledge_point_id == models.KnowledgePoint.id)
        .join(models.QuestionItem, models.QuestionItem.id == models.KnowledgeQuestionLink.question_item_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .order_by(models.KnowledgeQuestionLink.id.asc())
        .all()
    )

    grouped: "OrderedDict[int, Dict[str, Any]]" = OrderedDict()
    for package_link, point, question_link, question in rows:
        if not _is_package_coverage_link(package_link):
            continue
        current = grouped.get(question.id)
        if current is None:
            current = {
                "question_item_id": question.id,
                "question_stem": question.stem_plain_text,
                "subject": question.subject,
                "grade": question.grade,
                "relation_types": [],
                "max_relevance_score": None,
                "bridge_count": 0,
                "matched_points": [],
                "strong_count": 0,
                "medium_count": 0,
                "weak_count": 0,
            }
            grouped[question.id] = current

        relation_type = question_link.relation_type or ""
        if relation_type and relation_type not in current["relation_types"]:
            current["relation_types"].append(relation_type)
        if relation_type == "topic_strong":
            current["strong_count"] += 1
        elif relation_type == "topic_fallback":
            current["weak_count"] += 1
        else:
            current["medium_count"] += 1

        relevance_score = _to_float(question_link.relevance_score)
        previous_max = current.get("max_relevance_score")
        if relevance_score is not None and (previous_max is None or relevance_score > previous_max):
            current["max_relevance_score"] = relevance_score

        mp = current["matched_points"]
        # 同一题、同一知识点若存在多条 KnowledgeQuestionLink（异常重复），只计一次
        if any(m.get("knowledge_point_id") == point.id for m in mp):
            continue
        mp.append(
            {
                "knowledge_point_id": point.id,
                "knowledge_point_name": point.canonical_name,
                "package_relation_type": package_link.relation_type,
                "question_relation_type": question_link.relation_type,
                "relevance_score": relevance_score,
                "entry_point_text": question_link.entry_point_text,
                "confidence": _to_float(question_link.confidence),
            }
        )
        current["bridge_count"] = len(mp)

    ordered = sorted(
        grouped.values(),
        key=lambda item: (
            item.get("max_relevance_score") if item.get("max_relevance_score") is not None else -1.0,
            item.get("bridge_count") or 0,
            -int(item.get("question_item_id") or 0),
        ),
        reverse=True,
    )
    if limit is not None:
        ordered = ordered[:limit]
    return ordered


def build_knowledge_point_detail(db: Session, knowledge_point: models.KnowledgePoint) -> Dict[str, Any]:
    package_link_rows = (
        db.query(models.KnowledgePackagePoint, models.KnowledgePackage)
        .join(models.KnowledgePackage, models.KnowledgePackage.id == models.KnowledgePackagePoint.package_id)
        .filter(models.KnowledgePackagePoint.knowledge_point_id == knowledge_point.id)
        .order_by(models.KnowledgePackagePoint.order_in_package.asc(), models.KnowledgePackagePoint.id.asc())
        .all()
    )
    blocks = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.knowledge_point_id == knowledge_point.id)
        .order_by(models.KnowledgeBlock.source_page_no.asc(), models.KnowledgeBlock.block_order.asc(), models.KnowledgeBlock.id.asc())
        .all()
    )
    atoms = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.knowledge_point_id == knowledge_point.id)
        .order_by(models.KnowledgeAtom.id.asc())
        .all()
    )
    question_link_rows = (
        db.query(models.KnowledgeQuestionLink, models.QuestionItem)
        .join(models.QuestionItem, models.QuestionItem.id == models.KnowledgeQuestionLink.question_item_id)
        .filter(models.KnowledgeQuestionLink.knowledge_point_id == knowledge_point.id)
        .order_by(models.KnowledgeQuestionLink.id.asc())
        .all()
    )
    relation_rows = (
        db.query(models.KnowledgePointRelation, models.KnowledgePoint)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePointRelation.target_knowledge_point_id)
        .filter(models.KnowledgePointRelation.source_knowledge_point_id == knowledge_point.id)
        .order_by(models.KnowledgePointRelation.id.asc())
        .all()
    )

    payload = _serialize_knowledge_point(knowledge_point)
    payload.update(
        {
            "package_count": len(package_link_rows),
            "block_count": len(blocks),
            "atom_count": len(atoms),
            "question_link_count": len(question_link_rows),
            "relation_count": len(relation_rows),
            "package_links": [
                {
                    "id": link.id,
                    "package_id": package.id,
                    "package_title": package.package_title,
                    "knowledge_point_id": link.knowledge_point_id,
                    "knowledge_point_name": knowledge_point.canonical_name,
                    "relation_type": link.relation_type,
                    "weight_score": _to_float(link.weight_score),
                    "order_in_package": link.order_in_package,
                    "confidence": _to_float(link.confidence),
                    "approved_status": link.approved_status,
                }
                for link, package in package_link_rows
            ],
            "blocks": [_serialize_knowledge_block(block) for block in blocks],
            "atoms": [_serialize_knowledge_atom(atom) for atom in atoms],
            "question_links": [_serialize_question_link_row(link, question) for link, question in question_link_rows],
            "outgoing_relations": [
                {
                    "id": relation.id,
                    "target_knowledge_point_id": target_point.id,
                    "target_knowledge_point_name": target_point.canonical_name,
                    "relation_type": relation.relation_type,
                    "strength_score": _to_float(relation.strength_score),
                    "confidence": _to_float(relation.confidence),
                    "approved_status": relation.approved_status,
                }
                for relation, target_point in relation_rows
            ],
        }
    )
    return payload


def build_knowledge_package_detail(db: Session, package: models.KnowledgePackage) -> Dict[str, Any]:
    point_link_rows = (
        db.query(models.KnowledgePackagePoint, models.KnowledgePoint)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package.id)
        .order_by(models.KnowledgePackagePoint.order_in_package.asc(), models.KnowledgePackagePoint.id.asc())
        .all()
    )
    blocks = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.package_id == package.id)
        .order_by(models.KnowledgeBlock.source_page_no.asc(), models.KnowledgeBlock.block_order.asc(), models.KnowledgeBlock.id.asc())
        .all()
    )
    related_questions = list_package_related_questions(db, package.id)
    material_question_ids = [
        int(row[0])
        for row in db.query(models.KnowledgePackageQuestion.question_item_id)
        .filter(models.KnowledgePackageQuestion.package_id == package.id)
        .order_by(models.KnowledgePackageQuestion.display_order.asc(), models.KnowledgePackageQuestion.id.asc())
        .all()
    ]
    bridged_question_ids = {int(item.get("question_item_id")) for item in related_questions if item.get("question_item_id") is not None}
    material_question_count = len(material_question_ids)
    bridged_question_count = sum(1 for qid in material_question_ids if qid in bridged_question_ids)
    orphan_ids = [qid for qid in material_question_ids if qid not in bridged_question_ids]
    orphan_in_material_count = len(orphan_ids)
    extra_bridged_ids = [qid for qid in bridged_question_ids if qid not in set(material_question_ids)]
    extra_bridged_count = len(extra_bridged_ids)
    payload = _serialize_knowledge_package(package)
    payload.update(
        {
            "point_count": len(point_link_rows),
            "block_count": len(blocks),
            "related_question_count": len(related_questions),
            "material_question_count": material_question_count,
            "bridged_question_count": bridged_question_count,
            "orphan_in_material_count": orphan_in_material_count,
            "extra_bridged_count": extra_bridged_count,
            "bridge_coverage_ratio": (
                round(bridged_question_count / material_question_count, 4)
                if material_question_count
                else None
            ),
            "material_question_ids": material_question_ids,
            "orphan_question_ids": orphan_ids,
            "extra_bridged_question_ids": extra_bridged_ids,
            "point_links": [
                {
                    "id": link.id,
                    "package_id": link.package_id,
                    "package_title": package.package_title,
                    "knowledge_point_id": point.id,
                    "knowledge_point_name": point.canonical_name,
                    "relation_type": link.relation_type,
                    "weight_score": _to_float(link.weight_score),
                    "order_in_package": link.order_in_package,
                    "confidence": _to_float(link.confidence),
                    "approved_status": link.approved_status,
                }
                for link, point in point_link_rows
            ],
            "blocks": [_serialize_knowledge_block(block) for block in blocks],
            "related_questions": related_questions,
        }
    )
    return payload


def backfill_package_question_bridge(db: Session, package_id: int) -> Dict[str, Any]:
    """
    为历史包补齐 KnowledgeQuestionLink：
    - 目标：每道 KnowledgePackageQuestion 题目在本包内（KnowledgePackagePoint 集合）至少有一条桥接链。
    - 策略：若已有有效链则跳过；否则挂一条 topic_fallback + 低 confidence 链到「代表考点」。
    - 代表考点：优先 relation_type=core 中 order_in_package 最小者，其次所有包点中 order 最小者。
    """
    package = get_knowledge_package(db, package_id)
    if package is None:
        raise ValueError(f"Knowledge package {package_id} not found")

    allowed_point_rows = (
        db.query(models.KnowledgePackagePoint)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .order_by(models.KnowledgePackagePoint.order_in_package.asc(), models.KnowledgePackagePoint.id.asc())
        .all()
    )
    allowed_point_rows = [row for row in allowed_point_rows if _is_package_coverage_link(row)]
    allowed_point_ids = {int(row.knowledge_point_id) for row in allowed_point_rows if row.knowledge_point_id is not None}

    representative_id: Optional[int] = None
    for row in allowed_point_rows:
        if row.relation_type == "core" and row.knowledge_point_id is not None:
            representative_id = int(row.knowledge_point_id)
            break
    if representative_id is None and allowed_point_rows:
        for row in allowed_point_rows:
            if row.knowledge_point_id is not None:
                representative_id = int(row.knowledge_point_id)
                break

    material_ids = [
        int(r[0])
        for r in db.query(models.KnowledgePackageQuestion.question_item_id)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .all()
    ]

    if not material_ids:
        return {
            "package_id": package_id,
            "material_question_count": 0,
            "bridged_question_count": 0,
            "new_links": 0,
            "fallback_links": 0,
            "allowed_point_count": len(allowed_point_ids),
            "representative_point_id": representative_id,
            "note": "本包无材料题，无需补链。",
        }

    existing_rows = (
        db.query(models.KnowledgeQuestionLink.question_item_id, models.KnowledgeQuestionLink.knowledge_point_id)
        .filter(models.KnowledgeQuestionLink.question_item_id.in_(material_ids))
        .all()
    )
    bridged_ids: set[int] = set()
    for qid, pid in existing_rows:
        if pid is None or qid is None:
            continue
        if int(pid) in allowed_point_ids:
            bridged_ids.add(int(qid))

    new_links = 0
    fallback_links = 0
    if representative_id is None:
        return {
            "package_id": package_id,
            "material_question_count": len(material_ids),
            "bridged_question_count": len(bridged_ids),
            "new_links": 0,
            "fallback_links": 0,
            "allowed_point_count": 0,
            "representative_point_id": None,
            "note": "本包尚无 KnowledgePackagePoint，无法补链。请先完成知识点摄入。",
        }

    for qid in material_ids:
        if qid in bridged_ids:
            continue
        exists = (
            db.query(models.KnowledgeQuestionLink.id)
            .filter(
                models.KnowledgeQuestionLink.knowledge_point_id == representative_id,
                models.KnowledgeQuestionLink.question_item_id == qid,
            )
            .first()
        )
        if exists:
            bridged_ids.add(qid)
            continue
        db.add(
            models.KnowledgeQuestionLink(
                knowledge_point_id=representative_id,
                question_item_id=qid,
                relation_type="topic_fallback",
                relevance_score=0.3,
                entry_point_text=None,
                source_origin="backfill",
                confidence=0.4,
                approved_status="pending",
            )
        )
        bridged_ids.add(qid)
        new_links += 1
        fallback_links += 1

    if new_links:
        db.commit()

    return {
        "package_id": package_id,
        "material_question_count": len(material_ids),
        "bridged_question_count": len(bridged_ids),
        "new_links": new_links,
        "fallback_links": fallback_links,
        "allowed_point_count": len(allowed_point_ids),
        "representative_point_id": representative_id,
    }
