"""
AILEX -- Output cleanup utilities

Normaliza y deduplica listas textuales del pipeline juridico para reducir
redundancias leves sin eliminar informacion materialmente distinta.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


_NEGATIVE_PREFIXES = (
    "no se informa sobre ",
    "no se indica ",
    "no se indica si ",
    "no se informa si ",
    "falta precisar ",
    "falta identificar ",
    "falta determinar ",
    "falta aclarar ",
)

_NEUTRAL_PREFIXES = (
    "existencia de ",
    "determinacion sobre ",
    "acuerdo sobre ",
    "situacion de ",
    "situacion del ",
    "situacion patrimonial de ",
)

_STOPWORDS = {
    "de",
    "del",
    "la",
    "las",
    "el",
    "los",
    "y",
    "o",
    "u",
    "si",
    "se",
    "no",
    "sobre",
    "con",
    "sin",
    "en",
    "por",
    "para",
    "a",
    "al",
    "lo",
    "que",
    "su",
    "sus",
    "un",
    "una",
    "unos",
    "unas",
    "eventual",
    "corresponde",
    "hubiere",
}

_TOPIC_SYNONYMS = {
    "hijos": "children",
    "hijo": "children",
    "menores": "children",
    "menor": "children",
    "parentalidad": "children",
    "comunicacion": "children",
    "cuidado": "children",
    "gananciales": "assets",
    "ganancial": "assets",
    "bienes": "assets",
    "bien": "assets",
    "patrimonial": "assets",
    "patrimonio": "assets",
    "deudas": "assets",
    "deuda": "assets",
    "vivienda": "housing",
    "hogar": "housing",
    "domicilio": "jurisdiction",
    "competencia": "jurisdiction",
    "juzgado": "jurisdiction",
    "alimentos": "support",
    "alimento": "support",
    "alimentaria": "support",
    "cuota": "support",
    "compensacion": "compensation",
    "desequilibrio": "compensation",
    "reguladora": "agreement",
    "convenio": "agreement",
    "propuesta": "agreement",
    "matrimonio": "marriage",
    "matrimonial": "marriage",
    "fecha": "timing",
    "plazo": "timing",
    "documentacion": "documents",
    "prueba": "documents",
    "expediente": "documents",
}


@dataclass
class _NormalizedItem:
    original: str
    canonical: str
    tokens: set[str]
    topics: set[str]
    score: tuple[int, int, int, int]


def normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(text or "").strip())
    no_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    collapsed = re.sub(r"\s+", " ", no_accents)
    return collapsed.strip()


def cleanup_text_list(items: Iterable[str], item_type: str = "generic") -> list[str]:
    normalized_items: list[_NormalizedItem] = []

    for raw in items:
        text = _clean_display_text(str(raw))
        if not text:
            continue
        candidate = _build_normalized_item(text, item_type)
        duplicate_index = _find_duplicate_index(candidate, normalized_items, item_type)
        if duplicate_index is None:
            normalized_items.append(candidate)
            continue

        current = normalized_items[duplicate_index]
        if candidate.score > current.score:
            normalized_items[duplicate_index] = candidate

    return [_finalize_display_text(item.original) for item in normalized_items]


def _build_normalized_item(text: str, item_type: str) -> _NormalizedItem:
    canonical = _canonicalize(text, item_type)
    tokens = _tokenize(canonical)
    topics = _extract_topics(tokens)
    score = _score_text(text, canonical, topics)
    return _NormalizedItem(
        original=text,
        canonical=canonical,
        tokens=tokens,
        topics=topics,
        score=score,
    )


def _clean_display_text(text: str) -> str:
    cleaned = normalize_text(text).strip(" .")
    return cleaned


def _finalize_display_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    return cleaned[:1].upper() + cleaned[1:] + ("" if cleaned.endswith(".") else ".")


def _canonicalize(text: str, item_type: str) -> str:
    lowered = normalize_text(text).casefold().strip(" .")
    lowered = re.sub(r"^(riesgo identificado:\s*)", "", lowered)
    for prefix in _NEGATIVE_PREFIXES:
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):]
            break
    for prefix in _NEUTRAL_PREFIXES:
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):]
            break

    replacements = {
        " de divorcio": "" if item_type == "risk" else " de divorcio",
        " o propios en comun": "",
        " o propios en común": "",
        " situacion patrimonial": " bienes patrimoniales",
        " bienes comunes": " bienes gananciales",
        " ultimo domicilio conyugal": " domicilio conyugal",
        " domicilio actual de las partes": " domicilio de las partes",
        " con capacidad restringida": " con capacidad restringida",
        " para hijos": " para hijos",
    }
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)

    lowered = re.sub(r"\s+", " ", lowered).strip(" .")
    return lowered


def _tokenize(text: str) -> set[str]:
    parts = re.findall(r"[a-z0-9]+", text)
    return {part for part in parts if part not in _STOPWORDS}


def _extract_topics(tokens: set[str]) -> set[str]:
    topics = set()
    for token in tokens:
        topic = _TOPIC_SYNONYMS.get(token)
        if topic:
            topics.add(topic)
    return topics


def _score_text(original: str, canonical: str, topics: set[str]) -> tuple[int, int, int, int]:
    lowered = normalize_text(original).casefold()
    negative = any(lowered.startswith(prefix) for prefix in _NEGATIVE_PREFIXES)
    neutral = any(lowered.startswith(prefix) for prefix in _NEUTRAL_PREFIXES)
    return (
        0 if negative else 1,
        0 if neutral else 1,
        len(topics),
        len(canonical),
    )


def _find_duplicate_index(
    candidate: _NormalizedItem,
    existing: list[_NormalizedItem],
    item_type: str,
) -> int | None:
    for index, item in enumerate(existing):
        if _is_duplicate(candidate, item, item_type):
            return index
    return None


def _is_duplicate(left: _NormalizedItem, right: _NormalizedItem, item_type: str) -> bool:
    if not left.tokens or not right.tokens:
        return left.canonical == right.canonical

    if left.canonical == right.canonical:
        return True

    shared_topics = left.topics & right.topics
    overlap = _token_overlap(left.tokens, right.tokens)

    if shared_topics and overlap >= 0.45:
        return True

    if left.topics and right.topics:
        if left.topics == right.topics and overlap >= 0.34:
            return True
        if item_type == "missing_info":
            if (left.topics <= right.topics or right.topics <= left.topics) and overlap >= 0.2:
                return True

    return False


def _token_overlap(left: set[str], right: set[str]) -> float:
    intersection = len(left & right)
    minimum = min(len(left), len(right))
    if minimum == 0:
        return 0.0
    return intersection / minimum
