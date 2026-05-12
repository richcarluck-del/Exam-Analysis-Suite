"""add knowledge_point_provenance

Revision ID: 20260420_0008
Revises: 20260410_0007
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260420_0008"
down_revision = "20260410_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_point_provenance" in inspector.get_table_names():
        return

    op.create_table(
        "knowledge_point_provenance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=True),
        sa.Column("origin_step", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("extra_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["package_id"], ["knowledge_packages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_point_id",
            "source_kind",
            "source_id",
            name="uq_kp_provenance_kp_kind_source",
        ),
    )
    op.create_index("ix_kp_provenance_kp_id", "knowledge_point_provenance", ["knowledge_point_id"], unique=False)
    op.create_index("ix_kp_provenance_source", "knowledge_point_provenance", ["source_kind", "source_id"], unique=False)
    op.create_index("ix_kp_provenance_package_id", "knowledge_point_provenance", ["package_id"], unique=False)


def downgrade() -> None:
    op.drop_table("knowledge_point_provenance")
