from __future__ import annotations

import re
import unicodedata
from typing import Any

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

    messages = [
        {
            "type": "info",
            "text": _build_initial_orientation(query_text),
        },
        {
            "type": "info",
            "text": "Es un derecho de tu hija o hijo, incluso si el otro progenitor está aportando poco o de forma irregular.",
        },
        {
            "type": "practical",
            "text": "Podés iniciarlo en el juzgado de familia o, si hoy no tenés abogado, pedir orientación en la defensoría.",
        },
        {
            "type": "practical",
            "text": "También podés pedir una cuota provisoria para no esperar al final del proceso.",
        },
        {
            "type": "focus",
            "text": _build_documents_message(query_text),
        },
    ]

    if primary_question:
        messages.append({"type": "question", "text": primary_question})

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
