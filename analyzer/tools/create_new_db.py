#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建全新的数据库"""

import os
import time

DB_PATH = "exam_analysis_new.db"

# 确保旧文件不存在
for f in [DB_PATH, DB_PATH + '-wal', DB_PATH + '-shm']:
    if os.path.exists(f):
        os.remove(f)
        print(f"已删除：{f}")

print(f"\n创建新数据库：{DB_PATH}")

# 创建数据库
from src.database import Base, engine
Base.metadata.create_all(bind=engine)
print("✅ 数据库表创建成功！")

# 初始化数据
from src.database import SessionLocal
from src import crud, schemas

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
            name="exam_analysis",
            version=v,
            system_prompt=f"试卷分析助手 v{v}",
            user_prompt_template="请分析这张试卷"
        )
        crud.create_prompt(db, prompt)
        print(f"✅ 创建提示词：{v}")
    
    print("\n✅ 数据库初始化完成！")
    
finally:
    db.close()

print(f"\n新数据库路径：{os.path.abspath(DB_PATH)}")
