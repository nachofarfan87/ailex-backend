from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from app.models.conversation_state_snapshot import ConversationStateSnapshot
from app.services.utc import utc_now


logger = logging.getLogger(__name__)

STATE_VERSION = 1
MAX_KNOWN_FACTS = 25
MAX_MISSING_FACTS = 20
MAX_ASKED_QUESTIONS = 12
GENERIC_VALUES = {"", "generic", "unknown", "desconocido", "sin_clasificar", "general"}
HIGH_PRIORITY_SOURCES = {
    "turn_input.facts": 5,
    "pipeline.facts": 4,
    "conversational.known_facts": 3,
    "conversation_memory.known_facts": 2,
}
CASE_TYPE_SOURCE_STRENGTH = {
    "classification.action_slug": 5,
    "case_structure.action_slug": 4,
    "case_profile.case_type": 3,
    "pipeline.action_slug": 2,
}
DOMAIN_SOURCE_STRENGTH = {
    "case_profile.case_domain": 5,
    "classification.case_domain": 4,
    "pipeline.case_domain": 3,
}
MISSING_PRIORITY_STRENGTH = {
    "critical": 3,
    "high": 3,
    "required": 3,
    "medium": 2,
    "ordinary": 2,
    "optional": 1,
    "low": 1,
}
STRUCTURAL_FACT_PATTERNS = (
    "hay_hijos",
    "hijo",
    "hija",
    "vinculo",
    "convivencia",
    "rol_procesal",
    "ingresos",
    "domicilio",
    "dni",
    "nombre",
    "cuota",
    "monto",
    "parentesco",
    "progenitor",
    "nnya",
)
EVIDENTIARY_FACT_PATTERNS = (
    "recibo",
    "comprobante",
    "mensaje",
    "whatsapp",
    "captura",
    "testigo",
    "expediente",
    "denuncia",
    "prueba",
    "documental",
    "constancia",
)
CONTEXTUAL_FACT_PATTERNS = (
    "urgencia",
    "conflicto",
    "distancia",
    "frecuencia",
    "contacto",
    "situacion",
    "contexto",
)
IDENTIFY_PATTERNS = (
    "dni",
    "nombre",
    "apellido",
    "domicilio",
    "identidad",
    "parte",
    "progenitor",
)
QUANTIFY_PATTERNS = (
    "ingresos",
    "gastos",
    "monto",
    "cuota",
    "salario",
    "haber",
)
PROVE_PATTERNS = (
    "prueba",
    "testigo",
    "recibo",
    "comprobante",
    "mensaje",
    "captura",
    "expediente",
    "denuncia",
    "constancia",
)
ENABLE_PATTERNS = (
    "convivencia",
    "hay_hijos",
    "rol_procesal",
    "vinculo",
    "domicilio",
    "notificacion",
    "jurisdiccion",
)
BLOCKING_PURPOSES = {"identify", "enable"}
CORE_FACT_PATTERNS = (
    "hay_hijos",
    "vinculo",
    "rol_procesal",
    "ingresos_otro_progenitor",
    "domicilio_nnya",
    "convivencia",
    "notificacion",
)
RELEVANT_FACT_PATTERNS = (
    "urgencia",
    "conflicto_actual",
    "gastos",
    "cuota",
    "monto",
    "ingresos",
    "expediente",
    "comprobantes",
    "prueba",
)
ACCESSORY_FACT_PATTERNS = (
    "distancia",
    "frecuencia_contacto",
    "contexto_general",
    "detalle_adicional",
)
CONTEXTUAL_ACCESSORY_PATTERNS = (
    "distancia",
    "frecuencia",
    "contexto",
)
CORE_MISSING_PATTERNS = (
    "hay_hijos",
    "vinculo",
    "rol_procesal",
    "convivencia",
    "ingresos_otro_progenitor",
    "domicilio_nnya",
    "domicilio",
    "notificacion",
)
ACCESSORY_MISSING_PATTERNS = (
    "distancia",
    "frecuencia_contacto",
    "contexto_general",
)


