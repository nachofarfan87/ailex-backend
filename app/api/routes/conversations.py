"""
AILEX -- Endpoints de conversaciones y mensajes persistentes.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import Consulta, Conversation, Message, User
from app.services import conversation_service

router = APIRouter(prefix="/api/conversations", tags=["Conversations"])


class ConversationCreateRequest(BaseModel):
    titulo: str = Field(default="", max_length=255)
    expediente_id: Optional[str] = None


class MessageSendRequest(BaseModel):
    content: str = Field(..., min_length=1)
    jurisdiction: Optional[str] = None
    forum: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    document_mode: Optional[str] = None
    facts: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationOut(BaseModel):
    id: str
    user_id: str
    expediente_id: Optional[str] = None
    titulo: str
    message_count: int = 0
    consulta_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConsultaOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    expediente_id: Optional[str] = None
    conversation_id: Optional[str] = None
    titulo: str
    query: str
    jurisdiction: str
    forum: str
    document_mode: str
    confidence: Optional[float] = None
    notas: str
    created_at: Optional[str] = None
    resultado: dict[str, Any] = Field(default_factory=dict)
    warnings: list[Any] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    generated_document: str = ""


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    user_id: str
    consulta_id: Optional[str] = None
    role: str
    content: str
    created_at: Optional[str] = None
    consulta: Optional[ConsultaOut] = None


class ConversationCreateResponse(BaseModel):
    conversation: ConversationOut


class MessageSendResponse(BaseModel):
    conversation: ConversationOut
    user_message: MessageOut
    assistant_message: MessageOut
    consulta: ConsultaOut


class ConversationHistoryResponse(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    consultas: list[ConsultaOut]


def _to_conversation_out(conversation: Conversation) -> ConversationOut:
    payload = conversation.to_dict(include_counts=True)
    return ConversationOut(**payload)


def _to_consulta_out(consulta: Consulta) -> ConsultaOut:
    return ConsultaOut(**consulta.to_dict(include_resultado=True))


def _to_message_out(message: Message) -> MessageOut:
    consulta_payload = _to_consulta_out(message.consulta) if message.consulta else None
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        user_id=message.user_id,
        consulta_id=message.consulta_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at.isoformat() if message.created_at else None,
        consulta=consulta_payload,
    )


@router.post(
    "",
    response_model=ConversationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una conversacion",
)
def create_conversation(
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationCreateResponse:
    conversation = conversation_service.create_conversation(
        db=db,
        user_id=user.id,
        titulo=payload.titulo,
        expediente_id=payload.expediente_id,
    )
    return ConversationCreateResponse(conversation=_to_conversation_out(conversation))


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageSendResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar mensaje a una conversacion",
)
def send_message(
    conversation_id: str,
    payload: MessageSendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MessageSendResponse:
    result = conversation_service.send_message(
        db=db,
        user_id=user.id,
        conversation_id=conversation_id,
        content=payload.content,
        jurisdiction=payload.jurisdiction,
        forum=payload.forum,
        top_k=payload.top_k,
        document_mode=payload.document_mode,
        facts=payload.facts,
        metadata=payload.metadata,
    )
    return MessageSendResponse(
        conversation=_to_conversation_out(result["conversation"]),
        user_message=_to_message_out(result["user_message"]),
        assistant_message=_to_message_out(result["assistant_message"]),
        consulta=_to_consulta_out(result["consulta"]),
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationHistoryResponse,
    summary="Obtener historial completo de una conversacion",
)
def get_history(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationHistoryResponse:
    history = conversation_service.get_history(db, conversation_id, user.id)
    return ConversationHistoryResponse(
        conversation=_to_conversation_out(history["conversation"]),
        messages=[_to_message_out(message) for message in history["messages"]],
        consultas=[_to_consulta_out(consulta) for consulta in history["consultas"]],
    )
