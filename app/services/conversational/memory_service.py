from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.conversational.adaptive_policy import build_adaptive_context
from app.services.conversational.question_selector import derive_canonical_signals


_ALIMENTOS_SLOTS = (
    "aportes_actuales",
    "convivencia",
    "notificacion",
    "ingresos",
    "urgencia",
    "antecedentes",
)

_YES_PATTERNS = (
    r"\bsi\b",
    r"\bsí\b",
    r"\bclaro\b",
    r"\bcorrecto\b",
    r"\bexacto\b",
    r"\btengo\b",
)
_NO_PATTERNS = (
    r"\bno\b",
    r"\bninguno\b",
    r"\bninguna\b",
    r"\bpara nada\b",
)


def build_conversation_memory(payload: dict[str, Any] | None) -> dict[str, Any]:
    safe_payload = dict(payload or {})
    clarification_context = _extract_clarification_context(safe_payload)
    previous_memory = _as_dict(clarification_context.get("conversation_memory"))
    query_text = _extract_query_text(safe_payload, clarification_context)
    known_facts = _collect_known_facts(safe_payload, clarification_context)
    inferred_facts = _collect_inferred_facts(query_text, previous_memory)
    memory = merge_conversation_memory(
        previous_memory,
        {
            "known_facts": known_facts,
            "inferred_facts": inferred_facts,
            "asked_questions": _collect_asked_questions(clarification_context, previous_memory),
            "user_answers": list(previous_memory.get("user_answers") or []),
            "canonical_signals": dict(previous_memory.get("canonical_signals") or {}),
            "session_id": _extract_session_id(safe_payload),
        },
    )

    last_question = _clean_text(clarification_context.get("last_question"))
    last_user_answer = _clean_text(
        clarification_context.get("last_user_answer")
        or clarification_context.get("submitted_text")
        or ""
    )
    current_message = last_user_answer or query_text

    if last_question and last_user_answer:
        memory = update_memory_with_user_answer(
            memory,
            question=last_question,
            answer=last_user_answer,
        )
    else:
        memory["canonical_signals"] = _merge_canonical_signals(
            memory.get("canonical_signals"),
            derive_canonical_signals(_normalize_text(current_message)),
        )

    memory["last_user_message"] = current_message
    memory["conversation_turns"] = _compute_conversation_turns(memory, query_text=query_text, last_user_answer=last_user_answer)
    memory["resolved_slots"] = _resolve_slots(memory)
    memory["pending_slots"] = [slot for slot in _ALIMENTOS_SLOTS if slot not in set(memory["resolved_slots"])]
    memory["adaptive_context"] = build_adaptive_context(
        memory,
        last_exchange={
            "question": last_question,
            "answer": last_user_answer,
        },
    )
    return memory


def merge_conversation_memory(previous_memory: dict[str, Any] | None, updates: dict[str, Any] | None) -> dict[str, Any]:
    previous = dict(previous_memory or {})
    incoming = dict(updates or {})

    merged_known = dict(previous.get("known_facts") or {})
    merged_known.update(_as_dict(incoming.get("known_facts")))

    merged_inferred = dict(previous.get("inferred_facts") or {})
    merged_inferred.update(_as_dict(incoming.get("inferred_facts")))

    merged_signals = _merge_canonical_signals(
        previous.get("canonical_signals"),
        incoming.get("canonical_signals"),
    )

    # Preserve _last_opening_idx from Fase 5.5 conversational quality layer.
    # incoming wins if present; otherwise keep previous value.
    last_opening_idx = incoming.get("_last_opening_idx")
    if last_opening_idx is None:
        last_opening_idx = previous.get("_last_opening_idx")

    return {
        "known_facts": merged_known,
        "inferred_facts": merged_inferred,
        "canonical_signals": merged_signals,
        "asked_questions": _dedupe_strings([
            *_as_str_list(previous.get("asked_questions")),
            *_as_str_list(incoming.get("asked_questions")),
        ]),
        "user_answers": _merge_answer_logs(
            previous.get("user_answers"),
            incoming.get("user_answers"),
        ),
        "resolved_slots": _dedupe_strings([
            *_as_str_list(previous.get("resolved_slots")),
            *_as_str_list(incoming.get("resolved_slots")),
        ]),
        "pending_slots": _dedupe_strings([
            *_as_str_list(previous.get("pending_slots")),
            *_as_str_list(incoming.get("pending_slots")),
        ]),
        "conversation_turns": int(incoming.get("conversation_turns") or previous.get("conversation_turns") or 0),
        "last_user_message": _clean_text(incoming.get("last_user_message") or previous.get("last_user_message")),
        "session_id": _clean_text(incoming.get("session_id") or previous.get("session_id")),
        "adaptive_context": _as_dict(incoming.get("adaptive_context") or previous.get("adaptive_context")),
        "_last_opening_idx": last_opening_idx,
    }


