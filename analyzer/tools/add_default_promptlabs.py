#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""添加默认实验区提示词数据"""

from src.database import SessionLocal
from src import crud, schemas, models

db = SessionLocal()
try:
    # 检查是否已有数据
    existing = db.query(models.PromptLab).count()
    if existing > 0:
        print(f"数据库中已有 {existing} 个实验区提示词")
        response = input("是否继续添加默认提示词？(y/n): ")
        if response.lower() != 'y':
            print("已取消")
            exit(0)
    
    # 默认提示词列表
    default_prompts = [
        {
            "name": "通用解题助手",
            "content": """你是一个专业的解题助手。请仔细阅读题目，给出详细的解题步骤和最终答案。

要求：
1. 先分析题目要求
2. 列出解题思路
3. 给出详细步骤
4. 总结最终答案

请用清晰的格式输出。""",
            "description": "适用于各类题目的通用解题提示词",
            "tags": "通用，解题，教育"
        },
        {
            "name": "数学题解答",
            "content": """你是一个数学老师。请解答这道数学题。

要求：
1. 分析已知条件和求解目标
2. 选择合适的解题方法
3. 逐步推导，展示计算过程
4. 验证答案的合理性
5. 给出最终答案

如果是几何题，请说明用到的定理和公式。
如果是代数题，请展示每一步的变形过程。""",
            "description": "专门用于数学题目解答",
            "tags": "数学，代数，几何"
        },
        {
            "name": "物理题解答",
            "content": """你是一个物理老师。请解答这道物理题。

要求：
1. 分析物理过程和已知条件
2. 列出适用的物理定律和公式
3. 建立物理模型
4. 进行计算推导
5. 讨论结果的物理意义
6. 给出最终答案

注意单位的统一和换算。""",
            "description": "专门用于物理题目解答",
            "tags": "物理，力学，电磁学"
        },
        {
            "name": "英语作文批改",
            "content": """你是一个英语老师。请批改这篇英语作文。

请从以下几个方面进行评价：
1. 语法准确性（指出错误并改正）
2. 词汇使用（评价词汇丰富度和准确性）
3. 句子结构（评价句式多样性）
4. 逻辑连贯性（评价段落组织和衔接）
5. 内容完整性（评价是否切题）

最后给出总体评价和修改建议，并给出一个分数（0-100）。""",
            "description": "用于英语作文批改和评价",
            "tags": "英语，作文，批改"
        },
        {
            "name": "图片内容描述",
            "content": """请详细描述这张图片的内容。

要求：
1. 描述图片中的主要元素
2. 说明各元素的位置关系
3. 识别图片中的文字（如果有）
4. 分析图片的场景和用途
5. 指出任何特殊或值得注意的细节

请用清晰、准确的语言描述。""",
            "description": "用于识别和描述图片内容",
            "tags": "图片识别，OCR，描述"
        }
    ]
    
    # 添加提示词
    for prompt_data in default_prompts:
        # 检查是否已存在
        existing = db.query(models.PromptLab).filter(
            models.PromptLab.name == prompt_data["name"]
        ).first()
        
        if existing:
            print(f"⚠️  提示词 '{prompt_data['name']}' 已存在，跳过")
            continue
        
        prompt = schemas.PromptLabCreate(**prompt_data)
        crud.create_prompt_lab(db, prompt)
        print(f"✅ 已添加提示词：{prompt_data['name']}")
    
    db.commit()
    
    # 统计结果
    total = db.query(models.PromptLab).count()
    print(f"\n✅ 完成！数据库中共有 {total} 个实验区提示词")
    
finally:
    db.close()
