#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查透视矫正提示词的所有版本"""

from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    # 查找所有透视矫正相关的提示词
    prompts = db.query(models.Prompt).filter(
        models.Prompt.name.like("%perspective%")
    ).order_by(models.Prompt.version).all()
    
    print(f"数据库中有 {len(prompts)} 个透视矫正提示词：\n")
    
    for p in prompts:
        print("="*80)
        print(f"ID: {p.id}")
        print(f"名称：{p.name}")
        print(f"版本：{p.version}")
        print(f"描述：{p.description}")
        print(f"创建时间：{p.created_at}")
        print(f"更新时间：{p.updated_at}")
        print(f"\n提示词内容（前 300 字符）：")
        print(p.content[:300] + "..." if len(p.content) > 300 else p.content)
        print("="*80)
        print()
    
    # 同时检查代码中是否有硬编码的提示词
    print("\n" + "="*80)
    print("检查代码中的硬编码提示词...")
    print("="*80)
    
    import os
    import re
    
    # 搜索 task_perspective_correction.py 文件
    task_file = "src/tasks/task_perspective_correction.py"
    if os.path.exists(task_file):
        with open(task_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # 查找 prompt 赋值
            prompt_matches = re.findall(r'self\.prompt\s*=\s*"""(.*?)"""', content, re.DOTALL)
            if prompt_matches:
                print(f"\n在 {task_file} 中找到 {len(prompt_matches)} 个硬编码提示词：")
                for i, match in enumerate(prompt_matches, 1):
                    print(f"\n提示词 {i}:")
                    print(match[:200] + "..." if len(match) > 200 else match)
            else:
                print(f"\n在 {task_file} 中未找到硬编码的提示词")
    
finally:
    db.close()
