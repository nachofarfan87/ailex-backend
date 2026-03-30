from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.services.conversational import build_conversation_memory, build_conversational_response
from app.services.conversational.conversational_quality import (
    apply_conversational_style,
    build_contextual_opening,
    simplify_question_text,
)


_USER_TERM_RULES = (
    {
        "patterns": (r"\blegitimacion activa\b", r"\blegitimacion\b"),
        "replacement": "si la persona esta habilitada para pedir esto",
        "context": "user_only",
    },
    {
        "patterns": (r"\bcompetencia\b",),
        "replacement": "que juzgado corresponde",
        "context": "user_only",
    },
    {
        "patterns": (r"\bvia procesal\b",),
        "replacement": "como conviene iniciar el tramite",
        "context": "user_only",
    },
    {
        "patterns": (r"\bpropuesta reguladora\b", r"\bconvenio regulador\b"),
        "replacement": "acuerdo o propuesta sobre vivienda, bienes, hijos y alimentos",
        "context": "user_only",
    },
    {
        "patterns": (r"\bpersoneria\b",),
        "replacement": "la representacion formal de la parte",
        "context": "user_only",
    },
)

_USER_TEXT_BLOCK_PATTERNS = (
    r"\bincompetencia\b",
    r"\bcompetencia federal\b",
    r"\bcompetencia originaria\b",
)

_DECISIVE_MISSING_PATTERNS = (
    "definir la via procesal aplicable",
    "precisar competencia judicial",
    "acreditar legitimacion",
    "acreditar legitimacion y personeria",
    "falta acreditar matrimonio",
    "falta acreditar vinculo",
)

_DECISIVE_QUESTION_PATTERNS = (
    "tramitarse unilateralmente",
    "mutuo acuerdo",
    "presentacion conjunta",
    "ultimo domicilio conyugal",
    "domicilio actual del otro conyuge",
    "propuesta reguladora",
    "juzgado competente",
    "legitimacion",
)

# ---------------------------------------------------------------------------
# Question relevance scoring
# ---------------------------------------------------------------------------
# Each rule: (score, [patterns]).  Patterns are matched against the
# normalised (lowercased, collapsed-whitespace) text of the candidate.
# A candidate accumulates points from every matching tier — the highest
# total wins.  Tiers are ordered by strategic impact.

_QUESTION_SCORE_RULES: tuple[tuple[int, tuple[str, ...]], ...] = (
    # --- TIER 1 — structural / determinative (10-9) ---
    (10, (
        r"conjunto.*unilateral|unilateral.*conjunto",
        r"de acuerdo.*unilateral|unilateral.*acuerdo",
        r"mutuo acuerdo|presentacion conjunta",
        r"tipo de (proceso|tramite|divorcio|juicio)",
        r"contencioso|incidental|voluntario",
        r"variante procesal",
    )),
    (9, (
        r"\bhijos?\b.*menor|menor.*\bhijos?\b",
        r"hijos en comun|hijos menores|existencia de hijos",
        r"regimen de (comunicacion|visitas|cuidado)",
        r"responsabilidad parental",
    )),
    (9, (
        r"\bactor\b|\bdemandado\b|rol procesal",
        r"quien (inicia|promueve|demanda)",
        r"legitimacion (activa|pasiva)",
    )),
    (9, (
        r"urgencia|medida cautelar|peligro en la demora",
        r"tutela anticipada|proteccion (urgente|inmediata)",
        r"violencia|restriccion",
    )),
    (8, (
        r"competencia|juzgado|jurisdiccion",
        r"domicilio conyugal|ultimo domicilio",
        r"fuero|radicacion",
    )),
    # --- TIER 2 — important context (7-5) ---
    (7, (
        r"bienes|vivienda|patrimonio|inmueble",
        r"compensacion economica",
        r"propuesta reguladora|convenio regulador",
        r"sociedad conyugal|regimen patrimonial",
    )),
    (7, (
        r"alimentos|cuota alimentaria|obligacion alimentaria",
        r"pension|manutencion",
    )),
    (6, (
        r"prueba|documental|testimonial|pericial",
        r"acreditar|documentacion",
    )),
    (5, (
        r"hechos|circunstancias|contexto",
        r"antecedentes|situacion actual",
    )),
    # --- TIER 3 — accessory (3-1) ---
    (3, (
        r"costas|honorarios|regulacion de honorarios",
        r"notificacion|traslado|cedula",
    )),
    (1, (
        r"plazo|termino",
        r"formato|modelo|escrito",
    )),
)

_CASE_COMPLETENESS_RULES: dict[str, dict[str, Any]] = {
    "divorcio": {
        "critical_any": (
            ("divorcio_modalidad", "hay_acuerdo"),
        ),
        "critical_all": ("hay_hijos",),
        "optional": ("cese_convivencia", "hay_bienes"),
    },
    "alimentos": {
        "critical_all": ("rol_procesal", "hay_hijos"),
        "critical_any": (
            ("situacion_economica", "urgencia", "hay_ingresos"),
        ),
        "optional": ("hay_bienes", "vivienda_familiar"),
    },
    "cuidado_personal": {
        "critical_all": ("hay_hijos",),
        "critical_any": (
            ("rol_procesal",),
            ("hay_acuerdo",),
        ),
        "optional": ("urgencia", "cese_convivencia"),
    },
}

_DOMAIN_FIELD_PRIORITIES: dict[str, dict[str, float]] = {
    "divorcio": {
        "divorcio_modalidad": 1.0,
        "hay_hijos": 0.9,
        "hay_acuerdo": 0.85,
        "cese_convivencia": 0.6,
        "hay_bienes": 0.5,
        "vivienda_familiar": 0.45,
    },
    "alimentos": {
        "rol_procesal": 1.0,
        "hay_hijos": 0.95,
        "situacion_economica": 0.85,
        "hay_ingresos": 0.85,
        "urgencia": 0.8,
        "hay_bienes": 0.45,
        "vivienda_familiar": 0.4,
    },
    "cuidado_personal": {
        "hay_hijos": 1.0,
        "rol_procesal": 0.9,
        "hay_acuerdo": 0.85,
        "urgencia": 0.75,
        "cese_convivencia": 0.55,
    },
}

