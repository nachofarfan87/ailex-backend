"""
AILEX -- Modelos de persistencia para usuarios, expedientes y consultas.

Tablas:
  users        -- usuario del sistema (abogado)
  expedientes  -- carpeta de un caso judicial
  consultas    -- consulta juridica guardada (query + resultado del pipeline)
  conversations -- sesion de chat persistente
  messages      -- mensajes dentro de una conversacion

Compatibilidad:
  - SQLite: desarrollo local (ailex_local.db)
  - PostgreSQL: produccion (activar en config)

Todos los PK son UUID almacenados como String(36), consistente con los
modelos existentes en app/db/models.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float,
    ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(Base):
    """
    Usuario del sistema (abogado / colaborador del estudio).

    La autenticacion es email + password.  El campo hashed_password almacena
    el hash bcrypt generado por passlib; nunca se almacena la contrasena en
    texto plano.
    """
    __tablename__ = "users"

    id              = Column(String(36),  primary_key=True, default=_new_uuid)
    email           = Column(String(255), nullable=False, unique=True, index=True)
    nombre          = Column(String(200), nullable=False, default="")
    hashed_password = Column(String(200), nullable=False)
    is_active       = Column(Boolean,     nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    expedientes = relationship(
        "Expediente", back_populates="user", cascade="all, delete-orphan"
    )
    consultas = relationship("Consulta", back_populates="user")
    conversations = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )
    messages = relationship("Message", back_populates="user")
    documents = relationship(
        "SourceDocument", back_populates="owner",
        foreign_keys="SourceDocument.user_id",
    )

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "email":      self.email,
            "nombre":     self.nombre,
            "is_active":  self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Expediente
# ---------------------------------------------------------------------------

class Expediente(Base):
    """
    Carpeta de un caso judicial.

    Agrupa consultas relacionadas a un mismo expediente judicial.
    Los campos siguen la nomenclatura de la practica forense en Jujuy.

    Estado:
      activo    -- expediente en tramite
      archivado -- cerrado pero conservado
      cerrado   -- definitivamente concluido
    """
    __tablename__ = "expedientes"

    id          = Column(String(36),  primary_key=True, default=_new_uuid)
    user_id     = Column(String(36),  ForeignKey("users.id"), nullable=False, index=True)

    # Identificacion del expediente
    titulo      = Column(String(500), nullable=False, index=True)
    caratula    = Column(String(500), default="")   # p.ej. "Perez c/ Lopez s/ daños"
    numero      = Column(String(100), default="")   # p.ej. "J.Civil N3 123/2026"

    # Clasificacion
    materia      = Column(String(100), default="")  # civil | laboral | familia | penal
    juzgado      = Column(String(200), default="")
    jurisdiccion = Column(String(100), default="jujuy")

    # Texto libre
    descripcion      = Column(Text, default="")
    notas_estrategia = Column(Text, default="")
    partes_json      = Column(Text, default="[]")
    hechos_relevantes = Column(Text, default="")
    pretension_principal = Column(Text, default="")
    riesgos_clave = Column(Text, default="")
    estrategia_base = Column(Text, default="")
    proxima_accion_sugerida = Column(Text, default="")

    # Contexto juridico estructurado
    tipo_caso = Column(String(120), default="")
    subtipo_caso = Column(String(120), default="")
    estado_procesal = Column(String(120), default="")

    # Estado
    estado = Column(String(20), default="activo", index=True)  # activo | archivado | cerrado

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user      = relationship("User",     back_populates="expedientes")
    consultas = relationship(
        "Consulta", back_populates="expediente",
        order_by="Consulta.created_at.desc()",
    )
    conversations = relationship(
        "Conversation", back_populates="expediente",
        order_by="Conversation.updated_at.desc()",
    )
    documents = relationship(
        "SourceDocument", back_populates="expediente",
        foreign_keys="SourceDocument.expediente_id",
    )

    def consulta_count(self) -> int:
        return len(self.consultas) if self.consultas else 0

    def to_dict(self, include_consulta_count: bool = True) -> dict:
        d: dict = {
            "id":               self.id,
            "user_id":          self.user_id,
            "titulo":           self.titulo,
            "caratula":         self.caratula,
            "numero":           self.numero,
            "materia":          self.materia,
            "juzgado":          self.juzgado,
            "jurisdiccion":     self.jurisdiccion,
            "descripcion":      self.descripcion,
            "notas_estrategia": self.notas_estrategia,
            "tipo_caso":        self.tipo_caso,
            "subtipo_caso":     self.subtipo_caso,
            "partes_json":      self.partes_json,
            "hechos_relevantes": self.hechos_relevantes,
            "pretension_principal": self.pretension_principal,
            "estado_procesal":  self.estado_procesal,
            "riesgos_clave":    self.riesgos_clave,
            "estrategia_base":  self.estrategia_base,
            "proxima_accion_sugerida": self.proxima_accion_sugerida,
            "estado":           self.estado,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_consulta_count:
            d["consulta_count"] = self.consulta_count()
        return d


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

class Consulta(Base):
    """
    Consulta juridica guardada.

    Almacena el par pregunta / respuesta del pipeline de AILEX.
    El campo resultado_json contiene el JSON serializado de PipelineResult,
    lo que permite reconstruir la vista completa sin reejecutar el pipeline.

    La relacion con expediente es opcional: una consulta puede estar suelta
    (sin expediente) o vinculada a uno.
    """
    __tablename__ = "consultas"

    id             = Column(String(36),  primary_key=True, default=_new_uuid)
    user_id        = Column(String(36),  ForeignKey("users.id"),     nullable=True,  index=True)
    expediente_id  = Column(String(36),  ForeignKey("expedientes.id"), nullable=True, index=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=True, index=True)

    # Identificacion
    titulo = Column(String(300), default="")  # auto-generado si no se provee

    # Consulta original
    query         = Column(Text,         nullable=False)
    jurisdiction  = Column(String(100),  default="jujuy")
    forum         = Column(String(100),  default="")
    document_mode = Column(String(50),   default="")
    facts_json    = Column(Text,         default="{}")   # JSON dict de facts

    # Resultado del pipeline
    resultado_json     = Column(Text, default="{}")   # PipelineResult.to_dict() completo
    confidence         = Column(Float,  nullable=True)
    generated_document = Column(Text,   default="")
    warnings_json      = Column(Text,   default="[]")  # JSON list de warnings

    # Notas del usuario sobre esta consulta
    notas = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relaciones
    user        = relationship("User",        back_populates="consultas")
    expediente  = relationship("Expediente",  back_populates="consultas")
    conversation = relationship("Conversation", back_populates="consultas")
    assistant_messages = relationship("Message", back_populates="consulta")

    def to_dict(self, include_resultado: bool = True) -> dict:
        import json
        d: dict = {
            "id":             self.id,
            "user_id":        self.user_id,
            "expediente_id":  self.expediente_id,
            "conversation_id": self.conversation_id,
            "titulo":         self.titulo,
            "query":          self.query,
            "jurisdiction":   self.jurisdiction,
            "forum":          self.forum,
            "document_mode":  self.document_mode,
            "confidence":     self.confidence,
            "notas":          self.notas,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
        }
        if include_resultado:
            try:
                d["resultado"]  = json.loads(self.resultado_json or "{}")
            except (ValueError, TypeError):
                d["resultado"]  = {}
            try:
                d["warnings"] = json.loads(self.warnings_json or "[]")
            except (ValueError, TypeError):
                d["warnings"] = []
            d["generated_document"] = self.generated_document or ""
            try:
                d["facts"] = json.loads(self.facts_json or "{}")
            except (ValueError, TypeError):
                d["facts"] = {}
        return d

    def to_summary(self) -> dict:
        """Version reducida para listados (sin resultado completo)."""
        return self.to_dict(include_resultado=False)


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

class Conversation(Base):
    """
    Conversacion persistente de chat.

    Agrupa multiples mensajes y consultas juridicas dentro de una misma
    sesion conversacional del usuario.
    """
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    expediente_id = Column(String(36), ForeignKey("expedientes.id"), nullable=True, index=True)
    titulo = Column(String(255), nullable=False, default="")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    user = relationship("User", back_populates="conversations")
    expediente = relationship("Expediente", back_populates="conversations")
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )
    consultas = relationship(
        "Consulta",
        back_populates="conversation",
        order_by="Consulta.created_at.asc()",
    )

    def to_dict(self, include_counts: bool = True) -> dict:
        payload = {
            "id": self.id,
            "user_id": self.user_id,
            "expediente_id": self.expediente_id,
            "titulo": self.titulo,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_counts:
            payload["message_count"] = len(self.messages) if self.messages else 0
            payload["consulta_count"] = len(self.consultas) if self.consultas else 0
        return payload


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class Message(Base):
    """
    Mensaje individual dentro de una conversacion.

    El mensaje asistente puede vincularse a una Consulta, que conserva el
    resultado juridico completo y evita duplicar resultado_json en chat.
    """
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    consulta_id = Column(String(36), ForeignKey("consultas.id"), nullable=True, index=True)
    role = Column(String(20), nullable=False, default="user")  # user | assistant | system
    content = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    conversation = relationship("Conversation", back_populates="messages")
    user = relationship("User", back_populates="messages")
    consulta = relationship("Consulta", back_populates="assistant_messages")

    def to_dict(self, include_consulta: bool = False) -> dict:
        payload = {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "consulta_id": self.consulta_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_consulta and self.consulta is not None:
            payload["consulta"] = self.consulta.to_dict(include_resultado=True)
        return payload
