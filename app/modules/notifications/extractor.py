"""
AILEX — Extractor de notificaciones judiciales.

Normaliza texto de notificaciones y extrae datos básicos
con regex simples y estructura trazable.
"""

import re


_HEADER_LINE = re.compile(
    r"(juzgado|tribunal|c[aá]mara|camara|sala|secretar[ií]a|poder judicial|expte)",
    re.IGNORECASE,
)

_EXPEDIENTE_PATTERNS = [
    re.compile(
        r"\bExp(?:te|ediente)\.?\s*(?:[Nn](?:[°ºo.]|\s)*)?([A-Za-z0-9.\-\/]+)",
        re.IGNORECASE,
    ),
]

_PARTES_PATTERNS = [
    re.compile(
        r'"([^"\n]{3,120}?\s+c\/\s+[^"\n]{3,120}?(?:\s+s\/\s+[^"\n]{3,120})?)"',
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([A-ZÁÉÍÓÚÑ][^,\n]{2,120}?\s+c\/\s+[^,\n]{2,120}?(?:\s+s\/\s+[^,\n]{2,120})?)",
        re.IGNORECASE,
    ),
]

_ORGANO_PATTERN = re.compile(
    r"(?im)^(.*(?:juzgado|tribunal|c[aá]mara|camara|sala|secretar[ií]a).*)$"
)

_DATE_PATTERNS = [
    re.compile(
        r"\b(\d{1,2}\s+de\s+[A-Za-záéíóúñ]+\s+de\s+\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b"),
]

_ACTION_PATTERNS = {
    "traslado": re.compile(r"\b(?:c[oó]rrase\s+)?traslado\b", re.IGNORECASE),
    "intimacion": re.compile(r"\bint[ií]m[ea]se?\b|\bintimaci[oó]n\b", re.IGNORECASE),
    "vista": re.compile(r"\bd[ée]se\s+vista\b|\bvista\b", re.IGNORECASE),
    "proveido": re.compile(r"\bprove[ií]do\b", re.IGNORECASE),
    "resolucion": re.compile(r"\bresoluci[oó]n\b|\bresu[eé]lvase\b", re.IGNORECASE),
    "apercibimiento": re.compile(r"\bapercibimiento\b", re.IGNORECASE),
    "tengase_presente": re.compile(r"\bt[eé]ngase\s+presente\b", re.IGNORECASE),
}

_PLAZO_PATTERNS = [
    re.compile(
        r"\b(?:por|en el plazo de|dentro del plazo de|plazo de)\s+"
        r"((?:[A-Za-záéíóúñ]+(?:\s*\(\s*\d+\s*\))?)|\d+)\s+"
        r"(d[ií]as?|horas?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d+)\s+(d[ií]as?|horas?)\b", re.IGNORECASE),
]

_NUMBER_WORDS = {
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "veinte": 20,
    "treinta": 30,
}


def normalize_notification_text(text: str) -> str:
    """
    Limpiar texto de notificación preservando estructura legible.

    - normaliza espacios
    - elimina líneas de encabezado repetidas
    - conserva separaciones entre bloques
    """
    if not text:
        return ""

    raw_text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines = []
    seen_headers = set()

    for line in raw_text.split("\n"):
        normalized_line = re.sub(r"[ \t]+", " ", line).strip()

        if not normalized_line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        header_key = normalized_line.casefold()
        if _looks_like_header(normalized_line):
            if header_key in seen_headers:
                continue
            seen_headers.add(header_key)

        if cleaned_lines and cleaned_lines[-1] == normalized_line:
            continue

        cleaned_lines.append(normalized_line)

    normalized_text = "\n".join(cleaned_lines)
    normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
    return normalized_text.strip()


