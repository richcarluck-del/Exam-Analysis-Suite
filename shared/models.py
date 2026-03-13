from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from shared.database import Base

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
    name = Column(String, unique=True, index=True) # e.g., "Perspective Correction", "Layout Analysis"
    description = Column(String)

    versions = relationship("PromptVersion", back_populates="prompt")

class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    prompt_id = Column(Integer, ForeignKey("prompts.id"))

    prompt = relationship("Prompt", back_populates="versions")
