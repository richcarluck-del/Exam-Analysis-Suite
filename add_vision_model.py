import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from shared.database import SessionLocal
from shared import models
from analyzer.app import crud, schemas

db = SessionLocal()

try:
    # 查找 dashscope provider
    provider = db.query(models.APIProvider).filter(models.APIProvider.name == 'dashscope').first()
    if not provider:
        print("Error: dashscope provider not found")
        sys.exit(1)
    
    print(f"Found provider: {provider.name} (id={provider.id})")
    
    # 检查是否已存在
    existing = db.query(models.LLMModel).filter(
        models.LLMModel.name == 'qwen-vl-max',
        models.LLMModel.provider_id == provider.id
    ).first()
    
    if existing:
        print("Model qwen-vl-max already exists")
    else:
        new_model = models.LLMModel(
            name='qwen-vl-max',
            provider_id=provider.id
        )
        db.add(new_model)
        db.commit()
        print("✅ Added qwen-vl-max model to database")
    
    # 列出所有模型
    all_models = db.query(models.LLMModel).filter(models.LLMModel.provider_id == provider.id).all()
    print("\nAll models for dashscope:")
    for m in all_models:
        print(f"  - {m.name}")
    
finally:
    db.close()
