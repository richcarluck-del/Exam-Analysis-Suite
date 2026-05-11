from src.database import SessionLocal
from src.models import TestRun

db = SessionLocal()
test_run = db.query(TestRun).filter(TestRun.id == 20).first()
if test_run:
    print(test_run.output_dir)
db.close()
