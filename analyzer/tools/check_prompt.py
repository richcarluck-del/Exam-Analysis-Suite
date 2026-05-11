#!/usr/bin/env python3
from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    # 查找所有透视矫正相关的提示词
    prompt = db.query(models.Prompt).filter(
        models.Prompt.name == "perspective_correction",
        models.Prompt.version == "v1"
    ).first()
    
    if prompt:
        print("当前数据库中的透视矫正提示词：")
        print("="*80)
        print(f"名称：{prompt.name}")
        print(f"版本：{prompt.version}")
        print(f"描述：{prompt.description}")
        print(f"\n完整内容：")
        print(prompt.content)
        print("="*80)
    else:
        print("未找到透视矫正提示词")
    
finally:
    db.close()
