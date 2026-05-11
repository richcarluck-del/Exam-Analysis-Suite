import os
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from shared.database import DATABASE_URL as PRIMARY_DATABASE_URL


@dataclass(frozen=True)
class DatabaseRuntimeState:
    mode: str
    active_url: str


def _build_engine(database_url: str):
    if not database_url.startswith(("postgresql", "postgres")):
        raise RuntimeError("测试后台仅支持 PostgreSQL 数据库连接。")

    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        "connect_args": {
            "connect_timeout": int(os.getenv("PREPROCESSOR_TEST_UI_DB_CONNECT_TIMEOUT", "3"))
        },
    }
    return create_engine(database_url, **engine_kwargs)


def _probe_database_or_raise(database_url: str) -> None:
    try:
        test_engine = _build_engine(database_url)
    except (ModuleNotFoundError, ImportError) as exc:
        raise RuntimeError(f"测试后台缺少 PostgreSQL 驱动：{exc}") from exc

    try:
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except (SQLAlchemyError, ModuleNotFoundError, ImportError) as exc:
        raise RuntimeError(f"测试后台无法连接 PostgreSQL：{exc}") from exc
    finally:
        test_engine.dispose()


_probe_database_or_raise(PRIMARY_DATABASE_URL)
RUNTIME_DB_STATE = DatabaseRuntimeState(
    mode="primary",
    active_url=PRIMARY_DATABASE_URL,
)

engine = _build_engine(RUNTIME_DB_STATE.active_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_database_runtime_state() -> DatabaseRuntimeState:
    return RUNTIME_DB_STATE


def get_database_mode_label() -> str:
    return "PostgreSQL"

