# backend/alembic/versions/20260406_0006_case_state.py
"""add conversation case state tables

Revision ID: 20260406_0006
Revises: 20260326_0005
Create Date: 2026-04-06 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_0006"
down_revision = "20260326_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_case_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("case_type", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("case_stage", sa.String(length=80), nullable=False, server_default="consulta_inicial"),
        sa.Column("primary_goal", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("secondary_goals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("jurisdiction", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_user_turn_at", sa.DateTime(), nullable=True),
        sa.Column("last_system_turn_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversation_case_states_conversation_id", "conversation_case_states", ["conversation_id"], unique=True)
    op.create_index("ix_conversation_case_states_case_type", "conversation_case_states", ["case_type"])
    op.create_index("ix_conversation_case_states_case_stage", "conversation_case_states", ["case_stage"])
    op.create_index("ix_conversation_case_states_status", "conversation_case_states", ["status"])
    op.create_index("ix_conversation_case_states_last_user_turn_at", "conversation_case_states", ["last_user_turn_at"])
    op.create_index("ix_conversation_case_states_last_system_turn_at", "conversation_case_states", ["last_system_turn_at"])
    op.create_index("ix_conversation_case_states_created_at", "conversation_case_states", ["created_at"])
    op.create_index("ix_conversation_case_states_updated_at", "conversation_case_states", ["updated_at"])

    op.create_table(
        "case_facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("fact_key", sa.String(length=120), nullable=False),
        sa.Column("fact_value_json", sa.Text(), nullable=False, server_default="null"),
        sa.Column("value_type", sa.String(length=40), nullable=False, server_default="string"),
        sa.Column("domain", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="pipeline_inferred"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="probable"),
        sa.Column("first_seen_turn", sa.Integer(), nullable=True),
        sa.Column("last_updated_turn", sa.Integer(), nullable=True),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "fact_key", name="uq_case_facts_conversation_fact_key"),
    )
    op.create_index("ix_case_facts_conversation_id", "case_facts", ["conversation_id"])
    op.create_index("ix_case_facts_fact_key", "case_facts", ["fact_key"])
    op.create_index("ix_case_facts_domain", "case_facts", ["domain"])
    op.create_index("ix_case_facts_source_type", "case_facts", ["source_type"])
    op.create_index("ix_case_facts_status", "case_facts", ["status"])
    op.create_index("ix_case_facts_created_at", "case_facts", ["created_at"])
    op.create_index("ix_case_facts_updated_at", "case_facts", ["updated_at"])

    op.create_table(
        "case_needs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("need_key", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=40), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_question", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved_by_fact_key", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("conversation_id", "need_key", name="uq_case_needs_conversation_need_key"),
    )
    op.create_index("ix_case_needs_conversation_id", "case_needs", ["conversation_id"])
    op.create_index("ix_case_needs_need_key", "case_needs", ["need_key"])
    op.create_index("ix_case_needs_category", "case_needs", ["category"])
    op.create_index("ix_case_needs_priority", "case_needs", ["priority"])
    op.create_index("ix_case_needs_status", "case_needs", ["status"])
    op.create_index("ix_case_needs_resolved_by_fact_key", "case_needs", ["resolved_by_fact_key"])
    op.create_index("ix_case_needs_created_at", "case_needs", ["created_at"])
    op.create_index("ix_case_needs_updated_at", "case_needs", ["updated_at"])

    op.create_table(
        "case_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_case_events_conversation_id", "case_events", ["conversation_id"])
    op.create_index("ix_case_events_event_type", "case_events", ["event_type"])
    op.create_index("ix_case_events_created_at", "case_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_case_events_created_at", table_name="case_events")
    op.drop_index("ix_case_events_event_type", table_name="case_events")
    op.drop_index("ix_case_events_conversation_id", table_name="case_events")
    op.drop_table("case_events")

    op.drop_index("ix_case_needs_updated_at", table_name="case_needs")
    op.drop_index("ix_case_needs_created_at", table_name="case_needs")
    op.drop_index("ix_case_needs_resolved_by_fact_key", table_name="case_needs")
    op.drop_index("ix_case_needs_status", table_name="case_needs")
    op.drop_index("ix_case_needs_priority", table_name="case_needs")
    op.drop_index("ix_case_needs_category", table_name="case_needs")
    op.drop_index("ix_case_needs_need_key", table_name="case_needs")
    op.drop_index("ix_case_needs_conversation_id", table_name="case_needs")
    op.drop_table("case_needs")

    op.drop_index("ix_case_facts_updated_at", table_name="case_facts")
    op.drop_index("ix_case_facts_created_at", table_name="case_facts")
    op.drop_index("ix_case_facts_status", table_name="case_facts")
    op.drop_index("ix_case_facts_source_type", table_name="case_facts")
    op.drop_index("ix_case_facts_domain", table_name="case_facts")
    op.drop_index("ix_case_facts_fact_key", table_name="case_facts")
    op.drop_index("ix_case_facts_conversation_id", table_name="case_facts")
    op.drop_table("case_facts")

    op.drop_index("ix_conversation_case_states_updated_at", table_name="conversation_case_states")
    op.drop_index("ix_conversation_case_states_created_at", table_name="conversation_case_states")
    op.drop_index("ix_conversation_case_states_last_system_turn_at", table_name="conversation_case_states")
    op.drop_index("ix_conversation_case_states_last_user_turn_at", table_name="conversation_case_states")
    op.drop_index("ix_conversation_case_states_status", table_name="conversation_case_states")
    op.drop_index("ix_conversation_case_states_case_stage", table_name="conversation_case_states")
    op.drop_index("ix_conversation_case_states_case_type", table_name="conversation_case_states")
    op.drop_index("ix_conversation_case_states_conversation_id", table_name="conversation_case_states")
    op.drop_table("conversation_case_states")
