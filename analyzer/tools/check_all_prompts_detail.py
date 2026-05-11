#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查数据库中所有提示词及其版本"""

from src.database import SessionLocal
from src import models

db = SessionLocal()
try:
    # 查询所有提示词
    prompts = db.query(models.Prompt).order_by(models.Prompt.name, models.Prompt.version).all()
    
    print(f"数据库中共有 {len(prompts)} 个提示词：\n")
    print("="*80)
    
    # 按名称分组
    from collections import defaultdict
    grouped = defaultdict(list)
    for p in prompts:
        grouped[p.name].append(p)
    
    for name, prompt_list in grouped.items():
        print(f"\n【{name}】")
        print(f"版本数量：{len(prompt_list)}")
        print("-"*80)
        
        for p in prompt_list:
            print(f"  版本：{p.version}")
            print(f"  描述：{p.description}")
            print(f"  内容长度：{len(p.content)} 字符")
            print(f"  创建时间：{p.created_at}")
            print()
    
    print("="*80)
    print("\n总结：")
    print("-"*80)
    for name, prompt_list in grouped.items():
        versions = [p.version for p in prompt_list]
        print(f"  {name}: {len(prompt_list)} 个版本 - {', '.join(versions)}")
    
finally:
    db.close()
