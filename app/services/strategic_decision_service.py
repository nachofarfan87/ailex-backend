from __future__ import annotations

import re
import unicodedata
from typing import Any


PROFILE_SCORES = {
    "strong": 5,
    "supports": 3,
    "neutral": 0,
    "low": -3,
}

AGREEMENT_SCORES = {
    "high": 5,
    "neutral": 0,
    "low": -4,
}

_SIGNAL_LABELS = {
    "involves_divorce": "divorcio",
    "involves_alimentos": "alimentos",
    "has_children": "hijos",
    "has_minor_children": "hijos_menores",
    "clear_agreement": "acuerdo_claro",
    "high_conflict": "conflicto_alto",
    "no_current_support": "sin_aporte_actual",
    "has_assets_or_home": "bienes_o_vivienda",
    "simple_urgency": "urgencia_simple",
    "ended_cohabitation": "cese_convivencia",
}


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
    signals = _build_case_signals(
        facts=facts,
        pipeline_payload=payload,
        progression_policy=progression,
    )

    candidates = _build_strategy_candidates(payload=payload, signals=signals)
    if not candidates:
        decision = _build_default_decision(payload, signals=signals)
    else:
        scored = _score_candidates(candidates=candidates, signals=signals)
        winner = scored[0]
        alternative = scored[1] if len(scored) > 1 else None
        decision = _materialize_decision(
            payload=payload,
            signals=signals,
            winner=winner,
            alternative=alternative,
        )

    decision["case_domain"] = signals["case_domain"]
    decision["signals"] = signals
    decision["confidence"] = _resolve_decision_confidence(
        decision_basis=_as_str_list(decision.get("decision_basis"))
    )
    return decision


