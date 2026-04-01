# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\strategic_decision_service.py
from __future__ import annotations

import re
import unicodedata
from typing import Any


def resolve_strategic_decision(
    *,
    conversation_state: dict[str, Any] | None,
    pipeline_payload: dict[str, Any] | None,
    progression_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _as_dict(conversation_state)
    payload = _as_dict(pipeline_payload)
    progression = _as_dict(progression_policy)

    facts = _collect_case_facts(conversation_state=state, pipeline_payload=payload)
    query = _clean_text(payload.get("query"))
    action_slug = _clean_text(_as_dict(payload.get("classification")).get("action_slug")).lower()
    case_domain = _clean_text(
        _as_dict(payload.get("case_profile")).get("case_domain")
        or payload.get("case_domain")
    ).lower()
    topics = set(_as_str_list(progression.get("topics_covered")))

    has_children = _resolve_has_children(facts=facts, query=query, action_slug=action_slug)
    has_minor_children = _resolve_has_minor_children(facts=facts, query=query, has_children=has_children)
    clear_agreement = _resolve_clear_agreement(facts=facts, query=query)
    high_conflict = _resolve_high_conflict(facts=facts, query=query)
    no_current_support = _resolve_no_current_support(facts=facts, query=query)
    involves_divorce = case_domain == "divorcio" or "divorcio" in action_slug or "divorcio" in topics or "divorcio" in _normalize_text(query)
    involves_alimentos = case_domain == "alimentos" or "alimentos" in action_slug or "alimentos" in topics or "alimentos" in _normalize_text(query)

    decision = _build_default_decision(payload)

    if involves_divorce and involves_alimentos and has_minor_children and not clear_agreement:
        decision = {
            "recommended_path": "Iniciar divorcio unilateral con una presentacion completa y pedir alimentos provisorios en el mismo arranque.",
            "priority_action": "Preparar cuanto antes el escrito inicial con pedido alimentario urgente.",
            "justification": "Hay una necesidad alimentaria inmediata y esperar a cerrar un acuerdo claro suele demorar la cobertura del hijo o hija menor.",
            "alternative_path": "Intentar primero un acuerdo integral y presentar despues un divorcio de comun acuerdo con convenio completo.",
            "alternative_reason": "Solo suele ser mas conveniente si el acuerdo ya esta suficientemente avanzado y no posterga la cobertura alimentaria.",
            "decision_basis": ["hijo_menor", "sin_acuerdo_claro", "alimentos_urgentes"],
        }
    elif involves_alimentos and has_minor_children and (high_conflict or no_current_support):
        decision = {
            "recommended_path": "Iniciar de inmediato el reclamo principal de alimentos con pedido de cuota provisoria.",
            "priority_action": "Presentar el reclamo alimentario con la mejor base documental disponible.",
            "justification": "Cuando no hay aporte actual estable, suele convenir priorizar una cuota provisoria antes que esperar a reunir toda la prueba ideal.",
            "alternative_path": "Reunir primero mas prueba de ingresos y despues presentar un reclamo mas cerrado.",
            "alternative_reason": "Puede dar mas precision probatoria, pero normalmente demora la respuesta economica que el nino o nina necesita ahora.",
            "decision_basis": ["hijo_menor", "falta_aporte_actual" if no_current_support else "conflicto_alto"],
        }
    elif involves_divorce and clear_agreement:
        decision = {
            "recommended_path": "Ordenar un divorcio de comun acuerdo con propuesta reguladora o convenio suficientemente completo.",
            "priority_action": "Cerrar por escrito los puntos del acuerdo que deban homologarse desde el inicio.",
            "justification": "Si ya hay acuerdo real sobre los efectos principales, esta via suele reducir friccion y observaciones innecesarias.",
            "alternative_path": "Iniciar un divorcio unilateral y discutir despues los efectos que no quedaron cerrados.",
            "alternative_reason": "Sigue siendo viable, pero suele agregar desgaste si el acuerdo principal ya puede presentarse de forma ordenada.",
            "decision_basis": ["acuerdo_claro"],
        }
    elif involves_divorce and not clear_agreement:
        decision = {
            "recommended_path": "Preparar un divorcio unilateral con el mejor encuadre posible y dejar definidos desde el inicio los efectos urgentes.",
            "priority_action": "Cerrar modalidad, competencia y efectos inmediatos antes de presentar.",
            "justification": "Si no hay acuerdo claro, la via unilateral suele dar un camino mas estable para avanzar sin quedar atado a una negociacion incierta.",
            "alternative_path": "Seguir intentando un acuerdo previo antes de iniciar.",
            "alternative_reason": "Puede ahorrar conflicto si realmente esta maduro, pero suele ser menos conveniente cuando todavia faltan definiciones centrales.",
            "decision_basis": ["sin_acuerdo_claro"],
        }

    decision["case_domain"] = case_domain or ("divorcio" if involves_divorce else "alimentos" if involves_alimentos else "")
    decision["signals"] = {
        "has_children": has_children,
        "has_minor_children": has_minor_children,
        "clear_agreement": clear_agreement,
        "high_conflict": high_conflict,
        "no_current_support": no_current_support,
        "involves_divorce": involves_divorce,
        "involves_alimentos": involves_alimentos,
    }
    decision["confidence"] = _resolve_decision_confidence(decision_basis=_as_str_list(decision.get("decision_basis")))
    return decision


def _build_default_decision(payload: dict[str, Any]) -> dict[str, Any]:
    case_strategy = _as_dict(payload.get("case_strategy"))
    recommended_actions = _as_str_list(case_strategy.get("recommended_actions"))
    procedural_focus = _as_str_list(case_strategy.get("procedural_focus"))
    quick_start = _strip_quick_start(_clean_text(payload.get("quick_start")))
    primary = quick_start or (recommended_actions[0] if recommended_actions else "Ordenar primero el encuadre principal del caso antes de cerrar la estrategia.")
    secondary = recommended_actions[1] if len(recommended_actions) > 1 else "Avanzar con una variante mas abierta y ajustar despues los faltantes relevantes."
    practical_focus = procedural_focus[0] if procedural_focus else "todavia faltan definiciones que cambian el encuadre practico"
    return {
        "recommended_path": primary,
        "priority_action": primary,
        "justification": f"Suele ser el camino mas prudente porque permite avanzar sin perder control sobre {practical_focus}.",
        "alternative_path": secondary,
        "alternative_reason": "Puede servir, pero normalmente deja mas margen para observaciones o ajustes posteriores.",
        "decision_basis": ["payload_strategy"],
    }


def _collect_case_facts(*, conversation_state: dict[str, Any], pipeline_payload: dict[str, Any]) -> dict[str, Any]:
    facts = dict(_as_dict(pipeline_payload.get("facts")))
    case_profile = _as_dict(pipeline_payload.get("case_profile"))
    for key, value in case_profile.items():
        if key not in facts and value not in ({}, [], "", None):
            facts[key] = value
    for item in _as_list(conversation_state.get("known_facts")):
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key") or item.get("fact_key"))
        if key:
            facts[key] = item.get("value")
    return facts


def _resolve_has_children(*, facts: dict[str, Any], query: str, action_slug: str) -> bool:
    value = _normalize_text(
        facts.get("hay_hijos")
        or facts.get("has_children")
        or facts.get("hijos")
    )
    if value in {"true", "1", "si", "yes"}:
        return True
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("hija", "hijo", "hijos", "nina", "nino")) or "alimentos_hijos" in action_slug


