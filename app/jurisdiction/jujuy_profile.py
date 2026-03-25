"""
AILEX — Perfil Jurisdiccional de Jujuy.

Datos de referencia de la jurisdicción de Jujuy, Argentina.
Usados para:
- Contextualizar análisis (verificar normativa local)
- Sugerir terminología procesal correcta
- Identificar tribunales y cámaras
- Detectar estructuras de carátula típicas

IMPORTANTE: Los plazos y datos son ORIENTATIVOS.
Verificar siempre con la normativa y acordadas vigentes.
"""

import re


# ═══════════════════════════════════════════════════════════
# PERFIL PRINCIPAL
# ═══════════════════════════════════════════════════════════

JUJUY_PROFILE = {
    "jurisdiction": "Jujuy",
    "province": "Jujuy",
    "country": "Argentina",
    "capital": "San Salvador de Jujuy",

    # ─── Fueros disponibles ──────────────────────────────
    "fueros": [
        "Civil y Comercial",
        "Penal",
        "Laboral y de la Seguridad Social",
        "Contencioso Administrativo",
        "Familia y Menores",
        "Minería",
        "Violencia Familiar",
        "Justicia de Paz",
    ],

    # ─── Normativa procesal base ─────────────────────────
    "normativa_base": {
        "procesal_civil": "Código Procesal Civil y Comercial de Jujuy (Ley 5305)",
        "procesal_penal": "Código Procesal Penal de Jujuy (Ley 5623 y modif.)",
        "procesal_laboral": "Código Procesal del Trabajo de Jujuy",
        "contencioso": "Código Contencioso Administrativo de Jujuy",
        "nota": "Verificar versión y modificaciones vigentes antes de citar.",
    },

    # ─── Plazos procesales comunes (días hábiles) ────────
    # ORIENTATIVOS — verificar con normativa vigente
    "plazos_comunes": {
        "contestacion_demanda": {
            "civil": 15,
            "laboral": 10,
            "contencioso": 20,
            "familia": 15,
            "nota": "Verificar CPC Jujuy vigente. Pueden variar por tipo de proceso.",
        },
        "apelacion": {
            "civil": 5,
            "penal": 3,
            "laboral": 3,
            "contencioso": 5,
            "nota": "Plazos perentorios. Verificar acordadas STJ.",
        },
        "revocatoria": {
            "civil": 3,
            "penal": 3,
        },
        "expresion_agravios": {
            "civil": 10,
            "laboral": 5,
        },
        "aclaracion": {
            "civil": 3,
        },
        "nota_general": (
            "Los plazos son indicativos y deben verificarse con la normativa vigente. "
            "Consultar acordadas del STJ de Jujuy para suspensiones y feriados."
        ),
    },

    # ─── Estructura judicial ─────────────────────────────
    "estructura_judicial": {
        "primera_instancia": "Juzgados de Primera Instancia (numerados por fuero)",
        "segunda_instancia": "Cámaras de Apelaciones",
        "maximo_tribunal": "Superior Tribunal de Justicia de Jujuy (STJ)",
        "nota": "La STJ actúa como última instancia provincial.",
    },

    # ─── Tribunales comunes ──────────────────────────────
    "tribunales": {
        "civil": [
            "Juzgado Civil y Comercial N° 1 — San Salvador de Jujuy",
            "Juzgado Civil y Comercial N° 2 — San Salvador de Jujuy",
            "Juzgado Civil y Comercial N° 3 — San Salvador de Jujuy",
            "Juzgado Civil y Comercial N° 4 — San Salvador de Jujuy",
            "Juzgado Civil y Comercial N° 5 — San Salvador de Jujuy",
            "Juzgado Civil y Comercial — San Pedro de Jujuy",
            "Juzgado Civil y Comercial — Libertador General San Martín",
        ],
        "penal": [
            "Juzgado de Instrucción Penal — San Salvador de Jujuy",
            "Tribunal de Juicio Oral — San Salvador de Jujuy",
            "Juzgado Correccional — San Salvador de Jujuy",
        ],
        "laboral": [
            "Juzgado del Trabajo N° 1 — San Salvador de Jujuy",
            "Juzgado del Trabajo N° 2 — San Salvador de Jujuy",
            "Juzgado del Trabajo — San Pedro de Jujuy",
        ],
        "camaras": [
            "Cámara Civil y Comercial — Sala I",
            "Cámara Civil y Comercial — Sala II",
            "Cámara Penal — San Salvador de Jujuy",
            "Cámara del Trabajo — San Salvador de Jujuy",
        ],
        "stj": "Superior Tribunal de Justicia de Jujuy",
        "nota": (
            "Denominaciones orientativas. Verificar numeración y competencia "
            "territorial actual en el STJ de Jujuy."
        ),
    },

    # ─── Terminología procesal típica ────────────────────
    "terminologia_procesal": {
        "traslado": "Córrase traslado a la parte contraria por N días",
        "notificacion": (
            "Notifíquese por cédula / electrónicamente (verificar sistema vigente)"
        ),
        "providencia": "Resolución de mero trámite (art. XX CPC Jujuy)",
        "auto": "Resolución interlocutoria con sustancia jurídica",
        "sentencia": "Resolución definitiva sobre el objeto del proceso",
        "caratula": "Formato: 'APELLIDO, Nombre c/ APELLIDO, Nombre s/ Materia'",
        "domicilio_procesal": (
            "Constituir en la ciudad sede del tribunal, "
            "incluir domicilio electrónico (verificar reglamento)"
        ),
        "patrocinio": (
            "Dr./Dra. NOMBRE APELLIDO, Tomo N°, Folio N°, "
            "Colegio de Abogados de Jujuy"
        ),
        "rebeldía": (
            "Declarada cuando el demandado no contesta en plazo. "
            "Verificar efectos en CPC Jujuy."
        ),
        "preclusión": "Pérdida de la facultad procesal por vencimiento de plazo",
        "acumulación": "Acumulación de procesos o pretensiones (verificar requisitos)",
        "excepción_previa": "Oponer antes o con la contestación de demanda",
        "prueba_confesional": "Absolución de posiciones (verificar modalidad vigente)",
    },

    # ─── Estructuras de carátula frecuentes ─────────────
    "estructuras_caratula": {
        "formato_base": "{ACTOR} c/ {DEMANDADO} s/ {MATERIA}",
        "ejemplos": [
            "GARCÍA, Juan c/ RODRÍGUEZ, María s/ Daños y Perjuicios",
            "EMPRESA SRL c/ MINISTERIO DE SALUD DE JUJUY s/ Contencioso Administrativo",
            "SINDICATO XX c/ EMPRESA YY s/ Cobro de Pesos (Laboral)",
            "HERRERA, Carlos s/ Sucesión Ab-Intestato",
            "F.S.J. c/ A.P.A. s/ Régimen de Comunicación",
        ],
        "materias_frecuentes": [
            "Daños y Perjuicios",
            "Cobro de Pesos",
            "Desalojo",
            "División de Condominio",
            "Sucesión Testamentaria",
            "Sucesión Ab-Intestato",
            "Alimentos",
            "Filiación",
            "Régimen de Comunicación",
            "Violencia Familiar",
            "Despido Injustificado",
            "Accidente de Trabajo",
            "Amparo",
            "Habeas Corpus",
            "Contencioso Administrativo",
        ],
    },

    # ─── Particularidades locales ────────────────────────
    "particularidades": [
        "Verificar feriados y asuetos provinciales: impactan el cómputo de plazos",
        "Consultar acordadas del STJ de Jujuy para días inhábiles del año en curso",
        "Sistema de notificación electrónica: verificar reglamento vigente (puede cambiar)",
        "Excepción de falta de legitimación activa/pasiva: frecuente en fuero civil",
        "Verificar si el tribunal tiene sistema de gestión electrónica de expedientes",
        "Algunas circunscripciones tienen fuero múltiple (San Pedro, Libertador)",
    ],

    # ─── Colegio de Abogados ─────────────────────────────
    "colegio_abogados": {
        "nombre": "Colegio de Abogados de Jujuy",
        "sede": "San Salvador de Jujuy",
        "nota": "Verificar tomo y folio del profesional antes de suscribir escritos",
    },
}


