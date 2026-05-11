from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class KnowledgePointBase(BaseModel):
    tenant_id: Optional[int] = None
    primary_taxonomy_node_id: Optional[int] = None
    subject: Optional[str] = None
    grade_scope: Optional[str] = None
    canonical_name: str
    aliases_json: Optional[List[str]] = None
    knowledge_type: str = "concept"
    importance_level: Optional[int] = None
    difficulty_band: Optional[str] = None
    exam_frequency: Optional[int] = None
    canonical_summary: Optional[str] = None
    learning_objectives_json: Optional[Any] = None
    prerequisite_summary: Optional[str] = None
    common_confusions_json: Optional[Any] = None
    source_origin: str = "human"
    review_status: str = "draft"
    version_no: int = 1
    is_active: bool = True


class KnowledgePointCreate(KnowledgePointBase):
    pass


class KnowledgePoint(KnowledgePointBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class KnowledgePackageBase(BaseModel):
    source_document_id: int
    tenant_id: Optional[int] = None
    package_title: str
    package_type: str = "topic"
    subject: Optional[str] = None
    grade: Optional[str] = None
    page_range_json: Optional[Any] = None
    outline_json: Optional[Any] = None
    summary_text: Optional[str] = None
    parse_status: str = "pending"
    review_status: str = "draft"
    version_no: int = 1


class KnowledgePackageCreate(KnowledgePackageBase):
    pass


class KnowledgePackage(KnowledgePackageBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class KnowledgePackagePointBase(BaseModel):
    knowledge_point_id: int
    relation_type: str = "core"
    weight_score: Optional[float] = None
    order_in_package: Optional[int] = None
    source_origin: str = "human"
    confidence: Optional[float] = None
    approved_status: str = "approved"


class KnowledgePackagePointCreate(KnowledgePackagePointBase):
    pass


class KnowledgePackagePoint(KnowledgePackagePointBase):
    id: int
    package_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class KnowledgeBlockBase(BaseModel):
    knowledge_point_id: Optional[int] = None
    parent_block_id: Optional[int] = None
    block_order: int
    section_path: Optional[str] = None
    block_role: str
    content_format: str
    raw_text: Optional[str] = None
    normalized_text: Optional[str] = None
    rich_content_json: Optional[Any] = None
    source_page_no: Optional[int] = None
    anchor_bbox_json: Optional[Any] = None
    source_anchor_json: Optional[Any] = None
    asset_id: Optional[int] = None
    source_origin: str = "human"
    confidence: Optional[float] = None
    is_primary: bool = False


class KnowledgeBlockCreate(KnowledgeBlockBase):
    pass


class KnowledgeBlock(KnowledgeBlockBase):
    id: int
    package_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class KnowledgeAtomBase(BaseModel):
    package_id: Optional[int] = None
    atom_type: str
    canonical_text: str
    normalized_json: Optional[Any] = None
    formula_signature: Optional[str] = None
    importance_level: Optional[int] = None
    difficulty_band: Optional[str] = None
    evidence_block_id: Optional[int] = None
    source_origin: str = "human"
    confidence: Optional[float] = None
    review_status: str = "draft"


class KnowledgeAtomCreate(KnowledgeAtomBase):
    pass


class KnowledgeAtom(KnowledgeAtomBase):
    id: int
    knowledge_point_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class KnowledgeQuestionLinkBase(BaseModel):
    question_item_id: int
    relation_type: str
    relevance_score: Optional[float] = None
    entry_point_text: Optional[str] = None
    explanation_block_id: Optional[int] = None
    commentary_block_id: Optional[int] = None
    source_origin: str = "human"
    confidence: Optional[float] = None
    approved_status: str = "approved"


class KnowledgeQuestionLinkCreate(KnowledgeQuestionLinkBase):
    pass


class KnowledgeQuestionLinkApprovalUpdate(BaseModel):
    """审核态更新：approved / rejected / pending。可选给出新档位 relation_type。"""
    approved_status: str
    relation_type: Optional[str] = None
    resync_retrieval: bool = True


class KnowledgeQuestionLink(KnowledgeQuestionLinkBase):
    id: int
    knowledge_point_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class KnowledgePointRelationBase(BaseModel):
    target_knowledge_point_id: int
    relation_type: str
    strength_score: Optional[float] = None
    evidence_block_id: Optional[int] = None
    source_origin: str = "human"
    confidence: Optional[float] = None
    approved_status: str = "approved"


class KnowledgePointRelationCreate(KnowledgePointRelationBase):
    pass


class KnowledgePointRelation(KnowledgePointRelationBase):
    id: int
    source_knowledge_point_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class KnowledgePackagePointLinkView(BaseModel):
    id: int
    package_id: int
    package_title: str
    knowledge_point_id: int
    knowledge_point_name: str
    relation_type: str
    weight_score: Optional[float] = None
    order_in_package: Optional[int] = None
    confidence: Optional[float] = None
    approved_status: str


class KnowledgeQuestionLinkView(BaseModel):
    id: int
    question_item_id: int
    question_stem: Optional[str] = None
    relation_type: str
    relevance_score: Optional[float] = None
    entry_point_text: Optional[str] = None
    confidence: Optional[float] = None
    approved_status: str


class KnowledgePointRelationView(BaseModel):
    id: int
    target_knowledge_point_id: int
    target_knowledge_point_name: Optional[str] = None
    relation_type: str
    strength_score: Optional[float] = None
    confidence: Optional[float] = None
    approved_status: str


class KnowledgePackageRelatedQuestionPointView(BaseModel):
    knowledge_point_id: int
    knowledge_point_name: str
    package_relation_type: Optional[str] = None
    question_relation_type: str
    relevance_score: Optional[float] = None
    entry_point_text: Optional[str] = None
    confidence: Optional[float] = None


class KnowledgePackageRelatedQuestionView(BaseModel):
    question_item_id: int
    question_stem: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[str] = None
    relation_types: List[str] = Field(default_factory=list)
    max_relevance_score: Optional[float] = None
    bridge_count: int = 0
    strong_count: int = 0
    medium_count: int = 0
    weak_count: int = 0
    matched_points: List[KnowledgePackageRelatedQuestionPointView] = Field(default_factory=list)


class KnowledgePointDetail(KnowledgePoint):
    package_count: int = 0
    block_count: int = 0
    atom_count: int = 0
    question_link_count: int = 0
    relation_count: int = 0
    package_links: List[KnowledgePackagePointLinkView] = Field(default_factory=list)
    blocks: List[KnowledgeBlock] = Field(default_factory=list)
    atoms: List[KnowledgeAtom] = Field(default_factory=list)
    question_links: List[KnowledgeQuestionLinkView] = Field(default_factory=list)
    outgoing_relations: List[KnowledgePointRelationView] = Field(default_factory=list)


class KnowledgePackageDetail(KnowledgePackage):
    point_count: int = 0
    block_count: int = 0
    related_question_count: int = 0
    material_question_count: int = 0
    bridged_question_count: int = 0
    orphan_in_material_count: int = 0
    extra_bridged_count: int = 0
    bridge_coverage_ratio: Optional[float] = None
    material_question_ids: List[int] = Field(default_factory=list)
    orphan_question_ids: List[int] = Field(default_factory=list)
    extra_bridged_question_ids: List[int] = Field(default_factory=list)
    point_links: List[KnowledgePackagePointLinkView] = Field(default_factory=list)
    blocks: List[KnowledgeBlock] = Field(default_factory=list)
    related_questions: List[KnowledgePackageRelatedQuestionView] = Field(default_factory=list)


class KnowledgeRetrievalSyncResponse(BaseModel):
    indexed_documents: int
    target_type: str
    target_id: int
    vector_backend: Optional[str] = None
    text_backend: Optional[str] = None
    embedding_model: Optional[str] = None
    vector_dim: Optional[int] = None


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    subject: Optional[str] = None
    grade: Optional[str] = None
    package_id: Optional[int] = None
    knowledge_point_id: Optional[int] = None
    view_types: Optional[List[str]] = None


class KnowledgeSearchResultItem(BaseModel):
    doc_id: str
    entity_type: str
    entity_id: Optional[int] = None
    score: float
    reranker_score: Optional[float] = None
    vector_score: float = 0.0
    text_score: float = 0.0
    source_type: str
    title: Optional[str] = None
    snippet: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    query: str
    keywords: List[str] = Field(default_factory=list)
    expanded_query: Optional[str] = None
    results: List[KnowledgeSearchResultItem] = Field(default_factory=list)
    applied_filters: Dict[str, Any] = Field(default_factory=dict)
    backends: Dict[str, Optional[str]] = Field(default_factory=dict)
