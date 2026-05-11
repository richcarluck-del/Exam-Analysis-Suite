#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新 OhMyGPT API 供应商配置"""

from src.database import SessionLocal
from src import crud, schemas, models

db = SessionLocal()
try:
    # 查找现有的 ohmygpt 供应商
    existing = db.query(models.APIProvider).filter(
        models.APIProvider.provider_name == "ohmygpt"
    ).first()
    
    new_api_url = "https://c-z0-api-01.hash070.com/v1"
    new_api_key = "sk-DVFq570T4f7dDDf26dc3T3BlbKFJ78f7909d1Dc647B8982C"
    
    if existing:
        # 更新现有供应商
        existing.api_url = new_api_url
        existing.api_key = new_api_key
        print("✅ 已更新 OhMyGPT 供应商配置：")
        print(f"   API URL: {new_api_url}")
        print(f"   API Key: {new_api_key[:15]}...{new_api_key[-5:]}")
    else:
        # 创建新供应商
        provider = schemas.APIProviderCreate(
            provider_name="ohmygpt",
            api_url=new_api_url,
            api_key=new_api_key
        )
        crud.create_api_provider(db, provider)
        print("✅ 已创建 OhMyGPT 供应商：")
        print(f"   API URL: {new_api_url}")
        print(f"   API Key: {new_api_key[:15]}...{new_api_key[-5:]}")
    
    db.commit()
    
    # 验证更新
    print("\n验证数据库中的配置：")
    providers = db.query(models.APIProvider).filter(
        models.APIProvider.provider_name.like("%ohmy%")
    ).all()
    
    for p in providers:
        print(f"\n供应商：{p.provider_name}")
        print(f"  API URL: {p.api_url}")
        print(f"  API Key: {p.api_key[:15]}...{p.api_key[-5:]}")
    
    print("\n✅ OhMyGPT 供应商配置更新完成！")
    
finally:
    db.close()
