from __future__ import annotations

import re
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any


_SIMILARITY_THRESHOLD = 0.9
_MAX_ACTIONS = 5
_REMOVED_PHRASES = (
    "no corresponde presentar",
    "no sobreactuar",
    "base disponible",
)
_SOFT_WARNING_PATTERNS = (
    "la informacion faltante todavia es significativa para una evaluacion estable",
    "persisten cuestiones normativas sin resolver que pueden impactar la prueba",
    "la prueba faltante relevante todavia es amplia",
    "persisten preguntas criticas que pueden alterar la estrategia",
)
_CRITICAL_ACTION_PATTERNS = (
    "definir via",
    "definir la via",
    "via procesal",
    "competencia",
    "presentar demanda",
    "iniciar demanda",
    "promover accion",
    "decidir estrategia",
)
_EVIDENCE_ACTION_PATTERNS = (
    "prueba",
    "acreditar",
    "documental",
    "pericia",
    "testigo",
    "constancia",
)
_DRAFTING_ACTION_PATTERNS = (
    "redact",
    "escrito",
    "borrador",
    "petitorio",
    "demanda",
    "presentacion",
)
_CRITICAL_MISSING_PATTERNS = (
    "competencia",
    "incompetencia",
    "legitimacion",
    "legitimación",
    "personeria",
    "personería",
    "capacidad para demandar",
    "plazo fatal",
    "caducidad",
    "prescripcion",
    "prescripción",
    "domicilio para definir competencia",
    "juzgado competente",
    "falta acreditar matrimonio",
    "falta acreditar vinculo",
    "falta acreditar vínculo",
    "prueba critica",
    "prueba crítica",
)
_ORDINARY_MISSING_PATTERNS = (
    "bienes",
    "ganancial",
    "compensacion economica",
    "compensación económica",
    "convenio regulador",
    "propuesta reguladora",
    "vivienda familiar",
    "alimentos",
    "cuidado personal",
    "regimen de comunicacion",
    "régimen de comunicación",
    "modalidad final",
    "detalle patrimonial",
    "detalle completo de bienes",
)
_AMBIGUOUS_DOMAIN_PATTERNS = (
    "generic",
    "generico",
    "genérico",
    "indefinido",
)
_HIGH_RISK_WARNING_PATTERNS = (
    "incompetencia",
    "legitimacion",
    "legitimación",
    "caducidad",
    "prescripcion",
    "prescripción",
    "prueba critica",
    "prueba crítica",
)


def refine(response: dict[str, Any]) -> dict[str, Any]:
    refined = deepcopy(response or {})
    refined = dedupe_output_blocks(refined)

    case_domains = dedupe_domains(_as_str_list(refined.get("case_domains")))
    if case_domains:
        refined["case_domains"] = case_domains

    legal_strategy = _as_dict(refined.get("legal_strategy"))
    if legal_strategy:
        legal_strategy["case_domains"] = dedupe_domains(_as_str_list(legal_strategy.get("case_domains")))
        refined["legal_strategy"] = legal_strategy

    case_strategy = _as_dict(refined.get("case_strategy"))
    if case_strategy:
        actions = prioritize_actions(_as_str_list(case_strategy.get("recommended_actions")))
        case_strategy["recommended_actions"] = actions
        case_strategy["risk_analysis"] = _dedupe_texts(_as_str_list(case_strategy.get("risk_analysis")))
        case_strategy["conflict_summary"] = _dedupe_texts(_as_str_list(case_strategy.get("conflict_summary")))
        case_strategy["procedural_focus"] = _dedupe_texts(_as_str_list(case_strategy.get("procedural_focus")))
        case_strategy["secondary_domain_notes"] = _dedupe_texts(_as_str_list(case_strategy.get("secondary_domain_notes")))
        case_strategy["strategic_narrative"] = simplify_strategy_text(str(case_strategy.get("strategic_narrative") or ""))
        refined["case_strategy"] = case_strategy
        quick_start = extract_quick_start(actions)
        if quick_start:
            refined["quick_start"] = quick_start

    refined = rebalance_missing_info_and_confidence(refined)
    return refined


