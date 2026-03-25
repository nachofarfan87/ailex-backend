"""
AILEX — API Routes: Estrategia Procesal.

Endpoints:
  POST /analyze  — análisis estratégico completo
  POST /options  — listado comparado de opciones
  POST /quick    — resumen breve para decisión rápida
"""

from fastapi import APIRouter, HTTPException

from app.api.schemas.requests import StrategyRequest
from app.modules.strategy.schemas import StrategyResponse
from app.modules.strategy.service import StrategyService

router = APIRouter()
_service = StrategyService()


@router.post("/analyze", response_model=StrategyResponse)
async def analyze_strategy(request: StrategyRequest):
    response, validation = await _service.analyze(
        text=request.text,
        tipo_proceso=request.tipo_proceso,
        etapa_procesal=request.etapa_procesal,
        objetivo_abogado=request.objetivo_abogado,
        fuentes_recuperadas=request.fuentes_recuperadas,
        actuaciones_detectadas=request.actuaciones_detectadas,
        plazos_detectados=request.plazos_detectados,
        hallazgos_revision=request.hallazgos_revision,
        tipo_escrito_generado=request.tipo_escrito_generado,
        session_id=request.session_id,
    )

    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "La estrategia no pasó la validación de guardrails.",
                "errors": validation.errors,
            },
        )

    return response


@router.post("/options")
async def list_strategy_options(request: StrategyRequest):
    return await _service.get_options(
        text=request.text,
        tipo_proceso=request.tipo_proceso,
        etapa_procesal=request.etapa_procesal,
        objetivo_abogado=request.objetivo_abogado,
        fuentes_recuperadas=request.fuentes_recuperadas,
        actuaciones_detectadas=request.actuaciones_detectadas,
        plazos_detectados=request.plazos_detectados,
        hallazgos_revision=request.hallazgos_revision,
        tipo_escrito_generado=request.tipo_escrito_generado,
        session_id=request.session_id,
    )


@router.post("/quick")
async def quick_strategy_summary(request: StrategyRequest):
    return await _service.get_quick_summary(
        text=request.text,
        tipo_proceso=request.tipo_proceso,
        etapa_procesal=request.etapa_procesal,
        objetivo_abogado=request.objetivo_abogado,
        fuentes_recuperadas=request.fuentes_recuperadas,
        actuaciones_detectadas=request.actuaciones_detectadas,
        plazos_detectados=request.plazos_detectados,
        hallazgos_revision=request.hallazgos_revision,
        tipo_escrito_generado=request.tipo_escrito_generado,
        session_id=request.session_id,
    )
