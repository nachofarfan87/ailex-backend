from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def generate_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class LearningImpactLog(Base):
    __tablename__ = "learning_impact_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    action_log_id = Column(String, nullable=True, index=True)
    metric_before_json = Column(Text, nullable=True)
    metric_after_json = Column(Text, nullable=True)
    impact_score = Column(Float, nullable=True)
    impact_label = Column(String, nullable=True, index=True)

    learning_action_log_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    before_metrics_json = Column(Text, nullable=True)
    after_metrics_json = Column(Text, nullable=True)
    delta_metrics_json = Column(Text, nullable=True)
    evaluation_window_hours = Column(Integer, nullable=False, default=24)
    evaluated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action_log_id": self.action_log_id,
            "metric_before_json": _safe_json_loads(self.metric_before_json, {}),
            "metric_after_json": _safe_json_loads(self.metric_after_json, {}),
            "impact_score": self.impact_score,
            "impact_label": self.impact_label,
            "learning_action_log_id": self.learning_action_log_id,
            "event_type": self.event_type,
            "status": self.status,
            "before_metrics_json": _safe_json_loads(self.before_metrics_json, {}),
            "after_metrics_json": _safe_json_loads(self.after_metrics_json, {}),
            "delta_metrics_json": _safe_json_loads(self.delta_metrics_json, {}),
            "evaluation_window_hours": self.evaluation_window_hours,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
