#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证数据库中的透视矫正提示词"""

from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    prompts = db.query(models.Prompt).filter(
        models.Prompt.name.like("%perspective%")
    ).all()
    
    print(f"数据库中共有 {len(prompts)} 个透视矫正相关提示词：\n")
    
    for p in prompts:
        print("="*80)
        print(f"名称：{p.name}")
        print(f"版本：{p.version}")
        print(f"描述：{p.description}")
        print(f"系统提示：{p.system_prompt}")
        print(f"内容长度：{len(p.content)} 字符")
        print(f"\n内容前 500 字符：")
        print(p.content[:500])
        print("...")
        print("="*80)
        print()
    
finally:
    db.close()
