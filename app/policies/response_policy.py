"""
AILEX — Política de respuesta.

Define la estructura obligatoria de toda salida jurídica,
las reglas de formato y las validaciones de completitud.

Ninguna respuesta sale del sistema sin pasar por esta política.
"""

class ResponsePolicy:
    """
    Política de respuesta para salidas jurídicas.
    Toda respuesta DEBE cumplir con las 8 secciones canónicas.
    """

    # ─── Secciones obligatorias (8 canónicas) ───────────
    # Si una sección no aplica, debe estar presente pero
    # indicando explícitamente su ausencia con motivo.
    MANDATORY_SECTIONS = {
        "resumen_ejecutivo": {
            "label": "Resumen ejecutivo",
            "description": "Síntesis breve de la situación y conclusión principal.",
            "can_be_empty": False,
        },
        "hechos_relevantes": {
            "label": "Hechos relevantes",
            "description": "Lista de hechos, cada uno marcado como EXTRAÍDO o INFERENCIA.",
            "can_be_empty": True,
        },
        "encuadre_preliminar": {
            "label": "Encuadre procesal o jurídico preliminar",
            "description": "Marco normativo aplicable. Solo normas verificables.",
            "can_be_empty": True,
        },
        "acciones_sugeridas": {
            "label": "Acciones sugeridas",
            "description": "Qué hacer, con prioridad y plazos. Marcadas como SUGERENCIA.",
            "can_be_empty": True,
        },
        "riesgos_observaciones": {
            "label": "Riesgos / observaciones",
            "description": "Riesgos procesales, plazos, consecuencias de inacción.",
            "can_be_empty": True,
        },
        "fuentes_respaldo": {
            "label": "Fuentes y respaldo",
            "description": "Documentos y normas que respaldan las afirmaciones.",
            "can_be_empty": True,  # si no hay fuentes, marcar confianza baja
        },
        "datos_faltantes": {
            "label": "Datos faltantes / puntos a verificar",
            "description": "Información necesaria para respuesta más precisa.",
            "can_be_empty": True,
        },
        "nivel_confianza": {
            "label": "Nivel de confianza",
            "description": "Clasificación: alto / medio / bajo / sin_respaldo.",
            "can_be_empty": False,
        },
    }

    # ─── Disclaimer obligatorio ─────────────────────────
    DISCLAIMER = (
        "Esta respuesta es asistencia profesional orientativa. "
        "No sustituye el criterio del abogado. "
        "Verifique todas las fuentes citadas antes de actuar."
    )

    # ─── Reglas de contenido ────────────────────────────
    CONTENT_RULES = [
        "Todo hecho debe estar marcado con su tipo: EXTRAÍDO, INFERENCIA o SUGERENCIA",
        "Toda acción sugerida debe estar marcada como SUGERENCIA",
        "Si el nivel_confianza es bajo, mencionarlo al inicio del resumen_ejecutivo",
        "Si faltan datos críticos, no presentar conclusiones como certezas",
        "No usar frases de cortesía innecesarias",
        "No usar tono vendedor ni dar seguridad artificial",
        "No redactar escritos cerrados si faltan datos esenciales — usar {{PLACEHOLDER}}",
    ]

    @classmethod
    def validate_structure(cls, response: dict) -> tuple[bool, list[str]]:
        """
        Verifica que la respuesta contenga las 8 secciones canónicas.
        Retorna (es_válida, errores).
        """
        errors = []

        for key, spec in cls.MANDATORY_SECTIONS.items():
            if key not in response:
                errors.append(f"Sección obligatoria ausente: '{spec['label']}'")
            elif not spec["can_be_empty"] and not response[key]:
                errors.append(
                    f"Sección '{spec['label']}' no puede estar vacía"
                )

        # Verificar disclaimer
        if not response.get("advertencia_general"):
            errors.append("Falta disclaimer obligatorio.")

        return len(errors) == 0, errors

    @classmethod
    def validate_tagged_facts(cls, hechos: list[dict]) -> list[str]:
        """
        Verifica que cada hecho tenga su tipo de información.
        Rechaza hechos sin clasificar.
        """
        errors = []
        for i, hecho in enumerate(hechos):
            if not hecho.get("info_type"):
                errors.append(
                    f"Hecho #{i+1} sin clasificación de tipo "
                    "(debe ser EXTRAÍDO, INFERENCIA o SUGERENCIA)"
                )
            if hecho.get("info_type") == "extraido" and not hecho.get("source"):
                errors.append(
                    f"Hecho #{i+1} marcado como EXTRAÍDO pero sin fuente vinculada"
                )
        return errors

    @classmethod
    def validate_low_confidence_disclosure(cls, response: dict) -> list[str]:
        """
        Si la confianza es baja, el resumen_ejecutivo debe mencionarlo.
        No se permite confianza baja sin advertencia explícita.
        """
        errors = []
        score = response.get("confianza_score", 0.0)
        nivel = response.get("nivel_confianza", "sin_respaldo")
        resumen = response.get("resumen_ejecutivo", "").lower()

        is_low = score < 0.4 or nivel in ("bajo", "sin_respaldo")
        if is_low:
            low_indicators = [
                "confianza baja", "respaldo insuficiente",
                "datos faltantes", "sin fuentes",
                "orientativ", "verificar", "sin respaldo",
            ]
            has_disclosure = any(ind in resumen for ind in low_indicators)
            if not has_disclosure:
                errors.append(
                    "Confianza baja o sin respaldo pero el resumen_ejecutivo "
                    "no advierte sobre respaldo insuficiente."
                )

        return errors

    @classmethod
    def enforce_disclaimer(cls, response: dict) -> dict:
        """Inyecta el disclaimer obligatorio."""
        response["advertencia_general"] = cls.DISCLAIMER
        return response

    @classmethod
    def validate_completeness(cls, response: dict) -> tuple[bool, list[str]]:
        """
        Validación completa de estructura + contenido.
        Punto de entrada único para validar una respuesta.
        """
        all_errors = []

        # 1. Estructura (8 secciones)
        _, struct_errors = cls.validate_structure(response)
        all_errors.extend(struct_errors)

        # 2. Hechos taggeados
        hechos = response.get("hechos_relevantes", [])
        if isinstance(hechos, list):
            fact_errors = cls.validate_tagged_facts(hechos)
            all_errors.extend(fact_errors)

        # 3. Confianza baja sin disclosure
        disclosure_errors = cls.validate_low_confidence_disclosure(response)
        all_errors.extend(disclosure_errors)

        return len(all_errors) == 0, all_errors
