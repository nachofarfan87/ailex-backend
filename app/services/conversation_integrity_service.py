from __future__ import annotations

import re
from typing import Any


_SLOT_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "aportes_actuales": (
        "aportes_actuales",
        "aporte_actual",
        "aporta_actualmente",
        "otro_progenitor_aporta_actualmente",
        "cumplimiento_alimentos",
        "pago_actual_alimentos",
        "pagos_actuales",
        "cuota_actual",
        "incumplimiento_actual",
    ),
    "ingresos_otro_progenitor": (
        "ingresos_otro_progenitor",
        "ingresos",
        "actividad_otro_progenitor",
        "trabajo_otro_progenitor",
        "otro_progenitor_tiene_ingresos",
    ),
    "domicilio_relevante": (
        "domicilio_relevante",
        "domicilio",
        "jurisdiccion",
        "competencia",
        "ubicacion_otro_progenitor",
        "domicilio_otro_progenitor",
        "notificacion",
    ),
    "convivencia": (
        "convivencia",
        "convivencia_hijo",
        "convivencia_con_hijo",
        "hijo_convive_consultante",
        "cuidado_personal_de_hecho",
    ),
    "modalidad_divorcio": (
        "modalidad_divorcio",
        "divorcio_modalidad",
        "tipo_divorcio",
    ),
}

_QUESTION_SLOT_PATTERNS: dict[str, tuple[str, ...]] = {
    "aportes_actuales": (
        r"aportando algo actualmente",
        r"pasa algo de plata",
        r"paga alimentos",
        r"aporta algo",
        r"cumple con la cuota",
    ),
    "ingresos_otro_progenitor": (
        r"ingresos del otro progenitor",
        r"actividad laboral",
        r"cuanto gana",
        r"tiene ingresos",
    ),
    "domicilio_relevante": (
        r"domicilio relevante",
        r"en que provincia",
        r"en que jurisdiccion",
        r"competencia",
        r"ubicar al otro progenitor",
    ),
    "convivencia": (
        r"vive con vos",
        r"convive",
        r"esta a tu cargo",
    ),
    "modalidad_divorcio": (
        r"divorcio seria unilateral",
        r"divorcio sería unilateral",
        r"de comun acuerdo",
        r"de común acuerdo",
    ),
}

_CONCEPT_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "family_link_birth": (
        "partida de nacimiento",
        "vinculo filial",
        "grupo familiar",
    ),
    "income_support": (
        "ingresos del progenitor",
        "ingresos del obligado",
        "indicios de ingresos",
        "recibos de sueldo",
        "ingresos del otro progenitor",
    ),
    "child_expenses": (
        "gastos del hijo",
        "detalle de gastos",
        "comprobantes de gastos",
        "gastos ordinarios",
        "gastos extraordinarios",
    ),
}

_CLOSING_STRATEGY_MODES = frozenset(
    {
        "close_without_more_questions",
        "action_first_no_followup",
        "ready_without_followup",
    }
)


