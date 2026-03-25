"""
AILEX — Ranking jurídico compuesto.

El score final de recuperación no depende solo de similitud semántica.
Pondera múltiples factores con relevancia jurídica real:

  a. similitud semántica       — qué tan parecido semánticamente
  b. coincidencia textual      — qué tan parecido por palabras
  c. jerarquía de fuente       — normativa > jurisprudencia > doctrina > interno
  d. jurisdicción aplicable    — Jujuy > Nacional/Federal > otra
  e. vigencia                  — fuente no vigente se penaliza
  f. afinidad temática         — área jurídica coincidente
  g. tipo de uso               — fuente autorizada vs material interno

Reglas clave:
  - normativa aplicable > jurisprudencia relevante > doctrina > escritos
  - Jujuy pesa más para práctica local
  - Material interno útil para estilo/estrategia, NO como autoridad
  - Fuente no vigente: penalizada (multiplicador negativo)
  - Fuente con uso no permitido para argumentación: marcada con aviso
"""

from dataclasses import dataclass, field
from typing import Optional


# ─── Jerarquía base (0-1) ────────────────────────────────

HIERARCHY_BASE_SCORE: dict[str, float] = {
    "normativa":      1.00,
    "jurisprudencia": 0.85,
    "doctrina":       0.55,
    "interno":        0.30,
}

# Tipos de fuente vinculantes (máximo peso en normativa)
PRIMARY_SOURCE_TYPES: set[str] = {
    "codigo", "ley", "reglamento", "acordada",
}

# Tipos que NO deben usarse como autoridad normativa en escritos
NON_AUTHORITATIVE_TYPES: set[str] = {
    "escritos_estudio", "plantillas", "escrito", "modelo", "estrategia",
}

# Mensaje de advertencia para fuentes no autoritativas
NON_AUTHORITATIVE_WARNING = (
    "Material interno — referencia de estilo o estrategia procesal. "
    "No citar como fuente normativa o jurisprudencial en escritos."
)


# ─── Configuración de pesos ──────────────────────────────

@dataclass
class RankingWeights:
    """
    Pesos para combinar los factores de ranking.

    La suma de pesos define la escala del score compuesto.
    Se normalizan al calcular el score final (max ~ 1.0).
    """
    semantic:     float = 0.40   # Similitud semántica
    keyword:      float = 0.20   # Coincidencia textual BM25
    hierarchy:    float = 0.20   # Jerarquía jurídica de la fuente
    jurisdiction: float = 0.10   # Jurisdicción aplicable
    vigencia:     float = 0.05   # Vigencia del documento
    thematic:     float = 0.03   # Afinidad temática (área jurídica)
    usage:        float = 0.02   # Tipo de uso permitido


DEFAULT_WEIGHTS = RankingWeights()


# ─── Factores calculados ─────────────────────────────────

@dataclass
class RankingFactors:
    """Factores individuales calculados para un chunk."""
    semantic:     float = 0.0
    keyword:      float = 0.0
    hierarchy:    float = 0.0
    jurisdiction: float = 0.5  # neutral por defecto
    vigencia:     float = 1.0  # vigente por defecto
    thematic:     float = 0.5  # neutral por defecto
    usage:        float = 1.0  # autorizado por defecto

    # Metadatos para trazabilidad y advertencias
    is_authoritative: bool = True   # False si es material interno sin peso formal
    vigente:          bool = True   # False si el documento no está vigente
    explanation:      str = ""


@dataclass
class RankingResult:
    """Score final con explicación de los factores."""
    final_score:   float
    factors:       RankingFactors
    weights:       RankingWeights
    explanation:   str
    usage_warning: Optional[str] = None


# ─── Motor de ranking ────────────────────────────────────