def _resolve_has_minor_children(*, facts: dict[str, Any], query: str, has_children: bool) -> bool:
    if not has_children:
        return False
    age_candidates = [
        facts.get("edad_hijo"),
        facts.get("edad_hija"),
        facts.get("edad_hijos"),
        facts.get("child_age"),
    ]
    for candidate in age_candidates:
        age = _extract_numeric_age(candidate)
        if age is not None and age < 18:
            return True
    normalized_query = _normalize_text(query)
    month_match = re.search(r"(\d+)\s*(mes|meses)", normalized_query)
    if month_match:
        return True
    year_match = re.search(r"(\d+)\s*(ano|anos|año|años)", normalized_query)
    if year_match:
        try:
            return int(year_match.group(1)) < 18
        except ValueError:
            return False
    return has_children


def _resolve_clear_agreement(*, facts: dict[str, Any], query: str) -> bool:
    candidates = [
        _normalize_text(facts.get("divorcio_modalidad")),
        _normalize_text(facts.get("hay_acuerdo")),
        _normalize_text(facts.get("agreement_level")),
    ]
    if any(value in {"comun_acuerdo", "mutuo_acuerdo", "conjunto", "true", "1", "si", "yes", "alto"} for value in candidates):
        return True
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("comun acuerdo", "mutuo acuerdo", "estamos de acuerdo", "acordamos"))


def _resolve_high_conflict(*, facts: dict[str, Any], query: str) -> bool:
    values = [
        _normalize_text(facts.get("conflicto")),
        _normalize_text(facts.get("conflict_level")),
        _normalize_text(facts.get("agreement_level")),
    ]
    if any(value in {"alto", "high", "sin_acuerdo", "ninguno", "none"} for value in values):
        return True
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("no hay acuerdo", "conflicto", "discusion", "denuncia", "violencia", "no me pasa"))


def _resolve_no_current_support(*, facts: dict[str, Any], query: str) -> bool:
    values = [
        _normalize_text(facts.get("aporte_actual")),
        _normalize_text(facts.get("aporta_actualmente")),
        _normalize_text(facts.get("cumplimiento_alimentos")),
    ]
    if any(value in {"false", "0", "no", "nulo", "irregular"} for value in values):
        return True
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("no me pasa", "no pasa alimentos", "no aporta", "aporta poco", "irregular"))


def _resolve_decision_confidence(*, decision_basis: list[str]) -> str:
    if len(decision_basis) >= 3:
        return "high"
    if len(decision_basis) >= 2:
        return "medium"
    return "low"


def _extract_numeric_age(value: Any) -> int | None:
    text = _normalize_text(value)
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _strip_quick_start(value: str) -> str:
    prefix = "Primer paso recomendado:"
    if value.lower().startswith(prefix.lower()):
        return value[len(prefix):].strip(" .:")
    return value


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
