from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


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


def build_dual_output(response: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(response or {})
    payload["output_modes"] = {
        "user": _build_user_output(payload),
        "professional": _build_professional_output(payload),
    }
    return payload


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


def _build_user_output(response: dict[str, Any]) -> dict[str, Any]:
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