class ConversationIntegrityService:
    def canonicalize_slot(
        self,
        value: Any = None,
        *,
        question: str = "",
        need_key: str = "",
        resolved_by_fact_key: str = "",
    ) -> str:
        for candidate in (resolved_by_fact_key, need_key, value):
            canonical = self._canonicalize_slot_from_key(candidate)
            if canonical:
                return canonical
        return self._canonicalize_slot_from_question(question)

    def canonicalize_concept_key(self, value: Any) -> str:
        normalized = self._normalize_text(value)
        if not normalized:
            return ""
        for canonical, aliases in _CONCEPT_ALIAS_GROUPS.items():
            if any(alias in normalized for alias in aliases):
                return canonical
        return ""

    def build_integrity_state(
        self,
        *,
        conversation_state: dict[str, Any] | None,
        case_memory: dict[str, Any] | None,
    ) -> dict[str, Any]:
        state = dict(conversation_state or {})
        memory = dict(case_memory or {})

        asked_slots: set[str] = set()
        answered_slots: set[str] = set()
        resolved_slots: set[str] = set()

        for question in list(state.get("asked_questions") or []):
            canonical = self.canonicalize_slot(question=question)
            if canonical:
                asked_slots.add(canonical)

        conversation_memory = dict(state.get("conversation_memory") or {})
        for key in list(conversation_memory.get("asked_missing_keys_history") or []):
            canonical = self.canonicalize_slot(value=key)
            if canonical:
                asked_slots.add(canonical)

        for answer_entry in list(conversation_memory.get("user_answers") or []):
            if not isinstance(answer_entry, dict):
                continue
            canonical = self.canonicalize_slot(
                value=answer_entry.get("slot"),
                question=str(answer_entry.get("question") or ""),
            )
            if canonical:
                answered_slots.add(canonical)

        for item in list(state.get("known_facts") or []):
            if not isinstance(item, dict):
                continue
            canonical = self.canonicalize_slot(
                value=item.get("key") or item.get("fact_key"),
            )
            if canonical and self._has_meaningful_value(item.get("value")):
                resolved_slots.add(canonical)

        for key, value in dict(state.get("known_facts_map") or {}).items():
            canonical = self.canonicalize_slot(value=key)
            if canonical and self._has_meaningful_value(value):
                resolved_slots.add(canonical)

        for key, payload in dict(memory.get("facts") or {}).items():
            canonical = self.canonicalize_slot(value=key)
            fact_value = dict(payload or {}).get("value") if isinstance(payload, dict) else payload
            if canonical and self._has_meaningful_value(fact_value):
                resolved_slots.add(canonical)

        slot_statuses = self._build_slot_statuses(
            asked_slots=asked_slots,
            answered_slots=answered_slots,
            resolved_slots=resolved_slots,
        )
        blocked_slots = {
            slot
            for slot, status in slot_statuses.items()
            if status in {"resolved", "partial"}
        }
        return {
            "asked_slots": sorted(asked_slots),
            "answered_slots": sorted(answered_slots),
            "resolved_slots": sorted(resolved_slots),
            "slot_statuses": dict(sorted(slot_statuses.items())),
            "blocked_slots": sorted(blocked_slots),
        }

    def should_allow_followup(
        self,
        *,
        api_payload: dict[str, Any],
        question: str = "",
        need_key: str = "",
        resolved_by_fact_key: str = "",
    ) -> dict[str, Any]:
        strategy_profile = dict(api_payload.get("strategy_composition_profile") or {})
        smart_strategy = dict(api_payload.get("smart_strategy") or {})
        case_progress = dict(api_payload.get("case_progress") or {})
        case_followup = dict(api_payload.get("case_followup") or {})
        integrity_state = self.build_integrity_state(
            conversation_state=dict(api_payload.get("conversation_state") or {}),
            case_memory=dict(api_payload.get("case_memory") or {}),
        )
        canonical_slot = self.canonicalize_slot(
            question=question,
            need_key=need_key or str(case_followup.get("need_key") or ""),
            resolved_by_fact_key=resolved_by_fact_key,
        )

        if not bool(strategy_profile.get("allow_followup", True)):
            return self._decision(False, "strategy_profile_disallows_followup", canonical_slot, integrity_state)

        strategy_mode = str(smart_strategy.get("strategy_mode") or "").strip().lower()
        if strategy_mode in _CLOSING_STRATEGY_MODES:
            return self._decision(False, "strategy_mode_closes_without_questions", canonical_slot, integrity_state)

        if not bool(case_followup.get("should_ask", True)) and "sin follow-up" in self._normalize_text(case_followup.get("reason")):
            return self._decision(False, "case_followup_already_closed", canonical_slot, integrity_state)

        readiness_label = str(case_progress.get("readiness_label") or "").strip().lower()
        critical_gap_count = len(list(case_progress.get("critical_gaps") or []))
        has_blockers = bool(list(case_progress.get("blocking_issues") or []))
        next_step_type = str(case_progress.get("next_step_type") or "").strip().lower()
        if next_step_type != "resolve_contradiction" and (
            next_step_type == "execute"
            or (readiness_label == "high" and critical_gap_count == 0 and not has_blockers)
        ):
            return self._decision(False, "readiness_allows_advancing_without_followup", canonical_slot, integrity_state)

        if canonical_slot and canonical_slot in set(integrity_state["blocked_slots"]):
            status = str(dict(integrity_state.get("slot_statuses") or {}).get(canonical_slot) or "")
            if status == "resolved":
                return self._decision(False, "slot_already_resolved", canonical_slot, integrity_state)
            if status == "partial":
                return self._decision(False, "slot_already_answered_partially", canonical_slot, integrity_state)

        return self._decision(True, "", canonical_slot, integrity_state)

    def _canonicalize_slot_from_key(self, value: Any) -> str:
        normalized = self._normalize_text(value)
        if not normalized:
            return ""
        if "::" in normalized:
            normalized = normalized.rsplit("::", 1)[-1]
        normalized = re.sub(r"[^a-z0-9_ ]+", " ", normalized).strip()

        for canonical, aliases in _SLOT_ALIAS_GROUPS.items():
            if normalized == canonical or normalized in aliases:
                return canonical
            if any(alias in normalized for alias in aliases):
                return canonical
            if self._token_overlap(normalized, aliases):
                return canonical
        return normalized.replace(" ", "_") if normalized else ""

    def _canonicalize_slot_from_question(self, question: str) -> str:
        normalized = self._normalize_text(question)
        if not normalized:
            return ""
        for canonical, patterns in _QUESTION_SLOT_PATTERNS.items():
            if any(re.search(pattern, normalized) for pattern in patterns):
                return canonical
        fallback = self._canonicalize_slot_from_key(normalized)
        if fallback:
            return fallback
        return ""

    @staticmethod
    def _build_slot_statuses(
        *,
        asked_slots: set[str],
        answered_slots: set[str],
        resolved_slots: set[str],
    ) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for slot in asked_slots:
            statuses[slot] = "unknown"
        for slot in answered_slots:
            statuses[slot] = "partial"
        for slot in resolved_slots:
            statuses[slot] = "resolved"
        return statuses

    @staticmethod
    def _token_overlap(text: str, aliases: tuple[str, ...]) -> bool:
        text_tokens = {
            token for token in re.split(r"[^a-z0-9]+", text)
            if len(token) >= 4
        }
        if not text_tokens:
            return False
        for alias in aliases:
            alias_tokens = {
                token for token in re.split(r"[^a-z0-9]+", alias)
                if len(token) >= 4
            }
            if alias_tokens and len(text_tokens & alias_tokens) >= max(1, min(2, len(alias_tokens))):
                return True
        return False

    @staticmethod
    def _has_meaningful_value(value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str):
            normalized = ConversationIntegrityService._normalize_text(value)
            return normalized not in {"desconocido", "sin dato", "pendiente"}
        return True

    @staticmethod
    def _normalize_text(value: Any) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "").strip().casefold())
        return normalized

    @staticmethod
    def _decision(
        allowed: bool,
        reason: str,
        canonical_slot: str,
        integrity_state: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "should_allow_followup": allowed,
            "reason": reason,
            "canonical_slot": canonical_slot,
            "integrity_state": integrity_state,
        }


conversation_integrity_service = ConversationIntegrityService()


def canonicalize_slot(
    value: Any = None,
    *,
    question: str = "",
    need_key: str = "",
    resolved_by_fact_key: str = "",
) -> str:
    return conversation_integrity_service.canonicalize_slot(
        value=value,
        question=question,
        need_key=need_key,
        resolved_by_fact_key=resolved_by_fact_key,
    )


def canonicalize_concept_key(value: Any) -> str:
    return conversation_integrity_service.canonicalize_concept_key(value)


def build_integrity_state(
    *,
    conversation_state: dict[str, Any] | None,
    case_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    return conversation_integrity_service.build_integrity_state(
        conversation_state=conversation_state,
        case_memory=case_memory,
    )


def should_allow_followup(
    *,
    api_payload: dict[str, Any],
    question: str = "",
    need_key: str = "",
    resolved_by_fact_key: str = "",
) -> dict[str, Any]:
    return conversation_integrity_service.should_allow_followup(
        api_payload=api_payload,
        question=question,
        need_key=need_key,
        resolved_by_fact_key=resolved_by_fact_key,
    )
