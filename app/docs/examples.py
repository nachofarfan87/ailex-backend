"""
AILEX — Ejemplos de inputs y outputs esperados.

Documentación ejecutable con casos de uso reales que muestran
cómo debe comportarse el sistema en diferentes escenarios.

Estos ejemplos sirven como:
1. Referencia para desarrollo y testing
2. Contratos de regresión del comportamiento del sistema
3. Documentación viva del formato de respuesta y del pipeline documental

FORMATO CANÓNICO DE SALIDA (8 secciones obligatorias):
  resumen_ejecutivo | hechos_relevantes | encuadre_preliminar
  acciones_sugeridas | riesgos_observaciones | fuentes_respaldo
  datos_faltantes | nivel_confianza
"""


# ═══════════════════════════════════════════════════════════
# EJEMPLO 1: Análisis de Notificación Judicial
# Input → Output esperado con confianza MEDIA
# ═══════════════════════════════════════════════════════════

EXAMPLE_NOTIFICATION_INPUT = {
    "module": "notificaciones",
    "endpoint": "POST /api/notifications/analyze",
    "input": {
        "text": (
            "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
            'Expte. N° 12345/2024 - "GONZÁLEZ, MARÍA C/ LÓPEZ, JUAN S/ DAÑOS Y PERJUICIOS"\n'
            "San Salvador de Jujuy, 5 de marzo de 2026.\n\n"
            "RESOLUCIÓN: Córrase traslado de la demanda al demandado por el "
            "plazo de quince (15) días. Notifíquese."
        ),
    },
}

