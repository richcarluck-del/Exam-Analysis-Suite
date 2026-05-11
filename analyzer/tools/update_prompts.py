#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新提示词名称"""

from src.database import SessionLocal
from src import crud, schemas, models

db = SessionLocal()
try:
    # 删除旧提示词
    prompts = db.query(models.Prompt).filter(models.Prompt.name == "exam_analysis").all()
    for p in prompts:
        db.delete(p)
    db.commit()
    print(f"✅ 已删除 {len(prompts)} 个旧提示词")
    
    # 创建新提示词
    for v in ['v1', 'v2', 'v3', 'v4', 'v5']:
        prompt = schemas.PromptCreate(
            name="answer_sheet",
            version=v,
            system_prompt=f"试卷分析助手 v{v}",
            user_prompt_template="请分析这张试卷",
            content=f"提示词内容 v{v}"
        )
        crud.create_prompt(db, prompt)
        print(f"✅ 创建提示词：answer_sheet/{v}")
    
    print("\n✅ 提示词更新完成！")
    
finally:
    db.close()
