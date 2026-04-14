"""add knowledge point foundation

Revision ID: 20260409_0006
Revises: 20260331_0005
Create Date: 2026-04-09 12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260409_0006"
down_revision = "20260331_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_points" in inspector.get_table_names():
        return

    op.create_table(

        "knowledge_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("primary_taxonomy_node_id", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(length=32), nullable=True),
        sa.Column("grade_scope", sa.String(length=64), nullable=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=True),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False, server_default="concept"),
        sa.Column("importance_level", sa.Integer(), nullable=True),
        sa.Column("difficulty_band", sa.String(length=16), nullable=True),
        sa.Column("exam_frequency", sa.Integer(), nullable=True),
        sa.Column("canonical_summary", sa.Text(), nullable=True),
        sa.Column("learning_objectives_json", sa.JSON(), nullable=True),
        sa.Column("prerequisite_summary", sa.Text(), nullable=True),
        sa.Column("common_confusions_json", sa.JSON(), nullable=True),
        sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="explicit"),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),

        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["primary_taxonomy_node_id"], ["taxonomy_nodes.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_points_id"), "knowledge_points", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_points_tenant_id"), "knowledge_points", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_knowledge_points_primary_taxonomy_node_id"), "knowledge_points", ["primary_taxonomy_node_id"], unique=False)
    op.create_index(op.f("ix_knowledge_points_subject"), "knowledge_points", ["subject"], unique=False)
    op.create_index(op.f("ix_knowledge_points_canonical_name"), "knowledge_points", ["canonical_name"], unique=False)
    op.create_index(op.f("ix_knowledge_points_review_status"), "knowledge_points", ["review_status"], unique=False)
    op.create_index(op.f("ix_knowledge_points_is_active"), "knowledge_points", ["is_active"], unique=False)

    op.create_table(
        "knowledge_packages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("package_title", sa.String(length=255), nullable=False),
        sa.Column("package_type", sa.String(length=32), nullable=False, server_default="topic"),
        sa.Column("subject", sa.String(length=32), nullable=True),
        sa.Column("grade", sa.String(length=32), nullable=True),
        sa.Column("page_range_json", sa.JSON(), nullable=True),
        sa.Column("outline_json", sa.JSON(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_packages_id"), "knowledge_packages", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_packages_source_document_id"), "knowledge_packages", ["source_document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_packages_tenant_id"), "knowledge_packages", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_knowledge_packages_package_title"), "knowledge_packages", ["package_title"], unique=False)
    op.create_index(op.f("ix_knowledge_packages_subject"), "knowledge_packages", ["subject"], unique=False)
    op.create_index(op.f("ix_knowledge_packages_parse_status"), "knowledge_packages", ["parse_status"], unique=False)
    op.create_index(op.f("ix_knowledge_packages_review_status"), "knowledge_packages", ["review_status"], unique=False)

    op.create_table(
        "knowledge_package_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="core"),
        sa.Column("weight_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("order_in_package", sa.Integer(), nullable=True),
        sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="explicit"),
        sa.Column("confidence", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("approved_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["knowledge_packages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_package_points_id"), "knowledge_package_points", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_package_points_package_id"), "knowledge_package_points", ["package_id"], unique=False)
    op.create_index(op.f("ix_knowledge_package_points_knowledge_point_id"), "knowledge_package_points", ["knowledge_point_id"], unique=False)

    op.create_table(
        "knowledge_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=True),
        sa.Column("parent_block_id", sa.Integer(), nullable=True),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("block_role", sa.String(length=32), nullable=False),
        sa.Column("content_format", sa.String(length=32), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("rich_content_json", sa.JSON(), nullable=True),
        sa.Column("source_page_no", sa.Integer(), nullable=True),
        sa.Column("anchor_bbox_json", sa.JSON(), nullable=True),
        sa.Column("source_anchor_json", sa.JSON(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="explicit"),
        sa.Column("confidence", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),

        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["knowledge_packages.id"]),
        sa.ForeignKeyConstraint(["parent_block_id"], ["knowledge_blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_blocks_id"), "knowledge_blocks", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_blocks_package_id"), "knowledge_blocks", ["package_id"], unique=False)
    op.create_index(op.f("ix_knowledge_blocks_knowledge_point_id"), "knowledge_blocks", ["knowledge_point_id"], unique=False)
    op.create_index(op.f("ix_knowledge_blocks_parent_block_id"), "knowledge_blocks", ["parent_block_id"], unique=False)
    op.create_index(op.f("ix_knowledge_blocks_block_role"), "knowledge_blocks", ["block_role"], unique=False)
    op.create_index(op.f("ix_knowledge_blocks_source_page_no"), "knowledge_blocks", ["source_page_no"], unique=False)
    op.create_index(op.f("ix_knowledge_blocks_asset_id"), "knowledge_blocks", ["asset_id"], unique=False)

    op.create_table(
        "knowledge_atoms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=True),
        sa.Column("atom_type", sa.String(length=32), nullable=False),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=True),
        sa.Column("formula_signature", sa.Text(), nullable=True),
        sa.Column("importance_level", sa.Integer(), nullable=True),
        sa.Column("difficulty_band", sa.String(length=16), nullable=True),
        sa.Column("evidence_block_id", sa.Integer(), nullable=True),
        sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="explicit"),
        sa.Column("confidence", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["evidence_block_id"], ["knowledge_blocks.id"]),
        sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["knowledge_packages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_atoms_id"), "knowledge_atoms", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_atoms_knowledge_point_id"), "knowledge_atoms", ["knowledge_point_id"], unique=False)
    op.create_index(op.f("ix_knowledge_atoms_package_id"), "knowledge_atoms", ["package_id"], unique=False)
    op.create_index(op.f("ix_knowledge_atoms_atom_type"), "knowledge_atoms", ["atom_type"], unique=False)
    op.create_index(op.f("ix_knowledge_atoms_evidence_block_id"), "knowledge_atoms", ["evidence_block_id"], unique=False)
    op.create_index(op.f("ix_knowledge_atoms_review_status"), "knowledge_atoms", ["review_status"], unique=False)

    op.create_table(
        "knowledge_question_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("question_item_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("relevance_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("entry_point_text", sa.Text(), nullable=True),
        sa.Column("explanation_block_id", sa.Integer(), nullable=True),
        sa.Column("commentary_block_id", sa.Integer(), nullable=True),
        sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="explicit"),
        sa.Column("confidence", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("approved_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["commentary_block_id"], ["knowledge_blocks.id"]),
        sa.ForeignKeyConstraint(["explanation_block_id"], ["knowledge_blocks.id"]),
        sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]),
        sa.ForeignKeyConstraint(["question_item_id"], ["question_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_question_links_id"), "knowledge_question_links", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_question_links_knowledge_point_id"), "knowledge_question_links", ["knowledge_point_id"], unique=False)
    op.create_index(op.f("ix_knowledge_question_links_question_item_id"), "knowledge_question_links", ["question_item_id"], unique=False)
    op.create_index(op.f("ix_knowledge_question_links_relation_type"), "knowledge_question_links", ["relation_type"], unique=False)
    op.create_index(op.f("ix_knowledge_question_links_explanation_block_id"), "knowledge_question_links", ["explanation_block_id"], unique=False)
    op.create_index(op.f("ix_knowledge_question_links_commentary_block_id"), "knowledge_question_links", ["commentary_block_id"], unique=False)

    op.create_table(
        "knowledge_point_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("target_knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("strength_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("evidence_block_id", sa.Integer(), nullable=True),
        sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="explicit"),
        sa.Column("confidence", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("approved_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["evidence_block_id"], ["knowledge_blocks.id"]),
        sa.ForeignKeyConstraint(["source_knowledge_point_id"], ["knowledge_points.id"]),
        sa.ForeignKeyConstraint(["target_knowledge_point_id"], ["knowledge_points.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_point_relations_id"), "knowledge_point_relations", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_point_relations_source_knowledge_point_id"), "knowledge_point_relations", ["source_knowledge_point_id"], unique=False)
    op.create_index(op.f("ix_knowledge_point_relations_target_knowledge_point_id"), "knowledge_point_relations", ["target_knowledge_point_id"], unique=False)
    op.create_index(op.f("ix_knowledge_point_relations_relation_type"), "knowledge_point_relations", ["relation_type"], unique=False)
    op.create_index(op.f("ix_knowledge_point_relations_evidence_block_id"), "knowledge_point_relations", ["evidence_block_id"], unique=False)

    op.create_table(
        "entity_graph_edges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_entity_type", sa.String(length=32), nullable=False),
        sa.Column("source_entity_id", sa.Integer(), nullable=False),
        sa.Column("target_entity_type", sa.String(length=32), nullable=False),
        sa.Column("target_entity_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("weight_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("source_origin", sa.String(length=32), nullable=False, server_default="explicit"),
        sa.Column("confidence", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_entity_graph_edges_id"), "entity_graph_edges", ["id"], unique=False)
    op.create_index(op.f("ix_entity_graph_edges_source_entity_type"), "entity_graph_edges", ["source_entity_type"], unique=False)
    op.create_index(op.f("ix_entity_graph_edges_source_entity_id"), "entity_graph_edges", ["source_entity_id"], unique=False)
    op.create_index(op.f("ix_entity_graph_edges_target_entity_type"), "entity_graph_edges", ["target_entity_type"], unique=False)
    op.create_index(op.f("ix_entity_graph_edges_target_entity_id"), "entity_graph_edges", ["target_entity_id"], unique=False)
    op.create_index(op.f("ix_entity_graph_edges_relation_type"), "entity_graph_edges", ["relation_type"], unique=False)

    op.create_table(
        "knowledge_derivatives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
        sa.Column("derivative_type", sa.String(length=32), nullable=False),
        sa.Column("target_audience", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("source_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("generated_content", sa.JSON(), nullable=True),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_derivatives_id"), "knowledge_derivatives", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_derivatives_knowledge_point_id"), "knowledge_derivatives", ["knowledge_point_id"], unique=False)
    op.create_index(op.f("ix_knowledge_derivatives_derivative_type"), "knowledge_derivatives", ["derivative_type"], unique=False)
    op.create_index(op.f("ix_knowledge_derivatives_target_audience"), "knowledge_derivatives", ["target_audience"], unique=False)
    op.create_index(op.f("ix_knowledge_derivatives_review_status"), "knowledge_derivatives", ["review_status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_derivatives_review_status"), table_name="knowledge_derivatives")
    op.drop_index(op.f("ix_knowledge_derivatives_target_audience"), table_name="knowledge_derivatives")
    op.drop_index(op.f("ix_knowledge_derivatives_derivative_type"), table_name="knowledge_derivatives")
    op.drop_index(op.f("ix_knowledge_derivatives_knowledge_point_id"), table_name="knowledge_derivatives")
    op.drop_index(op.f("ix_knowledge_derivatives_id"), table_name="knowledge_derivatives")
    op.drop_table("knowledge_derivatives")

    op.drop_index(op.f("ix_entity_graph_edges_relation_type"), table_name="entity_graph_edges")
    op.drop_index(op.f("ix_entity_graph_edges_target_entity_id"), table_name="entity_graph_edges")
    op.drop_index(op.f("ix_entity_graph_edges_target_entity_type"), table_name="entity_graph_edges")
    op.drop_index(op.f("ix_entity_graph_edges_source_entity_id"), table_name="entity_graph_edges")
    op.drop_index(op.f("ix_entity_graph_edges_source_entity_type"), table_name="entity_graph_edges")
    op.drop_index(op.f("ix_entity_graph_edges_id"), table_name="entity_graph_edges")
    op.drop_table("entity_graph_edges")

    op.drop_index(op.f("ix_knowledge_point_relations_evidence_block_id"), table_name="knowledge_point_relations")
    op.drop_index(op.f("ix_knowledge_point_relations_relation_type"), table_name="knowledge_point_relations")
    op.drop_index(op.f("ix_knowledge_point_relations_target_knowledge_point_id"), table_name="knowledge_point_relations")
    op.drop_index(op.f("ix_knowledge_point_relations_source_knowledge_point_id"), table_name="knowledge_point_relations")
    op.drop_index(op.f("ix_knowledge_point_relations_id"), table_name="knowledge_point_relations")
    op.drop_table("knowledge_point_relations")

    op.drop_index(op.f("ix_knowledge_question_links_commentary_block_id"), table_name="knowledge_question_links")
    op.drop_index(op.f("ix_knowledge_question_links_explanation_block_id"), table_name="knowledge_question_links")
    op.drop_index(op.f("ix_knowledge_question_links_relation_type"), table_name="knowledge_question_links")
    op.drop_index(op.f("ix_knowledge_question_links_question_item_id"), table_name="knowledge_question_links")
    op.drop_index(op.f("ix_knowledge_question_links_knowledge_point_id"), table_name="knowledge_question_links")
    op.drop_index(op.f("ix_knowledge_question_links_id"), table_name="knowledge_question_links")
    op.drop_table("knowledge_question_links")

    op.drop_index(op.f("ix_knowledge_atoms_review_status"), table_name="knowledge_atoms")
    op.drop_index(op.f("ix_knowledge_atoms_evidence_block_id"), table_name="knowledge_atoms")
    op.drop_index(op.f("ix_knowledge_atoms_atom_type"), table_name="knowledge_atoms")
    op.drop_index(op.f("ix_knowledge_atoms_package_id"), table_name="knowledge_atoms")
    op.drop_index(op.f("ix_knowledge_atoms_knowledge_point_id"), table_name="knowledge_atoms")
    op.drop_index(op.f("ix_knowledge_atoms_id"), table_name="knowledge_atoms")
    op.drop_table("knowledge_atoms")

    op.drop_index(op.f("ix_knowledge_blocks_asset_id"), table_name="knowledge_blocks")
    op.drop_index(op.f("ix_knowledge_blocks_source_page_no"), table_name="knowledge_blocks")
    op.drop_index(op.f("ix_knowledge_blocks_block_role"), table_name="knowledge_blocks")
    op.drop_index(op.f("ix_knowledge_blocks_parent_block_id"), table_name="knowledge_blocks")
    op.drop_index(op.f("ix_knowledge_blocks_knowledge_point_id"), table_name="knowledge_blocks")
    op.drop_index(op.f("ix_knowledge_blocks_package_id"), table_name="knowledge_blocks")
    op.drop_index(op.f("ix_knowledge_blocks_id"), table_name="knowledge_blocks")
    op.drop_table("knowledge_blocks")

    op.drop_index(op.f("ix_knowledge_package_points_knowledge_point_id"), table_name="knowledge_package_points")
    op.drop_index(op.f("ix_knowledge_package_points_package_id"), table_name="knowledge_package_points")
    op.drop_index(op.f("ix_knowledge_package_points_id"), table_name="knowledge_package_points")
    op.drop_table("knowledge_package_points")

    op.drop_index(op.f("ix_knowledge_packages_review_status"), table_name="knowledge_packages")
    op.drop_index(op.f("ix_knowledge_packages_parse_status"), table_name="knowledge_packages")
    op.drop_index(op.f("ix_knowledge_packages_subject"), table_name="knowledge_packages")
    op.drop_index(op.f("ix_knowledge_packages_package_title"), table_name="knowledge_packages")
    op.drop_index(op.f("ix_knowledge_packages_tenant_id"), table_name="knowledge_packages")
    op.drop_index(op.f("ix_knowledge_packages_source_document_id"), table_name="knowledge_packages")
    op.drop_index(op.f("ix_knowledge_packages_id"), table_name="knowledge_packages")
    op.drop_table("knowledge_packages")

    op.drop_index(op.f("ix_knowledge_points_is_active"), table_name="knowledge_points")
    op.drop_index(op.f("ix_knowledge_points_review_status"), table_name="knowledge_points")
    op.drop_index(op.f("ix_knowledge_points_canonical_name"), table_name="knowledge_points")
    op.drop_index(op.f("ix_knowledge_points_subject"), table_name="knowledge_points")
    op.drop_index(op.f("ix_knowledge_points_primary_taxonomy_node_id"), table_name="knowledge_points")
    op.drop_index(op.f("ix_knowledge_points_tenant_id"), table_name="knowledge_points")
    op.drop_index(op.f("ix_knowledge_points_id"), table_name="knowledge_points")
    op.drop_table("knowledge_points")
