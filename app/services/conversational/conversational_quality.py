"""Conversational Quality Layer - FASE 5.5

Pure text-quality module. Does NOT change decisions, slots, memory, or
scoring. It only improves how AILEX phrases questions and openings.

Public API
----------
- build_contextual_opening(conversation_memory, question_key) -> str
- simplify_question_text(raw_question, slot_key) -> str
- apply_conversational_style(raw_question, conversation_memory) -> str
"""

from __future__ import annotations

import hashlib
from typing import Any


_FIRST_TURN_OPENINGS: tuple[str, ...] = (
    "Para orientarte mejor, necesito confirmar algo.",
    "Antes de darte una respuesta, necesito saber algo importante.",
    "Para poder ayudarte bien, hay un punto que necesito aclarar.",
    "Para darte una orientacion mas precisa, necesito un dato.",
    "Antes de avanzar, hay algo que necesito confirmar.",
    "Para empezar a orientarte, necesito saber algo primero.",
)

_CONTINUATION_OPENINGS: tuple[str, ...] = (
    "Con lo que me contas, falta definir algo importante.",
    "Bien, ahora necesito confirmar otro punto.",
    "Avanzando con tu consulta, necesito saber algo mas.",
    "Siguiendo con lo que hablamos, hay otro dato clave.",
    "Con lo que ya se, queda un punto por definir.",
    "Para seguir avanzando, necesito confirmar algo mas.",
)

_LATE_TURN_OPENINGS: tuple[str, ...] = (
    "Ya tenemos bastante claro el panorama, pero falta un detalle.",
    "Estamos cerca de tener todo, solo necesito confirmar algo mas.",
    "Con todo lo que me dijiste, queda un ultimo punto.",
    "Casi tenemos todo cubierto, pero necesito un dato mas.",
    "Solo me falta confirmar algo para completar el cuadro.",
    "Un dato mas y ya puedo darte una orientacion completa.",
)


def build_contextual_opening(
    conversation_memory: dict[str, Any] | None = None,
    question_key: str = "",
) -> str:
    """Return a varied, context-aware opening phrase."""
    memory = conversation_memory if conversation_memory is not None else {}
    turns = int(memory.get("conversation_turns") or 0)
    last_opening_idx = memory.get("_last_opening_idx")

    if turns <= 1:
        pool = _FIRST_TURN_OPENINGS
    elif turns <= 3:
        pool = _CONTINUATION_OPENINGS
    else:
        pool = _LATE_TURN_OPENINGS

    idx = _pick_index(pool, question_key, turns)
    if last_opening_idx is not None and idx == last_opening_idx and len(pool) > 1:
        idx = (idx + 1) % len(pool)

    if conversation_memory is not None:
        conversation_memory["_last_opening_idx"] = idx

    return pool[idx]


_SIMPLIFIED_QUESTIONS: dict[str, str] = {
    "aportes_actuales": "El otro padre o madre le pasa algo de plata actualmente?",
    "convivencia": "Tu hijo o hija vive con vos?",
    "notificacion": "Sabes donde vive o como ubicar al otro padre o madre?",
    "ingresos": "Sabes si el otro padre o madre trabaja o tiene algun ingreso?",
    "urgencia": "Hay alguna necesidad urgente ahora mismo? Por ejemplo, salud, comida o educacion.",
    "antecedentes": "Alguna vez ya hicieron un reclamo o acuerdo por este tema?",
    "divorcio_modalidad": "El divorcio va a ser de comun acuerdo o unilateral?",
    "hay_hijos": "Hay hijos menores o con capacidad restringida?",
    "hay_acuerdo": "Ya hay acuerdo entre ustedes sobre lo principal?",
    "cese_convivencia": "Ya dejaron de convivir?",
    "hay_bienes": "Hay bienes para ordenar en el divorcio?",
    "vivienda_familiar": "Hay una vivienda familiar que haya que resolver?",
    "rol_procesal": "Consultas por tu parte, por la otra parte o como profesional?",
    "situacion_economica": "Como es hoy la situacion economica de cada parte?",
    "hay_ingresos": "Hay ingresos identificables de la otra parte?",
}


def simplify_question_text(raw_question: str, slot_key: str = "") -> str:
    """Return a simpler, more natural version of *raw_question*."""
    if slot_key and slot_key in _SIMPLIFIED_QUESTIONS:
        simplified = _SIMPLIFIED_QUESTIONS[slot_key].strip()
        return f"¿{simplified}" if not simplified.startswith("¿") else simplified
    return raw_question


def apply_conversational_style(
    raw_question: str,
    conversation_memory: dict[str, Any] | None = None,
    *,
    slot_key: str = "",
    include_opening: bool = True,
) -> str:
    """Wrap *raw_question* with a contextual opening and simplified phrasing."""
    simplified = simplify_question_text(raw_question, slot_key)
    if not include_opening:
        return simplified

    opening = build_contextual_opening(conversation_memory, question_key=slot_key)
    return f"{opening} {simplified}"


def _pick_index(pool: tuple[str, ...], key: str, turn: int) -> int:
    seed = f"{key}:{turn}"
    digest = hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()
    return int(digest, 16) % len(pool)
