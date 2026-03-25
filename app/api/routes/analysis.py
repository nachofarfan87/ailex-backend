"""
AILEX — API Routes: Análisis Jurídico.
"""

from fastapi import APIRouter, HTTPException
from app.api.schemas.contracts import JuridicalResponse
from app.api.schemas.requests import AnalysisRequest
from app.modules.analysis.service import AnalysisService

router = APIRouter()
_service = AnalysisService()


@router.post("/analyze", response_model=JuridicalResponse)
async def analyze_legal_situation(request: AnalysisRequest):
    """
    Analizar una situación jurídica.

    Pipeline: normalización → extracción de entidades → ReasoningPipeline
    → guardrails → JuridicalResponse validada.

    Toda salida garantiza las 8 secciones canónicas con trazabilidad
    EXTRAÍDO / INFERENCIA / SUGERENCIA y nivel de confianza explícito.
    """
    response, validation = await _service.analyze(
        text=request.text,
        doc_type=request.doc_type,
        session_id=request.session_id,
        fuero=request.fuero,
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
