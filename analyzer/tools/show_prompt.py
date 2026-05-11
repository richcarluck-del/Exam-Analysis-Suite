#!/usr/bin/env python3
from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    prompt = db.query(models.Prompt).filter(
        models.Prompt.name == "perspective_correction",
        models.Prompt.version == "v1"
    ).first()
    
    if prompt:
        print("="*80)
        print("透视矫正提示词（完整版）")
        print("="*80)
        print(f"名称：{prompt.name}")
        print(f"版本：{prompt.version}")
        print(f"描述：{prompt.description}")
        print(f"创建时间：{prompt.created_at}")
        print(f"最后更新：{prompt.updated_at}")
        print("\n" + "="*80)
        print("【完整提示词内容】")
        print("="*80)
        print(prompt.content)
        print("="*80)
    else:
        print("未找到提示词")
finally:
    db.close()
