"""
AILEX — Política de confianza.

Define cómo se calcula, clasifica y comunica el nivel de confianza
de las respuestas del sistema.

Cuatro niveles: ALTO, MEDIO, BAJO, SIN_RESPALDO.
La confianza nunca puede ser alta sin fuentes reales.
Sin fuentes → SIN_RESPALDO obligatorio (no BAJO).
"""

from app.api.schemas.contracts import ConfidenceLevel, SourceHierarchy


class ConfidencePolicy:
    """
    Calcula y valida niveles de confianza.

    Principios:
    - Sin fuentes → confianza SIN_RESPALDO obligatoria
    - Solo normativa/jurisprudencia verificable sube a ALTO
    - Doctrina e interno no alcanzan para ALTO por sí solos
    - Se requiere mínimo de fuentes para afirmaciones firmes
    """

    # ─── Umbrales ───────────────────────────────────────
    THRESHOLD_ALTO = 0.75   # Respaldo directo suficiente
    THRESHOLD_MEDIO = 0.40  # Respaldo parcial o inferencia razonable
    # Por debajo de 0.40 → BAJO

    # ─── Peso por tipo de fuente ────────────────────────
    # Refleja el peso argumental real en la práctica jurídica
    SOURCE_WEIGHTS = {
        SourceHierarchy.NORMATIVA: 1.0,      # Ley → peso máximo
        SourceHierarchy.JURISPRUDENCIA: 0.85, # Fallos → peso alto
        SourceHierarchy.DOCTRINA: 0.45,       # Doctrina → medio, no vinculante
        SourceHierarchy.INTERNO: 0.20,        # Material interno → solo práctico
    }

    # Mínimo de fuentes verificables para una afirmación firme
    MIN_SOURCES_FOR_ASSERTION = 2

    # Fuentes que pueden respaldar confianza ALTA
    HIGH_CONFIDENCE_SOURCES = {
        SourceHierarchy.NORMATIVA,
        SourceHierarchy.JURISPRUDENCIA,
    }

    @classmethod
    def classify(cls, score: float) -> ConfidenceLevel:
        """
        Clasifica un score numérico en nivel categórico.

        - >= 0.75 → ALTO: respaldo directo suficiente
        - >= 0.40 → MEDIO: respaldo parcial o inferencia razonable
        - < 0.40  → BAJO: faltan fuentes o datos críticos
        """
        if score >= cls.THRESHOLD_ALTO:
            return ConfidenceLevel.ALTO
        elif score >= cls.THRESHOLD_MEDIO:
            return ConfidenceLevel.MEDIO
        return ConfidenceLevel.BAJO

    @classmethod
    def calculate(cls, sources: list[dict]) -> tuple[float, ConfidenceLevel]:
        """
        Calcula confianza a partir de las fuentes disponibles.
        Retorna (score, nivel).

        Si no hay fuentes → (0.0, SIN_RESPALDO).
        Si solo hay doctrina/interno → máximo MEDIO.
        """
        if not sources:
            return 0.0, ConfidenceLevel.SIN_RESPALDO

        total_weight = 0.0
        has_high_source = False

        for source in sources:
            hierarchy = source.get("hierarchy", SourceHierarchy.INTERNO)
            relevance = source.get("relevance", 0.5)
            weight = cls.SOURCE_WEIGHTS.get(hierarchy, 0.2)
            total_weight += weight * relevance

            if hierarchy in cls.HIGH_CONFIDENCE_SOURCES:
                has_high_source = True

        # Normalizar
        max_possible = len(sources) * 1.0
        raw_score = total_weight / max_possible if max_possible > 0 else 0.0

        # Bonus por múltiples fuentes (hasta +0.15)
        count_bonus = min(len(sources) / cls.MIN_SOURCES_FOR_ASSERTION, 1.0) * 0.15
        score = min(raw_score + count_bonus, 1.0)

        # Cap: sin fuentes normativas/jurisprudenciales, máximo MEDIO
        if not has_high_source:
            score = min(score, cls.THRESHOLD_ALTO - 0.01)

        level = cls.classify(score)
        return round(score, 3), level

    @classmethod
    def can_assert(cls, sources: list[dict]) -> bool:
        """
        ¿Hay suficiente respaldo para hacer una afirmación firme?
        Si no, el sistema debe usar lenguaje cautelar.
        """
        if len(sources) < cls.MIN_SOURCES_FOR_ASSERTION:
            return False

        return any(
            s.get("hierarchy") in cls.HIGH_CONFIDENCE_SOURCES
            for s in sources
        )

    @classmethod
    def get_confidence_disclaimer(cls, level: ConfidenceLevel) -> str:
        """Disclaimer específico según nivel de confianza."""
        disclaimers = {
            ConfidenceLevel.ALTO: (
                "Confianza alta: respaldo documental directo y verificable."
            ),
            ConfidenceLevel.MEDIO: (
                "Confianza media: respaldo parcial. "
                "Algunas conclusiones se basan en inferencia razonable. "
                "Verificar fuentes antes de actuar."
            ),
            ConfidenceLevel.BAJO: (
                "Confianza baja: faltan fuentes o datos críticos. "
                "Esta respuesta es orientativa y requiere verificación "
                "independiente antes de cualquier acción procesal."
            ),
            ConfidenceLevel.SIN_RESPALDO: (
                "Sin respaldo documental. "
                "No hay fuentes disponibles para respaldar conclusiones. "
                "Toda la respuesta es puramente orientativa."
            ),
        }
        return disclaimers.get(level, disclaimers[ConfidenceLevel.SIN_RESPALDO])

    @classmethod
    def validate_confidence_coherence(cls, response: dict) -> list[str]:
        """
        Verifica que la confianza asignada sea coherente con las fuentes.
        Detecta confianza inflada (alta sin fuentes reales).
        """
        errors = []
        score = response.get("confianza_score", 0.0)
        sources = response.get("fuentes_respaldo", [])
        level = response.get("nivel_confianza", "sin_respaldo")

        # Confianza alta sin fuentes → ERROR
        if score >= cls.THRESHOLD_ALTO and not sources:
            errors.append(
                "confianza_score alto asignado sin fuentes en fuentes_respaldo. "
                "Viola la política de confianza."
            )

        # Confianza alta solo con doctrina/interno → ERROR
        if score >= cls.THRESHOLD_ALTO and sources:
            has_binding = any(
                s.get("source_hierarchy") in ("normativa", "jurisprudencia")
                for s in sources
                if isinstance(s, dict)
            )
            if not has_binding:
                errors.append(
                    "Confianza alta sin fuentes normativas ni "
                    "jurisprudenciales. Máximo permitido: MEDIO."
                )

        # Nivel textual incoherente con score
        if level == "alto" and score < cls.THRESHOLD_ALTO:
            errors.append(
                f"nivel_confianza 'alto' con score {score} "
                f"(mínimo requerido: {cls.THRESHOLD_ALTO})."
            )

        return errors
