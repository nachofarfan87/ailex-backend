"""
AILEX — Plantillas estructuradas de escritos forenses.

Cada plantilla define:
- Estructura canónica (secciones en orden)
- Texto base con {{PLACEHOLDER}} para todo dato no provisto
- Ajustes de tono por variante (conservador / estandar / firme / agresivo_prudente)
- Placeholders requeridos y opcionales
- Checklist previo a la presentación
- Riesgos habituales del tipo de escrito

REGLA FUNDAMENTAL: los placeholders nunca se autocompletan.
Todo dato desconocido → {{NOMBRE_DEL_DATO}}.

Variantes:
  conservador      — mínimo riesgo, máxima formalidad, fórmulas cautelosas
  estandar         — equilibrio entre completitud y prudencia (default)
  firme            — tono asertivo y directo, sin condicionantes innecesarios
  agresivo_prudente— máxima argumentación disponible, sin temeraridad ni invención
"""

from app.modules.generation.schemas import TemplateMetadata

# ─── Fórmulas por variante ───────────────────────────────────────────────────
# Cada variante ajusta el tono de ciertas fórmulas sin cambiar hechos ni datos.

VARIANTES_FORMULAS: dict[str, dict[str, str]] = {
    "conservador": {
        "apertura": "respetuosamente me presento y digo",
        "petitorio_intro": "En virtud de lo expuesto, y con la prudencia que el caso amerita, solicito a V.S.:",
        "petitorio_costas": "con costas si correspondiere",
        "tono_derecho": "Con fundamento en la normativa aplicable al caso, cuya determinación concreta queda sujeta a verificación jurídica,",
        "cierre_advertencia": "Se deja constancia que el presente escrito es un borrador sujeto a revisión profesional.",
    },
    "estandar": {
        "apertura": "me presento y respetuosamente digo",
        "petitorio_intro": "Por todo lo expuesto, solicito a V.S.:",
        "petitorio_costas": "con costas",
        "tono_derecho": "En virtud de la normativa aplicable,",
        "cierre_advertencia": "Se solicita el acogimiento de lo peticionado.",
    },
    "firme": {
        "apertura": "me presento y digo",
        "petitorio_intro": "Por las razones expuestas, solicito a V.S. que:",
        "petitorio_costas": "con costas a la contraria",
        "tono_derecho": "Conforme la normativa que rige la materia y los principios generales del derecho,",
        "cierre_advertencia": "Se hace reserva de ampliar fundamentos en la oportunidad procesal correspondiente.",
    },
    "agresivo_prudente": {
        "apertura": "me presento y, con el respeto de estilo, digo",
        "petitorio_intro": "Sobre la base de los argumentos desarrollados, solicito a V.S.:",
        "petitorio_costas": "con especial imposición de costas a la contraria",
        "tono_derecho": "Sobre la base de la normativa vigente y los principios generales del derecho que informan la materia,",
        "cierre_advertencia": "Se hace expresa reserva de todos los derechos y acciones que asisten a la parte.",
    },
}

VARIANTES_VALIDAS = list(VARIANTES_FORMULAS.keys())


def _formula(variante: str, clave: str) -> str:
    """Obtener fórmula de variante con fallback a estandar."""
    return VARIANTES_FORMULAS.get(variante, VARIANTES_FORMULAS["estandar"]).get(
        clave, VARIANTES_FORMULAS["estandar"][clave]
    )


# ─── Generadores de texto por plantilla ─────────────────────────────────────
# Cada función recibe la variante y retorna el texto base con placeholders.

