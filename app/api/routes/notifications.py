"""
AILEX — API Routes: Notificaciones.
Análisis de notificaciones judiciales.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from app.api.schemas.contracts import JuridicalResponse
from app.api.schemas.requests import NotificationRequest
from app.modules.analysis.service import AnalysisService

router = APIRouter()
_service = AnalysisService()


@router.post("/analyze", response_model=JuridicalResponse)
async def analyze_notification(request: NotificationRequest):
    """
    Analizar una notificación judicial.

    Extrae: tipo de resolución, partes, expediente, plazos detectados.
    Propone: actos procesales concretos con prioridad.
    Marca: qué surge del texto (EXTRAÍDO) vs qué se infiere (INFERENCIA).
    Señala: datos faltantes para cómputo exacto de plazos.
    """
    response, validation = await _service.analyze(
        text=request.text,
        doc_type="notificacion",
        session_id=request.session_id,
    )

    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "La respuesta no pasó la validación de guardrails.",
                "errors": validation.errors,
            },
        )

    return response


@router.post("/upload")
async def upload_notification(file: UploadFile = File(...)):
    """
    Cargar un documento de notificación para análisis.
    El texto extraído se procesará por el mismo pipeline que /analyze.
    """
    return {
        "status": "pending",
        "message": (
            f"Archivo '{file.filename}' recibido. "
            "Extracción de texto y análisis pendiente de implementación."
        ),
    }
