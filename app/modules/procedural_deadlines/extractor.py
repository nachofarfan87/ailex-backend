"""
AILEX — Detector básico de plazos procesales.
"""

import re

from app.modules.notifications.extractor import normalize_notification_text
from app.modules.procedural_deadlines.models import DeadlineDetection
from app.modules.procedural_deadlines.rules import classify_procedural_action


_DEADLINE_PATTERNS = [
    re.compile(
        r"\bc[oó]rrase traslado(?: de [^.,;\n]+?)?\s+por(?: el plazo de)?\s+"
        r"(?P<amount>[A-Za-záéíóúñ]+(?:\s*\(\s*\d+\s*\))?|\d+)\s+"
        r"(?P<unit>d[ií]as?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bint[ií]m(?:ese|ase)(?: a [^.,;\n]+?)?\s+(?:en|por|dentro de)\s+"
        r"(?P<amount>[A-Za-záéíóúñ]+(?:\s*\(\s*\d+\s*\))?|\d+)\s+"
        r"(?P<unit>d[ií]as?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:por|dentro de|en el plazo de)\s+"
        r"(?P<amount>[A-Za-záéíóúñ]+(?:\s*\(\s*\d+\s*\))?|\d+)\s+"
        r"(?P<unit>d[ií]as?)\b",
        re.IGNORECASE,
    ),
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


def detect_deadlines(text: str) -> list[DeadlineDetection]:
    """
    Detectar menciones simples de plazos procesales en notificaciones.

    No interpreta feriados, horas inhábiles ni reglas complejas.
    """
    normalized_text = normalize_notification_text(text)
    detections = []
    seen_spans = set()

    for pattern in _DEADLINE_PATTERNS:
        for match in pattern.finditer(normalized_text):
            span = (match.start(), match.end())
            if span in seen_spans:
                continue
            seen_spans.add(span)

            phrase = match.group(0).strip()
            plazo_dias = _parse_amount(match.group("amount"))
            unidad = _normalize_unit(match.group("unit"))
            tipo_actuacion = classify_procedural_action(phrase)
            confidence = 0.9 if tipo_actuacion else 0.65
            advertencias = []

            if plazo_dias is None:
                advertencias.append(
                    "No se pudo convertir con certeza la cantidad del plazo detectado."
                )
                confidence = min(confidence, 0.4)

            detections.append(
                DeadlineDetection(
                    tipo_actuacion=tipo_actuacion,
                    plazo_dias=plazo_dias,
                    unidad=unidad,
                    frase_detectada=phrase,
                    requiere_calculo=plazo_dias is not None and unidad == "dias",
                    advertencias=advertencias,
                    confianza=confidence,
                )
            )

    detections.sort(key=lambda item: normalized_text.find(item.frase_detectada))
    return _deduplicate_detections(detections)


def _parse_amount(raw_amount: str) -> int | None:
    digit_match = re.search(r"\d+", raw_amount)
    if digit_match:
        return int(digit_match.group(0))

    normalized = re.sub(r"\s+", " ", raw_amount.strip().casefold())
    return _NUMBER_WORDS.get(normalized)


def _normalize_unit(raw_unit: str) -> str:
    return "dias" if raw_unit.casefold().startswith("d") else raw_unit.casefold()


def _deduplicate_detections(
    detections: list[DeadlineDetection],
) -> list[DeadlineDetection]:
    detections = sorted(detections, key=lambda item: len(item.frase_detectada), reverse=True)
    unique = []

    for detection in detections:
        overlapped = False
        for saved in unique:
            same_deadline = (
                saved.plazo_dias == detection.plazo_dias
                and saved.unidad == detection.unidad
                and detection.frase_detectada.casefold() in saved.frase_detectada.casefold()
            )
            same_or_better_type = (
                saved.tipo_actuacion == detection.tipo_actuacion
                or (saved.tipo_actuacion and not detection.tipo_actuacion)
            )
            if same_deadline and same_or_better_type:
                overlapped = True
                break
        if overlapped:
            continue

        unique.append(detection)

    unique.sort(key=lambda item: item.frase_detectada.casefold())
    return unique