def _build_strategy_candidates(
    *,
    payload: dict[str, Any],
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    if signals["involves_divorce"]:
        candidates.append(
            {
                "id": "divorcio_acuerdo_integral",
                "recommended_path": (
                    "Ordenar un divorcio de comun acuerdo con un convenio que "
                    "llegue lo mas cerrado posible desde el inicio."
                ),
                "priority_action": (
                    "Cerrar por escrito los puntos del acuerdo y preparar una "
                    "presentacion conjunta suficientemente completa."
                ),
                "decision_basis": ["divorcio", "via_consensuada"],
                "profiles": {
                    "agreement": "high",
                    "children": "supports",
                    "alimentos": "supports",
                    "assets": "supports",
                    "urgency": "low",
                    "support_gap": "low",
                },
            }
        )
        candidates.append(
            {
                "id": "divorcio_unilateral_integral",
                "recommended_path": (
                    "Preparar un divorcio unilateral ordenando desde el inicio "
                    "los efectos que no conviene dejar abiertos."
                ),
                "priority_action": (
                    "Definir modalidad, competencia y el contenido minimo de la "
                    "presentacion inicial con foco en los puntos sensibles."
                ),
                "decision_basis": ["divorcio", "via_unilateral"],
                "profiles": {
                    "agreement": "low",
                    "children": "supports",
                    "alimentos": "supports",
                    "assets": "supports",
                    "urgency": "supports",
                    "support_gap": "supports",
                },
            }
        )

    if signals["involves_divorce"] and signals["has_children"] and signals["involves_alimentos"]:
        candidates.append(
            {
                "id": "divorcio_unilateral_alimentos_provisorios",
                "recommended_path": (
                    "Iniciar divorcio unilateral con una presentacion completa y "
                    "pedir alimentos provisorios desde el arranque si corresponde."
                ),
                "priority_action": (
                    "Preparar el inicio con foco en hijos, alimentos y cobertura "
                    "economica inmediata."
                ),
                "decision_basis": ["divorcio", "alimentos", "hijos"],
                "profiles": {
                    "agreement": "low",
                    "children": "strong",
                    "alimentos": "strong",
                    "assets": "supports",
                    "urgency": "strong",
                    "support_gap": "strong",
                },
            }
        )

    if signals["involves_alimentos"]:
        candidates.append(
            {
                "id": "alimentos_reclamo_inmediato",
                "recommended_path": (
                    "Iniciar de inmediato el reclamo principal de alimentos con "
                    "pedido de cuota provisoria."
                ),
                "priority_action": (
                    "Presentar el reclamo con la mejor base documental disponible "
                    "y foco en una respuesta inicial rapida."
                ),
                "decision_basis": ["alimentos", "cuota_provisoria"],
                "profiles": {
                    "agreement": "low",
                    "children": "supports",
                    "alimentos": "strong",
                    "assets": "neutral",
                    "urgency": "strong",
                    "support_gap": "strong",
                },
            }
        )
        candidates.append(
            {
                "id": "alimentos_preparacion_previa",
                "recommended_path": (
                    "Ordenar primero prueba e informacion economica para presentar "
                    "un reclamo alimentario mas cerrado."
                ),
                "priority_action": (
                    "Reunir datos de ingresos, gastos y documentacion antes de "
                    "judicializar."
                ),
                "decision_basis": ["alimentos", "preparacion_probatoria"],
                "profiles": {
                    "agreement": "neutral",
                    "children": "supports",
                    "alimentos": "supports",
                    "assets": "neutral",
                    "urgency": "low",
                    "support_gap": "low",
                },
            }
        )

    if not candidates:
        candidates.append(_build_default_decision(payload, signals=signals))

    return candidates


def _score_candidates(
    *,
    candidates: list[dict[str, Any]],
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        score, score_reasons = _score_candidate(candidate=candidate, signals=signals)
        scored.append(
            {
                **candidate,
                "score": score,
                "score_reasons": score_reasons,
                "_index": index,
            }
        )

    scored.sort(
        key=lambda item: (
            int(item.get("score", 0)),
            len(_as_str_list(item.get("decision_basis"))),
            -int(item.get("_index", 0)),
        ),
        reverse=True,
    )
    return scored


def _score_candidate(*, candidate: dict[str, Any], signals: dict[str, Any]) -> tuple[int, list[str]]:
    profiles = _as_dict(candidate.get("profiles"))
    score = 0
    reasons: list[str] = []

    agreement_profile = _clean_text(profiles.get("agreement")).lower()
    if signals["clear_agreement"]:
        agreement_score = AGREEMENT_SCORES.get(agreement_profile, 0)
        score += agreement_score
        if agreement_profile == "high":
            reasons.append("ya existe una base de acuerdo aprovechable")
        elif agreement_profile == "low":
            reasons.append("puede generar un nivel de conflicto innecesario")
    else:
        if agreement_profile == "low":
            score += 4
            reasons.append("hoy no hay acuerdo suficiente para depender de una via consensuada")
        elif agreement_profile == "high":
            score -= 4
            reasons.append("depende de un acuerdo que todavia no aparece firme")

    score += _score_signal(
        signal_active=signals["has_children"],
        profile=_clean_text(profiles.get("children")).lower(),
        positive_reason="hay hijos que conviene ordenar desde el inicio",
        negative_reason="deja demasiado abiertos los puntos que afectan a los hijos",
        reasons=reasons,
    )
    score += _score_signal(
        signal_active=signals["involves_alimentos"],
        profile=_clean_text(profiles.get("alimentos")).lower(),
        positive_reason="el componente alimentario ya pesa en la estrategia",
        negative_reason="deja el frente alimentario menos trabajado de lo que el caso sugiere",
        reasons=reasons,
    )
    score += _score_signal(
        signal_active=signals["no_current_support"],
        profile=_clean_text(profiles.get("support_gap")).lower(),
        positive_reason="hoy no hay aporte actual suficiente",
        negative_reason="postergaria una cobertura economica que ya aparece necesaria",
        reasons=reasons,
    )
    score += _score_signal(
        signal_active=signals["simple_urgency"],
        profile=_clean_text(profiles.get("urgency")).lower(),
        positive_reason="la respuesta practica no conviene postergarla",
        negative_reason="puede demorar una respuesta que hoy conviene dar antes",
        reasons=reasons,
    )
    score += _score_signal(
        signal_active=signals["has_assets_or_home"],
        profile=_clean_text(profiles.get("assets")).lower(),
        positive_reason="hay bienes o vivienda que conviene ordenar desde el arranque",
        negative_reason="deja patrimonialmente abiertos puntos que conviene encauzar ya",
        reasons=reasons,
    )

    if signals["high_conflict"]:
        if agreement_profile == "low":
            score += 2
            reasons.append("el nivel de conflicto hace menos confiable una salida apoyada solo en consenso")
        elif agreement_profile == "high":
            score -= 2

    if (
        signals["involves_divorce"]
        and signals["involves_alimentos"]
        and signals["has_children"]
        and candidate.get("id") == "divorcio_unilateral_alimentos_provisorios"
    ):
        score += 3
        reasons.append("integra en un mismo camino divorcio, hijos y alimentos")

    if (
        signals["involves_divorce"]
        and signals["has_assets_or_home"]
        and not signals["clear_agreement"]
        and candidate.get("id") in {"divorcio_unilateral_integral", "divorcio_unilateral_alimentos_provisorios"}
    ):
        score += 2

    return score, _dedupe_strings(reasons)[:4]


def _materialize_decision(
    *,
    payload: dict[str, Any],
    signals: dict[str, Any],
    winner: dict[str, Any],
    alternative: dict[str, Any] | None,
) -> dict[str, Any]:
    alternative_candidate = alternative or _build_default_decision(payload, signals=signals)

    return {
        "recommended_path": _adapt_recommended_path(candidate=winner, signals=signals),
        "priority_action": _adapt_priority_action(candidate=winner, signals=signals),
        "justification": _build_justification(candidate=winner, signals=signals),
        "alternative_path": _adapt_alternative_path(
            candidate=alternative_candidate,
            signals=signals,
            winner=winner,
        ),
        "alternative_reason": _build_alternative_reason(
            candidate=alternative_candidate,
            winner=winner,
            signals=signals,
        ),
        "decision_basis": _dedupe_strings(
            [
                *_as_str_list(winner.get("decision_basis")),
                *winner.get("score_reasons", []),
                *_decision_basis_from_signals(signals),
            ]
        )[:6],
    }


def _adapt_recommended_path(*, candidate: dict[str, Any], signals: dict[str, Any]) -> str:
    candidate_id = _clean_text(candidate.get("id"))
    path = _clean_text(candidate.get("recommended_path"))

    if candidate_id == "divorcio_unilateral_integral" and signals["has_assets_or_home"]:
        return (
            "Preparar un divorcio unilateral ordenando desde el inicio hijos, "
            "alimentos y los efectos patrimoniales mas sensibles."
        )
    if candidate_id == "divorcio_acuerdo_integral" and signals["has_children"] and signals["involves_alimentos"]:
        return (
            "Ordenar un divorcio de comun acuerdo con un convenio que deje "
            "resueltos hijos, alimentos y los demas puntos centrales."
        )
    return path


def _adapt_priority_action(*, candidate: dict[str, Any], signals: dict[str, Any]) -> str:
    candidate_id = _clean_text(candidate.get("id"))
    action = _clean_text(candidate.get("priority_action"))

    if candidate_id == "divorcio_unilateral_alimentos_provisorios" and signals["has_assets_or_home"]:
        return (
            "Preparar el inicio con foco en hijos, alimentos y orden de "
            "vivienda o bienes que no convenga dejar abiertos."
        )
    if candidate_id == "divorcio_acuerdo_integral" and signals["has_children"] and signals["involves_alimentos"]:
        return (
            "Cerrar un convenio que ordene hijos, alimentos y los demas "
            "efectos principales antes de presentar."
        )
    if candidate_id == "alimentos_reclamo_inmediato" and signals["no_current_support"]:
        return (
            "Presentar el reclamo alimentario con pedido provisorio y la "
            "mejor prueba basica disponible."
        )
    return action


def _adapt_alternative_path(*, candidate: dict[str, Any], signals: dict[str, Any], winner: dict[str, Any]) -> str:
    candidate_id = _clean_text(candidate.get("id"))
    winner_id = _clean_text(winner.get("id"))
    path = _clean_text(candidate.get("recommended_path") or candidate.get("alternative_path"))

    if candidate_id == winner_id:
        return "Mantener un camino mas gradual y ajustar despues lo que hoy no este cerrado."
    if candidate_id == "divorcio_acuerdo_integral" and not signals["clear_agreement"]:
        return "Seguir intentando un acuerdo integral antes de presentar."
    if candidate_id == "alimentos_preparacion_previa" and signals["no_current_support"]:
        return "Reunir primero mas prueba economica antes de iniciar el reclamo."
    return path


def _build_justification(*, candidate: dict[str, Any], signals: dict[str, Any]) -> str:
    candidate_id = _clean_text(candidate.get("id"))

    if candidate_id == "divorcio_unilateral_alimentos_provisorios":
        parts = ["hoy no hay acuerdo suficiente"]
        if signals["has_children"]:
            parts.append("hay hijos que requieren quedar ordenados desde el inicio")
        if signals["involves_alimentos"]:
            parts.append("el frente alimentario ya forma parte del caso")
        if signals["no_current_support"] or signals["simple_urgency"]:
            parts.append("la cobertura economica no conviene demorarla")
        if signals["has_assets_or_home"]:
            parts.append("ademas conviene ordenar desde el inicio lo relativo a la vivienda o los bienes")
        return "porque " + _join_reasons(parts) + "."

    if candidate_id == "divorcio_acuerdo_integral":
        parts = ["ya existe una base de acuerdo suficiente"]
        if signals["has_children"]:
            parts.append("eso permite ordenar mejor lo relativo a los hijos")
        if signals["involves_alimentos"]:
            parts.append("tambien ayuda a cerrar alimentos sin agregar friccion innecesaria")
        if signals["has_assets_or_home"]:
            parts.append("y facilita presentar de forma mas limpia vivienda o bienes")
        return "porque " + _join_reasons(parts) + "."

    if candidate_id == "alimentos_reclamo_inmediato":
        parts = []
        if signals["no_current_support"]:
            parts.append("hoy no hay aporte actual suficiente")
        if signals["has_children"]:
            parts.append("hay hijos que necesitan una respuesta economica mas inmediata")
        if signals["simple_urgency"]:
            parts.append("esperar a cerrar toda la prueba puede retrasar una cobertura que ya hace falta")
        return "porque " + _join_reasons(parts or ["este camino da una respuesta mas util para el estado actual del caso"]) + "."

    if candidate_id == "divorcio_unilateral_integral":
        parts = ["no hay acuerdo claro para sostener una presentacion conjunta"]
        if signals["has_children"]:
            parts.append("conviene dejar ordenados desde el inicio los efectos sobre hijos")
        if signals["has_assets_or_home"]:
            parts.append("y no conviene postergar vivienda o bienes sensibles para mas adelante")
        return "porque " + _join_reasons(parts) + "."

    score_reasons = _as_str_list(candidate.get("score_reasons"))
    if score_reasons:
        return f"porque {_join_reasons(score_reasons[:3])}."
    return "porque hoy es el camino mas ordenado para avanzar sin abrir frentes innecesarios."


def _build_alternative_reason(*, candidate: dict[str, Any], winner: dict[str, Any], signals: dict[str, Any]) -> str:
    candidate_id = _clean_text(candidate.get("id"))
    winner_id = _clean_text(winner.get("id"))

    if candidate_id == winner_id:
        return "sirve como variante de resguardo, pero hoy deja mas puntos sensibles abiertos de los que conviene."
    if signals["has_assets_or_home"] and winner_id in {"divorcio_unilateral_integral", "divorcio_unilateral_alimentos_provisorios"}:
        return "deja mas expuestos vivienda o bienes que conviene ordenar desde el inicio si el acuerdo sigue flojo."
    if candidate_id == "divorcio_acuerdo_integral" and not signals["clear_agreement"]:
        return "depende de un acuerdo que hoy no aparece lo bastante firme como para sostener el camino principal."
    if candidate_id == "alimentos_preparacion_previa" and signals["no_current_support"]:
        return "puede mejorar la base probatoria, pero deja sin respuesta inmediata una necesidad alimentaria que ya aparece en el caso."
    if candidate_id == "divorcio_unilateral_integral" and signals["clear_agreement"]:
        return "sigue siendo viable, pero puede generar un nivel de conflicto innecesario y mas friccion donde ya hay una base de acuerdo aprovechable."
    if candidate_id == "divorcio_unilateral_alimentos_provisorios" and signals["clear_agreement"]:
        return "puede usarse si el acuerdo se cae, pero hoy forzaria un nivel de conflicto que no parece necesario."
    if candidate_id == "alimentos_reclamo_inmediato" and not signals["no_current_support"] and not signals["simple_urgency"]:
        return "puede funcionar, aunque en este escenario todavia hay margen para cerrar mejor la base economica antes de presentar."
    return "es una opcion posible, pero hoy deja mas puntos abiertos o agrega friccion donde el camino principal ordena mejor el caso."


def _build_default_decision(payload: dict[str, Any], *, signals: dict[str, Any]) -> dict[str, Any]:
    case_strategy = _as_dict(payload.get("case_strategy"))
    recommended_actions = _as_str_list(case_strategy.get("recommended_actions"))
    procedural_focus = _as_str_list(case_strategy.get("procedural_focus"))
    quick_start = _strip_quick_start(_clean_text(payload.get("quick_start")))
    primary = quick_start or (
        recommended_actions[0]
        if recommended_actions
        else "Ordenar primero el encuadre principal del caso antes de cerrar la estrategia."
    )
    secondary = (
        recommended_actions[1]
        if len(recommended_actions) > 1
        else "Avanzar con una variante mas abierta y ajustar despues los faltantes relevantes."
    )
    practical_focus = procedural_focus[0] if procedural_focus else "los puntos que todavia cambian el encuadre practico"
    return {
        "id": "payload_strategy",
        "recommended_path": primary,
        "priority_action": primary,
        "justification": f"porque permite avanzar sin perder control sobre {practical_focus}.",
        "alternative_path": secondary,
        "alternative_reason": "es util como variante, pero normalmente deja mas margen para ajustes posteriores.",
        "decision_basis": ["payload_strategy"],
        "profiles": {
            "agreement": "neutral",
            "children": "neutral",
            "alimentos": "neutral",
            "assets": "neutral",
            "urgency": "neutral",
            "support_gap": "neutral",
        },
    }


def _build_case_signals(
    *,
    facts: dict[str, Any],
    pipeline_payload: dict[str, Any],
    progression_policy: dict[str, Any],
) -> dict[str, Any]:
    query = _clean_text(pipeline_payload.get("query"))
    classification = _as_dict(pipeline_payload.get("classification"))
    action_slug = _clean_text(classification.get("action_slug")).lower()
    case_domain = _clean_text(
        _as_dict(pipeline_payload.get("case_profile")).get("case_domain")
        or classification.get("case_domain")
        or pipeline_payload.get("case_domain")
    ).lower()
    topics = set(_as_str_list(progression_policy.get("topics_covered")))
    normalized_query = _normalize_text(query)

    involves_divorce = (
        _is_topic_present(facts.get("tema_divorcio"), allow_inferred=True)
        or case_domain == "divorcio"
        or "divorcio" in action_slug
        or "divorcio" in topics
    )
    if not involves_divorce:
        involves_divorce = "divorcio" in normalized_query

    involves_alimentos = (
        _is_topic_present(facts.get("tema_alimentos"), allow_inferred=True)
        or case_domain == "alimentos"
        or "alimentos" in action_slug
        or "alimentos" in topics
    )
    if not involves_alimentos:
        involves_alimentos = "alimento" in normalized_query
    has_children = _resolve_has_children(facts=facts, query=query, action_slug=action_slug)
    has_minor_children = _resolve_has_minor_children(facts=facts, query=query, has_children=has_children)
    clear_agreement = _resolve_clear_agreement(facts=facts, query=query)
    high_conflict = _resolve_high_conflict(facts=facts, query=query)
    no_current_support = _resolve_no_current_support(facts=facts, query=query)
    has_assets_or_home = _resolve_has_assets_or_home(facts=facts, query=query)
    simple_urgency = _resolve_simple_urgency(facts=facts, query=query)
    ended_cohabitation = _resolve_ended_cohabitation(facts=facts, query=query)

    return {
        "case_domain": case_domain or ("divorcio" if involves_divorce else "alimentos" if involves_alimentos else ""),
        "involves_divorce": involves_divorce,
        "involves_alimentos": involves_alimentos,
        "has_children": has_children,
        "has_minor_children": has_minor_children,
        "clear_agreement": clear_agreement,
        "high_conflict": high_conflict,
        "no_current_support": no_current_support,
        "has_assets_or_home": has_assets_or_home,
        "simple_urgency": simple_urgency,
        "ended_cohabitation": ended_cohabitation,
    }


def _collect_case_facts(*, conversation_state: dict[str, Any], pipeline_payload: dict[str, Any]) -> dict[str, Any]:
    facts = dict(_as_dict(pipeline_payload.get("facts")))
    facts.update(_as_dict(_as_dict(pipeline_payload.get("conversational")).get("known_facts")))
    facts.update(
        _as_dict(
            _as_dict(_as_dict(pipeline_payload.get("metadata")).get("clarification_context")).get("known_facts")
        )
    )
    facts.update(_as_dict(pipeline_payload.get("known_facts")))
    facts.update(_as_dict(conversation_state.get("known_facts_map")))

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
    fact_keys = ("hay_hijos", "has_children", "hijos")
    for key in ("hay_hijos", "has_children", "hijos"):
        if _is_true_like(facts.get(key)):
            return True
    if _has_signal_fact_data(facts, fact_keys):
        return False
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("hija", "hijo", "hijos", "nina", "nino")) or "alimentos_hijos" in action_slug


def _resolve_has_minor_children(*, facts: dict[str, Any], query: str, has_children: bool) -> bool:
    if not has_children:
        return False
    for key in ("hay_hijos_edad", "edad_hijo", "edad_hija", "edad_hijos", "child_age"):
        age = _extract_numeric_age(facts.get(key))
        if age is not None:
            return age < 18
    normalized_query = _normalize_text(query)
    if re.search(r"(\d+)\s*(mes|meses)", normalized_query):
        return True
    year_match = re.search(r"(\d+)\s*(ano|anos|año|años)", normalized_query)
    if year_match:
        try:
            return int(year_match.group(1)) < 18
        except ValueError:
            return False
    return has_children


def _resolve_clear_agreement(*, facts: dict[str, Any], query: str) -> bool:
    fact_keys = ("divorcio_modalidad", "hay_acuerdo", "agreement_level")
    candidates = [
        _normalize_text(facts.get("divorcio_modalidad")),
        _normalize_text(facts.get("hay_acuerdo")),
        _normalize_text(facts.get("agreement_level")),
    ]
    if any(
        value in {"comun_acuerdo", "mutuo_acuerdo", "conjunto", "true", "1", "si", "yes", "alto", "full", "completo"}
        for value in candidates
    ):
        return True
    if _has_signal_fact_data(facts, fact_keys):
        return False
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("comun acuerdo", "mutuo acuerdo", "estamos de acuerdo", "acordamos"))


