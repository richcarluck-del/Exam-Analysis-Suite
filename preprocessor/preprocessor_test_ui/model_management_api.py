from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from analyzer.app.security import decrypt_api_key, encrypt_api_key
from shared import models
from shared.database import SessionLocal as MainSessionLocal
from shared.llm_step_config import list_llm_step_configs, update_llm_step_config

router = APIRouter(tags=["model-management"])


class ProviderUpsertPayload(BaseModel):
    name: str
    api_url: str
    api_key: str


class ModelCreatePayload(BaseModel):
    name: str


class StepConfigUpdatePayload(BaseModel):
    provider_id: int
    model_id: int
    is_active: bool = True


def get_main_db():
    db = MainSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _clean_required_text(value: str, field_name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name} 不能为空")
    return cleaned


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return "未设置"
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:5]}...{api_key[-4:]}"


def _serialize_provider(provider: models.APIProvider) -> dict[str, Any]:
    display_api_key = "未设置"
    if provider.encrypted_api_key:
        try:
            display_api_key = _mask_api_key(decrypt_api_key(provider.encrypted_api_key))
        except Exception:
            display_api_key = "解密失败"

    return {
        "id": provider.id,
        "name": provider.name,
        "api_url": provider.api_url,
        "display_api_key": display_api_key,
        "model_count": len(provider.models or []),
    }


def _serialize_model(model: models.LLMModel) -> dict[str, Any]:
    provider = model.provider
    return {
        "id": model.id,
        "name": model.name,
        "provider_id": model.provider_id,
        "provider_name": provider.name if provider else None,
    }


@router.get("/api/main-db/providers")
def get_main_db_providers(db: Session = Depends(get_main_db)):
    providers = (
        db.query(models.APIProvider)
        .options(joinedload(models.APIProvider.models))
        .order_by(models.APIProvider.id.asc())
        .all()
    )
    return [_serialize_provider(provider) for provider in providers]


@router.post("/api/main-db/providers")
def upsert_main_db_provider(payload: ProviderUpsertPayload, db: Session = Depends(get_main_db)):
    provider_name = _clean_required_text(payload.name, "供应商名称")
    api_url = _clean_required_text(payload.api_url, "API URL")
    api_key = _clean_required_text(payload.api_key, "API Key")

    provider = (
        db.query(models.APIProvider)
        .filter(func.lower(models.APIProvider.name) == provider_name.lower())
        .first()
    )
    created = provider is None

    if created:
        provider = models.APIProvider(
            name=provider_name,
            api_url=api_url,
            encrypted_api_key=encrypt_api_key(api_key),
        )
        db.add(provider)
    else:
        provider.name = provider_name
        provider.api_url = api_url
        provider.encrypted_api_key = encrypt_api_key(api_key)

    db.commit()

    provider = (
        db.query(models.APIProvider)
        .options(joinedload(models.APIProvider.models))
        .filter(models.APIProvider.id == provider.id)
        .first()
    )
    return {
        "created": created,
        "provider": _serialize_provider(provider),
    }


@router.get("/api/main-db/models")
def get_main_db_models(db: Session = Depends(get_main_db)):
    llm_models = (
        db.query(models.LLMModel)
        .options(joinedload(models.LLMModel.provider))
        .order_by(models.LLMModel.provider_id.asc(), models.LLMModel.id.asc())
        .all()
    )
    return [_serialize_model(model) for model in llm_models]


@router.post("/api/main-db/providers/{provider_id}/models")
def create_main_db_model(provider_id: int, payload: ModelCreatePayload, db: Session = Depends(get_main_db)):
    provider = (
        db.query(models.APIProvider)
        .options(joinedload(models.APIProvider.models))
        .filter(models.APIProvider.id == provider_id)
        .first()
    )
    if not provider:
        raise HTTPException(status_code=404, detail="供应商不存在")

    model_name = _clean_required_text(payload.name, "模型名称")
    existing_model = (
        db.query(models.LLMModel)
        .options(joinedload(models.LLMModel.provider))
        .filter(
            models.LLMModel.provider_id == provider_id,
            func.lower(models.LLMModel.name) == model_name.lower(),
        )
        .first()
    )
    created = existing_model is None

    if created:
        existing_model = models.LLMModel(name=model_name, provider_id=provider_id)
        db.add(existing_model)
        db.commit()

    model = (
        db.query(models.LLMModel)
        .options(joinedload(models.LLMModel.provider))
        .filter(models.LLMModel.id == existing_model.id)
        .first()
    )
    return {
        "created": created,
        "model": _serialize_model(model),
    }


@router.get("/api/main-db/llm-step-configs")
def get_main_db_llm_step_configs(db: Session = Depends(get_main_db)):
    return list_llm_step_configs(db)


@router.put("/api/main-db/llm-step-configs/{step_key}")
def put_main_db_llm_step_config(
    step_key: str,
    payload: StepConfigUpdatePayload,
    db: Session = Depends(get_main_db),
):
    try:
        return update_llm_step_config(
            db,
            step_key,
            provider_id=int(payload.provider_id),
            model_id=int(payload.model_id),
            is_active=bool(payload.is_active),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
