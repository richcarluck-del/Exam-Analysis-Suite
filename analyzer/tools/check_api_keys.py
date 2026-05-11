#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查数据库中的 API Key"""

from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    providers = db.query(models.APIProvider).all()
    print(f"数据库中共有 {len(providers)} 个 API 提供商：")
    for p in providers:
        print(f"\n  ID: {p.id}")
        print(f"  名称：{p.provider_name}")
        print(f"  API Key: {p.api_key}")
        print(f"  API URL: {p.api_url}")
finally:
    db.close()
