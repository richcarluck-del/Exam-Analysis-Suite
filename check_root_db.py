import os
import sys
from sqlalchemy import create_engine, inspect, text

# 检查项目根目录下的数据库
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
db_path = os.path.join(project_root, 'exam_analysis.db')
print(f"检查数据库：{db_path}")
print(f"文件存在：{os.path.exists(db_path)}")

engine = create_engine(f'sqlite:///{db_path}')
inspector = inspect(engine)
tables = inspector.get_table_names()
print(f'\n表数量：{len(tables)}')
for t in tables:
    print(f'  - {t}')

# 检查 api_providers 表
from sqlalchemy.orm import sessionmaker
Session = sessionmaker(bind=engine)
session = Session()

print("\n=== API Providers ===")
providers = session.execute(text('SELECT * FROM api_providers')).fetchall()
for p in providers:
    print(p)

print("\n=== LLM Models ===")
models = session.execute(text('SELECT * FROM llm_models')).fetchall()
for m in models:
    print(m)

session.close()
