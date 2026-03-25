"""
AILEX -- Servicio de consultas guardadas.

Una Consulta es el par (pregunta + resultado del pipeline) que el usuario
decide persistir.  Puede estar asociada a un expediente o estar suelta.

El campo resultado_json almacena el JSON serializado de PipelineResult.to_dict(),
lo que permite reconstruir la vista completa en el frontend sin reejecutar
el pipeline.

Flujo de persistencia:
- save_consulta() siempre crea una consulta nueva.
- upsert_consulta() actualiza solo si viene consulta_id; si no, crea nueva.
- No hay deduplicación automática por query ni conversation_id.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.user_models import Consulta, Conversation, Expediente


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _auto_titulo(query: str, maxlen: int = 80) -> str:
    """Genera un titulo breve a partir del texto de la consulta."""
    clean = query.strip().replace("\n", " ")
    if len(clean) <= maxlen:
        return clean
    return clean[:maxlen].rsplit(" ", 1)[0] + "..."


def _verify_expediente_ownership(
    db: Session,
    expediente_id: str,
    user_id: str,
) -> None:
    """Lanza 404/403 si el expediente no existe o no pertenece al usuario."""
    exp = db.get(Expediente, expediente_id)
    if exp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expediente '{expediente_id}' no encontrado.",
        )
    if exp.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para acceder a este expediente.",
        )


def _verify_conversation_ownership(
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



def _extract_resultado_fields(resultado: dict) -> tuple[Optional[float], str, list]:
    """Extrae confidence, generated_document y warnings del resultado."""
    confidence: Optional[float] = None
    generated_doc: str = ""
    warnings: list = []

    if isinstance(resultado, dict):
        raw_conf = resultado.get("confidence")
        if isinstance(raw_conf, (int, float)):
            confidence = float(raw_conf)
        generated_doc = resultado.get("generated_document") or ""
        warnings = resultado.get("warnings") or []

    return confidence, generated_doc, warnings


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def get_consultas(
    db: Session,
    user_id: str,
    expediente_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Consulta]:
    """
    Lista las consultas del usuario.

    Si se provee expediente_id, filtra solo las de ese expediente.
    """
    q = db.query(Consulta).filter(Consulta.user_id == user_id)
    if expediente_id is not None:
        q = q.filter(Consulta.expediente_id == expediente_id)
    return (
        q.order_by(Consulta.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_consulta(
    db: Session,
    consulta_id: str,
    user_id: str,
) -> Consulta:
    """
    Obtiene una consulta por ID.

    Lanza HTTP 404 si no existe.
    Lanza HTTP 403 si pertenece a otro usuario.
    """
    c = db.get(Consulta, consulta_id)
    if c is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Consulta '{consulta_id}' no encontrada.",
        )
    if c.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para acceder a esta consulta.",
        )
    return c


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def save_consulta(
    db: Session,
    user_id: str,
    query: str,
    resultado: dict,
    titulo: str = "",
    jurisdiction: str = "jujuy",
    forum: str = "",
    document_mode: str = "",
    facts: Optional[dict] = None,
    notas: str = "",
    expediente_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    auto_commit: bool = True,
) -> Consulta:
    """
    Persiste una consulta juridica con su resultado.

    Siempre crea una nueva consulta. No deduplica.

    Args:
        user_id:       ID del usuario que realiza la consulta.
        query:         Texto de la consulta original.
        resultado:     Dict serializable producido por PipelineResult.to_dict().
        titulo:        Titulo descriptivo (auto-generado si vacio).
        jurisdiction:  Jurisdiccion usada.
        forum:         Fuero/materia usada.
        document_mode: Modo de documento solicitado.
        facts:         Hechos adicionales pasados al pipeline.
        notas:         Notas libres del usuario sobre esta consulta.
        expediente_id: Si se provee, vincula la consulta al expediente.
        conversation_id: Si se provee, vincula la consulta a una conversacion.
        auto_commit:   Si True, hace commit inmediato. Si False, solo flush.

    Returns:
        La Consulta nueva persistida.
    """
    if expediente_id:
        _verify_expediente_ownership(db, expediente_id, user_id)
    if conversation_id:
        conversation = _verify_conversation_ownership(db, conversation_id, user_id)
        if expediente_id is None and conversation.expediente_id:
            expediente_id = conversation.expediente_id

    # ── NO deduplicamos automáticamente ───────────────────────────
    # Las consultas deben persistirse siempre como nuevas ejecuciones,
    # salvo que venga un upsert explícito (consulta_id).
    # Esto evita perder corridas legítimas del pipeline.
    # ─────────────────────────────────────────────────────────────

    confidence, generated_doc, warnings = _extract_resultado_fields(resultado)

    c = Consulta(
        user_id=user_id,
        expediente_id=expediente_id,
        conversation_id=conversation_id,
        titulo=titulo.strip() if titulo else _auto_titulo(query),
        query=query,
        jurisdiction=jurisdiction,
        forum=forum,
        document_mode=document_mode,
        facts_json=json.dumps(facts or {}, ensure_ascii=False),
        resultado_json=json.dumps(resultado, ensure_ascii=False, default=str),
        confidence=confidence,
        generated_document=generated_doc,
        warnings_json=json.dumps(warnings, ensure_ascii=False, default=str),
        notas=notas,
    )
    db.add(c)
    if auto_commit:
        db.commit()
        db.refresh(c)
    else:
        db.flush()
    return c


def upsert_consulta(
    db: Session,
    user_id: str,
    query: str,
    resultado: dict,
    titulo: str = "",
    jurisdiction: str = "jujuy",
    forum: str = "",
    document_mode: str = "",
    facts: Optional[dict] = None,
    notas: str = "",
    expediente_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    consulta_id: Optional[str] = None,
) -> tuple[Consulta, bool]:
    """
    Crea o actualiza una consulta.

    Logica de resolucion:
    1. Si consulta_id se provee → actualizar esa consulta existente.
    2. Si no → crear nueva (sin deduplicación automática).

    Returns:
        Tupla (consulta, created) donde created=True si se creo nueva.
    """
    # ── Caso 1: ID explicito → actualizar ────────────────────────
    if consulta_id:
        existing = get_consulta(db, consulta_id, user_id)
        _update_consulta_fields(
            existing, resultado=resultado, titulo=titulo,
            notas=notas, expediente_id=expediente_id,
            jurisdiction=jurisdiction, forum=forum,
            document_mode=document_mode, facts=facts,
        )
        if expediente_id:
            _verify_expediente_ownership(db, expediente_id, user_id)
            existing.expediente_id = expediente_id
        db.commit()
        db.refresh(existing)
        return existing, False

    # ── Caso 2: crear nueva ──────────────────────────────────────
    nueva = save_consulta(
        db=db, user_id=user_id, query=query, resultado=resultado,
        titulo=titulo, jurisdiction=jurisdiction, forum=forum,
        document_mode=document_mode, facts=facts, notas=notas,
        expediente_id=expediente_id, conversation_id=conversation_id,
    )
    return nueva, True


def _update_consulta_fields(
    c: Consulta,
    *,
    resultado: dict,
    titulo: str,
    notas: str,
    expediente_id: Optional[str],
    jurisdiction: str,
    forum: str,
    document_mode: str,
    facts: Optional[dict],
) -> None:
    """Actualiza campos mutables de una consulta existente."""
    confidence, generated_doc, warnings = _extract_resultado_fields(resultado)

    if resultado:
        c.resultado_json = json.dumps(resultado, ensure_ascii=False, default=str)
        c.confidence = confidence
        c.generated_document = generated_doc
        c.warnings_json = json.dumps(warnings, ensure_ascii=False, default=str)
    if titulo and titulo.strip():
        c.titulo = titulo.strip()
    if notas:
        c.notas = notas
    if expediente_id is not None:
        c.expediente_id = expediente_id
    if jurisdiction:
        c.jurisdiction = jurisdiction
    if forum:
        c.forum = forum
    if document_mode:
        c.document_mode = document_mode
    if facts:
        c.facts_json = json.dumps(facts, ensure_ascii=False)


def update_notas(
    db: Session,
    consulta_id: str,
    user_id: str,
    notas: str,
) -> Consulta:
    """Actualiza las notas de una consulta."""
    c = get_consulta(db, consulta_id, user_id)
    c.notas = notas
    db.commit()
    db.refresh(c)
    return c


def assign_expediente(
    db: Session,
    consulta_id: str,
    user_id: str,
    expediente_id: Optional[str],
) -> Consulta:
    """
    Vincula (o desvincula) una consulta a un expediente.

    Pasar expediente_id=None desvincula la consulta de cualquier expediente.
    """
    c = get_consulta(db, consulta_id, user_id)
    if expediente_id is not None:
        _verify_expediente_ownership(db, expediente_id, user_id)
    c.expediente_id = expediente_id
    db.commit()
    db.refresh(c)
    return c


def delete_consulta(
    db: Session,
    consulta_id: str,
    user_id: str,
) -> None:
    """Elimina permanentemente una consulta."""
    c = get_consulta(db, consulta_id, user_id)
    db.delete(c)
    db.commit()
