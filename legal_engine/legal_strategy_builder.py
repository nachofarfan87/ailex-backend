from __future__ import annotations

import re
import unicodedata
from typing import Any


def build_legal_strategy(
    *,
    query: str,
    facts: dict[str, Any] | None = None,
    classification: dict[str, Any] | None = None,
    case_structure: dict[str, Any] | None = None,
    normative_reasoning: dict[str, Any] | None = None,
    procedural_strategy: dict[str, Any] | None = None,
    question_engine_result: dict[str, Any] | None = None,
    conflict_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts = facts or {}
    classification = classification or {}
    case_structure = case_structure or {}
    normative_reasoning = normative_reasoning or {}
    procedural_strategy = procedural_strategy or {}
    question_engine_result = question_engine_result or {}
    conflict_evidence = conflict_evidence or {}

    tipo_accion = _resolve_tipo_accion(query, facts, classification)
    variables = _detect_variables(
        query=query,
        facts=facts,
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        conflict_evidence=conflict_evidence,
    )

    if tipo_accion == "alimentos":
        return _build_alimentos_strategy(tipo_accion, variables)
    if tipo_accion == "divorcio":
        return _build_divorcio_strategy(tipo_accion, variables, classification)
    if tipo_accion == "cuidado_personal":
        return _build_cuidado_personal_strategy(tipo_accion, variables)
    return _build_fallback_strategy(tipo_accion, variables)


def _build_alimentos_strategy(tipo_accion: str, variables: dict[str, Any]) -> dict[str, Any]:
    children = variables.get("cantidad_hijos") or 1
    age = variables.get("edad_hijo")
    studies = variables.get("estudios")
    urgency = bool(variables.get("urgencia"))
    coexistence = variables.get("convivencia")
    incumplimiento = variables.get("incumplimientos")
    income_known = bool(variables.get("ingresos_demandado"))
    informal_income = bool(variables.get("ingresos_informales"))

    if income_known:
        if children >= 2:
            porcentaje = "30% a 35% de los haberes netos, con asignaciones y obra social aparte"
        elif urgency or incumplimiento in {"grave", "total"} or (age and age >= 13) or studies:
            porcentaje = "25% de los haberes netos, con escolaridad, salud y extraordinarios por fuera"
        else:
            porcentaje = "20% de los haberes netos, con asignaciones familiares y cobertura medica aparte"
    elif informal_income:
        porcentaje = "30% del SMVM como piso, con actualizacion y extraordinarios por fuera"
    else:
        porcentaje = "25% del SMVM como base provisoria, a reconducir cuando aparezca prueba patrimonial"

    pretensiones_secundarias: list[str] = []
    medidas: list[str] = [
        "acompanar planilla de gastos reales del hijo con tickets, cuotas y salud",
        "pedir informe ANSES, AFIP y SINTyS para ubicar ingresos y prestaciones",
        "librar oficio al empleador si hay trabajo registrado para retencion directa",
    ]

    if studies:
        medidas.append("agregar certificado de alumno regular y cronograma de estudios")
    if coexistence:
        medidas.append("acreditar convivencia y centro de vida con constancias escolares, medicas o vecinales")
    if variables.get("cuenta_bancaria"):
        medidas.append("denunciar CBU para deposito judicial o transferencia directa")
    if not income_known:
        medidas.append("pedir informes a Registro Automotor, inmuebles y bancos si hay indicios de ocultamiento")

    if urgency or incumplimiento in {"grave", "total"}:
        pretensiones_secundarias.append("alimentos provisorios desde el inicio")
        medidas.append("solicitar fijacion inmediata de cuota provisoria sin esperar prueba exhaustiva")
    if incumplimiento in {"grave", "total"}:
        pretensiones_secundarias.append("retencion directa o embargo sobre haberes/cuentas")
    if variables.get("deuda_alimentaria"):
        pretensiones_secundarias.append("retroactividad desde la interpelacion fehaciente o desde la demanda")

    fundamentos = [
        f"En foro de familia de Jujuy conviene entrar con una cuota cuantificable desde el primer escrito; aqui la referencia util es {porcentaje}.",
        _format_income_foundation(variables),
        _format_child_foundation(variables),
        _format_coexistence_foundation(coexistence),
        _format_noncompliance_foundation(incumplimiento, urgency),
    ]

    return {
        "tipo_accion": tipo_accion,
        "estrategia": {
            "pretension_principal": "promover demanda de alimentos con cuantificacion inicial y esquema de cobro verificable",
            "pretensiones_secundarias": [item for item in pretensiones_secundarias if item],
            "nivel_agresividad": _resolve_aggressiveness(
                urgency=urgency,
                incumplimiento=incumplimiento,
                hidden_income=not income_known,
            ),
            "urgencia": urgency,
        },
        "parametros_clave": {
            "porcentaje": porcentaje,
            "medidas": _dedupe(measures := medidas),
        },
        "fundamentos": [item for item in fundamentos if item],
    }


def _build_divorcio_strategy(
    tipo_accion: str,
    variables: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, Any]:
    action_slug = str(classification.get("action_slug") or "").strip()
    unilateral = action_slug == "divorcio_unilateral" or variables.get("sin_acuerdo")
    urgency = bool(variables.get("urgencia"))

    pretension_principal = (
        "promover divorcio unilateral con propuesta reguladora utilizable en Jujuy"
        if unilateral
        else "presentar divorcio con propuesta reguladora cerrada para homologacion temprana"
    )

    pretensiones_secundarias: list[str] = []
    medidas = [
        "acompanar partida de matrimonio y acreditar ultimo domicilio conyugal o centro de vida relevante",
        "ordenar propuesta reguladora sobre vivienda, bienes, cuidado y alimentos si hay hijos",
    ]

    if variables.get("hay_hijos"):
        pretensiones_secundarias.append("definir en la misma presentacion cuidado personal, comunicacion y alimentos")
        medidas.append("adjuntar partidas de nacimiento y base concreta de organizacion familiar")
    if variables.get("conflicto_vivienda"):
        pretensiones_secundarias.append("medida provisoria sobre atribucion del hogar")
    if variables.get("desigualdad_economica"):
        pretensiones_secundarias.append("reservar o acumular compensacion economica")
    if urgency:
        pretensiones_secundarias.append("medidas provisionales urgentes por vivienda, hijos o restriccion de contacto")

    fundamentos = [
        "En practica de familia de Jujuy el divorcio avanza rapido si la propuesta reguladora ya resuelve los frentes utiles y no queda en formulas vacias.",
        "La discusion real no suele estar en la disolucion del vinculo sino en vivienda, hijos y dinero; por eso la estrategia debe cerrar esos puntos desde el inicio.",
        "Si el tramite es unilateral, conviene no abrir narrativa innecesaria sobre culpas y concentrarse en competencia, documental basica y efectos del divorcio.",
    ]

    return {
        "tipo_accion": tipo_accion,
        "estrategia": {
            "pretension_principal": pretension_principal,
            "pretensiones_secundarias": [item for item in pretensiones_secundarias if item],
            "nivel_agresividad": "medio" if unilateral or urgency else "bajo",
            "urgencia": urgency,
        },
        "parametros_clave": {
            "porcentaje": "",
            "medidas": _dedupe(measures := medidas),
        },
        "fundamentos": fundamentos,
    }


def _build_cuidado_personal_strategy(tipo_accion: str, variables: dict[str, Any]) -> dict[str, Any]:
    urgency = bool(variables.get("urgencia"))
    obstruction = variables.get("obstruccion_vinculo")
    coexistence = variables.get("convivencia")

    if coexistence == "actor":
        principal = "pedir cuidado personal unilateral con mantenimiento del centro de vida actual"
    elif coexistence == "alternada":
        principal = "ordenar cuidado personal compartido con plan concreto de alternancia"
    else:
        principal = "definir judicialmente cuidado personal con eje en centro de vida y estabilidad cotidiana del hijo"

    pretensiones_secundarias = [
        "regimen de comunicacion claro y ejecutable",
    ]
    if urgency:
        pretensiones_secundarias.append("medida cautelar inmediata para evitar cambios de escuela, domicilio o retencion del hijo")
    if variables.get("hay_alimentos_pendientes"):
        pretensiones_secundarias.append("alimentos provisorios conexos al cuidado")

    medidas = [
        "acompanar certificados escolares, medicos y toda constancia del centro de vida en Jujuy",
        "ofrecer testigos de rutina diaria, retiros escolares y cuidado efectivo",
        "pedir informe socioambiental si la disputa es fuerte sobre condiciones de crianza",
    ]
    if obstruction:
        medidas.append("documentar impedimentos de contacto con mensajes, denuncias o constancias policiales")
    if variables.get("riesgo_psicofisico"):
        medidas.append("requerir intervencion interdisciplinaria y entrevista temprana del nino si la edad lo permite")

    fundamentos = [
        "En familia Jujuy pesa mas la prueba de quien sostiene la rutina real del nino que los planteos abstractos sobre mejor aptitud parental.",
        _format_coexistence_foundation(coexistence),
        "La estrategia debe fijar un esquema operativo de entregas, escuela y salud; sin eso el conflicto reaparece en cada incidente.",
    ]
    if obstruction:
        fundamentos.append("Si hay obstruccion de vinculo, conviene documentarla y pedir un regimen con apercibimientos concretos, no solo una formula abierta.")

    return {
        "tipo_accion": tipo_accion,
        "estrategia": {
            "pretension_principal": principal,
            "pretensiones_secundarias": [item for item in pretensiones_secundarias if item],
            "nivel_agresividad": "alto" if urgency or obstruction else "medio",
            "urgencia": urgency,
        },
        "parametros_clave": {
            "porcentaje": "",
            "medidas": _dedupe(measures := medidas),
        },
        "fundamentos": [item for item in fundamentos if item],
    }


def _build_fallback_strategy(tipo_accion: str, variables: dict[str, Any]) -> dict[str, Any]:
    urgency = bool(variables.get("urgencia"))
    return {
        "tipo_accion": tipo_accion or "indefinida",
        "estrategia": {
            "pretension_principal": "delimitar primero la accion y los hechos litigiosos antes de redactar cualquier pieza",
            "pretensiones_secundarias": ["cerrar prueba minima y competencia efectiva en Jujuy"],
            "nivel_agresividad": "medio" if urgency else "bajo",
            "urgencia": urgency,
        },
        "parametros_clave": {
            "porcentaje": "",
            "medidas": [
                "ordenar hechos cronologicos y variables economicas o familiares relevantes",
                "definir si el conflicto principal es de alimentos, divorcio o cuidado personal",
            ],
        },
        "fundamentos": [
            "Sin accion bien tipificada, cualquier escrito sale defectuoso o se llena de planteos mezclados.",
            "La practica util exige cerrar primero pretension, prueba y urgencia antes de pasar a redaccion.",
        ],
    }


def _detect_variables(
    *,
    query: str,
    facts: dict[str, Any],
    classification: dict[str, Any],
    case_structure: dict[str, Any],
    normative_reasoning: dict[str, Any],
    procedural_strategy: dict[str, Any],
    question_engine_result: dict[str, Any],
    conflict_evidence: dict[str, Any],
) -> dict[str, Any]:
    variables = _coerce_mapping(facts.get("variables_detectadas"))
    facts_text = _join_values(facts)
    text = _normalize_text(
        " ".join(
            [
                query,
                facts_text,
                _join_values(classification),
                _join_values(case_structure),
                _join_values(normative_reasoning),
                _join_values(procedural_strategy),
                _join_values(question_engine_result),
                _join_values(conflict_evidence),
            ]
        )
    )

    age = _extract_int(
        variables.get("edad_hijo")
        or facts.get("edad_hijo")
        or facts.get("edad")
        or _extract_number_from_text(text, ("anos", "anios"))
    )
    studies = _pick_text(
        variables.get("estudios"),
        facts.get("estudios"),
        "estudiante" if any(token in text for token in ("estudia", "escuela", "colegio", "universidad", "alumno regular")) else "",
    )
    income = _pick_text(
        variables.get("ingresos_demandado"),
        facts.get("ingresos_demandado"),
        facts.get("ingresos"),
    )
    convivencia = _resolve_convivencia(variables, facts, text)
    incumplimientos = _resolve_incumplimiento(variables, facts, text)
    urgencia = _resolve_urgency(variables, facts, text)

    return {
        "ingresos_demandado": income,
        "ingresos_informales": not income and any(token in text for token in ("changas", "informal", "monotrib", "negocio propio", "trabaja por su cuenta")),
        "edad_hijo": age,
        "estudios": studies,
        "convivencia": convivencia,
        "incumplimientos": incumplimientos,
        "urgencia": urgencia,
        "cantidad_hijos": _extract_int(variables.get("cantidad_hijos") or facts.get("cantidad_hijos")) or (2 if "hijos" in text else 1),
        "cuenta_bancaria": bool(variables.get("cbu") or facts.get("cbu") or "cbu" in text),
        "deuda_alimentaria": bool(variables.get("deuda") or any(token in text for token in ("deuda", "meses sin pagar", "retroactivo", "atrasado"))),
        "hay_hijos": any(token in text for token in ("hijo", "hija", "hijos", "nino", "nina")),
        "conflicto_vivienda": any(token in text for token in ("vivienda", "hogar", "casa", "alquiler")),
        "desigualdad_economica": any(token in text for token in ("compensacion economica", "dependencia economica", "sin ingresos propios")),
        "sin_acuerdo": any(token in text for token in ("no hay acuerdo", "no quiere firmar", "se opone", "unilateral")),
        "obstruccion_vinculo": any(token in text for token in ("impide ver", "impedimento de contacto", "no deja ver", "obstruccion")),
        "riesgo_psicofisico": any(token in text for token in ("violencia", "maltrato", "consumo problematico", "riesgo")),
        "hay_alimentos_pendientes": any(token in text for token in ("alimentos", "cuota", "no paga")),
    }


def _resolve_tipo_accion(query: str, facts: dict[str, Any], classification: dict[str, Any]) -> str:
    raw_tipo = _normalize_text(str(facts.get("tipo_accion") or facts.get("accion") or ""))
    action_slug = str(classification.get("action_slug") or "").strip()
    combined = _normalize_text(" ".join([query, raw_tipo, action_slug]))

    if raw_tipo in {"alimentos", "divorcio", "cuidado personal", "cuidado_personal"}:
        return raw_tipo.replace(" ", "_") if raw_tipo == "cuidado personal" else raw_tipo
    if action_slug == "alimentos_hijos" or "alimentos" in combined:
        return "alimentos"
    if action_slug in {"divorcio", "divorcio_unilateral", "divorcio_mutuo_acuerdo"} or "divorcio" in combined:
        return "divorcio"
    if "cuidado personal" in combined or "responsabilidad parental" in combined or "centro de vida" in combined:
        return "cuidado_personal"
    return ""


def _resolve_convivencia(variables: dict[str, Any], facts: dict[str, Any], text: str) -> str:
    raw = _normalize_text(str(
        variables.get("convivencia")
        or facts.get("convivencia")
        or facts.get("con_quien_convive")
        or ""
    ))
    if raw:
        if any(token in raw for token in ("madre", "actora", "actor", "progenitor conviviente")):
            return "actor"
        if any(token in raw for token in ("alternada", "compartida")):
            return "alternada"
        if any(token in raw for token in ("padre", "demandado")):
            return "demandado"
    if any(token in text for token in ("convive con su madre", "vive con su madre", "a cargo de la madre")):
        return "actor"
    if any(token in text for token in ("convive con su padre", "vive con su padre", "a cargo del padre")):
        return "demandado"
    if any(token in text for token in ("cuidado compartido", "convivencia alternada")):
        return "alternada"
    return ""


def _resolve_incumplimiento(variables: dict[str, Any], facts: dict[str, Any], text: str) -> str:
    raw = _normalize_text(str(variables.get("incumplimientos") or facts.get("incumplimientos") or ""))
    if any(token in raw for token in ("total", "grave")):
        return "grave"
    if any(token in raw for token in ("parcial", "irregular")):
        return "parcial"
    if any(token in text for token in ("no paga", "nunca pago", "abandono", "sin aportes", "deuda alimentaria")):
        return "grave"
    if any(token in text for token in ("paga poco", "paga cuando quiere", "aportes irregulares", "pagos parciales")):
        return "parcial"
    return ""


def _resolve_urgency(variables: dict[str, Any], facts: dict[str, Any], text: str) -> bool:
    value = variables.get("urgencia")
    if isinstance(value, bool):
        return value
    if str(facts.get("urgencia") or "").strip().lower() in {"true", "1", "si", "sí"}:
        return True
    return any(
        token in text
        for token in (
            "urgencia",
            "provisorios",
            "provisoria",
            "sin cobertura medica",
            "sin alimentos",
            "embargo",
            "retencion directa",
            "violencia",
            "riesgo",
            "cambio de escuela",
        )
    )


def _resolve_aggressiveness(*, urgency: bool, incumplimiento: str, hidden_income: bool) -> str:
    if urgency and (incumplimiento == "grave" or hidden_income):
        return "alto"
    if urgency or incumplimiento in {"grave", "parcial"}:
        return "medio"
    return "bajo"


def _format_income_foundation(variables: dict[str, Any]) -> str:
    income = variables.get("ingresos_demandado")
    if income:
        return f"Hay dato util sobre ingresos del demandado ({income}); eso permite pedir porcentaje sobre haberes y no una formula abierta."
    if variables.get("ingresos_informales"):
        return "No hay ingreso formal cerrado, pero aparecen indicios de actividad informal; conviene pedir piso sobre SMVM y abrir informativas patrimoniales."
    return "No hay ingreso acreditado del demandado; en Jujuy eso obliga a entrar con piso provisorio y bateria de oficios patrimoniales desde el inicio."


def _format_child_foundation(variables: dict[str, Any]) -> str:
    age = variables.get("edad_hijo")
    studies = variables.get("estudios")
    if age and studies:
        return f"La situacion del hijo no es abstracta: tiene {age} anos y surge actividad educativa ({studies}), dato util para sostener cuota y gastos conexos."
    if age:
        return f"La edad del hijo ({age} anos) impacta directamente en cuantificacion, escolaridad y urgencia del reclamo."
    if studies:
        return f"Los estudios detectados ({studies}) permiten justificar rubros de escolaridad, transporte y tecnologia."
    return "Todavia falta cerrar edad y situacion educativa del hijo; sin eso la cuota queda subfundada."


def _format_coexistence_foundation(convivencia: str) -> str:
    if convivencia == "actor":
        return "La convivencia aparece cargada del lado reclamante; eso fortalece pedir cuota plena y reembolso de gastos ordinarios."
    if convivencia == "demandado":
        return "La convivencia no queda del lado reclamante; antes de fijar estrategia conviene revisar si la pretension principal debe ser alimentos o cuidado."
    if convivencia == "alternada":
        return "La convivencia alternada obliga a cuantificar con cuidado para no pedir una cuota desconectada del esquema real de cuidado."
    return "La convivencia no esta suficientemente cerrada; ese dato es central para cuantificar alimentos o definir cuidado personal."


def _format_noncompliance_foundation(incumplimiento: str, urgency: bool) -> str:
    if incumplimiento == "grave":
        return "El incumplimiento aparece como sostenido o total; procesalmente conviene combinar cuota provisoria con retencion o embargo y no esperar audiencia larga."
    if incumplimiento == "parcial":
        return "Hay incumplimiento parcial o irregular; eso aconseja fijar monto cierto y mecanismo de cobro para cortar la discrecionalidad del alimentante."
    if urgency:
        return "Aunque el incumplimiento no esta del todo cerrado, la urgencia actual justifica pedir respuesta provisoria inmediata."
    return "No surge aun un incumplimiento claramente tipificado; conviene probar primero modalidad de aportes y gastos cubiertos."


def _coerce_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _join_values(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_join_values(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_join_values(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _normalize_text(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(value or "").lower())
    return " ".join(char for char in "".join(ch for ch in nfkd if not unicodedata.combining(ch)).split())


def _extract_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    return None


def _extract_number_from_text(text: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        match = re.search(rf"(\d{{1,2}})\s+{suffix}", text)
        if match:
            return match.group(1)
    return ""


def _pick_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
