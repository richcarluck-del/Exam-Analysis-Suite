from shared.database import SessionLocal
from shared.models import Prompt

db = SessionLocal()
prompts = db.query(Prompt).filter(Prompt.name.like('extract_content%')).order_by(Prompt.name).all()

print('\n' + '=' * 80)
print(f'数据库中的提示词详情')
print('=' * 80)
for i, p in enumerate(prompts):
    print(f'\n{i+1}. {p.name}')
    print(f'   ID: {p.id}')
    print(f'   版本数：{len(p.versions)}')
    print(f'   描述：{p.description[:100]}...' if len(p.description) > 100 else f'   描述：{p.description}')
    
print('\n' + '=' * 80)
db.close()