def update_memory_with_user_answer(
    memory: dict[str, Any] | None,
    *,
    question: str,
    answer: str,
) -> dict[str, Any]:
    base_memory = merge_conversation_memory(memory, {})
    clean_question = _clean_text(question)
    clean_answer = _clean_text(answer)
    normalized_answer = _normalize_text(clean_answer)
    slot = _infer_question_slot(clean_question)
    extracted_facts = _extract_answer_facts(slot=slot, normalized_answer=normalized_answer, raw_answer=clean_answer)

    updated = merge_conversation_memory(
        base_memory,
        {
            "known_facts": extracted_facts,
            "canonical_signals": derive_canonical_signals(normalized_answer),
            "user_answers": [{"question": clean_question, "answer": clean_answer, "slot": slot or ""}],
            "last_user_message": clean_answer,
        },
    )
    updated["resolved_slots"] = _resolve_slots(updated)
    updated["pending_slots"] = [slot_name for slot_name in _ALIMENTOS_SLOTS if slot_name not in set(updated["resolved_slots"])]
    updated["adaptive_context"] = build_adaptive_context(
        updated,
        last_exchange={"question": clean_question, "answer": clean_answer},
    )
    return updated


def derive_memory_from_context(
    *,
    query_text: str,
    known_facts: dict[str, Any] | None,
    clarification_context: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "query": query_text,
        "facts": known_facts or {},
        "metadata": {
            "clarification_context": clarification_context or {},
        },
    }
    return build_conversation_memory(payload)


