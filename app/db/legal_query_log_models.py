from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


class LegalQueryLog(Base):
    __tablename__ = "legal_queries"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    request_id = Column(String(100), nullable=False, unique=True, index=True)
    pipeline_version = Column(String(100), nullable=False, default="unknown")

    user_query_original = Column(Text, nullable=False, default="")
    user_query_normalized = Column(Text, nullable=False, default="")
    jurisdiction_requested = Column(String(100), default="", index=True)
    forum_requested = Column(String(100), default="")
    facts_json = Column(Text, default="{}")
    metadata_json = Column(Text, default="{}")

    case_domain = Column(String(100), default="", index=True)
    action_slug = Column(String(120), default="", index=True)
    action_label = Column(String(200), default="")

    source_mode = Column(String(50), default="", index=True)
    documents_considered = Column(Integer, default=0)
    sources_used_json = Column(Text, default="[]")
    normative_references_json = Column(Text, default="[]")
    jurisprudence_references_json = Column(Text, default="[]")
    top_retrieval_scores_json = Column(Text, default="[]")

    strategy_mode = Column(String(50), default="")
    dominant_factor = Column(String(50), default="")
    blocking_factor = Column(String(50), default="")
    execution_readiness = Column(String(50), default="")

    response_text = Column(Text, default="")
    warnings_json = Column(Text, default="[]")
    fallback_used = Column(Boolean, default=False, index=True)
    fallback_reason = Column(Text, default="")
    confidence_score = Column(Float, nullable=True)
    confidence_label = Column(String(20), default="")

    normalization_ms = Column(Integer, default=0)
    pipeline_ms = Column(Integer, default=0)
    classification_ms = Column(Integer, default=0)
    retrieval_ms = Column(Integer, default=0)
    strategy_ms = Column(Integer, default=0)
    postprocess_ms = Column(Integer, default=0)
    final_assembly_ms = Column(Integer, default=0)
    total_ms = Column(Integer, default=0)

    status = Column(String(20), default="processing", index=True)
    error_message = Column(Text, nullable=True)

    review_status = Column(String(30), default="pending", index=True)
    feedback_signal = Column(String(50), default="")
    review_notes = Column(Text, default="")

    reviews = relationship(
        "QueryReview",
        back_populates="query",
        cascade="all, delete-orphan",
        order_by="QueryReview.created_at.desc()",
    )

    def to_dict(self, include_reviews: bool = False) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "request_id": self.request_id,
            "pipeline_version": self.pipeline_version,
            "user_query_original": self.user_query_original,
            "user_query_normalized": self.user_query_normalized,
            "jurisdiction_requested": self.jurisdiction_requested,
            "forum_requested": self.forum_requested,
            "facts_json": _safe_json_loads(self.facts_json, {}),
            "metadata_json": _safe_json_loads(self.metadata_json, {}),
            "case_domain": self.case_domain,
            "action_slug": self.action_slug,
            "action_label": self.action_label,
            "source_mode": self.source_mode,
            "documents_considered": self.documents_considered,
            "sources_used_json": _safe_json_loads(self.sources_used_json, []),
            "normative_references_json": _safe_json_loads(self.normative_references_json, []),
            "jurisprudence_references_json": _safe_json_loads(self.jurisprudence_references_json, []),
            "top_retrieval_scores_json": _safe_json_loads(self.top_retrieval_scores_json, []),
            "strategy_mode": self.strategy_mode,
            "dominant_factor": self.dominant_factor,
            "blocking_factor": self.blocking_factor,
            "execution_readiness": self.execution_readiness,
            "response_text": self.response_text,
            "warnings_json": _safe_json_loads(self.warnings_json, []),
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "normalization_ms": self.normalization_ms,
            "pipeline_ms": self.pipeline_ms,
            "classification_ms": self.classification_ms,
            "retrieval_ms": self.retrieval_ms,
            "strategy_ms": self.strategy_ms,
            "postprocess_ms": self.postprocess_ms,
            "final_assembly_ms": self.final_assembly_ms,
            "total_ms": self.total_ms,
            "status": self.status,
            "error_message": self.error_message,
            "review_status": self.review_status,
            "feedback_signal": self.feedback_signal,
            "review_notes": self.review_notes,
        }
        if include_reviews:
            payload["reviews"] = [review.to_dict() for review in self.reviews]
        return payload


class QueryReview(Base):
    __tablename__ = "query_reviews"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    query_id = Column(String(36), ForeignKey("legal_queries.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    reviewer = Column(String(200), default="")
    review_status = Column(String(30), nullable=False, default="reviewed")
    feedback_signal = Column(String(50), default="")
    quality_score = Column(Float, nullable=True)
    legal_accuracy_score = Column(Float, nullable=True)
    clarity_score = Column(Float, nullable=True)
    usefulness_score = Column(Float, nullable=True)
    notes = Column(Text, default="")
    corrected_answer = Column(Text, default="")
    detected_issue_tags_json = Column(Text, default="[]")

    query = relationship("LegalQueryLog", back_populates="reviews")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query_id": self.query_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewer": self.reviewer,
            "review_status": self.review_status,
            "feedback_signal": self.feedback_signal,
            "quality_score": self.quality_score,
            "legal_accuracy_score": self.legal_accuracy_score,
            "clarity_score": self.clarity_score,
            "usefulness_score": self.usefulness_score,
            "notes": self.notes,
            "corrected_answer": self.corrected_answer,
            "detected_issue_tags_json": _safe_json_loads(self.detected_issue_tags_json, []),
        }
