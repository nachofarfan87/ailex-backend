"""
AILEX — Chequeos de revisión de escritos forenses.

Cada función de chequeo recibe el texto normalizado (y parámetros opcionales)
y retorna una lista de Hallazgo. Son funciones puras sin side effects.

Organización:
  check_estructura()        — secciones presentes, partes, encabezado
  check_redaccion()         — negativa genérica, vaguedad, ambigüedad
  check_argumental()        — citas normativas, debilidad de fondo
  check_riesgo_procesal()   — consecuencias procesales concretas
  check_guardrails()        — patrones prohibidos por las políticas del sistema
  detect_fortalezas()       — aspectos positivos detectados

REGLA: ningún check afirma error jurídico definitivo si depende
de normativa no verificada. Usa severidad="moderada" y carácter="inferido"
cuando el hallazgo depende de contexto que puede no estar disponible.
"""

from app.modules.audit.schemas import (
    Hallazgo, TipoHallazgo, Severidad, CaracterHallazgo,
)
from app.modules.audit import heuristics as H


# ─── Estructura ──────────────────────────────────────────────────────────────

def check_estructura(text: str, tipo_escrito: str = None) -> list[Hallazgo]:
    """
    Detectar secciones estructurales faltantes o incompletas.
    Usa SECCIONES_REQUERIDAS para determinar qué se espera según el tipo.
    """
    hallazgos: list[Hallazgo] = []
    tipo_norm = (tipo_escrito or "general").lower().replace("-", "_").replace(" ", "_")
    secciones = H.SECCIONES_REQUERIDAS.get(tipo_norm, H.SECCIONES_REQUERIDAS["general"])

    # Verificar encabezado
    if "encabezado" in secciones and not H.RE_ENCABEZADO.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.EXTRAIDO,
            seccion="encabezado",
            texto_detectado=None,
            observacion="No se detecta encabezado ('Señor/a Juez/a'). El escrito carece de destinatario formal.",
            mejora_sugerida="Agregar encabezado: 'Señor/a Juez/a:' al inicio del escrito.",
        ))

    # Verificar objeto
    if "objeto" in secciones and not H.RE_OBJETO.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="objeto",
            texto_detectado=None,
            observacion="No se detecta sección de objeto o propósito del escrito.",
            mejora_sugerida="Agregar sección 'I. OBJETO' indicando qué se solicita.",
        ))

    # Verificar hechos (solo para tipos que lo requieren)
    if "hechos" in secciones and not H.RE_HECHOS.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="hechos",
            texto_detectado=None,
            observacion="No se detecta sección de hechos. Los hechos deben narrarse ordenadamente.",
            mejora_sugerida="Agregar sección 'II. HECHOS' con relato cronológico y claro.",
        ))

    # Verificar fundamento de derecho
    if "derecho" in secciones and not H.RE_DERECHO.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="derecho",
            texto_detectado=None,
            observacion="No se detecta sección de fundamento de derecho o base normativa.",
            mejora_sugerida="Agregar sección 'III. DERECHO' con la normativa aplicable verificada.",
        ))

    # Verificar petitorio
    if "petitorio" in secciones and not H.RE_PETITORIO.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.EXTRAIDO,
            seccion="petitorio",
            texto_detectado=None,
            observacion="No se detecta petitorio. El escrito carece de pedido concreto al tribunal.",
            mejora_sugerida=(
                "Agregar sección 'PETITORIO' con pedidos numerados y concretos. "
                "El tribunal solo puede resolver lo que se le pide."
            ),
        ))

    # Verificar identificación de partes (DNI / CUIT)
    if not H.RE_DNI.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="partes",
            texto_detectado=None,
            observacion=(
                "No se detecta identificación de partes con DNI/CUIT. "
                "La individualización precisa de las partes es requisito formal."
            ),
            mejora_sugerida=(
                "Incluir nombre completo, DNI/CUIT y domicilio de cada parte."
            ),
        ))

    # Verificar domicilio procesal
    if not H.RE_DOMICILIO.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="domicilio",
            texto_detectado=None,
            observacion=(
                "No se detecta constitución de domicilio procesal o electrónico. "
                "Las notificaciones serán inválidas si no está constituido."
            ),
            mejora_sugerida=(
                "Constituir domicilio procesal y electrónico en el escrito."
            ),
        ))

    # Verificar prueba (si aplica)
    if "prueba" in secciones and not H.RE_PRUEBA_SECCION.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="prueba",
            texto_detectado=None,
            observacion=(
                "No se detecta ofrecimiento de prueba. "
                "En este tipo de escrito suele requerirse en la misma presentación."
            ),
            mejora_sugerida=(
                "Agregar sección 'PRUEBA' con ofrecimiento específico. "
                "La omisión puede generar preclusión del derecho probatorio."
            ),
        ))

    # Verificar matrícula del abogado
    if not H.RE_MATRICULA.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.LEVE,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="personeria",
            texto_detectado=None,
            observacion="No se detecta matrícula del letrado (Tomo/Folio).",
            mejora_sugerida="Incluir matrícula del abogado: 'Matrícula T° [X] F° [Y]'.",
        ))

    # Checks tipo-específicos
    if tipo_norm == "contestacion":
        hallazgos.extend(_check_estructura_contestacion(text))
    elif tipo_norm == "recurso":
        hallazgos.extend(_check_estructura_recurso(text))
    elif tipo_norm == "medida_cautelar":
        hallazgos.extend(_check_estructura_cautelar(text))

    return hallazgos


