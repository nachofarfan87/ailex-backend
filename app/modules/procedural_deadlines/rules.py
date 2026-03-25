"""
AILEX — Reglas simples para clasificar actos procesales con plazo.
"""

import re


_RULES: list[tuple[str, re.Pattern]] = [
    (
        "plazo_para_contestar",
        re.compile(r"\bcontest(?:ar|e|ación)\b.*\bdemanda\b|\btraslado de la demanda\b", re.IGNORECASE),
    ),
    (
        "plazo_para_apelar",
        re.compile(r"\bapelar\b|\bapelaci[oó]n\b|\brecurso\b", re.IGNORECASE),
    ),
    (
        "plazo_para_subsanar",
        re.compile(r"\bsubsan(?:ar|e|ación)\b|\baclar(?:ar|e)\b|\bcompletar\b", re.IGNORECASE),
    ),
    (
        "intimacion",
        re.compile(r"\bint[ií]m(?:ese|ase|ación)\b", re.IGNORECASE),
    ),
    (
        "vista",
        re.compile(r"\bd[ée]se vista\b|\bvista\b", re.IGNORECASE),
    ),
    (
        "traslado",
        re.compile(r"\bc[oó]rrase traslado\b|\btraslado\b", re.IGNORECASE),
    ),
]


def classify_procedural_action(text: str) -> str | None:
    """Clasificar el acto procesal predominante en una frase de plazo."""
    if not text:
        return None

    for action_type, pattern in _RULES:
        if pattern.search(text):
            return action_type
    return None
