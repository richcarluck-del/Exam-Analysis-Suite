from pathlib import Path
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_PREFIXES = ("postgresql://", "postgresql+", "postgres://", "postgres+")


def _is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(POSTGRES_PREFIXES)


def resolve_database_url() -> str:
    configured_url = (os.getenv("DATABASE_URL") or "").strip()
    if not configured_url:
        raise RuntimeError("必须通过 DATABASE_URL 配置 PostgreSQL 连接，项目已不再支持 SQLite。")
    if not _is_postgres_url(configured_url):
        scheme = configured_url.split("://", 1)[0] if "://" in configured_url else configured_url
        raise RuntimeError(f"DATABASE_URL 必须指向 PostgreSQL，当前配置为：{scheme}")
    return configured_url


def build_engine_kwargs(database_url: str) -> dict:
    if not _is_postgres_url(database_url):
        raise RuntimeError("当前项目仅支持 PostgreSQL 数据库连接。")

    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
    }
    connect_timeout = os.getenv("DB_CONNECT_TIMEOUT")
    if connect_timeout:
        engine_kwargs["connect_args"] = {"connect_timeout": int(connect_timeout)}
    return engine_kwargs


DATABASE_URL = resolve_database_url()
engine = create_engine(DATABASE_URL, **build_engine_kwargs(DATABASE_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

