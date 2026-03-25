"""
AILEX — API Routes: Generación de Escritos.

Endpoints:
  POST /generate                            — generar borrador completo
  GET  /templates                           — listar plantillas disponibles
  GET  /templates/{tipo_escrito}            — metadatos completos de una plantilla
  GET  /templates/{tipo_escrito}/draft      — borrador crudo con placeholders
  GET  /templates/{tipo_escrito}/placeholders — placeholders requeridos y opcionales
  GET  /variantes                           — variantes de redacción disponibles

Los endpoints existentes mantienen compatibilidad de respuesta.
/generate ahora retorna GenerationResponse (superset de JuridicalResponse).
"""

from fastapi import APIRouter, HTTPException
from app.modules.generation.schemas import GenerationResponse
from app.api.schemas.requests import GenerationRequest
from app.modules.generation.service import GenerationService
from app.modules.generation.registry import TemplateRegistry

router = APIRouter()
_service = GenerationService()


@router.post("/generate", response_model=GenerationResponse)
async def generate_document(request: GenerationRequest):
    """
    Generar un borrador de escrito jurídico estructurado.

    Usa plantillas con {{PLACEHOLDER}} para todo dato no provisto.
    NUNCA inventa datos. Todo campo desconocido queda marcado.

    La respuesta incluye:
    - `borrador`: texto completo del escrito con placeholders visibles
    - `placeholders_detectados`: lista de campos sin completar
    - `checklist_previo`: verificaciones antes de presentar
    - `riesgos_habituales`: riesgos típicos del tipo de escrito
    - `datos_faltantes`: detalle estructurado de cada placeholder (contrato base)
    - `nivel_confianza`: refleja disponibilidad de fuentes de respaldo

    Variantes: conservador | estandar | firme | agresivo_prudente
    (también acepta: conservadora, agresiva_prudente por compatibilidad)
    """
    response, validation = await _service.generate(
        fuero=request.fuero,
        materia=request.materia,
        tipo_escrito=request.tipo_escrito,
        variante=request.variante,
        hechos=request.hechos,
        datos=request.datos,
        session_id=request.session_id,
    )

    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "La generación no pasó la validación de guardrails.",
                "errors": validation.errors,
            },
        )

    return response


@router.get("/templates")
async def list_templates(fuero: str = "", materia: str = ""):
    """
    Listar plantillas de escritos disponibles.

    Filtros opcionales: fuero, materia.
    Las plantillas de fuero/materia 'general' aparecen siempre.
    """
    templates = await _service.list_templates(
        fuero=fuero or None,
        materia=materia or None,
    )
    return {
        "templates": templates,
        "total": len(templates),
    }


@router.get("/templates/{tipo_escrito}")
async def get_template_metadata(tipo_escrito: str):
    """
    Obtener metadatos completos de una plantilla.

    Incluye: estructura, placeholders requeridos y opcionales,
    checklist previo, riesgos habituales y variantes disponibles.
    """
    meta = await _service.get_template_metadata(tipo_escrito)
    if meta is None:
        disponibles = TemplateRegistry.get_tipos_disponibles()
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Plantilla '{tipo_escrito}' no encontrada.",
                "tipos_disponibles": disponibles,
            },
        )
    return meta


@router.get("/templates/{tipo_escrito}/draft")
async def get_template_draft(
    tipo_escrito: str,
    fuero: str = "",
    materia: str = "",
    variante: str = "estandar",
):
    """
    Obtener el borrador crudo de una plantilla con sus {{PLACEHOLDER}}.

    Útil para previsualizar la estructura antes de generar la respuesta completa.
    Acepta variante para mostrar el tono correspondiente.
    """
    draft = await _service.get_draft(
        fuero=fuero or "{{FUERO}}",
        materia=materia or "{{MATERIA}}",
        tipo_escrito=tipo_escrito,
        variante=variante,
    )
    if draft.startswith("[PLANTILLA NO DISPONIBLE"):
        disponibles = TemplateRegistry.get_tipos_disponibles()
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Plantilla '{tipo_escrito}' no encontrada.",
                "tipos_disponibles": disponibles,
            },
        )
    return {
        "tipo_escrito": tipo_escrito,
        "variante": TemplateRegistry.normalizar_variante(variante),
        "draft": draft,
    }


@router.get("/templates/{tipo_escrito}/placeholders")
async def get_template_placeholders(tipo_escrito: str):
    """
    Obtener los placeholders requeridos y opcionales de una plantilla.

    Útil para construir formularios de carga de datos del lado del cliente.
    """
    meta = await _service.get_template_metadata(tipo_escrito)
    if meta is None:
        disponibles = TemplateRegistry.get_tipos_disponibles()
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Plantilla '{tipo_escrito}' no encontrada.",
                "tipos_disponibles": disponibles,
            },
        )
    return {
        "tipo_escrito": tipo_escrito,
        "placeholders_requeridos": meta["placeholders_requeridos"],
        "placeholders_opcionales": meta["placeholders_opcionales"],
        "total_requeridos": len(meta["placeholders_requeridos"]),
        "total_opcionales": len(meta["placeholders_opcionales"]),
    }


@router.get("/variantes")
async def list_variantes():
    """
    Listar variantes de redacción disponibles y su descripción.
    """
    return {
        "variantes": [
            {
                "id": "conservador",
                "nombre": "Conservador",
                "descripcion": "Mínimo riesgo, máxima formalidad. Fórmulas cautelosas y reservadas.",
                "alias": ["conservadora"],
            },
            {
                "id": "estandar",
                "nombre": "Estándar",
                "descripcion": "Equilibrio entre completitud y prudencia. Recomendado como punto de partida.",
                "alias": [],
            },
            {
                "id": "firme",
                "nombre": "Firme",
                "descripcion": "Tono asertivo y directo. Sin condicionantes innecesarios.",
                "alias": [],
            },
            {
                "id": "agresivo_prudente",
                "nombre": "Agresivo Prudente",
                "descripcion": "Máxima argumentación disponible. Sin temeridad ni invención de datos.",
                "alias": ["agresiva_prudente"],
            },
        ]
    }