_FIELD_PRIORITY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("divorcio_modalidad", (
        "unilateral",
        "conjunto",
        "mutuo acuerdo",
        "comun acuerdo",
        "común acuerdo",
        "variante procesal",
        "presentacion conjunta",
    )),
    ("hay_hijos", (
        "hijos",
        "menores",
        "responsabilidad parental",
        "cuidado personal",
        "regimen de comunicacion",
        "régimen de comunicación",
    )),
    ("hay_acuerdo", (
        "hay acuerdo",
        "de acuerdo",
        "acuerdo",
    )),
    ("rol_procesal", (
        "actor",
        "demandado",
        "rol procesal",
        "quien inicia",
        "quien promueve",
        "quien demanda",
    )),
    ("urgencia", (
        "urgencia",
        "cautelar",
        "peligro en la demora",
        "tutela anticipada",
        "proteccion urgente",
    )),
    ("situacion_economica", (
        "situacion economica",
        "situación económica",
        "capacidad economica",
        "capacidad económica",
    )),
    ("hay_ingresos", (
        "ingresos",
        "recursos",
        "salario",
        "trabajo",
    )),
    ("cese_convivencia", (
        "cese de convivencia",
        "convivencia",
        "separados",
    )),
    ("hay_bienes", (
        "bienes",
        "patrimonio",
        "compensacion economica",
        "compensación económica",
    )),
    ("vivienda_familiar", (
        "vivienda",
        "hogar conyugal",
        "casa",
        "inmueble",
    )),
)

_FIELD_PRIORITY_WEIGHT_FACTOR = 4.0

# ---------------------------------------------------------------------------
# Human-friendly question templates per field
# ---------------------------------------------------------------------------
# Used by _fact_to_question when converting a missing-fact slug into a
# real, short, user-facing question.  One question per field — the system
# picks the highest-priority missing field and emits only this one.

_FIELD_TO_HUMAN_QUESTION: dict[str, str] = {
    "divorcio_modalidad": "¿El divorcio seria de comun acuerdo o unilateral?",
    "hay_hijos": "¿Hay hijos menores o con capacidad restringida?",
    "hay_acuerdo": "¿Hay acuerdo entre las partes?",
    "rol_procesal": "¿Consultas como madre, padre, o profesional de una de las partes?",
    "urgencia": "¿Necesitas resolver esto con urgencia?",
    "situacion_economica": "¿Cual es la situacion economica actual de cada parte?",
    "hay_ingresos": "¿El otro progenitor tiene ingresos identificables?",
    "cese_convivencia": "¿Ya dejaron de convivir?",
    "hay_bienes": "¿Hay bienes relevantes (inmuebles, vehiculos, ahorros)?",
    "vivienda_familiar": "¿Hay una vivienda familiar en juego?",
}

# Keyword → field mapping used to convert free-text missing facts into a
# known field, so we can use the human question template above.
_MISSING_TEXT_TO_FIELD: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("divorcio_modalidad", ("unilateral", "conjunto", "mutuo acuerdo", "comun acuerdo", "variante procesal", "presentacion conjunta", "tipo de divorcio")),
    ("hay_hijos", ("hijos", "menores", "responsabilidad parental", "cuidado personal", "regimen de comunicacion")),
    ("hay_acuerdo", ("hay acuerdo", "acuerdo entre",)),
    ("rol_procesal", ("actor", "demandado", "rol procesal", "quien inicia", "quien promueve", "quien demanda")),
    ("urgencia", ("urgencia", "cautelar", "peligro en la demora", "tutela anticipada", "proteccion urgente")),
    ("situacion_economica", ("situacion economica", "capacidad economica",)),
    ("hay_ingresos", ("ingresos", "recursos economicos", "salario",)),
    ("cese_convivencia", ("cese de convivencia", "convivencia", "separados",)),
    ("hay_bienes", ("bienes", "patrimonio", "compensacion economica", "vivienda familiar", "inmueble",)),
    ("vivienda_familiar", ("vivienda", "hogar conyugal", "casa",)),
)

# ---------------------------------------------------------------------------
# Query-based fact inference patterns
# ---------------------------------------------------------------------------
# Detects facts already present in the raw query text so that progress %
# reflects information the user already supplied even before clarification
# flow kicks in.

_QUERY_FACT_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # (field_name, value_if_matched, (patterns...))
    ("hay_hijos", "inferred", (
        r"\bhij[oa]s?\b", r"\bmenor(es)?\b", r"\bnene\b", r"\bnena\b",
        r"\bnino\b", r"\bnina\b", r"\bniño\b", r"\bniña\b",
        r"\bchic[oa]s?\b",
    )),
    ("hay_hijos_edad", "inferred", (
        r"\b\d{1,2}\s*(años|meses|dias)\b",
    )),
    ("tema_alimentos", "inferred", (
        r"\balimento", r"\bcuota alimentaria\b", r"\bmanutencion\b",
        r"\bpension alimentaria\b",
    )),
    ("tema_divorcio", "inferred", (
        r"\bdivorcio\b", r"\bdivorci",
    )),
    ("tema_cuidado", "inferred", (
        r"\bcuidado personal\b", r"\btenencia\b", r"\bguarda\b",
        r"\bregimen de (comunicacion|visitas)\b",
    )),
    ("vinculo_parental", "inferred", (
        r"\bpadre\b", r"\bmadre\b", r"\bprogenitor", r"\bpapa\b", r"\bmama\b",
        r"\babuel[oa]\b",
    )),
    ("urgencia", "inferred", (
        r"\burgente\b", r"\burgencia\b", r"\bcautelar\b",
        r"\bproteccion\s+urgente\b",
    )),
    ("hay_bienes", "inferred", (
        r"\bcasa\b", r"\bdepartamento\b", r"\bauto\b", r"\bvehiculo\b",
        r"\binmueble\b", r"\bbienes\b",
    )),
)


def infer_facts_from_query(query: str) -> dict[str, Any]:
    """Extract implicit facts from the raw user query text.

    Returns a dict of field→value for every pattern that matches.
    These are *inferred* facts — not confirmed — but useful to bump
    the progress bar above 0 % when the user already mentioned data.
    """
    normalized = _normalize_text(query)
    if not normalized:
        return {}
    facts: dict[str, Any] = {}
    for field, value, patterns in _QUERY_FACT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, normalized):
                facts[field] = value
                break
    return facts


def build_dual_output(response: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(response or {})
    # Run conversation-memory-aware path FIRST so its resolved_slots
    # can override the generic question selector in _build_conversational.
    conversational_response = build_conversational_response(payload)
    conversational = _build_conversational(payload)
    if conversational_response:
        payload["conversational_response"] = conversational_response
        _sync_with_conversation_memory(conversational, conversational_response, payload)
    payload["conversational"] = conversational
    payload["output_modes"] = {
        "user": _build_user_output(payload, conversational),
        "professional": _build_professional_output(payload),
    }
    return payload


_ALIMENTOS_SLOT_QUESTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "aportes_actuales": ("aportando algo actualmente", "aporta", "cumple con la cuota", "paga alimentos"),
    "convivencia": ("vive con vos", "convive", "hijos menores", "hay hijos", "capacidad restringida"),
    "notificacion": ("ubicar al otro progenitor", "domicilio", "notificar", "dato util para"),
    "ingresos": ("ingresos", "actividad laboral", "trabaja"),
    "urgencia": ("necesidad urgente", "urgencia"),
    "antecedentes": ("reclamo", "acuerdo", "intimacion"),
}


