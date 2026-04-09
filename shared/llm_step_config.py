from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from shared import models


VISION_MODEL_HINTS = (
    "vision",
    "vl",
    "4v",
    "4o",
    "gemini",
    "doubao",
    "glm-4v",
)


STEP_CONFIG_DEFINITIONS = [
    {
        "step_key": "preprocessor.perspective_correction",
        "step_label": "预处理-透视矫正",
        "module_name": "preprocessor",
        "step_order": "1",
        "description": "试卷/答题卡透视矫正的 VLM 配置。",
        "seed_provider_name": "dashscope",
        "seed_model_name": "qwen3.5-plus",
    },
    {
        "step_key": "preprocessor.classify",
        "step_label": "预处理-页面分类",
        "module_name": "preprocessor",
        "step_order": "2",
        "description": "单页分类与长图分类共用的页面分类模型配置。",
        "seed_provider_name": "dashscope",
        "seed_model_name": "qwen3.5-plus",
    },
    {
        "step_key": "preprocessor.extract_content",
        "step_label": "预处理-内容提取",
        "module_name": "preprocessor",
        "step_order": "4",
        "description": "题目/答题区内容提取的主 VLM 配置。",
        "seed_provider_name": "dashscope",
        "seed_model_name": "qwen3.5-plus",
    },
    {
        "step_key": "preprocessor.answer_card_recognition",
        "step_label": "预处理-涂卡识别",
        "module_name": "preprocessor",
        "step_order": "6",
        "description": "选择题涂卡区识别的专用 VLM 配置。",
        "seed_provider_name": "volcengine",
        "seed_model_name": "doubao-seed-2-0-pro-260215",
    },
    {
        "step_key": "preprocessor.whole_page_perspective_correction",
        "step_label": "整页画框-透视矫正",
        "module_name": "preprocessor",
        "step_order": "whole-page:2",
        "description": "整页画框工具内透视矫正所使用的 VLM 配置。",
        "seed_provider_name": "dashscope",
        "seed_model_name": "qwen3.5-plus",
    },
    {
        "step_key": "preprocessor.whole_page_detection",
        "step_label": "整页画框-整页识别",
        "module_name": "preprocessor",
        "step_order": "whole-page:4",
        "description": "整页画框工具识别整张长图题目的 VLM 配置。",
        "seed_provider_name": "dashscope",
        "seed_model_name": "qwen3.5-plus",
    },
    {
        "step_key": "preprocessor.question_solver_recognition",
        "step_label": "题目求解-题目识别",
        "module_name": "question_solver",
        "step_order": "question-solver:recognize",
        "description": "题目求解工具中题图识别所使用的视觉模型配置。",
        "seed_strategy": "first_vision",
    },
    {
        "step_key": "preprocessor.question_solver_solving",
        "step_label": "题目求解-解题推理",
        "module_name": "question_solver",
        "step_order": "question-solver:solve",
        "description": "题目求解工具中解题推理所使用的文本模型配置。",
        "seed_model_name": "deepseek-chat",
    },
    {
        "step_key": "analyzer.question_vlm",

        "step_label": "分析器-题级 VLM",
        "module_name": "analyzer",
        "step_order": "question_vlm",
        "description": "逐题图片观察与答题状态分析所使用的视觉模型配置。",
        "seed_strategy": "first_vision",
    },
    {
        "step_key": "analyzer.reasoning",
        "step_label": "分析器-推理融合",
        "module_name": "analyzer",
        "step_order": "reasoning",
        "description": "检索关键词提取与最终逐题结论融合所使用的文本模型配置。",
        "seed_strategy": "first_available",
    },
    {
        "step_key": "analyzer.knowledge_extraction",
        "step_label": "分析器-知识抽取",
        "module_name": "analyzer",
        "step_order": "knowledge_extraction",
        "description": "知识库文档实体关系抽取所使用的文本模型配置。",
        "seed_strategy": "first_available",
    },
]


STEP_CONFIG_DEFINITION_MAP = {
    definition["step_key"]: definition for definition in STEP_CONFIG_DEFINITIONS
}


def supports_vision_model_name(model_name: Optional[str]) -> bool:
    normalized = (model_name or "").strip().lower()
    if not normalized:
        return False
    return any(hint in normalized for hint in VISION_MODEL_HINTS)


def ensure_llm_step_config_table(bind) -> None:
    models.LLMStepConfig.__table__.create(bind=bind, checkfirst=True)


