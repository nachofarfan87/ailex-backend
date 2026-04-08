# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\response_composition_service.py
from __future__ import annotations

import re
from typing import Any

from app.services.strategic_decision_service import resolve_strategic_decision


def resolve_response_composition(
    *,
    output_mode: str,
    smart_strategy: dict[str, Any] | None,
    strategy_composition_profile: dict[str, Any] | None,
    strategy_language_profile: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
    execution_output: dict[str, Any] | None,
    progression_policy: dict[str, Any] | None,
    pipeline_payload: dict[str, Any] | None,
    api_payload: dict[str, Any] | None,
    followup_question: str = "",
) -> dict[str, Any]:
    normalized_output_mode = str(output_mode or "").strip().lower()
    smart_strategy = dict(smart_strategy or {})
    strategy_composition_profile = dict(strategy_composition_profile or {})
    strategy_language_profile = dict(strategy_language_profile or {})
    conversation_state = dict(conversation_state or {})
    dialogue_policy = dict(dialogue_policy or {})
    execution_output = dict(execution_output or {})
    progression_policy = dict(progression_policy or {})
    pipeline_payload = dict(pipeline_payload or {})
    api_payload = dict(api_payload or {})
    strategy_mode = str(smart_strategy.get("strategy_mode") or "").strip().lower()

    if normalized_output_mode == "estructuracion":
        sections = _render_structuring_sections(
            conversation_state=conversation_state,
            dialogue_policy=dialogue_policy,
            progression_policy=progression_policy,
            strategy_mode=strategy_mode,
            language_profile=strategy_language_profile,
            followup_question=str(followup_question or "").strip(),
        )
        metadata = _build_composition_metadata(
            output_mode=normalized_output_mode,
            strategy_mode=strategy_mode,
            sections=sections,
            language_profile=strategy_language_profile,
        )
        return {
            "response_sections": sections,
            "rendered_response_text": "\n\n".join(s for s in sections if s.strip()).strip(),
            "composition_metadata": metadata,
        }

    if normalized_output_mode == "estrategia":
        strategic_decision = resolve_strategic_decision(
            conversation_state=conversation_state,
            pipeline_payload=pipeline_payload,
            progression_policy=progression_policy,
        )
        sections = _render_strategy_sections(
            conversation_state=conversation_state,
            strategic_decision=strategic_decision,
            strategy_mode=strategy_mode,
            language_profile=strategy_language_profile,
            followup_question=str(followup_question or "").strip(),
        )
        metadata = _build_composition_metadata(
            output_mode=normalized_output_mode,
            strategy_mode=strategy_mode,
            sections=sections,
            language_profile=strategy_language_profile,
        )
        return {
            "response_sections": sections,
            "rendered_response_text": "\n\n".join(s for s in sections if s.strip()).strip(),
            "composition_metadata": metadata,
            "strategic_decision": strategic_decision,
        }

    if normalized_output_mode == "ejecucion":
        sections = _render_execution_sections(
            pipeline_payload=pipeline_payload,
            execution_output=execution_output,
            strategy_mode=strategy_mode,
            language_profile=strategy_language_profile,
            strategy_composition_profile=strategy_composition_profile,
            followup_question=str(followup_question or "").strip(),
        )
        metadata = _build_composition_metadata(
            output_mode=normalized_output_mode,
            strategy_mode=strategy_mode,
            sections=sections,
            language_profile=strategy_language_profile,
        )
        return {
            "response_sections": sections,
            "rendered_response_text": "\n\n".join(s for s in sections if s.strip()).strip(),
            "composition_metadata": metadata,
        }

    return {
        "response_sections": [],
        "rendered_response_text": str(api_payload.get("response_text") or "").strip(),
        "composition_metadata": {
            "output_mode": normalized_output_mode,
            "strategy_mode": strategy_mode,
            "section_count": 0,
            "render_family": "fallback",
            "expects_followup": False,
            "closing_applied": False,
            "allow_postprocessor_closing": True,
        },
    }


# ── Metadata construction ────────────────────────────────────────────────────

