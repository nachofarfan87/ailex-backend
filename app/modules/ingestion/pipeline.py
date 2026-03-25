"""
AILEX — Pipeline de ingestión documental (pasos explícitos).

Flujo canónico:
  archivo/texto
    → 1. parse_document     — extraer texto crudo
    → 2. normalize_text     — limpiar y detectar entidades
    → 3. extract_metadata   — resolver clasificación jurídica
    → 4. chunk_document     — particionar en chunks jurídicos
    → 5. persist_document   — guardar documento en store
    → 6. persist_chunks     — guardar chunks en store

Cada paso es una función pura, invocable de forma independiente.
El IngestionService en service.py orquesta el pipeline completo.

Tipos de fuente soportados:
  normativa: código, ley, reglamento, acordada
  jurisprudencia: fallos, sentencias
  doctrina: comentarios doctrinarios
  escritos_estudio: escritos históricos del estudio
  plantillas: modelos base

Formatos de entrada:
  PDF | DOCX | TXT | texto_manual
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.db.models import (
    SourceTypeEnum,
    SourceHierarchyEnum,
    AuthorityLevel,
    DocumentStatus,
    SOURCE_TYPE_TO_HIERARCHY,
    SOURCE_TYPE_TO_AUTHORITY,
)
from app.modules.ingestion.chunker import LegalChunker, LegalChunk


# ─── Resultado de cada paso ──────────────────────────────────

@dataclass
class ParseResult:
    """Resultado del paso de parsing."""
    text_raw: str
    pages: int = 1
    method: str = "unknown"
    file_type: str = "txt"


@dataclass
class NormalizeResult:
    """Resultado del paso de normalización."""
    text_clean: str
    entities: dict = field(default_factory=dict)
    doc_type_detected: str = "desconocido"


@dataclass
class MetadataResult:
    """Resultado del paso de extracción de metadatos."""
    source_type: SourceTypeEnum
    source_hierarchy: SourceHierarchyEnum
    authority_level: AuthorityLevel
    jurisdiction: str = "Jujuy"
    fuero: str = ""
    legal_area: str = ""
    court: str = ""
    document_date: Optional[str] = None
    authority: str = ""
    vigente: bool = True
    origin: str = "carga_manual"
    tags: str = ""
    title: str = ""
    description: str = ""
    reliability_score: float = 0.5


@dataclass
class PipelineResult:
    """Resultado completo del pipeline de ingestión."""
    document_id: str
    document: dict
    chunks: list[dict]
    status: str = "indexed"
    chunk_count: int = 0
    total_chars: int = 0
    source_type: str = ""
    source_hierarchy: str = ""
    detected_type: str = ""
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# PASO 1: parse_document
# ═══════════════════════════════════════════════════════════

def parse_document(
    content: bytes,
    file_type: str,
) -> ParseResult:
    """
    Paso 1: Extraer texto crudo de un archivo.

    Soporta: pdf, docx, txt.
    Retorna el texto crudo y metadata de extracción.
    """
    from app.modules.ingestion.extractor import TextExtractor
    extractor = TextExtractor()
    result = extractor.extract_from_bytes(content, file_type)
    return ParseResult(
        text_raw=result.get("text", ""),
        pages=result.get("pages", 1),
        method=result.get("method", "unknown"),
        file_type=file_type,
    )


def parse_text(text: str) -> ParseResult:
    """
    Paso 1 (variante): Aceptar texto ya extraído.
    Para ingestión desde textarea o API de texto.
    """
    return ParseResult(
        text_raw=text,
        pages=1,
        method="text_direct",
        file_type="txt",
    )


# ═══════════════════════════════════════════════════════════
# PASO 2: normalize_text
# ═══════════════════════════════════════════════════════════

async def normalize_text(text_raw: str) -> NormalizeResult:
    """
    Paso 2: Limpiar texto y detectar entidades jurídicas.

    Extrae: expedientes, fechas, artículos, carátulas.
    Detecta: tipo de documento preliminar.
    """
    from app.modules.normalization.service import NormalizationService
    normalizer = NormalizationService()
    result = await normalizer.normalize(text_raw)
    return NormalizeResult(
        text_clean=result.get("text_clean", text_raw),
        entities=result.get("entities", {}),
        doc_type_detected=result.get("doc_type", "desconocido"),
    )


# ═══════════════════════════════════════════════════════════
# PASO 3: extract_metadata
# ═══════════════════════════════════════════════════════════

def extract_metadata(metadata_input: dict) -> MetadataResult:
    """
    Paso 3: Resolver clasificación jurídica desde los metadatos provistos.

    Determina automáticamente:
    - source_hierarchy: normativa | jurisprudencia | doctrina | interno
    - authority_level: vinculante | referencial | interno

    El caller debe proveer al menos source_type en metadata_input.
    """
    # Resolver source_type
    raw_type = metadata_input.get("source_type", "escrito")
    # Normalizar alias comunes
    _aliases = {
        "escrito": SourceTypeEnum.ESCRITO,
        "modelo": SourceTypeEnum.MODELO,
        "estrategia": SourceTypeEnum.ESTRATEGIA,
    }

    try:
        source_type = SourceTypeEnum(raw_type)
    except ValueError:
        source_type = _aliases.get(raw_type, SourceTypeEnum.ESCRITO)

    source_hierarchy = SOURCE_TYPE_TO_HIERARCHY.get(source_type, SourceHierarchyEnum.INTERNO)
    authority_level = SOURCE_TYPE_TO_AUTHORITY.get(source_type, AuthorityLevel.INTERNO)

    # Calcular reliability_score base por tipo
    reliability_base = {
        SourceHierarchyEnum.NORMATIVA: 0.95,
        SourceHierarchyEnum.JURISPRUDENCIA: 0.80,
        SourceHierarchyEnum.DOCTRINA: 0.60,
        SourceHierarchyEnum.INTERNO: 0.40,
    }
    reliability_score = reliability_base.get(source_hierarchy, 0.5)
    # Override manual si se proporciona
    if "reliability_score" in metadata_input:
        reliability_score = float(metadata_input["reliability_score"])

    return MetadataResult(
        source_type=source_type,
        source_hierarchy=source_hierarchy,
        authority_level=authority_level,
        jurisdiction=metadata_input.get("jurisdiction", "Jujuy"),
        fuero=metadata_input.get("fuero", ""),
        legal_area=metadata_input.get("legal_area", ""),
        court=metadata_input.get("court", ""),
        document_date=metadata_input.get("document_date"),
        authority=metadata_input.get("authority", ""),
        vigente=metadata_input.get("vigente", True),
        origin=metadata_input.get("origin", "carga_manual"),
        tags=metadata_input.get("tags", ""),
        title=metadata_input.get("title", ""),
        description=metadata_input.get("description", ""),
        reliability_score=reliability_score,
    )


# ═══════════════════════════════════════════════════════════
# PASO 4: chunk_document
# ═══════════════════════════════════════════════════════════

def chunk_document(
    text_clean: str,
    source_type: SourceTypeEnum = None,
) -> list[LegalChunk]:
    """
    Paso 4: Particionar texto en chunks jurídicos.

    Estrategia por tipo de fuente:
    - normativa (código/ley): por artículos → secciones → párrafos
    - jurisprudencia: sumario → considerandos → resolutiva
    - doctrina/escritos: por secciones → párrafos
    - plantillas: por secciones

    El chunker detecta automáticamente la estructura.
    Nunca corta en medio de un artículo o cita legal.
    """
    chunker = LegalChunker()
    chunks = chunker.chunk(text_clean)

    # Si no hay chunks útiles, crear uno con el texto completo
    if not chunks and text_clean.strip():
        return [LegalChunk(
            text=text_clean.strip(),
            index=0,
            section="completo",
        )]

    return chunks


# ═══════════════════════════════════════════════════════════
# PASO 5: persist_document
# ═══════════════════════════════════════════════════════════

def persist_document(
    doc_id: str,
    text_raw: str,
    text_clean: str,
    meta: MetadataResult,
    parse: ParseResult,
    normalize: NormalizeResult,
    chunk_count: int,
    store,
) -> dict:
    """
    Paso 5: Construir el dict del documento y almacenarlo en el store.

    El hash_documento permite detectar duplicados.
    Retorna el dict del documento almacenado.
    """
    hash_doc = hashlib.sha256(text_clean.encode()).hexdigest()

    document = {
        "id": doc_id,
        "title": meta.title,
        "description": meta.description,
        "file_path": None,
        "file_type": parse.file_type,
        "content_raw": text_raw,
        "source_type": meta.source_type.value,
        "source_hierarchy": meta.source_hierarchy.value,
        "authority_level": meta.authority_level.value,
        "jurisdiction": meta.jurisdiction,
        "court": meta.court,
        "legal_area": meta.legal_area,
        "fuero": meta.fuero,
        "document_date": meta.document_date,
        "authority": meta.authority,
        "vigente": meta.vigente,
        "reliability_score": meta.reliability_score,
        "origin": meta.origin,
        "tags": meta.tags,
        "status": DocumentStatus.INDEXED.value,
        "chunk_count": chunk_count,
        "total_chars": len(text_clean),
        "detected_type": normalize.doc_type_detected,
        "entities": normalize.entities,
        "hash_documento": hash_doc,
    }

    store.add_document(document)
    return document


# ═══════════════════════════════════════════════════════════
# PASO 6: persist_chunks
# ═══════════════════════════════════════════════════════════

def persist_chunks(
    doc_id: str,
    chunks: list[LegalChunk],
    embeddings: list[list[float]],
    meta: MetadataResult,
    embedder,
    store,
) -> list[dict]:
    """
    Paso 6: Construir los dicts de chunks y almacenarlos en el store.

    Cada chunk recibe:
    - Texto normalizado para búsqueda (lowercase, sin puntuación extra)
    - Embedding serializado como JSON
    - Metadata de posición (sección, artículo, página)
    - Clasificación heredada del documento
    """
    import re

    chunk_dicts = []

    for i, (lc, emb) in enumerate(zip(chunks, embeddings)):
        text_search = re.sub(r'\s+', ' ', lc.text).strip().lower()

        chunk_dicts.append({
            "id": str(uuid.uuid4()),
            "document_id": doc_id,
            "text": lc.text,
            "text_search": text_search,
            "char_count": lc.char_count,
            "embedding_json": embedder.to_json(emb),
            "embedding_model": embedder.model_name,
            "chunk_index": i,
            "page_number": lc.page_number,
            "section": lc.section,
            "article_reference": lc.article_reference,
            "source_type": meta.source_type.value,
            "source_hierarchy": meta.source_hierarchy.value,
            "jurisdiction": meta.jurisdiction,
            "legal_area": meta.legal_area,
        })

    store.add_chunks(doc_id, chunk_dicts)
    return chunk_dicts


# ═══════════════════════════════════════════════════════════
# ORCHESTRATOR: run_pipeline
# ═══════════════════════════════════════════════════════════

async def run_pipeline(
    doc_id: str,
    text_raw: str,
    metadata_input: dict,
    parse_result: ParseResult,
    store,
    embedder,
) -> PipelineResult:
    """
    Ejecutar el pipeline completo de ingestión (pasos 2-6).

    Entrada: texto crudo ya extraído + metadata del llamador.
    Salida: PipelineResult con documento y chunks almacenados.

    Paso 1 (parse) se realiza antes de llamar a esta función,
    porque depende del origen (archivo vs texto manual).
    """
    # Paso 2: Normalizar
    normalize = await normalize_text(text_raw)
    text_clean = normalize.text_clean

    if not text_clean or len(text_clean.strip()) < 10:
        return PipelineResult(
            document_id=doc_id,
            document={},
            chunks=[],
            status="error",
            error="Texto extraído vacío o demasiado corto.",
        )

    # Paso 3: Metadatos
    meta = extract_metadata(metadata_input)

    # Paso 4: Chunking
    legal_chunks = chunk_document(text_clean, meta.source_type)

    # Embeddings (placeholder en esta etapa)
    chunk_texts = [c.text for c in legal_chunks]
    embeddings = embedder.generate_batch(chunk_texts) if chunk_texts else []

    # Paso 5: Persistir documento
    document = persist_document(
        doc_id=doc_id,
        text_raw=text_raw,
        text_clean=text_clean,
        meta=meta,
        parse=parse_result,
        normalize=normalize,
        chunk_count=len(legal_chunks),
        store=store,
    )

    # Paso 6: Persistir chunks
    chunk_dicts = persist_chunks(
        doc_id=doc_id,
        chunks=legal_chunks,
        embeddings=embeddings,
        meta=meta,
        embedder=embedder,
        store=store,
    )

    return PipelineResult(
        document_id=doc_id,
        document=document,
        chunks=chunk_dicts,
        status="indexed",
        chunk_count=len(chunk_dicts),
        total_chars=len(text_clean),
        source_type=meta.source_type.value,
        source_hierarchy=meta.source_hierarchy.value,
        detected_type=normalize.doc_type_detected,
    )