def _extract_clarification_context(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = _as_dict(payload.get("metadata"))
    return _as_dict(metadata.get("clarification_context"))


def _extract_session_id(payload: dict[str, Any]) -> str:
    metadata = _as_dict(payload.get("metadata"))
    for key in ("session_id", "sessionId", "chat_session_id", "chatSessionId"):
        value = _clean_text(metadata.get(key))
        if value:
            return value
    return ""


def _extract_query_text(payload: dict[str, Any], clarification_context: dict[str, Any]) -> str:
    return _clean_text(
        payload.get("query")
        or clarification_context.get("base_query")
        or clarification_context.get("last_user_answer")
        or ""
    )


def _collect_known_facts(payload: dict[str, Any], clarification_context: dict[str, Any]) -> dict[str, Any]:
    known_facts = {}
    known_facts.update(_as_dict(clarification_context.get("known_facts")))
    known_facts.update(_as_dict(payload.get("facts")))
    return {key: value for key, value in known_facts.items() if value not in (None, "", [], {})}


def _collect_inferred_facts(query_text: str, previous_memory: dict[str, Any]) -> dict[str, Any]:
    inferred = dict(previous_memory.get("inferred_facts") or {})
    normalized_query = _normalize_text(query_text)
    if re.search(r"\bhij[ao]s?\b|\bmi hija\b|\bmi hijo\b|\bbebe\b|\bnena\b|\bnene\b|\bmenor(?:es)?\b|\bbeba\b", normalized_query):
        inferred["hay_hijos"] = "inferred"
    if re.search(r"\b\d{1,2}\s*(anos|años)\b", normalized_query):
        inferred["hay_hijos_edad"] = "inferred"
    if re.search(r"\balimentos?\b|\bcuota alimentaria\b", normalized_query):
        inferred["tema_alimentos"] = "inferred"
    if re.search(r"\bpadre\b|\bmadre\b|\bprogenitor\b", normalized_query):
        inferred["vinculo_parental"] = "inferred"
    return inferred


def _collect_asked_questions(clarification_context: dict[str, Any], previous_memory: dict[str, Any]) -> list[str]:
    return _dedupe_strings([
        *_as_str_list(previous_memory.get("asked_questions")),
        *_as_str_list(clarification_context.get("asked_questions")),
        _clean_text(clarification_context.get("last_question")),
    ])


def _merge_canonical_signals(
    previous_signals: dict[str, Any] | None,
    incoming_signals: dict[str, Any] | None,
) -> dict[str, bool]:
    merged: dict[str, bool] = {}
    for key, value in _as_dict(previous_signals).items():
        merged[str(key)] = bool(value)
    for key, value in _as_dict(incoming_signals).items():
        merged[str(key)] = merged.get(str(key), False) or bool(value)
    return merged


def _merge_answer_logs(previous_answers: Any, incoming_answers: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in list(previous_answers or []) + list(incoming_answers or []):
        if not isinstance(item, dict):
            continue
        question = _clean_text(item.get("question"))
        answer = _clean_text(item.get("answer"))
        slot = _clean_text(item.get("slot"))
        key = (_normalize_text(question), _normalize_text(answer))
        if not question or not answer or key in seen:
            continue
        seen.add(key)
        result.append({"question": question, "answer": answer, "slot": slot})
    return result


def _compute_conversation_turns(memory: dict[str, Any], *, query_text: str, last_user_answer: str) -> int:
    existing = int(memory.get("conversation_turns") or 0)
    answers_count = len(memory.get("user_answers") or [])
    base_turns = 1 if _clean_text(query_text) else 0
    if last_user_answer:
        return max(existing, base_turns + answers_count)
    return max(existing, base_turns, answers_count or 0)


def _resolve_slots(memory: dict[str, Any]) -> list[str]:
    resolved = set(_as_str_list(memory.get("resolved_slots")))
    known_facts = _as_dict(memory.get("known_facts"))
    canonical_signals = _as_dict(memory.get("canonical_signals"))

    if _has_meaningful_value(known_facts.get("aportes_actuales")) or canonical_signals.get("incumplimiento_aportes"):
        resolved.add("aportes_actuales")
    if _has_meaningful_value(known_facts.get("convivencia")) or _has_meaningful_value(known_facts.get("convivencia_hijo")):
        resolved.add("convivencia")
    if _has_meaningful_value(known_facts.get("notificacion")) or canonical_signals.get("problema_ubicacion"):
        resolved.add("notificacion")
    if _has_meaningful_value(known_facts.get("ingresos")) or _has_meaningful_value(known_facts.get("ingresos_otro_progenitor")):
        resolved.add("ingresos")
    if _has_meaningful_value(known_facts.get("urgencia")) or canonical_signals.get("urgencia_reclamo"):
        resolved.add("urgencia")
    if _has_meaningful_value(known_facts.get("antecedentes")) or canonical_signals.get("antecedente_reclamo"):
        resolved.add("antecedentes")

    return [slot for slot in _ALIMENTOS_SLOTS if slot in resolved]


def _infer_question_slot(question: str) -> str | None:
    normalized_question = _normalize_text(question)
    if "aportando algo actualmente" in normalized_question:
        return "aportes_actuales"
    if "vive con vos" in normalized_question or "convive" in normalized_question:
        return "convivencia"
    if "ubicar al otro progenitor" in normalized_question or "domicilio" in normalized_question:
        return "notificacion"
    if "ingresos" in normalized_question or "actividad laboral" in normalized_question:
        return "ingresos"
    if "necesidad urgente" in normalized_question:
        return "urgencia"
    if "reclamo, acuerdo o intimacion previa" in normalized_question:
        return "antecedentes"
    return None


def _extract_answer_facts(*, slot: str | None, normalized_answer: str, raw_answer: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}

    if slot == "aportes_actuales":
        if _looks_negative(normalized_answer):
            facts["aportes_actuales"] = False
        elif _looks_positive(normalized_answer):
            facts["aportes_actuales"] = True
    elif slot == "convivencia":
        if re.search(r"\bvive con su padre\b|\bconvive con su padre\b", normalized_answer):
            facts["convivencia"] = False
        elif re.search(r"\bvive con su madre\b|\bconvive con su madre\b", normalized_answer):
            facts["convivencia"] = False
        elif re.search(r"\bvive conmigo\b|\bconvive conmigo\b|\besta conmigo\b|\besta a mi cargo\b", normalized_answer):
            facts["convivencia"] = True
        elif _looks_positive(normalized_answer):
            facts["convivencia"] = True
        elif _looks_negative(normalized_answer):
            facts["convivencia"] = False
    elif slot == "notificacion":
        if re.search(r"\bno se donde vive\b|\bdesconozco su domicilio\b|\bno lo puedo ubicar\b|\bno la puedo ubicar\b", normalized_answer):
            facts["notificacion"] = False
        elif _looks_positive(normalized_answer):
            facts["notificacion"] = True
    elif slot == "ingresos":
        if re.search(r"\btrabaja\b|\btiene ingresos\b|\besta en blanco\b|\bmonotribut", normalized_answer):
            facts["ingresos"] = True
        elif _looks_negative(normalized_answer):
            facts["ingresos"] = False
        elif raw_answer:
            facts["ingresos_otro_progenitor"] = raw_answer
    elif slot == "urgencia":
        if _looks_positive(normalized_answer):
            facts["urgencia"] = True
        elif _looks_negative(normalized_answer):
            facts["urgencia"] = False
    elif slot == "antecedentes":
        if _looks_positive(normalized_answer):
            facts["antecedentes"] = True
        elif _looks_negative(normalized_answer):
            facts["antecedentes"] = False

    if not facts and re.search(r"\bno me pasa plata\b|\bno me pasa nada\b|\bno paga\b|\bno cumple\b|\bno ayuda\b", normalized_answer):
        facts["aportes_actuales"] = False
    if not facts and re.search(r"\bvive con su padre\b|\bvive con su madre\b|\bvive conmigo\b", normalized_answer):
        facts["convivencia"] = "conmigo" in normalized_answer
    if not facts and re.search(r"\bno se nada de el\b|\bno se nada de ella\b|\bdesaparecio\b", normalized_answer):
        facts["notificacion"] = False

    # Universal: detect child mentions regardless of current slot.
    # This ensures hay_hijos is set whenever the user mentions children,
    # even if the active question is about something else entirely.
    if re.search(r"\bhij[ao]s?\b|\bhija\b|\bhijo\b|\bbebe\b|\bnena\b|\bnene\b|\bbeba\b|\bmenor(?:es)?\b", normalized_answer):
        facts.setdefault("hay_hijos", True)

    return facts


def _looks_positive(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in _YES_PATTERNS)


def _looks_negative(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in _NO_PATTERNS)


def _has_meaningful_value(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return normalized not in {"desconocido", "sin dato", "pendiente"}
    return True


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.lower()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


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
