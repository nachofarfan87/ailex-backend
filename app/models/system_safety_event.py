from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class SystemSafetyEvent(Base):
    __tablename__ = "system_safety_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    request_id = Column(String(100), nullable=True, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    source_ip = Column(String(100), nullable=True, index=True)
    route_path = Column(String(200), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    safety_status = Column(String(50), nullable=False, index=True, default="normal")
    dominant_safety_reason = Column(String(200), nullable=True, default="", index=True)
    fallback_type = Column(String(50), nullable=True, default="", index=True)
    reason = Column(String(200), nullable=True, default="", index=True)
    reason_category = Column(String(100), nullable=True, default="", index=True)
    excluded_from_learning = Column(Boolean, nullable=False, default=False, index=True)
    severity = Column(String(20), nullable=True, default="info", index=True)
    protective_mode_active = Column(Boolean, nullable=False, default=False, index=True)
    detail_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "source_ip": self.source_ip,
            "route_path": self.route_path,
            "event_type": self.event_type,
            "safety_status": self.safety_status,
            "dominant_safety_reason": self.dominant_safety_reason,
            "fallback_type": self.fallback_type,
            "reason": self.reason,
            "reason_category": self.reason_category,
            "excluded_from_learning": self.excluded_from_learning,
            "severity": self.severity,
            "protective_mode_active": self.protective_mode_active,
            "detail": _safe_json_loads(self.detail_json, {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
