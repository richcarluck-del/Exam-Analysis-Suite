#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查数据库中的提示词"""

from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    prompts = db.query(models.Prompt).all()
    print(f"数据库中共有 {len(prompts)} 个提示词：")
    for p in prompts:
        print(f"  - name='{p.name}', version='{p.version}', content='{p.content[:50]}...'")
finally:
    db.close()