def _serialize_step_config(record: models.LLMStepConfig) -> Dict[str, Any]:
    provider = record.provider
    model = record.model
    return {
        "id": record.id,
        "step_key": record.step_key,
        "step_label": record.step_label,
        "module_name": record.module_name,
        "step_order": record.step_order,
        "description": record.description,
        "is_active": record.is_active,
        "provider_id": record.provider_id,
        "provider_name": provider.name if provider else None,
        "model_id": record.model_id,
        "model_name": model.name if model else None,
        "model_provider_id": model.provider_id if model else None,
        "config_complete": bool(
            record.is_active
            and provider is not None
            and model is not None
            and record.provider_id == model.provider_id
        ),
    }


def _query_step_config(db: Session, step_key: str) -> Optional[models.LLMStepConfig]:
    return (
        db.query(models.LLMStepConfig)
        .options(
            joinedload(models.LLMStepConfig.provider),
            joinedload(models.LLMStepConfig.model),
        )
        .filter(models.LLMStepConfig.step_key == step_key)
        .first()
    )


def _query_all_step_configs(db: Session) -> list[models.LLMStepConfig]:
    records = (
        db.query(models.LLMStepConfig)
        .options(
            joinedload(models.LLMStepConfig.provider),
            joinedload(models.LLMStepConfig.model),
        )
        .all()
    )
    sort_index = {
        definition["step_key"]: index for index, definition in enumerate(STEP_CONFIG_DEFINITIONS)
    }
    return sorted(records, key=lambda item: sort_index.get(item.step_key, 9999))


