"""
AILEX -- Servicio de conversaciones persistentes.

Conversation organiza el hilo de chat.
Consulta sigue siendo el registro canonico del resultado juridico completo.
Message solo persiste la linea temporal del intercambio y referencia a Consulta
cuando el asistente produjo una respuesta juridica.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import json

from app.db.user_models import Consulta, Conversation, Expediente, Message
from app.services import consulta_service
from legal_engine.ailex_pipeline import AilexPipeline


_pipeline = AilexPipeline()


# Mapping materia → forum (matches practice areas used in the pipeline)
_MATERIA_TO_FORUM: dict[str, str] = {
    "civil":    "civil",
    "laboral":  "laboral",
    "familia":  "familia",
    "penal":    "penal",
    "comercial": "comercial",
    "administrativo": "contencioso_administrativo",
    "tributario": "tributario",
}


def _build_expediente_context(
    db: Session,
    conversation: Conversation,
) -> dict[str, Any]:
    """
    Load the linked Expediente (if any) and return a dict with fields
    useful for enriching the pipeline call.

    Returns an empty dict when the conversation has no expediente.
    """
    if not conversation.expediente_id:
        return {}

    expediente = db.get(Expediente, conversation.expediente_id)
    if expediente is None:
        return {}

    # Parse partes_json safely
    try:
        partes = json.loads(expediente.partes_json or "[]")
    except (ValueError, TypeError):
        partes = []

    return {
        "expediente_id": expediente.id,
        "jurisdiccion": (expediente.jurisdiccion or "").strip().lower() or None,
        "forum": _MATERIA_TO_FORUM.get((expediente.materia or "").strip().lower()),
        "materia": (expediente.materia or "").strip() or None,
        "tipo_caso": (expediente.tipo_caso or "").strip() or None,
        "subtipo_caso": (expediente.subtipo_caso or "").strip() or None,
        "estado_procesal": (expediente.estado_procesal or "").strip() or None,
        "hechos_relevantes": (expediente.hechos_relevantes or "").strip() or None,
        "pretension_principal": (expediente.pretension_principal or "").strip() or None,
        "riesgos_clave": (expediente.riesgos_clave or "").strip() or None,
        "caratula": (expediente.caratula or "").strip() or None,
        "partes": partes,
    }


def _auto_title(content: str, maxlen: int = 80) -> str:
    clean = str(content or "").strip().replace("\n", " ")
    if len(clean) <= maxlen:
        return clean
    return clean[:maxlen].rsplit(" ", 1)[0] + "..."


def _extract_response_summary(response_dict: dict[str, Any]) -> str:
    reasoning = response_dict.get("reasoning") or {}
    if isinstance(reasoning, dict):
        summary = reasoning.get("short_answer") or reasoning.get("case_analysis")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()

    generated = response_dict.get("generated_document")
    if isinstance(generated, str) and generated.strip():
        return generated.strip()[:400]

    query = response_dict.get("query")
    if isinstance(query, str) and query.strip():
        return query.strip()

    return "Respuesta juridica generada."


def _verify_expediente_ownership(
    db: Session,
    expediente_id: Optional[str],
    user_id: str,
) -> Optional[Expediente]:
    if not expediente_id:
        return None
    expediente = db.get(Expediente, expediente_id)
    if expediente is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expediente '{expediente_id}' no encontrado.",
        )
    if expediente.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para acceder a este expediente.",
        )
    return expediente


def get_conversation(
    db: Session,
    conversation_id: str,
    user_id: str,
) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversacion '{conversation_id}' no encontrada.",
        )
    if conversation.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para acceder a esta conversacion.",
        )
    return conversation


def create_conversation(
    db: Session,
    user_id: str,
    titulo: str = "",
    expediente_id: Optional[str] = None,
) -> Conversation:
    _verify_expediente_ownership(db, expediente_id, user_id)

    conversation = Conversation(
        user_id=user_id,
        expediente_id=expediente_id,
        titulo=titulo.strip(),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def send_message(
    db: Session,
    *,
    user_id: str,
    conversation_id: str,
    content: str,
    jurisdiction: Optional[str] = None,
    forum: Optional[str] = None,
    top_k: int = 5,
    document_mode: Optional[str] = None,
    facts: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    conversation = get_conversation(db, conversation_id, user_id)

    clean_content = str(content or "").strip()
    if not clean_content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El mensaje no puede estar vacio.",
        )

    # ── Enrich from expediente ──────────────────────────────────
    exp_ctx = _build_expediente_context(db, conversation)

    # Jurisdiction: caller > expediente > None (pipeline defaults to "jujuy")
    effective_jurisdiction = jurisdiction or exp_ctx.get("jurisdiccion")

    # Forum: caller > expediente mapping > None
    effective_forum = forum or exp_ctx.get("forum")

    # Facts: expediente hechos as base, caller facts override
    enriched_facts: dict[str, Any] = {}
    if exp_ctx.get("hechos_relevantes"):
        enriched_facts["hechos_relevantes"] = exp_ctx["hechos_relevantes"]
    if exp_ctx.get("pretension_principal"):
        enriched_facts["pretension_principal"] = exp_ctx["pretension_principal"]
    if exp_ctx.get("partes"):
        enriched_facts["partes"] = exp_ctx["partes"]
    enriched_facts.update(facts or {})

    # Metadata: inject expediente context for downstream engines
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault("conversation_id", conversation.id)
    if exp_ctx:
        payload_metadata["expediente_context"] = exp_ctx
    # ────────────────────────────────────────────────────────────

    user_message = Message(
        conversation_id=conversation.id,
        user_id=user_id,
        role="user",
        content=clean_content,
    )
    db.add(user_message)
    db.flush()

    result = _pipeline.run(
        query=clean_content,
        jurisdiction=effective_jurisdiction,
        forum=effective_forum,
        top_k=top_k,
        document_mode=document_mode,
        facts=enriched_facts,
        metadata=payload_metadata,
    )
    response_dict = result.to_dict()
    response_dict.setdefault("warnings", [])

    effective_jurisdiction = jurisdiction or response_dict.get("jurisdiction") or "jujuy"
    effective_forum = forum or response_dict.get("forum") or ""
    effective_document_mode = document_mode or ""

    consulta = consulta_service.save_consulta(
        db=db,
        user_id=user_id,
        query=clean_content,
        resultado=response_dict,
        jurisdiction=effective_jurisdiction,
        forum=effective_forum,
        document_mode=effective_document_mode,
        facts=enriched_facts,
        expediente_id=conversation.expediente_id,
        conversation_id=conversation.id,
        auto_commit=False,
    )

    assistant_message = Message(
        conversation_id=conversation.id,
        user_id=user_id,
        consulta_id=consulta.id,
        role="assistant",
        content=_extract_response_summary(response_dict),
    )
    db.add(assistant_message)

    if not conversation.titulo:
        conversation.titulo = _auto_title(clean_content)

    db.commit()
    db.refresh(conversation)
    db.refresh(consulta)
    db.refresh(user_message)
    db.refresh(assistant_message)

    return {
        "conversation": conversation,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "consulta": consulta,
    }


def get_history(
    db: Session,
    conversation_id: str,
    user_id: str,
) -> dict[str, Any]:
    conversation = get_conversation(db, conversation_id, user_id)

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    consultas = (
        db.query(Consulta)
        .filter(Consulta.conversation_id == conversation.id)
        .order_by(Consulta.created_at.asc())
        .all()
    )

    return {
        "conversation": conversation,
        "messages": messages,
        "consultas": consultas,
    }
