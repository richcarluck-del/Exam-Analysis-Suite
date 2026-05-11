from datetime import date, datetime
from typing import Any, Dict, ForwardRef, List, Optional

from pydantic import BaseModel, HttpUrl

APIProviderInModel = ForwardRef("APIProviderInModel")
LLMModelInProvider = ForwardRef("LLMModelInProvider")


class PromptVersionBase(BaseModel):
    version: int
    prompt_text: str


class PromptVersionCreate(PromptVersionBase):
    pass


class PromptVersion(PromptVersionBase):
    id: int
    prompt_id: int

    class Config:
        orm_mode = True


class PromptBase(BaseModel):
    name: str
    description: Optional[str] = None


class PromptCreate(PromptBase):
    pass


class Prompt(PromptBase):
    id: int
    versions: List[PromptVersion] = []

    class Config:
        orm_mode = True


class LLMModelBase(BaseModel):
    name: str


class LLMModelCreate(LLMModelBase):
    pass


class LLMModel(LLMModelBase):
    id: int
    provider: APIProviderInModel

    class Config:
        orm_mode = True


class LLMModelInProvider(LLMModelBase):
    id: int

    class Config:
        orm_mode = True


class APIProviderBase(BaseModel):
    name: str
    api_url: HttpUrl


class APIProviderCreate(APIProviderBase):
    api_key: str


class APIProvider(APIProviderBase):
    id: int
    models: List[LLMModelInProvider] = []
    display_api_key: Optional[str] = None

    class Config:
        orm_mode = True


class APIProviderInModel(APIProviderBase):
    id: int

    class Config:
        orm_mode = True


LLMModel.update_forward_refs()
APIProvider.update_forward_refs()


class UserBase(BaseModel):
    phone_number: str


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    is_active: bool

    class Config:
        orm_mode = True


class QuestionRequest(BaseModel):
    question: str
    model_id: int


class IngestRequest(BaseModel):
    model_id: Optional[int] = None


class KnowledgePointsIngestRequest(BaseModel):
    model_id: Optional[int] = None
    files: List[str]
    force_reingest: bool = False
    sync_retrieval: bool = False



class ContentSourceBase(BaseModel):
    tenant_id: Optional[int] = None
    source_name: str
    source_type: str
    provider_name: Optional[str] = None
    commercial_allowed: bool = False
    ai_processing_allowed: bool = True
    training_allowed: bool = False
    license_scope: Optional[Dict[str, Any]] = None
    remark: Optional[str] = None


class ContentSourceCreate(ContentSourceBase):
    pass


