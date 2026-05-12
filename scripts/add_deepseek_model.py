"""Add DeepSeek provider/model to database and bind to topic_docx_block_points step."""
import sys
sys.path.insert(0, r"D:\10739\Exam-Analysis-Suite")

from analyzer.app.security import encrypt_api_key
from shared.database import SessionLocal
from shared.models import APIProvider, LLMModel, LLMStepConfig

PROVIDER_NAME = "deepseek"
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = "sk-77f228b8691a458a853a36d632887c8a"
MODEL_NAME = "deepseek-v4-pro"
STEP_KEY = "analyzer.topic_docx_block_points"

db = SessionLocal()
try:
    # 1. Create or get the provider
    provider = db.query(APIProvider).filter(APIProvider.name == PROVIDER_NAME).first()
    if not provider:
        provider = APIProvider(
            name=PROVIDER_NAME,
            api_url=API_URL,
            encrypted_api_key=encrypt_api_key(API_KEY),
        )
        db.add(provider)
        db.flush()
        print(f"[OK] Created provider: {PROVIDER_NAME} (id={provider.id})")
    else:
        provider.api_url = API_URL
        provider.encrypted_api_key = encrypt_api_key(API_KEY)
        db.add(provider)
        db.flush()
        print(f"[OK] Updated provider: {PROVIDER_NAME} (id={provider.id})")

    # 2. Create or get the model
    model = (
        db.query(LLMModel)
        .filter(LLMModel.name == MODEL_NAME, LLMModel.provider_id == provider.id)
        .first()
    )
    if not model:
        model = LLMModel(name=MODEL_NAME, provider_id=provider.id)
        db.add(model)
        db.flush()
        print(f"[OK] Created model: {MODEL_NAME} (id={model.id})")
    else:
        print(f"[OK] Model already exists: {MODEL_NAME} (id={model.id})")

    # 3. Bind the step config to this model
    step_config = db.query(LLMStepConfig).filter(LLMStepConfig.step_key == STEP_KEY).first()
    if step_config:
        step_config.provider_id = provider.id
        step_config.model_id = model.id
        print(f"[OK] Bound {STEP_KEY} → {PROVIDER_NAME}/{MODEL_NAME}")
    else:
        print("[WARN] LLMStepConfig for {STEP_KEY} not found — will be created by sync_llm_step_configs")

    db.commit()
    print("[DONE] All changes committed.")

finally:
    db.close()