def _resolve_high_conflict(*, facts: dict[str, Any], query: str) -> bool:
    fact_keys = ("conflicto", "conflict_level", "agreement_level", "hay_acuerdo")
    values = [
        _normalize_text(facts.get("conflicto")),
        _normalize_text(facts.get("conflict_level")),
        _normalize_text(facts.get("agreement_level")),
        _normalize_text(facts.get("hay_acuerdo")),
    ]
    if any(value in {"alto", "high", "sin_acuerdo", "ninguno", "none", "false", "0", "no"} for value in values):
        return True
    if _has_signal_fact_data(facts, fact_keys):
        return False
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("no hay acuerdo", "conflicto", "discusion", "denuncia", "violencia", "no me pasa"))


def _resolve_no_current_support(*, facts: dict[str, Any], query: str) -> bool:
    fact_keys = ("aporte_actual", "aporta_actualmente", "cumplimiento_alimentos", "aportes_actuales")
    values = [
        _normalize_text(facts.get("aporte_actual")),
        _normalize_text(facts.get("aporta_actualmente")),
        _normalize_text(facts.get("cumplimiento_alimentos")),
        _normalize_text(facts.get("aportes_actuales")),
    ]
    if any(value in {"false", "0", "no", "nulo", "irregular"} for value in values):
        return True
    if _has_signal_fact_data(facts, fact_keys):
        return False
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("no me pasa", "no pasa alimentos", "no aporta", "aporta poco", "irregular"))


