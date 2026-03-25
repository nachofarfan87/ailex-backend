# backend/app/models/auto_healing_event.py
"""
Modelo de auditoría para decisiones de auto-healing.

Cada evaluación del sistema genera un registro inmutable que
documenta qué señales se leyeron, qué situación se clasificó,
qué acción se decidió y si se aplicó o solo se recomendó.
"""

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


class AutoHealingEvent(Base):
    __tablename__ = "auto_healing_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)

    # Clasificación
    situation = Column(String(30), nullable=False, index=True)
    previous_situation = Column(String(30), nullable=True, index=True)

    # Acción decidida
    action_type = Column(String(60), nullable=False, index=True)
    action_applied = Column(Boolean, nullable=False, default=False, index=True)
    confidence = Column(String(20), nullable=False, default="low")

    # Razón y evidencia
    reason = Column(String(500), nullable=False, default="")
    rollback_plan = Column(String(500), nullable=True, default="")

    # Señales que alimentaron la decisión (JSON)
    signals_json = Column(Text, nullable=True, default="{}")

    # Resultado de la acción (JSON)
    result_json = Column(Text, nullable=True, default="{}")

    # Contexto del sistema al momento
    system_mode = Column(String(30), nullable=True, index=True)
    protective_mode_active = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "situation": self.situation,
            "previous_situation": self.previous_situation,
            "action_type": self.action_type,
            "action_applied": self.action_applied,
            "confidence": self.confidence,
            "reason": self.reason,
            "rollback_plan": self.rollback_plan,
            "signals": _safe_json_loads(self.signals_json, {}),
            "result": _safe_json_loads(self.result_json, {}),
            "system_mode": self.system_mode,
            "protective_mode_active": self.protective_mode_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