class ContentSource(ContentSourceBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


class DocumentParseJob(BaseModel):
    id: int
    source_document_id: int
    job_stage: str
    tool_name: Optional[str] = None
    model_name: Optional[str] = None
    input_version: Optional[str] = None
    output_location: Optional[str] = None
    status: str
    metrics_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class SourceDocumentBase(BaseModel):
    source_id: int
    tenant_id: Optional[int] = None
    file_name: Optional[str] = None
    file_ext: Optional[str] = None
    mime_type: Optional[str] = None
    storage_url: str
    file_sha256: Optional[str] = None
    parse_profile: str = "default"
    subject: Optional[str] = None
    grade: Optional[str] = None
    year: Optional[int] = None
    region: Optional[str] = None
    title: Optional[str] = None
    visibility_scope: str = "tenant_private"


class SourceDocumentCreate(SourceDocumentBase):
    pass


class SourceDocument(SourceDocumentBase):
    id: int
    normalized_docx_url: Optional[str] = None
    normalized_pdf_url: Optional[str] = None
    parse_status: str
    created_at: datetime
    parse_jobs: List[DocumentParseJob] = []

    class Config:
        orm_mode = True


class SourceDocumentTaskResponse(BaseModel):
    task_id: str
    source_document_id: int


class QuestionBankSearchRequest(BaseModel):
    query: str
    top_k: int = 5


class QuestionBankAsset(BaseModel):
    id: int
    asset_role: str
    storage_url: str
    public_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    page_no: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    bbox: Optional[Any] = None
    ocr_text: Optional[str] = None
    caption_text: Optional[str] = None
    file_hash: Optional[str] = None


class QuestionBankFormula(BaseModel):
    id: int
    block_id: Optional[int] = None
    source_type: str
    latex_text: Optional[str] = None
    mathml_text: Optional[str] = None
    linear_text: Optional[str] = None
    normalized_signature: Optional[str] = None
    asset_id: Optional[int] = None


class QuestionBankOption(BaseModel):
    id: int
    option_key: str
    option_text: Optional[str] = None
    formula_id: Optional[int] = None
    asset_id: Optional[int] = None
    display_order: int
    is_correct: Optional[bool] = None


class QuestionBankBlock(BaseModel):
    id: int
    block_order: int
    block_role: str
    content_format: str
    text_content: Optional[str] = None
    rich_content_json: Optional[Dict[str, Any]] = None
    formula_id: Optional[int] = None
    asset_id: Optional[int] = None
    parent_block_id: Optional[int] = None
    is_primary: bool


class QuestionBankQuestionDetail(BaseModel):
    question_item_id: int
    paper_question_id: Optional[int] = None
    paper_id: Optional[int] = None
    question_no: Optional[str] = None
    display_order: Optional[int] = None
    page_no: Optional[int] = None
    anchor_bbox: Optional[Any] = None
    subject: Optional[str] = None
    grade: Optional[str] = None
    question_type: str
    stem_plain_text: str
    answer_text: Optional[str] = None
    solution_summary: Optional[str] = None
    has_formula: bool
    has_figure: bool
    blocks: List[QuestionBankBlock] = []
    options: List[QuestionBankOption] = []
    formulas: List[QuestionBankFormula] = []
    assets: List[QuestionBankAsset] = []


class QuestionBankPaperDetail(BaseModel):
    paper_id: int
    source_document_id: int
    title: str
    subject: Optional[str] = None
    grade: Optional[str] = None
    year: Optional[int] = None
    region: Optional[str] = None
    total_questions: int
    normalized_docx_url: Optional[str] = None
    normalized_docx_public_url: Optional[str] = None
    normalized_pdf_url: Optional[str] = None
    normalized_pdf_public_url: Optional[str] = None
    questions: List[QuestionBankQuestionDetail] = []


class ExamSessionQuestionCreate(BaseModel):

    source_question_no: str
    recognized_text: Optional[str] = None
    page_no: Optional[int] = None
    parse_confidence: Optional[float] = None
    review_status: str = "pending"
    question_image_path: Optional[str] = None
    student_answer_raw: Optional[str] = None
    answer_blocks_json: Optional[Any] = None
    ocr_confidence: Optional[float] = None


class ExamSessionCreate(BaseModel):
    tenant_id: Optional[int] = None
    student_id: int
    source_document_id: Optional[int] = None
    exam_date: Optional[date] = None
    subject: Optional[str] = None
    parse_status: str = "completed"
    matching_status: str = "pending"
    analysis_status: str = "pending"
    visibility_scope: str = "private"
    bundle_dir: Optional[str] = None
    questions: List[ExamSessionQuestionCreate] = []


class ExamSessionBundleImportRequest(BaseModel):
    bundle_dir: str
    student_id: Optional[int] = None
    tenant_id: Optional[int] = None
    source_document_id: Optional[int] = None
    exam_date: Optional[date] = None
    subject: Optional[str] = None
    visibility_scope: str = "private"
    auto_match: bool = True
    match_top_k: int = 5
    match_accept_threshold: float = 0.78
    match_min_gap: float = 0.05


class ExamSessionQuestion(BaseModel):


    id: int
    exam_session_id: int
    source_question_no: str
    question_item_id: Optional[int] = None
    page_no: Optional[int] = None
    question_crop_asset_id: Optional[int] = None
    recognized_text: Optional[str] = None
    parse_confidence: Optional[float] = None
    match_confidence: Optional[float] = None
    review_status: str

    class Config:
        orm_mode = True


class StudentAttempt(BaseModel):
    id: int
    exam_session_id: int
    exam_question_id: int
    question_item_id: Optional[int] = None
    student_id: int
    student_answer_raw: Optional[str] = None
    answer_blocks_json: Optional[Any] = None
    is_correct: Optional[bool] = None
    score_earned: Optional[float] = None
    time_spent_seconds: Optional[int] = None
    teacher_mark_json: Optional[Dict[str, Any]] = None
    ocr_confidence: Optional[float] = None

    class Config:
        orm_mode = True


class ExamSessionListItem(BaseModel):
    id: int
    tenant_id: Optional[int] = None
    student_id: int
    source_document_id: Optional[int] = None
    matched_paper_id: Optional[int] = None
    exam_date: Optional[date] = None
    subject: Optional[str] = None
    parse_status: str
    matching_status: str
    analysis_status: str
    visibility_scope: str
    bundle_dir: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class ExamSessionDetail(ExamSessionListItem):
    questions: List[ExamSessionQuestion] = []
    attempts: List[StudentAttempt] = []


class ExamSessionMatchSummary(BaseModel):
    status: str
    exam_session_id: int
    matched_paper_id: Optional[int] = None
    matched_question_count: int = 0
    pending_review_count: int = 0
    question_count: int = 0
    questions: List[Dict[str, Any]] = []


class ExamSessionBundleImportResponse(BaseModel):
    bundle_id: str
    run_id: str
    question_count: int
    warnings: List[str] = []
    auto_match_requested: bool = False
    match_result: Optional[ExamSessionMatchSummary] = None
    match_error: Optional[str] = None
    exam_session: ExamSessionDetail


class QuestionMatchCandidate(BaseModel):


    match_result_id: int
    candidate_question_id: int
    match_type: str
    text_score: Optional[float] = None
    vector_score: Optional[float] = None
    overlap_score: Optional[float] = None
    formula_score: Optional[float] = None
    final_score: Optional[float] = None
    accepted: bool
    paper_id: Optional[int] = None
    similarity_reason: Optional[str] = None
    candidate_subject: Optional[str] = None
    candidate_grade: Optional[str] = None
    candidate_question_type: Optional[str] = None
    candidate_stem: Optional[str] = None
    candidate_answer: Optional[str] = None


class MatchAnchorQuestionRef(BaseModel):
    anchor_type: str
    question_item_id: int
    paper_id: Optional[int] = None
    final_score: float = 0.0
    text_score: Optional[float] = None
    vector_score: Optional[float] = None
    overlap_score: Optional[float] = None
    formula_score: Optional[float] = None
    candidate_subject: Optional[str] = None
    candidate_grade: Optional[str] = None
    candidate_question_type: Optional[str] = None
    candidate_stem: Optional[str] = None
    candidate_answer: Optional[str] = None
    similarity_reason: Optional[str] = None


class MatchAnchorKnowledgeRef(BaseModel):
    anchor_type: str = "knowledge_anchor"
    source_type: str
    source_id: str
    title: str
    snippet: str
    score: float = 0.0
    knowledge_point_id: Optional[int] = None
    metadata: Dict[str, Any] = {}


class MatchAnchorPack(BaseModel):
    primary_anchor_type: str = "unanchored"
    exact_match: Optional[MatchAnchorQuestionRef] = None
    structural_matches: List[MatchAnchorQuestionRef] = []
    knowledge_anchors: List[MatchAnchorKnowledgeRef] = []
    diagnostics: Dict[str, Any] = {}


class ExamSessionQuestionMatchView(BaseModel):
    exam_question_id: int
    source_question_no: str
    recognized_text: Optional[str] = None
    question_item_id: Optional[int] = None
    match_confidence: Optional[float] = None
    review_status: str
    student_attempt: Optional[StudentAttempt] = None
    candidates: List[QuestionMatchCandidate] = []
    match_anchors: Optional[MatchAnchorPack] = None


class ExamSessionMatchRequest(BaseModel):
    top_k: int = 5
    accept_threshold: float = 0.78
    min_gap: float = 0.05


class ExamSessionTaskResponse(BaseModel):
    task_id: str
    exam_session_id: int


class AnalysisEvidenceItem(BaseModel):
    source_type: str
    source_id: str
    title: str
    snippet: str
    score: float = 0.0
    metadata: Dict[str, Any] = {}


class AnalysisGraphNode(BaseModel):
    node_type: str
    node_id: str
    label: str
    properties: Dict[str, Any] = {}


class AnalysisGraphEdge(BaseModel):
    relation_type: str
    from_node_id: str
    to_node_id: str
    weight: Optional[float] = None
    confidence: Optional[float] = None


class AnalysisGraphPath(BaseModel):
    summary: str
    nodes: List[AnalysisGraphNode] = []
    edges: List[AnalysisGraphEdge] = []


class AnalysisKnowledgePointRef(BaseModel):
    knowledge_point_id: int
    canonical_name: str
    relation_type: Optional[str] = None
    relevance_score: Optional[float] = None
    confidence: Optional[float] = None
    mastery_status: Optional[str] = None


class AnalysisInterventionAsset(BaseModel):
    asset_type: str
    asset_id: Optional[int] = None
    title: str
    audience: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[Any] = None


class ExamQuestionAnalysis(BaseModel):
    exam_question_id: int
    exam_session_id: int
    source_question_no: str
    question_item_id: Optional[int] = None
    match_anchor_type: Optional[str] = None
    match_anchor_summary: Optional[str] = None
    match_anchors: Optional[MatchAnchorPack] = None
    analysis_mode: Optional[str] = None
    image_paths: List[str] = []
    question_summary: str
    recognized_text: Optional[str] = None
    student_answer_raw: Optional[str] = None
    correctness: str
    mastery_level: str
    confidence: float
    needs_manual_review: bool = False
    uncertainty_reason: Optional[str] = None
    visual_evidence_summary: Optional[str] = None
    text_consistency_summary: Optional[str] = None
    knowledge_points: List[AnalysisKnowledgePointRef] = []
    retrieval_evidence: List[AnalysisEvidenceItem] = []
    graph_path: Optional[AnalysisGraphPath] = None
    error_pattern: Optional[Dict[str, Any]] = None
    solution_steps: Optional[str] = None
    llm_answer: Optional[str] = None
    root_cause_hypothesis: Optional[str] = None
    study_advice: List[str] = []
    intervention_assets: List[AnalysisInterventionAsset] = []


class KnowledgeMasterySummary(BaseModel):
    knowledge_point_id: int
    canonical_name: str
    total_questions: int
    correct_questions: int
    incorrect_questions: int
    uncertain_questions: int
    accuracy: float
    weighted_score: float
    mastery_status: str
    prerequisite_of: List[int] = []
    easy_to_confuse_with: List[int] = []
    recommended_assets: List[AnalysisInterventionAsset] = []


class MistakeProfileItem(BaseModel):
    code: str
    name: str
    category: str
    count: int
    question_nos: List[str] = []
    related_knowledge_points: List[int] = []
    suggested_assets: List[AnalysisInterventionAsset] = []


class ActionPlanItem(BaseModel):
    title: str
    description: str
    priority: str = "medium"
    target_knowledge_point_ids: List[int] = []
    assets: List[AnalysisInterventionAsset] = []


class AnalysisSurfaceBase(BaseModel):
    exam_session_id: int
    audience: str
    generated_at: datetime
    summary: Dict[str, Any]
    question_analyses: List[ExamQuestionAnalysis] = []
    knowledge_profile: List[KnowledgeMasterySummary] = []
    mistake_profile: List[MistakeProfileItem] = []
    action_plan: List[ActionPlanItem] = []
    graph_overview: Dict[str, Any] = {}


class StudentReportResponse(AnalysisSurfaceBase):
    pass


class TeacherReportResponse(AnalysisSurfaceBase):
    class_breakdown: Dict[str, Any] = {}


class GovernanceReportResponse(AnalysisSurfaceBase):
    governance_metrics: Dict[str, Any] = {}


class AnalysisGenerateResponse(BaseModel):
    exam_session_id: int
    diagnosis_snapshot_id: Optional[int] = None
    surfaces: Dict[str, str] = {}
    summary: Dict[str, Any] = {}


class Neo4jSyncResponse(BaseModel):
    status: str
    synced_nodes: int = 0
    synced_relationships: int = 0
    scopes: List[str] = []
    warnings: List[str] = []