def _sync_with_conversation_memory(
    conversational: dict[str, Any],
    conversational_response: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Override Path A's question with the conversation-memory-aware selection from Path B.

    Path B (build_conversational_response / question_selector) tracks resolved_slots
    and knows which alimentos questions have already been answered.  Path A
    (_build_conversational / _select_primary_question) does not.  This function
    bridges the gap so the user never sees a repeated question.
    """
    conv_memory = _as_dict(conversational_response.get("conversation_memory"))
    memory_question = conversational_response.get("primary_question")  # str | None
    resolved_slots = set(_as_str_list(conv_memory.get("resolved_slots")))

    # Merge conversation_memory known_facts into conversational for frontend progress.
    memory_known_facts = _as_dict(conv_memory.get("known_facts"))
    memory_inferred = _as_dict(conv_memory.get("inferred_facts"))
    if memory_known_facts or memory_inferred:
        existing_known = _as_dict(conversational.get("known_facts"))
        # Inferred go first so explicit known_facts override them.
        existing_known.update(memory_inferred)
        existing_known.update(memory_known_facts)
        conversational["known_facts"] = {
            k: v for k, v in existing_known.items() if v not in (None, "", [], {})
        }

    # Extract slot key and memory for the conversational quality layer.
    question_selection = _as_dict(conversational_response.get("question_selection"))
    selected_info = _as_dict(question_selection.get("selected"))
    slot_key = str(selected_info.get("key") or "")

    if memory_question is not None:
        # Memory-aware path selected a question — use it if different from Path A's.
        current_q_norm = _normalize_text(conversational.get("question") or "")
        memory_q_norm = _normalize_text(memory_question)
        if current_q_norm != memory_q_norm:
            conversational["question"] = memory_question
            if conversational.get("should_ask_first") and memory_question:
                guided = _build_guided_response(
                    memory_question,
                    payload,
                    slot_key=slot_key,
                    conversation_memory=conv_memory,
                )
                if guided:
                    # Preserve existing memory phrase (e.g. "actuas como demandado")
                    memory_phrase = _build_memory_phrase(conversational.get("known_facts") or {})
                    if memory_phrase:
                        guided = f"{memory_phrase} {guided}".strip()
                    conversational["guided_response"] = guided
                    conversational["message"] = guided
    elif resolved_slots:
        # Memory-aware path has no more questions — clear stale Path A question.
        current_q = _clean_text(conversational.get("question"))
        if current_q and _question_targets_resolved_slot(current_q, resolved_slots):
            conversational["question"] = None
            if conversational.get("should_ask_first"):
                conversational["should_ask_first"] = False
            conversational["guided_response"] = None


def _question_targets_resolved_slot(question: str, resolved_slots: set[str]) -> bool:
    """Return True if *question* is about a slot that was already resolved."""
    normalized_q = _normalize_text(question)
    for slot, patterns in _ALIMENTOS_SLOT_QUESTION_PATTERNS.items():
        if slot in resolved_slots and any(p in normalized_q for p in patterns):
            return True
    return False


def explain_confidence(response: dict[str, Any], mode: str) -> str:
    confidence = _safe_float(response.get("confidence"))
    case_strategy = _as_dict(response.get("case_strategy"))
    critical_missing = _as_str_list(case_strategy.get("critical_missing_information"))
    ordinary_missing = _as_str_list(case_strategy.get("ordinary_missing_information"))
    blocking_factor = str(
        _as_dict(response.get("procedural_case_state")).get(
            "blocking_factor",
            _as_dict(response.get("legal_decision")).get("blocking_factor", "none"),
        )
        or "none"
    ).strip().lower()

    if mode == "user":
        if blocking_factor not in {"", "none"} or critical_missing:
            return "Hay una orientacion util, pero todavia faltan datos importantes para confirmar con seguridad como avanzar."
        if (confidence or 0.0) >= 0.6:
            return "Hay una base suficiente para orientarte, aunque todavia faltan algunos datos para definir detalles del tramite."
        if ordinary_missing:
            return "La orientacion sirve para empezar y el encuadre principal aparece claro, aunque conviene completar algunos datos para ajustar mejor el tramite."
        return "La orientacion disponible alcanza para darte un primer mapa claro de como avanzar."

    if blocking_factor not in {"", "none"} or critical_missing:
        return "La estrategia base requiere validacion adicional porque persisten faltantes criticos o bloqueos procesales relevantes."
    if ordinary_missing:
        return "El encuadre principal aparece suficientemente determinado, con faltantes ordinarios de cierre procesal y patrimonial que no impiden orientar la estrategia base."
    return "El encuadre principal aparece suficientemente determinado y la estrategia base puede sostenerse con la informacion disponible."


def _build_user_output(response: dict[str, Any], conversational: dict[str, Any]) -> dict[str, Any]:
    case_domain = _clean_text(response.get("case_domain"))
    case_strategy = _as_dict(response.get("case_strategy"))
    quick_start = _clean_text(response.get("quick_start"))
    summary_source = _first_nonempty_text(
        _as_dict(response.get("reasoning")).get("short_answer"),
        case_strategy.get("strategic_narrative"),
        response.get("response_text"),
    )
    what_this_means_source = _first_nonempty_text(
        case_strategy.get("strategic_narrative"),
        summary_source,
        quick_start,
    )
    next_steps = _to_user_list(case_strategy.get("recommended_actions") or [])
    if not next_steps and quick_start:
        next_steps = [_strip_known_prefix(quick_start, "Primer paso recomendado:")]

    key_risks = _to_user_list(case_strategy.get("risk_analysis") or [])
    missing_information = _to_user_list(
        case_strategy.get("ordinary_missing_information")
        or case_strategy.get("missing_information")
        or case_strategy.get("critical_missing_information")
        or []
    )

    summary = _to_user_text(summary_source) or _default_user_summary(case_domain, quick_start)
    what_this_means = _to_user_text(what_this_means_source) or summary

    if conversational.get("should_ask_first"):
        decisive_question = _clean_text(conversational.get("question"))
        guided_response = _clean_text(conversational.get("guided_response"))
        return {
            "title": _question_first_title(case_domain),
            "summary": guided_response or summary,
            "quick_start": "",
            "what_this_means": guided_response or what_this_means,
            "next_steps": [decisive_question] if decisive_question else [],
            "key_risks": [],
            "missing_information": _dedupe_strs(_to_user_list(conversational.get("missing_facts") or []))[:2],
            "confidence_explained": "Con ese dato se puede orientar la estrategia con mucha mas precision y evitar una respuesta sobredesarrollada demasiado pronto.",
        }

    return {
        "title": _user_title(case_domain, quick_start),
        "summary": summary,
        "quick_start": quick_start,
        "what_this_means": what_this_means,
        "next_steps": _dedupe_strs(next_steps)[:5],
        "key_risks": _dedupe_strs(key_risks)[:5],
        "missing_information": _dedupe_strs(missing_information)[:5],
        "confidence_explained": explain_confidence(response, mode="user"),
    }


def _build_professional_output(response: dict[str, Any]) -> dict[str, Any]:
    case_domain = _clean_text(response.get("case_domain"))
    case_strategy = _as_dict(response.get("case_strategy"))
    normative_focus = _build_normative_focus(_as_dict(response.get("normative_reasoning")))
    summary = _professional_summary(response)
    return {
        "title": _professional_title(case_domain),
        "summary": summary,
        "strategic_narrative": _clean_text(case_strategy.get("strategic_narrative")),
        "conflict_summary": _dedupe_strs(_as_str_list(case_strategy.get("conflict_summary"))),
        "recommended_actions": _dedupe_strs(_as_str_list(case_strategy.get("recommended_actions"))),
        "risk_analysis": _dedupe_strs(_as_str_list(case_strategy.get("risk_analysis"))),
        "procedural_focus": _dedupe_strs(_as_str_list(case_strategy.get("procedural_focus"))),
        "critical_missing_information": _dedupe_strs(_as_str_list(case_strategy.get("critical_missing_information"))),
        "ordinary_missing_information": _dedupe_strs(_as_str_list(case_strategy.get("ordinary_missing_information"))),
        "normative_focus": normative_focus,
        "confidence_explained": explain_confidence(response, mode="professional"),
    }


def _build_conversational(response: dict[str, Any]) -> dict[str, Any]:
    case_strategy = _as_dict(response.get("case_strategy"))
    reasoning = _as_dict(response.get("reasoning"))
    procedural_strategy = _as_dict(response.get("procedural_strategy"))
    case_domain = _clean_text(response.get("case_domain"))
    metadata = _as_dict(response.get("metadata"))
    clarification_context = _as_dict(metadata.get("clarification_context"))
    conversation_memory = build_conversation_memory(response)
    known_facts = _collect_known_facts(response)
    completeness = evaluate_case_completeness(known_facts, case_domain)

    message = _to_user_text(
        _first_nonempty_text(
            reasoning.get("short_answer"),
            case_strategy.get("strategic_narrative"),
            response.get("quick_start"),
            response.get("response_text"),
        )
    )
    if not message:
        message = _default_user_summary(case_domain, _clean_text(response.get("quick_start")))
    memory_phrase = _build_memory_phrase(known_facts)
    if memory_phrase:
        message = f"{memory_phrase} {message}".strip()

    critical_missing = _filter_unresolved_items(
        _dedupe_strs(_as_str_list(case_strategy.get("critical_missing_information"))),
        known_facts=known_facts,
        case_domain=case_domain,
    )
    ordinary_missing = _filter_unresolved_items(
        _dedupe_strs(_as_str_list(case_strategy.get("ordinary_missing_information"))),
        known_facts=known_facts,
        case_domain=case_domain,
    )
    procedural_missing = _dedupe_strs(
        _as_str_list(procedural_strategy.get("missing_information") or procedural_strategy.get("missing_info"))
    )
    procedural_missing = _filter_unresolved_items(
        procedural_missing,
        known_facts=known_facts,
        case_domain=case_domain,
    )
    missing_facts = _dedupe_strs([*critical_missing, *ordinary_missing, *procedural_missing])[:3]
    recommended = _as_str_list(case_strategy.get("recommended_actions"))

    question_candidates = _filter_question_candidates(
        _extract_question_candidates(response),
        known_facts=known_facts,
        case_domain=case_domain,
    )
    selected_question = _select_primary_question(response, critical_missing, ordinary_missing, question_candidates)
    if _question_is_stale_after_clarification(
        selected_question,
        clarification_context=clarification_context,
        known_facts=known_facts,
        question_candidates=question_candidates,
    ):
        alternative_candidates = [
            candidate
            for candidate in question_candidates
            if _normalize_text(candidate.get("question")) != _normalize_text(selected_question or "")
        ]
        selected_question = _select_primary_question(
            response,
            critical_missing,
            ordinary_missing,
            alternative_candidates,
        )
        if _question_is_stale_after_clarification(
            selected_question,
            clarification_context=clarification_context,
            known_facts=known_facts,
            question_candidates=alternative_candidates,
        ):
            selected_question = None
    question_slot_key = _infer_question_slot_key(selected_question, question_candidates)

    precision_prompt = _clean_text(clarification_context.get("precision_prompt"))
    precision_required = bool(clarification_context.get("precision_required")) and bool(precision_prompt)
    if precision_required:
        selected_question = _clean_question(precision_prompt)
        should_ask_first = True
        guided_response = f"{memory_phrase} {precision_prompt}".strip() if memory_phrase else precision_prompt
    else:
        should_ask_first = _should_ask_first(
            response,
            critical_missing,
            question_candidates,
            selected_question,
            completeness=completeness,
        )
        guided_response = (
            _build_guided_response(
                selected_question,
                response,
                slot_key=question_slot_key,
                conversation_memory=conversation_memory,
            )
            if should_ask_first
            else None
        )
        if memory_phrase and guided_response:
            guided_response = f"{memory_phrase} {guided_response}".strip()
    if not should_ask_first and _should_close_clarification(
        response,
        critical_missing=critical_missing,
        completeness=completeness,
    ):
        message = _build_closure_message(message)

    options: list[str] = []
    if 2 <= len(recommended) <= 3 and all(len(item) < 120 for item in recommended):
        options = [_to_user_text(item) for item in recommended]

    quick_start_raw = _clean_text(response.get("quick_start"))
    next_step_source = _first_nonempty_text(
        _strip_known_prefix(quick_start_raw, "Primer paso recomendado:") if quick_start_raw else "",
        recommended[0] if recommended else "",
        _as_str_list(procedural_strategy.get("next_steps"))[0] if _as_str_list(procedural_strategy.get("next_steps")) else "",
    )
    # Defensive: ensure next_step is always a plain string, never an object.
    raw_next_step = _to_user_text(next_step_source) if next_step_source else None
    if isinstance(raw_next_step, dict):
        next_step = _clean_text(
            raw_next_step.get("description")
            or raw_next_step.get("action")
            or raw_next_step.get("title")
            or raw_next_step.get("text")
        )
    else:
        next_step = _clean_text(raw_next_step) if raw_next_step else None

    return {
        "message": guided_response or message,
        "question": selected_question,
        "options": options,
        "missing_facts": [_to_user_text(item) for item in missing_facts][:3],
        "next_step": None if should_ask_first else next_step,
        "should_ask_first": should_ask_first,
        "guided_response": guided_response,
        "known_facts": known_facts,
        "clarification_status": _clean_text(clarification_context.get("answer_status")) or "none",
        "asked_questions": _dedupe_strs(
            [
                *_as_str_list(clarification_context.get("asked_questions")),
                _clean_text(clarification_context.get("last_question")),
            ]
        ),
        "case_completeness": completeness,
        "conversation_memory": conversation_memory,
    }


def _build_memory_phrase(known_facts: dict[str, Any]) -> str:
    facts = _as_dict(known_facts)
    if not facts:
        return ""

    prioritized_fields = (
        "divorcio_modalidad",
        "hay_hijos",
        "hay_acuerdo",
        "rol_procesal",
        "urgencia",
        "hay_bienes",
        "situacion_economica",
    )
    snippets: list[str] = []
    for field in prioritized_fields:
        snippet = _fact_to_memory_snippet(field, facts.get(field))
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= 3:
            break

    if not snippets:
        return ""

    lead = _memory_lead(snippets[0], facts)
    return f"{lead}{_join_memory_snippets(snippets)}."


def _fact_to_memory_snippet(field: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return ""

    if field == "divorcio_modalidad":
        modalidad = _clean_text(value).casefold()
        if modalidad in {"unilateral", "conjunto"}:
            return f"divorcio {modalidad}"
        return ""
    if field == "hay_hijos":
        return "con hijos" if bool(value) else "sin hijos"
    if field == "hay_acuerdo":
        return "con acuerdo" if bool(value) else "sin acuerdo"
    if field == "rol_procesal":
        rol = _clean_text(value)
        return f"actuas como {rol}" if rol else ""
    if field == "urgencia":
        return "hay urgencia" if bool(value) else ""
    if field == "hay_bienes":
        return "hay bienes" if bool(value) else "no aparecen bienes relevantes"
    if field == "situacion_economica":
        descripcion = _clean_text(value)
        return f"hay un dato economico relevante: {descripcion}" if descripcion else ""
    return ""


def _memory_lead(first_snippet: str, facts: dict[str, Any]) -> str:
    if first_snippet.startswith("divorcio "):
        return "Perfecto. Entonces estamos frente a un "
    if "rol_procesal" in facts:
        return "Bien. Entonces veo que "
    return "Perfecto. Entonces "


def _join_memory_snippets(snippets: list[str]) -> str:
    if not snippets:
        return ""
    if len(snippets) == 1:
        return snippets[0]
    if len(snippets) == 2:
        return f"{snippets[0]} y {snippets[1]}"
    return f"{snippets[0]}, {snippets[1]} y {snippets[2]}"


def _extract_question_candidates(response: dict[str, Any]) -> list[dict[str, str]]:
    question_engine = _as_dict(response.get("question_engine_result"))
    raw_items = question_engine.get("questions") or []
    candidates: list[dict[str, str]] = []

    for item in raw_items:
        if isinstance(item, dict):
            question = _clean_text(item.get("question"))
            purpose = _clean_text(item.get("purpose"))
            priority = _clean_text(item.get("priority"))
            category = _clean_text(item.get("category"))
        else:
            question = _clean_text(item)
            purpose = ""
            priority = ""
            category = ""
        if not question:
            continue
        candidates.append(
            {
                "question": question,
                "purpose": purpose,
                "priority": priority,
                "category": category,
            }
        )

    if candidates:
        return candidates

    for question in _as_str_list(question_engine.get("critical_questions")):
        candidates.append(
            {
                "question": question,
                "purpose": "",
                "priority": "alta",
                "category": "",
            }
        )
    return candidates


def _score_candidate_text(text: str) -> int:
    """Score a question/fact text by matching against _QUESTION_SCORE_RULES.

    Accumulates points from every matching tier.  Higher = more strategically
    relevant.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return 0
    total = 0
    for score, patterns in _QUESTION_SCORE_RULES:
        for pattern in patterns:
            if re.search(pattern, normalized):
                total += score
                break  # one match per tier is enough
    return total


def _select_primary_question(
    response: dict[str, Any],
    critical_missing: list[str],
    ordinary_missing: list[str],
    question_candidates: list[dict[str, str]],
) -> str | None:
    """Select the most strategically relevant question across all sources.

    Pools candidates from:
      1. question_engine_result questions (structured)
      2. critical_missing_information
      3. ordinary_missing_information

    Each candidate is scored.  Ties are broken by:
      a. explicit priority == "alta" gets +3 bonus
      b. shorter text wins (clearer, less ambiguous)

    Falls back to positional [0] only when scoring produces a tie at 0.
    """
    case_domain = _clean_text(response.get("case_domain"))
    # Build a unified pool: (display_text, raw_score, source_priority, original_text)
    pool: list[tuple[str, float, int, str]] = []

    # Source 1: question_engine candidates
    for candidate in question_candidates:
        text = _clean_text(candidate.get("question"))
        if not text:
            continue
        score = _score_candidate_text(text)
        priority_bonus = 3 if str(candidate.get("priority") or "").strip().lower() == "alta" else 0
        priority_bonus += _priority_score_bonus(
            case_domain=case_domain,
            text=text,
            category=_clean_text(candidate.get("category")),
        )
        pool.append((text, score + priority_bonus, 0, text))

    # Source 2: critical_missing (implicit high priority)
    for fact in critical_missing:
        text = _clean_text(fact)
        if not text:
            continue
        score = _score_candidate_text(text)
        score += 2
        score += _priority_score_bonus(case_domain=case_domain, text=text)
        pool.append((text, score, 1, fact))  # +2 for being critical

    # Source 3: ordinary_missing
    for fact in ordinary_missing:
        text = _clean_text(fact)
        if not text:
            continue
        score = _score_candidate_text(text)
        score += _priority_score_bonus(case_domain=case_domain, text=text)
        pool.append((text, score, 2, fact))

    if not pool:
        return None

    # Sort: highest score first, then shortest text (tiebreaker)
    pool.sort(key=lambda item: (-item[1], len(item[0])))

    best_text, _best_score, source_idx, original = pool[0]

    # Source 0 = question_engine → already a question, just clean it
    if source_idx == 0:
        return _clean_question(best_text)

    # Source 1/2 = missing fact → convert to question
    return _fact_to_question(original)


def _infer_question_slot_key(
    selected_question: str | None,
    question_candidates: list[dict[str, str]],
) -> str:
    question_text = _clean_text(selected_question)
    if not question_text:
        return ""

    normalized_selected = _normalize_text(question_text)
    for candidate in question_candidates:
        candidate_question = _clean_text(candidate.get("question"))
        if _normalize_text(candidate_question) != normalized_selected:
            continue
        inferred = _infer_priority_field(
            text=candidate_question,
            category=_clean_text(candidate.get("category")),
        )
        if inferred:
            return inferred

    return _infer_priority_field(text=question_text, category="")


def _question_is_stale_after_clarification(
    selected_question: str | None,
    *,
    clarification_context: dict[str, Any],
    known_facts: dict[str, Any],
    question_candidates: list[dict[str, str]],
) -> bool:
    question_text = _clean_text(selected_question)
    if not question_text:
        return False

    normalized_question = _normalize_text(question_text)
    normalized_last_question = _normalize_text(clarification_context.get("last_question") or "")
    answer_status = _clean_text(clarification_context.get("answer_status")).casefold()
    clarified_fields = {
        _clean_text(item)
        for item in _as_str_list(clarification_context.get("clarified_fields"))
        if _clean_text(item)
    }
    inferred_field = _infer_question_slot_key(question_text, question_candidates)

    if answer_status == "precise" and normalized_last_question and normalized_question == normalized_last_question:
        return True
    if inferred_field and inferred_field in clarified_fields:
        return True
    if inferred_field and _has_meaningful_fact(known_facts, inferred_field):
        return True
    return False


def _should_ask_first(
    response: dict[str, Any],
    critical_missing: list[str],
    question_candidates: list[dict[str, str]],
    selected_question: str | None,
    *,
    completeness: dict[str, Any] | None = None,
) -> bool:
    if not selected_question:
        return False

    completeness = completeness or evaluate_case_completeness(
        _collect_known_facts(response),
        _clean_text(response.get("case_domain")),
    )
    if completeness.get("is_complete"):
        return False

    if critical_missing:
        return True

    normalized_question = _clean_text(selected_question).casefold()
    if _looks_detailed_enough(response):
        return False

    if any(pattern in normalized_question for pattern in _DECISIVE_QUESTION_PATTERNS):
        return True

    if any(pattern in _normalize_text(" ".join(critical_missing)) for pattern in _DECISIVE_MISSING_PATTERNS):
        return True

    high_priority_questions = [
        item
        for item in question_candidates
        if str(item.get("priority") or "").strip().lower() == "alta"
    ]
    return bool(high_priority_questions)


def _should_close_clarification(
    response: dict[str, Any],
    *,
    critical_missing: list[str],
    completeness: dict[str, Any] | None = None,
) -> bool:
    if critical_missing:
        return False

    metadata = _as_dict(response.get("metadata"))
    clarification_context = _as_dict(metadata.get("clarification_context"))
    if not clarification_context:
        return False

    completeness = completeness or evaluate_case_completeness(
        _collect_known_facts(response),
        _clean_text(response.get("case_domain")),
    )
    if completeness.get("is_complete"):
        return True

    return _looks_detailed_enough(response)


def _build_closure_message(message: str) -> str:
    base_message = _clean_text(message)
    closure_lead = "Con esto ya tengo una base clara para orientarte."
    if not base_message:
        return closure_lead
    if base_message.casefold().startswith(closure_lead.casefold()):
        return base_message
    return f"{closure_lead} {base_message}"


def _priority_score_bonus(
    *,
    case_domain: str,
    text: str,
    category: str | None = None,
) -> float:
    inferred_field = _infer_priority_field(text=text, category=category)
    if not inferred_field:
        return 0.0
    return round(get_field_priority(case_domain, inferred_field) * _FIELD_PRIORITY_WEIGHT_FACTOR, 4)


def _infer_priority_field(*, text: str, category: str | None = None) -> str | None:
    normalized_category = _normalize_text(category or "")
    normalized_text = _normalize_text(text)
    for field, patterns in _FIELD_PRIORITY_PATTERNS:
        if normalized_category and any(pattern in normalized_category for pattern in patterns):
            return field
        if any(pattern in normalized_text for pattern in patterns):
            return field
    return None


def _looks_detailed_enough(response: dict[str, Any]) -> bool:
    query = _clean_text(response.get("query"))
    facts = _collect_known_facts(response)
    case_strategy = _as_dict(response.get("case_strategy"))
    case_domain = _clean_text(response.get("case_domain")).casefold()
    completeness = evaluate_case_completeness(facts, case_domain)

    token_count = len([token for token in re.split(r"\W+", query) if token])
    detailed_facts = len([value for value in facts.values() if value not in (None, "", [], {})]) >= 2
    has_children_detail = any(
        term in _normalize_text(query) for term in ("hijos", "bienes", "vivienda", "alimentos", "compensacion")
    )
    ordinary_missing = len(_as_str_list(case_strategy.get("ordinary_missing_information")))

    if completeness.get("is_complete"):
        return True
    if detailed_facts:
        return True
    if token_count >= 14:
        return True
    if case_domain == "divorcio" and has_children_detail and ordinary_missing <= 2:
        return True
    return False


def evaluate_case_completeness(facts: dict[str, Any] | None, domain: str | None) -> dict[str, Any]:
    normalized_domain = _clean_text(domain).casefold()
    rules = _CASE_COMPLETENESS_RULES.get(normalized_domain)
    known_facts = {
        key: value
        for key, value in _as_dict(facts).items()
        if value not in (None, "", [], {})
    }

    # Count how many *useful* pieces of information we already have,
    # including inferred meta-fields like tema_alimentos, hay_hijos_edad, etc.
    useful_fact_count = len(known_facts)

    if not rules:
        confidence_level = "high" if useful_fact_count >= 3 else "medium" if useful_fact_count >= 2 else "low"
        return {
            "is_complete": useful_fact_count >= 2,
            "missing_critical": [],
            "missing_optional": [],
            "confidence_level": confidence_level,
            "known_count": useful_fact_count,
        }

    missing_critical: list[str] = []
    missing_optional: list[str] = []

    for field in rules.get("critical_all", ()):
        if not _has_meaningful_fact(known_facts, field):
            missing_critical.append(field)

    for alternative_group in rules.get("critical_any", ()):
        if not any(_has_meaningful_fact(known_facts, field) for field in alternative_group):
            missing_critical.append("/".join(alternative_group))

    for field in rules.get("optional", ()):
        if not _has_meaningful_fact(known_facts, field):
            missing_optional.append(field)

    is_complete = not missing_critical
    if is_complete and not missing_optional:
        confidence_level = "high"
    elif is_complete:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    return {
        "is_complete": is_complete,
        "missing_critical": missing_critical,
        "missing_optional": missing_optional,
        "confidence_level": confidence_level,
        "known_count": useful_fact_count,
    }


def get_field_priority(domain: str | None, field: str | None) -> float:
    normalized_domain = _clean_text(domain).casefold()
    normalized_field = _clean_text(field)
    if not normalized_domain or not normalized_field:
        return 0.0
    return float(_DOMAIN_FIELD_PRIORITIES.get(normalized_domain, {}).get(normalized_field, 0.0) or 0.0)


def _collect_known_facts(response: dict[str, Any]) -> dict[str, Any]:
    metadata = _as_dict(response.get("metadata"))
    clarification_context = _as_dict(metadata.get("clarification_context"))
    # Start with facts inferred from the raw query text so that the
    # progress bar is never 0 % when the user already mentioned data.
    query_text = _clean_text(
        response.get("query")
        or clarification_context.get("base_query")
        or ""
    )
    inferred = infer_facts_from_query(query_text)
    # Explicit facts always override inferred ones.
    known_facts = _merge_dicts(
        inferred,
        _merge_dicts(
            _as_dict(clarification_context.get("known_facts")),
            _as_dict(response.get("facts")),
        ),
    )
    return {key: value for key, value in known_facts.items() if value not in (None, "", [], {})}


def _filter_question_candidates(
    candidates: list[dict[str, str]],
    *,
    known_facts: dict[str, Any],
    case_domain: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for candidate in candidates:
        question = _clean_text(candidate.get("question"))
        if not question:
            continue
        inferred_field = _infer_priority_field(
            text=question,
            category=_clean_text(candidate.get("category")),
        )
        if inferred_field and _has_meaningful_fact(known_facts, inferred_field):
            continue
        if _item_is_resolved(question, known_facts=known_facts, case_domain=case_domain):
            continue
        result.append(candidate)
    return result


def _filter_unresolved_items(
    items: list[str],
    *,
    known_facts: dict[str, Any],
    case_domain: str,
) -> list[str]:
    return [
        item
        for item in items
        if not _item_is_resolved(item, known_facts=known_facts, case_domain=case_domain)
    ]


def _item_is_resolved(
    text: str,
    *,
    known_facts: dict[str, Any],
    case_domain: str,
) -> bool:
    normalized = _normalize_text(text)
    if not normalized or not known_facts:
        return False

    if any(term in normalized for term in ("unilateral", "conjunto", "acuerdo")):
        modalidad = _clean_text(known_facts.get("divorcio_modalidad")).casefold()
        if modalidad in {"unilateral", "conjunto"}:
            return True
        if "hay_acuerdo" in known_facts and "acuerdo" in normalized and "unilateral" not in normalized:
            return True

    if "hijos" in normalized and "hay_hijos" in known_facts:
        return True

    if any(term in normalized for term in ("actor", "demandado", "rol procesal")) and _clean_text(known_facts.get("rol_procesal")):
        return True

    if "urgencia" in normalized and "urgencia" in known_facts:
        return True

    if any(term in normalized for term in ("bienes", "vivienda", "patrimonial")) and "hay_bienes" in known_facts:
        return True

    if "convivencia" in normalized and "cese_convivencia" in known_facts:
        return True

    if case_domain.casefold() == "divorcio" and "propuesta reguladora" in normalized and known_facts.get("hay_acuerdo") is True:
        return False

    # --- Alimentos-specific resolution ---
    if any(term in normalized for term in ("aporta", "paga", "cumple", "cuota")) and (
        "aportes_actuales" in known_facts or "cumplimiento_alimentos" in known_facts
    ):
        return True

    if any(term in normalized for term in ("convive", "vive con", "cuidado personal", "a cargo")) and (
        "convivencia" in known_facts or "convivencia_hijo" in known_facts
    ):
        return True

    if any(term in normalized for term in ("notificar", "ubicar", "domicilio", "localizar")) and (
        "notificacion" in known_facts or "domicilio_otro_progenitor" in known_facts
    ):
        return True

    if any(term in normalized for term in ("ingresos", "actividad laboral", "sueldo", "salario")) and (
        "ingresos" in known_facts or "ingresos_otro_progenitor" in known_facts
    ):
        return True

    if any(term in normalized for term in ("reclamo previo", "acuerdo previo", "mediacion", "intimacion")) and (
        "antecedentes" in known_facts or "reclamo_previo" in known_facts
    ):
        return True

    # Match "hijos menores" / "hay hijos" when hay_hijos is in known_facts (any domain)
    if any(term in normalized for term in ("menor", "menores", "hija", "hijo", "bebe", "nena", "nene")) and "hay_hijos" in known_facts:
        return True

    return False


def _build_guided_response(
    question: str | None,
    response: dict[str, Any],
    *,
    slot_key: str = "",
    conversation_memory: dict[str, Any] | None = None,
) -> str | None:
    if not question:
        return None

    question_candidates = _extract_question_candidates(response)
    selected_candidate = question_candidates[0] if question_candidates else {}
    purpose = _clean_text(selected_candidate.get("purpose"))
    inferred_slot = slot_key or _infer_question_slot_key(question, question_candidates)
    styled = apply_conversational_style(
        question,
        conversation_memory,
        slot_key=inferred_slot,
        include_opening=True,
    )
    reason = _purpose_to_reason(purpose, response)
    if reason:
        return f"{styled} Esto es importante porque {reason}."
    return styled

    # --- Conversational Quality Layer (Fase 5.5) ---
    # When we have slot_key / conversation_memory, use the new quality layer
    # for varied openings and simplified questions.
    if slot_key or conversation_memory:
        styled = apply_conversational_style(
            question,
            conversation_memory,
            slot_key=slot_key,
            include_opening=True,
        )
        reason = _purpose_to_reason(purpose, response)
        if reason:
            return f"{styled} Esto es importante porque {reason}."
        return styled

    # --- Legacy path (non-alimentos domains without memory context) ---
    clean_q = _clean_text(question)
    if clean_q.startswith("¿") or clean_q.endswith("?"):
        reason = _purpose_to_reason(purpose, response)
        if reason:
            return f"Para orientarte bien, necesito un dato clave: {clean_q} Esto es importante porque {reason}."
        return f"Para orientarte bien, necesito un dato clave: {clean_q}"

    # Legacy path: strip and wrap
    question_body = _strip_question_marks(question)
    question_body = re.sub(r"^necesito saber\s+", "", question_body, flags=re.IGNORECASE).strip()
    reason = _purpose_to_reason(purpose, response)
    if reason:
        return f"Para orientarte bien, primero necesito saber {question_body}, porque {reason}."
    return f"Para orientarte bien, primero necesito saber {question_body}."


def _purpose_to_reason(purpose: str, response: dict[str, Any]) -> str:
    lowered = _normalize_text(purpose)
    if not lowered:
        case_domain = _clean_text(response.get("case_domain")).casefold()
        if case_domain == "divorcio":
            return "eso cambia la estrategia y la presentacion inicial"
        return ""
    replacements = (
        ("definir la variante procesal del divorcio y evitar un encuadre incompleto", "eso cambia la estrategia y la presentacion inicial"),
        ("determinar competencia y eventuales necesidades de notificacion", "eso define el juzgado y la forma correcta de iniciar"),
        ("ordenar el contenido minimo exigible para la presentacion judicial", "sin ese dato la presentacion inicial puede quedar incompleta"),
        ("identificar si el divorcio involucra efectos parentales que deben ordenarse desde el inicio", "eso cambia lo que hay que regular desde el comienzo"),
    )
    for source, target in replacements:
        if source in lowered:
            return target
    return lowered


def _fact_to_question(fact: str) -> str:
    """Convert a missing-fact description into a short, human-friendly question.

    Strategy:
      1. If the text already ends with '?', return it as-is.
      2. Try to match the text to a known field and use the pre-written
         human question from _FIELD_TO_HUMAN_QUESTION.
      3. Fall back to a concise "¿…?" wrap.
    """
    text = _to_user_text(fact)
    if not text:
        return ""
    if text.rstrip().endswith("?"):
        return text

    # Try to map the free-text fact to a known field
    normalized = _normalize_text(text)
    for field, patterns in _MISSING_TEXT_TO_FIELD:
        for pattern in patterns:
            if pattern in normalized:
                human_q = _FIELD_TO_HUMAN_QUESTION.get(field)
                if human_q:
                    return human_q
                break

    # Fallback: strip verbs and wrap as question
    lowered = text.lower().rstrip(".")
    lowered = re.sub(
        r"^(definir|precisar|completar|verificar|confirmar|determinar|especificar)\s+",
        "",
        lowered,
    )
    lowered = re.sub(r"^si\s+", "", lowered)
    lowered = re.sub(r"^(la|el|los|las)\s+", "", lowered)
    if not lowered:
        return ""
    return f"¿{lowered[0].upper()}{lowered[1:]}?"


def _clean_question(question: str | None) -> str | None:
    text = _clean_text(question)
    if not text:
        return None
    return _strip_question_marks(_to_user_text(text))


def _strip_question_marks(text: str) -> str:
    value = _clean_text(text)
    value = value.lstrip("¿").rstrip("?").strip()
    if value:
        return value[:1].lower() + value[1:]
    return value


def _question_first_title(case_domain: str) -> str:
    if case_domain.casefold() == "divorcio":
        return "Dato clave para orientar tu divorcio"
    if case_domain:
        return f"Dato clave para orientar {_humanize_case_domain(case_domain)}"
    return "Dato clave para orientar el caso"


def _build_normative_focus(normative_reasoning: dict[str, Any]) -> list[str]:
    focus: list[str] = []
    for item in normative_reasoning.get("applied_rules") or []:
        if not isinstance(item, dict):
            continue
        source = _clean_text(item.get("source") or item.get("source_id"))
        article = _clean_text(item.get("article"))
        if source and article:
            focus.append(f"{source} art. {article}")
        elif source:
            focus.append(source)
    return _dedupe_strs(focus)[:5]


def _user_title(case_domain: str, quick_start: str) -> str:
    normalized = case_domain.casefold()
    if normalized == "divorcio":
        if quick_start:
            return "Que hacer primero en tu divorcio"
        return "Orientacion inicial para divorcio"
    if case_domain:
        return f"Orientacion inicial para {_humanize_case_domain(case_domain)}"
    if quick_start:
        return "Que hacer primero"
    return "Orientacion inicial del caso"


def _professional_title(case_domain: str) -> str:
    normalized = case_domain.casefold()
    if normalized == "divorcio":
        return "Estrategia inicial de divorcio"
    if case_domain:
        return f"Encuadre estrategico de {_humanize_case_domain(case_domain)}"
    return "Encuadre estrategico inicial"


def _professional_summary(response: dict[str, Any]) -> str:
    case_strategy = _as_dict(response.get("case_strategy"))
    legal_decision = _as_dict(response.get("legal_decision"))
    summary = _first_nonempty_text(
        _as_dict(response.get("reasoning")).get("short_answer"),
        case_strategy.get("strategic_narrative"),
        response.get("response_text"),
    )
    posture = _clean_text(case_strategy.get("strategy_mode") or legal_decision.get("strategic_posture"))
    if summary and posture:
        return f"{summary} Estrategia sugerida: {posture}."
    if summary:
        return summary
    return "No hay desarrollo estrategico suficiente para ampliar el analisis, pero el payload sigue siendo compatible."


def _to_user_list(items: Any) -> list[str]:
    result = [_to_user_text(str(item).strip()) for item in _as_str_list(items)]
    return [item for item in _dedupe_strs(result) if item]


def _to_user_text(text: str) -> str:
    result = _clean_text(text)
    if not result:
        return ""
    segments = _split_text_segments(result)
    normalized_segments: list[str] = []
    for segment in segments:
        rewritten = segment
        for rule in _USER_TERM_RULES:
            rewritten = _apply_user_rule(rewritten, rule)
        normalized_segments.append(rewritten)
    result = "".join(normalized_segments)
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"\s+([,.;:])", r"\1", result)
    result = re.sub(
        r"(?i)^definir la como conviene iniciar el tramite(?: aplicable)?\.?$",
        "Definir como conviene iniciar el tramite.",
        result,
    )
    return result


def _apply_user_rule(text: str, rule: dict[str, Any]) -> str:
    if str(rule.get("context") or "") != "user_only":
        return text
    result = text
    for pattern in rule.get("patterns") or ():
        if _should_skip_user_pattern(result, pattern):
            continue
        result = re.sub(pattern, str(rule.get("replacement") or ""), result, flags=re.IGNORECASE)
    return result


def _should_skip_user_pattern(text: str, pattern: str) -> bool:
    lowered = text.casefold()
    if any(re.search(block_pattern, lowered, flags=re.IGNORECASE) for block_pattern in _USER_TEXT_BLOCK_PATTERNS):
        if "competencia" in pattern:
            return True
    return False


def _split_text_segments(text: str) -> list[str]:
    parts = re.split(r"([.!?]\s*)", text)
    if len(parts) <= 1:
        return [text]
    segments: list[str] = []
    index = 0
    while index < len(parts):
        current = parts[index]
        trailing = parts[index + 1] if index + 1 < len(parts) else ""
        segments.append(f"{current}{trailing}")
        index += 2
    return segments


def _default_user_summary(case_domain: str, quick_start: str) -> str:
    if quick_start:
        return "Ya hay una orientacion inicial util para saber que hacer primero."
    if case_domain:
        return f"Se detecta una consulta vinculada con {_humanize_case_domain(case_domain)} y ya puede darse una orientacion inicial."
    return "Hay una orientacion inicial disponible aunque falten algunos bloques del analisis."


def _humanize_case_domain(case_domain: str) -> str:
    return _clean_text(case_domain).replace("_", " ")


def _strip_known_prefix(text: str, prefix: str) -> str:
    value = _clean_text(text)
    if not value:
        return ""
    lowered_value = value.casefold()
    lowered_prefix = prefix.casefold()
    if lowered_value.startswith(lowered_prefix):
        return value[len(prefix):].strip()
    return value


def _first_nonempty_text(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _dedupe_strs(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = _clean_text(item)
        normalized = value.casefold()
        if not value or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _has_meaningful_fact(facts: dict[str, Any], field: str) -> bool:
    if field not in facts:
        return False
    value = facts.get(field)
    if isinstance(value, str):
        return bool(_clean_text(value))
    return value not in (None, [], {})


def _merge_dicts(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
            continue
        merged[key] = value
    return merged


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
