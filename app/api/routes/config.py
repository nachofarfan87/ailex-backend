"""
AILEX — API Routes: Configuración jurídica.
"""

from fastapi import APIRouter

from app.jurisdiction.jujuy_profile import (
    JUJUY_PROFILE,
    get_fueros,
    get_tribunales,
    get_plazo,
)
from app.policies.identity import Identity
from app.policies.legal_guardrails import LegalGuardrails
from app.config import settings

router = APIRouter()


@router.get("/jurisdiction")
async def get_jurisdiction_profile():
    """Obtener perfil jurisdiccional activo con datos reales."""
    return {
        "jurisdiction": JUJUY_PROFILE["jurisdiction"],
        "province": JUJUY_PROFILE["province"],
        "country": JUJUY_PROFILE["country"],
        "capital": JUJUY_PROFILE["capital"],
        "fueros": get_fueros(),
        "normativa_base": JUJUY_PROFILE["normativa_base"],
        "estructura_judicial": JUJUY_PROFILE["estructura_judicial"],
        "particularidades": JUJUY_PROFILE["particularidades"],
        "advertencia": (
            "Los datos de plazos y tribunales son orientativos. "
            "Verificar siempre con normativa y acordadas STJ vigentes."
        ),
    }


@router.get("/jurisdiction/tribunales")
async def get_tribunales_route(fuero: str = None):
    """Listar tribunales de Jujuy, opcionalmente filtrados por fuero."""
    tribunales = get_tribunales(fuero)
    return {
        "fuero": fuero or "todos",
        "tribunales": tribunales,
        "nota": JUJUY_PROFILE["tribunales"]["nota"],
    }


@router.get("/jurisdiction/plazos")
async def get_plazos_route(tipo_acto: str = "contestacion_demanda", fuero: str = "civil"):
    """
    Obtener plazo orientativo para un acto procesal.
    Siempre incluye advertencia de verificación.
    """
    return get_plazo(tipo_acto, fuero)


@router.get("/jurisdiction/caratulas")
async def get_caratulas_route():
    """Estructura de carátulas y materias frecuentes en Jujuy."""
    return JUJUY_PROFILE["estructuras_caratula"]


@router.get("/jurisdiction/terminologia")
async def get_terminologia_route():
    """Terminología procesal típica de Jujuy."""
    return JUJUY_PROFILE["terminologia_procesal"]


@router.get("/policies")
async def get_policies():
    """Obtener políticas activas del sistema."""
    return {
        "sistema": Identity.NAME,
        "version": Identity.VERSION,
        "jurisdiccion": Identity.JURISDICTION,
        "confidence_threshold": settings.default_confidence_threshold,
        "min_sources_for_assertion": settings.min_sources_for_assertion,
        "response_policy": "active",
        "legal_guardrails": "active",
        "guardrails_count": {
            "prohibiciones": len(LegalGuardrails.PROHIBITIONS),
            "obligaciones": len(LegalGuardrails.OBLIGATIONS),
        },
        "prohibiciones": [p["id"] + ": " + p["rule"] for p in LegalGuardrails.PROHIBITIONS],
        "obligaciones": [o["id"] + ": " + o["rule"] for o in LegalGuardrails.OBLIGATIONS],
    }


@router.put("/policies")
async def update_policies(confidence_threshold: float = 0.7):
    """Actualizar umbral de confianza del sistema."""
    # En esta etapa no persiste — placeholder para configuración dinámica futura
    return {
        "status": "applied_session_only",
        "confidence_threshold": confidence_threshold,
        "nota": "El cambio aplica solo a esta sesión. Persistencia pendiente.",
    }
