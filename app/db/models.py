"""
AILEX — Modelos SQLAlchemy de infraestructura documental.

Modelos:
  SourceDocument  — documento jurídico ingresado
  DocumentChunk   — fragmento de documento con metadata jurídica
  SourceCitation  — cita utilizada en una JuridicalResponse

Enums:
  SourceTypeEnum       — tipo de fuente (código, ley, jurisprudencia, etc.)
  SourceHierarchyEnum  — jerarquía jurídica (normativa > jurisprudencia > ...)
  AuthorityLevel       — nivel de autoridad
  DocumentStatus       — estado de procesamiento

Mappings:
  SOURCE_TYPE_TO_HIERARCHY  — tipo → jerarquía automática
  SOURCE_TYPE_TO_AUTHORITY  — tipo → nivel de autoridad

Compatibilidad:
  - SQLite: para desarrollo local (campo embedding = TEXT con JSON)
  - PostgreSQL + pgvector: para producción (activar en config)
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, Boolean, Float, Integer,
    DateTime, ForeignKey, Enum as SAEnum,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


# ═══════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════

class SourceTypeEnum(str, enum.Enum):
    """
    Tipos de fuente documental soportados.
    Determina el peso y uso permitido en argumentación.
    """
    # Normativa
    CODIGO       = "codigo"       # Códigos procesales y de fondo
    LEY          = "ley"          # Leyes nacionales y provinciales
    REGLAMENTO   = "reglamento"   # Decretos reglamentarios
    ACORDADA     = "acordada"     # Acordadas del STJ y Cámaras

    # Jurisprudencia
    JURISPRUDENCIA = "jurisprudencia"  # Fallos y sentencias

    # Doctrina
    DOCTRINA     = "doctrina"     # Comentarios doctrinarios, tratados

    # Material interno
    ESCRITO      = "escrito"      # Escritos históricos del estudio
    MODELO       = "modelo"       # Modelos y plantillas base
    ESTRATEGIA   = "estrategia"   # Notas de estrategia procesal


class SourceHierarchyEnum(str, enum.Enum):
    """
    Jerarquía jurídica de la fuente.
    Refleja el peso argumental real en la práctica.
    """
    NORMATIVA      = "normativa"      # Código/ley — máximo peso
    JURISPRUDENCIA = "jurisprudencia" # Fallos — peso alto
    DOCTRINA       = "doctrina"       # Tratados — medio, no vinculante
    INTERNO        = "interno"        # Material estudio — uso práctico


class AuthorityLevel(str, enum.Enum):
    """
    Nivel de autoridad de la fuente.
    Refinamiento de la jerarquía para ordenar resultados.
    """
    VINCULANTE   = "vinculante"   # Obligatoria (ley, código, STJ propio fuero)
    REFERENCIAL  = "referencial"  # Orientadora (doctrina, jurisprudencia otro fuero)
    INTERNO      = "interno"      # Solo uso interno del estudio


class DocumentStatus(str, enum.Enum):
    """Estado de procesamiento del documento."""
    PENDING  = "pending"   # Recibido, no procesado
    INDEXED  = "indexed"   # Procesado y disponible para búsqueda
    ERROR    = "error"     # Error en procesamiento
    ARCHIVED = "archived"  # Archivado, no disponible para búsqueda activa


class DocumentScope(str, enum.Enum):
    """Alcance documental dentro de la plataforma."""
    CORPUS = "corpus"
    CASE = "case"


# ═══════════════════════════════════════════════════════════
# MAPPINGS: tipo → jerarquía y autoridad
# ═══════════════════════════════════════════════════════════

SOURCE_TYPE_TO_HIERARCHY: dict[SourceTypeEnum, SourceHierarchyEnum] = {
    SourceTypeEnum.CODIGO:          SourceHierarchyEnum.NORMATIVA,
    SourceTypeEnum.LEY:             SourceHierarchyEnum.NORMATIVA,
    SourceTypeEnum.REGLAMENTO:      SourceHierarchyEnum.NORMATIVA,
    SourceTypeEnum.ACORDADA:        SourceHierarchyEnum.NORMATIVA,
    SourceTypeEnum.JURISPRUDENCIA:  SourceHierarchyEnum.JURISPRUDENCIA,
    SourceTypeEnum.DOCTRINA:        SourceHierarchyEnum.DOCTRINA,
    SourceTypeEnum.ESCRITO:         SourceHierarchyEnum.INTERNO,
    SourceTypeEnum.MODELO:          SourceHierarchyEnum.INTERNO,
    SourceTypeEnum.ESTRATEGIA:      SourceHierarchyEnum.INTERNO,
}

SOURCE_TYPE_TO_AUTHORITY: dict[SourceTypeEnum, AuthorityLevel] = {
    SourceTypeEnum.CODIGO:          AuthorityLevel.VINCULANTE,
    SourceTypeEnum.LEY:             AuthorityLevel.VINCULANTE,
    SourceTypeEnum.REGLAMENTO:      AuthorityLevel.VINCULANTE,
    SourceTypeEnum.ACORDADA:        AuthorityLevel.VINCULANTE,
    SourceTypeEnum.JURISPRUDENCIA:  AuthorityLevel.REFERENCIAL,
    SourceTypeEnum.DOCTRINA:        AuthorityLevel.REFERENCIAL,
    SourceTypeEnum.ESCRITO:         AuthorityLevel.INTERNO,
    SourceTypeEnum.MODELO:          AuthorityLevel.INTERNO,
    SourceTypeEnum.ESTRATEGIA:      AuthorityLevel.INTERNO,
}


# ═══════════════════════════════════════════════════════════
# MODELO: SourceDocument
# ═══════════════════════════════════════════════════════════

class SourceDocument(Base):
    """
    Documento jurídico ingresado a la base documental.

    Cada documento se procesa en chunks para búsqueda.
    El campo embedding_placeholder se reemplazará por
    un campo VECTOR de pgvector en producción.
    """
    __tablename__ = "source_documents"

    # ─── Identificación ──────────────────────────────
    id             = Column(String(36), primary_key=True)
    user_id        = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    title          = Column(String(500), nullable=False, index=True)
    description    = Column(Text, default="")

    # ─── Clasificación jurídica ──────────────────────
    source_type      = Column(
        SAEnum(SourceTypeEnum, name="source_type_enum"),
        nullable=False,
        index=True,
    )
    source_hierarchy = Column(
        SAEnum(SourceHierarchyEnum, name="source_hierarchy_enum"),
        nullable=False,
        index=True,
    )
    authority_level  = Column(
        SAEnum(AuthorityLevel, name="authority_level_enum"),
        nullable=False,
        default=AuthorityLevel.REFERENCIAL,
    )

    # ─── Jurisdicción y materia ──────────────────────
    jurisdiction = Column(String(100), default="Jujuy", index=True)
    fuero        = Column(String(100), default="")
    legal_area   = Column(String(100), default="", index=True)
    court        = Column(String(200), default="")

    # ─── Metadatos documentales ──────────────────────
    document_date     = Column(String(20), nullable=True)   # ISO 8601
    authority         = Column(String(200), default="")     # Autor/tribunal
    nivel_jerarquia   = Column(String(100), default="")     # Descripción libre
    vigente           = Column(Boolean, default=True)
    origin            = Column(String(100), default="carga_manual")
    tags              = Column(String(500), default="")
    detected_type     = Column(String(120), default="")
    entities_json     = Column(Text, default="{}")
    extraction_mode   = Column(String(50), default="")
    extraction_method = Column(String(50), default="")
    ocr_used          = Column(Boolean, default=False)
    extracted_text_length = Column(Integer, default=0)
    extraction_warning = Column(Text, default="")
    page_count        = Column(Integer, nullable=True)
    ocr_pages_processed = Column(Integer, nullable=True)
    document_scope    = Column(
        SAEnum(DocumentScope, name="document_scope_enum"),
        nullable=False,
        default=DocumentScope.CORPUS,
        index=True,
    )

    # ─── Vinculación con expediente ────────────────────
    expediente_id = Column(String(36), ForeignKey("expedientes.id"), nullable=True, index=True)

    # ─── Archivo y contenido ─────────────────────────
    file_path         = Column(String(500), nullable=True)
    file_type         = Column(String(10), default="txt")
    content_raw       = Column(Text, nullable=True)
    hash_documento    = Column(String(64), nullable=True, index=True)

    # ─── Calidad y confiabilidad ─────────────────────
    reliability_score = Column(Float, default=0.5)

    # ─── Estado de procesamiento ─────────────────────
    status     = Column(
        SAEnum(DocumentStatus, name="document_status_enum"),
        default=DocumentStatus.PENDING,
        index=True,
    )
    chunk_count  = Column(Integer, default=0)
    total_chars  = Column(Integer, default=0)

    # ─── Timestamps ──────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ─── Relaciones ──────────────────────────────────
    chunks    = relationship("DocumentChunk", back_populates="document",
                             cascade="all, delete-orphan")
    citations = relationship("SourceCitation", back_populates="document")
    owner     = relationship("User", back_populates="documents", foreign_keys=[user_id])
    expediente = relationship("Expediente", back_populates="documents", foreign_keys=[expediente_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "source_type": self.source_type.value if self.source_type else None,
            "source_hierarchy": self.source_hierarchy.value if self.source_hierarchy else None,
            "authority_level": self.authority_level.value if self.authority_level else None,
            "jurisdiction": self.jurisdiction,
            "fuero": self.fuero,
            "legal_area": self.legal_area,
            "court": self.court,
            "document_date": self.document_date,
            "authority": self.authority,
            "vigente": self.vigente,
            "origin": self.origin,
            "tags": self.tags,
            "detected_type": self.detected_type,
            "entities": self.entities_json,
            "extraction_mode": self.extraction_mode,
            "extraction_method": self.extraction_method,
            "ocr_used": self.ocr_used,
            "extracted_text_length": self.extracted_text_length,
            "extraction_warning": self.extraction_warning,
            "page_count": self.page_count,
            "ocr_pages_processed": self.ocr_pages_processed,
            "document_scope": self.document_scope.value if self.document_scope else None,
            "expediente_id": self.expediente_id,
            "file_type": self.file_type,
            "hash_documento": self.hash_documento,
            "reliability_score": self.reliability_score,
            "status": self.status.value if self.status else None,
            "chunk_count": self.chunk_count,
            "total_chars": self.total_chars,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ═══════════════════════════════════════════════════════════
# MODELO: DocumentChunk
# ═══════════════════════════════════════════════════════════

class DocumentChunk(Base):
    """
    Fragmento de documento jurídico.

    Unidad básica de búsqueda y recuperación.
    Preserva metadata de posición (sección, artículo, página).

    El campo embedding_json almacena el vector como JSON
    para compatibilidad SQLite. En producción con pgvector
    se usará un campo VECTOR nativo.
    """
    __tablename__ = "document_chunks"

    # ─── Identificación ──────────────────────────────
    id          = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("source_documents.id"), nullable=False, index=True)

    # ─── Contenido ───────────────────────────────────
    text        = Column(Text, nullable=False)
    text_search = Column(Text, default="")  # versión normalizada para keyword search

    # ─── Posición en el documento ────────────────────
    chunk_index       = Column(Integer, nullable=False)
    page_number       = Column(Integer, nullable=True)
    section           = Column(String(300), default="")
    article_reference = Column(String(100), default="")
    char_count        = Column(Integer, default=0)

    # ─── Embedding vectorial ─────────────────────────
    # En SQLite: JSON serializado
    # En PostgreSQL + pgvector: migrar a Column(Vector(384))
    embedding_json  = Column(Text, nullable=True)
    embedding_model = Column(String(100), default="placeholder")

    # ─── Clasificación (heredada del documento) ──────
    source_type      = Column(String(50), default="")
    source_hierarchy = Column(String(50), default="", index=True)
    jurisdiction     = Column(String(100), default="Jujuy", index=True)
    legal_area       = Column(String(100), default="")

    # ─── Timestamps ──────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)

    # ─── Relaciones ──────────────────────────────────
    document  = relationship("SourceDocument", back_populates="chunks")
    citations = relationship("SourceCitation", back_populates="chunk")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "text": self.text,
            "chunk_index": self.chunk_index,
            "page_number": self.page_number,
            "section": self.section,
            "article_reference": self.article_reference,
            "char_count": self.char_count,
            "source_type": self.source_type,
            "source_hierarchy": self.source_hierarchy,
            "jurisdiction": self.jurisdiction,
            "legal_area": self.legal_area,
            "embedding_model": self.embedding_model,
        }


# ═══════════════════════════════════════════════════════════
# MODELO: SourceCitation
# ═══════════════════════════════════════════════════════════

class SourceCitation(Base):
    """
    Cita de fuente utilizada en una JuridicalResponse.

    Registra exactamente qué fragmento de qué documento
    fue usado para respaldar una afirmación en una respuesta.
    Esto permite auditar el razonamiento del sistema.

    Compatible con SourceCitationSchema del contrato de respuesta.
    """
    __tablename__ = "source_citations"

    # ─── Identificación ──────────────────────────────
    id          = Column(String(36), primary_key=True)
    session_id  = Column(String(100), nullable=True, index=True)
    module      = Column(String(50), default="")

    # ─── Fuente referenciada ─────────────────────────
    document_id = Column(String(36), ForeignKey("source_documents.id"), nullable=True)
    chunk_id    = Column(String(36), ForeignKey("document_chunks.id"), nullable=True)

    # ─── Contenido de la cita ────────────────────────
    document_title   = Column(String(500), default="")
    source_hierarchy = Column(String(50), default="")
    fragment         = Column(Text, default="")
    page_or_section  = Column(String(200), nullable=True)
    relevance_score  = Column(Float, default=0.0)

    # ─── Carácter de la afirmación ───────────────────
    # extraido | inferencia | sugerencia
    caracter = Column(String(20), default="extraido")

    # ─── Timestamps ──────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)

    # ─── Relaciones ──────────────────────────────────
    document = relationship("SourceDocument", back_populates="citations")
    chunk    = relationship("DocumentChunk", back_populates="citations")

    def to_source_citation_schema(self) -> dict:
        """
        Convertir a formato compatible con SourceCitationSchema.
        Para poblar fuentes_respaldo en JuridicalResponse.
        """
        return {
            "document_id": self.document_id,
            "document_title": self.document_title,
            "source_hierarchy": self.source_hierarchy,
            "fragment": self.fragment,
            "page_or_section": self.page_or_section,
            "relevance_score": self.relevance_score,
        }
