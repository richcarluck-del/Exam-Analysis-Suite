#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化数据库表（添加实验区相关表）"""

from src.database import engine, Base
from src import models

print("创建数据库表...")

# 创建所有表
Base.metadata.create_all(bind=engine)

print("✅ 数据库表创建成功！")

# 验证表是否存在
from src.database import SessionLocal
from sqlalchemy import inspect

db = SessionLocal()
try:
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()
    print(f"\n数据库中共有 {len(tables)} 个表：")
    for table in tables:
        print(f"  - {table}")
    
    # 检查实验区表
    if 'prompt_lab' in tables:
        print("\n✅ 实验区提示词表 (prompt_lab) 已创建")
    else:
        print("\n❌ 实验区提示词表未创建")
    
    if 'prompt_lab_tests' in tables:
        print("✅ 实验区测试记录表 (prompt_lab_tests) 已创建")
    else:
        print("❌ 实验区测试记录表未创建")
        
finally:
    db.close()