class ConversationStateService:
    def load_state(
        self,
        db: Session,
        *,
        conversation_id: str,
    ) -> dict[str, Any]:
        normalized_id = _clean_text(conversation_id)
        if not normalized_id:
            return {}

        snapshot = (
            db.query(ConversationStateSnapshot)
            .filter(ConversationStateSnapshot.conversation_id == normalized_id)
            .one_or_none()
        )
        if snapshot is None:
            return self._build_empty_state(normalized_id)
        return self._normalize_snapshot(snapshot.to_dict(), conversation_id=normalized_id)

    def update_conversation_state(
        self,
        db: Session,
        *,
        conversation_id: str,
        turn_input: dict[str, Any] | None,
        pipeline_payload: dict[str, Any] | None,
        response_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_id = _clean_text(conversation_id)
        if not normalized_id:
            return {}

        previous_state = self.load_state(db, conversation_id=normalized_id)
        signals = self._extract_turn_signals(
            turn_input=turn_input,
            pipeline_payload=pipeline_payload,
            response_payload=response_payload,
        )
        snapshot = self._consolidate_state(previous_state=previous_state, signals=signals)
        self._persist_state(db, snapshot=snapshot)
        return snapshot

    def _build_empty_state(self, conversation_id: str) -> dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "turn_count": 0,
            "known_facts": [],
            "missing_facts": [],
            "asked_questions": [],
            "working_case_type": "",
            "working_domain": "",
            "current_stage": "intake",
            "progress_signals": {
                "known_fact_count": 0,
                "missing_fact_count": 0,
                "question_count": 0,
                "repeated_question_risk": "low",
                "turn_count": 0,
            },
            "last_user_message_at": None,
            "last_engine_update_at": None,
            "state_version": STATE_VERSION,
        }

    def _extract_turn_signals(
        self,
        *,
        turn_input: dict[str, Any] | None,
        pipeline_payload: dict[str, Any] | None,
        response_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        safe_turn_input = _as_dict(turn_input)
        safe_pipeline = _as_dict(pipeline_payload)
        safe_response = _as_dict(response_payload)
        conversational = _as_dict(safe_pipeline.get("conversational"))
        conversation_memory = _as_dict(conversational.get("conversation_memory"))
        classification = _as_dict(safe_pipeline.get("classification"))
        case_structure = _as_dict(safe_pipeline.get("case_structure"))
        case_profile = _as_dict(safe_pipeline.get("case_profile"))
        conversational_response = _as_dict(
            safe_pipeline.get("conversational_response")
            or safe_response.get("conversational_response")
        )

        asked_questions = self._extract_questions(
            conversational=conversational,
            conversational_response=conversational_response,
        )
        return {
            "known_facts": [
                *self._extract_known_facts(_as_dict(safe_turn_input.get("facts")), source="turn_input.facts"),
                *self._extract_known_facts(_as_dict(safe_pipeline.get("facts")), source="pipeline.facts"),
                *self._extract_known_facts(_as_dict(conversational.get("known_facts")), source="conversational.known_facts"),
                *self._extract_known_facts(_as_dict(conversation_memory.get("known_facts")), source="conversation_memory.known_facts"),
            ],
            "missing_facts": self._extract_missing_facts(
                pipeline_payload=safe_pipeline,
                response_payload=safe_response,
            ),
            "asked_questions": asked_questions,
            "working_case_type_candidate": self._extract_case_type_candidate(
                classification=classification,
                case_structure=case_structure,
                case_profile=case_profile,
                pipeline_payload=safe_pipeline,
            ),
            "working_domain_candidate": self._extract_domain_candidate(
                classification=classification,
                case_profile=case_profile,
                pipeline_payload=safe_pipeline,
            ),
            "current_stage": self._extract_current_stage(safe_pipeline, safe_response),
            "repeated_question_detected": False,
            "has_user_message": bool(self._extract_last_user_message(safe_turn_input)),
        }

    def _extract_known_facts(self, facts: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw_key, raw_value in facts.items():
            if raw_value in (None, "", [], {}):
                continue
            key = _canonical_key(raw_key)
            if not key:
                continue
            result.append(
                {
                    "key": key,
                    "value": _sanitize_scalar(raw_value),
                    "status": "confirmed" if source in {"turn_input.facts", "pipeline.facts"} else "observed",
                    "source": source,
                    "fact_type": self._infer_fact_type(key=key, source=source, value=raw_value),
                    "importance": self._infer_fact_importance(
                        key=key,
                        fact_type=self._infer_fact_type(key=key, source=source, value=raw_value),
                        source=source,
                        value=raw_value,
                    ),
                }
            )
        return result

    def _extract_missing_facts(
        self,
        *,
        pipeline_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        output_modes = _as_dict(pipeline_payload.get("output_modes") or response_payload.get("output_modes"))
        user_mode = _as_dict(output_modes.get("user"))
        case_profile = _as_dict(pipeline_payload.get("case_profile"))
        case_strategy = _as_dict(pipeline_payload.get("case_strategy"))
        procedural_strategy = _as_dict(pipeline_payload.get("procedural_strategy"))
        question_engine_result = _as_dict(pipeline_payload.get("question_engine_result"))

        collected: list[dict[str, Any]] = []
        collected.extend(self._normalize_missing_items(case_profile.get("missing_critical_facts"), source="case_profile.missing_critical_facts", priority="critical"))
        collected.extend(self._normalize_missing_items(case_profile.get("missing_optional_facts"), source="case_profile.missing_optional_facts", priority="optional"))
        collected.extend(self._normalize_missing_items(case_profile.get("missing_info"), source="case_profile.missing_info", priority="ordinary"))
        collected.extend(self._normalize_missing_items(case_strategy.get("critical_missing_information"), source="case_strategy.critical_missing_information", priority="critical"))
        collected.extend(self._normalize_missing_items(case_strategy.get("ordinary_missing_information"), source="case_strategy.ordinary_missing_information", priority="ordinary"))
        collected.extend(self._normalize_missing_items(procedural_strategy.get("missing_information") or procedural_strategy.get("missing_info"), source="procedural_strategy.missing_information", priority="ordinary"))
        collected.extend(self._normalize_missing_items(user_mode.get("missing_information"), source="output_modes.user.missing_information", priority="ordinary"))
        collected.extend(self._normalize_missing_items(question_engine_result.get("critical_missing"), source="question_engine_result.critical_missing", priority="critical"))
        collected.extend(self._normalize_missing_items(question_engine_result.get("missing_facts"), source="question_engine_result.missing_facts", priority="ordinary"))
        return collected

    def _normalize_missing_items(
        self,
        raw_items: Any,
        *,
        source: str,
        priority: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in _as_list(raw_items):
            if isinstance(item, dict):
                label = _clean_text(item.get("label") or item.get("fact") or item.get("key") or item.get("name"))
                key = _canonical_key(item.get("key") or item.get("fact") or label)
                item_priority = _clean_text(item.get("priority") or priority).lower() or priority
            else:
                label = _clean_text(item)
                key = _canonical_key(label)
                item_priority = priority
            if not key or not label:
                continue
            result.append(
                {
                    "key": key,
                    "label": label,
                    "priority": item_priority,
                    "source": source,
                    "purpose": self._infer_missing_purpose(
                        key=key,
                        label=label,
                        source=source,
                        priority=item_priority,
                    ),
                }
            )
        return result

    def _extract_questions(
        self,
        *,
        conversational: dict[str, Any],
        conversational_response: dict[str, Any],
    ) -> list[str]:
        questions: list[str] = []
        direct_question = _clean_text(conversational.get("question"))
        if direct_question:
            questions.append(direct_question)
        primary_question = _clean_text(conversational_response.get("primary_question"))
        if primary_question:
            questions.append(primary_question)
        for message in _as_list(conversational_response.get("messages")):
            if not isinstance(message, dict):
                continue
            if _clean_text(message.get("type")).lower() != "question":
                continue
            question_text = _clean_text(message.get("text"))
            if question_text:
                questions.append(question_text)
        return _dedupe_strings(questions)

    def _extract_case_type_candidate(
        self,
        *,
        classification: dict[str, Any],
        case_structure: dict[str, Any],
        case_profile: dict[str, Any],
        pipeline_payload: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = [
            {"value": _clean_text(classification.get("action_slug")), "source": "classification.action_slug"},
            {"value": _clean_text(case_structure.get("action_slug")), "source": "case_structure.action_slug"},
            {"value": _clean_text(case_profile.get("case_type")), "source": "case_profile.case_type"},
            {"value": _clean_text(pipeline_payload.get("action_slug")), "source": "pipeline.action_slug"},
        ]
        return self._select_best_candidate(candidates, source_strengths=CASE_TYPE_SOURCE_STRENGTH)

    def _extract_domain_candidate(
        self,
        *,
        classification: dict[str, Any],
        case_profile: dict[str, Any],
        pipeline_payload: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = [
            {"value": _clean_text(case_profile.get("case_domain")), "source": "case_profile.case_domain"},
            {"value": _clean_text(classification.get("case_domain")), "source": "classification.case_domain"},
            {"value": _clean_text(pipeline_payload.get("case_domain")), "source": "pipeline.case_domain"},
        ]
        return self._select_best_candidate(candidates, source_strengths=DOMAIN_SOURCE_STRENGTH)

    def _select_best_candidate(
        self,
        candidates: list[dict[str, Any]],
        *,
        source_strengths: dict[str, int],
    ) -> dict[str, Any]:
        best = {"value": "", "source": "", "strength": 0}
        for candidate in candidates:
            value = _clean_text(candidate.get("value"))
            if not value or value.casefold() in GENERIC_VALUES:
                continue
            source = _clean_text(candidate.get("source"))
            strength = int(source_strengths.get(source, 1))
            specificity_bonus = len([token for token in value.split("_") if token])
            total_strength = strength * 10 + specificity_bonus
            if total_strength > int(best.get("strength") or 0):
                best = {"value": value, "source": source, "strength": total_strength}
        return best

    def _extract_current_stage(self, pipeline_payload: dict[str, Any], response_payload: dict[str, Any]) -> str:
        conversational = _as_dict(pipeline_payload.get("conversational"))
        if bool(conversational.get("should_ask_first")):
            return "clarification"
        if _clean_text(pipeline_payload.get("generated_document") or response_payload.get("generated_document")):
            return "document_generation"
        if _clean_text(response_payload.get("response_text")):
            return "advice"
        return "intake"

    def _extract_last_user_message(self, turn_input: dict[str, Any]) -> str:
        metadata = _as_dict(turn_input.get("metadata"))
        clarification_context = _as_dict(metadata.get("clarification_context"))
        return _clean_text(
            clarification_context.get("submitted_text")
            or clarification_context.get("last_user_answer")
            or turn_input.get("query")
        )

    def _consolidate_state(
        self,
        *,
        previous_state: dict[str, Any],
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        conversation_id = _clean_text(previous_state.get("conversation_id"))
        previous_known = self._normalize_known_facts(previous_state.get("known_facts"))
        merged_known = self._merge_known_facts(previous_known, signals.get("known_facts"))

        previous_questions = _as_str_list(previous_state.get("asked_questions"))
        new_questions = _as_str_list(signals.get("asked_questions"))
        repeated_question_detected = any(
            _normalize_text(question) in {_normalize_text(item) for item in previous_questions}
            for question in new_questions
        )

        previous_missing = self._normalize_missing_facts(previous_state.get("missing_facts"))
        merged_missing = self._merge_missing_facts(previous_missing, signals.get("missing_facts"), merged_known)

        turn_count = int(previous_state.get("turn_count") or 0) + 1
        working_case_type = self._choose_best_label(
            previous_value=_clean_text(previous_state.get("working_case_type")),
            candidate=_as_dict(signals.get("working_case_type_candidate")),
            source_strengths=CASE_TYPE_SOURCE_STRENGTH,
        )
        working_domain = self._choose_best_label(
            previous_value=_clean_text(previous_state.get("working_domain")),
            candidate=_as_dict(signals.get("working_domain_candidate")),
            source_strengths=DOMAIN_SOURCE_STRENGTH,
        )
        current_stage = _clean_text(signals.get("current_stage")) or _clean_text(previous_state.get("current_stage")) or "intake"
        last_user_message_at = (
            now.isoformat()
            if bool(signals.get("has_user_message"))
            else previous_state.get("last_user_message_at")
        )
        repeated_question_risk = self._repeated_question_risk(
            repeated_question_detected=repeated_question_detected,
            missing_count=len(merged_missing),
            question_count=len(previous_questions) + len(new_questions),
        )
        asked_questions = self._merge_questions(previous_questions, new_questions)

        snapshot = {
            "conversation_id": conversation_id,
            "turn_count": turn_count,
            "known_facts": merged_known,
            "missing_facts": merged_missing,
            "asked_questions": asked_questions,
            "working_case_type": working_case_type,
            "working_domain": working_domain,
            "current_stage": current_stage,
            "progress_signals": self._compute_progress_signals(
                known_facts=merged_known,
                missing_facts=merged_missing,
                asked_questions=asked_questions,
                repeated_question_risk=repeated_question_risk,
                turn_count=turn_count,
            ),
            "last_user_message_at": last_user_message_at,
            "last_engine_update_at": now.isoformat(),
            "state_version": STATE_VERSION,
            # 8.3: propagar conversation_memory del turno anterior
            "conversation_memory": _as_dict(previous_state.get("conversation_memory")),
        }
        return self._normalize_snapshot(snapshot, conversation_id=conversation_id)

    def _merge_known_facts(
        self,
        previous_items: list[dict[str, Any]],
        incoming_items: Any,
    ) -> list[dict[str, Any]]:
        best_by_key: dict[str, dict[str, Any]] = {}
        for item in [*previous_items, *self._normalize_known_facts(incoming_items)]:
            key = _canonical_key(item.get("key"))
            if not key:
                continue
            current_best = best_by_key.get(key)
            if current_best is None or self._score_known_fact(item) >= self._score_known_fact(current_best):
                best_by_key[key] = {
                    "key": key,
                    "value": _sanitize_scalar(item.get("value")),
                    "status": _clean_text(item.get("status")) or "observed",
                    "source": _clean_text(item.get("source")) or "unknown",
                    "fact_type": self._infer_fact_type(
                        key=key,
                        source=_clean_text(item.get("source")) or "unknown",
                        value=item.get("value"),
                        explicit_fact_type=item.get("fact_type"),
                    ),
                    "importance": self._infer_fact_importance(
                        key=key,
                        fact_type=self._infer_fact_type(
                            key=key,
                            source=_clean_text(item.get("source")) or "unknown",
                            value=item.get("value"),
                            explicit_fact_type=item.get("fact_type"),
                        ),
                        source=_clean_text(item.get("source")) or "unknown",
                        value=item.get("value"),
                        explicit_importance=item.get("importance"),
                    ),
                }
        ordered = sorted(
            best_by_key.values(),
            key=lambda item: (-self._score_known_fact(item), item["key"]),
        )
        return ordered[:MAX_KNOWN_FACTS]

    def _normalize_known_facts(self, raw_items: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in _as_list(raw_items):
            if not isinstance(item, dict):
                continue
            key = _canonical_key(item.get("key"))
            if not key:
                continue
            value = item.get("value")
            if value in (None, "", [], {}):
                continue
            result.append(
                {
                    "key": key,
                    "value": _sanitize_scalar(value),
                    "status": _clean_text(item.get("status")) or "observed",
                    "source": _clean_text(item.get("source")) or "unknown",
                    "fact_type": self._infer_fact_type(
                        key=key,
                        source=_clean_text(item.get("source")) or "unknown",
                        value=value,
                        explicit_fact_type=item.get("fact_type"),
                    ),
                    "importance": self._infer_fact_importance(
                        key=key,
                        fact_type=self._infer_fact_type(
                            key=key,
                            source=_clean_text(item.get("source")) or "unknown",
                            value=value,
                            explicit_fact_type=item.get("fact_type"),
                        ),
                        source=_clean_text(item.get("source")) or "unknown",
                        value=value,
                        explicit_importance=item.get("importance"),
                    ),
                }
            )
        return result

    def _score_known_fact(self, item: dict[str, Any]) -> int:
        source = _clean_text(item.get("source"))
        status = _clean_text(item.get("status")).casefold()
        key = _canonical_key(item.get("key"))
        value = item.get("value")
        score = HIGH_PRIORITY_SOURCES.get(source, 1) * 10
        if status == "confirmed":
            score += 10
        score += len(key.split("_"))
        importance = _clean_text(item.get("importance")).lower()
        if importance == "core":
            score += 8
        elif importance == "relevant":
            score += 4
        if isinstance(value, str) and len(value) > 24:
            score += 2
        return score

    def _merge_missing_facts(
        self,
        previous_items: list[dict[str, Any]],
        incoming_items: Any,
        known_facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        known_keys = {_canonical_key(item.get("key")) for item in known_facts}
        best_by_key: dict[str, dict[str, Any]] = {}
        for item in [*previous_items, *self._normalize_missing_facts(incoming_items)]:
            key = _canonical_key(item.get("key"))
            if not key or key in known_keys:
                continue
            current_best = best_by_key.get(key)
            if current_best is None or self._score_missing_fact(item) >= self._score_missing_fact(current_best):
                best_by_key[key] = {
                    "key": key,
                    "label": _clean_text(item.get("label") or key),
                    "priority": _clean_text(item.get("priority")).lower() or "ordinary",
                    "source": _clean_text(item.get("source")) or "unknown",
                    "purpose": self._infer_missing_purpose(
                        key=key,
                        label=_clean_text(item.get("label") or key),
                        source=_clean_text(item.get("source")) or "unknown",
                        priority=_clean_text(item.get("priority")).lower() or "ordinary",
                        explicit_purpose=item.get("purpose"),
                    ),
                }
        ordered = sorted(
            best_by_key.values(),
            key=lambda item: (-self._score_missing_fact(item), item["key"]),
        )
        return ordered[:MAX_MISSING_FACTS]

    def _normalize_missing_facts(self, raw_items: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in _as_list(raw_items):
            if not isinstance(item, dict):
                continue
            key = _canonical_key(item.get("key"))
            label = _clean_text(item.get("label") or key)
            if not key or not label:
                continue
            result.append(
                {
                    "key": key,
                    "label": label,
                    "priority": _clean_text(item.get("priority")).lower() or "ordinary",
                    "source": _clean_text(item.get("source")) or "unknown",
                    "purpose": self._infer_missing_purpose(
                        key=key,
                        label=label,
                        source=_clean_text(item.get("source")) or "unknown",
                        priority=_clean_text(item.get("priority")).lower() or "ordinary",
                        explicit_purpose=item.get("purpose"),
                    ),
                }
            )
        return result

    def _score_missing_fact(self, item: dict[str, Any]) -> int:
        priority = _clean_text(item.get("priority")).lower()
        source = _clean_text(item.get("source"))
        return MISSING_PRIORITY_STRENGTH.get(priority, 1) * 10 + len(source)

    def _merge_questions(self, previous_items: list[str], new_items: list[str]) -> list[str]:
        merged = _dedupe_strings([*previous_items, *new_items])
        if len(merged) <= MAX_ASKED_QUESTIONS:
            return merged
        return merged[-MAX_ASKED_QUESTIONS:]

    def _choose_best_label(
        self,
        *,
        previous_value: str,
        candidate: dict[str, Any],
        source_strengths: dict[str, int],
    ) -> str:
        candidate_value = _clean_text(candidate.get("value"))
        candidate_source = _clean_text(candidate.get("source"))
        candidate_strength = int(source_strengths.get(candidate_source, 0))
        previous_strength = 0 if previous_value.casefold() in GENERIC_VALUES else 2 + len(previous_value.split("_"))
        candidate_specificity = len(candidate_value.split("_")) if candidate_value else 0

        if candidate_value and candidate_value.casefold() not in GENERIC_VALUES:
            if candidate_strength > previous_strength:
                return candidate_value
            if candidate_strength == previous_strength and candidate_specificity > len(previous_value.split("_")):
                return candidate_value
        return previous_value

    def _repeated_question_risk(
        self,
        *,
        repeated_question_detected: bool,
        missing_count: int,
        question_count: int,
    ) -> str:
        if repeated_question_detected and question_count >= 3:
            return "high"
        if repeated_question_detected or (question_count >= 4 and missing_count <= 1):
            return "medium"
        return "low"

    def _infer_fact_type(
        self,
        *,
        key: str,
        source: str,
        value: Any,
        explicit_fact_type: Any = None,
    ) -> str:
        normalized_explicit = _clean_text(explicit_fact_type).lower()
        if normalized_explicit in {"structural", "evidentiary", "contextual"}:
            return normalized_explicit

        haystack = " ".join(
            part for part in (
                _normalize_text(key),
                _normalize_text(source),
                _normalize_text(value if isinstance(value, str) else ""),
            ) if part
        )
        if any(pattern in haystack for pattern in EVIDENTIARY_FACT_PATTERNS):
            return "evidentiary"
        if any(pattern in haystack for pattern in STRUCTURAL_FACT_PATTERNS):
            return "structural"
        if any(pattern in haystack for pattern in CONTEXTUAL_FACT_PATTERNS):
            return "contextual"
        return "contextual"

    def _infer_missing_purpose(
        self,
        *,
        key: str,
        label: str,
        source: str,
        priority: str,
        explicit_purpose: Any = None,
    ) -> str:
        normalized_explicit = _clean_text(explicit_purpose).lower()
        if normalized_explicit in {"identify", "quantify", "prove", "enable", "situational"}:
            return normalized_explicit

        haystack = " ".join(
            part for part in (
                _normalize_text(key),
                _normalize_text(label),
                _normalize_text(source),
                _normalize_text(priority),
            ) if part
        )
        if any(pattern in haystack for pattern in PROVE_PATTERNS):
            return "prove"
        if any(pattern in haystack for pattern in QUANTIFY_PATTERNS):
            return "quantify"
        if any(pattern in haystack for pattern in IDENTIFY_PATTERNS):
            return "identify"
        if any(pattern in haystack for pattern in ENABLE_PATTERNS):
            return "enable"
        if priority in {"critical", "high", "required"}:
            return "enable"
        return "situational"

    def _infer_fact_importance(
        self,
        *,
        key: str,
        fact_type: str,
        source: str,
        value: Any,
        explicit_importance: Any = None,
    ) -> str:
        normalized_explicit = _clean_text(explicit_importance).lower()
        if normalized_explicit in {"core", "relevant", "accessory"}:
            return normalized_explicit

        haystack = " ".join(
            part for part in (
                _normalize_text(key),
                _normalize_text(source),
                _normalize_text(value if isinstance(value, str) else ""),
                _normalize_text(fact_type),
            ) if part
        )
        if any(pattern in haystack for pattern in CORE_FACT_PATTERNS):
            return "core"
        if any(pattern in haystack for pattern in RELEVANT_FACT_PATTERNS):
            return "relevant"
        if any(pattern in haystack for pattern in ACCESSORY_FACT_PATTERNS):
            return "accessory"
        if fact_type == "structural":
            return "relevant"
        if fact_type == "evidentiary":
            return "relevant"
        if any(pattern in haystack for pattern in CONTEXTUAL_ACCESSORY_PATTERNS):
            return "accessory"
        return "accessory" if fact_type == "contextual" else "relevant"

    def _infer_missing_importance(
        self,
        *,
        key: str,
        purpose: str,
        priority: str,
        label: str,
    ) -> str:
        haystack = " ".join(
            part for part in (
                _normalize_text(key),
                _normalize_text(label),
                _normalize_text(purpose),
                _normalize_text(priority),
            ) if part
        )
        if any(pattern in haystack for pattern in CORE_MISSING_PATTERNS):
            return "core"
        if any(pattern in haystack for pattern in ACCESSORY_MISSING_PATTERNS):
            return "accessory"
        if purpose in {"identify", "enable"}:
            return "core"
        if purpose in {"quantify", "prove"}:
            return "relevant"
        return "accessory" if priority == "low" else "relevant"

    def _compute_progress_signals(
        self,
        *,
        known_facts: list[dict[str, Any]],
        missing_facts: list[dict[str, Any]],
        asked_questions: list[str],
        repeated_question_risk: str,
        turn_count: int,
    ) -> dict[str, Any]:
        structural_fact_count = sum(1 for item in known_facts if item.get("fact_type") == "structural")
        evidentiary_fact_count = sum(1 for item in known_facts if item.get("fact_type") == "evidentiary")
        contextual_fact_count = sum(1 for item in known_facts if item.get("fact_type") == "contextual")
        core_fact_count = sum(1 for item in known_facts if item.get("importance") == "core")
        relevant_fact_count = sum(1 for item in known_facts if item.get("importance") == "relevant")
        accessory_fact_count = sum(1 for item in known_facts if item.get("importance") == "accessory")
        blocking_missing = self._has_blocking_missing(missing_facts)
        case_completeness = self._compute_case_completeness(
            core_fact_count=core_fact_count,
            relevant_fact_count=relevant_fact_count,
            missing_facts=missing_facts,
            blocking_missing=blocking_missing,
        )
        return {
            "known_fact_count": len(known_facts),
            "missing_fact_count": len(missing_facts),
            "question_count": len(asked_questions),
            "repeated_question_risk": repeated_question_risk,
            "turn_count": turn_count,
            "structural_fact_count": structural_fact_count,
            "evidentiary_fact_count": evidentiary_fact_count,
            "contextual_fact_count": contextual_fact_count,
            "core_fact_count": core_fact_count,
            "relevant_fact_count": relevant_fact_count,
            "accessory_fact_count": accessory_fact_count,
            "blocking_missing": blocking_missing,
            "case_completeness": case_completeness,
        }

    def _has_blocking_missing(self, missing_facts: list[dict[str, Any]]) -> bool:
        for item in missing_facts:
            priority = _clean_text(item.get("priority")).lower()
            purpose = _clean_text(item.get("purpose")).lower()
            importance = self._infer_missing_importance(
                key=_canonical_key(item.get("key")),
                purpose=purpose,
                priority=priority,
                label=_clean_text(item.get("label")),
            )
            if purpose in BLOCKING_PURPOSES and importance == "core":
                return True
            if priority in {"critical", "high", "required"} and importance != "accessory" and purpose != "situational":
                return True
        return False

    def _compute_case_completeness(
        self,
        *,
        core_fact_count: int,
        relevant_fact_count: int,
        missing_facts: list[dict[str, Any]],
        blocking_missing: bool,
    ) -> str:
        missing_count = len(missing_facts)
        core_missing_count = sum(
            1
            for item in missing_facts
            if self._infer_missing_importance(
                key=_canonical_key(item.get("key")),
                purpose=_clean_text(item.get("purpose")).lower(),
                priority=_clean_text(item.get("priority")).lower(),
                label=_clean_text(item.get("label")),
            ) == "core"
        )
        if core_fact_count < 2 or core_missing_count > 0 or blocking_missing:
            return "low"
        if core_fact_count >= 3 and missing_count <= 2:
            return "high"
        return "medium"

    def _normalize_snapshot(self, snapshot: dict[str, Any], *, conversation_id: str) -> dict[str, Any]:
        normalized = self._build_empty_state(conversation_id)
        normalized.update(_as_dict(snapshot))
        normalized["conversation_id"] = conversation_id
        normalized["turn_count"] = int(normalized.get("turn_count") or 0)
        normalized["known_facts"] = self._normalize_known_facts(normalized.get("known_facts"))
        normalized["missing_facts"] = self._normalize_missing_facts(normalized.get("missing_facts"))
        normalized["asked_questions"] = self._merge_questions([], _as_str_list(normalized.get("asked_questions")))
        normalized["working_case_type"] = _clean_text(normalized.get("working_case_type"))
        normalized["working_domain"] = _clean_text(normalized.get("working_domain"))
        normalized["current_stage"] = _clean_text(normalized.get("current_stage")) or "intake"
        normalized["state_version"] = int(normalized.get("state_version") or STATE_VERSION)
        normalized["progress_signals"] = self._compute_progress_signals(
            known_facts=normalized["known_facts"],
            missing_facts=normalized["missing_facts"],
            asked_questions=normalized["asked_questions"],
            repeated_question_risk=_clean_text(
                _as_dict(normalized.get("progress_signals")).get("repeated_question_risk")
            )
            or "low",
            turn_count=int(normalized.get("turn_count") or 0),
        )
        normalized["last_user_message_at"] = _clean_text(normalized.get("last_user_message_at")) or None
        normalized["last_engine_update_at"] = _clean_text(normalized.get("last_engine_update_at")) or None
        return normalized

    def _persist_state(self, db: Session, *, snapshot: dict[str, Any]) -> None:
        conversation_id = _clean_text(snapshot.get("conversation_id"))
        record = (
            db.query(ConversationStateSnapshot)
            .filter(ConversationStateSnapshot.conversation_id == conversation_id)
            .one_or_none()
        )
        if record is None:
            record = ConversationStateSnapshot(conversation_id=conversation_id)
            db.add(record)

        record.state_version = int(snapshot.get("state_version") or STATE_VERSION)
        record.snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        record.last_user_message_at = _parse_iso_datetime(snapshot.get("last_user_message_at"))
        record.last_engine_update_at = _parse_iso_datetime(snapshot.get("last_engine_update_at"))
        db.flush()

    def update_conversation_memory(
        self,
        db: Session,
        *,
        conversation_id: str,
        conversation_memory: dict[str, Any],
    ) -> None:
        """
        Actualiza solo el campo conversation_memory del snapshot persistido.
        Llamado después de que dialogue_policy y composer ya corrieron (Fase 8.3).
        No modifica ningún otro campo del snapshot.
        """
        normalized_id = _clean_text(conversation_id)
        if not normalized_id:
            return
        record = (
            db.query(ConversationStateSnapshot)
            .filter(ConversationStateSnapshot.conversation_id == normalized_id)
            .one_or_none()
        )
        if record is None:
            return
        try:
            snapshot = json.loads(record.snapshot_json)
        except (json.JSONDecodeError, TypeError):
            snapshot = {}
        snapshot["conversation_memory"] = dict(conversation_memory or {})
        record.snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        db.flush()


conversation_state_service = ConversationStateService()


def _parse_iso_datetime(value: Any):
    text = _clean_text(value)
    if not text:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(text)
    except ValueError:
        logger.debug("No se pudo parsear timestamp de conversation state.", extra={"value": text})
        return None


def _sanitize_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = _clean_text(value)
        return text[:240] if len(text) > 240 else text
    return _clean_text(value)


def _canonical_key(value: Any) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return normalized[:80]


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.casefold()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(_clean_text(item))
    return result
