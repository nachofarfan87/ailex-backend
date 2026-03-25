from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def generate_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class LearningActionLog(Base):
    __tablename__ = "learning_action_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    event_type = Column(String, nullable=False)
    recommendation_type = Column(String, nullable=True)
    applied = Column(Boolean, default=False)
    reason = Column(String, nullable=True)
    confidence_score = Column(Float, nullable=True)
    priority = Column(Float, nullable=True)
    evidence_json = Column(Text, nullable=True)
    changes_applied_json = Column(Text, nullable=True)
    impact_status = Column(String, nullable=True, index=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "recommendation_type": self.recommendation_type,
            "applied": self.applied,
            "reason": self.reason,
            "confidence_score": self.confidence_score,
            "priority": self.priority,
            "evidence_json": _safe_json_loads(self.evidence_json, {}),
            "changes_applied_json": _safe_json_loads(self.changes_applied_json, {}),
            "impact_status": self.impact_status,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
