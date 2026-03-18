from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from shared.database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)

class APIProvider(Base):
    __tablename__ = "api_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    api_url = Column(String, nullable=False)
    encrypted_api_key = Column(String, nullable=False)

    models = relationship("LLMModel", back_populates="provider")

class LLMModel(Base):
    __tablename__ = "llm_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    provider_id = Column(Integer, ForeignKey("api_providers.id"))

    provider = relationship("APIProvider", back_populates="models")

class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)  # e.g., "perspective_correction_all_types_v1"
    display_name = Column(String(200))  # 显示名称，如 "透视矫正 V1"
    description = Column(Text)  # 详细描述
    
    # 多维度分类字段
    pipeline_step = Column(Integer)  # 所属步骤：1, 2, 3, 4, 6
    category = Column(String(50))  # 类别：perspective_correction, classification, layout_analysis, content_extraction, draw_output
    target_type = Column(String(50))  # 作用对象：all_types, full_page, exam_paper, answer_sheet, mixed
    scenario = Column(String(100))  # 场景：corner_detection, page_type, question_detection 等
    
    # 版本管理
    version = Column(Integer, default=1)  # 版本号
    is_latest = Column(Boolean, default=False)  # 是否最新版本
    is_active = Column(Boolean, default=True)  # 是否启用
    
    # 元数据
    created_by = Column(String(100))  # 创建者
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    # 关联
    versions = relationship("PromptVersion", back_populates="prompt", cascade="all, delete-orphan", lazy="selectin")

class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(Integer, primary_key=True, index=True)
    
    # 关联
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False)
    
    # 版本信息
    version = Column(Integer, nullable=False)  # 版本号
    prompt_text = Column(Text, nullable=False)  # 提示词完整内容
    
    # 状态
    status = Column(String(20), default='published')  # draft, review, published, deprecated
    
    # 元数据
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    change_log = Column(Text)  # 变更说明
    
    # 关联
    prompt = relationship("Prompt", back_populates="versions")
