# backend/app/services/conversational_interpretation_service.py
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.conversation_integrity_service import canonicalize_slot
from app.services.conversational.conversational_quality import simplify_question_text
from app.services.conversational.memory_service import update_memory_with_user_answer

_USER_CANNOT_ANSWER_PATTERNS = (
    "no se",
    "no lo se",
    "no sabria",
    "no sabria decirte",
    "no tengo ese dato",
    "no tengo ese dato ahora",
    "no tengo idea",
    "ni idea",
    "desconozco",
    "no recuerdo",
    "no estoy seguro",
    "no estoy segura",
)

_AMBIGUOUS_PATTERNS = (
    "depende",
    "mas o menos",
    "más o menos",
    "creo que si",
    "creo que sí",
    "creo que no",
    "puede ser",
    "quizas",
    "quizás",
    "tal vez",
)

_TENSION_PATTERNS = (
    "pero",
    "aunque",
    "no siempre",
    "a veces",
    "segun",
    "según",
)

_YES_PATTERNS = (
    r"\bsi\b",
    r"\bsí\b",
    r"\bclaro\b",
    r"\bcorrecto\b",
    r"\bexacto\b",
    r"\baj[aá]m\b",
)

_NO_PATTERNS = (
    r"\bno\b",
    r"\bpara nada\b",
    r"\bninguno\b",
    r"\bninguna\b",
)

_REFORMULATION_HINTS: dict[str, str] = {
    "aportes_actuales": "Por ejemplo, si hoy te pasa una cuota, algo fijo, algo esporadico o nada.",
    "convivencia": "Por ejemplo, si vive con vos, con la otra persona o si van alternando.",
    "notificacion": "Por ejemplo, si tenes un domicilio, telefono, trabajo o algun dato para ubicarlo.",
    "ingresos_otro_progenitor": "Por ejemplo, si sabes donde trabaja, si tiene sueldo fijo o si hace changas.",
    "domicilio_relevante": "Por ejemplo, en que ciudad vive hoy o donde corresponderia tramitar el caso.",
    "modalidad_divorcio": "Por ejemplo, si seria de comun acuerdo o si la otra parte no quiere firmar.",
}

_REFORMULATION_PURPOSES: dict[str, str] = {
    "aportes_actuales": "Eso me ayuda a saber si ya hay algun cumplimiento o si el reclamo arranca desde cero.",
    "convivencia": "Eso cambia bastante como conviene enfocar el caso.",
    "notificacion": "Eso sirve para saber si el reclamo se puede mover sin trabas practicas.",
    "ingresos_otro_progenitor": "Eso sirve para estimar mejor que se puede pedir y con que respaldo.",
    "domicilio_relevante": "Eso ayuda a ubicar donde conviene tramitar y como seguir.",
    "modalidad_divorcio": "Eso cambia bastante la forma de encarar el tramite.",
}

_CONTRADICTION_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("aportes_actuales", "cumplimiento_alimentos", "aporte_actual", "aporta_actualmente"),
    ("convivencia", "convivencia_hijo", "convivencia_con_hijo"),
    ("notificacion", "domicilio_otro_progenitor", "ubicacion_otro_progenitor"),
    ("ingresos_otro_progenitor", "ingresos", "actividad_otro_progenitor"),
)

_YES_NO_SLOT_FACTS: dict[str, str] = {
    "aportes_actuales": "aportes_actuales",
    "cumplimiento_alimentos": "aportes_actuales",
    "convivencia": "convivencia",
    "notificacion": "notificacion",
    "ingresos_otro_progenitor": "ingresos_otro_progenitor",
    "urgencia": "urgencia",
}


