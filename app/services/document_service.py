"""
AILEX -- Servicio documental con persistencia SQLAlchemy.

Mantiene la API interna de documentos desacoplada del almacenamiento
concreto. En esta etapa SQLAlchemy es la fuente de verdad y DocumentStore
queda sincronizado como fallback/cache temporal para compatibilidad.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import get_default_provider
from app.db.models import (
    AuthorityLevel,
    DocumentChunk,
    DocumentScope,
    DocumentStatus,
    SourceDocument,
    SourceHierarchyEnum,
    SourceTypeEnum,
)
from app.db.store import DocumentStore


class DocumentService:
    """Acceso unificado a documentos y chunks."""

    def __init__(
        self,
        store: Optional[DocumentStore] = None,
        embedder: Optional[EmbeddingProvider] = None,
    ) -> None:
        self.store = store or DocumentStore()
        self.embedder = embedder or get_default_provider()
        self._store_bootstrapped = False

    def _bootstrap_store_from_db(self, db: Session) -> None:
        if self._store_bootstrapped:
            return

        documents = db.query(SourceDocument).all()
        for document in documents:
            doc_payload = self._document_to_payload(document, include_content=True)
            chunk_payloads = [
                self._chunk_to_payload(chunk)
                for chunk in (
                    db.query(DocumentChunk)
                    .filter(DocumentChunk.document_id == document.id)
                    .order_by(DocumentChunk.chunk_index.asc())
                    .all()
                )
            ]
            self.store.add_document(doc_payload)
            self.store.add_chunks(document.id, chunk_payloads)

        self._store_bootstrapped = True

    def _document_to_payload(
        self,
        document: SourceDocument,
        *,
        include_content: bool = False,
    ) -> dict:
        try:
            entities = json.loads(document.entities_json or "{}")
        except (TypeError, ValueError):
            entities = {}

        payload = {
            "id": document.id,
            "user_id": document.user_id,
            "title": document.title,
            "description": document.description or "",
            "source_type": document.source_type.value if document.source_type else "",
            "source_hierarchy": (
                document.source_hierarchy.value if document.source_hierarchy else ""
            ),
            "authority_level": (
                document.authority_level.value if document.authority_level else ""
            ),
            "jurisdiction": document.jurisdiction or "",
            "fuero": document.fuero or "",
            "legal_area": document.legal_area or "",
            "court": document.court or "",
            "document_date": document.document_date,
            "authority": document.authority or "",
            "nivel_jerarquia": document.nivel_jerarquia or "",
            "vigente": document.vigente,
            "origin": document.origin or "",
            "tags": document.tags or "",
            "detected_type": document.detected_type or "",
            "entities": entities,
            "extraction_mode": document.extraction_mode or "",
            "extraction_method": document.extraction_method or "",
            "ocr_used": bool(document.ocr_used),
            "extracted_text_length": document.extracted_text_length or 0,
            "extraction_warning": document.extraction_warning or "",
            "page_count": document.page_count,
            "ocr_pages_processed": document.ocr_pages_processed,
            "document_scope": (
                document.document_scope.value if document.document_scope else ""
            ),
            "expediente_id": document.expediente_id,
            "file_path": document.file_path,
            "file_type": document.file_type or "",
            "hash_documento": document.hash_documento,
            "reliability_score": document.reliability_score,
            "status": document.status.value if document.status else "",
            "chunk_count": document.chunk_count or 0,
            "total_chars": document.total_chars or 0,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        }
        if include_content:
            payload["content_raw"] = document.content_raw
        return payload

    def _chunk_to_payload(self, chunk: DocumentChunk) -> dict:
        return {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "text": chunk.text,
            "text_search": chunk.text_search or "",
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "section": chunk.section or "",
            "article_reference": chunk.article_reference or "",
            "char_count": chunk.char_count or 0,
            "embedding_json": chunk.embedding_json,
            "embedding_model": chunk.embedding_model or "",
            "source_type": chunk.source_type or "",
            "source_hierarchy": chunk.source_hierarchy or "",
            "jurisdiction": chunk.jurisdiction or "",
            "legal_area": chunk.legal_area or "",
        }

    def _sync_store_document(self, db: Session, document_id: str) -> None:
        document = db.get(SourceDocument, document_id)
        if document is None:
            self.store.delete_document(document_id)
            return

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        self.store.add_document(self._document_to_payload(document, include_content=True))
        self.store.add_chunks(document_id, [self._chunk_to_payload(chunk) for chunk in chunks])

    def _coerce_source_type(self, value: str) -> SourceTypeEnum:
        return value if isinstance(value, SourceTypeEnum) else SourceTypeEnum(value)

    def _coerce_source_hierarchy(self, value: str) -> SourceHierarchyEnum:
        return (
            value
            if isinstance(value, SourceHierarchyEnum)
            else SourceHierarchyEnum(value)
        )

    def _coerce_authority_level(self, value: str) -> AuthorityLevel:
        return value if isinstance(value, AuthorityLevel) else AuthorityLevel(value)

    def _coerce_document_scope(self, value: str) -> DocumentScope:
        return value if isinstance(value, DocumentScope) else DocumentScope(value)

    def _coerce_document_status(self, value: str) -> DocumentStatus:
        return value if isinstance(value, DocumentStatus) else DocumentStatus(value)

    def create_from_ingestion_result(
        self,
        db: Session,
        result: dict,
        user_id: Optional[str] = None,
    ) -> dict:
        self._bootstrap_store_from_db(db)

        document_data = result["document"]
        chunks_data = result["chunks"]
        entities = document_data.get("entities") or {}

        document = SourceDocument(
            id=document_data["id"],
            user_id=user_id or document_data.get("user_id"),
            title=document_data["title"],
            description=document_data.get("description", ""),
            source_type=self._coerce_source_type(document_data["source_type"]),
            source_hierarchy=self._coerce_source_hierarchy(
                document_data["source_hierarchy"]
            ),
            authority_level=self._coerce_authority_level(
                document_data["authority_level"]
            ),
            jurisdiction=document_data.get("jurisdiction", ""),
            fuero=document_data.get("fuero", ""),
            legal_area=document_data.get("legal_area", ""),
            court=document_data.get("court", ""),
            document_date=document_data.get("document_date"),
            authority=document_data.get("authority", ""),
            nivel_jerarquia=document_data.get("nivel_jerarquia", ""),
            vigente=document_data.get("vigente", True),
            origin=document_data.get("origin", ""),
            tags=document_data.get("tags", ""),
            detected_type=document_data.get("detected_type", ""),
            entities_json=json.dumps(entities, ensure_ascii=False, default=str),
            extraction_mode=document_data.get("extraction_mode", ""),
            extraction_method=document_data.get("extraction_method", ""),
            ocr_used=bool(document_data.get("ocr_used", False)),
            extracted_text_length=document_data.get("extracted_text_length", 0) or 0,
            extraction_warning=document_data.get("extraction_warning", ""),
            page_count=document_data.get("page_count"),
            ocr_pages_processed=document_data.get("ocr_pages_processed"),
            document_scope=self._coerce_document_scope(
                document_data.get("document_scope", "corpus")
            ),
            file_path=document_data.get("file_path"),
            file_type=document_data.get("file_type", "txt"),
            content_raw=document_data.get("content_raw"),
            hash_documento=document_data.get("hash_documento"),
            reliability_score=document_data.get("reliability_score", 0.5),
            status=self._coerce_document_status(document_data.get("status", "pending")),
            chunk_count=document_data.get("chunk_count", len(chunks_data)),
            total_chars=document_data.get("total_chars", 0),
            expediente_id=document_data.get("expediente_id"),
        )
        db.add(document)

        for chunk_data in chunks_data:
            db.add(
                DocumentChunk(
                    id=chunk_data["id"],
                    document_id=document.id,
                    text=chunk_data["text"],
                    text_search=chunk_data.get("text_search", ""),
                    chunk_index=chunk_data["chunk_index"],
                    page_number=chunk_data.get("page_number"),
                    section=chunk_data.get("section", ""),
                    article_reference=chunk_data.get("article_reference", ""),
                    char_count=chunk_data.get("char_count", 0),
                    embedding_json=chunk_data.get("embedding_json"),
                    embedding_model=chunk_data.get("embedding_model", ""),
                    source_type=chunk_data.get("source_type", ""),
                    source_hierarchy=chunk_data.get("source_hierarchy", ""),
                    jurisdiction=chunk_data.get("jurisdiction", ""),
                    legal_area=chunk_data.get("legal_area", ""),
                )
            )

        db.commit()
        self._sync_store_document(db, document.id)
        return self.get_document(db, document.id)

    def list_documents(
        self,
        db: Session,
        *,
        user_id: Optional[str] = None,
        source_hierarchy: Optional[str] = None,
        source_type: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        legal_area: Optional[str] = None,
        document_scope: Optional[str] = None,
        expediente_id: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        self._bootstrap_store_from_db(db)

        query = db.query(SourceDocument)
        if user_id:
            query = query.filter(SourceDocument.user_id == user_id)
        if expediente_id:
            query = query.filter(SourceDocument.expediente_id == expediente_id)
        if document_scope:
            query = query.filter(
                SourceDocument.document_scope == self._coerce_document_scope(document_scope)
            )
        if source_hierarchy:
            try:
                query = query.filter(
                    SourceDocument.source_hierarchy
                    == self._coerce_source_hierarchy(source_hierarchy)
                )
            except ValueError:
                return {"documents": [], "total": 0, "page": page, "per_page": per_page}
        if source_type:
            try:
                query = query.filter(
                    SourceDocument.source_type == self._coerce_source_type(source_type)
                )
            except ValueError:
                return {"documents": [], "total": 0, "page": page, "per_page": per_page}
        if jurisdiction:
            query = query.filter(func.lower(SourceDocument.jurisdiction) == jurisdiction.lower())
        if legal_area:
            query = query.filter(func.lower(SourceDocument.legal_area) == legal_area.lower())

        total = query.count()
        documents = (
            query.order_by(SourceDocument.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "documents": [self._document_to_payload(doc) for doc in documents],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    def get_document(
        self,
        db: Session,
        document_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[dict]:
        self._bootstrap_store_from_db(db)
        document = db.get(SourceDocument, document_id)
        if document is None:
            return None
        # Reglas de acceso:
        # - corpus → acceso libre
        # - case → requiere ownership

        if document.document_scope == DocumentScope.CASE:
            if user_id and document.user_id != user_id:
                return None
        payload = self._document_to_payload(document, include_content=True)
        self.store.add_document(payload)
        return payload

    def get_chunks(self, db: Session, document_id: str) -> list[dict]:
        self._bootstrap_store_from_db(db)
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        payloads = [self._chunk_to_payload(chunk) for chunk in chunks]
        if payloads:
            self.store.add_chunks(document_id, payloads)
        return payloads

    def get_all_chunks(
        self,
        db: Session,
        document_scope: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """
        Return all chunks enriched with parent-document metadata.

        This replaces ``DocumentStore.get_all_chunks()`` with a real
        SQLAlchemy query.  Each chunk dict gets ``document_title``,
        ``document_scope`` and ``vigente`` merged in — the same shape
        that ``HybridSearchService`` expects.
        """
        query = (
            db.query(DocumentChunk, SourceDocument)
            .join(SourceDocument, DocumentChunk.document_id == SourceDocument.id)
        )
        if document_scope:
            query = query.filter(
                SourceDocument.document_scope == self._coerce_document_scope(document_scope)
            )

        query = query.order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        if isinstance(limit, int) and limit > 0:
            query = query.limit(limit)

        rows = query.all()

        results: list[dict] = []
        for chunk, doc in rows:
            payload = self._chunk_to_payload(chunk)
            payload["document_title"] = doc.title or ""
            payload["document_scope"] = doc.document_scope.value if doc.document_scope else ""
            payload["vigente"] = doc.vigente if doc.vigente is not None else True
            results.append(payload)
        return results

    def get_expediente_chunks(
        self,
        db: Session,
        expediente_id: str,
    ) -> list[dict]:
        """
        Return all chunks from documents linked to an expediente.

        Includes both scope=case and scope=corpus documents that have
        the given expediente_id FK set. Each chunk dict is enriched
        with parent-document metadata (same shape as get_all_chunks).
        """
        rows = (
            db.query(DocumentChunk, SourceDocument)
            .join(SourceDocument, DocumentChunk.document_id == SourceDocument.id)
            .filter(SourceDocument.expediente_id == expediente_id)
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .all()
        )

        results: list[dict] = []
        for chunk, doc in rows:
            payload = self._chunk_to_payload(chunk)
            payload["document_title"] = doc.title or ""
            payload["document_scope"] = doc.document_scope.value if doc.document_scope else ""
            payload["vigente"] = doc.vigente if doc.vigente is not None else True
            payload["expediente_id"] = doc.expediente_id
            results.append(payload)
        return results

    def delete_document(
        self,
        db: Session,
        document_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        self._bootstrap_store_from_db(db)
        document = db.get(SourceDocument, document_id)
        if document is None:
            return False
        # Política de acceso alineada con get_document():
        # - corpus → no depende de ownership individual
        # - case → requiere ownership
        if document.document_scope == DocumentScope.CASE:
            if user_id and document.user_id != user_id:
                return False
        db.delete(document)
        db.commit()
        self.store.delete_document(document_id)
        return True

    def get_stats(
        self,
        db: Session,
        document_scope: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        self._bootstrap_store_from_db(db)

        query = db.query(SourceDocument)
        if user_id:
            query = query.filter(SourceDocument.user_id == user_id)
        if document_scope:
            query = query.filter(
                SourceDocument.document_scope == self._coerce_document_scope(document_scope)
            )

        documents = query.all()
        document_ids = [doc.id for doc in documents]
        total_chunks = 0
        if document_ids:
            total_chunks = (
                db.query(func.count(DocumentChunk.id))
                .filter(DocumentChunk.document_id.in_(document_ids))
                .scalar()
                or 0
            )

        by_hierarchy: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for document in documents:
            hierarchy = (
                document.source_hierarchy.value
                if document.source_hierarchy
                else "desconocido"
            )
            source_type = document.source_type.value if document.source_type else "desconocido"
            by_hierarchy[hierarchy] = by_hierarchy.get(hierarchy, 0) + 1
            by_type[source_type] = by_type.get(source_type, 0) + 1

        return {
            "total_documents": len(documents),
            "total_chunks": total_chunks,
            "by_hierarchy": by_hierarchy,
            "by_type": by_type,
        }

    def update_document_scope(self, db: Session, document_id: str, target_scope: str) -> Optional[dict]:
        self._bootstrap_store_from_db(db)
        document = db.get(SourceDocument, document_id)
        if document is None:
            return None

        scope = self._coerce_document_scope(target_scope)
        document.document_scope = scope
        if scope == DocumentScope.CASE:
            document.status = DocumentStatus.PENDING
        db.commit()
        self._sync_store_document(db, document_id)
        return self.get_document(db, document_id)

    def index_document(self, db: Session, document_id: str) -> dict:
        self._bootstrap_store_from_db(db)
        document = db.get(SourceDocument, document_id)
        if document is None:
            return {
                "status": "error",
                "document_id": document_id,
                "error": "Documento no encontrado.",
                "chunks_indexed": 0,
            }

        if document.document_scope != DocumentScope.CORPUS:
            return {
                "status": "skipped",
                "document_id": document_id,
                "document_title": document.title,
                "chunks_indexed": 0,
                "error": "Solo se indexan documentos con scope corpus.",
            }

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        if not chunks:
            return {
                "status": "no_chunks",
                "document_id": document_id,
                "document_title": document.title,
                "chunks_indexed": 0,
                "message": "El documento no tiene chunks para indexar.",
            }

        try:
            embeddings = self.embedder.embed_batch([chunk.text for chunk in chunks])
        except Exception as exc:
            return {
                "status": "error",
                "document_id": document_id,
                "error": f"Error generando embeddings: {exc}",
                "chunks_indexed": 0,
            }

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding_json = self.embedder.to_json(embedding)
            chunk.embedding_model = self.embedder.model_name

        document.status = DocumentStatus.INDEXED
        db.commit()
        self._sync_store_document(db, document_id)

        return {
            "status": "indexed",
            "document_id": document_id,
            "document_title": document.title,
            "chunks_indexed": len(chunks),
            "embedding_model": self.embedder.model_name,
            "errors": [],
        }

    def get_indexing_status(self, db: Session, document_id: str) -> dict:
        self._bootstrap_store_from_db(db)
        document = db.get(SourceDocument, document_id)
        if document is None:
            return {"status": "not_found", "document_id": document_id}

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        total = len(chunks)
        if total == 0:
            return {
                "status": "no_chunks",
                "document_id": document_id,
                "document_title": document.title,
                "total_chunks": 0,
                "indexed_chunks": 0,
            }

        indexed = sum(1 for chunk in chunks if chunk.embedding_json)
        models_used = sorted(
            {
                chunk.embedding_model
                for chunk in chunks
                if chunk.embedding_model
            }
        )
        status = "indexed" if indexed == total else "partial" if indexed > 0 else "not_indexed"

        return {
            "status": status,
            "document_id": document_id,
            "document_title": document.title,
            "total_chunks": total,
            "indexed_chunks": indexed,
            "embedding_models": models_used,
        }

    async def reindex_all(
        self,
        db: Session,
        user_id: Optional[str] = None,
    ) -> dict:
        self._bootstrap_store_from_db(db)

        query = db.query(SourceDocument).filter(
            SourceDocument.document_scope == DocumentScope.CORPUS
        )
        if user_id:
            query = query.filter(SourceDocument.user_id == user_id)
        documents = (
            query.order_by(SourceDocument.created_at.desc())
            .all()
        )
        if not documents:
            return {
                "status": "empty",
                "message": "No hay documentos en la base documental.",
                "documents_processed": 0,
                "total_chunks_indexed": 0,
            }

        total_indexed = 0
        total_errors = 0
        results = []
        for document in documents:
            result = self.index_document(db, document.id)
            results.append(
                {
                    "document_id": document.id,
                    "title": document.title,
                    "status": result["status"],
                    "chunks_indexed": result.get("chunks_indexed", 0),
                    "error": result.get("error"),
                }
            )
            if result["status"] == "indexed":
                total_indexed += result.get("chunks_indexed", 0)
            else:
                total_errors += 1

        return {
            "status": "completed",
            "documents_processed": len(documents),
            "total_chunks_indexed": total_indexed,
            "total_errors": total_errors,
            "embedding_model": self.embedder.model_name,
            "results": results,
        }
