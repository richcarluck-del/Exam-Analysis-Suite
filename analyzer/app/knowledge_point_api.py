from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy.orm import Session

from shared.database import get_db
from . import knowledge_point_schemas as schemas
from .config import KNOWLEDGE_RAG_ENABLED
from .knowledge_point_retriever import (
    search_knowledge_documents,
    sync_knowledge_package_retrieval,
    sync_knowledge_point_retrieval,
)
from .knowledge_point_service import (
    backfill_package_question_bridge,
    build_knowledge_package_detail,
    build_knowledge_point_detail,
    create_knowledge_atom,
    create_knowledge_package,
    create_knowledge_point,
    create_knowledge_point_relation,
    delete_knowledge_point,
    create_knowledge_question_link,
    create_package_block,
    create_package_point_link,
    get_knowledge_package,
    get_knowledge_point,
    get_question_item,
    get_source_document,
    list_knowledge_packages,
    list_knowledge_point_question_links,
    list_knowledge_points,
    list_package_related_questions,
    count_knowledge_points,
)


KNOWLEDGE_POINT_TAGS = ["knowledge-points"]


def register_knowledge_point_routes(app: FastAPI) -> None:
    @app.post("/api/knowledge-points/points", response_model=schemas.KnowledgePoint, status_code=201, tags=KNOWLEDGE_POINT_TAGS)
    def create_point(payload: schemas.KnowledgePointCreate, db: Session = Depends(get_db)):
        return create_knowledge_point(db, payload)

    @app.get("/api/knowledge-points/points", response_model=List[schemas.KnowledgePoint], tags=KNOWLEDGE_POINT_TAGS)
    def list_points(
        response: Response,
        skip: int = 0,
        limit: int = Query(100, ge=1, le=200),
        subject: Optional[str] = None,
        review_status: Optional[str] = None,
        taxonomy_node_id: Optional[int] = None,
        knowledge_point_id: Optional[int] = Query(
            None,
            description="按知识点主键过滤；可与其他条件组合，用于在列表中定位单条。",
        ),
        db: Session = Depends(get_db),
    ):
        total = count_knowledge_points(
            db,
            subject=subject,
            review_status=review_status,
            taxonomy_node_id=taxonomy_node_id,
            knowledge_point_id=knowledge_point_id,
        )
        response.headers["X-Total-Count"] = str(total)
        return list_knowledge_points(
            db,
            skip=skip,
            limit=limit,
            subject=subject,
            review_status=review_status,
            taxonomy_node_id=taxonomy_node_id,
            knowledge_point_id=knowledge_point_id,
        )

    @app.get("/api/knowledge-points/points/{knowledge_point_id}", response_model=schemas.KnowledgePointDetail, tags=KNOWLEDGE_POINT_TAGS)
    def get_point_detail(knowledge_point_id: int, db: Session = Depends(get_db)):
        point = get_knowledge_point(db, knowledge_point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        return build_knowledge_point_detail(db, point)

    @app.delete("/api/knowledge-points/points/{knowledge_point_id}", status_code=204, tags=KNOWLEDGE_POINT_TAGS)
    def delete_point(knowledge_point_id: int, db: Session = Depends(get_db)) -> None:
        if not delete_knowledge_point(db, knowledge_point_id):
            raise HTTPException(status_code=404, detail="Knowledge point not found")

    @app.get(
        "/api/knowledge-points/points/{knowledge_point_id}/question-links",
        response_model=List[schemas.KnowledgeQuestionLinkView],
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def get_point_question_links(
        knowledge_point_id: int,
        limit: int = Query(100, ge=1, le=200),
        db: Session = Depends(get_db),
    ):
        point = get_knowledge_point(db, knowledge_point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        return list_knowledge_point_question_links(db, knowledge_point_id, limit=limit)

    @app.post("/api/knowledge-points/packages", response_model=schemas.KnowledgePackage, status_code=201, tags=KNOWLEDGE_POINT_TAGS)
    def create_package(payload: schemas.KnowledgePackageCreate, db: Session = Depends(get_db)):
        source_document = get_source_document(db, payload.source_document_id)
        if not source_document:
            raise HTTPException(status_code=404, detail="Linked source document not found")
        return create_knowledge_package(db, payload)

    @app.get("/api/knowledge-points/packages", response_model=List[schemas.KnowledgePackage], tags=KNOWLEDGE_POINT_TAGS)
    def list_packages(
        skip: int = 0,
        limit: int = Query(100, ge=1, le=200),
        subject: Optional[str] = None,
        source_document_id: Optional[int] = None,
        review_status: Optional[str] = None,
        db: Session = Depends(get_db),
    ):
        return list_knowledge_packages(
            db,
            skip=skip,
            limit=limit,
            subject=subject,
            source_document_id=source_document_id,
            review_status=review_status,
        )

    @app.get("/api/knowledge-points/packages/{package_id}", response_model=schemas.KnowledgePackageDetail, tags=KNOWLEDGE_POINT_TAGS)
    def get_package_detail(package_id: int, db: Session = Depends(get_db)):
        package = get_knowledge_package(db, package_id)
        if not package:
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        return build_knowledge_package_detail(db, package)

    @app.get(
        "/api/knowledge-points/packages/{package_id}/related-questions",
        response_model=List[schemas.KnowledgePackageRelatedQuestionView],
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def get_package_related_questions(
        package_id: int,
        limit: int = Query(100, ge=1, le=200),
        db: Session = Depends(get_db),
    ):
        package = get_knowledge_package(db, package_id)
        if not package:
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        return list_package_related_questions(db, package_id, limit=limit)

    @app.post(
        "/api/knowledge-points/packages/{package_id}/points",
        response_model=schemas.KnowledgePackagePoint,
        status_code=201,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def create_package_point(package_id: int, payload: schemas.KnowledgePackagePointCreate, db: Session = Depends(get_db)):
        package = get_knowledge_package(db, package_id)
        if not package:
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        point = get_knowledge_point(db, payload.knowledge_point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        return create_package_point_link(db, package_id, payload)

    @app.post(
        "/api/knowledge-points/packages/{package_id}/blocks",
        response_model=schemas.KnowledgeBlock,
        status_code=201,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def create_block(package_id: int, payload: schemas.KnowledgeBlockCreate, db: Session = Depends(get_db)):
        package = get_knowledge_package(db, package_id)
        if not package:
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        if payload.knowledge_point_id is not None and not get_knowledge_point(db, payload.knowledge_point_id):
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        return create_package_block(db, package_id, payload)

    @app.post(
        "/api/knowledge-points/points/{knowledge_point_id}/atoms",
        response_model=schemas.KnowledgeAtom,
        status_code=201,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def create_atom(knowledge_point_id: int, payload: schemas.KnowledgeAtomCreate, db: Session = Depends(get_db)):
        point = get_knowledge_point(db, knowledge_point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        if payload.package_id is not None and not get_knowledge_package(db, payload.package_id):
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        return create_knowledge_atom(db, knowledge_point_id, payload)

    @app.post(
        "/api/knowledge-points/points/{knowledge_point_id}/question-links",
        response_model=schemas.KnowledgeQuestionLink,
        status_code=201,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def create_question_link(knowledge_point_id: int, payload: schemas.KnowledgeQuestionLinkCreate, db: Session = Depends(get_db)):
        point = get_knowledge_point(db, knowledge_point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        question = get_question_item(db, payload.question_item_id)
        if not question:
            raise HTTPException(status_code=404, detail="Question item not found")
        return create_knowledge_question_link(db, knowledge_point_id, payload)

    @app.post(
        "/api/knowledge-points/points/{knowledge_point_id}/relations",
        response_model=schemas.KnowledgePointRelation,
        status_code=201,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def create_relation(knowledge_point_id: int, payload: schemas.KnowledgePointRelationCreate, db: Session = Depends(get_db)):
        point = get_knowledge_point(db, knowledge_point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        target_point = get_knowledge_point(db, payload.target_knowledge_point_id)
        if not target_point:
            raise HTTPException(status_code=404, detail="Target knowledge point not found")
        return create_knowledge_point_relation(db, knowledge_point_id, payload)

    @app.post(
        "/api/knowledge-points/points/{knowledge_point_id}/search-index",
        response_model=schemas.KnowledgeRetrievalSyncResponse,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def sync_point_search_index(knowledge_point_id: int, db: Session = Depends(get_db)):
        if not KNOWLEDGE_RAG_ENABLED:
            raise HTTPException(status_code=503, detail="Knowledge RAG is disabled")
        point = get_knowledge_point(db, knowledge_point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        try:
            return sync_knowledge_point_retrieval(db, knowledge_point_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to sync knowledge point search index: {exc}") from exc

    @app.post(
        "/api/knowledge-points/packages/{package_id}/search-index",
        response_model=schemas.KnowledgeRetrievalSyncResponse,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def sync_package_search_index(package_id: int, db: Session = Depends(get_db)):
        if not KNOWLEDGE_RAG_ENABLED:
            raise HTTPException(status_code=503, detail="Knowledge RAG is disabled")
        package = get_knowledge_package(db, package_id)
        if not package:
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        try:
            return sync_knowledge_package_retrieval(db, package_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to sync knowledge package search index: {exc}") from exc

    @app.post(
        "/api/knowledge-points/packages/{package_id}/backfill-question-bridge",
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def backfill_package_bridge(package_id: int, db: Session = Depends(get_db)):
        package = get_knowledge_package(db, package_id)
        if not package:
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        try:
            return backfill_package_question_bridge(db, package_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to backfill question bridge: {exc}") from exc

    @app.post(
        "/api/knowledge-points/question-links/{link_id}/approval",
        response_model=schemas.KnowledgeQuestionLink,
        tags=KNOWLEDGE_POINT_TAGS,
    )
    def update_question_link_approval(
        link_id: int,
        payload: schemas.KnowledgeQuestionLinkApprovalUpdate,
        db: Session = Depends(get_db),
    ):
        from shared import models as shared_models

        allowed = {"approved", "rejected", "pending"}
        new_status = (payload.approved_status or "").strip().lower()
        if new_status not in allowed:
            raise HTTPException(status_code=400, detail=f"approved_status must be one of {sorted(allowed)}")
        link = db.query(shared_models.KnowledgeQuestionLink).filter(shared_models.KnowledgeQuestionLink.id == link_id).first()
        if not link:
            raise HTTPException(status_code=404, detail="Knowledge question link not found")
        link.approved_status = new_status
        if payload.relation_type:
            link.relation_type = payload.relation_type.strip()
        db.commit()
        db.refresh(link)
        # 审核流与检索同步对齐：状态变更后重新投影该知识点的检索文档，使强中档/审核结果立刻反映到检索。
        if payload.resync_retrieval and KNOWLEDGE_RAG_ENABLED:
            try:
                sync_knowledge_point_retrieval(db, link.knowledge_point_id)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=500,
                    detail=f"approval saved, but retrieval sync failed: {exc}",
                ) from exc
        return link

    @app.post("/api/knowledge-points/search", response_model=schemas.KnowledgeSearchResponse, tags=KNOWLEDGE_POINT_TAGS)
    def search_knowledge(payload: schemas.KnowledgeSearchRequest, db: Session = Depends(get_db)):
        if not KNOWLEDGE_RAG_ENABLED:
            raise HTTPException(status_code=503, detail="Knowledge RAG is disabled")
        if payload.package_id is not None and not get_knowledge_package(db, payload.package_id):
            raise HTTPException(status_code=404, detail="Knowledge package not found")
        if payload.knowledge_point_id is not None and not get_knowledge_point(db, payload.knowledge_point_id):
            raise HTTPException(status_code=404, detail="Knowledge point not found")
        try:
            return search_knowledge_documents(
                db,
                query=payload.query,
                top_k=payload.top_k,
                subject=payload.subject,
                grade=payload.grade,
                package_id=payload.package_id,
                knowledge_point_id=payload.knowledge_point_id,
                view_types=payload.view_types,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Knowledge search failed: {exc}") from exc