def _check_estructura_contestacion(text: str) -> list[Hallazgo]:
    hallazgos = []
    if not H.PATRON_SECCION["negativa"].search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="negativa",
            observacion=(
                "No se detecta negativa de hechos en una contestación de demanda. "
                "La ausencia de negativa puede interpretarse como admisión tácita."
            ),
            mejora_sugerida="Agregar sección de negativa específica hecho por hecho.",
        ))
    return hallazgos


def _check_estructura_recurso(text: str) -> list[Hallazgo]:
    hallazgos = []
    if not H.PATRON_SECCION["agravios"].search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="agravios",
            observacion=(
                "No se detecta sección de agravios en un recurso. "
                "Los agravios son el fundamento del recurso y su ausencia puede motivar deserción."
            ),
            mejora_sugerida=(
                "Desarrollar agravios específicos contra la resolución recurrida. "
                "Cada agravio debe identificar el error y su impacto."
            ),
        ))
    return hallazgos


def _check_estructura_cautelar(text: str) -> list[Hallazgo]:
    hallazgos = []
    if not H.PATRON_SECCION["verosimilitud"].search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="verosimilitud",
            observacion="No se detecta acreditación de verosimilitud del derecho en medida cautelar.",
            mejora_sugerida="Fundar verosimilitud del derecho con documentación concreta.",
        ))
    if not H.PATRON_SECCION["peligro_demora"].search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ESTRUCTURA,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="peligro_demora",
            observacion="No se detecta peligro en la demora en medida cautelar.",
            mejora_sugerida="Acreditar peligro en la demora con hechos concretos y actuales.",
        ))
    return hallazgos


# ─── Redacción ────────────────────────────────────────────────────────────────

