# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\execution_output_service.py
from __future__ import annotations

import re
import unicodedata
from typing import Any


MAX_ACTIONS = 4
MAX_DOCS = 3
MAX_WHERE = 2
MAX_REQUESTS = 3
MAX_MISSING = 2
DIVORCIO_MODALIDAD_QUESTION = "¿El divorcio sería unilateral o de común acuerdo?"
DIVORCIO_CESE_QUESTION = "¿Ya hubo cese de convivencia?"
DIVORCIO_COMPETENCIA_QUESTION = "¿Cuál es el domicilio que hoy resulta relevante para definir la competencia?"
DIVORCIO_EFECTOS_QUESTION = "¿Hay hijos, bienes o convenio que deban ordenarse desde el inicio?"
ALIMENTOS_CONVIVENCIA_QUESTION = "¿El niño o niña vive con quien consulta?"
ALIMENTOS_APORTE_QUESTION = "¿El otro progenitor está aportando algo actualmente?"
ALIMENTOS_INGRESOS_QUESTION = "¿Tenés algún dato sobre ingresos o gastos relevantes?"
ALIMENTOS_PRUEBA_QUESTION = "¿Ya tenés documentación o prueba básica para respaldar el reclamo?"


def build_execution_output(
    *,
    conversation_state: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
    conversational_intelligence: dict[str, Any] | None,
    pipeline_payload: dict[str, Any] | None,
    response_text: str,
    intent_resolution: dict[str, Any] | None,
) -> dict[str, Any]:
    state = _as_dict(conversation_state)
    policy = dict(dialogue_policy or {})
    intelligence = dict(conversational_intelligence or {})
    payload = _as_dict(pipeline_payload)
    intent = dict(intent_resolution or {})
    del intelligence

    intent_type = _clean_text(intent.get("intent_type")) or "general_information"
    urgency = _clean_text(intent.get("urgency")) or "low"
    should_activate = _should_activate(intent_type=intent_type, urgency=urgency)
    has_confirmed_children = _has_confirmed_children(conversation_state=state, pipeline_payload=payload)

    action_texts = _collect_action_texts(payload)
    translated_actions = _dedupe_strs(
        _translate_action_text(
            text,
            case_domain=_resolve_case_domain(payload),
            has_confirmed_children=has_confirmed_children,
        )
        for text in action_texts
    )
    documents_needed = _dedupe_strs(
        _translate_document_text(text)
        for text in _collect_document_texts(payload)
    )[:MAX_DOCS]
    where_to_go = _dedupe_strs(
        _translate_where_text(text, case_domain=_resolve_case_domain(payload))
        for text in _collect_where_texts(payload)
    )[:MAX_WHERE]
    what_to_request = _dedupe_strs(
        _translate_request_text(text)
        for text in _collect_request_texts(payload)
    )[:MAX_REQUESTS]
    what_is_still_missing = _dedupe_strs(
        _clean_text(item)
        for item in _collect_missing_texts(state=state, payload=payload)
    )[:MAX_MISSING]
    followup_question = _resolve_followup_question(
        payload=payload,
        dialogue_policy=policy,
        conversation_state=state,
    )
    enough_basis = _has_enough_basis(
        translated_actions=translated_actions,
        documents_needed=documents_needed,
        where_to_go=where_to_go,
        what_to_request=what_to_request,
    )
    applies = should_activate and enough_basis
    policy_patch = _resolve_policy_patch(
        conversation_state=state,
        dialogue_policy=policy,
        applies=applies,
        urgency=urgency,
    )

    execution_output = {
        "what_to_do_now": translated_actions[:MAX_ACTIONS],
        "how_to_start": translated_actions[:2],
        "documents_needed": documents_needed,
        "where_to_go": where_to_go,
        "what_to_request": what_to_request,
        "what_is_still_missing": what_is_still_missing,
        "followup_question": followup_question,
    }

    rendered_response_text = response_text
    if applies:
        rendered_response_text = _render_execution_response(
            execution_output=execution_output,
            base_response_text=response_text,
            intent_type=intent_type,
            urgency=urgency,
            case_domain=_resolve_case_domain(payload),
        )

    return {
        "intent_type": intent_type,
        "urgency": urgency,
        "applies": applies,
        "enough_basis": enough_basis,
        "execution_output": execution_output,
        "policy_patch": policy_patch,
        "rendered_response_text": rendered_response_text,
    }


