#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""添加 qwen3.5-plus 模型到数据库"""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app'))

from app.database import SessionLocal
from app import crud, schemas, models

db = SessionLocal()
try:
    # 检查是否已存在
    existing = db.query(models.LLMModel).filter(
        models.LLMModel.provider_name == "dashscope",
        models.LLMModel.model_name == "qwen-vl-plus"
    ).first()
    
    if existing:
        print(f"⚠️  模型 qwen-vl-plus 已存在")
        print(f"   ID: {existing.id}")
        print(f"   描述：{existing.description}")
    else:
        # 创建新模型
        model = schemas.LLMModelCreate(
            provider_name="dashscope",
            model_name="qwen-vl-plus",
            description="通义千问 VL Plus - DashScope 多模态视觉模型"
        )
        crud.create_llm_model(db, model)
        print(f"✅ 已成功添加模型 qwen-vl-plus")
        db.commit()
    
    # 显示 dashscope 的所有模型
    print(f"\nDashScope 提供商的所有模型：")
    print("-"*80)
    dashscope_models = db.query(models.LLMModel).filter(
        models.LLMModel.provider_name == "dashscope"
    ).all()
    
    for m in dashscope_models:
        print(f"  - {m.model_name}: {m.description}")
    
    print(f"\n共 {len(dashscope_models)} 个模型")
    
finally:
    db.close()
