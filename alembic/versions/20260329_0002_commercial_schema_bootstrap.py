"""commercial schema bootstrap

Revision ID: 20260329_0002
Revises: 20260329_0001
Create Date: 2026-03-29 21:00:00
"""

from alembic import op

from shared import models

revision = "20260329_0002"
down_revision = "20260329_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    models.Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    models.Base.metadata.drop_all(bind=bind, checkfirst=True)