def rebalance_missing_info_and_confidence(response: dict[str, Any]) -> dict[str, Any]:
    refined = deepcopy(response or {})
    classified = _classify_missing_information(refined)

    case_strategy = _as_dict(refined.get("case_strategy"))
    if case_strategy:
        case_strategy["critical_missing_information"] = classified["critical_missing_information"]
        case_strategy["ordinary_missing_information"] = classified["ordinary_missing_information"]
        case_strategy["missing_information"] = [
            *classified["critical_missing_information"],
            *classified["ordinary_missing_information"],
        ]
        case_strategy["risk_analysis"] = _dedupe_texts(_as_str_list(case_strategy.get("risk_analysis")))
        refined["case_strategy"] = case_strategy

    procedural_strategy = _as_dict(refined.get("procedural_strategy"))
    if procedural_strategy:
        procedural_strategy["missing_information"] = list(case_strategy.get("missing_information") or [])
        procedural_strategy["missing_info"] = list(case_strategy.get("missing_information") or [])
        refined["procedural_strategy"] = procedural_strategy

    refined["warnings"] = _rebalance_warnings(
        warnings=_as_str_list(refined.get("warnings")),
        critical_missing_information=classified["critical_missing_information"],
        ordinary_missing_information=classified["ordinary_missing_information"],
        simple_case=_is_simple_case(refined, classified["critical_missing_information"]),
    )

    legal_decision = _as_dict(refined.get("legal_decision"))
    rebalanced_confidence = rebalance_confidence(refined, classified=classified)
    if rebalanced_confidence is not None:
        refined["confidence"] = rebalanced_confidence
        if legal_decision:
            legal_decision["confidence_score"] = rebalanced_confidence
            refined["legal_decision"] = legal_decision

    return refined


def dedupe_output_blocks(response: dict[str, Any]) -> dict[str, Any]:
    refined = deepcopy(response or {})
    case_strategy = _as_dict(refined.get("case_strategy"))
    if case_strategy:
        for key in ("recommended_actions", "risk_analysis", "conflict_summary", "procedural_focus", "secondary_domain_notes"):
            case_strategy[key] = _dedupe_texts(_as_str_list(case_strategy.get(key)))
        case_strategy["strategic_narrative"] = _dedupe_paragraphs(str(case_strategy.get("strategic_narrative") or ""))
        refined["case_strategy"] = case_strategy
    warnings = refined.get("warnings")
    if isinstance(warnings, list):
        refined["warnings"] = _dedupe_texts(_as_str_list(warnings))
    return refined


def dedupe_domains(domains: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in domains or []:
        value = str(item or "").strip()
        normalized = value.casefold()
        if not value or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def prioritize_actions(actions: list[str]) -> list[str]:
    ranked = []
    for index, action in enumerate(_dedupe_texts(actions)):
        normalized = _normalize_text(action)
        priority = 3
        if any(token in normalized for token in _CRITICAL_ACTION_PATTERNS):
            priority = 0
        elif any(token in normalized for token in _EVIDENCE_ACTION_PATTERNS):
            priority = 1
        elif any(token in normalized for token in _DRAFTING_ACTION_PATTERNS):
            priority = 2
        ranked.append((priority, index, action))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:_MAX_ACTIONS]]


