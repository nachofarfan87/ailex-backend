from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Float, String, Text

from app.db.database import Base
from app.services.utc import utc_now


VALID_TUNING_EVENT_STATUSES = {
    "proposed",
    "approved",
    "rejected",
    "applied",
    "rolled_back",
    "invalidated",
}

VALID_EVALUATION_STATUSES = {
    "pending",
    "improved",
    "regressed",
    "neutral",
    "insufficient_data",
}


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class OrchestratorTuningEvent(Base):
    __tablename__ = "orchestrator_tuning_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    event_type = Column(String(50), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="proposed", index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    evidence_json = Column(Text, nullable=True, default="{}")
    proposed_changes_json = Column(Text, nullable=True, default="{}")
    confidence_score = Column(Float, nullable=False, default=0.0)
    priority = Column(Float, nullable=False, default=0.0, index=True)
    evaluation_status = Column(String(30), nullable=False, default="pending", index=True)
    observed_effect_json = Column(Text, nullable=True, default="{}")
    source_version = Column(String(100), nullable=True, default="")
    target_version = Column(String(100), nullable=True, default="")
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "status": self.status,
            "title": self.title,
            "description": self.description,
            "evidence_json": _safe_json_loads(self.evidence_json, {}),
            "proposed_changes_json": _safe_json_loads(self.proposed_changes_json, {}),
            "confidence_score": self.confidence_score,
            "priority": self.priority,
            "evaluation_status": self.evaluation_status,
            "observed_effect_json": _safe_json_loads(self.observed_effect_json, {}),
            "source_version": self.source_version,
            "target_version": self.target_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