def check_redaccion(text: str) -> list[Hallazgo]:
    """
    Detectar problemas de redacción: negativa genérica, vaguedad,
    petición ambigua, certeza artificial, lenguaje temerario.
    """
    hallazgos: list[Hallazgo] = []

    # Negativa genérica
    m = H.RE_NEGATIVA_GENERICA.search(text)
    if m:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.REDACCION,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.EXTRAIDO,
            seccion="negativa",
            texto_detectado=m.group(0),
            observacion=(
                "Negativa genérica detectada. En muchos fueros la negativa general "
                "sin especificar hecho por hecho no satisface la carga procesal "
                "y puede ser declarada insuficiente."
            ),
            mejora_sugerida=(
                "Reemplazar por negativa específica hecho por hecho: "
                "'Respecto del hecho [X]: niego / reconozco / desconozco...'"
            ),
        ))
    elif H.RE_NEGATIVA_SEMIGENERICA.search(text):
        m2 = H.RE_NEGATIVA_SEMIGENERICA.search(text)
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.REDACCION,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.EXTRAIDO,
            seccion="negativa",
            texto_detectado=m2.group(0) if m2 else None,
            observacion=(
                "Negativa semigenérica detectada. Si bien es menos riesgosa que la "
                "negativa total, puede no satisfacer el estándar del CPC aplicable."
            ),
            mejora_sugerida="Especificar la negativa hecho por hecho.",
        ))

    # Petición ambigua
    m = H.RE_PETICION_AMBIGUA.search(text)
    if m:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.REDACCION,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.EXTRAIDO,
            seccion="petitorio",
            texto_detectado=m.group(0),
            observacion=(
                "Petición ambigua detectada. El tribunal no puede conceder lo que "
                "no se solicita claramente. La indeterminación del petitorio "
                "puede generar rechazo o resolución por menos de lo pedido."
            ),
            mejora_sugerida=(
                "Precisar el petitorio con verbos concretos: "
                "'se condene al pago de $X', 'se revoque la resolución de fecha Y', etc."
            ),
        ))

    # Vaguedad excesiva
    matches = list(H.RE_VAGUEDAD.finditer(text))
    if len(matches) >= 2:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.REDACCION,
            severidad=Severidad.LEVE,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=", ".join(m.group(0) for m in matches[:3]),
            observacion=(
                f"Se detectaron {len(matches)} expresiones vagas ('etc.', 'y demás', 'entre otras'). "
                "La vaguedad excesiva debilita la claridad del escrito."
            ),
            mejora_sugerida="Especificar cada elemento en lugar de usar expresiones genéricas.",
        ))
    elif len(matches) == 1:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.REDACCION,
            severidad=Severidad.LEVE,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=matches[0].group(0),
            observacion="Expresión vaga detectada. Prefiera enumeración específica.",
            mejora_sugerida="Especificar el elemento en lugar de usar expresión genérica.",
        ))

    # Certeza artificial
    m = H.RE_CERTEZA_ARTIFICIAL.search(text)
    if m:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.REDACCION,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=m.group(0),
            observacion=(
                "Expresión de certeza artificial detectada. "
                "El lenguaje forense prudente evita afirmaciones absolutas."
            ),
            mejora_sugerida=(
                "Reemplazar por lenguaje prudente: 'surge de las constancias', "
                "'conforme la prueba a producirse', 'prima facie'."
            ),
        ))

    # Lenguaje temerario
    m = H.RE_TEMERARIO.search(text)
    if m:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.REDACCION,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=m.group(0),
            observacion=(
                "Lenguaje potencialmente temerario detectado. "
                "Las imputaciones subjetivas sin respaldo probatorio pueden generar "
                "observaciones del tribunal o responsabilidades."
            ),
            mejora_sugerida=(
                "Describir la conducta objetivamente sin calificativos subjetivos "
                "que no estén respaldados por prueba concreta."
            ),
        ))

    return hallazgos


# ─── Argumental ───────────────────────────────────────────────────────────────

