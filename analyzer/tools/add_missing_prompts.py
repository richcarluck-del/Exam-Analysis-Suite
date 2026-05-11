#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""添加缺失的提示词版本"""

from src.database import SessionLocal
from src import crud, schemas, models

db = SessionLocal()
try:
    # 检查现有版本
    existing = db.query(models.Prompt).filter(models.Prompt.name == "answer_sheet").all()
    existing_versions = [p.version for p in existing]
    print(f"现有版本：{existing_versions}")
    
    # 添加缺失的版本
    for v in ['v1', 'v2', 'v3', 'v4', 'v5']:
        if v not in existing_versions:
            prompt = schemas.PromptCreate(
                name="answer_sheet",
                version=v,
                system_prompt=f"试卷分析助手 v{v}",
                user_prompt_template="请分析这张试卷",
                content=f"提示词内容 v{v}"
            )
            crud.create_prompt(db, prompt)
            print(f"✅ 创建提示词：answer_sheet/{v}")
        else:
            print(f"✓ 已存在：answer_sheet/{v}")
    
    print("\n✅ 提示词版本检查完成！")
    
finally:
    db.close()
