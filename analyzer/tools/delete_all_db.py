#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删除所有数据库文件"""

import os
import glob
import time

print("删除所有数据库相关文件...")

# 等待几秒确保文件被释放
time.sleep(2)

# 删除所有 exam_analysis*.db 文件
for pattern in ['exam_analysis*.db', 'exam_analysis*.db-wal', 'exam_analysis*.db-shm', 'exam_analysis*.db-journal']:
    files = glob.glob(pattern)
    for file in files:
        try:
            os.remove(file)
            print(f"✅ 已删除：{file}")
        except Exception as e:
            print(f"❌ 无法删除 {file}: {e}")

print("\n数据库文件清理完成！")