class LegalRanking:
    """
    Motor de ranking jurídico compuesto.

    Recibe un chunk con metadata y sus scores semántico/keyword,
    y devuelve un score final que refleja su utilidad jurídica real.

    Instanciar con parámetros de boost/penalización desde settings:

        ranking = LegalRanking(
            boost_local_jurisdiction=settings.boost_jurisdiccion_local,
            boost_primary_source=settings.boost_fuente_primaria,
            penalize_not_vigente=settings.penalize_no_vigente,
        )
    """

    def __init__(
        self,
        weights: RankingWeights = None,
        boost_local_jurisdiction: float = 0.20,
        boost_primary_source: float = 0.15,
        penalize_not_vigente: float = 0.30,
        local_jurisdiction: str = "Jujuy",
    ):
        self.weights = weights or DEFAULT_WEIGHTS
        self.boost_local_jurisdiction = boost_local_jurisdiction
        self.boost_primary_source = boost_primary_source
        self.penalize_not_vigente = penalize_not_vigente
        self.local_jurisdiction = local_jurisdiction.lower()

    def rank(
        self,
        chunk: dict,
        semantic_score: float,
        keyword_score: float,
        query_jurisdiction: Optional[str] = None,
        query_legal_area: Optional[str] = None,
        weights: RankingWeights = None,
    ) -> RankingResult:
        """
        Calcular ranking completo para un chunk.

        Args:
            chunk: dict con metadata del fragmento
            semantic_score: similitud vectorial (0-1)
            keyword_score: score BM25 (0-1)
            query_jurisdiction: jurisdicción de la consulta
            query_legal_area: área jurídica de la consulta
            weights: pesos personalizados (usa self.weights por defecto)

        Returns:
            RankingResult con score final y explicación
        """
        factors = self._compute_factors(
            chunk, semantic_score, keyword_score,
            query_jurisdiction, query_legal_area,
        )
        return self._compute_final(factors, weights or self.weights)

    def _compute_factors(
        self,
        chunk: dict,
        semantic_score: float,
        keyword_score: float,
        query_jurisdiction: Optional[str],
        query_legal_area: Optional[str],
    ) -> RankingFactors:
        source_hierarchy = chunk.get("source_hierarchy", "interno")
        source_type = chunk.get("source_type", "")
        chunk_jurisdiction = chunk.get("jurisdiction", "")
        chunk_legal_area = chunk.get("legal_area", "")
        vigente = chunk.get("vigente", True)  # None = asume vigente

        # c. Jerarquía
        hierarchy_base = HIERARCHY_BASE_SCORE.get(source_hierarchy, 0.30)
        if source_type in PRIMARY_SOURCE_TYPES:
            hierarchy_base = min(1.0, hierarchy_base + self.boost_primary_source)
        # Bonus si tiene referencia a artículo específico (más preciso)
        if chunk.get("article_reference"):
            hierarchy_base = min(1.0, hierarchy_base + 0.03)

        # d. Jurisdicción
        jurisdiction_score = self._jurisdiction_score(
            chunk_jurisdiction, query_jurisdiction
        )

        # e. Vigencia
        vigencia_score = 0.0 if vigente is False else 1.0

        # f. Afinidad temática
        thematic_score = self._thematic_score(chunk_legal_area, query_legal_area)

        # g. Tipo de uso
        is_authoritative = source_type not in NON_AUTHORITATIVE_TYPES
        usage_score = 1.0 if is_authoritative else 0.5

        # Construir explicación
        exp_parts = [
            f"hierarchy={source_hierarchy}({hierarchy_base:.2f})",
            f"jurisdiction({jurisdiction_score:.2f})",
            f"thematic({thematic_score:.2f})",
        ]
        if source_type in PRIMARY_SOURCE_TYPES:
            exp_parts.append("primary_source(+boost)")
        if vigente is False:
            exp_parts.append("NOT_VIGENTE")
        if not is_authoritative:
            exp_parts.append("non_authoritative")
        if chunk.get("article_reference"):
            exp_parts.append(f"art={chunk['article_reference']}")

        return RankingFactors(
            semantic=semantic_score,
            keyword=keyword_score,
            hierarchy=hierarchy_base,
            jurisdiction=jurisdiction_score,
            vigencia=vigencia_score,
            thematic=thematic_score,
            usage=usage_score,
            is_authoritative=is_authoritative,
            vigente=vigente if vigente is not None else True,
            explanation=" | ".join(exp_parts),
        )

    def _compute_final(
        self, factors: RankingFactors, weights: RankingWeights
    ) -> RankingResult:
        raw = (
            weights.semantic     * factors.semantic
            + weights.keyword    * factors.keyword
            + weights.hierarchy  * factors.hierarchy
            + weights.jurisdiction * factors.jurisdiction
            + weights.vigencia   * factors.vigencia
            + weights.thematic   * factors.thematic
            + weights.usage      * factors.usage
        )

        # Penalizar fuente no vigente (multiplicador)
        if not factors.vigente:
            raw *= max(0.0, 1.0 - self.penalize_not_vigente)

        final = max(0.0, min(1.0, raw))

        usage_warning = None
        explanation = factors.explanation
        if not factors.is_authoritative:
            usage_warning = NON_AUTHORITATIVE_WARNING
            explanation += f" | AVISO: {usage_warning}"

        return RankingResult(
            final_score=final,
            factors=factors,
            weights=weights,
            explanation=explanation,
            usage_warning=usage_warning,
        )

    def _jurisdiction_score(
        self, chunk_jurisdiction: str, query_jurisdiction: Optional[str]
    ) -> float:
        """Score de afinidad jurisdiccional."""
        if not query_jurisdiction:
            return 0.5  # neutral si no se especifica

        cj = (chunk_jurisdiction or "").lower()
        qj = query_jurisdiction.lower()

        if cj == qj:
            score = 0.80
            # Bonus adicional si es la jurisdicción local
            if cj == self.local_jurisdiction:
                score = min(1.0, score + self.boost_local_jurisdiction)
            return score

        if "nacional" in cj or "federal" in cj:
            return 0.60  # Nacional aplica en toda jurisdicción

        if not cj:
            return 0.40  # Sin jurisdicción → neutral bajo

        return 0.10  # Jurisdicción distinta → muy baja relevancia

    def _thematic_score(
        self, chunk_area: str, query_area: Optional[str]
    ) -> float:
        """Score de afinidad temática (materia jurídica)."""
        if not query_area or not chunk_area:
            return 0.5  # neutral

        ca = chunk_area.lower()
        qa = query_area.lower()

        if ca == qa:
            return 1.0
        if ca in qa or qa in ca:
            return 0.70  # Match parcial
        return 0.20
