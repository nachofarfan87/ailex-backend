# backend/app/services/adaptive_followup_service.py
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


_SIMILARITY_THRESHOLD = 0.75
_LOOP_MIN_OCCURRENCES = 2

_GENERIC_QUESTION_PATTERNS = (
    "mas contexto",
    "queres contarme mas",
    "podrias ampliar",
    "puedes ampliar",
    "contarme mas",
    "algo mas",
    "necesito saber mas",
)

_IMPORTANCE_RANK: dict[str, int] = {
    "critical": 3,
    "high": 2,
    "medium": 1,
    "low": 0,
}

_USER_CANNOT_ANSWER_PATTERNS = (
    "no se",
    "no se eso",
    "no lo se",
    "no sabria decirte",
    "no sabria",
    "no tengo ese dato",
    "no tengo ese dato ahora",
    "no tengo ese dato conmigo",
    "no cuento con esa informacion",
    "no cuento con esa info",
    "desconozco",
    "ni idea",
    "no tengo forma de saberlo",
    "no puedo saberlo",
    "no puedo conseguirlo ahora",
    "eso no lo tengo",
)

_NON_INFORMATIVE_PATTERNS = (
    "no se",
    "no lo se",
    "no sabria",
    "ya te dije",
    "lo mismo",
    "eso no lo tengo",
    "ni idea",
    "no puedo conseguirlo ahora",
    "no tengo ese dato",
    "desconozco",
)

_MONTH_WORDS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

_COMMON_INFORMATIONAL_TOKENS = (
    "si",
    "no",
    "vive",
    "domicilio",
    "provincia",
    "jujuy",
    "salta",
    "buenos aires",
    "mendoza",
    "cordoba",
    "acuerdo",
    "unilateral",
    "comun acuerdo",
    "hijo",
    "hija",
    "hijos",
    "hijas",
    "dni",
    "trabaja",
    "ingresos",
    "sueldo",
    "cuota",
    "alimentos",
    "convivencia",
    "casados",
    "separados",
    "fecha",
    "mes",
    "anio",
)


def resolve_followup_decision(
    known_facts: dict,
    missing_facts: list,
    conversation_state: dict,
    previous_questions: list,
    last_user_messages: list,
) -> dict:
    """
    Decide si conviene formular una pregunta de seguimiento y cual.

    Mantiene compatibilidad con la API previa y agrega metadatos de progreso.
    """
    known_facts = dict(known_facts or {})
    missing_facts = [dict(item) for item in list(missing_facts or []) if isinstance(item, dict)]
    conversation_state = dict(conversation_state or {})
    previous_questions = [str(item) for item in list(previous_questions or []) if str(item).strip()]
    last_user_messages = [str(item) for item in list(last_user_messages or []) if str(item).strip()]

    uncovered = _filter_uncovered(missing_facts, known_facts)
    detected_loop = _detect_loop(previous_questions)
    user_cannot_answer = _detect_user_cannot_answer(last_user_messages)
    recent_progress = _detect_recent_information_progress(last_user_messages)

    progress_state, stagnation_reason = _compute_progress_state(
        uncovered=uncovered,
        detected_loop=detected_loop,
        user_cannot_answer=user_cannot_answer,
        recent_progress=recent_progress,
        recent_message_count=len(last_user_messages[-2:]),
    )

    top_fact = _pick_priority_fact(uncovered, previous_questions)
    should_ask, reason = _decide_should_ask(
        top_fact=top_fact,
        uncovered=uncovered,
        previous_questions=previous_questions,
        detected_loop=detected_loop,
        progress_state=progress_state,
        user_cannot_answer=user_cannot_answer,
        recent_progress=recent_progress,
        stagnation_reason=stagnation_reason,
    )

    priority_question: str | None = None
    question_type: str | None = None
    if should_ask and top_fact:
        priority_question = _build_question(top_fact)
        question_type = _classify_question_type(top_fact)
        if priority_question and _is_question_redundant(priority_question, previous_questions):
            should_ask = False
            reason = "La pregunta generada es redundante con una pregunta anterior."
            priority_question = None
            question_type = None

    return {
        "should_ask": should_ask,
        "reason": reason,
        "priority_question": priority_question,
        "question_type": question_type,
        "detected_loop": detected_loop,
        "progress_state": progress_state,
        "user_cannot_answer": user_cannot_answer,
        "recent_progress": recent_progress,
        "stagnation_reason": stagnation_reason,
    }


