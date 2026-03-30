"""Conversational Quality Layer — FASE 5.5

Pure text-quality module.  Does NOT change decisions, slots, memory, or
scoring.  It only improves *how* AILEX phrases questions and openings.

Public API
----------
- build_contextual_opening(conversation_memory, question_key) -> str
- simplify_question_text(raw_question, slot_key) -> str
- apply_conversational_style(raw_question, conversation_memory) -> str
"""

from __future__ import annotations

import hashlib
from typing import Any


# ---------------------------------------------------------------------------
# 1.  Opening variations  (clarification mode)
# ---------------------------------------------------------------------------
# Each group is selected based on conversation turn.  Within a group the
# specific line is chosen deterministically (hash of question_key) so the
# same opening is never repeated for consecutive *different* questions.

_FIRST_TURN_OPENINGS: tuple[str, ...] = (
    "Para orientarte mejor, necesito confirmar algo.",
    "Antes de darte una respuesta, necesito saber algo importante.",
    "Para poder ayudarte bien, hay un punto que necesito aclarar.",
    "Para darte una orientación más precisa, necesito un dato.",
    "Antes de avanzar, hay algo que necesito confirmar.",
    "Para empezar a orientarte, necesito saber algo primero.",
)

_CONTINUATION_OPENINGS: tuple[str, ...] = (
    "Con lo que me contás, falta definir algo importante.",
    "Bien, ahora necesito confirmar otro punto.",
    "Avanzando con tu consulta, necesito saber algo más.",
    "Siguiendo con lo que hablamos, hay otro dato clave.",
    "Con lo que ya sé, queda un punto por definir.",
    "Para seguir avanzando, necesito confirmar algo más.",
)

_LATE_TURN_OPENINGS: tuple[str, ...] = (
    "Ya tenemos bastante claro el panorama, pero falta un detalle.",
    "Estamos cerca de tener todo, solo necesito confirmar algo más.",
    "Con todo lo que me dijiste, queda un último punto.",
    "Casi tenemos todo cubierto, pero necesito un dato más.",
    "Solo me falta confirmar algo para completar el cuadro.",
    "Un dato más y ya puedo darte una orientación completa.",
)


def build_contextual_opening(
    conversation_memory: dict[str, Any] | None = None,
    question_key: str = "",
) -> str:
    """Return a varied, context-aware opening phrase.

    Selection logic:
    - Turn 1        → introductory tone
    - Turns 2-3     → continuation tone
    - Turns 4+      → late/closing tone

    Within each group, the specific line is picked deterministically via a
    hash of *question_key* + *turn* so that consecutive different questions
    never repeat the same opening, yet the result is stable (not random) for
    testing.

    Side-effect: writes ``_last_opening_idx`` back into *conversation_memory*
    so the next turn can avoid repeating the same opening.  This is
    consistent with how ``build_conversation_memory`` mutates the memory dict
    in place (e.g. ``memory["conversation_turns"] = …``).
    """
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

    # Avoid repeating the exact same opening as last turn
    if last_opening_idx is not None and idx == last_opening_idx and len(pool) > 1:
        idx = (idx + 1) % len(pool)

    # Persist the chosen index so the next turn can read it.
    if conversation_memory is not None:
        conversation_memory["_last_opening_idx"] = idx

    return pool[idx]


# ---------------------------------------------------------------------------
# 2.  Question simplification
# ---------------------------------------------------------------------------
# Maps slot keys to a simpler, more natural phrasing.  The original
# (juridically precise) text remains available as metadata if needed.

_SIMPLIFIED_QUESTIONS: dict[str, str] = {
    "aportes_actuales": "¿El otro padre o madre le pasa algo de plata actualmente?",
    "convivencia": "¿Tu hijo o hija vive con vos?",
    "notificacion": "¿Sabés dónde vive o cómo ubicar al otro padre o madre?",
    "ingresos": "¿Sabés si el otro padre o madre trabaja o tiene algún ingreso?",
    "urgencia": "¿Hay alguna necesidad urgente ahora mismo? Por ejemplo, salud, comida o educación.",
    "antecedentes": "¿Alguna vez ya hicieron un reclamo o acuerdo por este tema?",
}


def simplify_question_text(raw_question: str, slot_key: str = "") -> str:
    """Return a simpler, more natural version of *raw_question*.

    If a pre-built simplification exists for *slot_key*, use it.
    Otherwise return the original question unchanged.
    """
    if slot_key and slot_key in _SIMPLIFIED_QUESTIONS:
        return _SIMPLIFIED_QUESTIONS[slot_key]
    return raw_question


# ---------------------------------------------------------------------------
# 3.  Full conversational style wrapper
# ---------------------------------------------------------------------------

def apply_conversational_style(
    raw_question: str,
    conversation_memory: dict[str, Any] | None = None,
    *,
    slot_key: str = "",
    include_opening: bool = True,
) -> str:
    """Wrap *raw_question* with a contextual opening and simplified phrasing.

    Returns a ready-to-display string like:
        "Para orientarte mejor, necesito confirmar algo. ¿Tu hijo o hija vive con vos?"

    Parameters
    ----------
    raw_question : str
        The original question text (may be formal/technical).
    conversation_memory : dict | None
        Current conversation memory for turn-awareness.
    slot_key : str
        The slot key (e.g. "convivencia") for simplification lookup.
    include_opening : bool
        If False, skip the opening and return only the simplified question.
    """
    simplified = simplify_question_text(raw_question, slot_key)

    if not include_opening:
        return simplified

    opening = build_contextual_opening(conversation_memory, question_key=slot_key)
    return f"{opening} {simplified}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pick_index(pool: tuple[str, ...], key: str, turn: int) -> int:
    """Deterministic index selection based on key + turn."""
    seed = f"{key}:{turn}"
    digest = hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()
    return int(digest, 16) % len(pool)
