from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.conversational.conversational_quality import simplify_question_text
from app.services.conversational.question_selector import (
    build_primary_question_for_alimentos,
    select_primary_question_for_alimentos,
)


def build_alimentos_playbook(context: dict[str, Any]) -> dict[str, Any]:
    known_facts = dict(context.get("known_facts") or {})
    missing_facts = [str(item).strip() for item in (context.get("missing_facts") or []) if str(item or "").strip()]
    query_text = str(context.get("query_text") or "").strip()
    clarification_context = dict(context.get("clarification_context") or {})
    conversation_memory = dict(context.get("conversation_memory") or {})

    primary_question = select_primary_question_for_alimentos(
        known_facts=known_facts,
        missing_facts=missing_facts,
        query_text=query_text,
        clarification_context=clarification_context,
        conversation_memory=conversation_memory,
    )
    question_selection = build_primary_question_for_alimentos(
        {
            "known_facts": known_facts,
            "missing_facts": missing_facts,
            "query_text": query_text,
            "clarification_context": clarification_context,
            "conversation_memory": conversation_memory,
        }
    )

    # Fase 5.5: simplify the question shown to the user.
    slot_key = ""
    if question_selection:
        slot_key = str((question_selection.get("selected") or {}).get("key") or "")
    if primary_question and slot_key:
        primary_question = simplify_question_text(primary_question, slot_key)

    conversation_turns = int(conversation_memory.get("conversation_turns") or 0)
    resolved_slots = set(conversation_memory.get("resolved_slots") or [])
    messages = _build_messages(
        query_text=query_text,
        known_facts=known_facts,
        conversation_turns=conversation_turns,
        resolved_slots=resolved_slots,
        primary_question=primary_question,
    )

    return {
        "mode": "guided_answer",
        "domain": "alimentos",
        "messages": messages,
        "primary_question": primary_question,
        "question_selection": question_selection or {},
        "conversation_memory": conversation_memory,
    }


def _build_initial_orientation(query_text: str) -> str:
    normalized = _normalize_text(query_text)
    if "demanda de alimentos" in normalized or "iniciar" in normalized or "reclamo" in normalized:
        child_phrase = _detect_child_phrase(query_text)
        if child_phrase:
            return f"Sí, podés iniciar un reclamo de alimentos por {child_phrase}."
        return "Sí, podés iniciar un reclamo de alimentos."
    if re.search(r"\bno paga\b|\bno aporta\b|\bdejo de pagar\b|\bno me pasa plata\b|\bno cumple\b", normalized):
        return "Sí, podés reclamar alimentos cuando el otro progenitor dejó de pagar o no está cumpliendo de manera suficiente."
    return "Sí, podés reclamar una cuota alimentaria para tu hija o hijo."


def _build_documents_message(query_text: str) -> str:
    child_phrase = _detect_child_phrase(query_text)
    if child_phrase:
        return (
            f"Para avanzar, normalmente se necesita DNI, partida de nacimiento, datos del otro progenitor y comprobantes "
            f"de gastos habituales de {child_phrase}."
        )
    return (
        "Para avanzar, normalmente se necesita DNI, partida de nacimiento, datos del otro progenitor y comprobantes "
        "de gastos habituales del hijo o hija."
    )


def _detect_child_phrase(query_text: str) -> str:
    lowered = str(query_text or "").strip()
    match = re.search(r"\b(mi hija|mi hijo|mis hijas|mis hijos)\b", lowered, flags=re.IGNORECASE)
    if match:
        return match.group(1).lower()
    if re.search(r"\bhija\b", lowered, flags=re.IGNORECASE):
        return "tu hija"
    if re.search(r"\bhijo\b", lowered, flags=re.IGNORECASE):
        return "tu hijo"
    return ""


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def _build_messages(
    *,
    query_text: str,
    known_facts: dict,
    conversation_turns: int,
    resolved_slots: set,
    primary_question: str | None,
) -> list[dict]:
    """
    Build the message list adapted to conversation state.

    Turn 0 (first contact): full orientation block.
    Turn 1+: skip already-given orientation, lead with what's known and what's next.
    """
    messages: list[dict] = []

    if conversation_turns == 0:
        # First turn: full orientation
        messages.append({"type": "info", "text": _build_initial_orientation(query_text)})
        messages.append({
            "type": "info",
            "text": "Es un derecho de tu hija o hijo, incluso si el otro progenitor está aportando poco o de forma irregular.",
        })
        messages.append({
            "type": "practical",
            "text": "Podés iniciarlo en el juzgado de familia o, si hoy no tenés abogado, pedir orientación en la defensoría.",
        })
        messages.append({
            "type": "practical",
            "text": "También podés pedir una cuota provisoria para no esperar al final del proceso.",
        })
        messages.append({"type": "focus", "text": _build_documents_message(query_text)})
    else:
        # Follow-up turns: acknowledge what was learned, skip base orientation
        ack = _build_acknowledgement(known_facts, resolved_slots, conversation_turns)
        if ack:
            messages.append({"type": "info", "text": ack})
        progress = _build_progress_message(known_facts, resolved_slots)
        if progress:
            messages.append({"type": "focus", "text": progress})

    if primary_question:
        messages.append({"type": "question", "text": primary_question})

    return messages


def _build_acknowledgement(known_facts: dict, resolved_slots: set, turn: int) -> str:
    """Generate a short acknowledgement based on what the user just revealed."""
    convivencia = known_facts.get("convivencia")
    aportes = known_facts.get("aportes_actuales")

    if convivencia is True:
        return "Bien, con el hijo o hija viviendo con vos tenés legitimación directa para reclamar."
    if convivencia is False:
        return "Entendido. Vamos a necesitar determinar quién ejerce la guarda para encuadrar el reclamo."
    if aportes is False:
        return "Con eso confirmado, el incumplimiento refuerza la urgencia del reclamo."
    if aportes is True:
        return "Bien. Aunque haya aportes parciales, podés reclamar la cuota completa que le corresponde."
    if len(resolved_slots) >= 3:
        return "Con lo que me contaste ya tenemos una base sólida para avanzar."
    if turn == 1:
        return "Gracias por la información. Necesito confirmar algunos datos más."
    return "Bien. Sigamos construyendo el caso."


def _build_progress_message(known_facts: dict, resolved_slots: set) -> str:
    """Surface what we know so far when there's something meaningful to show."""
    if not resolved_slots:
        return ""
    items = []
    if "convivencia" in resolved_slots:
        val = known_facts.get("convivencia")
        items.append("Convivencia: " + ("sí" if val else "no confirmada"))
    if "aportes_actuales" in resolved_slots:
        val = known_facts.get("aportes_actuales")
        items.append("Aportes actuales: " + ("sí" if val else "incumplimiento"))
    if "ingresos" in resolved_slots:
        items.append("Situación laboral del otro progenitor: registrada")
    if not items:
        return ""
    return "Lo que ya tenemos: " + " · ".join(items) + "."