def interpret_clarification_answer(
    *,
    answer: str,
    last_question: str,
    known_facts: dict[str, Any] | None = None,
    asked_questions: list[str] | None = None,
    extracted_facts: dict[str, Any] | None = None,
    clarified_fields: list[str] | None = None,
) -> dict[str, Any]:
    clean_answer = _clean_text(answer)
    normalized_answer = _normalize_text(clean_answer)
    clean_question = _clean_text(last_question)
    safe_known_facts = dict(known_facts or {})
    safe_extracted_facts = dict(extracted_facts or {})
    safe_clarified_fields = [str(item).strip() for item in list(clarified_fields or []) if str(item).strip()]
    safe_asked_questions = [str(item).strip() for item in list(asked_questions or []) if str(item).strip()]

    canonical_slot = canonicalize_slot(question=clean_question)
    memory_facts = _extract_contextual_facts(answer=clean_answer, question=clean_question)
    if not memory_facts:
        memory_facts = _extract_yes_no_slot_facts(
            normalized_answer=normalized_answer,
            canonical_slot=canonical_slot,
        )
    merged_facts = {**memory_facts, **safe_extracted_facts}
    merged_clarified_fields = _dedupe_strings([*safe_clarified_fields, *merged_facts.keys()])

    user_cannot_answer = _looks_user_cannot_answer(normalized_answer)
    ambiguous_language = _looks_ambiguous(normalized_answer)
    internal_tension = _looks_internally_tense(normalized_answer)
    short_answer = _is_short_answer(clean_answer)
    contradictory = _detect_contradiction(
        merged_facts=merged_facts,
        known_facts=safe_known_facts,
    )
    repeated_slot = _is_repeated_slot(
        canonical_slot=canonical_slot,
        asked_questions=safe_asked_questions,
    )

    has_meaningful_facts = _facts_are_substantive(
        merged_facts=merged_facts,
        normalized_answer=normalized_answer,
    ) or bool(safe_clarified_fields)
    if contradictory:
        response_quality = "contradictory"
    elif internal_tension:
        response_quality = "ambiguous"
    elif user_cannot_answer:
        response_quality = "ambiguous"
    elif ambiguous_language and has_meaningful_facts:
        response_quality = "ambiguous"
    elif ambiguous_language:
        response_quality = "ambiguous"
    elif short_answer and has_meaningful_facts:
        response_quality = "short_valid"
    elif has_meaningful_facts:
        response_quality = "clear"
    else:
        response_quality = "insufficient"

    response_strategy = _resolve_response_strategy(
        response_quality=response_quality,
        repeated_slot=repeated_slot,
        has_meaningful_facts=has_meaningful_facts,
        user_cannot_answer=user_cannot_answer,
    )
    answer_status = _map_answer_status(response_quality=response_quality)
    precision_required = response_strategy in {"clarify", "reformulate_question"}
    reformulated_question = _build_reformulated_question(
        canonical_slot=canonical_slot,
        last_question=clean_question,
        response_quality=response_quality,
    )
    limit_explanation = _build_limit_explanation(
        canonical_slot=canonical_slot,
        response_quality=response_quality,
        repeated_slot=repeated_slot,
    )
    hybrid_guidance = _build_hybrid_guidance(
        response_quality=response_quality,
        response_strategy=response_strategy,
        canonical_slot=canonical_slot,
    )

    return {
        "response_quality": response_quality,
        "answer_status": answer_status,
        "response_strategy": response_strategy,
        "precision_required": precision_required,
        "precision_prompt": reformulated_question if precision_required else "",
        "reformulated_question": reformulated_question,
        "limit_explanation": limit_explanation,
        "hybrid_guidance": hybrid_guidance,
        "user_cannot_answer": user_cannot_answer,
        "detected_loop": repeated_slot and response_strategy != "advance",
        "canonical_slot": canonical_slot,
        "interpreted_answer": _interpret_yes_no(normalized_answer),
        "facts": merged_facts,
        "clarified_fields": merged_clarified_fields,
    }


def _extract_contextual_facts(*, answer: str, question: str) -> dict[str, Any]:
    memory = update_memory_with_user_answer({}, question=question, answer=answer)
    return dict(memory.get("known_facts") or {})


def _extract_yes_no_slot_facts(*, normalized_answer: str, canonical_slot: str) -> dict[str, Any]:
    fact_key = _YES_NO_SLOT_FACTS.get(canonical_slot)
    if not fact_key:
        return {}
    interpreted = _interpret_yes_no(normalized_answer)
    if interpreted == "yes":
        return {fact_key: True}
    if interpreted == "no":
        return {fact_key: False}
    return {}


def _resolve_response_strategy(
    *,
    response_quality: str,
    repeated_slot: bool,
    has_meaningful_facts: bool,
    user_cannot_answer: bool,
) -> str:
    if response_quality == "contradictory":
        return "clarify"
    if response_quality == "clear":
        return "advance"
    if response_quality == "short_valid":
        return "advance"
    if response_quality == "ambiguous":
        if repeated_slot and not has_meaningful_facts:
            return "advance_with_prudence"
        return "clarify" if user_cannot_answer or not has_meaningful_facts else "advance_with_prudence"
    if repeated_slot:
        return "advance_with_prudence"
    if user_cannot_answer:
        return "clarify"
    return "reformulate_question"


def _map_answer_status(*, response_quality: str) -> str:
    if response_quality in {"clear", "short_valid"}:
        return "precise"
    if response_quality == "ambiguous":
        return "ambiguous"
    if response_quality == "contradictory":
        return "contradictory"
    return "unknown"


def _build_reformulated_question(
    *,
    canonical_slot: str,
    last_question: str,
    response_quality: str,
) -> str:
    if response_quality not in {"ambiguous", "insufficient"}:
        return ""

    simplified = simplify_question_text(last_question, canonical_slot).strip()
    if simplified and not simplified.startswith("¿"):
        simplified = f"¿{simplified}"
    hint = _REFORMULATION_HINTS.get(canonical_slot, "")
    purpose = _REFORMULATION_PURPOSES.get(canonical_slot, "")
    if simplified and hint and purpose:
        return f"{simplified} {hint} {purpose}"
    if simplified and hint:
        return f"{simplified} {hint}"
    if simplified and purpose:
        return f"{simplified} {purpose}"
    if simplified:
        return simplified
    if hint and purpose:
        return f"{hint} {purpose}"
    if hint:
        return hint
    if purpose:
        return purpose
    return "¿Me lo podes aclarar un poco mejor con un dato mas concreto?"


