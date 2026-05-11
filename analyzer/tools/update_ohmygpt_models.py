#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新 OhMyGPT 的可用模型"""

from src.database import SessionLocal
from src import crud, schemas, models

db = SessionLocal()
try:
    # 删除旧的模型
    old_models = db.query(models.LLMModel).filter(
        models.LLMModel.provider_name == "ohmygpt"
    ).all()
    
    for model in old_models:
        db.delete(model)
    db.commit()
    print(f"✅ 已删除 {len(old_models)} 个旧模型")
    
    # 添加新的视觉模型
    vision_models = [
        {
            "model_name": "gpt-4o",
            "description": "GPT-4o - OpenAI 的多模态模型，支持视觉理解"
        },
        {
            "model_name": "gpt-4-turbo",
            "description": "GPT-4 Turbo - 支持视觉的多模态模型"
        },
        {
            "model_name": "gpt-4-vision-preview",
            "description": "GPT-4 Vision - 专门的视觉模型"
        }
    ]
    
    for model_data in vision_models:
        model = schemas.LLMModelCreate(
            provider_name="ohmygpt",
            model_name=model_data["model_name"],
            description=model_data["description"]
        )
        crud.create_llm_model(db, model)
        print(f"✅ 已添加模型：{model_data['model_name']}")
    
    db.commit()
    
    # 验证添加
    print("\n验证数据库中的 OhMyGPT 模型：")
    ohmygpt_models = db.query(models.LLMModel).filter(
        models.LLMModel.provider_name == "ohmygpt"
    ).all()
    
    for m in ohmygpt_models:
        print(f"  - {m.model_name}: {m.description}")
    
    print(f"\n✅ 共添加了 {len(ohmygpt_models)} 个 OhMyGPT 模型")
    
finally:
    db.close()
