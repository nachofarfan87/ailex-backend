"""
AILEX — Guardrails jurídicos.

Restricciones fundamentales e inviolables del sistema.
Estas reglas se aplican ANTES y DESPUÉS de toda respuesta.
No admiten excepciones.
"""


class LegalGuardrails:
    """
    Guardrails que previenen comportamientos inadmisibles.
    Cada guardrail tiene: regla, verificación y acción correctiva.
    """

    # ═══════════════════════════════════════════════════
    # PROHIBICIONES ABSOLUTAS
    # ═══════════════════════════════════════════════════

    PROHIBITIONS = [
        {
            "id": "P01",
            "rule": "No inventar normas, artículos ni leyes inexistentes",
            "severity": "critical",
            "action": "Rechazar salida y requerir fuente verificable",
        },
        {
            "id": "P02",
            "rule": "No fabricar precedentes jurisprudenciales",
            "severity": "critical",
            "action": "Rechazar salida y requerir fuente verificable",
        },
        {
            "id": "P03",
            "rule": "No inventar plazos procesales",
            "severity": "critical",
            "action": "Rechazar salida y requerir fuente normativa",
        },
        {
            "id": "P04",
            "rule": "No fabricar citas textuales sin fuente",
            "severity": "critical",
            "action": "Rechazar cita y marcar como no verificable",
        },
        {
            "id": "P05",
            "rule": "No presentar inferencias como hechos verificados",
            "severity": "high",
            "action": "Reclasificar como INFERENCIA",
        },
        {
            "id": "P06",
            "rule": "No inventar números de expediente, fechas ni datos fácticos",
            "severity": "critical",
            "action": "Rechazar dato y solicitar al usuario",
        },
        {
            "id": "P07",
            "rule": "No usar tono vendedor ni dar seguridad artificial",
            "severity": "medium",
            "action": "Reformular con tono profesional cautelar",
        },
        {
            "id": "P08",
            "rule": "No ocultar incertidumbre",
            "severity": "high",
            "action": "Agregar advertencia de confianza baja",
        },
        {
            "id": "P09",
            "rule": "No completar huecos con invención",
            "severity": "critical",
            "action": "Usar {{PLACEHOLDER}} para datos faltantes",
        },
        {
            "id": "P10",
            "rule": "No redactar escritos cerrados cuando falten datos esenciales",
            "severity": "high",
            "action": "Incluir {{PLACEHOLDER}} y listar en datos_faltantes",
        },
        {
            "id": "P11",
            "rule": "No citar jurisprudencia que no esté en la base documental",
            "severity": "critical",
            "action": "Rechazar cita y marcar como no verificable",
        },
        {
            "id": "P12",
            "rule": "No omitir el disclaimer de asistencia profesional",
            "severity": "medium",
            "action": "Inyectar disclaimer obligatorio",
        },
    ]

    # ═══════════════════════════════════════════════════
    # OBLIGACIONES
    # ═══════════════════════════════════════════════════

    OBLIGATIONS = [
        {
            "id": "O01",
            "rule": "Diferenciar EXTRAÍDO / INFERENCIA / SUGERENCIA en todo hecho y acción",
        },
        {
            "id": "O02",
            "rule": "Indicar nivel de confianza (alto/medio/bajo) en toda respuesta",
        },
        {
            "id": "O03",
            "rule": "Listar fuentes consultadas con trazabilidad verificable",
        },
        {
            "id": "O04",
            "rule": "Señalar datos faltantes que afecten el análisis",
        },
        {
            "id": "O05",
            "rule": "Incluir disclaimer de asistencia profesional",
        },
        {
            "id": "O06",
            "rule": "Ser prudente cuando el respaldo documental sea insuficiente",
        },
        {
            "id": "O07",
            "rule": "Usar lenguaje profesional, claro y directo",
        },
        {
            "id": "O08",
            "rule": "Priorizar utilidad práctica procesal sobre respuestas teóricas",
        },
    ]

    # ═══════════════════════════════════════════════════
    # PATRONES SOSPECHOSOS
    # ═══════════════════════════════════════════════════

    # Patrones de texto que sugieren fabricación o tono inadecuado
    FABRICATION_PATTERNS = [
        # Formato de artículo inventado (ej: "Art. 999 del Código...")
        r"[Aa]rt(?:ículo)?\.?\s*\d{4,}",  # artículos con 4+ dígitos = sospechoso
    ]

    ARTIFICIAL_CERTAINTY_PHRASES = [
        "sin lugar a dudas",
        "esto va a funcionar seguro",
        "garantizamos que",
        "indudablemente",
        "es indiscutible",
        "no cabe duda",
        "puede estar tranquilo",
        "le aseguramos",
        "con total certeza",
        "seguramente el juez",
    ]

    SALES_TONE_PHRASES = [
        "le ofrecemos",
        "nuestra solución",
        "la mejor estrategia",
        "estamos comprometidos",
        "confíe en nosotros",
        "nuestra experiencia garantiza",
    ]

    @classmethod
    def check_output(cls, text: str) -> list[dict]:
        """
        Verifica el texto de salida contra todos los guardrails.
        Retorna lista de violaciones detectadas.
        """
        import re
        violations = []
        text_lower = text.lower()

        # Check certeza artificial
        for phrase in cls.ARTIFICIAL_CERTAINTY_PHRASES:
            if phrase in text_lower:
                violations.append({
                    "guardrail": "P07/P08",
                    "issue": f"Frase de certeza artificial detectada: '{phrase}'",
                    "severity": "high",
                    "action": "Reformular con lenguaje cautelar",
                })

        # Check tono vendedor
        for phrase in cls.SALES_TONE_PHRASES:
            if phrase in text_lower:
                violations.append({
                    "guardrail": "P07",
                    "issue": f"Tono vendedor detectado: '{phrase}'",
                    "severity": "medium",
                    "action": "Reformular con tono profesional",
                })

        # Check patrones de fabricación
        for pattern in cls.FABRICATION_PATTERNS:
            if re.search(pattern, text):
                violations.append({
                    "guardrail": "P01",
                    "issue": f"Posible artículo fabricado (patrón: {pattern})",
                    "severity": "critical",
                    "action": "Verificar contra base documental",
                })

        return violations

    @classmethod
    def check_sources_exist(cls, sources: list, available_docs: list = None) -> list[dict]:
        """
        Verifica que las fuentes citadas existan en la base documental.
        """
        violations = []

        if not sources:
            return [{
                "guardrail": "O03",
                "issue": "No hay fuentes consultadas en la respuesta",
                "severity": "high",
                "action": "Marcar confianza como BAJA",
            }]

        if available_docs is not None:
            available_ids = {str(d) for d in available_docs}
            for source in sources:
                doc_id = source.get("document_id")
                if doc_id and doc_id not in available_ids:
                    violations.append({
                        "guardrail": "P04/P11",
                        "issue": f"Fuente citada no encontrada en base documental: {doc_id}",
                        "severity": "critical",
                        "action": "Rechazar cita",
                    })

        return violations

    @classmethod
    def check_placeholders_for_missing_data(
        cls, text: str, missing_data: list
    ) -> list[dict]:
        """
        Si hay datos faltantes críticos, el texto debe usar {{PLACEHOLDER}}.
        No se puede presentar un escrito "completo" con datos inventados.
        """
        violations = []

        if missing_data and "{{" not in text:
            critical_missing = [
                d for d in missing_data
                if d.get("impact", "").lower() in ("alto", "crítico", "high", "critical")
                or "esencial" in d.get("description", "").lower()
            ]
            if critical_missing:
                violations.append({
                    "guardrail": "P09/P10",
                    "issue": (
                        f"Hay {len(critical_missing)} datos esenciales faltantes "
                        "pero el texto no contiene {{PLACEHOLDER}}"
                    ),
                    "severity": "high",
                    "action": "Insertar marcadores para datos faltantes",
                })

        return violations

    @classmethod
    def get_prudence_warning(cls) -> str:
        """Advertencia estándar cuando el respaldo es insuficiente."""
        return (
            "⚠️ El respaldo documental disponible es insuficiente "
            "para emitir conclusiones firmes. Las afirmaciones proporcionadas "
            "son orientativas y requieren verificación independiente."
        )
