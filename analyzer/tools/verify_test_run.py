from src.database import SessionLocal
from src.models import TestRun

db = SessionLocal()
test_run = db.query(TestRun).filter(TestRun.id == 22).first()
if test_run:
    print(f"api_provider: {test_run.api_provider}")
    print(f"model_name: {test_run.model_name}")
    print(f"prompt_version: {test_run.prompt_version}")
    print(f"input_dir: {test_run.input_dir}")
db.close()
