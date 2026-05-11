#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新数据库中的提示词内容"""

from src.database import SessionLocal
from src import crud, schemas, models
from src.prompts import PROMPTS

db = SessionLocal()
try:
    # 更新每个版本的提示词
    for version in ['v1', 'v2', 'v3', 'v4', 'v5']:
        prompt_data = PROMPTS.get(version, {})
        
        # 获取 answer_sheet 提示词
        answer_sheet_prompt = prompt_data.get('answer_sheet', '')
        
        if answer_sheet_prompt:
            # 查找现有提示词
            existing = db.query(models.Prompt).filter(
                models.Prompt.name == "answer_sheet",
                models.Prompt.version == version
            ).first()
            
            if existing:
                # 更新内容
                existing.content = answer_sheet_prompt
                existing.system_prompt = f"答题纸分析助手 {version}"
                existing.user_prompt_template = "请分析这张答题纸图片"
                print(f"✅ 已更新 answer_sheet/{version}")
            else:
                # 创建新提示词
                prompt = schemas.PromptCreate(
                    name="answer_sheet",
                    version=version,
                    system_prompt=f"答题纸分析助手 {version}",
                    user_prompt_template="请分析这张答题纸图片",
                    content=answer_sheet_prompt
                )
                crud.create_prompt(db, prompt)
                print(f"✅ 已创建 answer_sheet/{version}")
    
    db.commit()
    print("\n✅ 提示词更新完成！")
    
finally:
    db.close()
