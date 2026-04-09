from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from shared.database import Base


class TimestampMixin:
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class APIProvider(Base, TimestampMixin):
    __tablename__ = "api_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    api_url = Column(String, nullable=False)
    encrypted_api_key = Column(String, nullable=False)

    models = relationship("LLMModel", back_populates="provider")


class LLMModel(Base, TimestampMixin):
    __tablename__ = "llm_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    provider_id = Column(Integer, ForeignKey("api_providers.id"), nullable=False)

    provider = relationship("APIProvider", back_populates="models")


class LLMStepConfig(Base, TimestampMixin):
    __tablename__ = "llm_step_configs"

    id = Column(Integer, primary_key=True, index=True)
    step_key = Column(String(100), unique=True, index=True, nullable=False)
    step_label = Column(String(255), nullable=False)
    module_name = Column(String(64), nullable=False)
    step_order = Column(String(32))
    description = Column(Text)
    provider_id = Column(Integer, ForeignKey("api_providers.id"), nullable=True)
    model_id = Column(Integer, ForeignKey("llm_models.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    provider = relationship("APIProvider", foreign_keys=[provider_id])
    model = relationship("LLMModel", foreign_keys=[model_id])


class PromptStepConfig(Base, TimestampMixin):
    __tablename__ = "prompt_step_configs"

    id = Column(Integer, primary_key=True, index=True)
    step_key = Column(String(100), unique=True, index=True, nullable=False)
    step_label = Column(String(255), nullable=False)
    module_name = Column(String(64), nullable=False)
    step_order = Column(String(32))
    description = Column(Text)
    prompt_key = Column(String(255), nullable=False)
    selected_version = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class Prompt(Base):


    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String(200))
    description = Column(Text)
    pipeline_step = Column(Integer)
    category = Column(String(50))
    target_type = Column(String(50))
    scenario = Column(String(100))
    version = Column(Integer, default=1)
    is_latest = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(100))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    versions = relationship(
        "PromptVersion",
        back_populates="prompt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    status = Column(String(20), default="published")
    created_by = Column(String(100))
    created_at = Column(DateTime, default=func.now())
    change_log = Column(Text)

    prompt = relationship("Prompt", back_populates="versions")


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    tenant_name = Column(String(255), nullable=False, unique=True, index=True)
    tenant_type = Column(String(32), nullable=False)
    status = Column(String(16), default="active", nullable=False)

    content_sources = relationship("ContentSource", back_populates="tenant")
    source_documents = relationship("SourceDocument", back_populates="tenant")
    exam_sessions = relationship("ExamSession", back_populates="tenant")


class ContentSource(Base, TimestampMixin):
    __tablename__ = "content_sources"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    source_name = Column(String(255), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    provider_name = Column(String(255))
    commercial_allowed = Column(Boolean, default=False, nullable=False)
    ai_processing_allowed = Column(Boolean, default=True, nullable=False)
    training_allowed = Column(Boolean, default=False, nullable=False)
    license_scope = Column(JSON)
    expires_at = Column(DateTime)
    remark = Column(Text)

    tenant = relationship("Tenant", back_populates="content_sources")
    documents = relationship("SourceDocument", back_populates="content_source")


class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("content_sources.id"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_ext = Column(String(16), nullable=False, index=True)
    mime_type = Column(String(128))
    storage_url = Column(Text, nullable=False)
    file_sha256 = Column(String(64), index=True)
    normalized_docx_url = Column(Text)
    normalized_pdf_url = Column(Text)
    parse_profile = Column(String(64), default="default")
    subject = Column(String(32), index=True)
    grade = Column(String(32))
    year = Column(Integer, index=True)
    region = Column(String(64), index=True)
    title = Column(String(255))
    visibility_scope = Column(String(32), default="tenant_private", nullable=False)
    parse_status = Column(String(32), default="pending", nullable=False, index=True)

    content_source = relationship("ContentSource", back_populates="documents")
    tenant = relationship("Tenant", back_populates="source_documents")
    parse_jobs = relationship(
        "DocumentParseJob",
        back_populates="source_document",
        cascade="all, delete-orphan",
        order_by="DocumentParseJob.id",
    )
    papers = relationship("Paper", back_populates="source_document")
    exam_sessions = relationship("ExamSession", back_populates="source_document")


class DocumentParseJob(Base):
    __tablename__ = "document_parse_jobs"

    id = Column(Integer, primary_key=True, index=True)
    source_document_id = Column(Integer, ForeignKey("source_documents.id"), nullable=False, index=True)
    job_stage = Column(String(32), nullable=False, index=True)
    tool_name = Column(String(128))
    model_name = Column(String(128))
    input_version = Column(String(32))
    output_location = Column(Text)
    status = Column(String(16), default="pending", nullable=False, index=True)
    metrics_json = Column(JSON)
    error_message = Column(Text)
    started_at = Column(DateTime, default=func.now())
    ended_at = Column(DateTime)

    source_document = relationship("SourceDocument", back_populates="parse_jobs")


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    owner_type = Column(String(32), nullable=False, index=True)
    owner_id = Column(Integer, nullable=False, index=True)
    asset_role = Column(String(32), nullable=False, index=True)
    storage_url = Column(Text, nullable=False)
    thumbnail_url = Column(Text)
    page_no = Column(Integer)
    width = Column(Integer)
    height = Column(Integer)
    bbox = Column(JSON)
    ocr_text = Column(Text)
    caption_text = Column(Text)
    file_hash = Column(String(64), index=True)
    phash = Column(String(64), index=True)


class Paper(Base, TimestampMixin):
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    source_document_id = Column(Integer, ForeignKey("source_documents.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    subject = Column(String(32), index=True)
    grade = Column(String(32))
    year = Column(Integer, index=True)
    region = Column(String(64), index=True)
    stream_type = Column(String(32))
    exam_type = Column(String(32), default="unknown", nullable=False)
    source_type = Column(String(32), default="unknown", nullable=False)
    total_questions = Column(Integer, default=0, nullable=False)
    raw_outline_json = Column(JSON)
    is_canonical = Column(Boolean, default=False, nullable=False)
    review_status = Column(String(16), default="draft", nullable=False)

    source_document = relationship("SourceDocument", back_populates="papers")
    sections = relationship("PaperSection", back_populates="paper", cascade="all, delete-orphan")
    questions = relationship("PaperQuestion", back_populates="paper", cascade="all, delete-orphan")


class PaperSection(Base):
    __tablename__ = "paper_sections"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    section_order = Column(Integer, nullable=False)
    section_name = Column(String(128), nullable=False)
    section_type = Column(String(32), nullable=False)
    start_question_no = Column(String(32))
    end_question_no = Column(String(32))

    paper = relationship("Paper", back_populates="sections")


class QuestionFamily(Base, TimestampMixin):
    __tablename__ = "question_families"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(32), index=True)
    family_name = Column(String(255), nullable=False)
    core_pattern = Column(Text)
    core_strategy_id = Column(Integer, ForeignKey("strategy_cards.id"), nullable=True)
    core_intent_summary = Column(Text)
    gaokao_frequency = Column(Integer, default=0, nullable=False)
    region_stats_json = Column(JSON)
    year_stats_json = Column(JSON)

    questions = relationship("QuestionItem", back_populates="family")


class QuestionItem(Base, TimestampMixin):
    __tablename__ = "question_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    subject = Column(String(32), index=True)
    grade = Column(String(32))
    question_type = Column(String(32), index=True)
    stem_plain_text = Column(Text, nullable=False)
    stem_normalized_text = Column(Text, nullable=False)
    answer_text = Column(Text)
    solution_summary = Column(Text)
    difficulty = Column(Numeric(4, 2))
    has_formula = Column(Boolean, default=False, nullable=False)
    has_figure = Column(Boolean, default=False, nullable=False)
    family_id = Column(Integer, ForeignKey("question_families.id"), nullable=True, index=True)
    quality_score = Column(Numeric(4, 2))
    source_origin = Column(String(32), default="explicit", nullable=False)
    review_status = Column(String(16), default="draft", nullable=False)
    canonical_hash = Column(String(64), index=True)

    family = relationship("QuestionFamily", back_populates="questions")
    paper_questions = relationship("PaperQuestion", back_populates="question_item")
    blocks = relationship("QuestionBlock", back_populates="question_item", cascade="all, delete-orphan")
    options = relationship("QuestionOption", back_populates="question_item", cascade="all, delete-orphan")


class PaperQuestion(Base):
    __tablename__ = "paper_questions"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    question_item_id = Column(Integer, ForeignKey("question_items.id"), nullable=True, index=True)
    question_no = Column(String(32), nullable=False, index=True)
    sub_question_no = Column(String(32))
    display_order = Column(Integer, nullable=False)
    score_value = Column(Numeric(6, 2))
    page_no = Column(Integer)
    anchor_bbox = Column(JSON)
    source_question_label = Column(String(64))
    parse_confidence = Column(Numeric(4, 2))

    paper = relationship("Paper", back_populates="questions")
    question_item = relationship("QuestionItem", back_populates="paper_questions")


class Formula(Base):
    __tablename__ = "formulas"

    id = Column(Integer, primary_key=True, index=True)
    question_item_id = Column(Integer, ForeignKey("question_items.id"), nullable=False, index=True)
    block_id = Column(Integer, ForeignKey("question_blocks.id"), nullable=True, index=True)
    source_type = Column(String(32), nullable=False)
    latex_text = Column(Text)
    mathml_text = Column(Text)
    linear_text = Column(Text)
    normalized_signature = Column(Text)
    parse_confidence = Column(Numeric(4, 2))
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)


class QuestionBlock(Base):
    __tablename__ = "question_blocks"

    id = Column(Integer, primary_key=True, index=True)
    question_item_id = Column(Integer, ForeignKey("question_items.id"), nullable=False, index=True)
    block_order = Column(Integer, nullable=False)
    block_role = Column(String(32), nullable=False, index=True)
    content_format = Column(String(32), nullable=False)
    text_content = Column(Text)
    rich_content_json = Column(JSON)
    formula_id = Column(Integer, ForeignKey("formulas.id"), nullable=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    parent_block_id = Column(Integer, ForeignKey("question_blocks.id"), nullable=True)
    source_origin = Column(String(32), default="explicit", nullable=False)
    confidence = Column(Numeric(4, 2))
    is_primary = Column(Boolean, default=False, nullable=False)

    question_item = relationship("QuestionItem", back_populates="blocks")


class QuestionOption(Base):
    __tablename__ = "question_options"

    id = Column(Integer, primary_key=True, index=True)
    question_item_id = Column(Integer, ForeignKey("question_items.id"), nullable=False, index=True)
    option_key = Column(String(8), nullable=False)
    option_text = Column(Text)
    formula_id = Column(Integer, ForeignKey("formulas.id"), nullable=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    display_order = Column(Integer, nullable=False)
    is_correct = Column(Boolean)

    question_item = relationship("QuestionItem", back_populates="options")


class TaxonomyNode(Base, TimestampMixin):
    __tablename__ = "taxonomy_nodes"

    id = Column(Integer, primary_key=True, index=True)
    taxonomy_type = Column(String(32), nullable=False, index=True)
    code = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey("taxonomy_nodes.id"), nullable=True)
    path = Column(Text)
    subject = Column(String(32), index=True)
    grade_scope = Column(String(64))
    description = Column(Text)
    status = Column(String(16), default="active", nullable=False)


class StrategyCard(Base, TimestampMixin):
    __tablename__ = "strategy_cards"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(32), index=True)
    applicable_question_types = Column(JSON)
    trigger_signals = Column(JSON)
    thinking_steps = Column(JSON)
    common_mistakes = Column(JSON)
    short_tip = Column(String(255))
    detail_content = Column(Text)
    source_origin = Column(String(32), default="explicit", nullable=False)
    review_status = Column(String(16), default="draft", nullable=False)


class MistakePattern(Base, TimestampMixin):
    __tablename__ = "mistake_patterns"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(32), nullable=False)
    description = Column(Text)
    symptom_signals = Column(JSON)
    correction_advice = Column(Text)
    source_origin = Column(String(32), default="explicit", nullable=False)
    review_status = Column(String(16), default="draft", nullable=False)


class QuestionTagLink(Base):
    __tablename__ = "question_tag_links"

    id = Column(Integer, primary_key=True, index=True)
    question_item_id = Column(Integer, ForeignKey("question_items.id"), nullable=False, index=True)
    target_type = Column(String(32), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    relation_type = Column(String(32), nullable=False)
    source_origin = Column(String(32), default="source_explicit", nullable=False)
    confidence = Column(Numeric(4, 2))
    evidence_block_id = Column(Integer, ForeignKey("question_blocks.id"), nullable=True)
    approved_status = Column(String(16), default="pending", nullable=False)


class QuestionRelation(Base, TimestampMixin):
    __tablename__ = "question_relations"

    id = Column(Integer, primary_key=True, index=True)
    source_question_id = Column(Integer, ForeignKey("question_items.id"), nullable=False, index=True)
    target_question_id = Column(Integer, ForeignKey("question_items.id"), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False, index=True)
    score = Column(Numeric(5, 4))
    evidence_json = Column(JSON)


class RetrievalDocument(Base):
    __tablename__ = "retrieval_documents"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    entity_type = Column(String(32), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    text_for_bm25 = Column(Text, nullable=False)
    text_for_embedding = Column(Text, nullable=False)
    metadata_json = Column(JSON)
    is_active = Column(Boolean, default=True, nullable=False)
    content_hash = Column(String(64), index=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class EmbeddingPoint(Base, TimestampMixin):
    __tablename__ = "embedding_points"

    id = Column(Integer, primary_key=True, index=True)
    retrieval_document_id = Column(Integer, ForeignKey("retrieval_documents.id"), nullable=False, index=True)
    backend_type = Column(String(16), nullable=False)
    point_id = Column(String(128), nullable=False, index=True)
    model_name = Column(String(128), nullable=False)
    vector_dim = Column(Integer)
    content_hash = Column(String(64), index=True)


class ExamSession(Base, TimestampMixin):
    __tablename__ = "exam_sessions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    student_id = Column(Integer, nullable=False, index=True)
    source_document_id = Column(Integer, ForeignKey("source_documents.id"), nullable=True, index=True)
    matched_paper_id = Column(Integer, ForeignKey("papers.id"), nullable=True, index=True)
    exam_date = Column(Date)
    subject = Column(String(32), index=True)
    parse_status = Column(String(16), default="pending", nullable=False)
    matching_status = Column(String(16), default="pending", nullable=False)
    analysis_status = Column(String(16), default="pending", nullable=False)
    visibility_scope = Column(String(32), default="private", nullable=False)

    tenant = relationship("Tenant", back_populates="exam_sessions")
    source_document = relationship("SourceDocument", back_populates="exam_sessions")
    questions = relationship("ExamSessionQuestion", back_populates="exam_session", cascade="all, delete-orphan")
    attempts = relationship("StudentAttempt", back_populates="exam_session", cascade="all, delete-orphan")


class ExamSessionQuestion(Base):
    __tablename__ = "exam_session_questions"

    id = Column(Integer, primary_key=True, index=True)
    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id"), nullable=False, index=True)
    source_question_no = Column(String(32), nullable=False)
    question_item_id = Column(Integer, ForeignKey("question_items.id"), nullable=True, index=True)
    page_no = Column(Integer)
    question_crop_asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)
    recognized_text = Column(Text)
    parse_confidence = Column(Numeric(4, 2))
    match_confidence = Column(Numeric(4, 2))
    review_status = Column(String(16), default="pending", nullable=False)

    exam_session = relationship("ExamSession", back_populates="questions")
    attempts = relationship("StudentAttempt", back_populates="exam_question")


class QuestionMatchResult(Base, TimestampMixin):
    __tablename__ = "question_match_results"

    id = Column(Integer, primary_key=True, index=True)
    exam_question_id = Column(Integer, ForeignKey("exam_session_questions.id"), nullable=False, index=True)
    candidate_question_id = Column(Integer, ForeignKey("question_items.id"), nullable=False, index=True)
    match_type = Column(String(32), nullable=False)
    text_score = Column(Numeric(5, 4))
    vector_score = Column(Numeric(5, 4))
    formula_score = Column(Numeric(5, 4))
    final_score = Column(Numeric(5, 4))
    accepted = Column(Boolean, default=False, nullable=False)


class StudentAttempt(Base, TimestampMixin):
    __tablename__ = "student_attempts"

    id = Column(Integer, primary_key=True, index=True)
    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id"), nullable=False, index=True)
    exam_question_id = Column(Integer, ForeignKey("exam_session_questions.id"), nullable=False, index=True)
    question_item_id = Column(Integer, ForeignKey("question_items.id"), nullable=True, index=True)
    student_id = Column(Integer, nullable=False, index=True)
    student_answer_raw = Column(Text)
    answer_blocks_json = Column(JSON)
    is_correct = Column(Boolean)
    score_earned = Column(Numeric(6, 2))
    time_spent_seconds = Column(Integer)
    teacher_mark_json = Column(JSON)
    ocr_confidence = Column(Numeric(4, 2))

    exam_session = relationship("ExamSession", back_populates="attempts")
    exam_question = relationship("ExamSessionQuestion", back_populates="attempts")


class DiagnosisSnapshot(Base):
    __tablename__ = "diagnosis_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, nullable=False, index=True)
    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id"), nullable=False, index=True)
    knowledge_profile_json = Column(JSON)
    ability_profile_json = Column(JSON)
    mistake_profile_json = Column(JSON)
    action_plan_json = Column(JSON)
    llm_summary = Column(Text)
    generated_at = Column(DateTime, default=func.now(), nullable=False)
