#!/usr/bin/env python3
from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    # 查找所有透视矫正相关的提示词
    prompts = db.query(models.Prompt).filter(
        models.Prompt.name.like("%perspective%")
    ).all()
    
    print(f"数据库中有 {len(prompts)} 个透视矫正提示词：\n")
    
    for p in prompts:
        print("="*80)
        print(f"名称：{p.name}")
        print(f"版本：{p.version}")
        print(f"描述：{p.description}")
        print(f"系统提示：{p.system_prompt}")
        print(f"\n完整内容：")
        print(p.content)
        print("="*80)
        print()
    
finally:
    db.close()
