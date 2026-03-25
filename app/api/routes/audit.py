"""
AILEX — API Routes: Auditoría y Revisión de Escritos.

Endpoints:
  POST /review              — revisión general completa (AuditResponse)
  POST /review/hallazgos    — solo listado de hallazgos del escrito
  POST /review/version-sugerida — versión mejorada del escrito
  POST /review/severidad    — evaluación rápida de severidad global
  POST /review/upload       — carga de documento (stub)

El endpoint existente /review mantiene compatibilidad de respuesta
(AuditResponse es superset de JuridicalResponse).
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from app.modules.audit.schemas import AuditResponse
from app.api.schemas.requests import AuditRequest
from app.modules.audit.service import AuditService

router = APIRouter()
_service = AuditService()


@router.post("/review", response_model=AuditResponse)
async def review_document(request: AuditRequest):
    """
    Revisión general de un escrito jurídico.

    Detecta:
    - Problemas de estructura (secciones faltantes, partes, encabezado)
    - Redacción problemática (negativa genérica, vaguedad, petición ambigua)
    - Debilidades argumentales (normas sospechosas, citas vagas)
    - Riesgos procesales concretos (documentos no listados, plazos vagos)
    - Violaciones de guardrails (certeza artificial, tono inadecuado)

    La respuesta incluye:
    - `diagnostico_general`: diagnóstico textual global
    - `severidad_general`: grave | moderada | leve | sin_problemas
    - `hallazgos`: lista estructurada con tipo, severidad, carácter y mejora
    - `fortalezas`: aspectos positivos del escrito
    - `debilidades`: resumen de debilidades por categoría
    - `mejoras_sugeridas`: acciones concretas de mejora
    - `version_sugerida`: borrador corregido (cuando aplica)
    - `cambios_aplicados`: cambios realizados en la versión sugerida
    - `datos_faltantes`: según contrato base
    - `nivel_confianza`: refleja disponibilidad de fuentes RAG

    Cada hallazgo indica si es EXTRAÍDO del texto, INFERIDO del contexto
    o una SUGERENCIA de mejora.
    """
    response, validation = await _service.review(
        text=request.text,
        tipo_escrito=request.tipo_escrito,
        demanda_original=request.demanda_original,
        session_id=request.session_id,
        incluir_version_sugerida=True,
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


@router.post("/review/hallazgos")
async def get_hallazgos(request: AuditRequest):
    """
    Obtener solo el listado estructurado de hallazgos del escrito.

    Útil para integraciones que necesitan procesar los hallazgos
    sin el overhead de la versión sugerida y el RAG completo.

    Cada hallazgo incluye: tipo, severidad, carácter, sección,
    texto_detectado, observación y mejora_sugerida.
    """
    response, _ = await _service.review(
        text=request.text,
        tipo_escrito=request.tipo_escrito,
        demanda_original=request.demanda_original,
        session_id=request.session_id,
        incluir_version_sugerida=False,
    )

    return {
        "severidad_general": response.severidad_general.value,
        "total_hallazgos": len(response.hallazgos),
        "hallazgos": [h.model_dump() for h in response.hallazgos],
        "fortalezas": response.fortalezas,
    }


@router.post("/review/version-sugerida")
async def get_version_sugerida(request: AuditRequest):
    """
    Obtener solo la versión mejorada del escrito.

    La versión sugerida aplica correcciones prudentes:
    - Reemplaza negativas genéricas con estructuras específicas
    - Marca peticiones ambiguas para revisión
    - Agrega secciones faltantes con {{PLACEHOLDER}}
    - Corrige expresiones de certeza artificial
    - No inventa hechos ni normativa
    - Mantiene todos los {{PLACEHOLDER}} existentes

    Incluye la lista de cambios aplicados.
    """
    response, _ = await _service.review(
        text=request.text,
        tipo_escrito=request.tipo_escrito,
        demanda_original=request.demanda_original,
        session_id=request.session_id,
        incluir_version_sugerida=True,
    )

    if not response.version_sugerida:
        return {
            "version_sugerida": None,
            "cambios_aplicados": [],
            "nota": (
                "No se generó versión sugerida: sin hallazgos moderados o graves, "
                "o ninguna corrección prudente aplicable."
            ),
        }

    return {
        "version_sugerida": response.version_sugerida,
        "cambios_aplicados": response.cambios_aplicados,
        "severidad_general": response.severidad_general.value,
        "advertencia": (
            "La versión sugerida es un borrador con correcciones estructurales. "
            "Revisar todos los cambios antes de presentar. "
            "No sustituye el criterio del abogado."
        ),
    }


@router.post("/review/severidad")
async def get_severidad(request: AuditRequest):
    """
    Evaluación rápida de severidad del escrito.

    No ejecuta RAG ni genera versión sugerida.
    Útil para clasificación rápida antes de la revisión completa.

    Retorna:
    - severidad_general: grave | moderada | leve | sin_problemas
    - total_hallazgos: número total de hallazgos detectados
    - por_categoria: conteo por categoría (estructura, redaccion, etc.)
    - graves / moderados / leves: conteo por severidad
    """
    result = await _service.get_severidad(
        text=request.text,
        tipo_escrito=request.tipo_escrito,
    )
    return result


@router.post("/review/upload")
async def review_uploaded_document(file: UploadFile = File(...)):
    """
    Cargar un documento para revisión.
    El texto extraído se procesará por el mismo pipeline que /review.
    [Pendiente: implementar extracción de texto desde PDF/DOCX]
    """
    return {
        "status": "pending",
        "message": (
            f"Documento '{file.filename}' recibido para revisión. "
            "Extracción de texto pendiente de implementación."
        ),
    }
