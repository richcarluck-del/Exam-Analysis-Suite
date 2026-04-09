"""add llm step configs table

Revision ID: 20260330_0004
Revises: 20260330_0003
Create Date: 2026-03-30 15:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260330_0004"
down_revision = "20260330_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_step_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=100), nullable=False),
        sa.Column("step_label", sa.String(length=255), nullable=False),
        sa.Column("module_name", sa.String(length=64), nullable=False),
        sa.Column("step_order", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["provider_id"], ["api_providers.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["llm_models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_key", name="uq_llm_step_configs_step_key"),
    )
    op.create_index(op.f("ix_llm_step_configs_id"), "llm_step_configs", ["id"], unique=False)
    op.create_index(op.f("ix_llm_step_configs_step_key"), "llm_step_configs", ["step_key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_step_configs_step_key"), table_name="llm_step_configs")
    op.drop_index(op.f("ix_llm_step_configs_id"), table_name="llm_step_configs")
    op.drop_table("llm_step_configs")