def simplify_strategy_text(text: str) -> str:
    paragraphs = []
    for paragraph in re.split(r"\n{2,}", str(text or "")):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        for phrase in _REMOVED_PHRASES:
            cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(re.escape(f"{phrase}."), "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
        if cleaned:
            paragraphs.append(cleaned)
    deduped = _dedupe_texts(paragraphs)
    if not deduped:
        return ""
    simplified = " ".join(deduped)
    sentences = re.split(r"(?<=[\.\!\?])\s+", simplified)
    concise = " ".join(sentence.strip() for sentence in sentences[:3] if sentence.strip())
    return concise[:700].strip()


def extract_quick_start(actions: list[str]) -> str:
    prioritized = prioritize_actions(actions)
    if not prioritized:
        return ""
    return f"Primer paso recomendado: {prioritized[0]}"


def rebalance_confidence(
    response: dict[str, Any],
    *,
    classified: dict[str, list[str]] | None = None,
) -> float | None:
    classified = classified or _classify_missing_information(response)
    case_domains = [item.casefold() for item in _as_str_list(response.get("case_domains"))]
    case_domain = str(response.get("case_domain") or "").strip().casefold()
    legal_decision = _as_dict(response.get("legal_decision"))
    current_confidence = _safe_float(
        legal_decision.get("confidence_score", response.get("confidence"))
    )
    current_confidence = current_confidence if current_confidence is not None else 0.0
    if not _is_simple_case(response, classified["critical_missing_information"]):
        return current_confidence

    if "divorcio" in case_domains or case_domain == "divorcio":
        if _is_divorce_refinement_only(classified["ordinary_missing_information"]):
            return max(current_confidence, 0.6)
        if classified["ordinary_missing_information"]:
            return max(current_confidence, 0.55)
        return max(current_confidence, 0.6)
    return max(current_confidence, 0.55)


def _classify_missing_information(response: dict[str, Any]) -> dict[str, list[str]]:
    collected = _collect_missing_information(response)
    critical: list[str] = []
    ordinary: list[str] = []
    for item in collected:
        normalized = _normalize_text(item)
        if _is_critical_missing(normalized):
            critical.append(_normalize_missing_statement(item))
            continue
        ordinary.append(_normalize_missing_statement(item))
    return {
        "critical_missing_information": _dedupe_texts(critical),
        "ordinary_missing_information": _dedupe_texts(ordinary),
    }


def _collect_missing_information(response: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for payload_key, field_names in (
        ("case_profile", ("missing_critical_facts", "missing_info", "missing_information")),
        ("case_structure", ("missing_information",)),
        ("procedural_strategy", ("missing_information", "missing_info")),
        ("normative_reasoning", ("unresolved_issues",)),
        ("question_engine_result", ("critical_questions", "questions")),
    ):
        payload = _as_dict(response.get(payload_key))
        for field_name in field_names:
            values.extend(_as_str_list(payload.get(field_name)))
    case_strategy = _as_dict(response.get("case_strategy"))
    values.extend(_as_str_list(case_strategy.get("missing_information")))
    return _dedupe_texts(values)


def _rebalance_warnings(
    *,
    warnings: list[str],
    critical_missing_information: list[str],
    ordinary_missing_information: list[str],
    simple_case: bool,
) -> list[str]:
    deduped = _dedupe_texts(warnings)
    if not simple_case:
        return deduped

    moderated: list[str] = []
    for item in deduped:
        normalized = _normalize_text(item)
        if any(pattern in normalized for pattern in _HIGH_RISK_WARNING_PATTERNS):
            moderated.append(item)
            continue
        if any(pattern in normalized for pattern in _SOFT_WARNING_PATTERNS):
            continue
        moderated.append(item)

    if critical_missing_information:
        return moderated

    if ordinary_missing_information and not any("faltan datos para afinar" in _normalize_text(item) for item in moderated):
        moderated.append("Faltan datos para afinar detalles procesales o patrimoniales, pero el encuadre base del caso ya es utilizable.")
    return _dedupe_texts(moderated)


def _is_simple_case(response: dict[str, Any], critical_missing_information: list[str]) -> bool:
    case_domains = [item.casefold() for item in _as_str_list(response.get("case_domains"))]
    case_domain = str(response.get("case_domain") or "").strip().casefold()
    classification = _as_dict(response.get("classification"))
    action_slug = str(classification.get("action_slug") or "").strip().casefold()
    case_strategy = _as_dict(response.get("case_strategy"))
    legal_decision = _as_dict(response.get("legal_decision"))
    procedural_case_state = _as_dict(response.get("procedural_case_state"))

    if critical_missing_information:
        return False
    if str(procedural_case_state.get("blocking_factor") or legal_decision.get("blocking_factor") or "none").strip().lower() not in {"", "none"}:
        return False
    if legal_decision.get("execution_readiness") == "bloqueado_procesalmente":
        return False
    if _looks_ambiguous(action_slug, case_domain):
        return False
    if bool(response.get("had_interdomain_conflict")):
        return False
    if not (case_domain or case_domains):
        return False
    if not _has_clear_primary_domain(case_domain or (case_domains[0] if case_domains else "")):
        return False
    if not str(case_strategy.get("strategic_narrative") or "").strip():
        return False
    if not _as_str_list(case_strategy.get("recommended_actions")):
        return False
    if not str(response.get("quick_start") or "").strip():
        return False
    return True


def _has_clear_primary_domain(domain: str) -> bool:
    normalized = _normalize_text(domain)
    return bool(normalized) and not any(pattern in normalized for pattern in _AMBIGUOUS_DOMAIN_PATTERNS)


def _is_divorce_refinement_only(ordinary_missing_information: list[str]) -> bool:
    if not ordinary_missing_information:
        return True
    normalized_items = [_normalize_text(item) for item in ordinary_missing_information]
    if any(
        "alimentos" in item
        or "cuidado personal" in item
        or "regimen de comunicacion" in item
        or "régimen de comunicación" in item
        for item in normalized_items
    ):
        return False
    return True


def _looks_ambiguous(action_slug: str, case_domain: str) -> bool:
    action = _normalize_text(action_slug)
    domain = _normalize_text(case_domain)
    if not action and not domain:
        return True
    return any(pattern in action or pattern in domain for pattern in _AMBIGUOUS_DOMAIN_PATTERNS)


def _is_critical_missing(normalized_text: str) -> bool:
    return any(pattern in normalized_text for pattern in _CRITICAL_MISSING_PATTERNS)


def _normalize_missing_statement(text: str) -> str:
    normalized = _normalize_text(text)
    canonical_groups = (
        (
            ("si sera unilateral o conjunto", "si será unilateral o conjunto", "falta definir via", "falta definir modalidad procesal", "via procesal"),
            "Definir la via procesal aplicable.",
        ),
        (
            ("competencia", "juzgado competente", "domicilio para definir competencia"),
            "Precisar competencia judicial y domicilios relevantes.",
        ),
        (
            ("legitimacion", "legitimación", "personeria", "personería"),
            "Acreditar legitimacion y personeria de las partes.",
        ),
        (
            ("bienes", "ganancial", "compensacion economica", "compensación económica", "vivienda familiar"),
            "Precisar bienes, vivienda familiar y eventual compensacion economica.",
        ),
        (
            ("alimentos", "cuidado personal", "regimen de comunicacion", "régimen de comunicación"),
            "Precisar alimentos, cuidado personal y regimen de comunicacion si corresponden.",
        ),
        (
            ("convenio regulador", "propuesta reguladora", "modalidad final"),
            "Completar la propuesta o convenio regulador con el nivel de detalle necesario.",
        ),
    )
    for patterns, canonical in canonical_groups:
        if any(pattern in normalized for pattern in patterns):
            return canonical
    cleaned = re.sub(r"^(no se informa sobre|falta definir|falta precisar|falta acreditar)\s+", "", str(text or "").strip(), flags=re.IGNORECASE)
    cleaned = cleaned[:1].upper() + cleaned[1:] if cleaned else ""
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _dedupe_paragraphs(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", str(text or "")) if part.strip()]
    return "\n\n".join(_dedupe_texts(paragraphs))


def _dedupe_texts(items: list[str]) -> list[str]:
    result: list[str] = []
    normalized_seen: list[str] = []
    for item in items:
        value = str(item or "").strip()
        normalized = _normalize_text(value)
        if not normalized:
            continue
        if any(_similarity(normalized, existing) >= _SIMILARITY_THRESHOLD for existing in normalized_seen):
            continue
        normalized_seen.append(normalized)
        result.append(value)
    return result


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=left, b=right).ratio()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
