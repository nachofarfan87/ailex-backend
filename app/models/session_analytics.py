from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.services.utc import utc_now


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class AnalyticsSession(Base):
    __tablename__ = "analytics_sessions"

    session_id = Column(String(64), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    started_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    last_activity_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    ended_at = Column(DateTime, nullable=True, index=True)
    first_advice_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)

    total_turns = Column(Integer, nullable=False, default=0)
    total_user_turns = Column(Integer, nullable=False, default=0)
    total_assistant_turns = Column(Integer, nullable=False, default=0)
    clarification_turns = Column(Integer, nullable=False, default=0)
    advice_turns = Column(Integer, nullable=False, default=0)

    closure_reached = Column(Boolean, nullable=False, default=False, index=True)
    first_case_domain = Column(String(100), nullable=True, default="", index=True)
    latest_case_domain = Column(String(100), nullable=True, default="", index=True)
    first_jurisdiction = Column(String(100), nullable=True, default="")
    latest_jurisdiction = Column(String(100), nullable=True, default="")

    events = relationship(
        "AnalyticsSessionEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AnalyticsSessionEvent.created_at.asc()",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "first_advice_at": self.first_advice_at.isoformat() if self.first_advice_at else None,
            "status": self.status,
            "total_turns": self.total_turns,
            "total_user_turns": self.total_user_turns,
            "total_assistant_turns": self.total_assistant_turns,
            "clarification_turns": self.clarification_turns,
            "advice_turns": self.advice_turns,
            "closure_reached": self.closure_reached,
            "first_case_domain": self.first_case_domain,
            "latest_case_domain": self.latest_case_domain,
            "first_jurisdiction": self.first_jurisdiction,
            "latest_jurisdiction": self.latest_jurisdiction,
        }


class AnalyticsSessionEvent(Base):
    __tablename__ = "analytics_session_events"

    event_id = Column(String(36), primary_key=True, default=_new_uuid)
    session_id = Column(String(64), ForeignKey("analytics_sessions.session_id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    turn_index = Column(Integer, nullable=True, index=True)
    case_domain = Column(String(100), nullable=True, default="", index=True)
    jurisdiction = Column(String(100), nullable=True, default="")
    payload_json = Column(Text, nullable=False, default="{}")

    session = relationship("AnalyticsSession", back_populates="events")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "event_type": self.event_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "turn_index": self.turn_index,
            "case_domain": self.case_domain,
            "jurisdiction": self.jurisdiction,
            "payload": _safe_json_loads(self.payload_json, {}),
        }
