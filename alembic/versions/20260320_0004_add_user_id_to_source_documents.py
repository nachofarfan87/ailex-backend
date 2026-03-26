# backend/alembic/versions/20260320_0004_add_user_id_to_source_documents.py
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


TABLE_NAME = "source_documents"
COLUMN_NAME = "user_id"
INDEX_NAME = "ix_source_documents_user_id"
FK_NAME = "fk_source_documents_user_id"
REFERRED_TABLE = "users"
REFERRED_COLUMNS = ["id"]
LOCAL_COLUMNS = [COLUMN_NAME]


def _has_column(bind: sa.engine.Connection, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _has_index(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _has_foreign_key(bind: sa.engine.Connection, table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def _create_foreign_key_if_missing(bind: sa.engine.Connection) -> None:
    if _has_foreign_key(bind, TABLE_NAME, FK_NAME):
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME, recreate="always") as batch_op:
            batch_op.create_foreign_key(
                FK_NAME,
                REFERRED_TABLE,
                LOCAL_COLUMNS,
                REFERRED_COLUMNS,
            )
        return

    op.create_foreign_key(
        FK_NAME,
        TABLE_NAME,
        REFERRED_TABLE,
        LOCAL_COLUMNS,
        REFERRED_COLUMNS,
    )


def _drop_foreign_key_if_present(bind: sa.engine.Connection) -> None:
    if not _has_foreign_key(bind, TABLE_NAME, FK_NAME):
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME, recreate="always") as batch_op:
            batch_op.drop_constraint(FK_NAME, type_="foreignkey")
        return

    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, TABLE_NAME, COLUMN_NAME):
        op.add_column(
            TABLE_NAME,
            sa.Column(COLUMN_NAME, sa.String(36), nullable=True),
        )

    bind = op.get_bind()
    _create_foreign_key_if_missing(bind)

    bind = op.get_bind()
    if not _has_index(bind, TABLE_NAME, INDEX_NAME):
        op.create_index(
            INDEX_NAME,
            TABLE_NAME,
            [COLUMN_NAME],
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind, TABLE_NAME, INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)

    bind = op.get_bind()
    _drop_foreign_key_if_present(bind)

    bind = op.get_bind()
    if _has_column(bind, TABLE_NAME, COLUMN_NAME):
        op.drop_column(TABLE_NAME, COLUMN_NAME)