#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化新数据库"""

print("初始化新数据库...")

from src.database import Base, engine, SessionLocal
from src import crud, schemas

# 创建表
Base.metadata.create_all(bind=engine)
print("✅ 数据库表创建成功！")

# 初始化数据
db = SessionLocal()
try:
    # 创建 API 提供商
    providers = [
        schemas.APIProviderCreate(
            provider_name="ohmygpt",
            api_url="https://api.ohmygpt.com/v1/chat/completions",
            api_key="sk-test123"
        ),
        schemas.APIProviderCreate(
            provider_name="dashscope",
            api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key="sk-dashscope123"
        )
    ]
    
    for p in providers:
        crud.create_api_provider(db, p)
        print(f"✅ 创建 API 提供商：{p.provider_name}")
    
    # 创建模型
    models = [
        schemas.LLMModelCreate(provider_name="ohmygpt", model_name="gemini-pro-vision", model_type="vision"),
        schemas.LLMModelCreate(provider_name="dashscope", model_name="qwen-vl-plus", model_type="vision"),
        schemas.LLMModelCreate(provider_name="dashscope", model_name="qwen-vl-max", model_type="vision")
    ]
    
    for m in models:
        crud.create_llm_model(db, m)
        print(f"✅ 创建模型：{m.model_name}")
    
    # 创建提示词
    for v in ['v1', 'v2', 'v3', 'v4', 'v5']:
        prompt = schemas.PromptCreate(
            name="answer_sheet",
            version=v,
            system_prompt=f"试卷分析助手 v{v}",
            user_prompt_template="请分析这张试卷",
            content=f"提示词内容 v{v}"
        )
        crud.create_prompt(db, prompt)
        print(f"✅ 创建提示词：{v}")
    
    print("\n✅ 数据库初始化完成！")
    
finally:
    db.close()
