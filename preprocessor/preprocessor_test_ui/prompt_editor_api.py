#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词管理 API
- Prompt Catalog：管理所有注册提示词与版本历史
- Prompt Step Config：按步骤绑定提示词版本（默认最高版本，可固定版本）
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from db_runtime import SessionLocal
from shared.prompt_step_config import (
    create_prompt_version,
    get_prompt_detail,
    list_available_prompt_versions,
    list_prompt_step_configs,
    list_registered_prompts,
    parse_prompt_version,
    sync_prompt_step_configs,
    update_prompt_step_config,
)

router = APIRouter(tags=["prompts"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _filter_prompt_catalog(
    prompts: list[dict[str, Any]],
    *,
    module_name: Optional[str] = None,
    pipeline_step: Optional[int] = None,
    category: Optional[str] = None,
    target_type: Optional[str] = None,
    search: Optional[str] = None,
    version: Optional[int] = None,
) -> list[dict[str, Any]]:
    result = prompts
    if module_name:
        result = [item for item in result if item.get("module_name") == module_name]
    if pipeline_step is not None:
        result = [item for item in result if item.get("pipeline_step") == pipeline_step]
    if category:
        result = [item for item in result if item.get("category") == category]
    if target_type:
        result = [item for item in result if item.get("target_type") == target_type]
    if version is not None:
        result = [item for item in result if int(item.get("version") or 0) == int(version)]
    if search:
        keyword = search.strip().lower()
        result = [
            item
            for item in result
            if keyword in (item.get("name") or "").lower()
            or keyword in (item.get("display_name") or "").lower()
            or keyword in (item.get("description") or "").lower()
            or any(keyword in (step_key or "").lower() for step_key in (item.get("step_keys") or []))
            or any(keyword in (step_label or "").lower() for step_label in (item.get("step_labels") or []))
        ]
    return result


@router.get("/api/prompts/all")
def get_all_prompts(
    module_name: Optional[str] = None,
    step: Optional[int] = None,
    category: Optional[str] = None,
    target_type: Optional[str] = None,
    version: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    prompts = list_registered_prompts(db)
    return _filter_prompt_catalog(
        prompts,
        module_name=module_name,
        pipeline_step=step,
        category=category,
        target_type=target_type,
        search=search,
        version=version,
    )


@router.get("/api/prompts/versions")
def get_available_versions(db: Session = Depends(get_db)):
    return list_available_prompt_versions(db)


@router.get("/api/prompts/{prompt_id}")
def get_prompt_detail_api(prompt_id: int, db: Session = Depends(get_db)):
    payload = get_prompt_detail(db, prompt_id)
    if not payload:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return payload


@router.put("/api/prompts/{prompt_id}")
def update_prompt_compat(
    prompt_id: int,
    prompt_text: str,
    version: int,
    status: str = "published",
    change_log: str = "",
    db: Session = Depends(get_db),
):
    try:
        detail = create_prompt_version(
            db,
            prompt_id,
            prompt_text=prompt_text,
            version=version,
            status=status,
            change_log=change_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "提示词已更新",
        "prompt_id": prompt_id,
        "new_version": version,
        "prompt": detail,
    }


@router.post("/api/prompts/{prompt_id}/versions")
def create_prompt_version_api(prompt_id: int, payload: dict[str, Any], db: Session = Depends(get_db)):
    prompt_text = (payload or {}).get("prompt_text")
    version = (payload or {}).get("version")
    status = (payload or {}).get("status", "published")
    change_log = (payload or {}).get("change_log", "")

    if version is None:
        raise HTTPException(status_code=400, detail="version 不能为空")

    try:
        return create_prompt_version(
            db,
            prompt_id,
            prompt_text=prompt_text,
            version=int(version),
            status=status,
            change_log=change_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/prompts/stats/summary")
def get_prompts_summary(db: Session = Depends(get_db)):
    prompts = list_registered_prompts(db)
    total_versions = sum(int(item.get("version_count") or 0) for item in prompts)

    by_step: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_version: dict[str, int] = {}
    by_module: dict[str, int] = {}

    for item in prompts:
        pipeline_step = item.get("pipeline_step")
        target_type = item.get("target_type") or "unknown"
        module_name = item.get("module_name") or "unknown"

        if pipeline_step is not None:
            by_step[str(pipeline_step)] = by_step.get(str(pipeline_step), 0) + 1
        by_type[target_type] = by_type.get(target_type, 0) + 1
        by_module[module_name] = by_module.get(module_name, 0) + 1

        for prompt_version in item.get("available_versions") or []:
            key = str(prompt_version)
            by_version[key] = by_version.get(key, 0) + 1

    return {
        "total_prompts": len(prompts),
        "total_versions": total_versions,
        "by_step": by_step,
        "by_type": by_type,
        "by_version": by_version,
        "by_module": by_module,
    }


@router.get("/api/prompt-step-configs")
def get_prompt_step_configs(
    module_name: Optional[str] = None,
    version_override: Optional[str] = None,
    db: Session = Depends(get_db),
):
    sync_prompt_step_configs(db)
    configs = list_prompt_step_configs(db, version_override=version_override)
    if module_name:
        configs = [item for item in configs if item.get("module_name") == module_name]
    return configs


@router.put("/api/prompt-step-configs/{step_key}")
def put_prompt_step_config(step_key: str, payload: dict[str, Any], db: Session = Depends(get_db)):
    selected_version_raw = (payload or {}).get("selected_version")
    is_active = (payload or {}).get("is_active", True)
    selected_version = parse_prompt_version(selected_version_raw)

    try:
        return update_prompt_step_config(
            db,
            step_key,
            selected_version=selected_version,
            is_active=bool(is_active),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
