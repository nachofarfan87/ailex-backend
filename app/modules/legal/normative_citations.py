"""
AILEX — Resolver de citas normativas procesales (V1).

PRINCIPIO: todas las referencias provienen exclusivamente de normative_rules.py.
El sistema nunca genera artículos por inferencia libre.  Si no hay entrada
suficiente → devuelve vacío + advertencia explicativa.

Reglas de búsqueda (por prioridad):
  1. jurisdiccion + fuero + action_slug   → match_type "direct"
  2. "nacional"  + fuero + action_slug   → match_type "direct"  (+warning jurisdiccion)
  3. jurisdiccion + fuero + slug_general → match_type "inferred" (solo si se registra
     un alias explícito en _FALLBACK_SLUGS; confianza rebajada + warning)
  4. "nacional"  + fuero + slug_general → match_type "inferred"
  5. Sin coincidencia → vacío + warning explicativo.
"""

import unicodedata

from app.modules.legal.normative_rules import NORMATIVE_RULES


# Alias de retroceso: si action_slug no tiene entrada directa, intentar con
# el slug_general listado aquí.  Solo slugs cuyo fallback es semánticamente válido.
_FALLBACK_SLUGS: dict[str, str] = {
    "traslado_demanda": "traslado",
    "contestacion_demanda": "traslado_demanda",
    "comparecencia": "audiencia",
    "plazo_para_contestar": "traslado_demanda",
    "plazo_para_apelar": "apelacion",
    "plazo_para_subsanar": "subsanacion",
}

_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}

_WARNING_AUTO = (
    "Referencia normativa sugerida automáticamente a partir del acto procesal "
    "detectado. Verificar correspondencia exacta y vigencia antes de citar."
)
_WARNING_NACIONAL_FALLBACK = (
    "Se usó como referencia la legislación procesal nacional (CPCCN). "
    "La jurisdicción indicada puede tener normas propias con artículos distintos."
)
_WARNING_INFERRED = (
    "La referencia se obtuvo por analogía con un acto procesal relacionado "
    "(coincidencia indirecta). Verificar aplicabilidad al caso concreto."
)