def _resolve_named_provider_and_model(
    db: Session,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> tuple[Optional[models.APIProvider], Optional[models.LLMModel]]:
    provider = None
    model = None

    if provider_name:
        provider = (
            db.query(models.APIProvider)
            .filter(func.lower(models.APIProvider.name) == provider_name.strip().lower())
            .first()
        )
        if not provider:
            return None, None

    if model_name and provider:
        model = (
            db.query(models.LLMModel)
            .filter(
                models.LLMModel.provider_id == provider.id,
                func.lower(models.LLMModel.name) == model_name.strip().lower(),
            )
            .first()
        )
        return provider, model

    if model_name and not provider:
        model = (
            db.query(models.LLMModel)
            .options(joinedload(models.LLMModel.provider))
            .filter(func.lower(models.LLMModel.name) == model_name.strip().lower())
            .order_by(models.LLMModel.id.asc())
            .first()
        )
        if not model:
            return None, None
        return model.provider, model

    if provider and not model_name:
        model = (
            db.query(models.LLMModel)
            .filter(models.LLMModel.provider_id == provider.id)
            .order_by(models.LLMModel.id.asc())
            .first()
        )
        return provider, model

    return None, None


def _resolve_first_available_provider_and_model(
    db: Session,
    prefer_vision: bool = False,
) -> tuple[Optional[models.APIProvider], Optional[models.LLMModel]]:
    providers = (
        db.query(models.APIProvider)
        .options(joinedload(models.APIProvider.models))
        .order_by(models.APIProvider.id.asc())
        .all()
    )

    fallback_provider = None
    fallback_model = None
    for provider in providers:
        ordered_models = sorted(provider.models or [], key=lambda item: item.id)
        for model in ordered_models:
            if fallback_model is None:
                fallback_provider = provider
                fallback_model = model
            if prefer_vision and supports_vision_model_name(model.name):
                return provider, model

    return fallback_provider, fallback_model


def _seed_binding_for_definition(
    db: Session,
    definition: Dict[str, Any],
) -> tuple[Optional[models.APIProvider], Optional[models.LLMModel]]:
    if definition.get("seed_provider_name") or definition.get("seed_model_name"):
        return _resolve_named_provider_and_model(
            db,
            provider_name=definition.get("seed_provider_name"),
            model_name=definition.get("seed_model_name"),
        )

    strategy = definition.get("seed_strategy")
    if strategy == "first_vision":
        return _resolve_first_available_provider_and_model(db, prefer_vision=True)
    if strategy == "first_available":
        return _resolve_first_available_provider_and_model(db, prefer_vision=False)
    return None, None


def sync_llm_step_configs(db: Session) -> list[Dict[str, Any]]:
    ensure_llm_step_config_table(db.bind)

    existing_map = {
        record.step_key: record
        for record in db.query(models.LLMStepConfig).all()
    }
    changed = False

    for definition in STEP_CONFIG_DEFINITIONS:
        record = existing_map.get(definition["step_key"])
        if record is None:
            record = models.LLMStepConfig(
                step_key=definition["step_key"],
                step_label=definition["step_label"],
                module_name=definition["module_name"],
                step_order=definition.get("step_order"),
                description=definition.get("description"),
                is_active=True,
            )
            db.add(record)
            existing_map[record.step_key] = record
            changed = True
        else:
            if record.step_label != definition["step_label"]:
                record.step_label = definition["step_label"]
                changed = True
            if record.module_name != definition["module_name"]:
                record.module_name = definition["module_name"]
                changed = True
            if record.step_order != definition.get("step_order"):
                record.step_order = definition.get("step_order")
                changed = True
            if record.description != definition.get("description"):
                record.description = definition.get("description")
                changed = True

        if record.provider_id is None or record.model_id is None:
            provider, model = _seed_binding_for_definition(db, definition)
            if provider and model:
                record.provider_id = provider.id
                record.model_id = model.id
                changed = True

    if changed:
        db.commit()

    return [_serialize_step_config(record) for record in _query_all_step_configs(db)]


def list_llm_step_configs(db: Session) -> list[Dict[str, Any]]:
    sync_llm_step_configs(db)
    return [_serialize_step_config(record) for record in _query_all_step_configs(db)]


def get_llm_step_config(db: Session, step_key: str) -> Optional[models.LLMStepConfig]:
    sync_llm_step_configs(db)
    return _query_step_config(db, step_key)


def update_llm_step_config(
    db: Session,
    step_key: str,
    provider_id: int,
    model_id: int,
    is_active: bool = True,
) -> Dict[str, Any]:
    record = get_llm_step_config(db, step_key)
    if not record:
        raise ValueError(f"Unknown step_key: {step_key}")

    provider = db.query(models.APIProvider).filter(models.APIProvider.id == provider_id).first()
    if not provider:
        raise ValueError(f"Provider not found: {provider_id}")

    model = db.query(models.LLMModel).filter(models.LLMModel.id == model_id).first()
    if not model:
        raise ValueError(f"Model not found: {model_id}")

    if model.provider_id != provider.id:
        raise ValueError("Selected model does not belong to the selected provider")

    record.provider_id = provider.id
    record.model_id = model.id
    record.is_active = bool(is_active)
    db.commit()

    refreshed = _query_step_config(db, step_key)
    return _serialize_step_config(refreshed)


def build_llm_config(provider: models.APIProvider, model: models.LLMModel, api_key_override: Optional[str] = None) -> Dict[str, Any]:
    from analyzer.app.security import decrypt_api_key

    api_key = api_key_override if api_key_override else decrypt_api_key(provider.encrypted_api_key)
    return {
        "provider_id": provider.id,
        "provider_name": provider.name,
        "model_id": model.id,
        "model_name": model.name,
        "api_url": str(provider.api_url),
        "api_key": api_key,
        "api_key_decrypted": True,
    }


def resolve_model_config_by_id(
    db: Session,
    model_id: int,
    api_key_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    model = (
        db.query(models.LLMModel)
        .options(joinedload(models.LLMModel.provider))
        .filter(models.LLMModel.id == model_id)
        .first()
    )
    if not model or not model.provider:
        return None
    return build_llm_config(model.provider, model, api_key_override=api_key_override)


def resolve_step_llm_config(
    db: Session,
    step_key: str,
    *,
    api_key_override: Optional[str] = None,
    fallback_provider_name: Optional[str] = None,
    fallback_model_name: Optional[str] = None,
    allow_generic_fallback: bool = False,
    prefer_vision_fallback: bool = False,
) -> Optional[Dict[str, Any]]:
    record = get_llm_step_config(db, step_key)
    if record:
        if not record.is_active:
            return None
        if record.provider and record.model and record.model.provider_id == record.provider_id:
            config = build_llm_config(record.provider, record.model, api_key_override=api_key_override)
            config["step_key"] = step_key
            config["config_source"] = "llm_step_config"
            return config

    if fallback_provider_name or fallback_model_name:
        provider, model = _resolve_named_provider_and_model(
            db,
            provider_name=fallback_provider_name,
            model_name=fallback_model_name,
        )
        if provider and model:
            config = build_llm_config(provider, model, api_key_override=api_key_override)
            config["step_key"] = step_key
            config["config_source"] = "legacy_override"
            return config

    if allow_generic_fallback:
        provider, model = _resolve_first_available_provider_and_model(
            db,
            prefer_vision=prefer_vision_fallback,
        )
        if provider and model:
            config = build_llm_config(provider, model, api_key_override=api_key_override)
            config["step_key"] = step_key
            config["config_source"] = "generic_fallback"
            return config

    return None
