# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\progression_policy.py
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


MAX_RECENT_TURNS = 2
SEMANTIC_SIMILARITY_THRESHOLD = 0.82
OUTPUT_MODE_SEQUENCE = {
    "orientacion_inicial": "estructuracion",
    "estructuracion": "estrategia",
    "estrategia": "ejecucion",
    "ejecucion": "ejecucion",
}


def resolve_progression_policy(
    *,
    conversation_state: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
    conversational_intelligence: dict[str, Any] | None,
    intent_resolution: dict[str, Any] | None,
    execution_output: dict[str, Any] | None,
    pipeline_payload: dict[str, Any] | None,
    response_text: str,
) -> dict[str, Any]:
    state = _as_dict(conversation_state)
    policy = _as_dict(dialogue_policy)
    intelligence = _as_dict(conversational_intelligence)
    intent = _as_dict(intent_resolution)
    execution = _as_dict(execution_output)
    payload = _as_dict(pipeline_payload)
    previous_progression = normalize_progression_state(state.get("progression_state"))

    facts_collected = _extract_fact_keys(state)
    questions_asked = _as_str_list(state.get("asked_questions"))
    topics_covered = _resolve_topics_covered(
        conversation_state=state,
        pipeline_payload=payload,
        execution_output=execution,
    )
    candidate_output_mode = _resolve_candidate_output_mode(
        conversation_state=state,
        dialogue_policy=policy,
        intent_resolution=intent,
        execution_output=execution,
    )
    semantic_repetition = _detect_semantic_repetition(
        previous_progression=previous_progression,
        response_text=response_text,
        candidate_output_mode=candidate_output_mode,
        intent_resolution=intent,
        topics_covered=topics_covered,
    )
    has_new_facts = _has_new_facts(
        previous_progression=previous_progression,
        facts_collected=facts_collected,
    )
    selected_output_mode = _resolve_selected_output_mode(
        previous_progression=previous_progression,
        candidate_output_mode=candidate_output_mode,
        semantic_repetition=semantic_repetition,
        has_new_facts=has_new_facts,
        conversation_state=state,
        execution_output=execution,
    )
    progression_stage = _resolve_progression_stage(
        selected_output_mode=selected_output_mode,
        conversation_state=state,
        dialogue_policy=policy,
    )
    progress_focus = _build_progress_focus(
        conversation_state=state,
        dialogue_policy=policy,
        pipeline_payload=payload,
        execution_output=execution,
    )
    incremental_value = _resolve_incremental_value(
        selected_output_mode=selected_output_mode,
        semantic_repetition=semantic_repetition,
        has_new_facts=has_new_facts,
        progress_focus=progress_focus,
    )
    rendered_response_text = _render_progressed_response(
        selected_output_mode=selected_output_mode,
        response_text=response_text,
        progress_focus=progress_focus,
        execution_output=execution,
    )
    user_summary = _build_user_summary(
        selected_output_mode=selected_output_mode,
        semantic_repetition=semantic_repetition,
        incremental_value=incremental_value,
    )
    professional_summary = _build_professional_summary(
        selected_output_mode=selected_output_mode,
        progress_focus=progress_focus,
    )
    decision_required = selected_output_mode == "estrategia"
    decision_focus = _resolve_decision_focus(
        selected_output_mode=selected_output_mode,
        progress_focus=progress_focus,
    )

    return {
        "output_mode": selected_output_mode,
        "candidate_output_mode": candidate_output_mode,
        "progression_stage": progression_stage,
        "anti_repetition_guard": {
            "semantic_repetition_detected": bool(semantic_repetition.get("detected")),
            "max_similarity": float(semantic_repetition.get("max_similarity") or 0.0),
            "forced_progression": selected_output_mode != candidate_output_mode,
            "has_new_facts": has_new_facts,
        },
        "incremental_value": incremental_value,
        "topics_covered": topics_covered,
        "suggested_next_steps": list(progress_focus.get("strategic_actions") or [])[:3],
        "missing_focus": list(progress_focus.get("missing_highlights") or [])[:3],
        "decision_required": decision_required,
        "decision_focus": decision_focus,
        "user_summary": user_summary,
        "professional_summary": professional_summary,
        "rendered_response_text": rendered_response_text,
        "progression_state": {
            "facts_collected": facts_collected,
            "questions_asked": questions_asked[-8:],
            "topics_covered": topics_covered,
            "last_output_mode": selected_output_mode,
            "progression_stage": progression_stage,
            "recent_turns": list(previous_progression.get("recent_turns") or []),
            "last_intent_type": _clean_text(intent.get("intent_type")) or "general_information",
            "current_turn": {
                "output_mode": selected_output_mode,
                "intent_type": _clean_text(intent.get("intent_type")) or "general_information",
                "topics_covered": topics_covered,
                "question_asked": _clean_text(progress_focus.get("key_question")),
            },
        },
    }


