# backend/alembic/versions/20260326_0005_session_analytics.py
"""create session analytics tables

Revision ID: 20260326_0005
Revises: 20260320_0004
Create Date: 2026-03-26 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260326_0005"
down_revision = "20260320_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_sessions",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("first_advice_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("total_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_user_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_assistant_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clarification_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("advice_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closure_reached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_case_domain", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("latest_case_domain", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("first_jurisdiction", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("latest_jurisdiction", sa.String(length=100), nullable=True, server_default=""),
    )
    op.create_index("ix_analytics_sessions_user_id", "analytics_sessions", ["user_id"])
    op.create_index("ix_analytics_sessions_started_at", "analytics_sessions", ["started_at"])
    op.create_index("ix_analytics_sessions_last_activity_at", "analytics_sessions", ["last_activity_at"])
    op.create_index("ix_analytics_sessions_ended_at", "analytics_sessions", ["ended_at"])
    op.create_index("ix_analytics_sessions_status", "analytics_sessions", ["status"])
    op.create_index("ix_analytics_sessions_closure_reached", "analytics_sessions", ["closure_reached"])
    op.create_index("ix_analytics_sessions_first_case_domain", "analytics_sessions", ["first_case_domain"])
    op.create_index("ix_analytics_sessions_latest_case_domain", "analytics_sessions", ["latest_case_domain"])

    op.create_table(
        "analytics_session_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=64), sa.ForeignKey("analytics_sessions.session_id"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=True),
        sa.Column("case_domain", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_analytics_session_events_session_id", "analytics_session_events", ["session_id"])
    op.create_index("ix_analytics_session_events_user_id", "analytics_session_events", ["user_id"])
    op.create_index("ix_analytics_session_events_event_type", "analytics_session_events", ["event_type"])
    op.create_index("ix_analytics_session_events_created_at", "analytics_session_events", ["created_at"])
    op.create_index("ix_analytics_session_events_turn_index", "analytics_session_events", ["turn_index"])
    op.create_index("ix_analytics_session_events_case_domain", "analytics_session_events", ["case_domain"])


def downgrade() -> None:
    op.drop_index("ix_analytics_session_events_case_domain", table_name="analytics_session_events")
    op.drop_index("ix_analytics_session_events_turn_index", table_name="analytics_session_events")
    op.drop_index("ix_analytics_session_events_created_at", table_name="analytics_session_events")
    op.drop_index("ix_analytics_session_events_event_type", table_name="analytics_session_events")
    op.drop_index("ix_analytics_session_events_user_id", table_name="analytics_session_events")
    op.drop_index("ix_analytics_session_events_session_id", table_name="analytics_session_events")
    op.drop_table("analytics_session_events")

    op.drop_index("ix_analytics_sessions_latest_case_domain", table_name="analytics_sessions")
    op.drop_index("ix_analytics_sessions_first_case_domain", table_name="analytics_sessions")
    op.drop_index("ix_analytics_sessions_closure_reached", table_name="analytics_sessions")
    op.drop_index("ix_analytics_sessions_status", table_name="analytics_sessions")
    op.drop_index("ix_analytics_sessions_ended_at", table_name="analytics_sessions")
    op.drop_index("ix_analytics_sessions_last_activity_at", table_name="analytics_sessions")
    op.drop_index("ix_analytics_sessions_started_at", table_name="analytics_sessions")
    op.drop_index("ix_analytics_sessions_user_id", table_name="analytics_sessions")
    op.drop_table("analytics_sessions")
