from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Column, DateTime, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def generate_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class LearningHumanAuditLog(Base):
    __tablename__ = "learning_human_audit_log"

    id = Column(String, primary_key=True, default=generate_uuid)
    review_id = Column(String, nullable=True, index=True)
    override_id = Column(String, nullable=True, index=True)
    user_id = Column(String, nullable=True, index=True)
    user_email = Column(String, nullable=True)
    action_type = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=True, index=True)
    notes = Column(Text, nullable=True)
    before_state_json = Column(Text, nullable=True)
    after_state_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "review_id": self.review_id,
            "override_id": self.override_id,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "action_type": self.action_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "notes": self.notes,
            "before_state": _safe_json_loads(self.before_state_json, {}),
            "after_state": _safe_json_loads(self.after_state_json, {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