def _texto_demanda(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    pc = _formula(variante, "petitorio_costas")
    td = _formula(variante, "tono_derecho")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "PROMUEVE DEMANDA — {{MATERIA}}\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_ACTOR}}, DNI {{DNI_ACTOR}}, con domicilio real en {{DOMICILIO_REAL_ACTOR}}, "
        f"constituyendo domicilio procesal en {{{{DOMICILIO_PROCESAL}}}}, "
        "con patrocinio letrado del/la Dr./Dra. {{NOMBRE_ABOGADO}}, "
        "Matrícula T° {{TOMO}} F° {{FOLIO}} del Colegio de Abogados, "
        f"ante V.S. {ap}:\n\n"
        "I. OBJETO\n"
        "Que vengo a promover demanda por {{OBJETO_DE_LA_DEMANDA}} contra "
        "{{NOMBRE_DEMANDADO}}, DNI/CUIT {{DNI_DEMANDADO}}, "
        "con domicilio en {{DOMICILIO_DEMANDADO}}, "
        "reclamando la suma de {{MONTO_RECLAMADO}} o lo que en más o en menos "
        "resulte de la prueba a producirse, {{FUNDAMENTO_DEL_MONTO}}.\n\n"
        "II. HECHOS\n"
        "{{RELATO_DE_HECHOS}}\n\n"
        "III. DERECHO\n"
        f"{td}\n"
        "{{FUNDAMENTO_NORMATIVO}}\n"
        "[ADVERTENCIA: verificar artículos y normativa aplicable antes de presentar]\n\n"
        "IV. PRUEBA\n"
        "Ofrezco los siguientes medios de prueba:\n"
        "{{OFRECIMIENTO_DE_PRUEBA}}\n\n"
        "V. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por presentada la demanda y por constituido el domicilio procesal;\n"
        "2. Se corra traslado al demandado {{NOMBRE_DEMANDADO}} conforme las normas procesales aplicables;\n"
        "3. Oportunamente, se haga lugar a la demanda en todas sus partes, "
        f"con condena al pago de {{{{MONTO_RECLAMADO}}}}, {pc}.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


def _texto_contestacion(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    pc = _formula(variante, "petitorio_costas")
    td = _formula(variante, "tono_derecho")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "CONTESTA DEMANDA\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_DEMANDADO}}, DNI {{DNI_DEMANDADO}}, "
        f"constituyendo domicilio procesal en {{{{DOMICILIO_PROCESAL}}}}, "
        "con patrocinio letrado del/la Dr./Dra. {{NOMBRE_ABOGADO}}, "
        "Matrícula T° {{TOMO}} F° {{FOLIO}}, "
        "en autos \"{{CARATULA}}\" (Expte. N° {{NUMERO_EXPEDIENTE}}), "
        f"ante V.S. {ap}:\n\n"
        "I. NEGATIVA GENERAL Y ESPECÍFICA\n"
        "Niego todos y cada uno de los hechos afirmados en la demanda que no sean "
        "objeto de expreso reconocimiento en el presente escrito.\n"
        "En particular:\n"
        "{{NEGATIVA_ESPECIFICA_HECHO_POR_HECHO}}\n\n"
        "II. EXCEPCIONES PREVIAS\n"
        "{{EXCEPCIONES_PREVIAS_SI_APLICA}}\n"
        "[Si no hay excepciones previas, indicar expresamente: "
        "'No se oponen excepciones previas.']\n\n"
        "III. DEFENSA DE FONDO\n"
        f"{td}\n"
        "{{FUNDAMENTO_DEFENSA}}\n"
        "[ADVERTENCIA: verificar artículos y normativa aplicable antes de presentar]\n\n"
        "IV. PRUEBA\n"
        "Ofrezco los siguientes medios de prueba:\n"
        "{{OFRECIMIENTO_DE_PRUEBA}}\n\n"
        "V. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por contestada la demanda en tiempo y forma;\n"
        "2. Se tengan por opuestas las defensas y excepciones planteadas;\n"
        "3. Oportunamente, se rechace la demanda en todas sus partes, "
        f"{pc}.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


def _texto_contesta_traslado(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    td = _formula(variante, "tono_derecho")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "CONTESTA TRASLADO — {{OBJETO_DEL_TRASLADO}}\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_PARTE}}, en autos \"{{CARATULA}}\" (Expte. N° {{NUMERO_EXPEDIENTE}}), "
        "con el patrocinio letrado del/la Dr./Dra. {{NOMBRE_ABOGADO}}, "
        "Matrícula T° {{TOMO}} F° {{FOLIO}}, "
        f"ante V.S. {ap}:\n\n"
        "I. OBJETO\n"
        "Que vengo a contestar el traslado conferido en autos respecto de "
        "{{OBJETO_DEL_TRASLADO}}, en los términos que a continuación se exponen.\n\n"
        "II. CONSIDERACIONES\n"
        f"{td}\n"
        "{{DESARROLLO_DE_CONSIDERACIONES}}\n"
        "[ADVERTENCIA: desarrollar los argumentos específicos del traslado]\n\n"
        "III. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por contestado el traslado en tiempo y forma;\n"
        "2. {{PETICION_ESPECIFICA}};\n"
        "3. Oportunamente, se resuelva conforme a derecho.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


def _texto_pronto_despacho(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "SOLICITA PRONTO DESPACHO\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_PARTE}}, en autos \"{{CARATULA}}\" (Expte. N° {{NUMERO_EXPEDIENTE}}), "
        "con el patrocinio letrado del/la Dr./Dra. {{NOMBRE_ABOGADO}}, "
        "Matrícula T° {{TOMO}} F° {{FOLIO}}, "
        f"ante V.S. {ap}:\n\n"
        "I. OBJETO\n"
        "Que vengo a solicitar pronto despacho en las presentes actuaciones, "
        "dado que con fecha {{FECHA_ULTIMA_PRESENTACION}} se realizó "
        "{{DESCRIPCION_ULTIMA_ACTUACION}} y a la fecha no se ha obtenido resolución.\n\n"
        "II. FUNDAMENTO\n"
        "El tiempo transcurrido desde la última actuación es de {{TIEMPO_TRANSCURRIDO}}, "
        "circunstancia que afecta los derechos de mi parte en tanto {{FUNDAMENTO_URGENCIA}}.\n"
        "[ADVERTENCIA: verificar plazos procesales aplicables según CPC vigente]\n\n"
        "III. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por solicitado el pronto despacho;\n"
        "2. Se dicte resolución en el menor plazo posible respecto de {{CUESTION_PENDIENTE}}.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


def _texto_solicita_pronto_pago(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    pc = _formula(variante, "petitorio_costas")
    td = _formula(variante, "tono_derecho")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "SOLICITA PRONTO PAGO LABORAL\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_TRABAJADOR}}, DNI {{DNI_TRABAJADOR}}, "
        "con domicilio real en {{DOMICILIO_TRABAJADOR}}, "
        f"constituyendo domicilio procesal en {{{{DOMICILIO_PROCESAL}}}}, "
        "con patrocinio letrado del/la Dr./Dra. {{NOMBRE_ABOGADO}}, "
        "Matrícula T° {{TOMO}} F° {{FOLIO}}, "
        f"ante V.S. {ap}:\n\n"
        "I. OBJETO\n"
        "Que vengo a solicitar el beneficio de pronto pago previsto en la Ley 24.522 "
        "(Ley de Concursos y Quiebras) y/o normativa laboral aplicable, "
        "en los créditos laborales que a continuación se detallan.\n"
        "[ADVERTENCIA: verificar procedencia según el fuero y la normativa vigente]\n\n"
        "II. CRÉDITOS RECLAMADOS\n"
        "Los créditos laborales cuyo pronto pago se solicita son:\n"
        "{{DETALLE_DE_CREDITOS_LABORALES}}\n"
        "Total reclamado: {{MONTO_TOTAL_CREDITO}}\n\n"
        "III. FUNDAMENTO NORMATIVO\n"
        f"{td}\n"
        "{{FUNDAMENTO_NORMATIVO_LABORAL}}\n"
        "[ADVERTENCIA: citar artículos verificados de la ley aplicable]\n\n"
        "IV. DOCUMENTACIÓN ACOMPAÑADA\n"
        "{{DETALLE_DE_DOCUMENTACION_ADJUNTA}}\n\n"
        "V. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por presentada la solicitud de pronto pago;\n"
        "2. Se admita el crédito laboral denunciado por la suma de {{MONTO_TOTAL_CREDITO}};\n"
        "3. Se ordene el pago inmediato conforme al orden de privilegios legal, "
        f"{pc}.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


def _texto_acompana_documentacion(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "ACOMPAÑA DOCUMENTACIÓN\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_PARTE}}, en autos \"{{CARATULA}}\" (Expte. N° {{NUMERO_EXPEDIENTE}}), "
        "con el patrocinio letrado del/la Dr./Dra. {{NOMBRE_ABOGADO}}, "
        "Matrícula T° {{TOMO}} F° {{FOLIO}}, "
        f"ante V.S. {ap}:\n\n"
        "I. OBJETO\n"
        "Que vengo a acompañar documentación en las presentes actuaciones, "
        "en cumplimiento de lo ordenado por V.S. con fecha {{FECHA_RESOLUCION_QUE_ORDENA}} "
        "/ en apoyo de la posición de mi parte {{MOTIVO_DE_LA_PRESENTACION}}.\n\n"
        "II. DOCUMENTACIÓN QUE SE ACOMPAÑA\n"
        "Se adjuntan al presente los siguientes documentos:\n"
        "{{LISTADO_DE_DOCUMENTOS}}\n"
        "[Indicar: tipo de documento, fecha, emisor y número de ejemplares]\n\n"
        "III. RELEVANCIA DE LA DOCUMENTACIÓN\n"
        "{{EXPLICACION_DE_RELEVANCIA}}\n\n"
        "IV. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por acompañada la documentación precedentemente detallada;\n"
        "2. Se agregue a los autos para su oportuna valoración;\n"
        "3. {{PETICION_ADICIONAL_SI_APLICA}}.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


def _texto_recurso(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    td = _formula(variante, "tono_derecho")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "INTERPONE RECURSO DE APELACIÓN\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_RECURRENTE}}, en autos \"{{CARATULA}}\" (Expte. N° {{NUMERO_EXPEDIENTE}}), "
        f"ante V.S. {ap}:\n\n"
        "I. PRESENTACIÓN EN TÉRMINO\n"
        "Que dentro del plazo legal ({{VERIFICAR_PLAZO_RECURSIVO}}), "
        "vengo a interponer recurso de apelación contra la resolución de fecha "
        "{{FECHA_RESOLUCION_RECURRIDA}}, que {{DESCRIPCION_DE_LO_RESUELTO}}.\n"
        "[ADVERTENCIA: verificar el plazo recursivo en el CPC/CPP vigente según el tipo de resolución]\n\n"
        "II. AGRAVIOS\n"
        f"{td}\n"
        "{{DESARROLLO_DE_AGRAVIOS}}\n"
        "[ADVERTENCIA: desarrollar cada agravio en forma separada y fundada]\n\n"
        "III. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por interpuesto el recurso en tiempo y forma;\n"
        "2. Se conceda el recurso y se eleven los autos al tribunal de alzada;\n"
        "3. Oportunamente, se revoque la resolución recurrida en todas sus partes.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


def _texto_medida_cautelar(variante: str) -> str:
    ap = _formula(variante, "apertura")
    pi = _formula(variante, "petitorio_intro")
    td = _formula(variante, "tono_derecho")
    ca = _formula(variante, "cierre_advertencia")
    return (
        "SOLICITA MEDIDA CAUTELAR\n\n"
        "Señor/a Juez/a:\n\n"
        "{{NOMBRE_PETICIONANTE}}, DNI {{DNI_PETICIONANTE}}, "
        "en autos \"{{CARATULA}}\" / en los presentes que se iniciarán, "
        f"ante V.S. {ap}:\n\n"
        "I. VEROSIMILITUD DEL DERECHO\n"
        f"{td}\n"
        "{{FUNDAMENTO_VEROSIMILITUD}}\n"
        "[ADVERTENCIA: fundar con normativa verificada — no inventar citas]\n\n"
        "II. PELIGRO EN LA DEMORA\n"
        "{{FUNDAMENTO_PELIGRO_DEMORA}}\n\n"
        "III. CONTRACAUTELA\n"
        "{{CONTRACAUTELA_OFRECIDA}}\n"
        "[Indicar: caución real, personal o juratoria, según corresponda]\n\n"
        "IV. MEDIDA SOLICITADA\n"
        "{{DESCRIPCION_EXACTA_DE_LA_MEDIDA}}\n"
        "[Indicar con precisión: tipo de medida, bien afectado, alcance]\n\n"
        "V. PETITORIO\n"
        f"{pi}\n"
        "1. Se tenga por solicitada la medida cautelar;\n"
        "2. Sin sustanciación previa, se haga lugar a la {{TIPO_DE_MEDIDA}} "
        "sobre {{BIEN_O_PERSONA_AFECTADA}};\n"
        "3. Se libre oficio/mandamiento a {{ORGANISMO_DESTINATARIO}}.\n\n"
        f"{ca}\n"
        "Proveer de conformidad, SERÁ JUSTICIA."
    )


# ─── Definiciones de plantillas ─────────────────────────────────────────────

TEMPLATES: dict[str, TemplateMetadata] = {
    "demanda": TemplateMetadata(
        id="demanda_v1",
        nombre="Demanda",
        fuero="civil",
        materia="general",
        tipo_escrito="demanda",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "objeto", "hechos", "derecho", "prueba", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_ACTOR", "DNI_ACTOR", "DOMICILIO_REAL_ACTOR",
            "DOMICILIO_PROCESAL", "NOMBRE_ABOGADO", "TOMO", "FOLIO",
            "MATERIA", "OBJETO_DE_LA_DEMANDA",
            "NOMBRE_DEMANDADO", "DNI_DEMANDADO", "DOMICILIO_DEMANDADO",
            "MONTO_RECLAMADO", "RELATO_DE_HECHOS",
            "FUNDAMENTO_NORMATIVO", "OFRECIMIENTO_DE_PRUEBA",
        ],
        placeholders_opcionales=[
            "FUNDAMENTO_DEL_MONTO", "CARATULA", "NUMERO_EXPEDIENTE",
        ],
        checklist_previo=[
            "Verificar personería y acreditación de representación (poderes, estatutos)",
            "Confirmar competencia del juzgado (materia, cuantía, territorio)",
            "Controlar prescripción y caducidad de la acción",
            "Acompañar prueba documental base junto con la demanda",
            "Verificar correcta individualización del demandado (nombre, CUIT/DNI, domicilio)",
            "Revisar el monto reclamado y su fundamento (daños, liquidación, intereses)",
            "Controlar firma del letrado y copias necesarias según el juzgado",
            "Verificar que la normativa citada en el fundamento es la vigente",
            "Confirmar fuero y tribunal competente (civil, laboral, familia, etc.)",
        ],
        riesgos_habituales=[
            "Falta de individualización precisa del demandado puede dificultar la notificación",
            "Petitorio ambiguo o indeterminado puede dar lugar a excepciones de defecto legal",
            "Normativa citada sin verificación puede invalidar el fundamento de derecho",
            "Falta de ofrecimiento de prueba oportuno puede generar pérdida del derecho",
            "Domicilio procesal no constituido correctamente afecta la validez de las notificaciones",
        ],
    ),

    "contestacion": TemplateMetadata(
        id="contestacion_v1",
        nombre="Contestación de Demanda",
        fuero="civil",
        materia="general",
        tipo_escrito="contestacion",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "negativa", "excepciones", "defensa", "prueba", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_DEMANDADO", "DNI_DEMANDADO", "DOMICILIO_PROCESAL",
            "NOMBRE_ABOGADO", "TOMO", "FOLIO",
            "CARATULA", "NUMERO_EXPEDIENTE",
            "NEGATIVA_ESPECIFICA_HECHO_POR_HECHO",
            "FUNDAMENTO_DEFENSA", "OFRECIMIENTO_DE_PRUEBA",
        ],
        placeholders_opcionales=[
            "EXCEPCIONES_PREVIAS_SI_APLICA",
        ],
        checklist_previo=[
            "Verificar que la contestación se presenta dentro del plazo procesal",
            "Controlar que la negativa sea específica hecho por hecho (no genérica)",
            "Identificar si hay excepciones previas a oponer en este acto",
            "Verificar representación y poderes del demandado si es persona jurídica",
            "Acompañar prueba documental de descargo con la contestación",
            "Controlar la correcta constitución de domicilio procesal",
            "Revisar si hay reconvención a plantear en el mismo escrito",
            "Verificar la normativa citada en la defensa de fondo",
            "Controlar firma del letrado y copias necesarias",
        ],
        riesgos_habituales=[
            "Negativa genérica sin especificar hecho por hecho puede ser declarada insuficiente",
            "Omitir excepciones previas en este acto puede importar su pérdida",
            "No ofrecer prueba en la contestación puede generar preclusión",
            "Falta de reconvención en esta oportunidad puede impedir plantearla después",
            "Presentación fuera de plazo importa la rebeldía del demandado",
        ],
    ),

    "contesta_traslado": TemplateMetadata(
        id="contesta_traslado_v1",
        nombre="Contesta Traslado",
        fuero="general",
        materia="general",
        tipo_escrito="contesta_traslado",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "objeto", "consideraciones", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_PARTE", "CARATULA", "NUMERO_EXPEDIENTE",
            "NOMBRE_ABOGADO", "TOMO", "FOLIO",
            "OBJETO_DEL_TRASLADO",
            "DESARROLLO_DE_CONSIDERACIONES",
            "PETICION_ESPECIFICA",
        ],
        placeholders_opcionales=[],
        checklist_previo=[
            "Verificar que la contestación se presenta dentro del plazo del traslado conferido",
            "Identificar con precisión el acto que originó el traslado",
            "Controlar que la respuesta abarca todos los puntos del traslado",
            "Acompañar documentación de respaldo si la consideración lo requiere",
            "Verificar firma y copias según las normas del juzgado",
        ],
        riesgos_habituales=[
            "Presentación fuera del plazo del traslado puede importar consentimiento",
            "Respuesta incompleta a los puntos del traslado puede perjudicar la posición procesal",
            "No acompañar documentación de respaldo cuando existe debilita la contestación",
        ],
    ),

    "pronto_despacho": TemplateMetadata(
        id="pronto_despacho_v1",
        nombre="Solicita Pronto Despacho",
        fuero="general",
        materia="general",
        tipo_escrito="pronto_despacho",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "objeto", "fundamento", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_PARTE", "CARATULA", "NUMERO_EXPEDIENTE",
            "NOMBRE_ABOGADO", "TOMO", "FOLIO",
            "FECHA_ULTIMA_PRESENTACION", "DESCRIPCION_ULTIMA_ACTUACION",
            "TIEMPO_TRANSCURRIDO", "FUNDAMENTO_URGENCIA",
            "CUESTION_PENDIENTE",
        ],
        placeholders_opcionales=[],
        checklist_previo=[
            "Verificar que efectivamente existe mora judicial o administrativa",
            "Confirmar que se han cumplido los pasos previos requeridos",
            "Documentar la última actuación y la fecha correspondiente",
            "Verificar si aplica alguna norma específica de pronto despacho (Ley 19.549 si es administrativo)",
            "Controlar firma y copias",
        ],
        riesgos_habituales=[
            "Presentar pronto despacho sin que haya transcurrido el plazo legal puede ser rechazado",
            "No identificar con precisión la cuestión pendiente hace improcedente la solicitud",
            "En sede administrativa, omitir el encuadre en la norma específica debilita el pedido",
        ],
    ),

    "solicita_pronto_pago": TemplateMetadata(
        id="solicita_pronto_pago_v1",
        nombre="Solicita Pronto Pago Laboral",
        fuero="laboral",
        materia="laboral",
        tipo_escrito="solicita_pronto_pago",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "objeto", "creditos", "fundamento_normativo", "documentacion", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_TRABAJADOR", "DNI_TRABAJADOR", "DOMICILIO_TRABAJADOR",
            "DOMICILIO_PROCESAL", "NOMBRE_ABOGADO", "TOMO", "FOLIO",
            "DETALLE_DE_CREDITOS_LABORALES", "MONTO_TOTAL_CREDITO",
            "FUNDAMENTO_NORMATIVO_LABORAL",
            "DETALLE_DE_DOCUMENTACION_ADJUNTA",
        ],
        placeholders_opcionales=[
            "CARATULA", "NUMERO_EXPEDIENTE",
        ],
        checklist_previo=[
            "Verificar que el crédito tiene privilegio laboral reconocido por ley",
            "Confirmar que existe proceso concursal o quiebra en trámite (si aplica Ley 24.522)",
            "Reunir toda la documentación respaldatoria del crédito laboral (recibos, liquidaciones, etc.)",
            "Verificar el fuero competente para el pronto pago en la jurisdicción",
            "Controlar que la liquidación del crédito es correcta e incluye intereses si corresponde",
            "Acompañar la documentación detallada con el escrito",
            "Verificar si se requiere certificación contable de los créditos",
        ],
        riesgos_habituales=[
            "Falta de documentación respaldatoria puede motivar el rechazo del pronto pago",
            "Errores en la liquidación del crédito pueden reducir o eliminar el privilegio",
            "En procesos concursales, el pronto pago tiene plazos específicos a controlar",
            "No todos los créditos laborales tienen el mismo privilegio — verificar categoría",
            "Fuero y procedimiento varían según la jurisdicción — verificar normativa local",
        ],
    ),

    "acompana_documentacion": TemplateMetadata(
        id="acompana_documentacion_v1",
        nombre="Acompaña Documentación",
        fuero="general",
        materia="general",
        tipo_escrito="acompana_documentacion",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "objeto", "documentacion", "relevancia", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_PARTE", "CARATULA", "NUMERO_EXPEDIENTE",
            "NOMBRE_ABOGADO", "TOMO", "FOLIO",
            "LISTADO_DE_DOCUMENTOS",
            "EXPLICACION_DE_RELEVANCIA",
            "MOTIVO_DE_LA_PRESENTACION",
        ],
        placeholders_opcionales=[
            "FECHA_RESOLUCION_QUE_ORDENA",
            "PETICION_ADICIONAL_SI_APLICA",
        ],
        checklist_previo=[
            "Controlar que cada documento acompañado está correctamente identificado en el escrito",
            "Verificar que los documentos son copias certificadas o simples según lo requerido",
            "Confirmar la cantidad de copias a acompañar según el juzgado",
            "Verificar si la documentación fue oportunamente ofrecida como prueba",
            "Controlar fecha y firma del letrado",
            "Si se acompaña en cumplimiento de una orden judicial, identificar la resolución",
        ],
        riesgos_habituales=[
            "Documentación no ofrecida oportunamente como prueba puede ser rechazada",
            "Falta de descripción precisa de cada documento puede generar confusión o rechazo",
            "Documentos en idioma extranjero requieren traducción certificada",
            "Acompañar fotocopias simples cuando se requieren certificadas puede invalidar el acto",
        ],
    ),

    "recurso": TemplateMetadata(
        id="recurso_apelacion_v1",
        nombre="Recurso de Apelación",
        fuero="general",
        materia="general",
        tipo_escrito="recurso",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "presentacion_en_termino", "agravios", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_RECURRENTE", "CARATULA", "NUMERO_EXPEDIENTE",
            "VERIFICAR_PLAZO_RECURSIVO",
            "FECHA_RESOLUCION_RECURRIDA", "DESCRIPCION_DE_LO_RESUELTO",
            "DESARROLLO_DE_AGRAVIOS",
        ],
        placeholders_opcionales=[
            "NOMBRE_ABOGADO", "TOMO", "FOLIO",
        ],
        checklist_previo=[
            "Verificar que el recurso se interpone dentro del plazo legal (diferente según tipo de resolución)",
            "Controlar si la resolución es apelable o requiere otro tipo de recurso",
            "Desarrollar los agravios en forma específica y fundada — no basta la mera disconformidad",
            "Verificar si hay reserva de caso federal a formular",
            "Controlar si la apelación lleva expresión de agravios diferida o en el mismo acto",
            "Verificar si se requiere depósito previo o caución para apelar",
            "Controlar firma y copias",
        ],
        riesgos_habituales=[
            "Recurso presentado fuera de término es declarado inadmisible de plano",
            "Agravios genéricos o sin fundamentación pueden motivar deserción del recurso",
            "No verificar si la resolución es apelable puede derivar en un recurso improcedente",
            "Omitir la reserva de caso federal cuando corresponde impide el acceso a instancias superiores",
        ],
    ),

    "medida_cautelar": TemplateMetadata(
        id="medida_cautelar_v1",
        nombre="Solicita Medida Cautelar",
        fuero="civil",
        materia="general",
        tipo_escrito="medida_cautelar",
        version="1.0",
        variantes_permitidas=VARIANTES_VALIDAS,
        estructura_base=["encabezado", "personeria", "verosimilitud", "peligro_demora", "contracautela", "medida_solicitada", "petitorio"],
        placeholders_requeridos=[
            "NOMBRE_PETICIONANTE", "DNI_PETICIONANTE",
            "FUNDAMENTO_VEROSIMILITUD",
            "FUNDAMENTO_PELIGRO_DEMORA",
            "CONTRACAUTELA_OFRECIDA",
            "DESCRIPCION_EXACTA_DE_LA_MEDIDA",
            "TIPO_DE_MEDIDA",
            "BIEN_O_PERSONA_AFECTADA",
            "ORGANISMO_DESTINATARIO",
        ],
        placeholders_opcionales=[
            "CARATULA", "NUMERO_EXPEDIENTE",
        ],
        checklist_previo=[
            "Acreditar verosimilitud del derecho con documentación suficiente",
            "Demostrar peligro en la demora con hechos concretos y actuales",
            "Definir con precisión la medida solicitada y el bien afectado",
            "Ofrecer la contracautela adecuada al tipo de medida",
            "Verificar si la medida es inaudita parte o requiere bilateralidad",
            "Identificar el organismo o registro destinatario del oficio (Registro de la Propiedad, banco, etc.)",
            "Controlar si la normativa procesal admite la medida en el fuero",
        ],
        riesgos_habituales=[
            "Verosimilitud insuficientemente fundada lleva al rechazo de la medida",
            "Descripción imprecisa de la medida puede impedir su traba efectiva",
            "Contracautela inadecuada puede motivar el rechazo o la traba de la medida",
            "No identificar correctamente el organismo destinatario impide el diligenciamiento del oficio",
            "Medidas cautelares sin urgencia demostrada pueden rechazarse o tramitarse con sustanciación",
        ],
    ),
}