def _filter_uncovered(missing_facts: list[dict], known_facts: dict) -> list[dict]:
    normalized_known = {_normalize_key(key) for key in known_facts}
    return [
        fact
        for fact in missing_facts
        if _normalize_key(str(fact.get("key") or "")) not in normalized_known
    ]


def _detect_loop(previous_questions: list[str]) -> bool:
    if not previous_questions:
        return False

    normalized_questions = [_normalize_text(question) for question in previous_questions]
    counts: dict[str, int] = {}
    for text in normalized_questions:
        if not text:
            continue
        matched_key: str | None = None
        for key in counts:
            if _text_similarity(text, key) >= _SIMILARITY_THRESHOLD:
                matched_key = key
                break
        if matched_key:
            counts[matched_key] += 1
        else:
            counts[text] = 1
    return any(count >= _LOOP_MIN_OCCURRENCES for count in counts.values())


def _is_question_redundant(question: str, previous_questions: list[str]) -> bool:
    if not previous_questions:
        return False
    normalized_question = _normalize_text(question)
    return any(
        _text_similarity(normalized_question, _normalize_text(previous)) >= _SIMILARITY_THRESHOLD
        for previous in previous_questions
    )


def _compute_progress_state(
    *,
    uncovered: list[dict],
    detected_loop: bool,
    user_cannot_answer: bool,
    recent_progress: bool,
    recent_message_count: int,
) -> tuple[str, str | None]:
    if not uncovered:
        return "complete", None

    if detected_loop:
        return "blocked", "Se detecto un loop de follow-up."

    has_critical_or_high_impact = _has_critical_or_high_impact(uncovered)
    if user_cannot_answer and has_critical_or_high_impact:
        return "blocked", "El usuario indico que no puede aportar un dato critico o de alto impacto."

    if user_cannot_answer:
        return "stalled", "El usuario indico que no puede aportar mas informacion util ahora."

    if recent_message_count < 2:
        return "advancing", None

    if not recent_progress and has_critical_or_high_impact:
        return "blocked", "No hubo avance util reciente sobre datos criticos o de alto impacto."

    if not recent_progress:
        return "stalled", "No hubo avance util reciente en los ultimos mensajes."

    return "advancing", None


def _detect_user_cannot_answer(last_user_messages: list[str]) -> bool:
    if not last_user_messages:
        return False
    for message in last_user_messages[-2:]:
        normalized = _normalize_text(message)
        if any(pattern in normalized for pattern in _USER_CANNOT_ANSWER_PATTERNS):
            return True
    return False


def _detect_recent_information_progress(last_user_messages: list[str]) -> bool:
    if not last_user_messages:
        return False
    informative_hits = 0
    for message in last_user_messages[-2:]:
        if _is_non_informative_user_message(message):
            continue
        if _looks_informative(message):
            informative_hits += 1
    return informative_hits > 0


