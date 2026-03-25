"""link documents to expediente

Revision ID: 20260320_0003
Revises: 20260320_0002
Create Date: 2026-03-20 01:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260320_0003"
down_revision = "20260320_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_documents",
        sa.Column("expediente_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_source_documents_expediente_id",
        "source_documents",
        ["expediente_id"],
    )
    op.create_foreign_key(
        "fk_source_documents_expediente_id",
        "source_documents",
        "expedientes",
        ["expediente_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_source_documents_expediente_id", "source_documents", type_="foreignkey")
    op.drop_index("ix_source_documents_expediente_id", table_name="source_documents")
    op.drop_column("source_documents", "expediente_id")
