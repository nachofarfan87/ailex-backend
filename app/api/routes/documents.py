"""
AILEX - API Routes: Documentos.
Ingestion, consulta y gestion de la base documental.

Todos los endpoints validan ownership: un usuario solo puede ver,
modificar y eliminar documentos que le pertenecen.
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import Expediente, User
from app.modules.ingestion.service import IngestionService
from app.services.document_service import DocumentService

router = APIRouter(dependencies=[Depends(get_current_user)])

ingestion = IngestionService(use_placeholder_embeddings=True)
document_service = DocumentService()


class DocumentScopeUpdateRequest(BaseModel):
    document_scope: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_scope(scope: str) -> str:
    normalized = (scope or "").strip().lower()
    if normalized not in {"corpus", "case"}:
        raise HTTPException(status_code=400, detail="document_scope debe ser 'corpus' o 'case'")
    return normalized


def _verify_expediente_ownership(
    db: Session,
    expediente_id: Optional[str],
    user_id: str,
) -> None:
    """Valida que el expediente exista y pertenezca al usuario."""
    if not expediente_id:
        return
    exp = db.get(Expediente, expediente_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Expediente '{expediente_id}' no encontrado.")
    if exp.user_id != user_id:
        raise HTTPException(status_code=403, detail="No tiene permiso para acceder a este expediente.")


def _get_owned_document(
    db: Session,
    document_id: str,
    user_id: str,
) -> dict:
    """Obtiene un documento verificando ownership. Lanza 404/403."""
    doc = document_service.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if doc.get("user_id") and doc["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="No tiene permiso para acceder a este documento.")
    return doc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    source_type: str = Form(default="escrito"),
    jurisdiction: str = Form(default="Jujuy"),
    legal_area: str = Form(default=""),
    fuero: str = Form(default=""),
    court: str = Form(default=""),
    description: str = Form(default=""),
    tags: str = Form(default=""),
    scope: str = Form(default="corpus"),
    expediente_id: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_expediente_ownership(db, expediente_id, current_user.id)

    content = await file.read()
    metadata = {
        "title": title or file.filename,
        "source_type": source_type,
        "jurisdiction": jurisdiction,
        "legal_area": legal_area,
        "fuero": fuero,
        "court": court,
        "description": description,
        "tags": tags,
        "origin": "upload_api",
        "document_scope": _normalize_scope(scope),
        "expediente_id": expediente_id or None,
    }

    result = await ingestion.ingest_file(content, file.filename, metadata)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    persisted = document_service.create_from_ingestion_result(
        db, result, user_id=current_user.id,
    )
    return {
        "status": result["status"],
        "document_id": result["document_id"],
        "title": result["title"],
        "chunk_count": result["chunk_count"],
        "total_chars": result["total_chars"],
        "source_type": result["source_type"],
        "source_hierarchy": result["source_hierarchy"],
        "document_scope": result["document_scope"],
        "indexed_in_corpus": result["indexed_in_corpus"],
        "jurisdiction": persisted.get("jurisdiction"),
        "legal_area": persisted.get("legal_area"),
        "tags": persisted.get("tags"),
        "detected_type": persisted.get("detected_type"),
        "extraction_mode": persisted.get("extraction_mode"),
        "ocr_used": persisted.get("ocr_used"),
        "extracted_text_length": persisted.get("extracted_text_length"),
        "extraction_warning": persisted.get("extraction_warning"),
        "analysis_text": result.get("analysis_text", ""),
    }


@router.post("/upload/text")
async def upload_text(
    text: str = Form(...),
    title: str = Form(...),
    source_type: str = Form(default="escrito"),
    jurisdiction: str = Form(default="Jujuy"),
    legal_area: str = Form(default=""),
    fuero: str = Form(default=""),
    court: str = Form(default=""),
    description: str = Form(default=""),
    tags: str = Form(default=""),
    scope: str = Form(default="corpus"),
    expediente_id: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_expediente_ownership(db, expediente_id, current_user.id)

    metadata = {
        "title": title,
        "source_type": source_type,
        "jurisdiction": jurisdiction,
        "legal_area": legal_area,
        "fuero": fuero,
        "court": court,
        "description": description,
        "tags": tags,
        "origin": "text_manual",
        "document_scope": _normalize_scope(scope),
        "expediente_id": expediente_id or None,
    }

    result = await ingestion.ingest_text(text, title, metadata)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    persisted = document_service.create_from_ingestion_result(
        db, result, user_id=current_user.id,
    )
    return {
        "status": result["status"],
        "document_id": result["document_id"],
        "title": result["title"],
        "chunk_count": result["chunk_count"],
        "total_chars": result["total_chars"],
        "source_type": result["source_type"],
        "source_hierarchy": result["source_hierarchy"],
        "document_scope": result["document_scope"],
        "indexed_in_corpus": result["indexed_in_corpus"],
        "jurisdiction": persisted.get("jurisdiction"),
        "legal_area": persisted.get("legal_area"),
        "tags": persisted.get("tags"),
        "extraction_mode": persisted.get("extraction_mode"),
        "ocr_used": persisted.get("ocr_used"),
        "extracted_text_length": persisted.get("extracted_text_length"),
        "extraction_warning": persisted.get("extraction_warning"),
        "analysis_text": result.get("analysis_text", ""),
    }


@router.get("/")
async def list_documents(
    source_hierarchy: Optional[str] = None,
    source_type: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    legal_area: Optional[str] = None,
    document_scope: Optional[str] = "corpus",
    expediente_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if expediente_id:
        _verify_expediente_ownership(db, expediente_id, current_user.id)

    normalized_scope = _normalize_scope(document_scope) if document_scope else None
    result = document_service.list_documents(
        db,
        user_id=current_user.id,
        source_hierarchy=source_hierarchy,
        source_type=source_type,
        jurisdiction=jurisdiction,
        legal_area=legal_area,
        document_scope=normalized_scope,
        expediente_id=expediente_id,
        page=page,
        per_page=per_page,
    )

    clean_docs = []
    for doc in result["documents"]:
        clean_docs.append(
            {
                "id": doc.get("id"),
                "title": doc.get("title"),
                "source_type": doc.get("source_type"),
                "source_hierarchy": doc.get("source_hierarchy"),
                "authority_level": doc.get("authority_level"),
                "jurisdiction": doc.get("jurisdiction"),
                "legal_area": doc.get("legal_area"),
                "court": doc.get("court"),
                "document_scope": doc.get("document_scope"),
                "expediente_id": doc.get("expediente_id"),
                "status": doc.get("status"),
                "chunk_count": doc.get("chunk_count"),
                "total_chars": doc.get("total_chars"),
                "extraction_mode": doc.get("extraction_mode"),
                "ocr_used": doc.get("ocr_used"),
                "tags": doc.get("tags"),
                "created_at": doc.get("created_at"),
            }
        )

    return {
        "documents": clean_docs,
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
    }


@router.get("/stats")
async def document_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return document_service.get_stats(db, document_scope="corpus", user_id=current_user.id)


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = _get_owned_document(db, document_id, current_user.id)

    return {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "description": doc.get("description"),
        "source_type": doc.get("source_type"),
        "source_hierarchy": doc.get("source_hierarchy"),
        "authority_level": doc.get("authority_level"),
        "jurisdiction": doc.get("jurisdiction"),
        "court": doc.get("court"),
        "legal_area": doc.get("legal_area"),
        "fuero": doc.get("fuero"),
        "reliability_score": doc.get("reliability_score"),
        "document_scope": doc.get("document_scope"),
        "expediente_id": doc.get("expediente_id"),
        "status": doc.get("status"),
        "chunk_count": doc.get("chunk_count"),
        "total_chars": doc.get("total_chars"),
        "tags": doc.get("tags"),
        "extraction_mode": doc.get("extraction_mode"),
        "extraction_method": doc.get("extraction_method"),
        "ocr_used": doc.get("ocr_used"),
        "extracted_text_length": doc.get("extracted_text_length"),
        "extraction_warning": doc.get("extraction_warning"),
        "page_count": doc.get("page_count"),
        "ocr_pages_processed": doc.get("ocr_pages_processed"),
    }


@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = _get_owned_document(db, document_id, current_user.id)

    chunks = document_service.get_chunks(db, document_id)
    return {
        "document_id": document_id,
        "document_title": doc.get("title"),
        "total_chunks": len(chunks),
        "chunks": [
            {
                "id": chunk.get("id"),
                "text": chunk.get("text"),
                "chunk_index": chunk.get("chunk_index"),
                "section": chunk.get("section"),
                "article_reference": chunk.get("article_reference"),
                "page_number": chunk.get("page_number"),
                "char_count": chunk.get("char_count"),
            }
            for chunk in chunks
        ],
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_document(db, document_id, current_user.id)

    if document_service.delete_document(db, document_id, user_id=current_user.id):
        return {"status": "deleted", "document_id": document_id}
    raise HTTPException(status_code=404, detail="Documento no encontrado")


@router.post("/{document_id}/index")
async def index_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_document(db, document_id, current_user.id)

    result = document_service.index_document(db, document_id)
    if result["status"] == "error":
        if "no encontrado" in result.get("error", "").lower():
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=500, detail=result["error"])
    if result["status"] == "skipped":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{document_id}/index/status")
async def get_index_status(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_document(db, document_id, current_user.id)
    return document_service.get_indexing_status(db, document_id)


@router.post("/reindex")
async def reindex_all_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await document_service.reindex_all(db, user_id=current_user.id)


@router.post("/{document_id}/scope")
async def update_document_scope(
    document_id: str,
    request: DocumentScopeUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = _get_owned_document(db, document_id, current_user.id)

    target_scope = _normalize_scope(request.document_scope)
    current_scope = doc.get("document_scope") or "corpus"
    if current_scope == target_scope:
        return {
            "status": "unchanged",
            "document_id": document_id,
            "document_scope": current_scope,
            "indexed_in_corpus": current_scope == "corpus",
        }

    updated_doc = document_service.update_document_scope(db, document_id, target_scope)
    indexing_result = None
    if target_scope == "corpus":
        indexing_result = document_service.index_document(db, document_id)
        if indexing_result["status"] == "error":
            raise HTTPException(status_code=500, detail=indexing_result["error"])
        if indexing_result["status"] == "skipped":
            raise HTTPException(status_code=400, detail=indexing_result["error"])
        updated_doc = document_service.get_document(db, document_id)

    return {
        "status": "updated",
        "document_id": document_id,
        "title": updated_doc.get("title"),
        "document_scope": updated_doc.get("document_scope"),
        "indexed_in_corpus": updated_doc.get("document_scope") == "corpus",
        "chunk_count": updated_doc.get("chunk_count", 0),
        "indexing": indexing_result,
    }