def resolve_normative_references(
    action_slug: str | None,
    jurisdiction: str | None,
    forum: str | None = None,
) -> dict:
    """
    Resolver referencias normativas para un acto procesal detectado.

    Args:
        action_slug:  Slug del acto procesual (ej. "traslado_demanda").
                      Proviene de detect_procedural_action → "slug".
        jurisdiction: Jurisdicción normalizada (ej. "Jujuy", "Nacional").
        forum:        Fuero procesal (ej. "civil", "laboral").
                      Por defecto "civil" si se omite.

    Returns:
        dict con:
          normative_references  list[dict] — puede ser vacía
          normative_confidence  "high" | "medium" | "low" | None
          normative_warning     str | None
          normative_summary     str | None
    """
    # --- a) Sin action_slug → no hay base para buscar --------------------
    if not action_slug or action_slug == "desconocida":
        return _empty(
            "No se pudo determinar el acto procesal principal: "
            "es necesario identificar la actuación para sugerir base normativa."
        )

    norm_juris = _normalize(jurisdiction or "")
    norm_forum = _normalize(forum or "civil") or "civil"
    norm_slug = _normalize(action_slug)

    # --- Intento de resolución con prioridades -------------------------
    refs, match_type, used_juris = _resolve(norm_juris, norm_forum, norm_slug)

    # --- b) Jurisdicción sin mapping y sin fallback nacional -----------
    if refs is None:
        return _empty(
            f"No se encontró base normativa cargada para la jurisdicción "
            f"'{jurisdiction or 'no especificada'}' ni en la referencia nacional. "
            f"Acto: '{action_slug}'."
        )

    # --- c) Acto sin referencias (lista vacía explícita) ---------------
    if not refs:
        return _empty(
            f"El acto procesal '{action_slug}' no tiene una referencia normativa "
            "específica cargada con suficiente certeza. No se emite cita automática."
        )

    # --- Construir resultado -------------------------------------------
    warnings: list[str] = [_WARNING_AUTO]

    if used_juris == "nacional" and norm_juris not in ("", "nacional"):
        warnings.append(_WARNING_NACIONAL_FALLBACK)

    if match_type == "inferred":
        warnings.append(_WARNING_INFERRED)

    enriched = [_enrich(r, match_type) for r in refs]
    overall_confidence = _aggregate_confidence(enriched, match_type)
    summary = _build_summary(action_slug, enriched)

    return {
        "normative_references": enriched,
        "normative_confidence": overall_confidence,
        "normative_warning": "  ".join(warnings),
        "normative_summary": summary,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve(
    norm_juris: str,
    norm_forum: str,
    norm_slug: str,
) -> tuple[list[dict] | None, str, str]:
    """
    Return (refs, match_type, used_jurisdiction).
    refs=None means no entry found at all (not even an empty list).
    """
    # 1. Direct jurisdiction + forum + slug
    result = _lookup(norm_juris, norm_forum, norm_slug)
    if result is not None:
        return result, "direct", norm_juris

    # 2. Nacional fallback + direct slug
    if norm_juris != "nacional":
        result = _lookup("nacional", norm_forum, norm_slug)
        if result is not None:
            return result, "direct", "nacional"

    # 3. Fallback slug (inferred) — same jurisdiction
    fallback_slug = _FALLBACK_SLUGS.get(norm_slug)
    if fallback_slug:
        result = _lookup(norm_juris, norm_forum, fallback_slug)
        if result is not None:
            return result, "inferred", norm_juris

        # 4. Fallback slug via nacional
        if norm_juris != "nacional":
            result = _lookup("nacional", norm_forum, fallback_slug)
            if result is not None:
                return result, "inferred", "nacional"

    return None, "", ""


def _lookup(juris: str, forum: str, slug: str) -> list[dict] | None:
    """Return the list for (juris, forum, slug), or None if key missing at any level."""
    forum_data = NORMATIVE_RULES.get(juris, {}).get(forum)
    if forum_data is None:
        return None
    if slug not in forum_data:
        return None
    return list(forum_data[slug])  # copy; may be []


def _enrich(rule: dict, match_type: str) -> dict:
    """Add match_type and confidence_score to a raw rule entry."""
    conf_label = rule.get("confidence", "low")
    score = {"high": 0.90, "medium": 0.70, "low": 0.45}.get(conf_label, 0.45)
    if match_type == "inferred":
        score = round(score * 0.75, 2)
        conf_label = _downgrade_confidence(conf_label)
    return {
        "source": rule["source"],
        "article": rule["article"],
        "label": rule["label"],
        "purpose": rule["purpose"],
        "match_type": match_type,
        "confidence_score": score,
    }


def _downgrade_confidence(label: str) -> str:
    order = ["high", "medium", "low"]
    idx = order.index(label) if label in order else 2
    return order[min(idx + 1, 2)]


def _aggregate_confidence(enriched: list[dict], match_type: str) -> str:
    if not enriched:
        return "low"
    best_score = max(r["confidence_score"] for r in enriched)
    if best_score >= 0.80:
        return "high"
    if best_score >= 0.55:
        return "medium"
    return "low"


def _build_summary(action_slug: str, refs: list[dict]) -> str:
    labels = {
        "traslado_demanda": "un traslado de demanda",
        "contestacion_demanda": "una contestación de demanda",
        "traslado": "un traslado procesal",
        "intimacion": "una intimación procesal",
        "vista": "una vista procesal",
        "apelacion": "un recurso de apelación",
        "expresion_agravios": "una expresión de agravios",
        "contestacion_agravios": "una contestación de agravios",
        "subsanacion": "una subsanación de presentación",
        "audiencia": "una audiencia",
        "comparecencia": "una comparecencia a audiencia",
        "plazo_para_contestar": "un traslado para contestar",
        "plazo_para_apelar": "una apelación",
        "plazo_para_subsanar": "una subsanación",
        "integracion_tribunal": "una integración de tribunal",
    }
    act_desc = labels.get(action_slug, f"el acto procesal '{action_slug}'")
    article_list = ", ".join(r["article"] for r in refs[:2])
    return (
        f"La notificación contiene un acto compatible con {act_desc}, "
        f"por lo que se sugiere como base normativa {article_list} "
        f"({refs[0]['source'].split('(')[0].strip()})."
    )


def _empty(warning: str) -> dict:
    return {
        "normative_references": [],
        "normative_confidence": "low",
        "normative_warning": warning,
        "normative_summary": None,
    }


def _normalize(text: str) -> str:
    """Lowercase + strip accents for stable key comparison."""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.casefold().strip()
