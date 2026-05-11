from celery import Celery
from .config import REDIS_URL

celery_app = Celery(
    "tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["analyzer.app.tasks"]
)

celery_app.conf.update(
    task_track_started=True,
)
