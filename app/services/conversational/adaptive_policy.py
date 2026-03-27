from __future__ import annotations

import re
import unicodedata
from typing import Any


_AMBIGUOUS_ANSWER_PATTERNS = (
    r"^y?[.\s]*no se$",
    r"^ni idea$",
    r"^nose$",
    r"^mmm+$",
    r"^eh+$",
    r"^no recuerdo$",
    r"^no lo se$",
)

_EVASIVE_PATTERNS = (
    r"\bno se\b",
    r"\bno se bien\b",
    r"\bno tengo claro\b",
    r"\bla verdad no se\b",
    r"\bmas o menos\b",
    r"\bcreo que\b",
    r"\bcapaz\b",
    r"\bquizas\b",
)

_DIRECT_CATEGORIES = {
    "viabilidad_inmediata",
    "encuadre_familiar",
    "notificacion",
    "prueba_economica",
}

_CATEGORY_BY_SLOT = {
    "aportes_actuales": "viabilidad_inmediata",
    "convivencia": "encuadre_familiar",
    "notificacion": "notificacion",
    "ingresos": "prueba_economica",
    "urgencia": "urgencia",
    "antecedentes": "antecedentes",
}

_RECENT_WEIGHTS = (0.35, 0.7, 1.0)


def build_adaptive_context(
    memory: dict[str, Any] | None,
    question_selection: dict[str, Any] | None = None,
    last_exchange: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_memory = dict(memory or {})
    safe_selection = dict(question_selection or {})
    safe_exchange = dict(last_exchange or {})
    resolved_slots = [
        str(item).strip()
        for item in (safe_memory.get("resolved_slots") or [])
        if str(item or "").strip()
    ]
    pending_slots = [
        str(item).strip()
        for item in (safe_memory.get("pending_slots") or [])
        if str(item or "").strip()
    ]
    user_answers = [item for item in (safe_memory.get("user_answers") or []) if isinstance(item, dict)]
    recent_answers = user_answers[-3:]
    weighted_productive_score = _weighted_recent_score(recent_answers, _answer_is_productive)
    weighted_ambiguous_score = _weighted_recent_score(recent_answers, _answer_is_ambiguous)
    productive_recent = sum(1 for item in recent_answers if _answer_is_productive(item))
    ambiguous_recent = sum(1 for item in recent_answers if _answer_is_ambiguous(item))
    last_answer_log = user_answers[-1] if user_answers else {}
    last_question_productive = _answer_is_productive(last_answer_log)
    last_question_category = _CATEGORY_BY_SLOT.get(_clean_text(last_answer_log.get("slot")))
    recent_progress = evaluate_conversation_progress(safe_memory)
    friction_level = _derive_friction_level(
        ambiguous_recent=ambiguous_recent,
        recent_answers=recent_answers,
        weighted_ambiguous_score=weighted_ambiguous_score,
    )
    productive_categories = _collect_productive_categories(user_answers)
    recent_productive_categories = _collect_recent_productive_categories(recent_answers)
    conversation_quality = _derive_conversation_quality(
        recent_progress=recent_progress,
        friction_level=friction_level,
        last_question_productive=last_question_productive,
        weighted_productive_score=weighted_productive_score,
        weighted_ambiguous_score=weighted_ambiguous_score,
    )

    return {
        "resolved_slots_count": len(resolved_slots),
        "pending_slots_count": len(pending_slots),
        "recent_progress": recent_progress,
        "friction_level": friction_level,
        "conversation_quality": conversation_quality,
        "last_question_productive": last_question_productive,
        "last_question_category": last_question_category or "",
        "productive_categories": productive_categories,
        "recent_productive_categories": recent_productive_categories,
        "productive_answers_recent": productive_recent,
        "ambiguous_answers_recent": ambiguous_recent,
        "weighted_productive_score": round(weighted_productive_score, 2),
        "weighted_ambiguous_score": round(weighted_ambiguous_score, 2),
        "conversation_turns": int(safe_memory.get("conversation_turns") or 0),
        "adaptive_signals": derive_adaptive_signals(
            safe_memory,
            recent_progress=recent_progress,
            friction_level=friction_level,
            last_question_productive=last_question_productive,
        ),
        "last_exchange": {
            "question": _clean_text(safe_exchange.get("question") or last_answer_log.get("question")),
            "answer": _clean_text(safe_exchange.get("answer") or last_answer_log.get("answer")),
            "resolved_slot": _clean_text(last_answer_log.get("slot")),
        },
        "selection_reference": {
            "selected_key": _clean_text(_as_dict(safe_selection.get("selected")).get("key")),
        },
    }


def evaluate_conversation_progress(memory: dict[str, Any] | None) -> str:
    safe_memory = dict(memory or {})
    resolved_slots = [
        str(item).strip()
        for item in (safe_memory.get("resolved_slots") or [])
        if str(item or "").strip()
    ]
    user_answers = [item for item in (safe_memory.get("user_answers") or []) if isinstance(item, dict)]
    recent_answers = user_answers[-3:]
    productive_recent = sum(1 for item in recent_answers if _answer_is_productive(item))
    weighted_productive_score = _weighted_recent_score(recent_answers, _answer_is_productive)
    ambiguous_recent = sum(1 for item in recent_answers if _answer_is_ambiguous(item))
    conversation_turns = int(safe_memory.get("conversation_turns") or 0)

    if weighted_productive_score >= 1.55 or (len(resolved_slots) >= 2 and conversation_turns <= 3):
        return "good"
    if conversation_turns >= 3 and weighted_productive_score < 0.4 and ambiguous_recent >= 2:
        return "stalled"
    if conversation_turns >= 3 and productive_recent == 0 and not resolved_slots:
        return "stalled"
    if conversation_turns >= 3 and weighted_productive_score < 0.5:
        return "stalled"
    return "steady"


def derive_adaptive_signals(
    memory: dict[str, Any] | None,
    *,
    recent_progress: str | None = None,
    friction_level: str | None = None,
    last_question_productive: bool | None = None,
) -> dict[str, bool]:
    safe_memory = dict(memory or {})
    progress = recent_progress or evaluate_conversation_progress(safe_memory)
    recent_answers = [
        item for item in (safe_memory.get("user_answers") or []) if isinstance(item, dict)
    ][-3:]
    friction = friction_level or _derive_friction_level(
        ambiguous_recent=sum(1 for item in recent_answers if _answer_is_ambiguous(item)),
        recent_answers=recent_answers,
        weighted_ambiguous_score=_weighted_recent_score(recent_answers, _answer_is_ambiguous),
    )
    productive = bool(last_question_productive)
    return {
        "productive_last_turn": productive,
        "good_progress": progress == "good",
        "stalled_conversation": progress == "stalled",
        "high_friction": friction == "high",
        "medium_friction": friction == "medium",
    }


def apply_adaptive_adjustments(candidate: Any, adaptive_context: dict[str, Any] | None) -> None:
    if not adaptive_context:
        return

    adaptive_signals = _as_dict(adaptive_context.get("adaptive_signals"))
    productive_categories = {
        _clean_text(item)
        for item in (adaptive_context.get("productive_categories") or [])
        if _clean_text(item)
    }
    recent_productive_categories = {
        _clean_text(item)
        for item in (adaptive_context.get("recent_productive_categories") or [])
        if _clean_text(item)
    }
    last_question_category = _clean_text(adaptive_context.get("last_question_category"))
    recent_progress = _clean_text(adaptive_context.get("recent_progress"))
    friction_level = _clean_text(adaptive_context.get("friction_level"))
    conversation_quality = _clean_text(adaptive_context.get("conversation_quality"))
    category = _clean_text(getattr(candidate, "category", ""))
    key = _clean_text(getattr(candidate, "key", ""))

    if adaptive_signals.get("productive_last_turn") and category and category == last_question_category:
        _apply_candidate_component(
            candidate,
            "adaptive",
            0.32,
            "adaptive_refuerzo_ultimo_turno_productivo",
        )
    elif category and category in recent_productive_categories:
        _apply_candidate_component(
            candidate,
            "adaptive",
            0.2,
            "adaptive_refuerzo_categoria_reciente",
        )
    elif category and category in productive_categories:
        _apply_candidate_component(
            candidate,
            "adaptive",
            0.12,
            "adaptive_refuerzo_categoria_historica",
        )

    if recent_progress == "good":
        if key in {"notificacion", "ingresos", "urgencia"}:
            _apply_candidate_component(
                candidate,
                "adaptive",
                0.2,
                "adaptive_prioriza_continuidad_eficiente",
            )

    if recent_progress == "stalled":
        if category in _DIRECT_CATEGORIES:
            _apply_candidate_component(
                candidate,
                "adaptive",
                0.3,
                "adaptive_prioriza_pregunta_directa",
            )
        if key == "antecedentes":
            _apply_candidate_component(
                candidate,
                "adaptive",
                -0.22,
                "adaptive_evitar_camino_lateral_en_estancamiento",
            )

    if friction_level == "medium":
        if key == "antecedentes":
            _apply_candidate_component(
                candidate,
                "adaptive",
                -0.15,
                "adaptive_baja_agresividad_por_friccion",
            )
        if category in _DIRECT_CATEGORIES:
            _apply_candidate_component(
                candidate,
                "adaptive",
                0.15,
                "adaptive_prioriza_claridad",
            )

    if friction_level == "high":
        if key in {"antecedentes", "urgencia"}:
            _apply_candidate_component(
                candidate,
                "adaptive",
                -0.25,
                "adaptive_penaliza_pregunta_menos_clara",
            )
        if category in _DIRECT_CATEGORIES:
            _apply_candidate_component(
                candidate,
                "adaptive",
                0.24,
                "adaptive_prioriza_pregunta_simple",
            )

    if conversation_quality == "high" and key in {"notificacion", "ingresos"}:
        _apply_candidate_component(
            candidate,
            "adaptive",
            0.12,
            "adaptive_aprovecha_calidad_alta",
        )
    elif conversation_quality == "low" and key == "antecedentes":
        _apply_candidate_component(
            candidate,
            "adaptive",
            -0.1,
            "adaptive_reduce_pregunta_lateral_por_calidad_baja",
        )


def _apply_candidate_component(candidate: Any, component: str, value: float, reason: str) -> None:
    breakdown = dict(getattr(candidate, "score_breakdown", {}) or {})
    breakdown[component] = round(float(breakdown.get(component, 0.0) or 0.0) + value, 4)
    setattr(candidate, "score_breakdown", breakdown)
    reasons = list(getattr(candidate, "reasons", []) or [])
    reasons.append(reason)
    setattr(candidate, "reasons", reasons)


def _collect_productive_categories(user_answers: list[dict[str, Any]]) -> list[str]:
    categories: list[str] = []
    for item in user_answers:
        if not _answer_is_productive(item):
            continue
        slot = _clean_text(item.get("slot"))
        category = _CATEGORY_BY_SLOT.get(slot)
        if category:
            categories.append(category)
    return _dedupe_strings(categories)


def _collect_recent_productive_categories(recent_answers: list[dict[str, Any]]) -> list[str]:
    weighted_categories: list[str] = []
    recent_weights = _resolve_recent_weights(len(recent_answers))
    for answer_log, weight in zip(recent_answers, recent_weights):
        if not _answer_is_productive(answer_log) or weight < 0.6:
            continue
        category = _CATEGORY_BY_SLOT.get(_clean_text(answer_log.get("slot")))
        if category:
            weighted_categories.append(category)
    return _dedupe_strings(reversed(weighted_categories))


def _weighted_recent_score(recent_answers: list[dict[str, Any]], predicate: Any) -> float:
    total = 0.0
    for answer_log, weight in zip(recent_answers, _resolve_recent_weights(len(recent_answers))):
        if predicate(answer_log):
            total += weight
    return total


def _resolve_recent_weights(size: int) -> tuple[float, ...]:
    if size <= 0:
        return ()
    return _RECENT_WEIGHTS[-size:]


def _derive_friction_level(
    *,
    ambiguous_recent: int,
    recent_answers: list[dict[str, Any]],
    weighted_ambiguous_score: float,
) -> str:
    if weighted_ambiguous_score >= 1.35 or ambiguous_recent >= 2:
        return "high"
    if weighted_ambiguous_score >= 0.7 or ambiguous_recent == 1:
        return "medium"
    if recent_answers and all(_clean_text(item.get("answer")) for item in recent_answers):
        return "low"
    return "low"


def _derive_conversation_quality(
    *,
    recent_progress: str,
    friction_level: str,
    last_question_productive: bool,
    weighted_productive_score: float | None = None,
    weighted_ambiguous_score: float | None = None,
) -> str:
    productive_score = float(weighted_productive_score or 0.0)
    ambiguous_score = float(weighted_ambiguous_score or 0.0)
    if (
        recent_progress == "good"
        and friction_level == "low"
        and last_question_productive
        and productive_score >= 1.2
        and ambiguous_score <= 0.35
    ):
        return "high"
    if (
        recent_progress == "stalled"
        or friction_level == "high"
        or ambiguous_score >= 1.0
        or (productive_score < 0.45 and friction_level != "low")
    ):
        return "low"
    return "medium"


def _answer_is_productive(answer_log: dict[str, Any]) -> bool:
    slot = _clean_text(answer_log.get("slot"))
    answer = _clean_text(answer_log.get("answer"))
    if not slot or not answer or _answer_is_ambiguous(answer_log):
        return False
    return _answer_has_slot_signal(slot, answer)


def _answer_is_ambiguous(answer_log: dict[str, Any]) -> bool:
    slot = _clean_text(answer_log.get("slot"))
    answer = _normalize_text(answer_log.get("answer"))
    if not answer:
        return True
    if slot and _answer_has_slot_signal(slot, answer):
        return False
    compact_answer = re.sub(r"[^a-z0-9]+", " ", answer).strip()
    if len(compact_answer) <= 4:
        return True
    if any(re.search(pattern, compact_answer) for pattern in _AMBIGUOUS_ANSWER_PATTERNS):
        return True
    evasive_hits = sum(1 for pattern in _EVASIVE_PATTERNS if re.search(pattern, compact_answer))
    if evasive_hits >= 1 and len(compact_answer.split()) <= 8:
        return True
    if evasive_hits >= 2:
        return True
    if re.search(r"\b(si|sí)\b", compact_answer) and evasive_hits >= 1:
        return True
    return False


def _answer_has_slot_signal(slot: str, answer: str) -> bool:
    normalized_answer = _normalize_text(answer)
    if slot == "aportes_actuales":
        return bool(
            re.search(
                r"\b(no paga|no aporta|no me pasa|no cumple|dejo de pagar|aporta poco|paga poco|regularmente|todos los meses|me deposita|me gira|a veces cumple|cumple a medias|no me deposita|no me transfiere)\b",
                normalized_answer,
            )
        )
    if slot == "convivencia":
        return bool(
            re.search(
                r"\b(vive conmigo|convive conmigo|esta conmigo|esta a mi cargo|vive con su padre|vive con su madre|convive con su padre|convive con su madre|esta con el|esta con ella|lo tengo a cargo|la tengo a cargo)\b",
                normalized_answer,
            )
        )
    if slot == "notificacion":
        return bool(
            re.search(
                r"\b(no se donde vive|desconozco su domicilio|no lo puedo ubicar|no la puedo ubicar|tengo domicilio|se donde vive|lo puedo ubicar|la puedo ubicar|no tengo direccion|no tengo domicilio|se borro|no aparece|no se donde esta)\b",
                normalized_answer,
            )
        )
    if slot == "ingresos":
        return bool(
            re.search(
                r"\b(trabaja|tiene ingresos|esta en blanco|monotribut|changas|cobra|sueldo|salario|esta en negro|hace changas|tiene trabajo informal|cobra por dia|tiene un ingreso fijo)\b",
                normalized_answer,
            )
        )
    if slot == "urgencia":
        return bool(
            re.search(
                r"\b(urgente|urgencia|no alcanza|medicamentos|remedios|tratamiento|colegio|alquiler)\b",
                normalized_answer,
            )
        )
    if slot == "antecedentes":
        return bool(
            re.search(
                r"\b(ya reclame|hubo acuerdo|mediacion|intimacion|carta documento|nunca reclame)\b",
                normalized_answer,
            )
        )
    return False


def _dedupe_strings(items: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(_clean_text(item))
    return result


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
