"""
AILEX — Heurísticas de revisión de escritos forenses.

Contiene únicamente patrones (regex) y listas de frases problemáticas.
No contiene lógica de negocio — esa va en checks.py.

Cada patrón está documentado con:
- qué detecta
- por qué es problemático
- nivel de certeza (si hay falsos positivos conocidos)
"""

import re

# ─── ESTRUCTURA ──────────────────────────────────────────────────────────────
# Detectan presencia o ausencia de secciones estructurales canónicas

# Encabezado ("Señor/a Juez/a", "Sr. Juez", variantes)
RE_ENCABEZADO = re.compile(
    r"[Ss]e[ñn](?:or|or/a|or\/a|ores?)\s*[Jj]uez",
    re.IGNORECASE,
)

# Sección de objeto ("I. OBJETO", "OBJETO:", "vengo a promover/solicitar/presentar")
RE_OBJETO = re.compile(
    r"\bOBJETO\b|vengo\s+a\s+(?:promover|solicitar|presentar|interponer|iniciar)",
    re.IGNORECASE,
)

# Sección de hechos ("II. HECHOS", "HECHOS:", "RELATO DE HECHOS")
RE_HECHOS = re.compile(
    r"\bHECHOS?\b|\bRELATO\b.*?\bHECHOS?\b",
    re.IGNORECASE,
)

# Sección de derecho ("III. DERECHO", "DERECHO APLICABLE", "FUNDAMENTO NORMATIVO")
RE_DERECHO = re.compile(
    r"\bDERECHO\b|\bFUNDAMENTO\s+NORM",
    re.IGNORECASE,
)

# Sección de prueba ("IV. PRUEBA", "OFRECIMIENTO DE PRUEBA", "ofrezco ... prueba")
RE_PRUEBA_SECCION = re.compile(
    r"\bPRUEBA\b|\bOFRECIMIENTO\b.*?\bPRUEBA\b",
    re.IGNORECASE,
)

# Ofrecimiento de prueba concreto
RE_PRUEBA_OFERTA = re.compile(
    r"(?:ofrezco|ofrece|ofrecemos|ofrecen)\s+(?:como\s+)?(?:prueba|probanza)",
    re.IGNORECASE,
)

# Petitorio ("PETITORIO", "solicito", "pido", "se tenga por")
RE_PETITORIO = re.compile(
    r"\bPETITORIO\b|\bSolicito\b|\bPido\b|\bse\s+tenga\s+por\b",
    re.IGNORECASE,
)

# Identificación de partes: DNI, CUIT, matrícula, nombre + calidad
RE_DNI = re.compile(r"\bDNI\b|\bC\.?U\.?I\.?T\.?\b", re.IGNORECASE)
RE_DOMICILIO = re.compile(r"domicilio\s+(?:procesal|electrónico|real)", re.IGNORECASE)
RE_MATRICULA = re.compile(r"[Tt]omo\s+\w+.*?[Ff]olio\s+\w+|[Mm]atrícula\b", re.IGNORECASE)


# ─── REDACCIÓN PROBLEMÁTICA ──────────────────────────────────────────────────

# Negativa genérica — patrón clásico procesalmente riesgoso
RE_NEGATIVA_GENERICA = re.compile(
    r"niego?\s+todos?\s+y\s+cada\s+uno\s+de\s+los\s+hechos?",
    re.IGNORECASE,
)

# Negativa semigenérica — también problemática pero menos severa
RE_NEGATIVA_SEMIGENERICA = re.compile(
    r"niego?\s+(?:la\s+totalidad\s+de\s+los\s+hechos?|todos?\s+los\s+hechos?)",
    re.IGNORECASE,
)

# Petición ambigua — el tribunal no puede saber qué se pide
RE_PETICION_AMBIGUA = re.compile(
    r"lo\s+que\s+[VvSs]\.?[Ss]\.?\s+(?:considere|disponga|estime|resuelva\s+pertinente)"
    r"|solicito\s+lo\s+que\s+corresponda"
    r"|en\s+lo\s+que\s+haga\s+lugar"
    r"|lo\s+que\s+por\s+derecho\s+corresponda\b",
    re.IGNORECASE,
)

# Vaguedad excesiva — "etc.", "entre otras", "y demás"
RE_VAGUEDAD = re.compile(
    r"\betc\.?\b|entre\s+otras\s+(?:cosas?|razones?|causas?)\b|y\s+dem[aá]s\b",
    re.IGNORECASE,
)

# Certeza artificial en un escrito (puede reflejarse en el texto del abogado)
RE_CERTEZA_ARTIFICIAL = re.compile(
    r"indubitablemente\b|sin\s+lugar\s+a\s+dudas?\b"
    r"|es\s+evidente\s+que\b|indiscutiblemente\b"
    r"|es\s+indiscutible\b|no\s+cabe\s+duda\b"
    r"|categóricamente\s+cierto\b",
    re.IGNORECASE,
)

# Lenguaje excesivamente agresivo / temerario
RE_TEMERARIO = re.compile(
    r"maliciosamente\b|de\s+mala\s+fe\b(?!\s+procesal)"
    r"|es\s+una\s+canallada\b|inexcusablemente\b",
    re.IGNORECASE,
)


# ─── ARGUMENTAL ──────────────────────────────────────────────────────────────

# Artículo con número de 4+ dígitos (altamente sospechoso en derecho argentino)
RE_ARTICULO_SOSPECHOSO = re.compile(
    r"[Aa]rt(?:ículo)?\.?\s*(\d{4,})",
    re.UNICODE,
)