def _is_non_informative_user_message(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized or len(normalized) <= 2:
        return True
    return any(normalized == pattern or normalized.startswith(pattern) for pattern in _NON_INFORMATIVE_PATTERNS)


def _looks_informative(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False

    if re.search(r"\d", message):
        return True
    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", normalized):
        return True
    if any(month in normalized for month in _MONTH_WORDS):
        return True
    if re.search(r"\b(si|no)\b", normalized) and len(normalized.split()) >= 3:
        return True
    if any(token in normalized for token in _COMMON_INFORMATIONAL_TOKENS) and len(normalized.split()) >= 3:
        return True
    return len(normalized.split()) >= 6


def _has_critical_or_high_impact(uncovered: list[dict]) -> bool:
    for fact in uncovered:
        importance = str(fact.get("importance") or "").strip().lower()
        if importance == "critical":
            return True
        if importance == "high" and bool(fact.get("impact_on_strategy")):
            return True
    return False


def _pick_priority_fact(uncovered: list[dict], previous_questions: list[str]) -> dict | None:
    if not uncovered:
        return None

    def _score(fact: dict) -> int:
        return _importance_rank(str(fact.get("importance") or "")) * 2 + int(bool(fact.get("impact_on_strategy")))

    candidates = sorted(uncovered, key=_score, reverse=True)
    for fact in candidates:
        question = _build_question(fact)
        if not question or _is_question_redundant(question, previous_questions):
            continue
        return fact
    return candidates[0] if candidates else None


def _decide_should_ask(
    *,
    top_fact: dict | None,
    uncovered: list[dict],
    previous_questions: list[str],
    detected_loop: bool,
    progress_state: str,
    user_cannot_answer: bool,
    recent_progress: bool,
    stagnation_reason: str | None,
) -> tuple[bool, str]:
    if detected_loop:
        return False, "Se detecto un bucle de preguntas. No se formula nueva pregunta."

    if progress_state == "complete":
        return False, "El caso tiene informacion suficiente para avanzar sin preguntar mas."

    if not uncovered:
        return False, "No hay hechos pendientes que justifiquen una pregunta."

    if user_cannot_answer:
        if _has_critical_or_high_impact(uncovered):
            return False, "El usuario no puede aportar el dato critico o de alto impacto faltante."
        return False, "El usuario no puede aportar mas informacion util por ahora."

    max_rank = max(_importance_rank(str(item.get("importance") or "")) for item in uncovered)
    if max_rank < _IMPORTANCE_RANK["medium"]:
        return False, "Solo quedan datos de baja prioridad; no es necesario preguntar."

    if top_fact is None:
        return False, "No se encontro una pregunta adecuada para el momento actual."

    if progress_state == "blocked":
        return False, stagnation_reason or "El caso esta bloqueado y no conviene insistir con la misma pregunta."

    if progress_state == "stalled":
        if _has_critical_or_high_impact(uncovered):
            candidate_question = _build_question(top_fact)
            if candidate_question and _is_question_redundant(candidate_question, previous_questions):
                return False, "El caso esta estancado y la pregunta seria redundante."
            return True, stagnation_reason or "Falta un dato critico y todavia vale intentar una ultima pregunta util."
        return False, stagnation_reason or "El caso esta estancado y no conviene seguir preguntando."

    importance = str(top_fact.get("importance") or "").strip().lower()
    if importance == "critical":
        return True, "Hay un dato critico faltante que impacta directamente en el caso."
    if importance == "high":
        return True, "Hay un dato de alta prioridad faltante que mejora la orientacion."
    if importance == "medium" and bool(top_fact.get("impact_on_strategy")):
        if recent_progress:
            return True, "Hay un dato de prioridad media que puede definir la estrategia."
        return False, "No hubo avance reciente y no conviene insistir con un dato de prioridad media."
    return False, "Los datos faltantes no tienen prioridad suficiente para preguntar ahora."


def _build_question(fact: dict) -> str:
    suggested = str(fact.get("suggested_question") or "").strip()
    if suggested and not _is_generic_question(suggested):
        return _normalize_question_format(suggested)

    label = str(fact.get("label") or fact.get("key") or "").strip()
    if not label:
        return ""
    label = _humanize_label(label)
    if not label:
        return ""
    return f"¿Podes precisar {label}?"


def _classify_question_type(fact: dict) -> str:
    importance = str(fact.get("importance") or "").strip().lower()
    impact = bool(fact.get("impact_on_strategy"))
    if importance == "critical":
        return "critical"
    if importance == "high" and impact:
        return "strategic"
    return "optional"


def _normalize_text(text: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    no_punct = re.sub(r"[^\w\s]", "", lowered)
    return re.sub(r"\s+", " ", no_punct).strip()


def _normalize_key(key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().casefold()).strip("_")
    return normalized[:120]


def _normalize_question_format(question: str) -> str:
    value = re.sub(r"\s+", " ", str(question or "").strip())
    if not value:
        return ""
    if not value.endswith("?"):
        value = f"{value}?"
    if not value.startswith("¿"):
        value = f"¿{value.lstrip('?')}"
    return value


def _humanize_label(label: str) -> str:
    text = str(label or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    return text.replace("_", " ").strip()


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a, b=b).ratio()


def _importance_rank(importance: str) -> int:
    return _IMPORTANCE_RANK.get(str(importance or "").strip().lower(), 0)


def _is_generic_question(question: str) -> bool:
    normalized = _normalize_text(question)
    return any(pattern in normalized for pattern in _GENERIC_QUESTION_PATTERNS)