def _should_activate(*, intent_type: str, urgency: str) -> bool:
    return intent_type in {"action_now", "process_guidance", "document_guidance"} or urgency == "high"


def _has_enough_basis(
    *,
    translated_actions: list[str],
    documents_needed: list[str],
    where_to_go: list[str],
    what_to_request: list[str],
) -> bool:
    if len(translated_actions) >= 3:
        return True
    if len(translated_actions) >= 2 and any((documents_needed, where_to_go, what_to_request)):
        return True
    if len(translated_actions) >= 1 and len(documents_needed) >= 2:
        return True
    return False


def _resolve_policy_patch(
    *,
    conversation_state: dict[str, Any],
    dialogue_policy: dict[str, Any],
    applies: bool,
    urgency: str,
) -> dict[str, Any]:
    if not applies:
        return {}
    legally_blocked = _is_legally_blocked(conversation_state, dialogue_policy)
    current_action = _clean_text(dialogue_policy.get("action")).lower()
    patch: dict[str, Any] = {
        "should_ask_first": False,
        "should_offer_partial_guidance": True,
        "guidance_strength": "high" if urgency == "high" and not legally_blocked else "medium",
    }
    if current_action == "ask" and not legally_blocked:
        patch["action"] = "hybrid"
    return patch


def _is_legally_blocked(conversation_state: dict[str, Any], dialogue_policy: dict[str, Any]) -> bool:
    progress = _as_dict(conversation_state.get("progress_signals"))
    if bool(progress.get("blocking_missing")):
        return True
    purpose = _clean_text(dialogue_policy.get("dominant_missing_purpose")).lower()
    importance = _clean_text(dialogue_policy.get("dominant_missing_importance")).lower()
    return importance == "core" and purpose in {"identify", "enable"}


def _collect_action_texts(payload: dict[str, Any]) -> list[str]:
    case_strategy = _as_dict(payload.get("case_strategy"))
    procedural_strategy = _as_dict(payload.get("procedural_strategy"))
    output_modes = _as_dict(payload.get("output_modes"))
    user_mode = _as_dict(output_modes.get("user"))
    quick_start = _strip_known_prefix(_clean_text(payload.get("quick_start")), "Primer paso recomendado:")
    return [
        quick_start,
        *_as_str_list(user_mode.get("next_steps")),
        *_as_str_list(case_strategy.get("recommended_actions")),
        *_as_str_list(procedural_strategy.get("next_steps")),
        *_as_str_list(case_strategy.get("procedural_focus")),
    ]


def _collect_document_texts(payload: dict[str, Any]) -> list[str]:
    case_strategy = _as_dict(payload.get("case_strategy"))
    procedural_strategy = _as_dict(payload.get("procedural_strategy"))
    output_modes = _as_dict(payload.get("output_modes"))
    user_mode = _as_dict(output_modes.get("user"))
    docs: list[str] = []
    docs.extend(item for item in _as_str_list(user_mode.get("missing_information")) if _looks_document_related(item))
    docs.extend(item for item in _as_str_list(procedural_strategy.get("missing_information") or procedural_strategy.get("missing_info")) if _looks_document_related(item))
    docs.extend(item for item in _as_str_list(case_strategy.get("ordinary_missing_information")) if _looks_document_related(item))
    docs.extend(item for item in _as_str_list(case_strategy.get("critical_missing_information")) if _looks_document_related(item))
    docs.extend(item for item in _collect_action_texts(payload) if _looks_document_related(item))
    return docs


