#!/usr/bin/env python3
"""
测试修复后的版本查询
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from preprocessor.src.prompt_manager import prompt_manager

print("测试修复后的版本查询")
print("=" * 80)

# 测试获取 v8 版本的答题纸提示词
print("\n测试获取 v8 版本的答题纸提示词:")
prompt_v8 = prompt_manager.get_prompt(step=4, target_type="answer_sheet", version=8)

if prompt_v8:
    print(f"✅ 成功获取 v8 版本答题纸提示词")
    print(f"   长度: {len(prompt_v8)} 字符")
    print(f"   前100字符: {prompt_v8[:100]}...")
else:
    print("❌ 获取 v8 版本答题纸提示词失败")

# 测试获取 v10 版本的答题纸提示词
print("\n测试获取 v10 版本的答题纸提示词:")
prompt_v10 = prompt_manager.get_prompt(step=4, target_type="answer_sheet", version=10)

if prompt_v10:
    print(f"✅ 成功获取 v10 版本答题纸提示词")
    print(f"   长度: {len(prompt_v10)} 字符")
    print(f"   前100字符: {prompt_v10[:100]}...")
else:
    print("❌ 获取 v10 版本答题纸提示词失败")

# 测试获取最新版本的答题纸提示词
print("\n测试获取最新版本的答题纸提示词:")
prompt_latest = prompt_manager.get_prompt(step=4, target_type="answer_sheet", version="latest")

if prompt_latest:
    print(f"✅ 成功获取最新版本答题纸提示词")
    print(f"   长度: {len(prompt_latest)} 字符")
    print(f"   前100字符: {prompt_latest[:100]}...")
else:
    print("❌ 获取最新版本答题纸提示词失败")

# 测试获取 v8 版本的试卷提示词
print("\n测试获取 v8 版本的试卷提示词:")
exam_prompt_v8 = prompt_manager.get_prompt(step=4, target_type="exam_paper", version=8)

if exam_prompt_v8:
    print(f"✅ 成功获取 v8 版本试卷提示词")
    print(f"   长度: {len(exam_prompt_v8)} 字符")
else:
    print("❌ 获取 v8 版本试卷提示词失败")

prompt_manager.close_db_session()

print("\n" + "=" * 80)
print("测试完成")