def _build_composition_metadata(
    *,
    output_mode: str,
    strategy_mode: str,
    sections: list[str],
    language_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Construye metadata explícita para que el postprocessor sepa:
    - qué familia de render se usó
    - si composition ya incluyó un closing
    - si se espera un follow-up
    - si el postprocessor tiene permiso de agregar su propio closing
    """
    render_family = _resolve_render_family(output_mode=output_mode, strategy_mode=strategy_mode)
    expects_followup = _sections_contain_followup(sections)
    closing_applied = _sections_contain_closing(sections, language_profile=language_profile)

    # El postprocessor NO debe agregar cierre cuando:
    # - composition ya cerró (closing_applied)
    # - el modo es clarificación (el turno termina en pregunta, no en cierre)
    # - el modo es conclusivo sin follow-up (close_without_more_questions)
    allow_postprocessor_closing = not (
        closing_applied
        or render_family == "clarification"
        or (render_family == "conclusive" and not expects_followup)
    )

    return {
        "output_mode": output_mode,
        "strategy_mode": strategy_mode,
        "section_count": len([s for s in sections if s.strip()]),
        "render_family": render_family,
        "expects_followup": expects_followup,
        "closing_applied": closing_applied,
        "allow_postprocessor_closing": allow_postprocessor_closing,
    }


def _resolve_render_family(*, output_mode: str, strategy_mode: str) -> str:
    """
    Determina la familia de render. Gobierna cómo el postprocessor debe tratar el texto.

    - "clarification": turno termina en pregunta crítica (clarify_critical)
    - "conclusive": turno cierra sin abrir más preguntas (close_without_more_questions)
    - "action": turno orienta a acción concreta (action_first, guide en ejecucion)
    - "structured": turno estructura el caso (estructuracion)
    - "guided": turno orienta con prudencia (orient_with_prudence, guide_next_step en estrategia)
    """
    if strategy_mode == "clarify_critical":
        return "clarification"
    if strategy_mode == "close_without_more_questions":
        return "conclusive"
    if output_mode == "ejecucion" or strategy_mode == "action_first":
        return "action"
    if output_mode == "estructuracion":
        return "structured"
    return "guided"


def _sections_contain_followup(sections: list[str]) -> bool:
    """True si alguna sección termina con una pregunta."""
    return any("?" in s for s in sections if s.strip())


def _sections_contain_closing(
    sections: list[str],
    language_profile: dict[str, Any],
) -> bool:
    """True si la última sección sustantiva coincide con el closing del language profile."""
    closing = str(language_profile.get("selected_closing") or "").strip()
    if not closing:
        return False
    non_empty = [s.strip() for s in sections if s.strip()]
    if not non_empty:
        return False
    last = non_empty[-1]
    return closing.casefold() in last.casefold() or last.casefold() in closing.casefold()


# ── Section renderers ────────────────────────────────────────────────────────

def _render_structuring_sections(
    *,
    conversation_state: dict[str, Any],
    dialogue_policy: dict[str, Any],
    progression_policy: dict[str, Any],
    strategy_mode: str,
    language_profile: dict[str, Any],
    followup_question: str,
) -> list[str]:
    known_items = [_truncate_text(item) for item in _select_known_case_facts(conversation_state)[:3]]
    missing_items = [_truncate_text(item) for item in _select_missing_case_facts(conversation_state)[:3]]
    point_key = _resolve_point_key(dialogue_policy, conversation_state)

    sections: list[str] = []
    if strategy_mode == "clarify_critical":
        sections.append(str(language_profile.get("selected_opening") or "Con lo que ya sabemos, el punto que define el encuadre ahora es este."))
        if known_items:
            sections.append(f"Lo que ya aparece claro es: {known_items[0]}")
        if point_key:
            sections.append(f"El dato que falta para ordenar bien el caso es: {_truncate_text(point_key)}.")
        if followup_question:
            sections.append(f"{str(language_profile.get('selected_followup_intro') or 'Necesito confirmar esto:')} {followup_question}")
        return [item for item in sections if item.strip()]

    if strategy_mode == "guide_next_step":
        sections.append(str(language_profile.get("selected_opening") or "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor."))
        if point_key:
            sections.append(f"Ahora conviene definir primero: {_truncate_text(point_key)}.")
        elif missing_items:
            sections.append(f"Ahora conviene definir primero: {missing_items[0]}.")
        if known_items:
            sections.append("Lo que ya esta claro hasta aca:\n" + "\n".join(f"- {item}" for item in known_items[:2]))
        if followup_question:
            sections.append(f"{str(language_profile.get('selected_followup_intro') or 'Para avanzar sin perder foco, necesito confirmar:')} {followup_question}")
        return [item for item in sections if item.strip()]

    if strategy_mode in {"orient_with_prudence", "close_without_more_questions"}:
        sections.append(str(language_profile.get("selected_opening") or "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor."))
        if known_items:
            sections.append("Con lo que me contaste hasta ahora:\n" + "\n".join(f"- {item}" for item in known_items[:2]))
        if missing_items and strategy_mode != "close_without_more_questions":
            sections.append(f"Lo que todavia falta definir para cerrar bien el encuadre es: {missing_items[0]}.")
        # close_without_more_questions: composition agrega el cierre, postprocessor no debe agregar el suyo
        if strategy_mode == "close_without_more_questions":
            closing = str(language_profile.get("selected_closing") or "").strip()
            if closing:
                sections.append(closing)
        return [item for item in sections if item.strip()]

    sections.append(
        _pick_conversational_variant(
            conversation_state=conversation_state,
            key="structuring_open",
            options=(
                "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
                "Con lo que ya sabemos, el caso se deja ordenar con bastante mas claridad.",
            ),
        )
    )
    sections.append(
        "Con lo que me contaste hasta ahora:\n"
        + "\n".join(f"- {item}" for item in (known_items or ["Ya hay una base inicial del caso, pero conviene ordenarla mejor."]))
    )
    sections.append(
        "Ahora lo que todavia falta definir para cerrar bien el encuadre es esto:\n"
        + "\n".join(f"- {item}" for item in (missing_items or ["Queda cerrar el dato que define el encuadre final."]))
    )
    if point_key:
        sections.append(f"Ahora lo mas importante es: {_truncate_text(point_key)}.")
    elif progression_policy.get("missing_focus"):
        focus = str((progression_policy.get("missing_focus") or [""])[0]).strip()
        if focus:
            sections.append(f"Ahora lo mas importante es: {_truncate_text(focus)}.")
    if followup_question:
        sections.append(
            f"{_pick_conversational_variant(conversation_state=conversation_state, key='structuring_followup', options=('Para seguir sin cerrar esto en falso, necesito confirmar:', 'Para avanzar con una orientacion mas firme, necesito confirmar:'))} {followup_question}"
        )
    return [item for item in sections if item.strip()]


def _render_strategy_sections(
    *,
    conversation_state: dict[str, Any],
    strategic_decision: dict[str, Any],
    strategy_mode: str,
    language_profile: dict[str, Any],
    followup_question: str,
) -> list[str]:
    recommended_path = _truncate_text(_strip_known_quick_start(str(strategic_decision.get("recommended_path") or "").strip()))
    priority_action = _truncate_text(_strip_known_quick_start(str(strategic_decision.get("priority_action") or "").strip()))
    justification = str(strategic_decision.get("justification") or "").strip()
    alternative_path = _truncate_text(_strip_known_quick_start(str(strategic_decision.get("alternative_path") or "").strip()))
    alternative_reason = str(strategic_decision.get("alternative_reason") or "").strip()
    normalized_justification = _truncate_text(justification.rstrip(" .:"))
    normalized_alternative_reason = _truncate_text(alternative_reason.rstrip(" .:"))
    if normalized_justification:
        normalized_justification = normalized_justification[:1].upper() + normalized_justification[1:]

    sections: list[str] = []
    if strategy_mode == "clarify_critical":
        if recommended_path:
            sections.append(f"{str(language_profile.get('selected_opening') or 'Con lo que hay hoy, la via todavia depende de este punto:')} {recommended_path}")
        if priority_action:
            sections.append(f"Antes de desarrollar mas la estrategia, conviene definir: {priority_action}")
        if followup_question:
            sections.append(f"{str(language_profile.get('selected_followup_intro') or 'Necesito confirmar esto:')} {followup_question}")
        return [item for item in sections if item.strip()]

    if strategy_mode == "guide_next_step":
        if recommended_path:
            sections.append(f"{str(language_profile.get('selected_bridge') or 'Con lo que hay hoy, conviene avanzar asi:')} {recommended_path}")
        if priority_action:
            sections.append(f"El siguiente movimiento util seria: {priority_action}")
        if normalized_justification:
            sections.append(f"{normalized_justification}.")
        if alternative_path and alternative_path != recommended_path:
            sections.append(
                f"La otra via existe, pero hoy queda mas atras: {alternative_path}. {normalized_alternative_reason or 'Normalmente deja mas puntos criticos abiertos antes de presentar'}."
            )
        if followup_question:
            sections.append(f"{str(language_profile.get('selected_followup_intro') or 'Para terminar de orientar bien ese paso, necesito confirmar:')} {followup_question}")
        return [item for item in sections if item.strip()]

    if strategy_mode == "orient_with_prudence":
        if recommended_path:
            sections.append(f"{str(language_profile.get('selected_bridge') or 'Con lo que hay hoy, conviene avanzar asi:')} {recommended_path}")
        if normalized_justification:
            sections.append(f"{normalized_justification}.")
        if priority_action:
            sections.append(f"El paso que priorizaria ahora es: {priority_action}")
        if alternative_path and alternative_path != recommended_path:
            sections.append(
                f"La otra via existe, pero hoy queda mas atras: {alternative_path}. {normalized_alternative_reason or 'Normalmente deja mas puntos criticos abiertos antes de presentar'}."
            )
        return [item for item in sections if item.strip()]

    if strategy_mode == "close_without_more_questions":
        if recommended_path:
            sections.append(f"{str(language_profile.get('selected_bridge') or 'Con lo que hay hoy, conviene avanzar asi:')} {recommended_path}")
        if priority_action:
            sections.append(f"El paso que priorizaria ahora es: {priority_action}")
        if alternative_path and alternative_path != recommended_path:
            sections.append(
                f"La otra via existe, pero hoy queda mas atras: {alternative_path}. {normalized_alternative_reason or 'Normalmente deja mas puntos criticos abiertos antes de presentar'}."
            )
        # close_without_more_questions: composition cierra, postprocessor no debe agregar cierre
        closing = str(language_profile.get("selected_closing") or "").strip()
        if closing:
            sections.append(closing)
        return [item for item in sections if item.strip()]

    if recommended_path:
        sections.append(
            f"{_pick_conversational_variant(conversation_state=conversation_state, key='strategy_open', options=('Hoy, lo mas solido es ir por este camino:', 'Si ordenamos esto estrategicamente, la mejor via es:', 'Con lo que hay hoy, conviene avanzar asi:'))} {recommended_path}"
        )
    if normalized_justification:
        sections.append(f"{normalized_justification}.")
    if priority_action:
        sections.append(
            f"{_pick_conversational_variant(conversation_state=conversation_state, key='strategy_action', options=('El paso que priorizaria ahora es:', 'Si tuviera que ordenar el siguiente movimiento, iria por esto:'))} {priority_action}"
        )
    if alternative_path and alternative_path != recommended_path:
        sections.append(
            f"{_pick_conversational_variant(conversation_state=conversation_state, key='strategy_alternative', options=('La otra via existe, pero hoy queda mas atras:', 'Como alternativa se puede pensar esta via, pero hoy queda en segundo plano:'))} {alternative_path}. {normalized_alternative_reason or 'Normalmente deja mas puntos criticos abiertos antes de presentar'}."
        )
    if followup_question:
        sections.append(
            f"{_pick_conversational_variant(conversation_state=conversation_state, key='strategy_followup', options=('Para cerrar esta estrategia sin dejar cabos sueltos, necesito confirmar:', 'El dato que me falta para terminar de cerrarla bien es este:'))} {followup_question}"
        )
    return [item for item in sections if item.strip()]


def _render_execution_sections(
    *,
    pipeline_payload: dict[str, Any],
    execution_output: dict[str, Any],
    strategy_mode: str,
    language_profile: dict[str, Any],
    strategy_composition_profile: dict[str, Any],
    followup_question: str,
) -> list[str]:
    execution_data = dict(execution_output.get("execution_output") or {})
    actions = [_truncate_text(item) for item in _dedupe_texts(list(execution_data.get("what_to_do_now") or []))[:3]]
    where_to_go = [_truncate_text(item) for item in _dedupe_texts(list(execution_data.get("where_to_go") or []))[:3]]
    requests = [_truncate_text(item) for item in _dedupe_texts(list(execution_data.get("what_to_request") or []))[:2]]
    documents = [_truncate_text(item) for item in _dedupe_texts(list(execution_data.get("documents_needed") or []))[:2]]

    if not actions:
        case_strategy = dict(pipeline_payload.get("case_strategy") or {})
        actions = [_truncate_text(item) for item in _dedupe_texts(list(case_strategy.get("recommended_actions") or []))[:3]]

    sections: list[str] = []
    if strategy_mode in {"action_first", "guide_next_step"}:
        sections.append(
            f"{str(language_profile.get('selected_bridge') or 'Para avanzar de forma concreta, podes hacer esto:')}\n"
            + "\n".join(f"{index}. {item}" for index, item in enumerate(actions[:3], start=1))
        )
        if where_to_go:
            sections.append("Donde ir:\n" + "\n".join(f"- {item}" for item in where_to_go[:2]))
        if documents:
            sections.append("Que presentar:\n" + "\n".join(f"- {item}" for item in documents[:2]))
        if requests and strategy_mode == "action_first":
            sections.append("Que pedir:\n" + "\n".join(f"- {item}" for item in requests[:2]))
        if followup_question and bool(strategy_composition_profile.get("allow_followup")):
            sections.append(f"{str(language_profile.get('selected_followup_intro') or 'Si queres afinar el paso siguiente, necesito este dato:')} {followup_question}")
        else:
            # action_first sin follow-up: composition cierra, postprocessor no debe agregar cierre
            closing = str(language_profile.get("selected_closing") or "").strip()
            if closing and strategy_mode == "action_first":
                sections.append(closing)
        return [item for item in sections if item.strip()]

    if strategy_mode in {"orient_with_prudence", "close_without_more_questions"}:
        sections.append(
            f"{str(language_profile.get('selected_bridge') or 'Para avanzar de forma concreta, podes hacer esto:')}\n"
            + "\n".join(f"{index}. {item}" for index, item in enumerate(actions[:2], start=1))
        )
        if where_to_go:
            sections.append("Donde ir:\n" + "\n".join(f"- {item}" for item in where_to_go[:2]))
        if documents:
            sections.append("Que presentar:\n" + "\n".join(f"- {item}" for item in documents[:2]))
        # close_without_more_questions en ejecucion también cierra desde composition
        if strategy_mode == "close_without_more_questions":
            closing = str(language_profile.get("selected_closing") or "").strip()
            if closing:
                sections.append(closing)
        return [item for item in sections if item.strip()]

    legal_referral_note = str(language_profile.get("selected_legal_referral_note") or "").strip()
    sections.append(
        "Para avanzar de forma concreta, podes hacer esto:\n"
        + "\n".join(f"{index}. {item}" for index, item in enumerate(actions[:3], start=1))
    )
    if where_to_go:
        sections.append("Donde ir:\n" + "\n".join(f"- {item}" for item in where_to_go[:3]))
    if documents:
        sections.append("Que presentar:\n" + "\n".join(f"- {item}" for item in documents[:3]))
    if requests:
        sections.append("Que pedir:\n" + "\n".join(f"- {item}" for item in requests[:2]))
    if legal_referral_note and "abogado" not in str(pipeline_payload.get("facts") or "").lower():
        sections.append(legal_referral_note)
    if followup_question:
        sections.append(f"Para ajustar el paso siguiente, necesito este dato: {followup_question}")
    return [item for item in sections if item.strip()]


# ── Utility functions (module-level, importables) ────────────────────────────

def _pick_conversational_variant(
    *,
    conversation_state: dict[str, Any],
    key: str,
    options: tuple[str, ...],
) -> str:
    if not options:
        return ""
    if len(options) == 1:
        return options[0]

    turn_count = int(conversation_state.get("turn_count") or 0)
    memory = dict(conversation_state.get("conversation_memory") or {})
    if not memory and turn_count <= 2:
        return options[0]

    seed = (
        turn_count
        + len(key)
        + len(str(memory.get("last_turn_type") or ""))
        + len(str(memory.get("last_dialogue_action") or ""))
    )
    return options[seed % len(options)]


def _select_known_case_facts(conversation_state: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in list(conversation_state.get("known_facts") or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = item.get("value")
        rendered = _render_known_fact(key=key, value=value)
        if rendered:
            result.append(rendered)
    return _dedupe_texts(result)


def _select_missing_case_facts(conversation_state: dict[str, Any]) -> list[str]:
    critical: list[str] = []
    ordinary: list[str] = []
    for item in list(conversation_state.get("missing_facts") or []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("key") or "").strip()
        priority = str(item.get("priority") or "").strip().lower()
        importance = str(item.get("importance") or "").strip().lower()
        purpose = str(item.get("purpose") or "").strip().lower()
        if not label:
            continue
        if priority in {"critical", "high", "required"} or importance == "core" or purpose in {"identify", "enable"}:
            critical.append(label)
        else:
            ordinary.append(label)
    return _dedupe_texts([*critical, *ordinary])


def _resolve_point_key(dialogue_policy: dict[str, Any], conversation_state: dict[str, Any]) -> str:
    dominant = str(dialogue_policy.get("dominant_missing_key") or "").strip().replace("_", " ")
    if dominant:
        return dominant
    missing = _select_missing_case_facts(conversation_state)
    return missing[0] if missing else ""


def _render_known_fact(*, key: str, value: Any) -> str:
    clean_key = str(key or "").strip().replace("_", " ")
    clean_value = str(value or "").strip()
    if key == "hay_hijos":
        return "Hay hijos involucrados." if str(value).lower() not in {"false", "0", "no"} else "No aparecen hijos involucrados."
    if key == "rol_procesal" and clean_value:
        return f"El rol procesal informado es {clean_value}."
    if key == "ingresos_otro_progenitor" and clean_value:
        return "Ya hay un dato inicial sobre los ingresos del otro progenitor."
    if clean_value:
        return f"{clean_key.capitalize()}: {clean_value}."
    return ""


def _strip_known_quick_start(text: str) -> str:
    value = str(text or "").strip()
    prefix = "Primer paso recomendado:"
    if value.lower().startswith(prefix.lower()):
        return value[len(prefix):].strip(" .:")
    return value


def _truncate_text(text: str, max_chars: int = 180) -> str:
    value = _normalize_whitespace(text)
    if len(value) <= max_chars:
        return value
    truncated = value[: max_chars + 1]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    truncated = truncated.rstrip(" ,.;:")
    return f"{truncated}..." if truncated else value[:max_chars].rstrip() + "..."


def _dedupe_texts(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        normalized = _normalize_dedupe_text(value)
        if not value or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _normalize_dedupe_text(value: str) -> str:
    normalized = re.sub(r"[^\w\s]", "", str(value or "")).strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    words: list[str] = []
    for word in normalized.split():
        if len(word) > 4 and word.endswith("es"):
            words.append(word[:-2])
        elif len(word) > 3 and word.endswith("s"):
            words.append(word[:-1])
        else:
            words.append(word)
    return " ".join(words)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())
