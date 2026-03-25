"""
AILEX — Tabla local y controlada de referencias normativas procesales (V1).

PRINCIPIO RECTOR
----------------
Las referencias aquí cargadas son el ÚNICO origen permitido de citas normativas
automáticas en el sistema.  El resolver nunca inventa artículos: si no hay
entrada para un acto/jurisdicción/fuero, devuelve vacío + advertencia.

ESTRUCTURA
----------
NORMATIVE_RULES[jurisdiccion][fuero][action_slug] = [lista de referencias]

Jurisdicciones disponibles:
  "nacional"   — Código Procesal Civil y Comercial de la Nación (Ley 17.454)
                 Se usa como referencia de base cuando no existe entrada
                 jurisdicción-específica.  Siempre se advierte que la norma
                 local puede diferir.
  "jujuy"      — Código Procesal Civil y Comercial de Jujuy.
                 Entradas verificadas pendientes de carga; estructura preparada.

Campos de cada referencia:
  source       — Nombre completo del cuerpo normativo.
  article      — Artículo / inciso de forma abreviada (ej. "art. 338").
  label        — Denominación procesal del acto.
  purpose      — Qué regula ese artículo (una línea, sin inventar).
  confidence   — "high" | "medium" | "low"
                 "high"   → artículo directamente aplicable y unívoco.
                 "medium" → artículo relacionado; puede haber variantes locales.
                 "low"    → referencia orientativa; verificar antes de citar.

ACTUALIZACIÓN
-------------
Agregar entradas en los bloques correspondientes a medida que se validen
referencias específicas de cada jurisdicción.  No cargar referencias sin
verificación previa.
"""

_CPCCN = "Código Procesal Civil y Comercial de la Nación (Ley 17.454)"
_CPCC_JUJ = "Código Procesal Civil y Comercial de Jujuy"