def finalize_progression_state(
    *,
    progression_policy: dict[str, Any] | None,
    response_text: str,
) -> dict[str, Any]:
    policy = _as_dict(progression_policy)
    progression_state = normalize_progression_state(policy.get("progression_state"))
    current_turn = _as_dict(progression_state.pop("current_turn", {}))
    if not current_turn:
        return progression_state

    recent_turns = list(progression_state.get("recent_turns") or [])
    recent_turns.append(
        {
            "output_mode": _clean_text(current_turn.get("output_mode")),
            "intent_type": _clean_text(current_turn.get("intent_type")) or "general_information",
            "topics_covered": _as_str_list(current_turn.get("topics_covered")),
            "question_asked": _clean_text(current_turn.get("question_asked")),
            "response_fingerprint": _fingerprint(response_text),
        }
    )
    progression_state["recent_turns"] = recent_turns[-MAX_RECENT_TURNS:]
    progression_state["last_output_mode"] = _clean_text(policy.get("output_mode"))
    progression_state["progression_stage"] = _clean_text(policy.get("progression_stage")) or "initial"
    return progression_state


def normalize_progression_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    state = dict(raw or {})
    return {
        "facts_collected": _as_str_list(state.get("facts_collected")),
        "questions_asked": _as_str_list(state.get("questions_asked")),
        "topics_covered": _as_str_list(state.get("topics_covered")),
        "last_output_mode": _clean_text(state.get("last_output_mode")) or "",
        "progression_stage": _clean_text(state.get("progression_stage")) or "initial",
        "recent_turns": _normalize_recent_turns(state.get("recent_turns")),
        "last_intent_type": _clean_text(state.get("last_intent_type")) or "general_information",
    }


def _normalize_recent_turns(raw_turns: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(raw_turns):
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "output_mode": _clean_text(item.get("output_mode")),
                "intent_type": _clean_text(item.get("intent_type")) or "general_information",
                "topics_covered": _as_str_list(item.get("topics_covered")),
                "question_asked": _clean_text(item.get("question_asked")),
                "response_fingerprint": _clean_text(item.get("response_fingerprint")),
            }
        )
    return result[-MAX_RECENT_TURNS:]


