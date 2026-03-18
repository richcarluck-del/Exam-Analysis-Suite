from shared.database import SessionLocal
from shared.models import Prompt

db = SessionLocal()

# 只查询 V6 和 V7
v6 = db.query(Prompt).filter(Prompt.name == 'extract_content_v6').first()
v7 = db.query(Prompt).filter(Prompt.name == 'extract_content_v7').first()

print('=' * 80)
print('V6 提示词内容（前 500 字符）:')
print('=' * 80)
if v6 and v6.versions:
    print(v6.versions[0].prompt_text[:500])
    print('...(省略)')
    print(f'\n总长度：{len(v6.versions[0].prompt_text)} 字符')

print('\n' + '=' * 80)
print('V7 提示词内容（前 500 字符）:')
print('=' * 80)
if v7 and v7.versions:
    print(v7.versions[0].prompt_text[:500])
    print('...(省略)')
    print(f'\n总长度：{len(v7.versions[0].prompt_text)} 字符')

db.close()
