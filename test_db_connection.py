from shared.database import SessionLocal
from shared.models import Prompt, PromptVersion

db = SessionLocal()
print('✓ 数据库连接成功')

# 查询现有数据
prompts = db.query(Prompt).all()
print(f'✓ 现有 Prompt 数量：{len(prompts)}')

versions = db.query(PromptVersion).all()
print(f'✓ 现有 PromptVersion 数量：{len(versions)}')

# 显示前几个 Prompt
print('\n前 5 个 Prompt:')
for p in prompts[:5]:
    print(f'  - {p.name} (ID={p.id}, versions={len(p.versions)})')

db.close()
print('\n✓ 测试完成')