# ═══════════════════════════════════════════════════════════
# HELPERS DE CONSULTA
# ═══════════════════════════════════════════════════════════

def get_fueros() -> list[str]:
    """Listar fueros disponibles en Jujuy."""
    return JUJUY_PROFILE["fueros"]


def get_plazo(tipo_acto: str, fuero: str = "civil") -> dict:
    """
    Obtener plazo orientativo para un acto procesal.
    Siempre retorna con advertencia de verificación.
    """
    plazos = JUJUY_PROFILE["plazos_comunes"]
    grupo = plazos.get(tipo_acto)

    if not grupo:
        return {
            "dias": None,
            "fuero": fuero,
            "tipo_acto": tipo_acto,
            "advertencia": "Plazo no registrado. Verificar CPC Jujuy vigente.",
        }

    dias = grupo.get(fuero) if isinstance(grupo, dict) else None
    return {
        "dias": dias,
        "fuero": fuero,
        "tipo_acto": tipo_acto,
        "nota": grupo.get("nota", "") if isinstance(grupo, dict) else "",
        "advertencia": "ORIENTATIVO. Verificar con normativa y acordadas STJ vigentes.",
    }


def get_tribunales(fuero: str = None) -> list[str]:
    """
    Obtener lista de tribunales.
    Si se especifica fuero, filtrar por él.
    """
    tribunales = JUJUY_PROFILE["tribunales"]
    if fuero:
        fuero_key = fuero.lower().split(" ")[0]  # "civil" de "Civil y Comercial"
        return tribunales.get(fuero_key, [])
    result = []
    for key, val in tribunales.items():
        if key == "nota":
            continue
        if isinstance(val, list):
            result.extend(val)
        elif isinstance(val, str) and key == "stj":
            result.append(val)
    return result


def detect_caratula(text: str) -> dict:
    """
    Detectar si un texto contiene una carátula judicial.
    Retorna las partes si las encuentra.
    """
    pattern = re.compile(
        r'"([^"]+)\s+[cC]/\s+([^"]+)\s+[sS]/\s+([^"]+)"',
        re.UNICODE,
    )
    match = pattern.search(text)
    if match:
        return {
            "actor": match.group(1).strip(),
            "demandado": match.group(2).strip(),
            "materia": match.group(3).strip(),
            "caratula_completa": match.group(0).strip('"'),
        }
    return {}


def get_terminologia(termino: str) -> str:
    """Obtener definición de terminología procesal local."""
    return JUJUY_PROFILE["terminologia_procesal"].get(
        termino.lower(),
        "Término no registrado en el perfil de Jujuy.",
    )