def _resolve_has_assets_or_home(*, facts: dict[str, Any], query: str) -> bool:
    fact_keys = ("hay_bienes", "vivienda_familiar", "hay_vivienda", "bienes_relevantes")
    for key in fact_keys:
        if _is_true_like(facts.get(key)):
            return True
    if _has_signal_fact_data(facts, fact_keys):
        return False
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("vivienda", "casa", "departamento", "bienes", "auto", "inmueble"))


def _resolve_simple_urgency(*, facts: dict[str, Any], query: str) -> bool:
    fact_keys = ("urgencia", "urgency_level")
    value = _normalize_text(facts.get("urgencia") or facts.get("urgency_level"))
    if value in {"true", "1", "si", "yes", "alta", "high", "urgente"}:
        return True
    if _has_signal_fact_data(facts, fact_keys):
        return False
    normalized_query = _normalize_text(query)
    return "urgente" in normalized_query


def _resolve_ended_cohabitation(*, facts: dict[str, Any], query: str) -> bool:
    if _is_true_like(facts.get("cese_convivencia")):
        return True
    normalized_query = _normalize_text(query)
    return any(token in normalized_query for token in ("dejamos de convivir", "ya no convivimos", "separados"))


def _resolve_decision_confidence(*, decision_basis: list[str]) -> str:
    if len(decision_basis) >= 5:
        return "high"
    if len(decision_basis) >= 3:
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


