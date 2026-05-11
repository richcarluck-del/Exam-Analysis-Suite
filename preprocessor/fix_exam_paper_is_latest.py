import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from shared.database import SessionLocal
from shared.models import Prompt

print("修复试卷提示词的 is_latest 设置")
print("=" * 80)

db = SessionLocal()

try:
    # 1. 找到 exam_paper 类型中版本最高的提示词
    exam_paper_prompts = db.query(Prompt).filter(
        Prompt.pipeline_step == 4,
        Prompt.target_type == "exam_paper"
    ).all()
    
    print(f"找到 {len(exam_paper_prompts)} 个试卷提示词")
    
    # 找出版本最高的提示词
    highest_version_prompt = None
    highest_version = 0
    
    for p in exam_paper_prompts:
        if p.versions:
            max_version = max([v.version for v in p.versions])
            if max_version > highest_version:
                highest_version = max_version
                highest_version_prompt = p
    
    if highest_version_prompt:
        print(f"\n版本最高的试卷提示词: {highest_version_prompt.name} (v{highest_version})")
        print(f"当前 is_latest: {highest_version_prompt.is_latest}")
        
        # 2. 先把所有 exam_paper 提示词的 is_latest 设为 False
        for p in exam_paper_prompts:
            if p.is_latest:
                print(f"  将 {p.name} 的 is_latest 从 True 改为 False")
                p.is_latest = False
        
        # 3. 把版本最高的提示词的 is_latest 设为 True
        highest_version_prompt.is_latest = True
        print(f"  将 {highest_version_prompt.name} 的 is_latest 设为 True")
        
        # 提交更改
        db.commit()
        print(f"\n✅ 数据库已更新！")
        
        # 验证更改
        db.refresh(highest_version_prompt)
        print(f"验证: {highest_version_prompt.name} 的 is_latest = {highest_version_prompt.is_latest}")
    else:
        print("❌ 没有找到试卷提示词")
        
except Exception as e:
    print(f"❌ 更新数据库时出错: {e}")
    db.rollback()
finally:
    db.close()

print("\n" + "="*80)
print("验证修复结果")
print("="*80)

# 重新查询验证
db = SessionLocal()
exam_paper_prompts = db.query(Prompt).filter(
    Prompt.pipeline_step == 4,
    Prompt.target_type == "exam_paper",
    Prompt.is_latest == True
).all()

print(f"is_latest=True 的试卷提示词数量: {len(exam_paper_prompts)}")
for p in exam_paper_prompts:
    print(f"  - {p.name}, is_latest={p.is_latest}")

db.close()