def get_template_text(tipo_escrito: str, variante: str) -> str | None:
    """
    Obtener el texto de la plantilla para un tipo de escrito y variante.
    Retorna None si el tipo no existe.
    """
    _generadores = {
        "demanda": _texto_demanda,
        "contestacion": _texto_contestacion,
        "contesta_traslado": _texto_contesta_traslado,
        "pronto_despacho": _texto_pronto_despacho,
        "solicita_pronto_pago": _texto_solicita_pronto_pago,
        "acompana_documentacion": _texto_acompana_documentacion,
        "recurso": _texto_recurso,
        "medida_cautelar": _texto_medida_cautelar,
    }
    gen = _generadores.get(tipo_escrito)
    if gen is None:
        return None
    variante_norm = _normalizar_variante(variante)
    return gen(variante_norm)


def _normalizar_variante(variante: str) -> str:
    """
    Normalizar nombre de variante para compatibilidad con nombres anteriores.
    conservadora → conservador, agresiva_prudente → agresivo_prudente, etc.
    """
    _alias = {
        "conservadora": "conservador",
        "agresiva_prudente": "agresivo_prudente",
        "agresivo": "agresivo_prudente",
        "estandar": "estandar",
        "firme": "firme",
        "conservador": "conservador",
        "agresivo_prudente": "agresivo_prudente",
    }
    return _alias.get(variante.lower(), "estandar")