def check_argumental(text: str, entities: dict = None) -> list[Hallazgo]:
    """
    Detectar debilidades argumentales: normas sospechosas, citas vagas,
    prueba sin desarrollar, falta de conexión lógica.
    """
    hallazgos: list[Hallazgo] = []
    entities = entities or {}

    # Artículos con numeración sospechosa (4+ dígitos)
    arts_sospechosos = H.RE_ARTICULO_SOSPECHOSO.findall(text)
    for art_num in arts_sospechosos:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ARGUMENTAL,
            severidad=Severidad.GRAVE,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=f"Art. {art_num}",
            observacion=(
                f"El artículo {art_num} tiene numeración inusual (4+ dígitos). "
                "En el derecho argentino los artículos rara vez superan los 3 dígitos. "
                "Puede tratarse de un error de cita o de un artículo inexistente."
            ),
            mejora_sugerida=(
                f"Verificar que el artículo {art_num} existe en el cuerpo normativo citado. "
                "Si no existe, eliminar la cita o reemplazar por el artículo correcto."
            ),
        ))

    # Invocación normativa vaga (sin número de artículo ni ley)
    m = H.RE_NORMA_VAGA.search(text)
    if m:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ARGUMENTAL,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=m.group(0),
            observacion=(
                "Invocación normativa vaga detectada ('según el derecho', 'conforme la ley'). "
                "Sin identificar la norma concreta, el argumento carece de sustento verificable."
            ),
            mejora_sugerida=(
                "Identificar la ley, código y artículo concreto aplicable. "
                "Si no se tiene la cita, usar {{FUNDAMENTO_NORMATIVO}} como placeholder."
            ),
        ))

    # Prueba mencionada pero no detallada
    m = H.RE_PRUEBA_SIN_DETALLAR.search(text)
    if m and not H.RE_PRUEBA_OFERTA.search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.ARGUMENTAL,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.EXTRAIDO,
            seccion="prueba",
            texto_detectado=m.group(0),
            observacion=(
                "Se menciona prueba sin detallarla. "
                "La referencia vaga a 'la prueba' sin especificar qué prueba "
                "no permite al tribunal conocer los medios ofrecidos."
            ),
            mejora_sugerida=(
                "Enumerar específicamente cada medio de prueba: "
                "documental (con detalle), testimonial (con nómina), pericial (con objeto)."
            ),
        ))

    # Ausencia de conectores lógicos en escritos con hechos y derecho
    if H.RE_HECHOS.search(text) and H.RE_DERECHO.search(text):
        if not H.RE_CONECTOR_LOGICO.search(text):
            hallazgos.append(Hallazgo(
                tipo=TipoHallazgo.ARGUMENTAL,
                severidad=Severidad.LEVE,
                caracter=CaracterHallazgo.INFERIDO,
                observacion=(
                    "No se detectan conectores lógicos entre los hechos y el fundamento de derecho. "
                    "La ausencia de articulación explícita (por lo tanto, en consecuencia, etc.) "
                    "puede debilitar la coherencia argumentativa del escrito."
                ),
                mejora_sugerida=(
                    "Agregar párrafo puente que conecte los hechos con la pretensión jurídica: "
                    "'De los hechos expuestos se sigue que...'"
                ),
            ))

    return hallazgos


# ─── Riesgo procesal ──────────────────────────────────────────────────────────

def check_riesgo_procesal(text: str, tipo_escrito: str = None) -> list[Hallazgo]:
    """
    Detectar riesgos procesales concretos: documentos mencionados sin listar,
    plazos vagos, petitorio insuficiente, omisiones esenciales.
    """
    hallazgos: list[Hallazgo] = []

    # Menciona acompañar documentos — verificar si los lista
    if H.RE_ACOMPANA_SIN_LISTA.search(text):
        if not H.RE_LISTADO_DOCUMENTAL.search(text):
            hallazgos.append(Hallazgo(
                tipo=TipoHallazgo.RIESGO_PROCESAL,
                severidad=Severidad.MODERADA,
                caracter=CaracterHallazgo.INFERIDO,
                seccion="documentacion",
                observacion=(
                    "El escrito menciona acompañar documentación pero no lista los documentos. "
                    "La falta de detalle puede dificultar la agregación al expediente "
                    "y generar controversias sobre qué fue presentado."
                ),
                mejora_sugerida=(
                    "Agregar listado numerado de cada documento acompañado: "
                    "tipo, fecha, emisor y número de ejemplares."
                ),
            ))

    # Plazo mencionado vagamente
    m = H.RE_PLAZO_VAGO.search(text)
    if m:
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.RIESGO_PROCESAL,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=m.group(0),
            observacion=(
                "Plazo referenciado de forma vaga ('plazo de ley', 'plazo legal'). "
                "La imprecisión puede generar confusión o aplicación incorrecta del plazo."
            ),
            mejora_sugerida=(
                "Indicar el plazo exacto en días con su fuente normativa: "
                "'dentro del plazo de [X] días hábiles (Art. [Y] CPC)'."
            ),
        ))

    # Para contestaciones: verificar completitud de la defensa
    tipo_norm = (tipo_escrito or "").lower()
    if tipo_norm == "contestacion":
        hallazgos.extend(_check_riesgo_contestacion(text))

    # Para recursos: verificar que esté en término (mención del plazo)
    if tipo_norm == "recurso":
        hallazgos.extend(_check_riesgo_recurso(text))

    return hallazgos