EXAMPLE_NOTIFICATION_OUTPUT = {
    "resumen_ejecutivo": (
        "Notificación de traslado de demanda en juicio de daños y perjuicios. "
        "El demandado tiene 15 días para contestar. "
        "Respaldo parcial — el plazo surge del texto pero debe verificarse "
        "contra el CPC de Jujuy vigente."
    ),

    "hechos_relevantes": [
        {
            "content": "Expediente identificado: 12345/2024",
            "info_type": "extraido",
            "source": {
                "document_title": "Notificación Expte. 12345/2024",
                "source_hierarchy": "interno",
                "fragment": "Expte. N° 12345/2024",
                "relevance_score": 1.0,
            },
        },
        {
            "content": "Carátula: GONZÁLEZ, MARÍA C/ LÓPEZ, JUAN S/ DAÑOS Y PERJUICIOS",
            "info_type": "extraido",
            "source": {
                "document_title": "Notificación Expte. 12345/2024",
                "source_hierarchy": "interno",
                "fragment": '"GONZÁLEZ, MARÍA C/ LÓPEZ, JUAN S/ DAÑOS Y PERJUICIOS"',
                "relevance_score": 1.0,
            },
        },
        {
            "content": "Se ordena traslado de la demanda por 15 días",
            "info_type": "extraido",
            "source": {
                "document_title": "Notificación Expte. 12345/2024",
                "source_hierarchy": "interno",
                "fragment": "Córrase traslado de la demanda al demandado por el plazo de quince (15) días",
                "relevance_score": 1.0,
            },
        },
        {
            "content": "El plazo de 15 días es hábil y corre desde la notificación efectiva",
            "info_type": "inferencia",
            "source": None,
        },
    ],

    "encuadre_preliminar": [
        "Documento clasificado como 'notificacion'. Verificar normativa procesal aplicable.",
        "Jurisdicción: Provincia de Jujuy, Argentina. Verificar CPC Jujuy.",
        "Verificar si el plazo de 15 días coincide con el CPC de Jujuy vigente.",
        "Determinar fecha exacta de notificación para cómputo de plazo.",
    ],

    "acciones_sugeridas": [
        {
            "action": "Verificar el tipo de resolución notificada y el plazo que genera",
            "info_type": "sugerencia",
            "priority": "alta",
            "risk": "Vencimiento sin respuesta puede generar preclusión o rebeldía",
        },
        {
            "action": "Calcular plazo exacto desde la fecha de notificación efectiva",
            "info_type": "sugerencia",
            "priority": "alta",
            "risk": None,
        },
        {
            "action": "Revisar si corresponde oponer excepciones previas",
            "info_type": "sugerencia",
            "priority": "alta",
            "risk": None,
        },
        {
            "action": "Verificar domicilio constituido para notificaciones",
            "info_type": "sugerencia",
            "priority": "media",
            "risk": None,
        },
    ],

    "riesgos_observaciones": [
        "Sin fecha exacta de notificación, el cómputo de plazo es incierto.",
        "Si no se contesta en plazo: declaración de rebeldía.",
        "Si no se oponen excepciones: preclusión del derecho.",
    ],

    "fuentes_respaldo": [],

    "datos_faltantes": [
        {
            "description": "Fecha exacta de notificación para computar plazo",
            "impact": "Sin ella no se puede calcular el vencimiento",
            "required_for": "Cómputo de plazo procesal",
        },
        {
            "description": "Contenido completo de la demanda",
            "impact": "Necesario para preparar contestación y evaluar excepciones",
            "required_for": "Contestación de demanda",
        },
    ],

    "nivel_confianza": "sin_respaldo",
    "confianza_score": 0.0,
    "modulo_origen": "notificaciones",
    "advertencia_general": (
        "Esta respuesta es asistencia profesional orientativa. "
        "No sustituye el criterio del abogado. "
        "Verifique todas las fuentes citadas antes de actuar."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLOS SIMPLES: Extractor de Notificaciones
# modules/notifications/extractor.py
# ═══════════════════════════════════════════════════════════

ejemplo_notificacion_1 = {
    "_label": "Extractor simple — traslado con plazo",
    "input": (
        "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
        'Expte. N° 12345/2024 - "GONZÁLEZ, MARÍA C/ LÓPEZ, JUAN S/ DAÑOS Y PERJUICIOS"\n'
        "San Salvador de Jujuy, 5 de marzo de 2026.\n"
        "Córrase traslado de la demanda por 5 días."
    ),
    "expected_extraction": {
        "expediente": "12345/2024",
        "partes": "GONZÁLEZ, MARÍA C/ LÓPEZ, JUAN S/ DAÑOS Y PERJUICIOS",
        "organo": "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY",
        "fecha": "5 de marzo de 2026",
        "actuaciones_detectadas": [
            {"tipo": "traslado", "texto": "Córrase traslado"},
        ],
        "plazos_detectados": [
            {"texto": "por 5 días", "cantidad": 5, "unidad": "días"},
        ],
    },
}


ejemplo_notificacion_2 = {
    "_label": "Extractor simple — intimación con apercibimiento",
    "input": (
        "TRIBUNAL EN LO CRIMINAL N° 1\n"
        "Expediente 998/2025\n"
        "San Pedro de Jujuy, 12/02/2026\n"
        "Intímese al demandado a constituir domicilio en el plazo de 48 horas, "
        "bajo apercibimiento de ley. Téngase presente."
    ),
    "expected_extraction": {
        "expediente": "998/2025",
        "partes": None,
        "organo": "TRIBUNAL EN LO CRIMINAL N° 1",
        "fecha": "12/02/2026",
        "actuaciones_detectadas": [
            {"tipo": "intimacion", "texto": "Intímese"},
            {"tipo": "apercibimiento", "texto": "apercibimiento"},
            {"tipo": "tengase_presente", "texto": "Téngase presente"},
        ],
        "plazos_detectados": [
            {"texto": "plazo de 48 horas", "cantidad": 48, "unidad": "horas"},
        ],
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLOS SIMPLES: Motor de Plazos Procesales
# modules/procedural_deadlines/
# ═══════════════════════════════════════════════════════════

ejemplo_plazo_notificacion_1 = {
    "_label": "Traslado por 5 días con fecha disponible",
    "input": (
        "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
        "San Salvador de Jujuy, 5 de marzo de 2026.\n"
        "Córrase traslado de la demanda por 5 días."
    ),
    "expected_deadline": {
        "tipo_actuacion": "plazo_para_contestar",
        "plazo_dias": 5,
        "unidad": "dias",
        "frase_detectada": "Córrase traslado de la demanda por 5 días",
        "requiere_calculo": True,
        "fecha_notificacion": "5 de marzo de 2026",
        "fecha_vencimiento": "2026-03-10",
        "advertencias": [
            "Cálculo estimado simple: no contempla feriados, días inhábiles ni reglas procesales específicas."
        ],
    },
}


ejemplo_plazo_notificacion_2 = {
    "_label": "Intimación por 3 días sin fecha",
    "input": (
        "Intímese a la demandada en 3 días a acompañar la documentación requerida, "
        "bajo apercibimiento de ley."
    ),
    "expected_deadline": {
        "tipo_actuacion": "intimacion",
        "plazo_dias": 3,
        "unidad": "dias",
        "frase_detectada": "Intímese a la demandada en 3 días",
        "requiere_calculo": True,
        "fecha_notificacion": None,
        "fecha_vencimiento": None,
        "advertencias": [
            "Cálculo estimado simple: no contempla feriados, días inhábiles ni reglas procesales específicas.",
            "Falta fecha de notificación para estimar el vencimiento del plazo."
        ],
    },
}


ejemplo_plazo_notificacion_3 = {
    "_label": "Notificación con plazo pero sin base suficiente para calcular",
    "input": (
        "Téngase presente lo informado y subsánese en 2 días el defecto señalado. "
        "Sin constancia de fecha de notificación."
    ),
    "expected_analysis_effect": {
        "hechos_relevantes": [
            "Actuación con plazo detectada: plazo_para_subsanar",
            "Plazo procesal detectado: 2 dias",
        ],
        "riesgos_observaciones": [
            "Falta fecha de notificación para estimar el vencimiento del plazo."
        ],
        "datos_faltantes": [
            "Fecha de notificación suficiente para estimar vencimiento"
        ],
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 2: Revisión de Escrito — Detección de Problemas
# Input con escrito deficiente → Output muestra problemas concretos
# ═══════════════════════════════════════════════════════════

EXAMPLE_REVIEW_INPUT = {
    "module": "auditoria",
    "endpoint": "POST /api/audit/review",
    "input": {
        "text": (
            "CONTESTA DEMANDA. OPONE EXCEPCIONES.\n\n"
            "Señor Juez:\n"
            "Juan López, por derecho propio, contesta la demanda incoada "
            "en mi contra. Niego todos y cada uno de los hechos.\n\n"
            "La demanda es improcedente porque el art. 8000 del Código Civil "
            "establece que no hay responsabilidad en estos casos.\n\n"
            "Pido se rechace la demanda con costas."
        ),
        "tipo_escrito": "contestacion",
    },
}

EXAMPLE_REVIEW_OUTPUT = {
    "resumen_ejecutivo": (
        "Se detectaron 3 problemas en el escrito — algunos de carácter grave. "
        "Confianza media: revisión preliminar basada en patrones. "
        "Verificar cada punto antes de presentar."
    ),

    "hechos_relevantes": [
        {
            "content": "Negativa genérica detectada: 'niego todos y cada uno de los hechos'",
            "info_type": "extraido",
            "source": None,
        },
        {
            "content": "Se cita artículo 8000 — numeración inusual (4+ dígitos), verificar",
            "info_type": "extraido",
            "source": None,
        },
        {
            "content": "No se detecta constitución de domicilio procesal",
            "info_type": "inferencia",
            "source": None,
        },
        {
            "content": "No se detecta ofrecimiento de prueba",
            "info_type": "inferencia",
            "source": None,
        },
    ],

    "encuadre_preliminar": [
        "Tipo de escrito indicado: contestacion.",
        "FORMAL: Negativa genérica sin fundamentación individual",
        "FORMAL: No se constituye domicilio procesal ni electrónico",
        "FORMAL: No se detecta ofrecimiento de prueba",
        "SUSTANCIAL: Art. 8000 — numeración inusual, posible cita incorrecta",
    ],

    "acciones_sugeridas": [
        {
            "action": "Desarrollar negativa específica hecho por hecho con fundamento",
            "info_type": "sugerencia",
            "priority": "alta",
            "risk": "Negativa genérica puede ser considerada reconocimiento tácito",
        },
        {
            "action": "Constituir domicilio procesal y electrónico",
            "info_type": "sugerencia",
            "priority": "media",
            "risk": None,
        },
        {
            "action": "Agregar ofrecimiento de prueba",
            "info_type": "sugerencia",
            "priority": "media",
            "risk": None,
        },
        {
            "action": "Verificar existencia del artículo 8000 en el cuerpo normativo citado",
            "info_type": "sugerencia",
            "priority": "alta",
            "risk": "Cita de artículo inexistente puede generar observación del tribunal",
        },
    ],

    "riesgos_observaciones": [
        "1 artículo(s) con numeración inusual. Cita normativa incorrecta debilita el escrito.",
        "Negativa genérica: en algunos fueros equivale a reconocimiento tácito de hechos.",
    ],

    "fuentes_respaldo": [],

    "datos_faltantes": [
        {
            "description": "Demanda original para contrastar hechos y pretensiones",
            "impact": "Sin ella no se puede evaluar la suficiencia de la contestación",
            "required_for": "Revisión de contestación de demanda",
        },
    ],

    "nivel_confianza": "sin_respaldo",
    "confianza_score": 0.0,
    "modulo_origen": "auditoria",
    "advertencia_general": (
        "Esta respuesta es asistencia profesional orientativa. "
        "No sustituye el criterio del abogado. "
        "Verifique todas las fuentes citadas antes de actuar."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 3: Lo que AILEX NUNCA debe hacer
# Para testing de guardrails — LegalGuardrails.check_output()
# debe detectar estas violaciones
# ═══════════════════════════════════════════════════════════

EXAMPLE_BAD_OUTPUT = {
    "_label": "EJEMPLO DE RESPUESTA PROHIBIDA — NO IMITAR",
    "_violations": [
        "P01: Inventa artículo inexistente (art. 458 bis)",
        "P02: Inventa jurisprudencia (fallo Rodríguez c/ Martínez)",
        "P07/P08: Da certeza artificial ('sin lugar a dudas')",
        "O01: No marca datos faltantes",
        "O01: No diferencia entre extraído e inferencia",
        "P07: Tono vendedor",
    ],
    "resumen_ejecutivo": (
        "Sin lugar a dudas, este caso tiene una solución favorable. "
        "Según el art. 458 bis del CPC y el fallo 'Rodríguez c/ Martínez' "
        "del STJ de Jujuy, la demanda será rechazada con certeza."
    ),
    "_nota": (
        "LegalGuardrails.check_output() debe detectar 'sin lugar a dudas' "
        "como certeza artificial (P07/P08). "
        "El sistema debe rechazar este tipo de respuesta antes de entregarla."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 4: Generación de Escrito con Datos Faltantes
# Muestra comportamiento correcto: placeholders, no invención
# ═══════════════════════════════════════════════════════════

EXAMPLE_GENERATION_INPUT = {
    "module": "generacion",
    "endpoint": "POST /api/generation/generate",
    "input": {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "demanda",
        "variante": "estandar",
        "hechos": None,
        "datos": None,
    },
}

EXAMPLE_GENERATION_OUTPUT = {
    "resumen_ejecutivo": (
        "Borrador generado para demanda (estandar) — fuero civil, materia daños y perjuicios. "
        "Contiene datos pendientes de completar ({{PLACEHOLDER}}). "
        "Sin respaldo documental: score de confianza bajo hasta que se cargue contexto."
    ),
    "_borrador_fragment": (
        "PROMUEVE DEMANDA — DAÑOS Y PERJUICIOS\n\n"
        "{{NOMBRE_COMPLETO_ACTOR}}, DNI {{DNI_ACTOR}}, con domicilio real en "
        "{{DOMICILIO_REAL_ACTOR}}, constituyendo domicilio procesal en "
        "{{DOMICILIO_PROCESAL}}, con patrocinio del Dr./Dra. {{NOMBRE_ABOGADO}}, "
        "Tomo {{TOMO}}, Folio {{FOLIO}}...\n\n"
        "II. HECHOS\n{{RELATO_DE_HECHOS}}\n\n"
        "III. DERECHO\n{{FUNDAMENTO_NORMATIVO — verificar artículos aplicables}}\n\n"
        "IV. PRUEBA\n{{OFRECIMIENTO_DE_PRUEBA}}\n"
    ),
    "datos_faltantes": [
        {"description": "Nombre Completo Actor", "impact": "Dato necesario para completar el escrito"},
        {"description": "Dni Actor", "impact": "Dato necesario para completar el escrito"},
        {"description": "Domicilio Real Actor", "impact": "Dato necesario para completar el escrito"},
        {"description": "Domicilio Procesal", "impact": "Dato necesario para completar el escrito"},
        {"description": "Nombre Abogado", "impact": "Dato necesario para completar el escrito"},
        {"description": "Relato De Hechos", "impact": "Dato necesario para completar el escrito"},
        {"description": "Fundamento Normativo", "impact": "Dato necesario para completar el escrito"},
        {"description": "Ofrecimiento De Prueba", "impact": "Dato necesario para completar el escrito"},
    ],
    "nivel_confianza": "sin_respaldo",
    "confianza_score": 0.0,
    "modulo_origen": "generacion",
    "_nota": (
        "AILEX NUNCA rellena estos campos con datos inventados. "
        "Siempre usa {{PLACEHOLDER}} y lista los faltantes en datos_faltantes. "
        "La regla P09 prohíbe completar huecos con invención."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 5: Estrategia con nivel_confianza BAJO explícito
# Muestra cómo manejar incertidumbre sin ocultarla
# ═══════════════════════════════════════════════════════════

EXAMPLE_STRATEGY_OUTPUT = {
    "_label": "Respuesta estratégica con confianza baja — incertidumbre explícita",
    "resumen_ejecutivo": (
        "Sin respaldo documental suficiente para recomendar estrategia con certeza. "
        "Las opciones presentadas son orientativas y requieren verificación "
        "de normativa procesal local antes de actuar."
    ),

    "hechos_relevantes": [
        {
            "content": "Vencimiento de plazo de contestación inminente",
            "info_type": "extraido",
            "source": None,
        },
        {
            "content": "Se infiere que aplica el fuero civil por la naturaleza del reclamo",
            "info_type": "inferencia",
            "source": None,
        },
    ],

    "encuadre_preliminar": [
        "Jurisdicción: Jujuy, Argentina. Sin normativa específica cargada en la sesión.",
        "Marco procesal: CPC de Jujuy — requiere verificación directa.",
    ],

    "acciones_sugeridas": [
        {
            "action": "Verificar plazo exacto en el CPC de Jujuy antes de cualquier acto procesal",
            "info_type": "sugerencia",
            "priority": "alta",
            "risk": "Actuar fuera de plazo implica consecuencias procesales graves",
        },
        {
            "action": "Evaluar solicitud de suspensión de plazo si hay causa justificada",
            "info_type": "sugerencia",
            "priority": "media",
            "risk": None,
        },
    ],

    "riesgos_observaciones": [
        "Ausencia de normativa en la sesión impide confirmar plazos y procedimientos.",
        "No se puede recomendar estrategia definitiva sin el expediente completo.",
    ],

    "fuentes_respaldo": [],

    "datos_faltantes": [
        {
            "description": "Expediente completo con todas las resoluciones",
            "impact": "Sin él no se puede evaluar el estado procesal completo",
            "required_for": "Estrategia procesal",
        },
        {
            "description": "Fecha exacta del acto procesal que genera el plazo",
            "impact": "Sin ella no se puede calcular el vencimiento",
            "required_for": "Cómputo de plazo",
        },
    ],

    "nivel_confianza": "bajo",
    "confianza_score": 0.0,
    "modulo_origen": "estrategia",
    "advertencia_general": (
        "Esta respuesta es asistencia profesional orientativa. "
        "No sustituye el criterio del abogado. "
        "Verifique todas las fuentes citadas antes de actuar."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLOS ADICIONALES: Estrategia Procesal Comparada
# POST /api/strategy/analyze
# ═══════════════════════════════════════════════════════════

EXAMPLE_STRATEGY_OPTIONS_TRASLADO = {
    "_label": "Traslado con varias opciones de respuesta",
    "endpoint": "POST /api/strategy/analyze",
    "input": {
        "text": (
            "Se corre traslado de la demanda por cinco días. "
            "La documentación del cliente aún está incompleta."
        ),
        "tipo_proceso": "civil",
        "etapa_procesal": "traslado de demanda",
        "objetivo_abogado": "definir respuesta inicial sin cerrar defensas prematuramente",
    },
    "expected_structure": {
        "opciones_estrategicas": [
            {"nombre": "contestar traslado"},
            {"nombre": "reservar planteo"},
            {"nombre": "esperar constancia o documentación antes de actuar"},
        ],
        "comparacion_opciones": [
            {"perfil": "conservadora"},
            {"perfil": "estándar"},
            {"perfil": "ofensiva prudente"},
            {"perfil": "diferir_decision_por_falta_de_datos"},
        ],
        "recomendacion_prudente": (
            "Podría ser razonable priorizar contestar traslado o una variante de menor exposición, "
            "según la documentación faltante y el plazo real."
        ),
    },
}


EXAMPLE_STRATEGY_SUBSANACION = {
    "_label": "Escrito con defectos que admite subsanación o reformulación",
    "endpoint": "POST /api/strategy/analyze",
    "input": {
        "text": "El tribunal observó defectos formales y ordenó subsanar la presentación.",
        "tipo_proceso": "civil",
        "etapa_procesal": "observación formal",
        "objetivo_abogado": "corregir sin perder posición procesal",
        "hallazgos_revision": [
            "Falta precisión en el petitorio",
            "No se individualiza claramente la documental acompañada",
        ],
    },
    "expected_structure": {
        "opciones_estrategicas": [
            {"nombre": "subsanar presentación"},
            {"nombre": "reformular escrito"},
            {"nombre": "reservar planteo"},
        ],
        "version_corta_para_abogado": (
            "Opciones a mirar primero: subsanar presentación, reformular escrito, reservar planteo."
        ),
    },
}


EXAMPLE_STRATEGY_WEAK_SUPPORT = {
    "_label": "Situación con respaldo documental débil",
    "endpoint": "POST /api/strategy/analyze",
    "input": {
        "text": "Hay una posible demora del expediente, pero no tengo constancias ni despacho visible.",
        "objetivo_abogado": "evaluar si conviene mover el expediente",
    },
    "expected_structure": {
        "opciones_estrategicas": [
            {"nombre": "esperar constancia o documentación antes de actuar"},
            {"nombre": "solicitar pronto despacho"},
        ],
        "nivel_confianza": "sin_respaldo",
        "riesgos_observaciones": [
            "La viabilidad de las opciones no puede valorarse con solidez sin normativa, jurisprudencia o constancias relevantes."
        ],
    },
}


EXAMPLE_STRATEGY_PRONTO_DESPACHO = {
    "_label": "Pronto despacho versus esperar constancia",
    "endpoint": "POST /api/strategy/options",
    "input": {
        "text": "El expediente no muestra movimiento desde hace meses, pero no tengo copia del último pase.",
        "tipo_proceso": "contencioso",
        "objetivo_abogado": "reactivar el trámite",
    },
    "expected_structure": {
        "comparacion_opciones": [
            {
                "perfil": "conservadora",
                "opciones_priorizadas": [
                    "esperar constancia o documentación antes de actuar",
                ],
            },
            {
                "perfil": "estándar",
                "opciones_priorizadas": [
                    "solicitar pronto despacho",
                ],
            },
        ],
    },
}


EXAMPLE_STRATEGY_PRUDENT_RECOMMENDATION = {
    "_label": "Estrategia con recomendación prudente pero no cerrada",
    "endpoint": "POST /api/strategy/quick",
    "input": {
        "text": "Se notificó una resolución desfavorable y aún falta revisar el expediente completo.",
        "tipo_proceso": "civil",
        "etapa_procesal": "post resolución",
        "objetivo_abogado": "preservar opciones recursivas sin sobreactuar",
    },
    "expected_structure": {
        "recomendacion_prudente": (
            "Una línea prudente podría comenzar por apelar o por una variante de menor exposición, "
            "sin descartar diferir la decisión si el expediente muestra matices relevantes."
        ),
        "version_corta_para_abogado": (
            "Opciones a mirar primero: apelar, reservar planteo, esperar constancia o documentación antes de actuar."
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLOS: Workflow Jurídico Integrado
# POST /api/workflow/notification-response
# ═══════════════════════════════════════════════════════════

EXAMPLE_WORKFLOW_TRASLADO = {
    "_label": "Traslado con sugerencia de contesta_traslado",
    "endpoint": "POST /api/workflow/notification-response",
    "input": {
        "texto": (
            "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
            "San Salvador de Jujuy, 5 de marzo de 2026.\n"
            "Córrase traslado de la demanda por 5 días."
        ),
        "fuero": "civil",
        "materia": "general",
        "objetivo_usuario": "preparar respuesta inicial prudente",
    },
    "expected_structure": {
        "actuacion_detectada": "Córrase traslado",
        "plazo_detectado": "Córrase traslado de la demanda por 5 días",
        "vencimiento_estimado": "2026-03-10",
        "tipo_escrito_sugerido": {
            "tipo_escrito": "contesta_traslado",
            "disponible_en_generador": True,
        },
    },
}


EXAMPLE_WORKFLOW_INTIMACION_DOCUMENTAL = {
    "_label": "Intimación para acompañar documental",
    "endpoint": "POST /api/workflow/notification-response",
    "input": {
        "texto": (
            "Intímese a la parte actora a acompañar la documental ofrecida "
            "en el plazo de 3 días."
        ),
        "fuero": "civil",
        "materia": "general",
        "objetivo_usuario": "regularizar la documentación requerida",
    },
    "expected_structure": {
        "tipo_escrito_sugerido": {
            "tipo_escrito": "acompana_documentacion",
            "disponible_en_generador": True,
        },
        "opciones_estrategicas_resumidas": [
            {"nombre": "intimar previamente"},
            {"nombre": "esperar constancia o documentación antes de actuar"},
        ],
    },
}


EXAMPLE_WORKFLOW_NOTIFICATION_INSUFFICIENT = {
    "_label": "Notificación insuficiente con estrategia de esperar constancia",
    "endpoint": "POST /api/workflow/notification-response",
    "input": {
        "texto": "Se informa una posible demora del expediente, sin constancias adjuntas.",
        "objetivo_usuario": "decidir si conviene impulsar una medida",
        "generar_borrador": False,
    },
    "expected_structure": {
        "tipo_escrito_sugerido": {
            "tipo_escrito": None,
            "borrador_generado": False,
        },
        "riesgos_inmediatos": [
            "La viabilidad de las opciones no puede valorarse con solidez sin normativa, jurisprudencia o constancias relevantes."
        ],
        "datos_faltantes": [
            {"description": "Etapa procesal precisa"},
        ],
    },
}


EXAMPLE_WORKFLOW_FULL = {
    "_label": "Flujo completo con borrador y revisión",
    "endpoint": "POST /api/workflow/notification-response",
    "input": {
        "texto": (
            "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
            "Expte. N° 12345/2026\n"
            "San Salvador de Jujuy, 5 de marzo de 2026.\n"
            "Córrase traslado de la demanda por 5 días."
        ),
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "objetivo_usuario": "obtener un borrador base y revisarlo antes de responder",
        "datos_caso": {
            "actor": "María González",
            "demandado": "Juan López",
            "materia": "daños y perjuicios",
        },
    },
    "expected_structure": {
        "tipo_escrito_sugerido": {
            "tipo_escrito": "contesta_traslado",
            "borrador_generado": True,
        },
        "borrador_inicial": "CONTESTA TRASLADO",
        "observaciones_revision": {
            "hallazgos_clave": [],
            "mejoras_sugeridas": [],
        },
        "fuentes_respaldo": [],
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 6: Ingestión — Artículo de código
# POST /api/documents/upload/text
# ═══════════════════════════════════════════════════════════

EXAMPLE_INGESTION_CODIGO_INPUT = {
    "_label": "Ingestión de artículo de código procesal",
    "endpoint": "POST /api/documents/upload/text",
    "input_form": {
        "title": "CPC Jujuy — Art. 338: Traslado de la demanda",
        "text": (
            "Art. 338. — Plazo para contestar la demanda.\n\n"
            "El demandado deberá contestar la demanda dentro del plazo de quince (15) "
            "días hábiles contados desde la notificación de la resolución que ordena "
            "el traslado.\n\n"
            "En los procesos sumarísimos el plazo será de cinco (5) días hábiles.\n\n"
            "Art. 339. — Forma de la contestación.\n\n"
            "La contestación de la demanda deberá observar las formas prescriptas "
            "para la demanda, negando o admitiendo categoricamente cada uno de los "
            "hechos expuestos en ella."
        ),
        "source_type": "codigo",
        "jurisdiction": "Jujuy",
        "legal_area": "civil",
        "fuero": "Civil y Comercial",
        "description": "Código Procesal Civil y Comercial de Jujuy — Plazos de contestación",
        "tags": "plazo, contestacion, demanda, traslado",
    },
    "expected_result": {
        "status": "indexed",
        "source_type": "codigo",
        "source_hierarchy": "normativa",
        "chunk_count": 2,
        "_nota": (
            "El chunker detecta los artículos y crea un chunk por artículo. "
            "chunk_count=2 porque hay Art. 338 y Art. 339."
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 7: Ingestión — Sentencia
# POST /api/documents/upload/text
# ═══════════════════════════════════════════════════════════

EXAMPLE_INGESTION_SENTENCIA_INPUT = {
    "_label": "Ingestión de sentencia judicial",
    "endpoint": "POST /api/documents/upload/text",
    "input_form": {
        "title": "STJ Jujuy — Sala Civil — Expte. 22-456/2023",
        "text": (
            "SUMARIO: Daños y perjuicios. Accidente de tránsito. "
            "Responsabilidad objetiva. Art. 1757 CCCN. Concausalidad.\n\n"
            "CONSIDERANDOS:\n\n"
            "I. Que el actor reclama indemnización por daños sufridos en accidente "
            "vial ocurrido en calle San Martín de esta ciudad el día 15/03/2022. "
            "La prueba producida acredita que el demandado circulaba a velocidad "
            "excesiva al momento del impacto.\n\n"
            "II. Que en materia de daños derivados del riesgo de la cosa, "
            "corresponde aplicar la responsabilidad objetiva prevista en el art. 1757 "
            "del Código Civil y Comercial de la Nación.\n\n"
            "RESUELVE:\n\n"
            "I. Hacer lugar a la demanda de daños y perjuicios promovida por el actor "
            "contra el demandado, y condenar a este último al pago de la suma de "
            "$ {{MONTO}} en concepto de indemnización.\n"
            "II. Imponer las costas al demandado vencido.\n"
            "III. Notifíquese."
        ),
        "source_type": "jurisprudencia",
        "jurisdiction": "Jujuy",
        "legal_area": "civil",
        "fuero": "Civil y Comercial",
        "court": "STJ Jujuy — Sala Civil",
        "description": "Fallo sobre daños y perjuicios por accidente de tránsito",
        "tags": "daños, accidente, responsabilidad objetiva, art 1757",
    },
    "expected_result": {
        "status": "indexed",
        "source_type": "jurisprudencia",
        "source_hierarchy": "jurisprudencia",
        "_nota": (
            "El chunker detecta SUMARIO, CONSIDERANDOS y RESUELVE "
            "y crea chunks separados. Permite citar cada sección individualmente."
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 8: Ingestión — Escrito histórico del estudio
# POST /api/documents/upload/text
# ═══════════════════════════════════════════════════════════

EXAMPLE_INGESTION_ESCRITO_INPUT = {
    "_label": "Ingestión de escrito histórico del estudio",
    "endpoint": "POST /api/documents/upload/text",
    "input_form": {
        "title": "Modelo: Excepción de prescripción en juicio laboral",
        "text": (
            "OPONE EXCEPCIÓN DE PRESCRIPCIÓN\n\n"
            "Señor/a Juez/a:\n\n"
            "I. HECHOS\n\n"
            "Que el actor demanda el cobro de haberes adeudados correspondientes "
            "al período enero-diciembre de 2019. Sin embargo, la acción laboral "
            "prescribe a los dos años (art. 256 LCT).\n\n"
            "II. DERECHO\n\n"
            "El art. 256 de la Ley de Contrato de Trabajo establece que las "
            "acciones relativas a créditos provenientes de las relaciones "
            "individuales de trabajo prescriben a los dos años.\n\n"
            "III. PETITORIO\n\n"
            "Solicito se haga lugar a la excepción de prescripción y se rechace "
            "la demanda, con costas al actor."
        ),
        "source_type": "escrito",
        "jurisdiction": "Jujuy",
        "legal_area": "laboral",
        "fuero": "Laboral y de la Seguridad Social",
        "description": "Modelo de excepción de prescripción laboral — art. 256 LCT",
        "tags": "prescripcion, laboral, excepcion, LCT",
    },
    "expected_result": {
        "status": "indexed",
        "source_type": "escrito",
        "source_hierarchy": "interno",
        "_nota": (
            "source_hierarchy=interno porque es material del estudio. "
            "No tiene peso argumental formal pero sirve como modelo y referencia."
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 9: Búsqueda por materia
# POST /api/search/
# ═══════════════════════════════════════════════════════════

EXAMPLE_SEARCH_INPUT = {
    "_label": "Búsqueda: plazos de contestación de demanda en Jujuy",
    "endpoint": "POST /api/search/",
    "input": {
        "query": "plazo para contestar la demanda en juicio civil Jujuy",
        "jurisdiction": "Jujuy",
        "source_hierarchy": "normativa",
        "legal_area": "civil",
        "top_k": 5,
    },
    "expected_result_structure": {
        "results": [
            {
                "chunk_id": "...",
                "document_id": "...",
                "text": "Art. 338. — Plazo para contestar la demanda...",
                "document_title": "CPC Jujuy — Art. 338: Traslado de la demanda",
                "source_type": "codigo",
                "source_hierarchy": "normativa",
                "jurisdiction": "Jujuy",
                "legal_area": "civil",
                "section": "Art. 338",
                "article_reference": "Art. 338",
                "page_number": None,
                "vigente": True,
                "scores": {
                    "vector": 0.72,
                    "keyword": 0.68,
                    "legal": 0.95,
                    "final": 0.79,
                },
                "retrieval_explanation": (
                    "vector=0.7200 | keyword=0.6800 | legal=0.9500 | "
                    "jurisdiction=Jujuy | source_hierarchy=normativa"
                ),
            }
        ],
        "total": 1,
        "query": "plazo para contestar la demanda en juicio civil Jujuy",
        "search_mode": "hybrid",
        "search_profile": "general",
        "filters_applied": {
            "jurisdiction": "Jujuy",
            "source_hierarchy": "normativa",
            "source_type": None,
            "legal_area": "civil",
            "vigente": None,
        },
        "_nota": (
            "El score legal es alto (0.95) porque: "
            "source_hierarchy=normativa (1.0 * 0.5) + "
            "jurisdiction=Jujuy match (0.25) + "
            "legal_area=civil match (0.20) = 0.95."
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 10: Cómo poblar fuentes_respaldo desde búsqueda
# Integración SearchResult → SourceCitationSchema
# ═══════════════════════════════════════════════════════════

EXAMPLE_CITATION_INTEGRATION = {
    "_label": "Integración: SearchResult → fuentes_respaldo en JuridicalResponse",
    "_code_example": """
# En un servicio de análisis, después de buscar documentos relevantes:

from app.modules.search.service import HybridSearchService, SearchFilters
from app.modules.traceability.citations import search_results_to_citations
from app.db.store import DocumentStore

store = DocumentStore()
search_service = HybridSearchService()

# 1. Obtener chunks relevantes
chunks = store.get_all_chunks()
filters = SearchFilters(jurisdiction="Jujuy", source_hierarchy="normativa")

# 2. Buscar
results = search_service.search(
    query="plazo contestacion demanda civil",
    chunks=chunks,
    filters=filters,
    top_k=5,
)

# 3. Convertir a SourceCitationSchema (compatible con JuridicalResponse)
fuentes = search_results_to_citations(results, max_citations=3, min_score=0.1)

# 4. Incluir en JuridicalResponse
response = JuridicalResponse(
    resumen_ejecutivo="...",
    fuentes_respaldo=fuentes,   # <-- Trazabilidad real
    nivel_confianza="medio",    # Sube automáticamente si hay fuentes normativas
    ...
)
""",
    "_nota": (
        "Con fuentes reales de tipo 'normativa', el nivel_confianza "
        "puede subir a 'medio' o 'alto' automáticamente via ConfidencePolicy. "
        "Sin fuentes, siempre queda en 'sin_respaldo'."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 11: Indexación de embeddings por documento
# POST /api/documents/{id}/index
# ═══════════════════════════════════════════════════════════

EXAMPLE_DOCUMENT_INDEX_REQUEST = {
    "_label": "Indexación de chunks ya ingeridos para búsqueda vectorial",
    "endpoint": "POST /api/documents/doc_cpc_jujuy_338/index",
    "expected_result": {
        "status": "indexed",
        "document_id": "doc_cpc_jujuy_338",
        "document_title": "CPC Jujuy — Art. 338: Traslado de la demanda",
        "chunks_indexed": 2,
        "embedding_model": "text-embedding-3-small",
        "errors": [],
    },
    "_nota": (
        "Se usa luego de la ingestión cuando se quiere regenerar embeddings "
        "con el proveedor configurado sin volver a cargar el documento."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 12: Reindexación global de la base documental
# POST /api/documents/reindex
# ═══════════════════════════════════════════════════════════

EXAMPLE_REINDEX_REQUEST = {
    "_label": "Reindexación global tras cambio de modelo de embeddings",
    "endpoint": "POST /api/documents/reindex",
    "expected_result_structure": {
        "status": "completed",
        "documents_processed": 3,
        "total_chunks_indexed": 11,
        "total_errors": 0,
        "embedding_model": "text-embedding-3-small",
        "results": [
            {
                "document_id": "doc_cpc_jujuy_338",
                "title": "CPC Jujuy — Art. 338: Traslado de la demanda",
                "status": "indexed",
                "chunks_indexed": 2,
                "error": None,
            },
            {
                "document_id": "doc_stj_danos_2023",
                "title": "STJ Jujuy — Sala Civil — Expte. 22-456/2023",
                "status": "indexed",
                "chunks_indexed": 5,
                "error": None,
            },
        ],
    },
    "_nota": (
        "Para una reindexación por lote controlado, repetir el patrón "
        "de POST /api/documents/{id}/index sobre el subconjunto deseado."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 13: Búsqueda semántica pura
# POST /api/search/semantic
# ═══════════════════════════════════════════════════════════

EXAMPLE_SEMANTIC_SEARCH_INPUT = {
    "_label": "Búsqueda semántica de jurisprudencia por tema",
    "endpoint": "POST /api/search/semantic",
    "input": {
        "query": "responsabilidad objetiva por accidente de tránsito",
        "jurisdiction": "Jujuy",
        "source_type": "jurisprudencia",
        "legal_area": "civil",
        "vigente": True,
        "top_k": 3,
    },
    "expected_result_structure": {
        "results": [
            {
                "chunk_id": "chunk_stj_danos_003",
                "document_id": "doc_stj_danos_2023",
                "text": (
                    "La responsabilidad objetiva del dueño o guardián del automotor "
                    "solo cede ante prueba suficiente de causa ajena."
                ),
                "document_title": "STJ Jujuy — Sala Civil — Expte. 22-456/2023",
                "source_type": "jurisprudencia",
                "source_hierarchy": "jurisprudencia",
                "jurisdiction": "Jujuy",
                "legal_area": "civil",
                "section": "Considerando IV",
                "article_reference": "",
                "page_number": 7,
                "vigente": True,
                "scores": {
                    "vector": 0.9132,
                    "keyword": 0.0,
                    "legal": 0.0,
                    "final": 0.9132,
                },
                "retrieval_explanation": "semantic_only | vector=0.9132",
            }
        ],
        "total": 1,
        "query": "responsabilidad objetiva por accidente de tránsito",
        "search_mode": "semantic",
        "nota": (
            "Solo similitud vectorial — sin ranking jurídico. "
            "El campo text funciona como extracto recuperado."
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 14: Búsqueda híbrida con perfil jurídico
# POST /api/search/hybrid
# ═══════════════════════════════════════════════════════════

EXAMPLE_HYBRID_SEARCH_INPUT = {
    "_label": "Búsqueda híbrida de plazos procesales con perfil notifications",
    "endpoint": "POST /api/search/hybrid",
    "input": {
        "query": "traslado de demanda plazo apercibimiento rebeldia",
        "jurisdiction": "Jujuy",
        "legal_area": "civil",
        "vigente": True,
        "top_k": 5,
        "search_profile": "notifications",
    },
    "expected_result_structure": {
        "results": [
            {
                "chunk_id": "chunk_cpc_338",
                "document_id": "doc_cpc_jujuy_338",
                "text": (
                    "El demandado deberá contestar la demanda dentro del plazo "
                    "de quince (15) días hábiles contados desde la notificación."
                ),
                "document_title": "CPC Jujuy — Art. 338: Traslado de la demanda",
                "source_type": "codigo",
                "source_hierarchy": "normativa",
                "jurisdiction": "Jujuy",
                "legal_area": "civil",
                "section": "Art. 338",
                "article_reference": "Art. 338",
                "page_number": None,
                "vigente": True,
                "scores": {
                    "vector": 0.8041,
                    "keyword": 0.7714,
                    "legal": 0.97,
                    "final": 0.8572,
                },
                "retrieval_explanation": (
                    "profile=notifications | normativa procesal vigente | "
                    "jurisdiction=Jujuy | vector=0.8041 | keyword=0.7714"
                ),
            },
            {
                "chunk_id": "chunk_acordada_notif_001",
                "document_id": "doc_acordada_notificaciones_2025",
                "text": (
                    "Las notificaciones electrónicas se tendrán por perfeccionadas "
                    "conforme la acordada vigente del Superior Tribunal."
                ),
                "document_title": "Acordada STJ Jujuy 12/2025 — Notificaciones electrónicas",
                "source_type": "acordada",
                "source_hierarchy": "normativa",
                "jurisdiction": "Jujuy",
                "legal_area": "procesal",
                "section": "Punto 4",
                "article_reference": "",
                "page_number": 2,
                "vigente": True,
                "scores": {
                    "vector": 0.7124,
                    "keyword": 0.694,
                    "legal": 0.93,
                    "final": 0.7811,
                },
                "retrieval_explanation": (
                    "profile=notifications | acordada procesal vigente | "
                    "afinidad con notificación electrónica"
                ),
            },
        ],
        "total": 2,
        "query": "traslado de demanda plazo apercibimiento rebeldia",
        "search_mode": "hybrid",
        "search_profile": "notifications",
        "filters_applied": {
            "jurisdiction": "Jujuy",
            "source_hierarchy": None,
            "source_type": None,
            "legal_area": "civil",
            "vigente": True,
        },
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 15: Análisis con recuperación documental y trazabilidad
# POST /api/analysis/analyze
# ═══════════════════════════════════════════════════════════

EXAMPLE_ANALYSIS_WITH_RAG = {
    "_label": "Análisis de notificación con fuentes_respaldo recuperadas",
    "endpoint": "POST /api/analysis/analyze",
    "input": {
        "text": (
            "JUZGADO CIVIL Y COMERCIAL N° 3 - JUJUY\n"
            "Se corre traslado de la demanda por quince días. "
            "Notifíquese al demandado bajo apercibimiento de rebeldía."
        ),
    },
    "expected_output": {
        "resumen_ejecutivo": (
            "Se detecta un traslado de demanda en fuero civil de Jujuy. "
            "El plazo de quince días surge del acto y encuentra respaldo "
            "en normativa procesal local recuperada."
        ),
        "hechos_relevantes": [
            {
                "content": "El documento ordena correr traslado de la demanda al demandado.",
                "info_type": "extraido",
                "source": None,
            },
            {
                "content": "El plazo de contestación recuperado para el CPC de Jujuy es de 15 días hábiles.",
                "info_type": "extraido",
                "source": {
                    "document_id": "doc_cpc_jujuy_338",
                    "document_title": "CPC Jujuy — Art. 338: Traslado de la demanda",
                    "source_hierarchy": "normativa",
                    "fragment": (
                        "El demandado deberá contestar la demanda dentro del plazo "
                        "de quince (15) días hábiles contados desde la notificación."
                    ),
                    "page_or_section": "Art. 338",
                    "relevance_score": 0.94,
                },
            },
        ],
        "encuadre_preliminar": [
            "Documento clasificado como notificación judicial con incidencia procesal inmediata.",
            "La recuperación RAG priorizó normativa de Jujuy y jurisprudencia procesal vinculada.",
        ],
        "acciones_sugeridas": [
            {
                "action": "Calcular el vencimiento desde la fecha de notificación efectiva",
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": "La rebeldía procesal puede declararse por falta de contestación en término",
            },
            {
                "action": "Verificar si corresponde contestación de demanda o planteo previo",
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": None,
            },
        ],
        "riesgos_observaciones": [
            "La fecha exacta de notificación sigue siendo necesaria para computar el plazo.",
            "La recuperación es sólida en normativa, pero el expediente completo puede alterar la estrategia.",
        ],
        "fuentes_respaldo": [
            {
                "document_id": "doc_cpc_jujuy_338",
                "document_title": "CPC Jujuy — Art. 338: Traslado de la demanda",
                "source_hierarchy": "normativa",
                "fragment": (
                    "El demandado deberá contestar la demanda dentro del plazo "
                    "de quince (15) días hábiles contados desde la notificación."
                ),
                "page_or_section": "Art. 338",
                "relevance_score": 0.94,
            },
            {
                "document_id": "doc_stj_procesal_2024",
                "document_title": "STJ Jujuy — Sala Civil — 'P., M. c/ Q., R.'",
                "source_hierarchy": "jurisprudencia",
                "fragment": (
                    "El apercibimiento de rebeldía presupone la correcta notificación "
                    "del traslado y el vencimiento del plazo legal."
                ),
                "page_or_section": "Consid. III",
                "relevance_score": 0.72,
            },
        ],
        "datos_faltantes": [
            {
                "description": "Fecha exacta de notificación",
                "impact": "Sin ella no puede computarse el vencimiento del traslado",
                "required_for": "Cómputo procesal",
            }
        ],
        "nivel_confianza": "medio",
        "confianza_score": 0.74,
        "modulo_origen": "analisis",
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 16: Auditoría con apoyo en normativa y jurisprudencia
# POST /api/audit/review
# ═══════════════════════════════════════════════════════════

EXAMPLE_AUDIT_WITH_RAG = {
    "_label": "Auditoría de contestación con respaldo normativo y jurisprudencial",
    "endpoint": "POST /api/audit/review",
    "input": {
        "text": (
            "CONTESTA DEMANDA.\n\n"
            "Niego todos y cada uno de los hechos. "
            "Solicito se rechace la demanda sin más trámite."
        ),
        "tipo_escrito": "contestacion",
    },
    "expected_output": {
        "resumen_ejecutivo": (
            "La revisión detecta una negativa genérica riesgosa. "
            "La observación queda respaldada por normativa procesal y jurisprudencia local recuperadas."
        ),
        "hechos_relevantes": [
            {
                "content": "El escrito formula una negativa genérica sin contestación circunstanciada.",
                "info_type": "extraido",
                "source": None,
            },
            {
                "content": "El CPC local exige negar o admitir categóricamente los hechos de la demanda.",
                "info_type": "extraido",
                "source": {
                    "document_id": "doc_cpc_jujuy_339",
                    "document_title": "CPC Jujuy — Art. 339: Forma de la contestación",
                    "source_hierarchy": "normativa",
                    "fragment": (
                        "La contestación de la demanda deberá negar o admitir "
                        "categóricamente cada uno de los hechos expuestos."
                    ),
                    "page_or_section": "Art. 339",
                    "relevance_score": 0.96,
                },
            },
        ],
        "encuadre_preliminar": [
            "La auditoría recuperó primero normativa procesal y luego jurisprudencia correctiva.",
            "La fuente normativa tiene prioridad argumental sobre cualquier modelo interno.",
        ],
        "acciones_sugeridas": [
            {
                "action": "Reescribir la contestación con respuesta hecho por hecho",
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": "La negativa genérica puede ser considerada insuficiente",
            },
            {
                "action": "Agregar desarrollo defensivo y prueba vinculada a cada hecho controvertido",
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": None,
            },
        ],
        "riesgos_observaciones": [
            "La jurisprudencia local muestra que la negativa genérica debilita la defensa.",
            "No se detectó ofrecimiento probatorio en el fragmento auditado.",
        ],
        "fuentes_respaldo": [
            {
                "document_id": "doc_cpc_jujuy_339",
                "document_title": "CPC Jujuy — Art. 339: Forma de la contestación",
                "source_hierarchy": "normativa",
                "fragment": (
                    "La contestación de la demanda deberá negar o admitir "
                    "categóricamente cada uno de los hechos expuestos."
                ),
                "page_or_section": "Art. 339",
                "relevance_score": 0.96,
            },
            {
                "document_id": "doc_stj_contestacion_2022",
                "document_title": "STJ Jujuy — Sala Civil — 'L., A. c/ M., B.'",
                "source_hierarchy": "jurisprudencia",
                "fragment": (
                    "La negativa genérica, sin referencia concreta a los hechos, "
                    "no satisface la carga procesal de contestación."
                ),
                "page_or_section": "Consid. V",
                "relevance_score": 0.81,
            },
        ],
        "datos_faltantes": [
            {
                "description": "Texto completo de la demanda",
                "impact": "Sin la demanda no se puede verificar si la contestación cubre todos los hechos",
                "required_for": "Auditoría integral",
            }
        ],
        "nivel_confianza": "alto",
        "confianza_score": 0.86,
        "modulo_origen": "auditoria",
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 17: Generación con plantilla y fuentes recuperadas
# POST /api/generation/generate
# ═══════════════════════════════════════════════════════════

EXAMPLE_GENERATION_WITH_RAG = {
    "_label": "Generación asistida por plantilla interna y respaldo normativo",
    "endpoint": "POST /api/generation/generate",
    "input": {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "demanda",
        "variante": "estandar",
        "hechos": (
            "Choque en intersección semaforizada con lesiones leves y daños materiales."
        ),
        "datos": {
            "actor": "María González",
            "demandado": "Juan Pérez",
            "jurisdiccion": "Jujuy",
        },
    },
    "expected_output": {
        "resumen_ejecutivo": (
            "Se genera un borrador base de demanda con estructura de plantilla interna "
            "y apoyo normativo recuperado para daños por accidente de tránsito."
        ),
        "_borrador_fragment": (
            "III. DERECHO\n"
            "La responsabilidad del demandado se sustenta, prima facie, "
            "en el régimen objetivo previsto por el art. 1757 del CCCN, "
            "sin perjuicio de la prueba a producir.\n\n"
            "IV. PETITORIO\n"
            "Se tenga por promovida demanda de daños y perjuicios..."
        ),
        "hechos_relevantes": [
            {
                "content": "Se recuperó una plantilla interna útil para la estructura formal del escrito.",
                "info_type": "extraido",
                "source": {
                    "document_id": "doc_modelo_demanda_danos",
                    "document_title": "Modelo interno — Demanda de daños y perjuicios",
                    "source_hierarchy": "interno",
                    "fragment": "PROMUEVE DEMANDA — DAÑOS Y PERJUICIOS...",
                    "page_or_section": "Encabezado",
                    "relevance_score": 0.67,
                },
            },
            {
                "content": "La base normativa recuperada apunta al régimen de responsabilidad objetiva del CCCN.",
                "info_type": "extraido",
                "source": {
                    "document_id": "doc_cccn_1757",
                    "document_title": "Código Civil y Comercial — Art. 1757",
                    "source_hierarchy": "normativa",
                    "fragment": (
                        "Toda persona responde por el riesgo o vicio de las cosas "
                        "que utiliza o tiene a su cuidado."
                    ),
                    "page_or_section": "Art. 1757",
                    "relevance_score": 0.88,
                },
            },
        ],
        "encuadre_preliminar": [
            "La plantilla interna se usa solo como apoyo de estilo y organización.",
            "El fundamento jurídico debe descansar en normativa y jurisprudencia recuperadas.",
        ],
        "acciones_sugeridas": [
            {
                "action": "Completar los hechos con datos de mecánica del accidente y prueba documental",
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": "Sin hechos concretos y prueba, la demanda queda débil",
            },
            {
                "action": "Verificar si corresponde agregar jurisprudencia local de daños viales",
                "info_type": "sugerencia",
                "priority": "media",
                "risk": None,
            },
        ],
        "riesgos_observaciones": [
            "La plantilla interna no es fuente jurídica autoritativa y no debe citarse como tal.",
            "La narrativa fáctica aún requiere precisión sobre lesiones, gastos y causalidad.",
        ],
        "fuentes_respaldo": [
            {
                "document_id": "doc_cccn_1757",
                "document_title": "Código Civil y Comercial — Art. 1757",
                "source_hierarchy": "normativa",
                "fragment": (
                    "Toda persona responde por el riesgo o vicio de las cosas "
                    "que utiliza o tiene a su cuidado."
                ),
                "page_or_section": "Art. 1757",
                "relevance_score": 0.88,
            },
            {
                "document_id": "doc_modelo_demanda_danos",
                "document_title": "Modelo interno — Demanda de daños y perjuicios",
                "source_hierarchy": "interno",
                "fragment": "PROMUEVE DEMANDA — DAÑOS Y PERJUICIOS...",
                "page_or_section": "Encabezado",
                "relevance_score": 0.67,
            },
        ],
        "datos_faltantes": [
            {
                "description": "Detalle médico y documental del daño",
                "impact": "Sin cuantificación y respaldo probatorio no puede cerrarse la demanda",
                "required_for": "Redacción final del escrito",
            }
        ],
        "nivel_confianza": "medio",
        "confianza_score": 0.61,
        "modulo_origen": "generacion",
    },
}


# ═══════════════════════════════════════════════════════════
# EJEMPLO 18: Recuperación débil y salida prudente
# POST /api/analysis/analyze
# ═══════════════════════════════════════════════════════════

EXAMPLE_WEAK_RETRIEVAL_OUTPUT = {
    "_label": "Análisis con recuperación débil y confianza sin respaldo",
    "endpoint": "POST /api/analysis/analyze",
    "input": {
        "text": (
            "Necesito evaluar un trámite sancionatorio municipal ambiental "
            "con referencia parcial a una ordenanza no identificada."
        ),
    },
    "expected_output": {
        "resumen_ejecutivo": (
            "No se recuperó respaldo documental suficiente para emitir una conclusión jurídica confiable. "
            "La respuesta debe mantenerse prudente y orientada a recolección de información."
        ),
        "hechos_relevantes": [
            {
                "content": "La consulta refiere a un posible procedimiento sancionatorio ambiental municipal.",
                "info_type": "extraido",
                "source": None,
            }
        ],
        "encuadre_preliminar": [
            "La base documental activa no contiene normativa municipal identificable con score suficiente.",
            "No debe inferirse la ordenanza aplicable ni el régimen recursivo sin fuente directa.",
        ],
        "acciones_sugeridas": [
            {
                "action": "Obtener la ordenanza, resolución o acta municipal que originó la consulta",
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": "Sin la norma aplicable no puede definirse defensa ni plazo recursivo",
            },
            {
                "action": "Verificar manualmente competencia, autoridad emisora y estado de vigencia",
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": None,
            },
        ],
        "riesgos_observaciones": [
            "Cualquier respuesta de fondo sin respaldo normativo sería especulativa.",
            "Los resultados recuperados quedaron por debajo del umbral útil y no se citan.",
        ],
        "fuentes_respaldo": [],
        "datos_faltantes": [
            {
                "description": "Número y texto de la ordenanza o resolución aplicable",
                "impact": "Sin la fuente no puede determinarse el régimen sancionatorio",
                "required_for": "Análisis jurídico de fondo",
            },
            {
                "description": "Fecha de notificación del acto administrativo",
                "impact": "Sin ella no puede calcularse plazo de descargo o recurso",
                "required_for": "Defensa administrativa",
            },
        ],
        "nivel_confianza": "sin_respaldo",
        "confianza_score": 0.08,
        "modulo_origen": "analisis",
    },
    "_nota": (
        "Este es el comportamiento esperado cuando la recuperación RAG es débil: "
        "no inventar fuentes, no sobreactuar la confianza y explicitar la incertidumbre."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLOS DE GENERACIÓN FORENSE — nuevo módulo estructurado
# Cubren los 5 escenarios requeridos:
#   A. Demanda con placeholders faltantes (sin datos)
#   B. Contesta traslado con tono estándar
#   C. Pronto despacho con checklist
#   D. Generación con fuentes_respaldo recuperadas
#   E. Generación sin respaldo suficiente
# ═══════════════════════════════════════════════════════════

# ─── A. Demanda con placeholders faltantes ───────────────────────────────────
# Comportamiento esperado: el borrador se genera con todos los {{PLACEHOLDER}}
# visibles. datos_faltantes lista cada uno. No se inventa ningún dato.

EXAMPLE_GEN_A_DEMANDA_PLACEHOLDERS = {
    "_label": "A — Demanda con placeholders faltantes (sin datos)",
    "endpoint": "POST /api/generation/generate",
    "input": {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "demanda",
        "variante": "estandar",
        "hechos": None,
        "datos": None,
    },
    "expected_output": {
        "resumen_ejecutivo": (
            "Borrador generado: Demanda — variante estandar "
            "(fuero civil, materia daños y perjuicios, sin respaldo documental). "
            "16 campo(s) pendientes de completar. "
            "Revisar checklist previo antes de presentar."
        ),
        "borrador_fragment": (
            "PROMUEVE DEMANDA — DAÑOS Y PERJUICIOS\n\n"
            "Señor/a Juez/a:\n\n"
            "{{NOMBRE_ACTOR}}, DNI {{DNI_ACTOR}}, con domicilio real en {{DOMICILIO_REAL_ACTOR}}, "
            "constituyendo domicilio procesal en {{DOMICILIO_PROCESAL}}, "
            "con patrocinio letrado del/la Dr./Dra. {{NOMBRE_ABOGADO}}, "
            "Matrícula T° {{TOMO}} F° {{FOLIO}} del Colegio de Abogados, "
            "ante V.S. me presento y respetuosamente digo:\n\n"
            "I. OBJETO\n"
            "Que vengo a promover demanda por {{OBJETO_DE_LA_DEMANDA}} contra "
            "{{NOMBRE_DEMANDADO}}, DNI/CUIT {{DNI_DEMANDADO}}, ...\n\n"
            "III. DERECHO\n"
            "En virtud de la normativa aplicable,\n"
            "{{FUNDAMENTO_NORMATIVO}}\n"
            "[ADVERTENCIA: verificar artículos y normativa aplicable antes de presentar]"
        ),
        "placeholders_detectados": [
            "NOMBRE_ACTOR", "DNI_ACTOR", "DOMICILIO_REAL_ACTOR",
            "DOMICILIO_PROCESAL", "NOMBRE_ABOGADO", "TOMO", "FOLIO",
            "OBJETO_DE_LA_DEMANDA", "NOMBRE_DEMANDADO", "DNI_DEMANDADO",
            "DOMICILIO_DEMANDADO", "MONTO_RECLAMADO", "FUNDAMENTO_DEL_MONTO",
            "RELATO_DE_HECHOS", "FUNDAMENTO_NORMATIVO", "OFRECIMIENTO_DE_PRUEBA",
        ],
        "checklist_previo": [
            "Verificar personería y acreditación de representación (poderes, estatutos)",
            "Confirmar competencia del juzgado (materia, cuantía, territorio)",
            "Controlar prescripción y caducidad de la acción",
            "Acompañar prueba documental base junto con la demanda",
            "Verificar correcta individualización del demandado (nombre, CUIT/DNI, domicilio)",
        ],
        "riesgos_habituales": [
            "Falta de individualización precisa del demandado puede dificultar la notificación",
            "Petitorio ambiguo o indeterminado puede dar lugar a excepciones de defecto legal",
            "Normativa citada sin verificación puede invalidar el fundamento de derecho",
        ],
        "datos_faltantes": [
            {"description": "Nombre Actor", "impact": "Dato necesario para completar el escrito"},
            {"description": "Dni Actor", "impact": "Dato necesario para completar el escrito"},
            {"description": "Relato De Hechos", "impact": "Dato necesario para completar el escrito"},
            # ... (todos los placeholders pendientes)
        ],
        "nivel_confianza": "sin_respaldo",
        "confianza_score": 0.0,
        "modulo_origen": "generacion",
    },
    "_nota": (
        "AILEX NUNCA rellena placeholders con datos inventados. "
        "Todos los campos desconocidos quedan como {{PLACEHOLDER}} visible. "
        "datos_faltantes los lista individualmente. "
        "El borrador es útil como estructura aunque no tenga datos."
    ),
}


# ─── B. Contesta traslado con tono estándar ──────────────────────────────────
# Algunos datos provistos → los placeholders correspondientes se completan.
# Los restantes quedan visibles. Tono estándar por defecto.

EXAMPLE_GEN_B_CONTESTA_TRASLADO_ESTANDAR = {
    "_label": "B — Contesta traslado con tono estándar, datos parciales",
    "endpoint": "POST /api/generation/generate",
    "input": {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "contesta_traslado",
        "variante": "estandar",
        "datos": {
            "nombre_parte": "Juan Pérez",
            "caratula": "González, María c/ Pérez, Juan s/ Daños",
            "numero_expediente": "12345/2024",
            "nombre_abogado": "Rodríguez, Carlos",
            "tomo": "XV",
            "folio": "234",
            "objeto_del_traslado": "excepción de prescripción opuesta por la actora",
        },
    },
    "expected_output": {
        "borrador_fragment": (
            "CONTESTA TRASLADO — excepción de prescripción opuesta por la actora\n\n"
            "Señor/a Juez/a:\n\n"
            "Juan Pérez, en autos \"González, María c/ Pérez, Juan s/ Daños\" "
            "(Expte. N° 12345/2024), con el patrocinio letrado del/la Dr./Dra. Rodríguez, Carlos, "
            "Matrícula T° XV F° 234, ante V.S. me presento y respetuosamente digo:\n\n"
            "I. OBJETO\n"
            "Que vengo a contestar el traslado conferido en autos respecto de "
            "excepción de prescripción opuesta por la actora ...\n\n"
            "II. CONSIDERACIONES\n"
            "En virtud de la normativa aplicable,\n"
            "{{DESARROLLO_DE_CONSIDERACIONES}}\n\n"
            "III. PETITORIO\n"
            "Por todo lo expuesto, solicito a V.S.:\n"
            "1. Se tenga por contestado el traslado en tiempo y forma;\n"
            "2. {{PETICION_ESPECIFICA}};"
        ),
        "placeholders_detectados": [
            "DESARROLLO_DE_CONSIDERACIONES",
            "PETICION_ESPECIFICA",
        ],
        "variante_aplicada": "estandar",
        "nivel_confianza": "sin_respaldo",
        "modulo_origen": "generacion",
    },
    "_nota": (
        "Los datos provistos se insertan en los placeholders correspondientes. "
        "Solo quedan sin completar DESARROLLO_DE_CONSIDERACIONES y PETICION_ESPECIFICA, "
        "que son el contenido sustancial que debe proveer el abogado."
    ),
}


# ─── C. Pronto despacho con checklist ────────────────────────────────────────
# El endpoint retorna checklist_previo de la plantilla junto con el borrador.

EXAMPLE_GEN_C_PRONTO_DESPACHO_CON_CHECKLIST = {
    "_label": "C — Pronto despacho con checklist previo visible",
    "endpoint": "POST /api/generation/generate",
    "input": {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "pronto_despacho",
        "variante": "firme",
        "datos": {
            "nombre_parte": "María González",
            "caratula": "González, María c/ Pérez, Juan s/ Daños",
            "numero_expediente": "12345/2024",
            "nombre_abogado": "Rodríguez, Carlos",
            "tomo": "XV",
            "folio": "234",
            "fecha_ultima_presentacion": "15/01/2026",
            "descripcion_ultima_actuacion": "se presentó escrito de contestación de prueba",
            "tiempo_transcurrido": "45 días hábiles",
        },
    },
    "expected_output": {
        "checklist_previo": [
            "Verificar que efectivamente existe mora judicial o administrativa",
            "Confirmar que se han cumplido los pasos previos requeridos",
            "Documentar la última actuación y la fecha correspondiente",
            "Verificar si aplica alguna norma específica de pronto despacho (Ley 19.549 si es administrativo)",
            "Controlar firma y copias",
        ],
        "riesgos_habituales": [
            "Presentar pronto despacho sin que haya transcurrido el plazo legal puede ser rechazado",
            "No identificar con precisión la cuestión pendiente hace improcedente la solicitud",
            "En sede administrativa, omitir el encuadre en la norma específica debilita el pedido",
        ],
        "variante_aplicada": "firme",
        "placeholders_detectados": [
            "FUNDAMENTO_URGENCIA",
            "CUESTION_PENDIENTE",
        ],
        "nivel_confianza": "sin_respaldo",
        "modulo_origen": "generacion",
    },
    "_nota": (
        "checklist_previo y riesgos_habituales provienen de la plantilla, "
        "son constantes para este tipo de escrito e independientes del caso. "
        "El abogado debe revisarlos antes de presentar."
    ),
}


# ─── D. Generación con fuentes_respaldo recuperadas ──────────────────────────
# Cuando RAG recupera fuentes, se incluyen en fuentes_respaldo.
# El nivel_confianza sube según calidad de las fuentes.
# Las fuentes NO se inventan: se citan con fragmento textual real.

EXAMPLE_GEN_D_CON_FUENTES_RESPALDO = {
    "_label": "D — Generación con fuentes_respaldo recuperadas por RAG",
    "endpoint": "POST /api/generation/generate",
    "input": {
        "fuero": "civil",
        "materia": "daños y perjuicios",
        "tipo_escrito": "demanda",
        "variante": "estandar",
        "hechos": "Accidente de tránsito con responsabilidad del demandado por conducción negligente.",
        "datos": {
            "nombre_actor": "María González",
            "nombre_demandado": "Juan Pérez",
            "nombre_abogado": "Rodríguez, Carlos",
            "tomo": "XV",
            "folio": "234",
        },
    },
    "expected_output": {
        "resumen_ejecutivo": (
            "Borrador generado: Demanda — variante estandar "
            "(fuero civil, materia daños y perjuicios, 2 fuente(s) de respaldo recuperada(s)). "
            "11 campo(s) pendientes de completar."
        ),
        "fuentes_respaldo": [
            {
                "document_id": "doc_cccn_1757",
                "document_title": "Código Civil y Comercial — Art. 1757",
                "source_hierarchy": "normativa",
                "fragment": (
                    "Toda persona responde por el riesgo o vicio de las cosas "
                    "que utiliza o tiene a su cuidado."
                ),
                "page_or_section": "Art. 1757",
                "relevance_score": 0.88,
            },
        ],
        "nivel_confianza": "medio",
        "confianza_score": 0.61,
        "modulo_origen": "generacion",
    },
    "_nota": (
        "Las fuentes se usan como respaldo — no como citas textuales en el borrador. "
        "El abogado decide qué incorporar al texto final. "
        "AILEX no inventa ni presenta fuentes no recuperadas. "
        "El nivel_confianza sube a 'medio' porque hay al menos una fuente normativa."
    ),
}


# ─── E. Generación sin respaldo suficiente ───────────────────────────────────
# Cuando RAG no recupera fuentes útiles, el borrador se genera igual
# pero nivel_confianza = sin_respaldo y riesgos_observaciones lo advierte.

EXAMPLE_GEN_E_SIN_RESPALDO = {
    "_label": "E — Generación sin respaldo documental suficiente",
    "endpoint": "POST /api/generation/generate",
    "input": {
        "fuero": "laboral",
        "materia": "despido sin causa",
        "tipo_escrito": "solicita_pronto_pago",
        "variante": "conservador",
        "datos": {
            "nombre_trabajador": "Pedro Ramos",
            "dni_trabajador": "28.456.789",
        },
    },
    "expected_output": {
        "resumen_ejecutivo": (
            "Borrador generado: Solicita Pronto Pago Laboral — variante conservador "
            "(fuero laboral, materia despido sin causa, sin respaldo documental). "
            "Revisar checklist previo antes de presentar."
        ),
        "fuentes_respaldo": [],
        "nivel_confianza": "sin_respaldo",
        "confianza_score": 0.0,
        "riesgos_observaciones": [
            "El borrador contiene campo(s) sin completar ({{PLACEHOLDER}}).",
            "No presentar el escrito hasta completar y verificar todos los campos.",
            "Verificar artículos y normativa citados en el fundamento de derecho antes de presentar.",
            "Faltan datos obligatorios: DOMICILIO_TRABAJADOR, DOMICILIO_PROCESAL, NOMBRE_ABOGADO (y más).",
            (
                "Sin respaldo documental recuperado. El borrador se generó como base estructural — "
                "completar con normativa y jurisprudencia verificada."
            ),
        ],
        "acciones_sugeridas": [
            {
                "action": (
                    "Buscar y citar normativa verificada antes de presentar — "
                    "el borrador no tiene respaldo documental"
                ),
                "info_type": "sugerencia",
                "priority": "alta",
                "risk": "Base normativa no verificada",
            },
        ],
        "modulo_origen": "generacion",
    },
    "_nota": (
        "El borrador se genera igual aunque no haya respaldo RAG. "
        "El nivel_confianza queda en sin_respaldo y riesgos_observaciones "
        "advierte explícitamente la falta de sustento documental. "
        "El abogado debe agregar la normativa verificada antes de presentar."
    ),
}


# ═══════════════════════════════════════════════════════════
# EJEMPLOS DE AUDITORÍA DE ESCRITOS — nuevo módulo estructurado
# Cubren los 5 escenarios requeridos:
#   A. Escrito con negativa genérica
#   B. Escrito con petitorio ambiguo
#   C. Escrito con artículo sospechoso
#   D. Escrito con falta de objeto claro
#   E. Versión sugerida con placeholders preservados
# ═══════════════════════════════════════════════════════════

# ─── A. Escrito con negativa genérica ────────────────────────────────────────
# Comportamiento esperado: hallazgo de tipo REDACCION / severidad GRAVE,
# carácter EXTRAIDO, con texto detectado y mejora sugerida.

EXAMPLE_AUDIT_A_NEGATIVA_GENERICA = {
    "_label": "A — Contestación con negativa genérica",
    "endpoint": "POST /api/audit/review",
    "input": {
        "text": (
            "CONTESTA DEMANDA\n\n"
            "Señor/a Juez/a:\n\n"
            "Juan López, DNI 25.678.901, constituyendo domicilio procesal en "
            "Belgrano 456, San Salvador de Jujuy, con patrocinio del Dr. Carlos Ruiz, "
            "T° XII F° 180, en autos \"González c/ López\" (Expte. N° 345/2025), "
            "ante V.S. me presento y digo:\n\n"
            "Niego todos y cada uno de los hechos afirmados en la demanda.\n\n"
            "Solicito se rechace la demanda con costas."
        ),
        "tipo_escrito": "contestacion",
    },
    "expected_output": {
        "diagnostico_general": (
            "Escrito (contestacion) con 1 problema(s) grave(s), sin respaldo documental. "
            "No presentar sin corregir los problemas graves detectados."
        ),
        "severidad_general": "grave",
        "hallazgos": [
            {
                "tipo": "redaccion",
                "severidad": "grave",
                "caracter": "extraido",
                "seccion": "negativa",
                "texto_detectado": "Niego todos y cada uno de los hechos",
                "observacion": (
                    "Negativa genérica detectada. En muchos fueros la negativa general "
                    "sin especificar hecho por hecho no satisface la carga procesal."
                ),
                "mejora_sugerida": (
                    "Reemplazar por negativa específica hecho por hecho: "
                    "'Respecto del hecho [X]: niego / reconozco / desconozco...'"
                ),
            },
            {
                "tipo": "estructura",
                "severidad": "moderada",
                "caracter": "inferido",
                "seccion": "defensa",
                "observacion": (
                    "No se detecta defensa de fondo en la contestación."
                ),
                "mejora_sugerida": (
                    "Agregar defensa de fondo con fundamento normativo verificado."
                ),
            },
        ],
        "fortalezas": [
            "Encabezado formal presente.",
            "Petitorio presente.",
            "Domicilio procesal constituido.",
            "Partes identificadas con DNI/CUIT.",
        ],
        "nivel_confianza": "sin_respaldo",
        "modulo_origen": "auditoria",
    },
    "_nota": (
        "El hallazgo de negativa genérica tiene carácter EXTRAIDO (detectado en el texto). "
        "La ausencia de defensa de fondo tiene carácter INFERIDO "
        "(no hay sección de derecho pero puede estar implícita). "
        "Ambos son flaggeados con sus respectivas severidades."
    ),
}


# ─── B. Escrito con petitorio ambiguo ────────────────────────────────────────

EXAMPLE_AUDIT_B_PETITORIO_AMBIGUO = {
    "_label": "B — Escrito con petitorio ambiguo",
    "endpoint": "POST /api/audit/review",
    "input": {
        "text": (
            "PRONTO DESPACHO\n\n"
            "Señor/a Juez/a:\n\n"
            "María González, en autos \"González c/ López\" (Expte. N° 345/2025), "
            "solicita pronto despacho dado el tiempo transcurrido.\n\n"
            "PETITORIO\n"
            "Solicito a V.S. lo que considere pertinente para agilizar el trámite."
        ),
        "tipo_escrito": "pronto_despacho",
    },
    "expected_output": {
        "severidad_general": "moderada",
        "hallazgos": [
            {
                "tipo": "redaccion",
                "severidad": "moderada",
                "caracter": "extraido",
                "seccion": "petitorio",
                "texto_detectado": "lo que considere pertinente",
                "observacion": (
                    "Petición ambigua detectada. El tribunal no puede conceder "
                    "lo que no se solicita claramente."
                ),
                "mejora_sugerida": (
                    "Precisar el petitorio con verbos concretos: "
                    "'se dicte resolución respecto de [X]', etc."
                ),
            },
        ],
        "modulo_origen": "auditoria",
    },
    "_nota": (
        "El petitorio 'lo que V.S. considere pertinente' es ambiguo: el tribunal "
        "no tiene obligación de inferir qué se quiere. El hallazgo es EXTRAIDO "
        "con severidad MODERADA. La versión sugerida marcará el fragmento "
        "con [REVISAR — PETICIÓN AMBIGUA]."
    ),
}


# ─── C. Escrito con artículo sospechoso ──────────────────────────────────────

EXAMPLE_AUDIT_C_ARTICULO_SOSPECHOSO = {
    "_label": "C — Escrito con artículo de numeración sospechosa (4+ dígitos)",
    "endpoint": "POST /api/audit/review",
    "input": {
        "text": (
            "CONTESTA DEMANDA\n\n"
            "Señor/a Juez/a:\n\n"
            "La parte demandada, con patrocinio del Dr. Pérez T° X F° 120, "
            "constituyendo domicilio procesal en Lavalle 234, contesta la demanda.\n\n"
            "I. NEGATIVA\n"
            "Niega los hechos invocados por el actor en cuanto no sean reconocidos.\n\n"
            "II. DERECHO\n"
            "La demanda es improcedente en virtud del art. 5847 del Código Civil y Comercial "
            "que establece la exoneración de responsabilidad en estos supuestos.\n\n"
            "PETITORIO\nSolicito se rechace la demanda con costas."
        ),
        "tipo_escrito": "contestacion",
    },
    "expected_output": {
        "severidad_general": "grave",
        "hallazgos": [
            {
                "tipo": "argumental",
                "severidad": "grave",
                "caracter": "extraido",
                "texto_detectado": "Art. 5847",
                "observacion": (
                    "El artículo 5847 tiene numeración inusual (4+ dígitos). "
                    "En el derecho argentino los artículos rara vez superan los 3 dígitos. "
                    "Puede tratarse de un error de cita o de un artículo inexistente."
                ),
                "mejora_sugerida": (
                    "Verificar que el artículo 5847 existe en el CCCN. "
                    "Si no existe, eliminar la cita o reemplazar por el artículo correcto."
                ),
            },
        ],
        "modulo_origen": "auditoria",
    },
    "_nota": (
        "El art. 5847 no existe en el CCCN (que tiene ~2671 artículos). "
        "El hallazgo es EXTRAIDO / GRAVE. "
        "AILEX NO sugiere el artículo correcto — no inventa normativa. "
        "Solo advierte el problema y pide verificación."
    ),
}


# ─── D. Escrito con falta de objeto claro ────────────────────────────────────

EXAMPLE_AUDIT_D_FALTA_OBJETO = {
    "_label": "D — Escrito sin objeto ni secciones estructurales",
    "endpoint": "POST /api/audit/review",
    "input": {
        "text": (
            "Que las partes han acordado dar por terminado el litigio. "
            "Se adjuntan los documentos del caso. "
            "Solicito pronto despacho."
        ),
        "tipo_escrito": None,
    },
    "expected_output": {
        "severidad_general": "grave",
        "hallazgos": [
            {
                "tipo": "estructura",
                "severidad": "grave",
                "caracter": "extraido",
                "seccion": "encabezado",
                "observacion": "No se detecta encabezado ('Señor/a Juez/a').",
            },
            {
                "tipo": "estructura",
                "severidad": "grave",
                "caracter": "inferido",
                "seccion": "objeto",
                "observacion": "No se detecta sección de objeto o propósito del escrito.",
            },
            {
                "tipo": "estructura",
                "severidad": "moderada",
                "caracter": "inferido",
                "seccion": "domicilio",
                "observacion": "No se detecta constitución de domicilio procesal o electrónico.",
            },
            {
                "tipo": "estructura",
                "severidad": "moderada",
                "caracter": "inferido",
                "seccion": "partes",
                "observacion": "No se detecta identificación de partes con DNI/CUIT.",
            },
        ],
        "fortalezas": ["Petitorio presente."],
        "modulo_origen": "auditoria",
    },
    "_nota": (
        "El escrito carece de las secciones básicas. "
        "Los hallazgos de encabezado son EXTRAIDOS (ausencia verificable). "
        "Los de partes y objeto son INFERIDOS (podrían estar implícitos). "
        "La versión sugerida agrega encabezado, objeto y domicilio con {{PLACEHOLDER}}."
    ),
}


# ─── E. Versión sugerida con placeholders preservados ────────────────────────

EXAMPLE_AUDIT_E_VERSION_SUGERIDA = {
    "_label": "E — Versión sugerida de contestación con negativa genérica",
    "endpoint": "POST /api/audit/review/version-sugerida",
    "input": {
        "text": (
            "CONTESTA DEMANDA\n\n"
            "Señor/a Juez/a:\n\n"
            "{{NOMBRE_DEMANDADO}}, DNI {{DNI_DEMANDADO}}, "
            "constituyendo domicilio procesal en {{DOMICILIO_PROCESAL}}, "
            "con patrocinio del Dr. {{NOMBRE_ABOGADO}}, T° {{TOMO}} F° {{FOLIO}}, "
            "en autos \"{{CARATULA}}\" (Expte. N° {{NUMERO_EXPEDIENTE}}), "
            "ante V.S. me presento y digo:\n\n"
            "Niego todos y cada uno de los hechos afirmados en la demanda.\n\n"
            "{{FUNDAMENTO_DEFENSA}}\n\n"
            "Ofrezco prueba: {{OFRECIMIENTO_DE_PRUEBA}}\n\n"
            "PETITORIO\nSolicito se rechace la demanda con costas."
        ),
        "tipo_escrito": "contestacion",
    },
    "expected_output": {
        "version_sugerida": (
            "[VERSIÓN SUGERIDA — AILEX]\n"
            "[ADVERTENCIA: borrador mejorado con correcciones estructurales y de redacción.]\n"
            "[Revisar todos los cambios antes de presentar. No reemplaza criterio del abogado.]\n\n"
            "CONTESTA DEMANDA\n\n"
            "Señor/a Juez/a:\n\n"
            "{{NOMBRE_DEMANDADO}}, DNI {{DNI_DEMANDADO}}, ...\n\n"
            "En relación con los hechos invocados en la demanda, formulo negativa "
            "específica en los siguientes términos:\n"
            "a) {{HECHO_1_IDENTIFICAR}}: [niego / reconozco / desconozco]\n"
            "b) {{HECHO_2_IDENTIFICAR}}: [niego / reconozco / desconozco]\n"
            "[Continuar con negativa específica por cada hecho de la demanda]\n"
            "[ADVERTENCIA: eliminar ítems genéricos y completar hecho por hecho]\n\n"
            "{{FUNDAMENTO_DEFENSA}}\n\n"
            "Ofrezco prueba: {{OFRECIMIENTO_DE_PRUEBA}}\n\n"
            "PETITORIO\nSolicito se rechace la demanda con costas."
        ),
        "cambios_aplicados": [
            "Negativa genérica reemplazada por estructura de negativa específica "
            "con {{PLACEHOLDER}} para completar hecho por hecho."
        ],
        "advertencia": (
            "La versión sugerida es un borrador con correcciones estructurales. "
            "Revisar todos los cambios antes de presentar."
        ),
    },
    "_nota": (
        "La versión sugerida preserva todos los {{PLACEHOLDER}} originales: "
        "NOMBRE_DEMANDADO, DNI_DEMANDADO, FUNDAMENTO_DEFENSA, etc. "
        "Solo reemplaza la negativa genérica. "
        "No inventa hechos, no inventa normativa, no cierra los placeholders."
    ),
}
