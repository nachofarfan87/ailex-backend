from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.orm import Session

from app.db.database import Base
from app.services.utc import utc_now


CONFIG_VERSION = "v1"


class LearningRuntimeConfig(Base):
    __tablename__ = "learning_runtime_config"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    config_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)


def _extract_runtime_config(payload):
    if not isinstance(payload, dict):
        return None
    if "runtime_config" in payload and "config_version" in payload:
        runtime_config = payload.get("runtime_config")
        return dict(runtime_config) if isinstance(runtime_config, dict) else None
    return dict(payload)


def save_runtime_config(db: Session, config: dict) -> LearningRuntimeConfig:
    payload = {
        "config_version": CONFIG_VERSION,
        "runtime_config": dict(config or {}),
    }
    record = LearningRuntimeConfig(config_json=json.dumps(payload))
    db.add(record)
    return record


def load_latest_runtime_config(db: Session):
    record = (
        db.query(LearningRuntimeConfig)
        .order_by(LearningRuntimeConfig.created_at.desc())
        .first()
    )
    if not record:
        return None
    try:
        payload = json.loads(record.config_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return _extract_runtime_config(payload)
