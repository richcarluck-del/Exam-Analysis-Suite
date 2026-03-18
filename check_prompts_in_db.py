from shared.database import SessionLocal
from shared.models import Prompt

db = SessionLocal()
prompts = db.query(Prompt).filter(Prompt.name.like('extract_content%')).order_by(Prompt.name).all()

print(f'\n数据库中共有 {len(prompts)} 个 extract_content 提示词:\n')
for i, p in enumerate(prompts):
    print(f'  {i+1}. {p.name}')
    print(f'     ID: {p.id}')
    print(f'     版本数：{len(p.versions)}')
    print(f'     描述：{p.description}')
    print()

db.close()
