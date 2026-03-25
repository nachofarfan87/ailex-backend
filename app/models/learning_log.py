from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text

from app.db.database import Base
from app.services.utc import utc_now


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class LearningLog(Base):
    __tablename__ = "learning_logs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    request_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    session_id = Column(String(100), nullable=True, index=True)
    conversation_id = Column(String(100), nullable=True, index=True)

    query = Column(Text, nullable=False, default="")
    jurisdiction = Column(String(100), nullable=True, default="", index=False)
    forum = Column(String(100), nullable=True, default="")
    case_domain = Column(String(100), nullable=True, default="", index=True)
    action_slug = Column(String(120), nullable=True, default="", index=True)
    retrieval_mode = Column(String(50), nullable=True, default="", index=True)
    strategy_mode = Column(String(50), nullable=True, default="", index=True)
    pipeline_mode = Column(String(50), nullable=True, default="", index=True)

    decision_confidence = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    fallback_used = Column(Boolean, default=False, index=True)
    fallback_reason = Column(Text, nullable=True, default="")
    documents_considered = Column(Integer, default=0)
    warnings_count = Column(Integer, default=0)
    processing_time_ms = Column(Integer, default=0)

    orchestrator_decision_json = Column(Text, nullable=True, default="{}")
    classification_json = Column(Text, nullable=True, default="{}")
    retrieval_json = Column(Text, nullable=True, default="{}")
    strategy_json = Column(Text, nullable=True, default="{}")
    final_output_json = Column(Text, nullable=True, default="{}")
    timings_json = Column(Text, nullable=True, default="{}")
    quality_flags_json = Column(Text, nullable=True, default="{}")
    severity_score = Column(Float, nullable=False, default=0.0, index=True)

    user_feedback_score = Column(Integer, nullable=True)
    user_feedback_label = Column(String(50), nullable=True, default="")
    is_user_feedback_positive = Column(Boolean, nullable=True)
    feedback_submitted_at = Column(DateTime, nullable=True)
    corrected_strategy_mode = Column(String(50), nullable=True, default="")
    corrected_domain = Column(String(100), nullable=True, default="", index=True)
    feedback_comment = Column(Text, nullable=True, default="")
    reviewed_by_user = Column(Boolean, default=False, index=True)
    reviewed_by_admin = Column(Boolean, default=False, index=True)
    review_notes = Column(Text, nullable=True, default="")
    review_status = Column(String(30), default="pending", index=True)

    learning_version = Column(String(20), nullable=False, default="v1")
    orchestrator_version = Column(String(100), nullable=False, default="unknown")
    time_bucket = Column(String(20), nullable=False, default="")

    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "query": self.query,
            "jurisdiction": self.jurisdiction,
            "forum": self.forum,
            "case_domain": self.case_domain,
            "action_slug": self.action_slug,
            "retrieval_mode": self.retrieval_mode,
            "strategy_mode": self.strategy_mode,
            "pipeline_mode": self.pipeline_mode,
            "decision_confidence": self.decision_confidence,
            "confidence_score": self.confidence_score,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "documents_considered": self.documents_considered,
            "warnings_count": self.warnings_count,
            "processing_time_ms": self.processing_time_ms,
            "orchestrator_decision_json": _safe_json_loads(self.orchestrator_decision_json, {}),
            "classification_json": _safe_json_loads(self.classification_json, {}),
            "retrieval_json": _safe_json_loads(self.retrieval_json, {}),
            "strategy_json": _safe_json_loads(self.strategy_json, {}),
            "final_output_json": _safe_json_loads(self.final_output_json, {}),
            "timings_json": _safe_json_loads(self.timings_json, {}),
            "quality_flags_json": _safe_json_loads(self.quality_flags_json, {}),
            "severity_score": self.severity_score,
            "user_feedback_score": self.user_feedback_score,
            "user_feedback_label": self.user_feedback_label,
            "is_user_feedback_positive": self.is_user_feedback_positive,
            "feedback_submitted_at": self.feedback_submitted_at.isoformat() if self.feedback_submitted_at else None,
            "corrected_strategy_mode": self.corrected_strategy_mode,
            "corrected_domain": self.corrected_domain,
            "feedback_comment": self.feedback_comment,
            "reviewed_by_user": self.reviewed_by_user,
            "reviewed_by_admin": self.reviewed_by_admin,
            "review_notes": self.review_notes,
            "review_status": self.review_status,
            "learning_version": self.learning_version,
            "orchestrator_version": self.orchestrator_version,
            "time_bucket": self.time_bucket,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
