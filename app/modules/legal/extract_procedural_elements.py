"""Structured extraction of procedural elements from judicial notices."""

import re

from app.modules.legal.detect_procedural_action import detect_procedural_action
from app.modules.notifications.extractor import extract_notification_structure


_DOCUMENT_TYPE_RULES = [
    ("cedula judicial", re.compile(r"\bc[eé]dula\b", re.IGNORECASE)),
    ("providencia", re.compile(r"\bprovidencia\b|\bprove[ií]do\b", re.IGNORECASE)),
    ("resolucion", re.compile(r"\bresoluci[oó]n\b", re.IGNORECASE)),
    ("traslado", re.compile(r"\btraslado\b", re.IGNORECASE)),
    ("intimacion", re.compile(r"\bintimaci[oó]n\b|\bint[ií]m(?:ese|ase)\b", re.IGNORECASE)),
    ("vista", re.compile(r"\bvista\b", re.IGNORECASE)),
    ("audiencia", re.compile(r"\baudiencia\b", re.IGNORECASE)),
    ("notificacion judicial", re.compile(r"\bnotif[ií]quese\b|\bnotificaci[oó]n\b", re.IGNORECASE)),
]

_AUDIENCIA_DATE_PATTERNS = [
    re.compile(
        r"\baudiencia\b.*?\b(?:para el d[ií]a|el d[ií]a|fijada para el d[ií]a)\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\baudiencia\b.*?\b(?:para el d[ií]a|el d[ií]a|fijada para el d[ií]a)\s+(\d{1,2}\s+de\s+[A-Za-záéíóúñ]+\s+de\s+\d{4})",
        re.IGNORECASE,
    ),
]


def extract_procedural_elements(text: str) -> dict:
    """Extract the procedural elements required by the notification workflow."""
    structure = extract_notification_structure(text)
    normalized_text = structure.get("texto_normalizado", "")
    procedural_action = detect_procedural_action(
        normalized_text,
        detected_actions=structure.get("actuaciones_detectadas", []),
    )

    return {
        "document_detected": _detect_document_type(normalized_text, procedural_action["slug"]),
        "court": structure.get("organo") or "",
        "case_number": structure.get("expediente") or "",
        "notification_date": structure.get("fecha") or "",
        "hearing_date": _extract_hearing_date(normalized_text),
        "procedural_action": procedural_action["label"],
        "procedural_action_slug": procedural_action["slug"],
        "procedural_action_match": procedural_action["matched_text"],
        "procedural_action_confidence": procedural_action["confidence"],
        "raw_actions": structure.get("actuaciones_detectadas", []),
        "raw_deadlines": structure.get("plazos_detectados", []),
        "normalized_text": normalized_text,
    }


def _detect_document_type(text: str, action_slug: str) -> str:
    for label, pattern in _DOCUMENT_TYPE_RULES:
        if pattern.search(text):
            return label

    if action_slug == "integracion_tribunal":
        return "notificacion de integracion del tribunal"
    if action_slug == "desconocida":
        return "documento judicial no determinado"
    return "notificacion judicial"


def _extract_hearing_date(text: str) -> str:
    for pattern in _AUDIENCIA_DATE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(1).strip()
    return ""
