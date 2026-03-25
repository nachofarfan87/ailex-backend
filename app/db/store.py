"""
AILEX — Almacén de documentos en memoria.

Almacenamiento temporal para desarrollo sin PostgreSQL.
Cuando se configure la base de datos, se reemplaza por
queries SQLAlchemy reales.
"""

import json
from typing import Optional


class DocumentStore:
    """
    Almacén de documentos y chunks en memoria.
    Thread-safe para desarrollo con uvicorn.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._documents = {}
            cls._instance._chunks = {}  # document_id → [chunks]
        return cls._instance

    # ─── Documentos ─────────────────────────────────────

    def add_document(self, document: dict) -> None:
        """Agregar un documento al almacén."""
        doc_id = document["id"]
        self._documents[doc_id] = document

    def get_document(self, doc_id: str) -> Optional[dict]:
        """Obtener un documento por ID."""
        return self._documents.get(doc_id)

    def list_documents(
        self,
        source_hierarchy: str = None,
        source_type: str = None,
        jurisdiction: str = None,
        legal_area: str = None,
        document_scope: str = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """Listar documentos con filtros opcionales."""
        docs = list(self._documents.values())

        # Aplicar filtros
        if document_scope:
            docs = [d for d in docs if d.get("document_scope") == document_scope]
        if source_hierarchy:
            docs = [d for d in docs if d.get("source_hierarchy") == source_hierarchy]
        if source_type:
            docs = [d for d in docs if d.get("source_type") == source_type]
        if jurisdiction:
            docs = [d for d in docs if d.get("jurisdiction", "").lower() == jurisdiction.lower()]
        if legal_area:
            docs = [d for d in docs if d.get("legal_area", "").lower() == legal_area.lower()]

        # Paginación
        total = len(docs)
        start = (page - 1) * per_page
        end = start + per_page

        return {
            "documents": docs[start:end],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    def delete_document(self, doc_id: str) -> bool:
        """Eliminar un documento y sus chunks."""
        if doc_id in self._documents:
            del self._documents[doc_id]
            self._chunks.pop(doc_id, None)
            return True
        return False

    # ─── Chunks ─────────────────────────────────────────

    def add_chunks(self, document_id: str, chunks: list[dict]) -> None:
        """Agregar chunks de un documento."""
        self._chunks[document_id] = chunks

    def update_document(self, document_id: str, **updates) -> Optional[dict]:
        """Actualizar metadata de un documento existente."""
        document = self._documents.get(document_id)
        if not document:
            return None
        document.update(updates)
        self._documents[document_id] = document
        return document

    def get_chunks(self, document_id: str) -> list[dict]:
        """Obtener chunks de un documento."""
        return self._chunks.get(document_id, [])

    def get_all_chunks(self, document_scope: str = None) -> list[dict]:
        """Obtener todos los chunks (para búsqueda)."""
        all_chunks = []
        for doc_id, chunks in self._chunks.items():
            doc = self._documents.get(doc_id, {})
            if document_scope and doc.get("document_scope") != document_scope:
                continue
            for chunk in chunks:
                chunk_with_meta = {**chunk}
                chunk_with_meta["document_title"] = doc.get("title", "")
                chunk_with_meta["document_scope"] = doc.get("document_scope")
                chunk_with_meta["vigente"] = doc.get("vigente", True)
                all_chunks.append(chunk_with_meta)
        return all_chunks

    # ─── Stats ──────────────────────────────────────────

    def get_stats(self, document_scope: str = None) -> dict:
        """Estadísticas del almacén."""
        docs = list(self._documents.values())
        if document_scope:
            docs = [d for d in docs if d.get("document_scope") == document_scope]

        doc_ids = {doc.get("id") for doc in docs}
        total_chunks = sum(
            len(chunks)
            for document_id, chunks in self._chunks.items()
            if document_id in doc_ids
        )

        by_hierarchy = {}
        for d in docs:
            h = d.get("source_hierarchy", "desconocido")
            by_hierarchy[h] = by_hierarchy.get(h, 0) + 1

        by_type = {}
        for d in docs:
            t = d.get("source_type", "desconocido")
            by_type[t] = by_type.get(t, 0) + 1

        return {
            "total_documents": len(self._documents),
            "total_chunks": total_chunks,
            "by_hierarchy": by_hierarchy,
            "by_type": by_type,
        }

    def clear(self) -> None:
        """Vaciar el almacén."""
        self._documents.clear()
        self._chunks.clear()
