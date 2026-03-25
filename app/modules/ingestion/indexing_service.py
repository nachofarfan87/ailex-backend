"""
AILEX — Servicio de indexación de embeddings.

Genera o regenera embeddings para documentos ya almacenados en el store.

Flujo:
  documento ya parseado y persistido
    → generate_chunk_embeddings(document_id)
    → chunks actualizados con embedding_json

Operaciones disponibles:
  - index_document(document_id)  → indexar/reindexar un documento
  - reindex_all()                → reindexar toda la base documental
  - get_indexing_status(id)      → verificar estado de indexación

Útil cuando:
  - Se cambia el modelo de embeddings
  - Se agrega un documento sin embeddings
  - Se quiere regenerar embeddings con modelo superior
"""

from app.db.store import DocumentStore
from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import get_default_provider


class IndexingService:
    """
    Servicio de indexación y reindexación de embeddings.

    Actualiza los embeddings de los chunks en el store.
    No modifica el texto ni la metadata jurídica de los documentos.
    """

    def __init__(
        self,
        store: DocumentStore = None,
        embedder: EmbeddingProvider = None,
    ):
        self.store = store or DocumentStore()
        self.embedder = embedder or get_default_provider()

    async def index_document(self, document_id: str) -> dict:
        """
        Generar/regenerar embeddings para todos los chunks de un documento.

        Recupera los chunks del store, genera embeddings en batch,
        y sobreescribe el embedding_json de cada chunk.

        Returns:
            dict con status, chunks_indexed, embedding_model, errors
        """
        doc = self.store.get_document(document_id)
        if not doc:
            return {
                "status": "error",
                "document_id": document_id,
                "error": "Documento no encontrado.",
                "chunks_indexed": 0,
            }

        if doc.get("document_scope") != "corpus":
            return {
                "status": "skipped",
                "document_id": document_id,
                "document_title": doc.get("title", ""),
                "chunks_indexed": 0,
                "error": "Solo se indexan documentos con scope corpus.",
            }

        chunks = self.store.get_chunks(document_id)
        if not chunks:
            return {
                "status": "no_chunks",
                "document_id": document_id,
                "document_title": doc.get("title", ""),
                "chunks_indexed": 0,
                "message": "El documento no tiene chunks para indexar.",
            }

        texts = [c.get("text", "") for c in chunks]

        try:
            embeddings = self.embedder.embed_batch(texts)
        except Exception as e:
            return {
                "status": "error",
                "document_id": document_id,
                "error": f"Error generando embeddings: {str(e)}",
                "chunks_indexed": 0,
            }

        updated_chunks = []
        for chunk, emb in zip(chunks, embeddings):
            updated = {**chunk}
            updated["embedding_json"] = self.embedder.to_json(emb)
            updated["embedding_model"] = self.embedder.model_name
            updated_chunks.append(updated)

        self.store.add_chunks(document_id, updated_chunks)
        self.store.update_document(
            document_id,
            status="indexed",
        )

        return {
            "status": "indexed",
            "document_id": document_id,
            "document_title": doc.get("title", ""),
            "chunks_indexed": len(updated_chunks),
            "embedding_model": self.embedder.model_name,
            "errors": [],
        }

    async def reindex_all(self) -> dict:
        """
        Reindexar todos los documentos de la base documental.

        Útil tras cambiar el modelo de embeddings.
        Procesa todos los documentos en secuencia y reporta resultados.

        Returns:
            dict con documentos_procesados, chunks_indexados, errores
        """
        all_docs = self.store.list_documents(document_scope="corpus", page=1, per_page=9999)
        documents = all_docs.get("documents", [])

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

        for doc in documents:
            doc_id = doc.get("id")
            result = await self.index_document(doc_id)
            results.append({
                "document_id": doc_id,
                "title": doc.get("title", ""),
                "status": result["status"],
                "chunks_indexed": result.get("chunks_indexed", 0),
                "error": result.get("error"),
            })
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

    def get_indexing_status(self, document_id: str) -> dict:
        """
        Verificar estado de indexación de un documento.

        Chequea si los chunks tienen embeddings y con qué modelo.

        Returns:
            dict con status (indexed | partial | not_indexed | not_found)
        """
        doc = self.store.get_document(document_id)
        if not doc:
            return {"status": "not_found", "document_id": document_id}

        chunks = self.store.get_chunks(document_id)
        total = len(chunks)

        if total == 0:
            return {
                "status": "no_chunks",
                "document_id": document_id,
                "document_title": doc.get("title", ""),
                "total_chunks": 0,
                "indexed_chunks": 0,
            }

        indexed = sum(1 for c in chunks if c.get("embedding_json"))
        models_used = list({
            c.get("embedding_model", "unknown")
            for c in chunks
            if c.get("embedding_model")
        })

        if indexed == total:
            status = "indexed"
        elif indexed > 0:
            status = "partial"
        else:
            status = "not_indexed"

        return {
            "status": status,
            "document_id": document_id,
            "document_title": doc.get("title", ""),
            "total_chunks": total,
            "indexed_chunks": indexed,
            "embedding_models": models_used,
        }