def _extract_fact_keys(conversation_state: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for item in _as_list(conversation_state.get("known_facts")):
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key"))
        if key:
            keys.append(key)
    return _dedupe_strings(keys)


def _resolve_topics_covered(
    *,
    conversation_state: dict[str, Any],
    pipeline_payload: dict[str, Any],
    execution_output: dict[str, Any],
) -> list[str]:
    topics: list[str] = []
    domain = _clean_text(conversation_state.get("working_domain") or _as_dict(pipeline_payload.get("case_profile")).get("case_domain"))
    action_slug = _clean_text(_as_dict(pipeline_payload.get("classification")).get("action_slug"))
    if domain:
        topics.append(domain)
    if "alimentos" in action_slug:
        topics.append("alimentos")
    if "divorcio" in action_slug:
        topics.append("divorcio")

    values = [
        *_extract_fact_keys(conversation_state),
        *[
            _clean_text(item.get("label"))
            for item in _as_list(conversation_state.get("missing_facts"))
            if isinstance(item, dict)
        ],
        *_as_str_list(_as_dict(pipeline_payload.get("case_strategy")).get("procedural_focus")),
        *_as_str_list(_as_dict(execution_output.get("execution_output")).get("where_to_go")),
    ]
    joined = " ".join(_normalize_text(item) for item in values if item)
    if any(token in joined for token in ("domicilio", "competencia", "juzgado", "jurisdiccion")):
        topics.append("competencia")
    if any(token in joined for token in ("documentacion", "documental", "dni", "partida", "comprobante")):
        topics.append("documentos")
    if any(token in joined for token in ("cuota", "provisoria", "alimentos")):
        topics.append("pretension_inmediata")
    if _as_dict(execution_output).get("applies"):
        topics.append("ejecucion")
    return _dedupe_strings(topics)


def _resolve_candidate_output_mode(
    *,
    conversation_state: dict[str, Any],
    dialogue_policy: dict[str, Any],
    intent_resolution: dict[str, Any],
    execution_output: dict[str, Any],
) -> str:
    progress = _as_dict(conversation_state.get("progress_signals"))
    turn_count = int(conversation_state.get("turn_count") or 0)
    case_completeness = _clean_text(progress.get("case_completeness")).lower() or "low"
    blocking_missing = bool(progress.get("blocking_missing"))
    known_fact_count = int(progress.get("known_fact_count") or 0)
    intent_type = _clean_text(intent_resolution.get("intent_type")).lower()

    if bool(execution_output.get("applies")) or intent_type in {"action_now", "process_guidance", "document_guidance"}:
        return "ejecucion"
    if case_completeness == "high" and not blocking_missing:
        return "estrategia"
    if turn_count <= 1 and known_fact_count <= 1:
        return "orientacion_inicial"
    if known_fact_count >= 2 or _clean_text(dialogue_policy.get("dominant_missing_key")):
        return "estructuracion"
    return "orientacion_inicial"


def _detect_semantic_repetition(
    *,
    previous_progression: dict[str, Any],
    response_text: str,
    candidate_output_mode: str,
    intent_resolution: dict[str, Any],
    topics_covered: list[str],
) -> dict[str, Any]:
    current_fingerprint = _fingerprint(response_text)
    current_intent = _clean_text(intent_resolution.get("intent_type")) or "general_information"
    max_similarity = 0.0
    detected = False

    for item in _as_list(previous_progression.get("recent_turns")):
        if not isinstance(item, dict):
            continue
        previous_fingerprint = _clean_text(item.get("response_fingerprint"))
        similarity = SequenceMatcher(a=previous_fingerprint, b=current_fingerprint).ratio()
        same_output_mode = _clean_text(item.get("output_mode")) == candidate_output_mode
        same_intent = _clean_text(item.get("intent_type")) == current_intent
        shared_topics = set(_as_str_list(item.get("topics_covered"))).intersection(topics_covered)
        max_similarity = max(max_similarity, similarity)
        if similarity >= SEMANTIC_SIMILARITY_THRESHOLD and (same_output_mode or (same_intent and shared_topics)):
            detected = True

    return {
        "detected": detected,
        "max_similarity": round(max_similarity, 4),
    }


def _has_new_facts(
    *,
    previous_progression: dict[str, Any],
    facts_collected: list[str],
) -> bool:
    previous_facts = set(_as_str_list(previous_progression.get("facts_collected")))
    return bool(set(facts_collected) - previous_facts)


def _resolve_selected_output_mode(
    *,
    previous_progression: dict[str, Any],
    candidate_output_mode: str,
    semantic_repetition: dict[str, Any],
    has_new_facts: bool,
    conversation_state: dict[str, Any],
    execution_output: dict[str, Any],
) -> str:
    if bool(execution_output.get("applies")):
        return "ejecucion"

    previous_mode = _clean_text(previous_progression.get("last_output_mode"))
    turn_count = int(conversation_state.get("turn_count") or 0)
    repeated = bool(semantic_repetition.get("detected"))
    no_progress = not has_new_facts

    if repeated and no_progress:
        if previous_mode and previous_mode != candidate_output_mode:
            return candidate_output_mode
        return _advance_output_mode(candidate_output_mode)
    if previous_mode == "orientacion_inicial" and candidate_output_mode == "orientacion_inicial" and turn_count >= 2:
        return "estructuracion"
    if previous_mode == candidate_output_mode and no_progress and candidate_output_mode != "ejecucion" and turn_count >= 3:
        return _advance_output_mode(candidate_output_mode)
    return candidate_output_mode


def _advance_output_mode(output_mode: str) -> str:
    return OUTPUT_MODE_SEQUENCE.get(output_mode, "estructuracion")


def _resolve_progression_stage(
    *,
    selected_output_mode: str,
    conversation_state: dict[str, Any],
    dialogue_policy: dict[str, Any],
) -> str:
    progress = _as_dict(conversation_state.get("progress_signals"))
    blocking_missing = bool(progress.get("blocking_missing"))
    action = _clean_text(dialogue_policy.get("action")).lower()
    if selected_output_mode == "ejecucion":
        return "execution"
    if selected_output_mode == "estrategia":
        return "strategy"
    if selected_output_mode == "estructuracion":
        return "structuring_case"
    if blocking_missing and action in {"ask", "hybrid"}:
        return "clarification"
    return "initial"


def _build_progress_focus(
    *,
    conversation_state: dict[str, Any],
    dialogue_policy: dict[str, Any],
    pipeline_payload: dict[str, Any],
    execution_output: dict[str, Any],
) -> dict[str, Any]:
    known_highlights = _build_known_highlights(conversation_state)
    missing_highlights = _build_missing_highlights(conversation_state)
    case_strategy = _as_dict(pipeline_payload.get("case_strategy"))
    output_modes = _as_dict(pipeline_payload.get("output_modes"))
    user_mode = _as_dict(output_modes.get("user"))
    strategic_actions = _dedupe_strings(
        [
            *_as_str_list(case_strategy.get("recommended_actions")),
            *_as_str_list(case_strategy.get("procedural_focus")),
            *_as_str_list(user_mode.get("next_steps")),
        ]
    )[:4]
    key_question = (
        _clean_text(_as_dict(execution_output.get("execution_output")).get("followup_question"))
        or _clean_text(_as_dict(pipeline_payload.get("conversational")).get("question"))
        or _build_dominant_missing_question(dialogue_policy)
    )
    return {
        "known_highlights": known_highlights,
        "missing_highlights": missing_highlights,
        "strategic_actions": strategic_actions,
        "key_question": key_question,
    }


def _build_known_highlights(conversation_state: dict[str, Any]) -> list[str]:
    highlights: list[str] = []
    for item in _as_list(conversation_state.get("known_facts")):
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key"))
        value = item.get("value")
        if not key:
            continue
        highlights.append(_render_known_fact(key=key, value=value))
    return _dedupe_strings(highlights)[:3]


def _build_missing_highlights(conversation_state: dict[str, Any]) -> list[str]:
    highlights: list[str] = []
    for item in _as_list(conversation_state.get("missing_facts")):
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label") or item.get("key"))
        if label:
            highlights.append(label)
    return _dedupe_strings(highlights)[:3]


def _build_dominant_missing_question(dialogue_policy: dict[str, Any]) -> str:
    key = _clean_text(dialogue_policy.get("dominant_missing_key"))
    if not key:
        return ""
    return f"Necesito precisar {key.replace('_', ' ')}."


def _resolve_incremental_value(
    *,
    selected_output_mode: str,
    semantic_repetition: dict[str, Any],
    has_new_facts: bool,
    progress_focus: dict[str, Any],
) -> str:
    if selected_output_mode == "ejecucion":
        return "convert_information_into_action"
    if selected_output_mode == "estrategia":
        return "take_strategic_decision"
    if progress_focus.get("key_question"):
        return "ask_key_missing"
    if has_new_facts and not semantic_repetition.get("detected"):
        return "add_new_information"
    return "force_deeper_progress"


def _resolve_decision_focus(
    *,
    selected_output_mode: str,
    progress_focus: dict[str, Any],
) -> str:
    if selected_output_mode != "estrategia":
        return ""
    strategic_actions = _as_str_list(progress_focus.get("strategic_actions"))
    if strategic_actions:
        return strategic_actions[0]
    missing_highlights = _as_str_list(progress_focus.get("missing_highlights"))
    if missing_highlights:
        return missing_highlights[0]
    return "definir el camino practico mas conveniente"


def _render_progressed_response(
    *,
    selected_output_mode: str,
    response_text: str,
    progress_focus: dict[str, Any],
    execution_output: dict[str, Any],
) -> str:
    if selected_output_mode == "ejecucion":
        rendered = _clean_text(execution_output.get("rendered_response_text"))
        if rendered:
            return rendered
    if selected_output_mode == "orientacion_inicial":
        return response_text

    actions = _as_str_list(progress_focus.get("strategic_actions"))
    missing = _as_str_list(progress_focus.get("missing_highlights"))
    known = _as_str_list(progress_focus.get("known_highlights"))
    key_question = _clean_text(progress_focus.get("key_question"))
    sections: list[str] = []

    if selected_output_mode == "estructuracion":
        if known:
            sections.append("Lo que ya aparece claro en el caso:\n" + "\n".join(f"- {item}" for item in known))
        if missing:
            sections.append("Lo que ahora conviene ordenar para que el caso avance:\n" + "\n".join(f"- {item}" for item in missing))
        if actions:
            sections.append("Con eso, el siguiente movimiento pasa por:\n" + "\n".join(f"- {item}" for item in actions[:2]))
    elif selected_output_mode == "estrategia":
        if actions:
            sections.append("Con lo que ya surge del caso, la estrategia pasa por:\n" + "\n".join(f"- {item}" for item in actions[:3]))
        if missing:
            sections.append("Lo que todavia puede cambiar el encuadre:\n" + "\n".join(f"- {item}" for item in missing[:2]))
    if not sections and response_text:
        sections.append(response_text)
    if key_question:
        sections.append(f"Para seguir sin repetir la orientacion inicial, necesito un dato puntual: {key_question}")
    return "\n\n".join(section for section in sections if section.strip()).strip() or response_text


def _build_user_summary(
    *,
    selected_output_mode: str,
    semantic_repetition: dict[str, Any],
    incremental_value: str,
) -> str:
    if selected_output_mode == "ejecucion":
        return "La respuesta deja de quedarse en la orientacion inicial y pasa a pasos concretos para mover el caso."
    if selected_output_mode == "estrategia":
        return "La conversacion avanza desde la explicacion base hacia una decision estrategica mas concreta."
    if selected_output_mode == "estructuracion":
        if semantic_repetition.get("detected"):
            return "Para no repetir la misma orientacion, ahora la conversacion ordena el caso y apunta al dato que realmente destraba el siguiente paso."
        return "La conversacion ya no esta en una apertura general: pasa a ordenar el caso con foco en lo que define el encuadre."
    if incremental_value == "ask_key_missing":
        return "La respuesta pide un dato puntual que cambia la estrategia, no una aclaracion generica."
    return "La respuesta aporta una primera orientacion util para empezar."


def _build_professional_summary(
    *,
    selected_output_mode: str,
    progress_focus: dict[str, Any],
) -> str:
    action_count = len(_as_str_list(progress_focus.get("strategic_actions")))
    missing_count = len(_as_str_list(progress_focus.get("missing_highlights")))
    if selected_output_mode == "ejecucion":
        return "Modo de salida priorizado hacia ejecucion y accion inmediata."
    if selected_output_mode == "estrategia":
        return f"Modo de salida evolucionado a estrategia con {action_count} focos de accion y {missing_count} faltantes de cierre."
    if selected_output_mode == "estructuracion":
        return f"Modo de salida evolucionado a estructuracion con {missing_count} faltantes que ordenan el caso."
    return "Modo de salida inicial sin evolucion forzada."


def _render_known_fact(*, key: str, value: Any) -> str:
    normalized_key = _normalize_text(key)
    clean_value = _clean_text(value)
    if normalized_key == "hay_hijos":
        return "Hay hijos involucrados." if str(value).lower() not in {"false", "0", "no"} else "No aparecen hijos involucrados."
    if normalized_key == "rol_procesal" and clean_value:
        return f"El rol procesal informado es {clean_value}."
    if normalized_key == "divorcio_modalidad" and clean_value:
        return f"La modalidad del divorcio aparece como {clean_value}."
    if clean_value:
        return f"{key.replace('_', ' ').capitalize()}: {clean_value}."
    return key.replace("_", " ").capitalize() + "."


def _fingerprint(text: str) -> str:
    normalized = _normalize_text(text)
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:320]


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
