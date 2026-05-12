"""add bundle_dir to exam_sessions

Revision ID: 20260428_0009
Revises: 20260420_0008
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260428_0009"
down_revision = "20260420_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [c["name"] for c in inspector.get_columns("exam_sessions")]
    if "bundle_dir" not in columns:
        op.add_column("exam_sessions", sa.Column("bundle_dir", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = [c["name"] for c in inspector.get_columns("exam_sessions")]
    if "bundle_dir" in columns:
        with op.batch_alter_table("exam_sessions") as batch_op:
            batch_op.drop_column("bundle_dir")