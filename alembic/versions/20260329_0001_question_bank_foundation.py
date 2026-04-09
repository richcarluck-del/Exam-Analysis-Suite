"""question bank foundation baseline

Revision ID: 20260329_0001
Revises: 
Create Date: 2026-03-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260329_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 基线迁移占位符。
    # 当前仓库已经依赖 FastAPI 启动时的 metadata.create_all，
    # 为避免直接对现有 SQLite 数据做破坏性初始迁移，这里先建立 Alembic 基线。
    # 后续可在此基础上执行 `alembic revision --autogenerate` 产出增量迁移。
    pass


def downgrade() -> None:
    pass