NORMATIVE_RULES: dict[str, dict[str, dict[str, list[dict]]]] = {

    # ------------------------------------------------------------------
    # NACIONAL — referencias base ampliamente establecidas
    # Se aplican cuando no hay entrada jurisdicción-específica.
    # ------------------------------------------------------------------
    "nacional": {
        "civil": {

            # Traslado de demanda / contestación de demanda
            # Arts. 338-339 CPCCN: citación y plazo para contestar la demanda
            "traslado_demanda": [
                {
                    "source": _CPCCN,
                    "article": "art. 338",
                    "label": "Citación del demandado",
                    "purpose": (
                        "Regula la forma y plazo de citación al demandado "
                        "para que comparezca y conteste la demanda."
                    ),
                    "confidence": "medium",
                },
                {
                    "source": _CPCCN,
                    "article": "art. 339",
                    "label": "Plazo para contestar la demanda",
                    "purpose": (
                        "Fija el término procesal para contestar la demanda "
                        "ordinaria según domicilio del demandado."
                    ),
                    "confidence": "medium",
                },
            ],

            # Contestación de demanda — mismo sustento normativo
            "contestacion_demanda": [
                {
                    "source": _CPCCN,
                    "article": "art. 354",
                    "label": "Contestación de demanda",
                    "purpose": (
                        "Establece el contenido y forma del escrito de "
                        "contestación de demanda."
                    ),
                    "confidence": "medium",
                },
            ],

            # Traslado general (no específico de demanda)
            # Art. 150 CPCCN: traslados y vistas en general
            "traslado": [
                {
                    "source": _CPCCN,
                    "article": "art. 150",
                    "label": "Traslados y vistas en general",
                    "purpose": (
                        "Regula el procedimiento general para correr traslados "
                        "y vistas dentro del proceso."
                    ),
                    "confidence": "medium",
                },
            ],

            # Intimación procesal
            # Art. 37 inc. 2° CPCCN: facultades ordenatorias del juez
            "intimacion": [
                {
                    "source": _CPCCN,
                    "article": "art. 37, inc. 2°",
                    "label": "Facultad de intimar — deberes ordenatorios del juez",
                    "purpose": (
                        "Habilita al juez a intimar a las partes al "
                        "cumplimiento de cargas procesales bajo apercibimiento."
                    ),
                    "confidence": "medium",
                },
            ],

            # Vista judicial
            # Art. 120 CPCCN: vistas en general
            "vista": [
                {
                    "source": _CPCCN,
                    "article": "art. 120",
                    "label": "Vistas",
                    "purpose": (
                        "Regula el plazo y forma de las vistas corridas a las "
                        "partes dentro del proceso."
                    ),
                    "confidence": "medium",
                },
            ],

            # Recurso de apelación
            # Art. 244 CPCCN: plazo y forma para apelar
            "apelacion": [
                {
                    "source": _CPCCN,
                    "article": "art. 244",
                    "label": "Recurso de apelación — plazo y forma",
                    "purpose": (
                        "Establece el plazo (cinco días hábiles) y la forma "
                        "de interposición del recurso de apelación."
                    ),
                    "confidence": "medium",
                },
            ],

            # Expresión de agravios
            # Art. 259 CPCCN
            "expresion_agravios": [
                {
                    "source": _CPCCN,
                    "article": "art. 259",
                    "label": "Expresión de agravios",
                    "purpose": (
                        "Fija el plazo (diez días hábiles) para presentar "
                        "el memorial de agravios ante la alzada."
                    ),
                    "confidence": "medium",
                },
            ],

            # Contestación de agravios
            # Art. 260 CPCCN
            "contestacion_agravios": [
                {
                    "source": _CPCCN,
                    "article": "art. 260",
                    "label": "Contestación de agravios",
                    "purpose": (
                        "Regula el plazo (diez días hábiles) para contestar "
                        "el memorial de agravios de la parte apelante."
                    ),
                    "confidence": "medium",
                },
            ],

            # Subsanación / corrección de presentaciones
            # Art. 34 inc. 5°b CPCCN
            "subsanacion": [
                {
                    "source": _CPCCN,
                    "article": "art. 34, inc. 5°b",
                    "label": "Corrección / subsanación de escritos",
                    "purpose": (
                        "Faculta al juez a mandar subsanar defectos formales "
                        "en presentaciones de las partes."
                    ),
                    "confidence": "low",
                },
            ],

            # Audiencia — referencia general; el artículo exacto depende
            # del tipo de proceso y etapa, por lo que la confianza es baja
            "audiencia": [
                {
                    "source": _CPCCN,
                    "article": "art. 360",
                    "label": "Audiencia preliminar (proceso ordinario)",
                    "purpose": (
                        "Regula la audiencia preliminar en el proceso ordinario "
                        "civil; puede no ser aplicable a otros tipos de proceso."
                    ),
                    "confidence": "low",
                },
            ],

            # Comparecencia — se equipara funcionalmente a audiencia
            "comparecencia": [
                {
                    "source": _CPCCN,
                    "article": "art. 360",
                    "label": "Comparecencia a audiencia (proceso ordinario)",
                    "purpose": (
                        "Contempla la obligación de comparecer a la audiencia "
                        "fijada por el tribunal bajo apercibimiento de ley."
                    ),
                    "confidence": "low",
                },
            ],

            # Integración de tribunal — específico del fuero de apelaciones;
            # no existe un artículo único en CPCCN: dejamos preparado sin carga
            "integracion_tribunal": [],

            # Providencia / resolución — demasiado genéricos para citar norma única
            "providencia": [],
            "resolucion": [],
        },
    },

    # ------------------------------------------------------------------
    # JUJUY — entradas específicas del CPCC de Jujuy
    # Estructura preparada; referencias verificadas pendientes de carga.
    # Completar a medida que se valide cada artículo contra el texto oficial.
    # ------------------------------------------------------------------
    "jujuy": {
        "civil": {
            # Reservado para referencias verificadas del CPCC de Jujuy.
            # Por ahora vacío: el resolver caerá en el fallback nacional
            # con advertencia de que la norma local puede diferir.
        },
    },
}
