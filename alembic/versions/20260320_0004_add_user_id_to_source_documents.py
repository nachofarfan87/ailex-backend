"""add user_id to source_documents

Revision ID: 20260320_0004
Revises: 20260320_0003
Create Date: 2026-03-20 02:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260320_0004"
down_revision = "20260320_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_documents",
        sa.Column("user_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_source_documents_user_id",
        "source_documents",
        ["user_id"],
    )
    op.create_foreign_key(
        "fk_source_documents_user_id",
        "source_documents",
        "users",
        ["user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_source_documents_user_id", "source_documents", type_="foreignkey")
    op.drop_index("ix_source_documents_user_id", table_name="source_documents")
    op.drop_column("source_documents", "user_id")