def extract_basic_entities(text: str) -> dict:
    """Extraer entidades básicas de una notificación judicial."""
    normalized_text = normalize_notification_text(text)
    plazos = _extract_deadlines(normalized_text)
    actuaciones = detect_procedural_actions(normalized_text)

    return {
        "expediente": _search_first(_EXPEDIENTE_PATTERNS, normalized_text),
        "partes": _extract_partes(normalized_text),
        "organo": _extract_organo(normalized_text),
        "fecha": _search_first(_DATE_PATTERNS, normalized_text),
        "plazo_mencionado": plazos[0]["texto"] if plazos else None,
        "tipo_actuacion": actuaciones[0]["tipo"] if actuaciones else None,
    }


def detect_procedural_actions(text: str) -> list[dict]:
    """Detectar actuaciones procesales con palabras clave simples."""
    normalized_text = normalize_notification_text(text)
    detected = []
    seen = set()

    for action_type, pattern in _ACTION_PATTERNS.items():
        for match in pattern.finditer(normalized_text):
            key = (action_type, match.group(0).casefold())
            if key in seen:
                continue
            seen.add(key)
            detected.append(
                {
                    "tipo": action_type,
                    "texto": match.group(0).strip(),
                    "contexto": _extract_context(
                        normalized_text,
                        match.start(),
                        match.end(),
                    ),
                }
            )

    detected.sort(
        key=lambda item: normalized_text.casefold().find(item["texto"].casefold())
    )
    return detected


def extract_notification_structure(text: str) -> dict:
    """Construir una vista estructurada de la notificación."""
    normalized_text = normalize_notification_text(text)
    entities = extract_basic_entities(normalized_text)

    return {
        "expediente": entities["expediente"],
        "partes": entities["partes"],
        "organo": entities["organo"],
        "fecha": entities["fecha"],
        "actuaciones_detectadas": detect_procedural_actions(normalized_text),
        "plazos_detectados": _extract_deadlines(normalized_text),
        "texto_normalizado": normalized_text,
    }


def _looks_like_header(line: str) -> bool:
    return bool(_HEADER_LINE.search(line)) and (
        line.isupper() or len(line) <= 120
    )


def _search_first(patterns: list[re.Pattern], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _extract_partes(text: str) -> str | None:
    for pattern in _PARTES_PATTERNS:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" \"")
    return None


def _extract_organo(text: str) -> str | None:
    match = _ORGANO_PATTERN.search(text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _extract_context(text: str, start: int, end: int, window: int = 50) -> str:
    snippet = text[max(0, start - window): min(len(text), end + window)]
    return re.sub(r"\s+", " ", snippet).strip()


def _extract_deadlines(text: str) -> list[dict]:
    collected = []

    for pattern in _PLAZO_PATTERNS:
        for match in pattern.finditer(text):
            quantity = match.group(1).strip()
            unit = match.group(2).strip().lower()
            raw_text = match.group(0).strip()
            numeric_value = _parse_quantity(quantity)
            collected.append(
                {
                    "texto": raw_text,
                    "cantidad": numeric_value,
                    "unidad": unit,
                    "_start": match.start(),
                    "_end": match.end(),
                }
            )

    collected.sort(key=lambda item: (item["_start"], -(item["_end"] - item["_start"])))

    deadlines = []
    for item in collected:
        overlapped = False
        for saved in deadlines:
            same_value = (
                saved["cantidad"] == item["cantidad"]
                and saved["unidad"] == item["unidad"]
            )
            contained = (
                item["_start"] >= saved["_start"] and item["_end"] <= saved["_end"]
            )
            if same_value and contained:
                overlapped = True
                break
        if not overlapped:
            deadlines.append(item)

    for item in deadlines:
        item.pop("_start", None)
        item.pop("_end", None)
    return deadlines


def _parse_quantity(raw_value: str) -> int | None:
    digit_match = re.search(r"\d+", raw_value)
    if digit_match:
        return int(digit_match.group(0))

    normalized = raw_value.strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return _NUMBER_WORDS.get(normalized)
