# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\dialogue_policy_service.py
from __future__ import annotations

import re
import unicodedata
from typing import Any


MAX_PRIORITY_MISSING_KEYS = 1
DOMINANT_REFINE_WINDOW = 3
LOOP_RISK_VALUES = {"medium", "high"}
IMPORTANCE_SCORES = {"core": 30, "relevant": 20, "accessory": 10}
PURPOSE_SCORES = {"enable": 15, "identify": 12, "quantify": 9, "prove": 7, "situational": 3}
PRIORITY_SCORES = {"critical": 10, "high": 8, "required": 8, "ordinary": 4, "medium": 4, "optional": 1, "low": 1}
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
PURPOSE_TOKEN_MAP = {
    "identify": ("dni", "nombre", "domicilio", "identidad", "rol", "progenitor", "parte"),
    "enable": ("convivencia", "vinculo", "hijos", "notificacion", "jurisdiccion"),
    "quantify": ("ingresos", "gastos", "monto", "cuota", "salario"),
    "prove": ("comprobante", "recibo", "prueba", "testigo", "mensaje", "captura", "expediente"),
    "situational": ("urgencia", "distancia", "frecuencia", "contexto", "conflicto"),
}


def resolve_dialogue_policy(
    *,
    conversation_state: dict[str, Any] | None,
    turn_signals: dict[str, Any] | None = None,
    pipeline_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del turn_signals, pipeline_payload

    state = _as_dict(conversation_state)
    progress = _as_dict(state.get("progress_signals"))
    missing_facts = _normalize_missing_facts(state.get("missing_facts"))
    asked_questions = _as_str_list(state.get("asked_questions"))
    turn_count = int(state.get("turn_count") or 0)
    blocking_missing = bool(progress.get("blocking_missing"))
    case_completeness = _clean_text(progress.get("case_completeness")).lower() or "low"

    asked_missing_keys = _infer_asked_missing_keys(
        asked_questions=asked_questions,
        missing_facts=missing_facts,
    )
    priority_missing = _rank_missing_facts(
        missing_facts=missing_facts,
        asked_questions=asked_questions,
        asked_missing_keys=asked_missing_keys,
    )
    dominant_missing = _resolve_dominant_missing(priority_missing)
    dominant_missing = _refine_dominant_missing(
        priority_missing=priority_missing,
        dominant_missing=dominant_missing,
    )
    loop_risk = _detect_loop_risk(
        progress_signals=progress,
        turn_count=turn_count,
        asked_questions=asked_questions,
        priority_missing=priority_missing,
        dominant_missing=dominant_missing,
        asked_missing_keys=asked_missing_keys,
    )
    guidance_strength = _resolve_guidance_strength(
        blocking_missing=blocking_missing,
        case_completeness=case_completeness,
        dominant_missing=dominant_missing,
        loop_risk=loop_risk,
    )
    action = _resolve_base_action(
        blocking_missing=blocking_missing,
        case_completeness=case_completeness,
        loop_risk=loop_risk,
        dominant_missing=dominant_missing,
        priority_missing=priority_missing,
    )
    policy_stage = _resolve_policy_stage(action=action, case_completeness=case_completeness)
    should_ask_first = _resolve_should_ask_first(
        action=action,
        guidance_strength=guidance_strength,
    )
    should_offer_partial_guidance = _resolve_should_offer_partial_guidance(
        action=action,
        guidance_strength=guidance_strength,
    )
    confidence = _resolve_policy_confidence(
        action=action,
        blocking_missing=blocking_missing,
        case_completeness=case_completeness,
        loop_risk=loop_risk,
        dominant_missing=dominant_missing,
    )

    return {
        "action": action,
        "reason": _build_reason(
            action=action,
            blocking_missing=blocking_missing,
            case_completeness=case_completeness,
            loop_risk=loop_risk,
            dominant_missing=dominant_missing,
        ),
        "confidence": confidence,
        "max_questions": 1 if action in {"ask", "hybrid", "confirm"} else 0,
        "priority_missing_keys": [item["key"] for item in priority_missing[:MAX_PRIORITY_MISSING_KEYS]],
        "dominant_missing_key": dominant_missing.get("key", ""),
        "dominant_missing_purpose": dominant_missing.get("purpose", ""),
        "dominant_missing_importance": dominant_missing.get("importance", ""),
        "dominant_missing_priority": dominant_missing.get("priority", ""),
        "should_ask_first": should_ask_first,
        "should_offer_partial_guidance": should_offer_partial_guidance,
        "policy_stage": policy_stage,
        "guidance_strength": guidance_strength,
        "loop_risk": loop_risk,
    }


def _resolve_dominant_missing(priority_missing: list[dict[str, Any]]) -> dict[str, Any]:
    if not priority_missing:
        return _empty_missing()
    return _as_missing_descriptor(priority_missing[0])


def _refine_dominant_missing(
    *,
    priority_missing: list[dict[str, Any]],
    dominant_missing: dict[str, Any],
) -> dict[str, Any]:
    if not priority_missing:
        return dominant_missing
    for item in priority_missing[:DOMINANT_REFINE_WINDOW]:
        descriptor = _as_missing_descriptor(item)
        if descriptor["importance"] == "core" and descriptor["purpose"] in {"identify", "enable"}:
            return descriptor
    return dominant_missing


def _resolve_base_action(
    *,
    blocking_missing: bool,
    case_completeness: str,
    loop_risk: str,
    dominant_missing: dict[str, Any],
    priority_missing: list[dict[str, Any]],
) -> str:
    dominant_purpose = _clean_text(dominant_missing.get("purpose")).lower()
    dominant_importance = _clean_text(dominant_missing.get("importance")).lower()

    if loop_risk == "high":
        return "advise" if case_completeness == "high" else "hybrid"
    if blocking_missing and dominant_importance == "core":
        return "ask"
    if dominant_purpose in {"identify", "enable"} and dominant_importance == "core":
        return "ask"
    if dominant_purpose == "quantify":
        if case_completeness == "high" and not blocking_missing:
            return "hybrid"
        return "hybrid" if priority_missing else "defer"
    if dominant_purpose == "prove":
        return "advise" if case_completeness == "high" and not blocking_missing else "hybrid"
    if dominant_purpose == "situational" or dominant_importance == "accessory":
        if case_completeness == "high":
            return "advise"
        return "hybrid" if priority_missing else "defer"
    if blocking_missing:
        return "ask"
    if case_completeness == "low":
        return "ask" if priority_missing else "defer"
    if case_completeness == "medium":
        return "hybrid"
    if case_completeness == "high":
        return "advise"
    return "defer"


def _resolve_policy_stage(*, action: str, case_completeness: str) -> str:
    if action == "ask":
        return "clarify"
    if action == "advise":
        return "advance" if case_completeness == "high" else "guide"
    if action == "hybrid":
        return "guide"
    if action == "confirm":
        return "clarify"
    return "guide"


def _resolve_guidance_strength(
    *,
    blocking_missing: bool,
    case_completeness: str,
    dominant_missing: dict[str, Any],
    loop_risk: str,
) -> str:
    dominant_purpose = _clean_text(dominant_missing.get("purpose")).lower()
    dominant_importance = _clean_text(dominant_missing.get("importance")).lower()

    if loop_risk == "high":
        return "medium"
    if blocking_missing and dominant_importance == "core" and dominant_purpose in {"identify", "enable"}:
        return "low"
    if dominant_purpose == "prove" and case_completeness in {"medium", "high"}:
        return "high"
    if dominant_purpose == "quantify":
        return "medium"
    if case_completeness == "high":
        return "high"
    if case_completeness == "medium":
        return "medium"
    return "low"


def _resolve_should_ask_first(*, action: str, guidance_strength: str) -> bool:
    if action == "ask":
        return True
    if action == "hybrid" and guidance_strength == "low":
        return True
    return False


def _resolve_should_offer_partial_guidance(*, action: str, guidance_strength: str) -> bool:
    if action == "advise":
        return True
    if action == "hybrid":
        return guidance_strength in {"medium", "high"}
    return guidance_strength == "high"


def _detect_loop_risk(
    *,
    progress_signals: dict[str, Any],
    turn_count: int,
    asked_questions: list[str],
    priority_missing: list[dict[str, Any]],
    dominant_missing: dict[str, Any],
    asked_missing_keys: list[str],
) -> str:
    repeated_question_risk = _clean_text(progress_signals.get("repeated_question_risk")).lower()
    question_count = int(progress_signals.get("question_count") or len(asked_questions))
    dominant_key = _canonical_key(dominant_missing.get("key"))
    same_missing_key_hits = sum(1 for item in asked_missing_keys if item == dominant_key)
    same_missing_hits = _count_semantic_repetitions(
        asked_questions=asked_questions,
        dominant_missing=dominant_missing,
    )
    purpose_hits = _count_purpose_repetitions(
        asked_questions=asked_questions,
        purpose=_clean_text(dominant_missing.get("purpose")).lower(),
    )
    if same_missing_key_hits >= 2:
        return "high"
    if same_missing_hits >= 2:
        return "high"
    if turn_count >= 5 and question_count >= 3 and repeated_question_risk in LOOP_RISK_VALUES:
        return "high"
    if turn_count >= 4 and question_count >= 3 and priority_missing and purpose_hits >= 2:
        return "high"
    if same_missing_key_hits >= 1 or same_missing_hits >= 1 or purpose_hits >= 2:
        return "medium"
    if turn_count >= 3 and repeated_question_risk in LOOP_RISK_VALUES:
        return "medium"
    return "low"


def _infer_asked_missing_keys(
    *,
    asked_questions: list[str],
    missing_facts: list[dict[str, Any]],
) -> list[str]:
    inferred: list[str] = []
    for item in missing_facts:
        descriptor = _as_missing_descriptor(item)
        if _question_already_covers_missing(
            key=descriptor["key"],
            label=descriptor["label"],
            asked_questions=asked_questions,
        ):
            inferred.append(descriptor["key"])
    return inferred


def _count_semantic_repetitions(
    *,
    asked_questions: list[str],
    dominant_missing: dict[str, Any],
) -> int:
    key = _canonical_key(dominant_missing.get("key"))
    label = _clean_text(dominant_missing.get("label") or key)
    if not key and not label:
        return 0

    target_tokens = _extract_relevant_tokens(f"{key} {label}")
    hits = 0
    for question in asked_questions:
        question_tokens = _extract_relevant_tokens(question)
        if key and key in _normalize_text(question):
            hits += 1
            continue
        if target_tokens and len(target_tokens.intersection(question_tokens)) >= min(2, len(target_tokens)):
            hits += 1
    return hits


def _count_purpose_repetitions(*, asked_questions: list[str], purpose: str) -> int:
    purpose_tokens = PURPOSE_TOKEN_MAP.get(purpose, ())
    if not purpose_tokens:
        return 0
    hits = 0
    for question in asked_questions:
        haystack = _normalize_text(question)
        if any(token in haystack for token in purpose_tokens):
            hits += 1
    return hits


def _rank_missing_facts(
    *,
    missing_facts: list[dict[str, Any]],
    asked_questions: list[str],
    asked_missing_keys: list[str],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for item in missing_facts:
        key = _canonical_key(item.get("key"))
        if not key:
            continue
        purpose = _clean_text(item.get("purpose")).lower()
        priority = _clean_text(item.get("priority")).lower()
        label = _clean_text(item.get("label") or key)
        importance = _infer_missing_importance(
            key=key,
            purpose=purpose,
            priority=priority,
            label=label,
        )
        repeated_same_missing = _question_already_covers_missing(key=key, label=label, asked_questions=asked_questions)
        repeated_same_purpose = _count_purpose_repetitions(asked_questions=asked_questions, purpose=purpose) >= 2
        same_key_hits = sum(1 for item_key in asked_missing_keys if item_key == key)
        score = IMPORTANCE_SCORES.get(importance, 0)
        score += PURPOSE_SCORES.get(purpose, 0)
        score += PRIORITY_SCORES.get(priority, 0)
        if same_key_hits >= 1:
            score -= 40
        elif repeated_same_missing:
            score -= 30
        elif repeated_same_purpose and importance != "core":
            score -= 12
        enriched = dict(item)
        enriched["importance"] = importance
        enriched["_score"] = score
        ranked.append(enriched)
    ranked.sort(key=lambda item: (-int(item["_score"]), item["key"]))
    return ranked


def _question_already_covers_missing(*, key: str, label: str, asked_questions: list[str]) -> bool:
    normalized_key = _normalize_text(key)
    normalized_label = _normalize_text(label)
    label_tokens = [token for token in _extract_relevant_tokens(normalized_label) if token]
    for question in asked_questions:
        haystack = _normalize_text(question)
        question_tokens = _extract_relevant_tokens(question)
        if normalized_key and normalized_key in haystack:
            return True
        if label_tokens and len(set(label_tokens).intersection(question_tokens)) >= min(2, len(label_tokens)):
            return True
    return False


def _infer_missing_importance(
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
    return "accessory" if priority in {"low", "optional"} else "relevant"


def _resolve_policy_confidence(
    *,
    action: str,
    blocking_missing: bool,
    case_completeness: str,
    loop_risk: str,
    dominant_missing: dict[str, Any],
) -> str:
    dominant_key = _canonical_key(dominant_missing.get("key"))
    dominant_purpose = _clean_text(dominant_missing.get("purpose")).lower()
    dominant_importance = _clean_text(dominant_missing.get("importance")).lower()
    if not dominant_key and action != "advise":
        return "low"
    if blocking_missing and action != "ask":
        return "low"
    if loop_risk == "high":
        return "medium"
    if dominant_key and dominant_importance == "core" and dominant_purpose in {"identify", "enable"} and action == "ask":
        return "high"
    if dominant_key and dominant_purpose in {"quantify", "prove"} and action == "hybrid" and case_completeness in {"medium", "high"}:
        return "high"
    if dominant_key and action == "advise" and case_completeness == "high" and dominant_purpose in {"", "prove", "situational"}:
        return "high"
    if dominant_key and action in {"hybrid", "advise"}:
        return "medium"
    return "low"


def _build_reason(
    *,
    action: str,
    blocking_missing: bool,
    case_completeness: str,
    loop_risk: str,
    dominant_missing: dict[str, Any],
) -> str:
    missing_key = _clean_text(dominant_missing.get("key"))
    dominant_purpose = _clean_text(dominant_missing.get("purpose")).lower()
    dominant_importance = _clean_text(dominant_missing.get("importance")).lower()

    if loop_risk == "high":
        return "La conversacion ya insiste sobre la misma falta; conviene avanzar con ayuda parcial y evitar mas friccion."
    if action == "ask" and dominant_purpose in {"identify", "enable"} and dominant_importance == "core":
        return f"Falta un dato troncal para orientar con prudencia: {missing_key}.".strip()
    if action == "hybrid" and dominant_purpose == "quantify":
        return "Hay base suficiente para orientar parcialmente, pero falta un dato de cuantificacion relevante."
    if action == "hybrid" and dominant_purpose == "prove":
        return "La base del caso permite orientar, aunque todavia conviene sumar un elemento probatorio relevante."
    if action == "hybrid" and dominant_purpose == "situational":
        return "El faltante dominante es contextual y no justifica bloquear la orientacion util."
    if action == "ask" and blocking_missing:
        return f"Falta un dato bloqueante para orientar con prudencia: {missing_key}.".strip()
    if action == "ask" and case_completeness == "low":
        return "La base del caso todavia es insuficiente y conviene aclarar un dato prioritario antes de orientar."
    if action == "advise":
        return "La base conversacional actual es suficiente para orientar sin seguir repreguntando."
    return "La policy conversacional adopta un modo prudente con la informacion disponible."


def _as_missing_descriptor(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": _canonical_key(item.get("key")),
        "purpose": _clean_text(item.get("purpose")).lower(),
        "importance": _clean_text(item.get("importance")).lower() or _infer_missing_importance(
            key=_canonical_key(item.get("key")),
            purpose=_clean_text(item.get("purpose")).lower(),
            priority=_clean_text(item.get("priority")).lower(),
            label=_clean_text(item.get("label") or item.get("key")),
        ),
        "priority": _clean_text(item.get("priority")).lower(),
        "label": _clean_text(item.get("label") or item.get("key")),
    }


def _empty_missing() -> dict[str, Any]:
    return {
        "key": "",
        "purpose": "",
        "importance": "",
        "priority": "",
        "label": "",
    }


def _normalize_missing_facts(raw_items: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(raw_items):
        if not isinstance(item, dict):
            continue
        key = _canonical_key(item.get("key"))
        if not key:
            continue
        result.append(
            {
                "key": key,
                "label": _clean_text(item.get("label") or key),
                "priority": _clean_text(item.get("priority")).lower() or "ordinary",
                "purpose": _clean_text(item.get("purpose")).lower() or "situational",
                "source": _clean_text(item.get("source")) or "unknown",
                "importance": _clean_text(item.get("importance")).lower(),
            }
        )
    return result


def _extract_relevant_tokens(value: str) -> set[str]:
    normalized = _normalize_text(value).replace("_", " ")
    return {token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) >= 3}


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
