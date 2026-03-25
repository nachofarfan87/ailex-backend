"""initial schema

Revision ID: 20260320_0001
Revises:
Create Date: 2026-03-20 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260320_0001"
down_revision = None
branch_labels = None
depends_on = None


source_type_enum = sa.Enum(
    "CODIGO",
    "LEY",
    "REGLAMENTO",
    "ACORDADA",
    "JURISPRUDENCIA",
    "DOCTRINA",
    "ESCRITO",
    "MODELO",
    "ESTRATEGIA",
    name="source_type_enum",
)
source_hierarchy_enum = sa.Enum(
    "NORMATIVA",
    "JURISPRUDENCIA",
    "DOCTRINA",
    "INTERNO",
    name="source_hierarchy_enum",
)
authority_level_enum = sa.Enum(
    "VINCULANTE",
    "REFERENCIAL",
    "INTERNO",
    name="authority_level_enum",
)
document_status_enum = sa.Enum(
    "PENDING",
    "INDEXED",
    "ERROR",
    "ARCHIVED",
    name="document_status_enum",
)
document_scope_enum = sa.Enum(
    "CORPUS",
    "CASE",
    name="document_scope_enum",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("hashed_password", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "expedientes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("titulo", sa.String(length=500), nullable=False),
        sa.Column("caratula", sa.String(length=500), nullable=True, server_default=""),
        sa.Column("numero", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("materia", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("juzgado", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("jurisdiccion", sa.String(length=100), nullable=True, server_default="jujuy"),
        sa.Column("descripcion", sa.Text(), nullable=True, server_default=""),
        sa.Column("notas_estrategia", sa.Text(), nullable=True, server_default=""),
        sa.Column("partes_json", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("hechos_relevantes", sa.Text(), nullable=True, server_default=""),
        sa.Column("pretension_principal", sa.Text(), nullable=True, server_default=""),
        sa.Column("riesgos_clave", sa.Text(), nullable=True, server_default=""),
        sa.Column("estrategia_base", sa.Text(), nullable=True, server_default=""),
        sa.Column("proxima_accion_sugerida", sa.Text(), nullable=True, server_default=""),
        sa.Column("tipo_caso", sa.String(length=120), nullable=True, server_default=""),
        sa.Column("subtipo_caso", sa.String(length=120), nullable=True, server_default=""),
        sa.Column("estado_procesal", sa.String(length=120), nullable=True, server_default=""),
        sa.Column("estado", sa.String(length=20), nullable=True, server_default="activo"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_expedientes_estado"), "expedientes", ["estado"], unique=False)
    op.create_index(op.f("ix_expedientes_titulo"), "expedientes", ["titulo"], unique=False)
    op.create_index(op.f("ix_expedientes_user_id"), "expedientes", ["user_id"], unique=False)

    op.create_table(
        "source_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True, server_default=""),
        sa.Column("source_type", source_type_enum, nullable=False),
        sa.Column("source_hierarchy", source_hierarchy_enum, nullable=False),
        sa.Column(
            "authority_level",
            authority_level_enum,
            nullable=False,
            server_default="REFERENCIAL",
        ),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True, server_default="Jujuy"),
        sa.Column("fuero", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("legal_area", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("court", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("document_date", sa.String(length=20), nullable=True),
        sa.Column("authority", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("nivel_jerarquia", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("vigente", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("origin", sa.String(length=100), nullable=True, server_default="carga_manual"),
        sa.Column("tags", sa.String(length=500), nullable=True, server_default=""),
        sa.Column("detected_type", sa.String(length=120), nullable=True, server_default=""),
        sa.Column("entities_json", sa.Text(), nullable=True, server_default="{}"),
        sa.Column("extraction_mode", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("extraction_method", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("ocr_used", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("extracted_text_length", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("extraction_warning", sa.Text(), nullable=True, server_default=""),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ocr_pages_processed", sa.Integer(), nullable=True),
        sa.Column("document_scope", document_scope_enum, nullable=False, server_default="CORPUS"),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("file_type", sa.String(length=10), nullable=True, server_default="txt"),
        sa.Column("content_raw", sa.Text(), nullable=True),
        sa.Column("hash_documento", sa.String(length=64), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=True, server_default="0.5"),
        sa.Column("status", document_status_enum, nullable=True, server_default="PENDING"),
        sa.Column("chunk_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("total_chars", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_source_documents_document_scope"), "source_documents", ["document_scope"], unique=False)
    op.create_index(op.f("ix_source_documents_hash_documento"), "source_documents", ["hash_documento"], unique=False)
    op.create_index(op.f("ix_source_documents_jurisdiction"), "source_documents", ["jurisdiction"], unique=False)
    op.create_index(op.f("ix_source_documents_legal_area"), "source_documents", ["legal_area"], unique=False)
    op.create_index(op.f("ix_source_documents_source_hierarchy"), "source_documents", ["source_hierarchy"], unique=False)
    op.create_index(op.f("ix_source_documents_source_type"), "source_documents", ["source_type"], unique=False)
    op.create_index(op.f("ix_source_documents_status"), "source_documents", ["status"], unique=False)
    op.create_index(op.f("ix_source_documents_title"), "source_documents", ["title"], unique=False)

    op.create_table(
        "consultas",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("expediente_id", sa.String(length=36), nullable=True),
        sa.Column("titulo", sa.String(length=300), nullable=True, server_default=""),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True, server_default="jujuy"),
        sa.Column("forum", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("document_mode", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("facts_json", sa.Text(), nullable=True, server_default="{}"),
        sa.Column("resultado_json", sa.Text(), nullable=True, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("generated_document", sa.Text(), nullable=True, server_default=""),
        sa.Column("warnings_json", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("notas", sa.Text(), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["expediente_id"], ["expedientes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_consultas_created_at"), "consultas", ["created_at"], unique=False)
    op.create_index(op.f("ix_consultas_expediente_id"), "consultas", ["expediente_id"], unique=False)
    op.create_index(op.f("ix_consultas_user_id"), "consultas", ["user_id"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_search", sa.Text(), nullable=True, server_default=""),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=300), nullable=True, server_default=""),
        sa.Column("article_reference", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("char_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True, server_default="placeholder"),
        sa.Column("source_type", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("source_hierarchy", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True, server_default="Jujuy"),
        sa.Column("legal_area", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_jurisdiction"), "document_chunks", ["jurisdiction"], unique=False)
    op.create_index(op.f("ix_document_chunks_source_hierarchy"), "document_chunks", ["source_hierarchy"], unique=False)

    op.create_table(
        "source_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("module", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("chunk_id", sa.String(length=36), nullable=True),
        sa.Column("document_title", sa.String(length=500), nullable=True, server_default=""),
        sa.Column("source_hierarchy", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("fragment", sa.Text(), nullable=True, server_default=""),
        sa.Column("page_or_section", sa.String(length=200), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("caracter", sa.String(length=20), nullable=True, server_default="extraido"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_source_citations_session_id"), "source_citations", ["session_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(op.f("ix_source_citations_session_id"), table_name="source_citations")
    op.drop_table("source_citations")

    op.drop_index(op.f("ix_document_chunks_source_hierarchy"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_jurisdiction"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index(op.f("ix_consultas_user_id"), table_name="consultas")
    op.drop_index(op.f("ix_consultas_expediente_id"), table_name="consultas")
    op.drop_index(op.f("ix_consultas_created_at"), table_name="consultas")
    op.drop_table("consultas")

    op.drop_index(op.f("ix_source_documents_title"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_status"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_source_type"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_source_hierarchy"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_legal_area"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_jurisdiction"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_hash_documento"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_document_scope"), table_name="source_documents")
    op.drop_table("source_documents")

    op.drop_index(op.f("ix_expedientes_user_id"), table_name="expedientes")
    op.drop_index(op.f("ix_expedientes_titulo"), table_name="expedientes")
    op.drop_index(op.f("ix_expedientes_estado"), table_name="expedientes")
    op.drop_table("expedientes")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    if bind.dialect.name == "postgresql":
        document_scope_enum.drop(bind, checkfirst=True)
        document_status_enum.drop(bind, checkfirst=True)
        authority_level_enum.drop(bind, checkfirst=True)
        source_hierarchy_enum.drop(bind, checkfirst=True)
        source_type_enum.drop(bind, checkfirst=True)
