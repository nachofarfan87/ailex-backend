from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Column, DateTime, Float, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def generate_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class LearningDecisionAuditLog(Base):
    __tablename__ = "learning_decision_audit_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    learning_action_log_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    audit_status = Column(String, nullable=False, default="insufficient_data", index=True)
    audit_score = Column(Float, nullable=True)
    decision_quality = Column(String, nullable=False, default="unknown", index=True)
    recommended_action = Column(String, nullable=False, default="monitor", index=True)
    reasoning = Column(Text, nullable=True)
    audit_flags_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "learning_action_log_id": self.learning_action_log_id,
            "event_type": self.event_type,
            "audit_status": self.audit_status,
            "audit_score": self.audit_score,
            "decision_quality": self.decision_quality,
            "recommended_action": self.recommended_action,
            "reasoning": self.reasoning,
            "audit_flags_json": _safe_json_loads(self.audit_flags_json, []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
