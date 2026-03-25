"""
AILEX — Módulo de Ingestión Documental.

Pipeline completo:
1. Recibir archivo (PDF/DOCX/TXT) o texto manual
2. Extraer texto crudo
3. Normalizar (módulo normalization)
4. Detectar encabezados jurídicos
5. Particionar en chunks jurídicos
6. Generar embeddings
7. Almacenar documento + chunks en base de datos
"""

import logging
import os
import re
import unicodedata
import uuid
import json
import hashlib
from datetime import datetime

from app.config import settings
from app.modules.ingestion.extractor import TextExtractor
from app.modules.ingestion.chunker import LegalChunker
from app.modules.ingestion.embedder import EmbeddingGenerator
from app.modules.ingestion.ocr_service import OCRService
from app.modules.normalization.service import NormalizationService
from app.db.models import (
    SourceDocument, DocumentChunk, DocumentStatus, DocumentScope,
    SourceTypeEnum, SourceHierarchyEnum, AuthorityLevel,
    SOURCE_TYPE_TO_HIERARCHY, SOURCE_TYPE_TO_AUTHORITY,
)


# Directorio para almacenar archivos cargados
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "storage", "documents"
)

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Servicio de ingestión documental.
    Orquesta todo el pipeline desde la carga hasta el indexado.
    """

    SUPPORTED_FORMATS = {"pdf", "docx", "txt"}

    def __init__(self, use_placeholder_embeddings: bool = True):
        self.extractor = TextExtractor()
        self.ocr_service = OCRService()
        self.chunker = LegalChunker()
        self.embedder = EmbeddingGenerator(use_placeholder=use_placeholder_embeddings)
        self.normalizer = NormalizationService()
        self.ocr_min_text_chars = settings.ocr_min_text_chars
        self.ocr_max_file_size_bytes = settings.ocr_max_file_size_mb * 1024 * 1024

    async def ingest_file(
        self,
        file_content: bytes,
        filename: str,
        metadata: dict,
    ) -> dict:
        """
        Pipeline completo de ingestión desde archivo.

        Args:
            file_content: contenido binario del archivo
            filename: nombre original del archivo
            metadata: dict con source_type, jurisdiction, legal_area, etc.

        Returns:
            dict con document_id, chunk_count, status
        """
        # Validar formato
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        if ext not in self.SUPPORTED_FORMATS:
            return {
                "status": "error",
                "message": f"Formato no soportado: {ext}. Usar: {', '.join(self.SUPPORTED_FORMATS)}",
            }

        # Generar ID
        doc_id = str(uuid.uuid4())

        # Guardar archivo
        file_path = self._save_file(file_content, doc_id, filename)

        extraction = None
        raw_text = ""
        extraction_error = None

        # Extraer texto
        try:
            extraction = self.extractor.extract(file_path)
            raw_text = extraction.get("text", "")
            logger.info(
                "Extraccion primaria completada para %s con metodo=%s chars=%s",
                filename,
                extraction.get("method", "unknown"),
                len(raw_text),
            )
        except Exception as e:
            extraction_error = str(e)
            logger.warning(
                "Extraccion primaria fallo para %s: %s",
                filename,
                extraction_error,
            )

        extraction_info = self._build_extraction_info(
            file_type=ext,
            extraction=extraction,
            raw_text=raw_text,
            extraction_mode="pdf_text" if ext == "pdf" else "file_text",
            ocr_used=False,
            warning="",
        )

        if ext == "pdf" and (extraction_error or self._should_use_ocr_fallback(raw_text)):
            fallback_reason = (
                f"error de extraccion primaria: {extraction_error}"
                if extraction_error
                else f"texto insuficiente ({self._meaningful_text_length(raw_text)} caracteres significativos)"
            )
            logger.info("OCR fallback activado para %s por %s", filename, fallback_reason)
            try:
                ocr_result = self._run_ocr_fallback(file_path, file_content)
                raw_text = ocr_result["text"]
                extraction_info = self._build_extraction_info(
                    file_type=ext,
                    extraction=ocr_result,
                    raw_text=raw_text,
                    extraction_mode="ocr",
                    ocr_used=True,
                    warning=ocr_result.get("warning", ""),
                )
            except Exception as ocr_error:
                logger.exception("OCR fallback fallo para %s", filename)
                if extraction_error:
                    message = (
                        "Error extrayendo texto del PDF y OCR fallback fallo. "
                        f"Extraccion primaria: {extraction_error}. OCR: {ocr_error}"
                    )
                else:
                    message = (
                        "Texto PDF insuficiente y OCR fallback fallo. "
                        f"OCR: {ocr_error}"
                    )
                return {
                    "status": "error",
                    "message": message,
                    "document_id": doc_id,
                }
        elif extraction_error:
            return {
                "status": "error",
                "message": f"Error extrayendo texto: {extraction_error}",
                "document_id": doc_id,
            }

        # Pipeline de procesamiento
        return await self._process_text(
            doc_id=doc_id,
            raw_text=raw_text,
            filename=filename,
            file_path=file_path,
            file_type=ext,
            metadata=metadata,
            extraction_info=extraction_info,
        )

    async def ingest_text(
        self,
        text: str,
        title: str,
        metadata: dict,
    ) -> dict:
        """
        Pipeline de ingestión desde texto manual.

        Args:
            text: texto completo
            title: título del documento
            metadata: clasificación y metadatos
        """
        doc_id = str(uuid.uuid4())

        return await self._process_text(
            doc_id=doc_id,
            raw_text=text,
            filename=title,
            file_path=None,
            file_type="txt",
            metadata=metadata,
            extraction_info={
                "extraction_mode": "text_manual",
                "extraction_method": "text_manual",
                "ocr_used": False,
                "extracted_text_length": len(text.strip()),
                "extraction_warning": "",
                "page_count": 1,
                "ocr_pages_processed": 0,
            },
        )

    async def _process_text(
        self,
        doc_id: str,
        raw_text: str,
        filename: str,
        file_path: str,
        file_type: str,
        metadata: dict,
        extraction_info: dict | None = None,
    ) -> dict:
        """Pipeline interno de procesamiento de texto."""

        extraction_info = extraction_info or {}

        if not raw_text or len(raw_text.strip()) < 10:
            return {
                "status": "error",
                "message": self._build_empty_text_error(extraction_info),
                "document_id": doc_id,
            }

        # 1. Normalizar
        normalized = await self.normalizer.normalize(raw_text)
        clean_text = normalized["text_clean"]

        if not clean_text or len(clean_text.strip()) < 10:
            return {
                "status": "error",
                "message": self._build_empty_text_error(extraction_info),
                "document_id": doc_id,
            }

        inferred_title = self._resolve_title(metadata, clean_text, filename)
        inferred_source_type = self._resolve_source_type(metadata, clean_text)
        inferred_jurisdiction = self._resolve_jurisdiction(metadata, clean_text)
        inferred_legal_area = self._resolve_legal_area(metadata, clean_text)
        inferred_tags = self._resolve_tags(metadata, clean_text, inferred_source_type)
        document_scope = self._resolve_document_scope(metadata)
        should_index_in_corpus = document_scope == DocumentScope.CORPUS

        # 2. Detectar entidades y tipo de documento
        entities = normalized.get("entities", {})
        detected_type = normalized.get("doc_type", "desconocido")

        # 3. Resolver clasificación jurídica
        source_type = inferred_source_type
        source_hierarchy = SOURCE_TYPE_TO_HIERARCHY.get(
            source_type, SourceHierarchyEnum.INTERNO
        )
        authority_level = SOURCE_TYPE_TO_AUTHORITY.get(
            source_type, AuthorityLevel.REFERENCIAL
        )

        # 4. Chunking jurídico (con contexto de tipo de fuente)
        legal_chunks = self.chunker.chunk(clean_text, source_type=source_type.value)

        # 5. Generar embeddings
        chunk_texts = [c.text for c in legal_chunks]
        if should_index_in_corpus and chunk_texts:
            embeddings = self.embedder.generate_batch(chunk_texts)
        else:
            embeddings = [None] * len(chunk_texts)

        # 6. Construir objetos para almacenamiento
        document = {
            "id": doc_id,
            "title": inferred_title,
            "description": metadata.get("description", ""),
            "file_path": file_path,
            "file_type": file_type,
            "content_raw": raw_text,
            "source_type": source_type.value,
            "source_hierarchy": source_hierarchy.value,
            "authority_level": authority_level.value,
            "jurisdiction": inferred_jurisdiction,
            "court": metadata.get("court", ""),
            "legal_area": inferred_legal_area,
            "fuero": metadata.get("fuero", ""),
            "document_date": metadata.get("document_date"),
            "authority": metadata.get("authority", ""),
            "nivel_jerarquia": metadata.get("nivel_jerarquia", ""),
            "vigente": metadata.get("vigente", True),
            "reliability_score": metadata.get("reliability_score", 0.5),
            "origin": metadata.get("origin", "carga_manual"),
            "tags": inferred_tags,
            "hash_documento": self._build_content_hash(raw_text),
            "document_scope": document_scope.value,
            "expediente_id": metadata.get("expediente_id") or None,
            "status": (
                DocumentStatus.INDEXED.value
                if should_index_in_corpus
                else DocumentStatus.PENDING.value
            ),
            "chunk_count": len(legal_chunks),
            "total_chars": len(clean_text),
            "detected_type": detected_type,
            "entities": entities,
            "extraction_mode": extraction_info.get("extraction_mode", "unknown"),
            "extraction_method": extraction_info.get("extraction_method", ""),
            "ocr_used": extraction_info.get("ocr_used", False),
            "extracted_text_length": extraction_info.get("extracted_text_length", len(raw_text.strip())),
            "extraction_warning": extraction_info.get("extraction_warning", ""),
            "page_count": extraction_info.get("page_count"),
            "ocr_pages_processed": extraction_info.get("ocr_pages_processed"),
        }

        chunks = []
        for i, (lc, emb) in enumerate(zip(legal_chunks, embeddings)):
            chunks.append({
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "text": lc.text,
                "text_search": self._prepare_search_text(lc.text),
                "char_count": lc.char_count,
                "embedding_json": self.embedder.to_json(emb) if emb is not None else None,
                "embedding_model": self.embedder.model_name if emb is not None else "",
                "chunk_index": i,
                "page_number": lc.page_number,
                "section": lc.section,
                "article_reference": lc.article_reference,
                "source_type": source_type.value,
                "source_hierarchy": source_hierarchy.value,
                "jurisdiction": inferred_jurisdiction,
                "legal_area": inferred_legal_area,
                "document_scope": document_scope.value,
            })

        return {
            "status": "indexed" if should_index_in_corpus else "stored",
            "document_id": doc_id,
            "title": document["title"],
            "chunk_count": len(chunks),
            "total_chars": document["total_chars"],
            "source_type": source_type.value,
            "source_hierarchy": source_hierarchy.value,
            "document_scope": document_scope.value,
            "indexed_in_corpus": should_index_in_corpus,
            "detected_type": detected_type,
            "extraction_mode": document["extraction_mode"],
            "ocr_used": document["ocr_used"],
            "extracted_text_length": document["extracted_text_length"],
            "extraction_warning": document["extraction_warning"],
            "analysis_text": clean_text if document_scope == DocumentScope.CASE else "",
            "document": document,
            "chunks": chunks,
        }

    def _meaningful_text_length(self, text: str) -> int:
        """Contar caracteres significativos ignorando espacios y puntuación."""
        if not text:
            return 0
        return len(re.sub(r"[\W_]+", "", text, flags=re.UNICODE))

    def _should_use_ocr_fallback(self, raw_text: str) -> bool:
        """Determinar si el texto extraído amerita OCR fallback."""
        return self._meaningful_text_length(raw_text) < self.ocr_min_text_chars

    def _run_ocr_fallback(self, file_path: str, file_content: bytes) -> dict:
        """Ejecutar OCR con guardrails básicos para PDFs grandes."""
        if len(file_content) > self.ocr_max_file_size_bytes:
            raise RuntimeError(
                "OCR omitido: el archivo supera el maximo configurado "
                f"de {settings.ocr_max_file_size_mb} MB."
            )
        return self.ocr_service.extract_pdf(file_path)

    def _build_extraction_info(
        self,
        file_type: str,
        extraction: dict | None,
        raw_text: str,
        extraction_mode: str,
        ocr_used: bool,
        warning: str,
    ) -> dict:
        extraction = extraction or {}
        page_count = extraction.get("pages", extraction.get("total_pages", 1))
        ocr_pages_processed = extraction.get("pages_processed", 0)
        return {
            "extraction_mode": extraction_mode,
            "extraction_method": extraction.get("method", file_type),
            "ocr_used": ocr_used,
            "extracted_text_length": len((raw_text or "").strip()),
            "extraction_warning": warning or "",
            "page_count": page_count,
            "ocr_pages_processed": ocr_pages_processed,
        }

    def _normalize_heuristic_text(self, text: str) -> str:
        """Normalizar texto para heurísticas livianas de clasificación."""
        normalized = unicodedata.normalize("NFD", text or "")
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        return normalized.lower()

    def _resolve_title(self, metadata: dict, clean_text: str, fallback: str) -> str:
        """Inferir un titulo razonable cuando el usuario no lo provee."""
        raw_title = (metadata.get("title") or "").strip()
        if raw_title and raw_title != fallback:
            return raw_title

        for line in clean_text.splitlines():
            candidate = line.strip(" -:\t")
            if 8 <= len(candidate) <= 120:
                return candidate

        return raw_title or fallback

    def _resolve_source_type(self, metadata: dict, clean_text: str) -> SourceTypeEnum:
        """Resolver tipo documental desde selector simple o heurísticas."""
        raw_type = (metadata.get("source_type") or "").strip().lower()
        selector_map = {
            "norma": SourceTypeEnum.LEY,
            "jurisprudencia": SourceTypeEnum.JURISPRUDENCIA,
            "doctrina": SourceTypeEnum.DOCTRINA,
            "interno": SourceTypeEnum.ESCRITO,
        }

        if raw_type in selector_map:
            return selector_map[raw_type]

        if raw_type and raw_type not in {"automatico", "automatic", "auto"}:
            try:
                return SourceTypeEnum(raw_type)
            except ValueError:
                pass

        text = self._normalize_heuristic_text(clean_text)
        if any(term in text for term in ("codigo", "constitucion", "articulo", "capitulo", "ley", "reglamento", "acordada")):
            if "codigo" in text:
                return SourceTypeEnum.CODIGO
            if "acordada" in text:
                return SourceTypeEnum.ACORDADA
            if "reglamento" in text or "decreto" in text:
                return SourceTypeEnum.REGLAMENTO
            return SourceTypeEnum.LEY

        if any(term in text for term in ("autos", "sentencia", "tribunal", "juez", "juzgado", "fallo", "resuelve")):
            return SourceTypeEnum.JURISPRUDENCIA

        if any(term in text for term in ("doctrina", "tratado", "comentario", "manual", "autor", "bibliografia")):
            return SourceTypeEnum.DOCTRINA

        return SourceTypeEnum.ESCRITO

    def _resolve_jurisdiction(self, metadata: dict, clean_text: str) -> str:
        """Inferir jurisdicción si no viene explícita."""
        raw_value = (metadata.get("jurisdiction") or "").strip()
        if raw_value:
            return raw_value

        text = self._normalize_heuristic_text(clean_text)
        known = {
            "jujuy": "Jujuy",
            "nacion": "Nacional",
            "nacional": "Nacional",
            "buenos aires": "Buenos Aires",
            "cordoba": "Cordoba",
            "mendoza": "Mendoza",
            "salta": "Salta",
            "tucuman": "Tucuman",
            "chaco": "Chaco",
            "santa fe": "Santa Fe",
        }
        for needle, label in known.items():
            if needle in text:
                return label

        return settings.rag_default_jurisdiction

    def _resolve_legal_area(self, metadata: dict, clean_text: str) -> str:
        """Inferir materia legal básica si no viene explícita."""
        raw_value = (metadata.get("legal_area") or "").strip()
        if raw_value:
            return raw_value

        text = self._normalize_heuristic_text(clean_text)
        areas = (
            ("constitucional", "constitucional"),
            ("penal", "penal"),
            ("laboral", "laboral"),
            ("familia", "familia"),
            ("administrativo", "administrativo"),
            ("comercial", "comercial"),
            ("civil", "civil"),
            ("procesal", "procesal"),
        )
        for needle, label in areas:
            if needle in text:
                return label
        return ""

    def _resolve_tags(
        self,
        metadata: dict,
        clean_text: str,
        source_type: SourceTypeEnum,
    ) -> str:
        """Completar etiquetas simples cuando el usuario no las carga."""
        raw_value = (metadata.get("tags") or "").strip()
        if raw_value:
            return raw_value

        text = self._normalize_heuristic_text(clean_text)
        detected = []
        tag_candidates = (
            ("articulo", "articulos"),
            ("cedula", "cedula"),
            ("notificacion", "notificacion"),
            ("sentencia", "sentencia"),
            ("contrato", "contrato"),
            ("demanda", "demanda"),
            ("prueba", "prueba"),
            ("amparo", "amparo"),
        )
        for needle, label in tag_candidates:
            if needle in text and label not in detected:
                detected.append(label)

        hierarchy_tag = {
            SourceTypeEnum.LEY: "normativa",
            SourceTypeEnum.CODIGO: "normativa",
            SourceTypeEnum.REGLAMENTO: "normativa",
            SourceTypeEnum.ACORDADA: "normativa",
            SourceTypeEnum.JURISPRUDENCIA: "jurisprudencia",
            SourceTypeEnum.DOCTRINA: "doctrina",
            SourceTypeEnum.ESCRITO: "interno",
        }.get(source_type)
        if hierarchy_tag and hierarchy_tag not in detected:
            detected.insert(0, hierarchy_tag)

        return ", ".join(detected)

    def _resolve_document_scope(self, metadata: dict) -> DocumentScope:
        """Resolver si el documento pertenece al corpus global o a un caso."""
        raw_scope = (metadata.get("document_scope") or metadata.get("scope") or "").strip().lower()
        if raw_scope == DocumentScope.CASE.value:
            return DocumentScope.CASE
        return DocumentScope.CORPUS

    def _build_empty_text_error(self, extraction_info: dict) -> str:
        """Mensaje de error claro cuando no hubo texto útil tras extraer/OCR."""
        mode = extraction_info.get("extraction_mode") or "desconocido"
        if mode == "ocr":
            return "OCR ejecutado pero el texto extraido resulto vacio o demasiado corto."
        if mode == "text_manual":
            return "Texto manual vacio o demasiado corto."
        return "Texto extraido vacio o demasiado corto."

    def _save_file(self, content: bytes, doc_id: str, filename: str) -> str:
        """Guardar archivo en el almacén local."""
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        ext = os.path.splitext(filename)[1]
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}{ext}")
        with open(file_path, "wb") as f:
            f.write(content)
        return file_path

    def _prepare_search_text(self, text: str) -> str:
        """
        Preparar texto para búsqueda keyword.
        Normalización básica para full-text search.
        """
        import re
        # Lowercase, quitar acentos no sería ideal en español
        # pero sí normalizar espacios y puntuación excesiva
        text = re.sub(r'\s+', ' ', text)
        text = text.strip().lower()
        return text

    def _build_content_hash(self, text: str) -> str:
        """Hash estable del contenido para deduplicacion liviana."""
        normalized = (text or "").strip().encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()