def _join_reasons(parts: list[str]) -> str:
    clean = [part.strip() for part in parts if part and part.strip()]
    if not clean:
        return "hay elementos del caso que inclinan la estrategia en ese sentido"
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} y {clean[1]}"
    return f"{', '.join(clean[:-1])} y {clean[-1]}"


def _is_true_like(value: Any) -> bool:
    normalized = _normalize_text(value)
    return normalized in {"true", "1", "si", "yes", "inferred", "informada"}


def _is_topic_present(value: Any, *, allow_inferred: bool = False) -> bool:
    normalized = _normalize_text(value)
    if normalized in {"true", "1", "si", "yes"}:
        return True
    return allow_inferred and normalized == "inferred"


def _has_signal_fact_data(facts: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        if key in facts and facts.get(key) not in ({}, [], "", None):
            return True
    return False


def _strip_quick_start(value: str) -> str:
    prefix = "Primer paso recomendado:"
    if value.lower().startswith(prefix.lower()):
        return value[len(prefix):].strip(" .:")
    return value


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


def _decision_basis_from_signals(signals: dict[str, Any]) -> list[str]:
    basis: list[str] = []
    for key, label in _SIGNAL_LABELS.items():
        if signals.get(key):
            basis.append(label)
    return basis


def _score_signal(
    *,
    signal_active: bool,
    profile: str,
    positive_reason: str,
    negative_reason: str,
    reasons: list[str],
) -> int:
    if not signal_active:
        return 0

    value = PROFILE_SCORES.get(profile, 0)
    if value > 0:
        reasons.append(positive_reason)
    elif value < 0:
        reasons.append(negative_reason)
    return value


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.casefold()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


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
