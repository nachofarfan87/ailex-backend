from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class OrchestratorConfigSnapshot(Base):
    __tablename__ = "orchestrator_config_snapshots"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    event_id = Column(String(36), nullable=False, index=True)
    snapshot_type = Column(String(30), nullable=False, index=True)
    version = Column(String(100), nullable=False, default="")
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "snapshot_type": self.snapshot_type,
            "version": self.version,
            "config_json": _safe_json_loads(self.config_json, {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
