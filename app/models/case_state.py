from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint

from app.db.database import Base
from app.services.utc import utc_now


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class ConversationCaseState(Base):
    __tablename__ = "conversation_case_states"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    conversation_id = Column(String(64), nullable=False, unique=True, index=True)
    case_type = Column(String(120), nullable=False, default="", index=True)
    case_stage = Column(String(80), nullable=False, default="consulta_inicial", index=True)
    primary_goal = Column(String(255), nullable=False, default="")
    secondary_goals_json = Column(Text, nullable=False, default="[]")
    jurisdiction = Column(String(120), nullable=False, default="")
    status = Column(String(40), nullable=False, default="active", index=True)
    confidence_score = Column(Float, nullable=True)
    summary_text = Column(Text, nullable=False, default="")
    last_user_turn_at = Column(DateTime, nullable=True, index=True)
    last_system_turn_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "case_type": self.case_type,
            "case_stage": self.case_stage,
            "primary_goal": self.primary_goal,
            "secondary_goals_json": _safe_json_loads(self.secondary_goals_json, []),
            "jurisdiction": self.jurisdiction,
            "status": self.status,
            "confidence_score": self.confidence_score,
            "summary_text": self.summary_text,
            "last_user_turn_at": self.last_user_turn_at.isoformat() if self.last_user_turn_at else None,
            "last_system_turn_at": self.last_system_turn_at.isoformat() if self.last_system_turn_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseFact(Base):
    __tablename__ = "case_facts"
    __table_args__ = (
        UniqueConstraint("conversation_id", "fact_key", name="uq_case_facts_conversation_fact_key"),
    )

    id = Column(String(36), primary_key=True, default=_new_uuid)
    conversation_id = Column(String(64), nullable=False, index=True)
    fact_key = Column(String(120), nullable=False, index=True)
    fact_value_json = Column(Text, nullable=False, default="null")
    value_type = Column(String(40), nullable=False, default="string")
    domain = Column(String(120), nullable=False, default="", index=True)
    source_type = Column(String(40), nullable=False, default="pipeline_inferred", index=True)
    confidence = Column(Float, nullable=False, default=0.5)
    status = Column(String(40), nullable=False, default="probable", index=True)
    first_seen_turn = Column(Integer, nullable=True)
    last_updated_turn = Column(Integer, nullable=True)
    evidence_excerpt = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "fact_key": self.fact_key,
            "fact_value": _safe_json_loads(self.fact_value_json, None),
            "value_type": self.value_type,
            "domain": self.domain,
            "source_type": self.source_type,
            "confidence": self.confidence,
            "status": self.status,
            "first_seen_turn": self.first_seen_turn,
            "last_updated_turn": self.last_updated_turn,
            "evidence_excerpt": self.evidence_excerpt,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseNeed(Base):
    __tablename__ = "case_needs"
    __table_args__ = (
        UniqueConstraint("conversation_id", "need_key", name="uq_case_needs_conversation_need_key"),
    )

    id = Column(String(36), primary_key=True, default=_new_uuid)
    conversation_id = Column(String(64), nullable=False, index=True)
    need_key = Column(String(120), nullable=False, index=True)
    category = Column(String(80), nullable=False, default="", index=True)
    priority = Column(String(40), nullable=False, default="normal", index=True)
    status = Column(String(40), nullable=False, default="open", index=True)
    reason = Column(Text, nullable=False, default="")
    suggested_question = Column(Text, nullable=False, default="")
    resolved_by_fact_key = Column(String(120), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "need_key": self.need_key,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "reason": self.reason,
            "suggested_question": self.suggested_question,
            "resolved_by_fact_key": self.resolved_by_fact_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseEvent(Base):
    __tablename__ = "case_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    conversation_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "event_type": self.event_type,
            "payload": _safe_json_loads(self.payload_json, {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
