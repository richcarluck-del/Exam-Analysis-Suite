#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查数据库内容"""

from src.database import SessionLocal
from src import crud

db = SessionLocal()

try:
    # 检查 API 提供商
    providers = crud.get_api_providers(db)
    print(f"API 提供商数量：{len(providers)}")
    for p in providers:
        print(f"  - {p.provider_name}: {p.api_url}")
    
    # 检查提示词版本
    versions = crud.get_distinct_prompt_versions(db)
    print(f"\n提示词版本数量：{len(versions)}")
    for v in versions:
        print(f"  - {v[0]}")
        
finally:
    db.close()
