"""
AILEX — Perfiles de búsqueda por módulo.

Cada módulo del sistema recupera fuentes de manera diferente
según su propósito: analizar notificaciones no es lo mismo
que generar un escrito o auditar argumentos.

Los perfiles configuran:
- Pesos de ranking (más peso semántico vs jerárquico)
- Jerarquías preferidas (orden de prioridad)
- Tipos de fuente priorizados
- Términos boost específicos del módulo
- Tipos excluidos (material irrelevante para ese contexto)
"""

from dataclasses import dataclass, field
from enum import Enum

from app.modules.search.ranking import RankingWeights


class SearchProfile(str, Enum):
    """Perfiles de búsqueda disponibles."""
    GENERAL       = "general"        # Búsqueda equilibrada
    NOTIFICATIONS = "notifications"  # Análisis de notificaciones procesales
    GENERATION    = "generation"     # Generación de escritos judiciales
    AUDIT         = "audit"          # Revisión/auditoría de escritos
    STRATEGY      = "strategy"       # Estrategia procesal


@dataclass
class SearchProfileConfig:
    """Configuración de un perfil de búsqueda."""
    name: str
    description: str
    weights: RankingWeights
    preferred_hierarchies: list[str]  # Jerarquías en orden de preferencia
    preferred_types: list[str]        # Tipos de fuente priorizados
    boost_terms: list[str]            # Términos que reciben boost de relevancia
    exclude_types: list[str] = field(default_factory=list)  # Tipos a excluir
    min_score: float = 0.05
    max_results: int = 10
    max_chars: int = 8000


# ─── Definición de perfiles ──────────────────────────────

SEARCH_PROFILES: dict[SearchProfile, SearchProfileConfig] = {

    SearchProfile.GENERAL: SearchProfileConfig(
        name="General",
        description=(
            "Búsqueda equilibrada entre todos los tipos de fuente. "
            "Sin prioridad especial por módulo."
        ),
        weights=RankingWeights(
            semantic=0.40, keyword=0.20, hierarchy=0.20,
            jurisdiction=0.10, vigencia=0.05, thematic=0.03, usage=0.02,
        ),
        preferred_hierarchies=["normativa", "jurisprudencia", "doctrina", "interno"],
        preferred_types=[],
        boost_terms=[],
    ),

    SearchProfile.NOTIFICATIONS: SearchProfileConfig(
        name="Notificaciones procesales",
        description=(
            "Prioriza normativa procesal, acordadas y jurisprudencia procesal. "
            "Foco en plazos, traslados, intimaciones y apercibimientos. "
            "Excluye material de estrategia y plantillas vacías."
        ),
        weights=RankingWeights(
            semantic=0.35, keyword=0.25, hierarchy=0.25,
            jurisdiction=0.10, vigencia=0.03, thematic=0.01, usage=0.01,
        ),
        preferred_hierarchies=["normativa", "jurisprudencia"],
        preferred_types=[
            "acordada", "reglamento", "ley", "codigo", "jurisprudencia",
        ],
        boost_terms=[
            "traslado", "plazo", "notificación", "intimación",
            "apercibimiento", "rebeldía", "preclusión", "hábil",
            "vencimiento", "cómputo", "días", "término", "contesto",
        ],
        exclude_types=["plantillas", "estrategia"],
    ),

    SearchProfile.GENERATION: SearchProfileConfig(
        name="Generación de escritos",
        description=(
            "Prioriza plantillas y escritos modelo del estudio, "
            "luego normativa y jurisprudencia aplicable. "
            "Útil para redactar escritos procesales con estructura correcta."
        ),
        weights=RankingWeights(
            semantic=0.38, keyword=0.22, hierarchy=0.18,
            jurisdiction=0.12, vigencia=0.05, thematic=0.03, usage=0.02,
        ),
        preferred_hierarchies=["normativa", "jurisprudencia", "interno", "doctrina"],
        preferred_types=[
            "plantillas", "escrito", "escritos_estudio", "modelo",
            "codigo", "ley", "acordada", "jurisprudencia",
        ],
        boost_terms=[
            "demanda", "contestación", "recurso", "apelación",
            "medida cautelar", "fundamentos", "petición", "solicita",
            "ofrece prueba", "reserva", "formula", "interpone",
        ],
        exclude_types=[],
    ),

    SearchProfile.AUDIT: SearchProfileConfig(
        name="Revisión de escritos",
        description=(
            "Prioriza normativa y jurisprudencia para validar argumentos. "
            "Doctrina como apoyo. Escritos del estudio como referencia comparativa. "
            "Detecta inconsistencias entre lo afirmado y la normativa real."
        ),
        weights=RankingWeights(
            semantic=0.40, keyword=0.18, hierarchy=0.22,
            jurisdiction=0.12, vigencia=0.05, thematic=0.02, usage=0.01,
        ),
        preferred_hierarchies=["normativa", "jurisprudencia", "doctrina", "interno"],
        preferred_types=[
            "codigo", "ley", "acordada", "jurisprudencia", "doctrina",
        ],
        boost_terms=[
            "artículo", "norma", "prescribe", "establece", "doctrina",
            "fallo", "sentencia", "jurisprudencia", "criterio", "principio",
        ],
        exclude_types=[],
    ),

    SearchProfile.STRATEGY: SearchProfileConfig(
        name="Estrategia procesal",
        description=(
            "Prioriza jurisprudencia orientadora y normativa de fondo. "
            "Escritos del estudio como apoyo comparativo (sin autoridad formal). "
            "Doctrina para reforzar argumentos cuando no hay jurisprudencia."
        ),
        weights=RankingWeights(
            semantic=0.42, keyword=0.18, hierarchy=0.20,
            jurisdiction=0.12, vigencia=0.04, thematic=0.02, usage=0.02,
        ),
        preferred_hierarchies=["jurisprudencia", "normativa", "doctrina", "interno"],
        preferred_types=[
            "jurisprudencia", "codigo", "ley", "doctrina",
            "escritos_estudio", "acordada",
        ],
        boost_terms=[
            "estrategia", "argumento", "precedente", "criterio",
            "tribunal", "sala", "resolvió", "consideró", "doctrina",
        ],
        exclude_types=[],
    ),
}


# ─── Helpers ─────────────────────────────────────────────

def get_profile(profile: "SearchProfile | str") -> SearchProfileConfig:
    """Obtener configuración de un perfil por nombre o enum."""
    if isinstance(profile, str):
        try:
            profile = SearchProfile(profile)
        except ValueError:
            profile = SearchProfile.GENERAL
    return SEARCH_PROFILES.get(profile, SEARCH_PROFILES[SearchProfile.GENERAL])


def list_profiles() -> list[dict]:
    """Listar todos los perfiles disponibles con descripción."""
    return [
        {
            "profile": p.value,
            "name": cfg.name,
            "description": cfg.description,
            "preferred_hierarchies": cfg.preferred_hierarchies,
            "preferred_types": cfg.preferred_types,
        }
        for p, cfg in SEARCH_PROFILES.items()
    ]