def _collect_where_texts(payload: dict[str, Any]) -> list[str]:
    texts = [
        *_collect_action_texts(payload),
        *_as_str_list(_as_dict(payload.get("reasoning")).values()),
    ]
    return [text for text in texts if _looks_where_related(text)]


def _collect_request_texts(payload: dict[str, Any]) -> list[str]:
    texts = [
        *_collect_action_texts(payload),
        *_as_str_list(_as_dict(payload.get("reasoning")).values()),
        *_as_str_list(_as_dict(payload.get("normative_reasoning")).get("key_points")),
    ]
    return [text for text in texts if _looks_request_related(text)]


def _collect_missing_texts(*, state: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    missing_facts = _as_list(state.get("missing_facts"))
    missing = [_clean_text(item.get("label") or item.get("key")) for item in missing_facts if isinstance(item, dict)]
    if missing:
        return missing
    case_strategy = _as_dict(payload.get("case_strategy"))
    return [
        *_as_str_list(case_strategy.get("critical_missing_information")),
        *_as_str_list(case_strategy.get("ordinary_missing_information")),
    ]


def _resolve_followup_question(
    *,
    payload: dict[str, Any],
    dialogue_policy: dict[str, Any],
    conversation_state: dict[str, Any],
) -> str:
    conversational = _as_dict(payload.get("conversational"))
    available_question = _clean_text(conversational.get("question"))
    action = _clean_text(dialogue_policy.get("action")).lower()
    if action not in {"ask", "hybrid"}:
        return ""

    case_domain = _resolve_case_domain(payload)
    known_facts = _collect_known_facts(conversation_state, payload)
    priorities = _resolve_followup_priorities(case_domain=case_domain, known_facts=known_facts)
    if available_question and _question_matches_top_priority(available_question, priorities):
        return available_question
    if priorities:
        return priorities[0]
    return available_question


def _render_execution_response(
    *,
    execution_output: dict[str, Any],
    base_response_text: str,
    intent_type: str,
    urgency: str,
    case_domain: str,
) -> str:
    sections: list[str] = []
    actions = execution_output.get("what_to_do_now") or []
    docs = execution_output.get("documents_needed") or []
    where_to_go = execution_output.get("where_to_go") or []
    requests = execution_output.get("what_to_request") or []
    missing = execution_output.get("what_is_still_missing") or []
    followup = _clean_text(execution_output.get("followup_question"))

    if actions:
        sections.append(_resolve_executive_heading(intent_type=intent_type, urgency=urgency, case_domain=case_domain) + ":\n" + "\n".join(f"- {item}" for item in actions))
    if docs:
        sections.append("Que preparar o llevar:\n" + "\n".join(f"- {item}" for item in docs))
    if where_to_go:
        sections.append("Donde hacerlo:\n" + "\n".join(f"- {item}" for item in where_to_go))
    if requests:
        sections.append("Que podes pedir ya:\n" + "\n".join(f"- {item}" for item in requests))
    if missing:
        sections.append("Que todavia conviene precisar:\n" + "\n".join(f"- {item}" for item in missing))
    elif base_response_text:
        sections.append(base_response_text)
    if followup:
        sections.append(f"Para afinar el paso siguiente, necesito un dato: {followup}")
    return "\n\n".join(section for section in sections if section.strip()).strip()


def _translate_action_text(text: str, *, case_domain: str, has_confirmed_children: bool) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    if any(token in normalized for token in ("presentacion inicial", "escrito inicial", "iniciar divorcio", "promover divorcio", "presentar demanda")):
        if case_domain == "divorcio":
            if has_confirmed_children:
                return "Preparar y presentar el escrito inicial de divorcio con los datos del matrimonio y con los puntos vinculados a hijos que deban ordenarse desde el comienzo."
            return "Preparar y presentar el escrito inicial de divorcio con los datos del matrimonio y, si hay hijos, con los puntos que deban ordenarse desde el comienzo."
        return "Preparar y presentar el escrito inicial ante el organismo o juzgado competente."
    if any(token in normalized for token in ("encuadre y competencia", "competencia", "juzgado competente", "ultimo domicilio conyugal")):
        return "Definir el juzgado competente segun domicilio relevante o ultimo domicilio conyugal."
    if any(token in normalized for token in ("propuesta reguladora", "convenio regulador", "convenio")):
        return "Preparar la propuesta reguladora o el convenio con los puntos que deban quedar ordenados desde el inicio."
    if any(token in normalized for token in ("alimentos provisorios", "cuota provisoria", "pedir cuota provisoria")):
        return "Pedir cuota provisoria en la presentacion inicial si la urgencia alimentaria ya aparece sustentada."
    if any(token in normalized for token in ("prueba documental", "documental basica", "reunir prueba", "documentacion basica")):
        return "Reunir la documentacion y prueba basica que el propio caso ya marca como necesaria."
    if any(token in normalized for token in ("notificacion", "notificar")):
        return "Preparar los datos necesarios para notificar correctamente a la otra parte."
    return _sentence_case(_clean_text(text))


def _translate_document_text(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    if any(token in normalized for token in ("documental", "documentacion", "documentacion basica", "prueba documental")):
        return "Documentacion basica y prueba documental vinculada al caso."
    if "propuesta reguladora" in normalized or "convenio" in normalized:
        return "Propuesta reguladora o convenio con el nivel de detalle que el caso requiera."
    if any(token in normalized for token in ("ingresos", "recibos", "comprobantes")):
        return "Constancias o comprobantes sobre ingresos y gastos relevantes."
    return _sentence_case(_clean_text(text))


def _translate_where_text(text: str, *, case_domain: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    if any(token in normalized for token in ("juzgado", "competencia", "domicilio")):
        if case_domain in {"divorcio", "alimentos"}:
            return _resolve_competence_phrase(case_domain=case_domain)
        return "Organismo o juzgado competente segun el tipo de tramite."
    return _sentence_case(_clean_text(text))


def _translate_request_text(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    if any(token in normalized for token in ("cuota provisoria", "alimentos provisorios")):
        return "Cuota provisoria o alimentos provisorios si la necesidad actual ya puede sostenerse."
    if "propuesta reguladora" in normalized:
        return "Homologacion o tratamiento inicial de la propuesta reguladora si corresponde."
    if any(token in normalized for token in ("medidas", "urgencia")):
        return "La medida inicial que el propio caso justifique segun la urgencia descrita."
    return ""


def _looks_document_related(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(token in normalized for token in ("document", "prueba", "comprobante", "recibo", "partida", "dni", "convenio"))


def _looks_where_related(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(token in normalized for token in ("juzgado", "competencia", "domicilio", "organismo", "donde"))


def _looks_request_related(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(token in normalized for token in ("pedir", "solicitar", "cuota provisoria", "alimentos provisorios", "medidas"))


def _resolve_case_domain(payload: dict[str, Any]) -> str:
    return _clean_text(
        _as_dict(payload.get("case_profile")).get("case_domain")
        or payload.get("case_domain")
    ).lower()


def _resolve_executive_heading(*, intent_type: str, urgency: str, case_domain: str) -> str:
    if intent_type == "action_now" and urgency == "high":
        if case_domain == "divorcio":
            return "Que podes hacer hoy o manana para empezar tu divorcio"
        if case_domain == "alimentos":
            return "Que podes hacer hoy o manana para iniciar el reclamo"
        return "Que podes hacer hoy o manana"
    return "Que podes hacer ahora"


def _resolve_competence_phrase(*, case_domain: str) -> str:
    if case_domain in {"divorcio", "alimentos"}:
        return "Juzgado de familia que resulte competente segun tu jurisdiccion y el domicilio relevante para la competencia."
    return "Organismo o juzgado competente segun tu jurisdiccion y el domicilio que resulte relevante."


def _has_confirmed_children(*, conversation_state: dict[str, Any], pipeline_payload: dict[str, Any]) -> bool:
    known_facts = _collect_known_facts(conversation_state, pipeline_payload)
    value = str(known_facts.get("hay_hijos") or "").strip().casefold()
    return value in {"true", "1", "si", "sí", "yes"}


def _collect_known_facts(conversation_state: dict[str, Any], pipeline_payload: dict[str, Any]) -> dict[str, Any]:
    facts = dict(_as_dict(pipeline_payload.get("facts")))
    for item in _as_list(conversation_state.get("known_facts")):
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key") or item.get("fact_key"))
        value = item.get("value")
        if key:
            facts[key] = value
    return facts


def _resolve_followup_priorities(*, case_domain: str, known_facts: dict[str, Any]) -> list[str]:
    normalized_domain = _clean_text(case_domain).lower()
    if normalized_domain == "divorcio":
        priorities: list[str] = []
        modalidad = _normalize_text(known_facts.get("divorcio_modalidad"))
        hay_acuerdo = _normalize_text(known_facts.get("hay_acuerdo"))
        cese = _normalize_text(known_facts.get("cese_convivencia"))
        domicilio = _normalize_text(known_facts.get("domicilio_relevante") or known_facts.get("ultimo_domicilio_conyugal"))
        if modalidad not in {"unilateral", "comun_acuerdo", "mutuo_acuerdo", "conjunto"} and hay_acuerdo not in {"true", "false", "1", "0", "si", "sí", "no"}:
            priorities.append(DIVORCIO_MODALIDAD_QUESTION)
        if cese not in {"true", "1", "si", "sí"}:
            priorities.append(DIVORCIO_CESE_QUESTION)
        if not domicilio:
            priorities.append(DIVORCIO_COMPETENCIA_QUESTION)
        priorities.append(DIVORCIO_EFECTOS_QUESTION)
        return priorities
    if normalized_domain == "alimentos":
        priorities: list[str] = []
        convivencia = _normalize_text(known_facts.get("convivencia") or known_facts.get("nino_convive_con_consultante"))
        aporte = _normalize_text(known_facts.get("aporte_actual") or known_facts.get("aporta_actualmente"))
        ingresos = _normalize_text(known_facts.get("ingresos_otro_progenitor"))
        prueba = _normalize_text(known_facts.get("prueba_basica") or known_facts.get("documentacion_basica"))
        if not convivencia:
            priorities.append(ALIMENTOS_CONVIVENCIA_QUESTION)
        if aporte not in {"true", "false", "1", "0", "si", "sí", "no"}:
            priorities.append(ALIMENTOS_APORTE_QUESTION)
        if not ingresos:
            priorities.append(ALIMENTOS_INGRESOS_QUESTION)
        if not prueba:
            priorities.append(ALIMENTOS_PRUEBA_QUESTION)
        return priorities
    return []


def _question_matches_top_priority(question: str, priorities: list[str]) -> bool:
    if not priorities:
        return False
    normalized_question = _normalize_text(question)
    candidate_tokens = set(_normalize_text(priorities[0]).split())
    question_tokens = set(normalized_question.split())
    return len(candidate_tokens.intersection(question_tokens)) >= max(2, min(4, len(candidate_tokens)))


def _strip_known_prefix(text: str, prefix: str) -> str:
    if text.casefold().startswith(prefix.casefold()):
        return text[len(prefix):].strip(" :.-")
    return text


def _dedupe_strs(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = _clean_text(value)
        if not clean:
            continue
        normalized = _normalize_text(clean)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(clean)
    return result


def _sentence_case(text: str) -> str:
    clean = _clean_text(text)
    if not clean:
        return ""
    return clean[0].upper() + clean[1:]


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
    if isinstance(value, dict):
        return [_clean_text(item) for item in value.values() if _clean_text(item)]
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]