# Invocación normativa vaga — cita "la ley" sin especificar cuál
RE_NORMA_VAGA = re.compile(
    r"(?:según|conforme\s+a?|de\s+acuerdo\s+(?:con|a))\s+"
    r"(?:el\s+derecho|la\s+ley|la\s+norma\s+aplicable|lo\s+que\s+corresponda)"
    r"(?!\s*\d)(?!\s*N°)(?!\s*del\s+(?:Código|C\.))",
    re.IGNORECASE,
)

# Mención de prueba sin desarrollar ("según la prueba", "conforme la prueba")
RE_PRUEBA_SIN_DETALLAR = re.compile(
    r"(?:según|conforme)\s+(?:la|las|los|el)\s+prueba\b"
    r"|la\s+prueba\s+que\s+se\s+producir[aá]\b"
    r"|las?\s+pruebas?\s+oportunamente\b",
    re.IGNORECASE,
)

# Hecho sin conexión con pretensión
RE_CONECTOR_LOGICO = re.compile(
    r"(?:por\s+lo\s+tanto|en\s+consecuencia|de\s+ello\s+se\s+sigue"
    r"|razón\s+por\s+la\s+cual|lo\s+que\s+permite\s+concluir"
    r"|ello\s+determina\s+que|por\s+ende\b)",
    re.IGNORECASE,
)


# ─── RIESGO PROCESAL ─────────────────────────────────────────────────────────

# Menciona acompañar documentos sin listarlos
RE_ACOMPANA_SIN_LISTA = re.compile(
    r"acompa[ñn]o\b(?:.*?(?:los\s+siguientes|a\s+saber|:))?",
    re.IGNORECASE,
)

RE_LISTADO_DOCUMENTAL = re.compile(
    r"(?:los\s+siguientes|a\s+saber)\s*:|(?:1\.|a\))\s*\w+",
    re.IGNORECASE,
)

# Plazo mencionado sin dato específico
RE_PLAZO_VAGO = re.compile(
    r"en\s+el\s+plazo\s+(?:de\s+ley|legal|correspondiente)\b(?!\s+de\s+\d)",
    re.IGNORECASE,
)

# Petitorio con ítem único (puede ser insuficiente)
RE_PETITORIO_UNICO = re.compile(
    r"Solicito:\s*\n\s*[a-z1]\)", re.IGNORECASE
)


# ─── FORTALEZAS (detección positiva) ─────────────────────────────────────────

# Negativa específica bien formulada
RE_NEGATIVA_ESPECIFICA = re.compile(
    r"(?:en\s+cuanto\s+al\s+hecho|respecto\s+del\s+hecho|el\s+hecho\s+\w+)"
    r"|(?:niego\s+que|niega\s+que)\s+(?:el\s+actor|la\s+actora|la\s+parte)",
    re.IGNORECASE,
)

# Cita articular concreta y razonable (1-4 dígitos)
RE_ARTICULO_CONCRETO = re.compile(
    r"[Aa]rt(?:ículo)?\.?\s*(\d{1,3})\b",
    re.UNICODE,
)

# Ley citada con número
RE_LEY_CITADA = re.compile(
    r"[Ll]ey\s+(?:N°\s*)?(\d{4,6})",
    re.UNICODE,
)

# Jurisprudencia mencionada (inferencia — puede ser fabricada, usar con cuidado)
RE_JURISPRUDENCIA = re.compile(
    r"(?:fallo|sentencia|resolución|c\.\s*/\s*[A-Z])",
    re.IGNORECASE,
)


# ─── TIPOS DE ESCRITO — secciones requeridas ─────────────────────────────────
# Por cada tipo de escrito, qué secciones son obligatorias.

SECCIONES_REQUERIDAS: dict[str, list[str]] = {
    "demanda": ["encabezado", "objeto", "hechos", "derecho", "prueba", "petitorio"],
    "contestacion": ["encabezado", "negativa", "defensa", "prueba", "petitorio"],
    "contesta_traslado": ["encabezado", "objeto", "petitorio"],
    "pronto_despacho": ["encabezado", "objeto", "petitorio"],
    "solicita_pronto_pago": ["encabezado", "objeto", "creditos", "petitorio"],
    "acompana_documentacion": ["encabezado", "objeto", "documentacion", "petitorio"],
    "recurso": ["encabezado", "agravios", "petitorio"],
    "medida_cautelar": ["encabezado", "verosimilitud", "peligro_demora", "petitorio"],
    "general": ["encabezado", "petitorio"],
}

# Patrones para detectar cada sección canónica
PATRON_SECCION: dict[str, re.Pattern] = {
    "encabezado": RE_ENCABEZADO,
    "objeto": RE_OBJETO,
    "hechos": RE_HECHOS,
    "derecho": RE_DERECHO,
    "prueba": RE_PRUEBA_SECCION,
    "petitorio": RE_PETITORIO,
    "domicilio": RE_DOMICILIO,
    "negativa": re.compile(r"nieg[oa]|NEGAT", re.IGNORECASE),
    "defensa": re.compile(r"DEFENSA\b|FUND(?:AMENTO)?\s+DE\s+FONDO", re.IGNORECASE),
    "agravios": re.compile(r"AGRAVIOS?\b", re.IGNORECASE),
    "verosimilitud": re.compile(r"VEROSIMILITUD\b", re.IGNORECASE),
    "peligro_demora": re.compile(r"PELIGRO\b.*\bDEMORA\b|PELIGRO\s+EN\s+LA\s+DEMORA", re.IGNORECASE),
    "creditos": re.compile(r"CR[ÉE]DITO|detalle.*cr[ée]d", re.IGNORECASE),
    "documentacion": re.compile(r"DOCUMENTACI[ÓO]N\b|documentos.*acompa[ñn]", re.IGNORECASE),
    "contracautela": re.compile(r"CONTRACAUTELA\b", re.IGNORECASE),
}