def _check_riesgo_contestacion(text: str) -> list[Hallazgo]:
    hallazgos = []
    # Verificar que hay alguna defensa de fondo (no solo negativa)
    if not H.PATRON_SECCION["defensa"].search(text):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.RIESGO_PROCESAL,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="defensa",
            observacion=(
                "No se detecta defensa de fondo en la contestación. "
                "Una contestación sin fundamento de derecho puede ser insuficiente "
                "para resistir la pretensión del actor."
            ),
            mejora_sugerida=(
                "Agregar defensa de fondo con fundamento normativo verificado. "
                "Usar {{FUNDAMENTO_DEFENSA}} como placeholder si no se tiene el argumento completo."
            ),
        ))
    return hallazgos


def _check_riesgo_recurso(text: str) -> list[Hallazgo]:
    hallazgos = []
    # Verificar que menciona estar en término
    if not any(kw in text.lower() for kw in [
        "en término", "en plazo", "dentro del plazo", "en tiempo y forma",
        "plazo legal", "días para recurrir"
    ]):
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.RIESGO_PROCESAL,
            severidad=Severidad.MODERADA,
            caracter=CaracterHallazgo.INFERIDO,
            seccion="presentacion_en_termino",
            observacion=(
                "No se detecta afirmación de interposición en término. "
                "El recurso debe acreditar su presentación dentro del plazo legal "
                "para ser admitido."
            ),
            mejora_sugerida=(
                "Agregar: 'Que dentro del plazo de [X] días (Art. [Y] CPC/CPP), "
                "vengo a interponer el presente recurso.'"
            ),
        ))
    return hallazgos


# ─── Guardrails ───────────────────────────────────────────────────────────────

def check_guardrails(text: str) -> list[Hallazgo]:
    """
    Verificar violaciones a las políticas del sistema detectadas en el texto del escrito.
    Aplica los mismos guardrails que LegalGuardrails.check_output() pero produce Hallazgo.
    """
    from app.policies.legal_guardrails import LegalGuardrails
    hallazgos: list[Hallazgo] = []

    violations = LegalGuardrails.check_output(text)
    for v in violations:
        sev = Severidad.GRAVE if v.get("severity") == "critical" else Severidad.MODERADA
        hallazgos.append(Hallazgo(
            tipo=TipoHallazgo.GUARDRAIL,
            severidad=sev,
            caracter=CaracterHallazgo.EXTRAIDO,
            texto_detectado=None,
            observacion=f"[{v['guardrail']}] {v['issue']}",
            mejora_sugerida=v.get("action"),
        ))

    return hallazgos


# ─── Fortalezas ───────────────────────────────────────────────────────────────

def detect_fortalezas(text: str, entities: dict = None) -> list[str]:
    """
    Detectar aspectos positivos del escrito.
    Retorna lista de descripciones de fortalezas.
    """
    entities = entities or {}
    fortalezas: list[str] = []

    if H.RE_ENCABEZADO.search(text):
        fortalezas.append("Encabezado formal presente.")
    if H.RE_OBJETO.search(text):
        fortalezas.append("Sección de objeto o propósito claramente indicada.")
    if H.RE_PETITORIO.search(text):
        fortalezas.append("Petitorio presente.")
    if H.RE_PRUEBA_OFERTA.search(text):
        fortalezas.append("Ofrecimiento de prueba detectado.")
    if H.RE_DOMICILIO.search(text):
        fortalezas.append("Domicilio procesal constituido.")
    if H.RE_DNI.search(text):
        fortalezas.append("Partes identificadas con DNI/CUIT.")
    if H.RE_NEGATIVA_ESPECIFICA.search(text):
        fortalezas.append("Se detectan elementos de negativa específica (favorable).")
    if H.RE_ARTICULO_CONCRETO.search(text) and not H.RE_ARTICULO_SOSPECHOSO.search(text):
        fortalezas.append("Artículos normativos citados con numeración razonable.")
    if H.RE_LEY_CITADA.search(text):
        fortalezas.append("Leyes citadas con número (verificar vigencia y aplicabilidad).")
    if H.RE_CONECTOR_LOGICO.search(text):
        fortalezas.append("Conectores lógicos presentes — argumentación estructurada.")
    if H.RE_HECHOS.search(text) and H.RE_DERECHO.search(text):
        fortalezas.append("Estructura completa con sección de hechos y derecho.")

    return fortalezas
