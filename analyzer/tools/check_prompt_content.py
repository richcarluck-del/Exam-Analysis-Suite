#!/usr/bin/env python3
from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    prompts = db.query(models.Prompt).filter(models.Prompt.name == "answer_sheet").all()
    print(f"answer_sheet 提示词共有 {len(prompts)} 个版本：")
    for p in prompts:
        print(f"\n版本：{p.version}")
        print(f"内容：{p.content[:200]}...")
finally:
    db.close()
