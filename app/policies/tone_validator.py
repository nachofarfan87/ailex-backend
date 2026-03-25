"""
AILEX — Validador de tono.

Verifica que el texto de salida cumpla con los estándares
de comunicación de AILEX: profesional, directo, sin adornos.
"""

from app.policies.identity import Identity


class ToneValidator:
    """
    Valida el tono y estilo del texto de salida.

    AILEX debe hablar como un colega profesional:
    directo, claro, sin grandilocuencia.
    """

    # Frases que indican tono inadecuado
    FORBIDDEN_PATTERNS = Identity.FORBIDDEN_PHRASES

    # Muletillas que reducen claridad
    FILLER_PHRASES = [
        "en este sentido",
        "cabe señalar que",
        "cabe destacar que",
        "resulta pertinente",
        "corresponde mencionar",
        "en virtud de lo expuesto",
        "a mayor abundamiento",
        "no podemos soslayar",
        "deviene imprescindible",
        "en atención a",
    ]

    # Patrones de exceso de cortesía
    EXCESSIVE_COURTESY = [
        "le informamos cordialmente",
        "tenemos el agrado de",
        "nos permitimos sugerir",
        "si nos permite la observación",
        "humildemente sugerimos",
        "con el debido respeto",
    ]

    # Indicadores de respuesta genérica / de manual
    GENERIC_PATTERNS = [
        "según la doctrina mayoritaria",
        "como es sabido",
        "es menester recordar que",
        "la jurisprudencia ha sostenido reiteradamente",
        "en un estado de derecho",
        "desde una perspectiva teórica",
    ]

    @classmethod
    def validate(cls, text: str) -> list[str]:
        """
        Valida el tono del texto.
        Retorna lista de problemas detectados.
        """
        issues = []
        text_lower = text.lower()

        # Check frases prohibidas
        for phrase in cls.FORBIDDEN_PATTERNS:
            if phrase.lower() in text_lower:
                issues.append(
                    f"Frase prohibida: '{phrase}' — "
                    "reformular con lenguaje directo"
                )

        # Check muletillas
        filler_count = sum(
            1 for phrase in cls.FILLER_PHRASES
            if phrase in text_lower
        )
        if filler_count >= 2:
            issues.append(
                f"Exceso de muletillas ({filler_count} detectadas) — "
                "simplificar redacción"
            )

        # Check cortesía excesiva
        for phrase in cls.EXCESSIVE_COURTESY:
            if phrase in text_lower:
                issues.append(
                    f"Cortesía excesiva: '{phrase}' — "
                    "AILEX habla como colega profesional, no como subordinado"
                )

        # Check respuestas genéricas
        generic_count = sum(
            1 for phrase in cls.GENERIC_PATTERNS
            if phrase in text_lower
        )
        if generic_count >= 2:
            issues.append(
                f"Respuesta con {generic_count} patrones genéricos/de manual — "
                "priorizar utilidad práctica concreta"
            )

        # Check longitud excesiva del resumen (> 500 chars = demasiado)
        if len(text) > 500 and text_lower.startswith("resumen"):
            issues.append(
                "Resumen ejecutivo demasiado extenso — "
                "debe ser breve y al punto"
            )

        return issues

    @classmethod
    def suggest_rewrite(cls, phrase: str) -> str:
        """
        Sugiere alternativas para frases problemáticas.
        """
        rewrites = {
            "es importante destacar que": "→ (ir directo al punto)",
            "cabe mencionar que": "→ (eliminar, decir directamente)",
            "con todo respeto": "→ (eliminar)",
            "sin lugar a dudas": "→ 'hay respaldo suficiente para afirmar'",
            "garantizamos que": "→ 'con alto grado de certeza'",
            "resulta pertinente": "→ 'aplica' o 'es relevante'",
            "deviene imprescindible": "→ 'es necesario'",
            "a mayor abundamiento": "→ 'además'",
        }
        return rewrites.get(phrase.lower(), "→ reformular con lenguaje directo")