def _build_limit_explanation(
    *,
    canonical_slot: str,
    response_quality: str,
    repeated_slot: bool,
) -> str:
    target = _humanize_slot(canonical_slot) or "ese punto"
    if response_quality == "contradictory":
        return f"Lo que me respondiste sobre {target} no termina de cerrar con lo anterior y conviene aclararlo."
    if response_quality == "ambiguous":
        purpose = _REFORMULATION_PURPOSES.get(canonical_slot, "")
        if purpose:
            return f"Con esta respuesta todavia no queda claro {target}. {purpose}"
        return f"Con esta respuesta todavia no queda claro {target}."
    if repeated_slot:
        return f"Con lo que ya se y lo que me respondiste, no conviene seguir insistiendo igual sobre {target}."
    return f"Con esta respuesta todavia no alcanzo a definir bien {target}."


def _build_hybrid_guidance(
    *,
    response_quality: str,
    response_strategy: str,
    canonical_slot: str,
) -> str:
    target = _humanize_slot(canonical_slot) or "el dato que falta"
    if response_strategy == "advance_with_prudence":
        if response_quality == "ambiguous":
            return f"Puedo seguir orientando, pero manteniendo prudencia porque {target} no quedo del todo claro."
        return f"Puedo seguir orientando con prudencia, aunque {target} no termino de cerrarse."
    if response_strategy == "clarify":
        return f"Antes de cerrar una orientacion mas firme, conviene aclarar mejor {target}."
    if response_strategy == "reformulate_question":
        return f"Para no orientarte sobre una base floja, necesito precisar mejor {target}."
    return ""


def _interpret_yes_no(normalized_answer: str) -> str:
    if any(re.search(pattern, normalized_answer) for pattern in _YES_PATTERNS):
        return "yes"
    if any(re.search(pattern, normalized_answer) for pattern in _NO_PATTERNS):
        return "no"
    return ""


def _looks_user_cannot_answer(normalized_answer: str) -> bool:
    return any(pattern in normalized_answer for pattern in _USER_CANNOT_ANSWER_PATTERNS)


def _looks_ambiguous(normalized_answer: str) -> bool:
    return any(pattern in normalized_answer for pattern in _AMBIGUOUS_PATTERNS)


def _looks_internally_tense(normalized_answer: str) -> bool:
    has_yes_no = bool(_interpret_yes_no(normalized_answer))
    has_tension = any(pattern in normalized_answer for pattern in _TENSION_PATTERNS)
    return has_yes_no and has_tension


def _is_short_answer(answer: str) -> bool:
    return len(_clean_text(answer).split()) <= 3


def _detect_contradiction(
    *,
    merged_facts: dict[str, Any],
    known_facts: dict[str, Any],
) -> bool:
    for key, value in merged_facts.items():
        aliases = _resolve_aliases(key)
        for alias in aliases:
            if alias not in known_facts:
                continue
            previous_value = known_facts.get(alias)
            if not _has_meaningful_value(previous_value):
                continue
            if _normalize_scalar(previous_value) != _normalize_scalar(value):
                return True
    return False


def _resolve_aliases(key: str) -> tuple[str, ...]:
    normalized = _normalize_key(key)
    for group in _CONTRADICTION_ALIAS_GROUPS:
        if normalized in group:
            return group
    return (normalized,)


def _is_repeated_slot(*, canonical_slot: str, asked_questions: list[str]) -> bool:
    if not canonical_slot:
        return False
    count = 0
    for question in asked_questions:
        if canonicalize_slot(question=question) == canonical_slot:
            count += 1
    return count >= 2


def _humanize_slot(slot: str) -> str:
    if not slot:
        return ""
    return slot.replace("_", " ").strip()


def _has_meaningful_value(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return normalized not in {"desconocido", "sin dato", "pendiente"}
    return True


def _facts_are_substantive(*, merged_facts: dict[str, Any], normalized_answer: str) -> bool:
    for value in merged_facts.values():
        if isinstance(value, bool):
            return True
        if isinstance(value, str):
            normalized_value = _normalize_text(value)
            if not normalized_value or normalized_value == normalized_answer:
                continue
            if normalized_value in _AMBIGUOUS_PATTERNS or normalized_value in _USER_CANNOT_ANSWER_PATTERNS:
                continue
            return True
        if _has_meaningful_value(value):
            return True
    return False


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _normalize_text(value)


def _normalize_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    return normalized[:120]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.lower()


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
