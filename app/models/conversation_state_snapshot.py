from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class ConversationStateSnapshot(Base):
    __tablename__ = "conversation_state_snapshots"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    conversation_id = Column(String(36), nullable=False, unique=True, index=True)
    state_version = Column(Integer, nullable=False, default=1)
    snapshot_json = Column(Text, nullable=False, default="{}")
    last_user_message_at = Column(DateTime, nullable=True, index=True)
    last_engine_update_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        payload = _safe_json_loads(self.snapshot_json, {})
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("conversation_id", self.conversation_id)
        payload.setdefault("state_version", int(self.state_version or 1))
        payload.setdefault(
            "last_user_message_at",
            self.last_user_message_at.isoformat() if self.last_user_message_at else None,
        )
        payload.setdefault(
            "last_engine_update_at",
            self.last_engine_update_at.isoformat() if self.last_engine_update_at else None,
        )
        return payload
