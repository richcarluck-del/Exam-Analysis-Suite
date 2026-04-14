"""topic package question links and paper.topic package fk

Revision ID: 20260410_0007
Revises: 20260409_0006
Create Date: 2026-04-10 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260410_0007"
down_revision = "20260409_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "knowledge_package_questions" not in tables:
        op.create_table(
            "knowledge_package_questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("package_id", sa.Integer(), nullable=False),
            sa.Column("question_item_id", sa.Integer(), nullable=False),
            sa.Column("display_order", sa.Integer(), nullable=True),
            sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="topic_material"),
            sa.Column("context_json", sa.JSON(), nullable=True),
            sa.Column("source_block_id", sa.Integer(), nullable=True),
            sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="model"),
            sa.Column("confidence", sa.Numeric(precision=4, scale=2), nullable=True),
            sa.Column("approved_status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["package_id"], ["knowledge_packages.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["question_item_id"], ["question_items.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_block_id"], ["knowledge_blocks.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("package_id", "question_item_id", name="uq_knowledge_package_question_pair"),
        )
        op.create_index("ix_knowledge_package_questions_id", "knowledge_package_questions", ["id"], unique=False)
        op.create_index("ix_knowledge_package_questions_package_id", "knowledge_package_questions", ["package_id"], unique=False)
        op.create_index("ix_knowledge_package_questions_question_item_id", "knowledge_package_questions", ["question_item_id"], unique=False)

    cols = {c["name"] for c in inspector.get_columns("papers")} if "papers" in tables else set()
    if "papers" in tables and "knowledge_package_id" not in cols:
        op.add_column(
            "papers",
            sa.Column("knowledge_package_id", sa.Integer(), nullable=True),
        )
        op.create_index("ix_papers_knowledge_package_id", "papers", ["knowledge_package_id"], unique=False)
        op.create_foreign_key(
            "fk_papers_knowledge_package_id",
            "papers",
            "knowledge_packages",
            ["knowledge_package_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    cols = {c["name"] for c in inspector.get_columns("papers")} if "papers" in tables else set()
    if "papers" in tables and "knowledge_package_id" in cols:
        op.drop_constraint("fk_papers_knowledge_package_id", "papers", type_="foreignkey")
        op.drop_index("ix_papers_knowledge_package_id", table_name="papers")
        op.drop_column("papers", "knowledge_package_id")

    if "knowledge_package_questions" in tables:
        op.drop_table("knowledge_package_questions")
