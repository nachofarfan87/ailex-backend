"""Detection of the predominant procedural action in a judicial notice."""

import re


_ACTION_RULES = [
    (
        "traslado de demanda",
        re.compile(r"\btraslado\b.*\bdemanda\b|\bc[oó]rrase traslado de la demanda\b", re.IGNORECASE),
        "traslado_demanda",
    ),
    (
        "intimacion",
        re.compile(r"\bint[ií]m(?:ese|ase|acion|ación)\b", re.IGNORECASE),
        "intimacion",
    ),
    (
        "vista",
        re.compile(r"\bd[ée]se vista\b|\bvista\b", re.IGNORECASE),
        "vista",
    ),
    (
        "audiencia",
        re.compile(r"\baudiencia\b|\bfijase audiencia\b|\bfijese audiencia\b", re.IGNORECASE),
        "audiencia",
    ),
    (
        "integracion del tribunal",
        re.compile(r"\bintegraci[oó]n\b.*\btribunal\b|\bintegra(?:se|ción)\b.*\bsala\b", re.IGNORECASE),
        "integracion_tribunal",
    ),
    (
        "traslado",
        re.compile(r"\bc[oó]rrase traslado\b|\btraslado\b", re.IGNORECASE),
        "traslado",
    ),
    (
        "providencia",
        re.compile(r"\bprovidencia\b|\bprove[ií]do\b|\bt[eé]ngase presente\b", re.IGNORECASE),
        "providencia",
    ),
    (
        "resolucion",
        re.compile(r"\bresoluci[oó]n\b|\bresu[eé]lvase\b", re.IGNORECASE),
        "resolucion",
    ),
]


def detect_procedural_action(text: str, detected_actions: list[dict] | None = None) -> dict:
    """Return the most relevant procedural action detected in the text."""
    normalized_text = text or ""
    best_match = None

    for label, pattern, slug in _ACTION_RULES:
        match = pattern.search(normalized_text)
        if match:
            best_match = {
                "label": label,
                "slug": slug,
                "matched_text": match.group(0).strip(),
                "confidence": 0.9 if slug in {"traslado_demanda", "intimacion", "audiencia"} else 0.75,
            }
            break

    if not best_match and detected_actions:
        for action in detected_actions:
            action_type = (action.get("tipo") or "").strip().lower()
            action_text = (action.get("texto") or "").strip()
            if not action_type and not action_text:
                continue
            mapped = _map_action_type(action_type, action_text)
            if mapped:
                best_match = mapped
                break

    if best_match:
        return best_match

    return {
        "label": "actuacion no determinada",
        "slug": "desconocida",
        "matched_text": "",
        "confidence": 0.25,
    }


def _map_action_type(action_type: str, action_text: str) -> dict | None:
    combined = f"{action_type} {action_text}".strip()
    for label, pattern, slug in _ACTION_RULES:
        if action_type == slug or pattern.search(combined):
            return {
                "label": label,
                "slug": slug,
                "matched_text": action_text or action_type,
                "confidence": 0.85,
            }
    return None
