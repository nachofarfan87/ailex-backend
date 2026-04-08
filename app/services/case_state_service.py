# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\case_state_service.py
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.case_state import CaseEvent, CaseFact, CaseNeed, ConversationCaseState


logger = logging.getLogger(__name__)

ACTIVE_FACT_STATUSES = {"confirmed", "probable"}


class CaseStateService:
    def get_or_create_case_state(
        self,
        db: Session,
        conversation_id: str,
    ) -> ConversationCaseState:
        normalized_id = _clean_text(conversation_id)
        state = (
            db.query(ConversationCaseState)
            .filter(ConversationCaseState.conversation_id == normalized_id)
            .one_or_none()
        )
        if state is not None:
            return state

        state = ConversationCaseState(
            conversation_id=normalized_id,
            secondary_goals_json="[]",
            status="active",
            case_stage="consulta_inicial",
        )
        db.add(state)
        db.flush()
        return state

    def get_case_facts(self, db: Session, conversation_id: str) -> list[CaseFact]:
        normalized_id = _clean_text(conversation_id)
        return list(
            db.query(CaseFact)
            .filter(CaseFact.conversation_id == normalized_id)
            .order_by(CaseFact.updated_at.asc(), CaseFact.created_at.asc())
            .all()
        )

    def get_case_needs(self, db: Session, conversation_id: str) -> list[CaseNeed]:
        normalized_id = _clean_text(conversation_id)
        return list(
            db.query(CaseNeed)
            .filter(CaseNeed.conversation_id == normalized_id)
            .order_by(CaseNeed.updated_at.asc(), CaseNeed.created_at.asc())
            .all()
        )

    def upsert_case_fact(
        self,
        db: Session,
        *,
        conversation_id: str,
        fact_key: str,
        fact_value: Any,
        value_type: str = "",
        domain: str = "",
        source_type: str = "pipeline_inferred",
        confidence: float | None = None,
        status: str = "",
        turn_index: int | None = None,
        evidence_excerpt: str = "",
    ) -> CaseFact:
        normalized_conversation_id = _clean_text(conversation_id)
        normalized_fact_key = _canonical_key(fact_key)
        if not normalized_conversation_id or not normalized_fact_key:
            raise ValueError("conversation_id y fact_key son obligatorios")

        fact = (
            db.query(CaseFact)
            .filter(
                CaseFact.conversation_id == normalized_conversation_id,
                CaseFact.fact_key == normalized_fact_key,
            )
            .one_or_none()
        )
        normalized_source = _clean_text(source_type) or "pipeline_inferred"
        normalized_status = _clean_text(status) or self._default_fact_status(normalized_source)
        normalized_value_type = _clean_text(value_type) or _infer_value_type(fact_value)
        normalized_confidence = self._normalize_confidence(confidence, normalized_source, normalized_status)
        serialized_value = json.dumps(fact_value, ensure_ascii=False)

        if fact is None:
            fact = CaseFact(
                conversation_id=normalized_conversation_id,
                fact_key=normalized_fact_key,
                fact_value_json=serialized_value,
                value_type=normalized_value_type,
                domain=_clean_text(domain),
                source_type=normalized_source,
                confidence=normalized_confidence,
                status=normalized_status,
                first_seen_turn=turn_index,
                last_updated_turn=turn_index,
                evidence_excerpt=_clean_text(evidence_excerpt),
            )
            db.add(fact)
            db.flush()
            return fact

        previous_value = _safe_json_loads(fact.fact_value_json, None)
        previous_source = _clean_text(fact.source_type)
        previous_status = _clean_text(fact.status) or "probable"

        if _values_equal(previous_value, fact_value):
            fact.value_type = normalized_value_type
            fact.domain = _prefer_nonempty(_clean_text(domain), fact.domain)
            fact.source_type = self._prefer_source(previous_source, normalized_source)
            fact.confidence = max(float(fact.confidence or 0.0), normalized_confidence)
            fact.status = self._prefer_status(previous_status, normalized_status)
            fact.last_updated_turn = turn_index if turn_index is not None else fact.last_updated_turn
            fact.evidence_excerpt = _prefer_nonempty(_clean_text(evidence_excerpt), fact.evidence_excerpt)
            db.flush()
            return fact

        previous_strength = _source_strength(previous_source)
        incoming_strength = _source_strength(normalized_source)
        should_override = incoming_strength > previous_strength or (
            incoming_strength == previous_strength and normalized_confidence >= float(fact.confidence or 0.0)
        )

        if should_override:
            self.append_case_event(
                db,
                conversation_id=normalized_conversation_id,
                event_type="fact_value_changed",
                payload={
                    "fact_key": normalized_fact_key,
                    "previous_value": previous_value,
                    "new_value": fact_value,
                    "previous_source_type": previous_source,
                    "new_source_type": normalized_source,
                },
            )
            fact.fact_value_json = serialized_value
            fact.value_type = normalized_value_type
            fact.domain = _prefer_nonempty(_clean_text(domain), fact.domain)
            fact.source_type = normalized_source
            fact.confidence = normalized_confidence
            fact.status = normalized_status
            fact.last_updated_turn = turn_index if turn_index is not None else fact.last_updated_turn
            fact.evidence_excerpt = _prefer_nonempty(_clean_text(evidence_excerpt), fact.evidence_excerpt)
            db.flush()
            return fact

        self.append_case_event(
            db,
            conversation_id=normalized_conversation_id,
            event_type="fact_contradiction_detected",
            payload={
                "fact_key": normalized_fact_key,
                "stored_value": previous_value,
                "incoming_value": fact_value,
                "stored_source_type": previous_source,
                "incoming_source_type": normalized_source,
            },
        )
        fact.status = "contradicted" if previous_status == "probable" else previous_status
        fact.last_updated_turn = turn_index if turn_index is not None else fact.last_updated_turn
        db.flush()
        return fact

    def upsert_case_need(
        self,
        db: Session,
        *,
        conversation_id: str,
        need_key: str,
        category: str = "",
        priority: str = "",
        status: str = "open",
        reason: str = "",
        suggested_question: str = "",
        resolved_by_fact_key: str | None = None,
    ) -> CaseNeed:
        normalized_conversation_id = _clean_text(conversation_id)
        normalized_need_key = _canonical_need_key(need_key)
        if not normalized_conversation_id or not normalized_need_key:
            raise ValueError("conversation_id y need_key son obligatorios")

        need = (
            db.query(CaseNeed)
            .filter(
                CaseNeed.conversation_id == normalized_conversation_id,
                CaseNeed.need_key == normalized_need_key,
            )
            .one_or_none()
        )
        normalized_status = _clean_text(status) or "open"
        normalized_resolved_fact = _canonical_key(resolved_by_fact_key)

        if need is None:
            need = CaseNeed(
                conversation_id=normalized_conversation_id,
                need_key=normalized_need_key,
                category=_clean_text(category),
                priority=_clean_text(priority) or "normal",
                status=normalized_status,
                reason=_clean_text(reason),
                suggested_question=_clean_text(suggested_question),
                resolved_by_fact_key=normalized_resolved_fact or None,
            )
            db.add(need)
            db.flush()
            return need

        if need.status == "resolved" and normalized_status != "resolved":
            if need.resolved_by_fact_key and self._fact_is_active(
                db,
                conversation_id=normalized_conversation_id,
                fact_key=need.resolved_by_fact_key,
            ):
                db.flush()
                return need
            has_meaningful_change = any(
                (
                    _clean_text(category) and _clean_text(category) != _clean_text(need.category),
                    _clean_text(priority) and _clean_text(priority) != _clean_text(need.priority),
                    _clean_text(reason) and _clean_text(reason) != _clean_text(need.reason),
                    _clean_text(suggested_question) and _clean_text(suggested_question) != _clean_text(need.suggested_question),
                )
            )
            if has_meaningful_change:
                need.status = normalized_status
                need.resolved_by_fact_key = normalized_resolved_fact or None

        need.category = _prefer_nonempty(_clean_text(category), need.category)
        need.priority = _prefer_nonempty(_clean_text(priority), need.priority or "normal")
        need.reason = _prefer_nonempty(_clean_text(reason), need.reason)
        need.suggested_question = _prefer_nonempty(_clean_text(suggested_question), need.suggested_question)
        if normalized_status == "resolved":
            need.status = "resolved"
            need.resolved_by_fact_key = normalized_resolved_fact or need.resolved_by_fact_key
        elif need.status != "resolved":
            need.status = normalized_status
        db.flush()
        return need

    def resolve_need(
        self,
        db: Session,
        *,
        conversation_id: str,
        need_key: str,
        fact_key: str,
    ) -> CaseNeed | None:
        normalized_conversation_id = _clean_text(conversation_id)
        normalized_need_key = _canonical_need_key(need_key)
        normalized_fact_key = _canonical_key(fact_key)
        need = (
            db.query(CaseNeed)
            .filter(
                CaseNeed.conversation_id == normalized_conversation_id,
                CaseNeed.need_key == normalized_need_key,
            )
            .one_or_none()
        )
        if need is None:
            return None

        need.status = "resolved"
        need.resolved_by_fact_key = normalized_fact_key or need.resolved_by_fact_key
        db.flush()
        return need

    def fact_is_active(
        self,
        db: Session,
        *,
        conversation_id: str,
        fact_key: str,
    ) -> bool:
        return self._fact_is_active(db, conversation_id=conversation_id, fact_key=fact_key)

    def append_case_event(
        self,
        db: Session,
        *,
        conversation_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> CaseEvent:
        event = CaseEvent(
            conversation_id=_clean_text(conversation_id),
            event_type=_clean_text(event_type),
            payload_json=json.dumps(dict(payload or {}), ensure_ascii=False),
        )
        db.add(event)
        db.flush()
        return event

    def update_case_state(
        self,
        db: Session,
        *,
        conversation_id: str,
        case_type: str | None = None,
        case_stage: str | None = None,
        primary_goal: str | None = None,
        secondary_goals_json: list[Any] | None = None,
        jurisdiction: str | None = None,
        status: str | None = None,
        confidence_score: float | None = None,
        summary_text: str | None = None,
        last_user_turn_at: datetime | str | None = None,
        last_system_turn_at: datetime | str | None = None,
    ) -> ConversationCaseState:
        state = self.get_or_create_case_state(db, conversation_id)
        if _clean_text(case_type):
            state.case_type = _clean_text(case_type)
        if _clean_text(case_stage):
            state.case_stage = _clean_text(case_stage)
        if _clean_text(primary_goal):
            state.primary_goal = _clean_text(primary_goal)
        if secondary_goals_json is not None:
            state.secondary_goals_json = json.dumps(list(secondary_goals_json), ensure_ascii=False)
        if _clean_text(jurisdiction):
            state.jurisdiction = _clean_text(jurisdiction)
        if _clean_text(status):
            state.status = _clean_text(status)
        if confidence_score is not None:
            state.confidence_score = round(float(confidence_score), 4)
        if _clean_text(summary_text):
            state.summary_text = _clean_text(summary_text)
        parsed_last_user = _parse_datetime(last_user_turn_at)
        parsed_last_system = _parse_datetime(last_system_turn_at)
        if parsed_last_user is not None:
            state.last_user_turn_at = parsed_last_user
        if parsed_last_system is not None:
            state.last_system_turn_at = parsed_last_system
        db.flush()
        return state

    def update_case_summary_text(
        self,
        db: Session,
        *,
        conversation_id: str,
        summary_text: str,
    ) -> ConversationCaseState:
        return self.update_case_state(
            db,
            conversation_id=conversation_id,
            summary_text=summary_text,
        )

    def build_case_snapshot(self, db: Session, conversation_id: str) -> dict[str, Any]:
        state = self.get_or_create_case_state(db, conversation_id)
        facts = self.get_case_facts(db, conversation_id)
        needs = self.get_case_needs(db, conversation_id)
        events = list(
            db.query(CaseEvent)
            .filter(CaseEvent.conversation_id == _clean_text(conversation_id))
            .order_by(CaseEvent.created_at.desc())
            .all()
        )

        confirmed_facts = {
            fact.fact_key: _safe_json_loads(fact.fact_value_json, None)
            for fact in facts
            if _clean_text(fact.status) == "confirmed"
        }
        probable_facts = {
            fact.fact_key: _safe_json_loads(fact.fact_value_json, None)
            for fact in facts
            if _clean_text(fact.status) == "probable"
        }
        open_needs = [
            need.to_dict()
            for need in needs
            if _clean_text(need.status) not in {"resolved", "closed"}
        ]

        return {
            "case_state": state.to_dict(),
            "confirmed_facts": confirmed_facts,
            "probable_facts": probable_facts,
            "open_needs": open_needs,
            "contradictions": self._build_contradictions(facts=facts, events=events),
            "recommended_followup": None,
        }

    def _default_fact_status(self, source_type: str) -> str:
        return "confirmed" if _source_strength(source_type) >= 3 else "probable"

    def _prefer_status(self, previous_status: str, incoming_status: str) -> str:
        rank = {"confirmed": 4, "probable": 3, "stale": 2, "contradicted": 1}
        return incoming_status if rank.get(incoming_status, 0) >= rank.get(previous_status, 0) else previous_status

    def _prefer_source(self, previous_source: str, incoming_source: str) -> str:
        return incoming_source if _source_strength(incoming_source) >= _source_strength(previous_source) else previous_source

    def _normalize_confidence(self, confidence: float | None, source_type: str, status: str) -> float:
        if confidence is not None:
            return round(max(0.0, min(1.0, float(confidence))), 4)
        if status == "confirmed":
            return 0.95 if _source_strength(source_type) >= 3 else 0.85
        return 0.65 if _source_strength(source_type) >= 2 else 0.5

    def _fact_is_active(self, db: Session, *, conversation_id: str, fact_key: str) -> bool:
        fact = (
            db.query(CaseFact)
            .filter(
                CaseFact.conversation_id == _clean_text(conversation_id),
                CaseFact.fact_key == _canonical_key(fact_key),
            )
            .one_or_none()
        )
        if fact is None:
            return False
        return _clean_text(fact.status) in ACTIVE_FACT_STATUSES

    def _build_contradictions(
        self,
        *,
        facts: list[CaseFact],
        events: list[CaseEvent],
    ) -> list[dict[str, Any]]:
        contradictions: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for fact in facts:
            if _clean_text(fact.status) != "contradicted":
                continue
            contradictions.append(
                {
                    "fact_key": fact.fact_key,
                    "current_value": _safe_json_loads(fact.fact_value_json, None),
                    "source_type": fact.source_type,
                }
            )
            seen_keys.add(fact.fact_key)

        for event in events:
            if event.event_type != "fact_contradiction_detected":
                continue
            payload = _safe_json_loads(event.payload_json, {})
            fact_key = _canonical_key(payload.get("fact_key"))
            if not fact_key or fact_key in seen_keys:
                continue
            seen_keys.add(fact_key)
            contradictions.append(
                {
                    "fact_key": fact_key,
                    "stored_value": payload.get("stored_value") or payload.get("previous_value"),
                    "incoming_value": payload.get("incoming_value") or payload.get("new_value"),
                    "event_type": event.event_type,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
            )
        return contradictions


case_state_service = CaseStateService()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _canonical_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", _clean_text(value).casefold()).strip("_")
    return normalized[:120]


def _canonical_need_key(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if "::" in text:
        namespace, raw_key = text.split("::", 1)
        normalized_namespace = _canonical_key(namespace)
        normalized_key = _canonical_key(raw_key)
        if normalized_namespace and normalized_key:
            return f"{normalized_namespace}::{normalized_key}"
        return normalized_key
    return _canonical_key(text)


def _safe_json_loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        logger.debug("No se pudo parsear timestamp de case state.", extra={"value": text})
        return None


def _prefer_nonempty(incoming: str, existing: str | None) -> str:
    return incoming if incoming else _clean_text(existing)


def _infer_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


def _source_strength(source_type: Any) -> int:
    normalized = _clean_text(source_type).casefold()
    if "user_explicit" in normalized:
        return 4
    if "explicit" in normalized:
        return 3
    if "pipeline" in normalized:
        return 2
    return 1


def _values_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)
