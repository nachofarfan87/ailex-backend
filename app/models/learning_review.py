from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, String, Text

from app.db.database import Base
from app.services.utc import utc_now

REVIEW_STALE_AFTER_HOURS = 24
REVIEW_AGING_AFTER_HOURS = 6


def generate_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


def build_review_aging_snapshot(
    *,
    created_at: datetime | None,
    review_status: str,
) -> dict[str, Any]:
    if created_at is None:
        return {
            "age_hours": 0.0,
            "is_stale": False,
            "stale_reason": None,
            "stale_bucket": "unknown",
        }

    age_hours = round(max((utc_now() - created_at).total_seconds() / 3600, 0.0), 2)
    normalized_status = str(review_status or "").strip().lower()
    if normalized_status != "pending":
        return {
            "age_hours": age_hours,
            "is_stale": False,
            "stale_reason": None,
            "stale_bucket": "resolved",
        }
    if age_hours >= REVIEW_STALE_AFTER_HOURS:
        return {
            "age_hours": age_hours,
            "is_stale": True,
            "stale_reason": f"pending_review_older_than_{REVIEW_STALE_AFTER_HOURS}h",
            "stale_bucket": "stale",
        }
    if age_hours >= REVIEW_AGING_AFTER_HOURS:
        return {
            "age_hours": age_hours,
            "is_stale": False,
            "stale_reason": None,
            "stale_bucket": "aging",
        }
    return {
        "age_hours": age_hours,
        "is_stale": False,
        "stale_reason": None,
        "stale_bucket": "fresh",
    }


class LearningReview(Base):
    __tablename__ = "learning_reviews"

    id = Column(String, primary_key=True, default=generate_uuid)
    review_type = Column(String, nullable=False, default="self_tuning")
    source_cycle_id = Column(String, nullable=True, index=True)
    parameter_name = Column(String, nullable=True, index=True)
    proposed_delta = Column(Float, nullable=True)
    final_action = Column(String, nullable=False)
    meta_confidence = Column(Float, nullable=True)
    strategy_profile = Column(String, nullable=True)
    reason_summary = Column(Text, nullable=True)
    risk_flags_json = Column(Text, nullable=True)
    requires_review = Column(Boolean, default=True)
    review_priority = Column(String, nullable=False, default="medium", index=True)
    review_priority_reason = Column(Text, nullable=True)
    review_status = Column(String, nullable=False, default="pending", index=True)
    recommendation_json = Column(Text, nullable=False)
    manual_override_json = Column(Text, nullable=True)
    resolution_json = Column(Text, nullable=True)
    reviewed_by_user_id = Column(String, nullable=True, index=True)
    reviewed_by_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    resolved_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        aging = build_review_aging_snapshot(
            created_at=self.created_at,
            review_status=self.review_status,
        )
        return {
            "id": self.id,
            "review_type": self.review_type,
            "source_cycle_id": self.source_cycle_id,
            "parameter_name": self.parameter_name,
            "proposed_delta": self.proposed_delta,
            "final_action": self.final_action,
            "meta_confidence": self.meta_confidence,
            "strategy_profile": self.strategy_profile,
            "reason_summary": self.reason_summary,
            "risk_flags": _safe_json_loads(self.risk_flags_json, []),
            "requires_review": self.requires_review,
            "review_priority": self.review_priority,
            "review_priority_reason": self.review_priority_reason,
            "review_status": self.review_status,
            "recommendation": _safe_json_loads(self.recommendation_json, {}),
            "manual_override": _safe_json_loads(self.manual_override_json, {}),
            "resolution": _safe_json_loads(self.resolution_json, {}),
            "reviewed_by_user_id": self.reviewed_by_user_id,
            "reviewed_by_email": self.reviewed_by_email,
            "age_hours": aging["age_hours"],
            "is_stale": aging["is_stale"],
            "stale_reason": aging["stale_reason"],
            "stale_bucket": aging["stale_bucket"],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
