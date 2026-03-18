from shared.database import SessionLocal
from shared.models import Prompt

db = SessionLocal()
prompts = db.query(Prompt).filter(Prompt.name.like('extract_content%')).order_by(Prompt.name).all()

print('=' * 60)
print(f'数据库中共有 {len(prompts)} 个 extract_content 提示词')
print('=' * 60)
for i, p in enumerate(prompts):
    print(f'{i+1}. {p.name} (ID={p.id}, 版本={len(p.versions)})')
db.close()
print('=' * 60)
