from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


MAX_ACTION_STEPS = 4
MAX_REQUIRED_DOCUMENTS = 6
MAX_LOCAL_NOTES = 3
MAX_PROFESSIONAL_CHECKLIST = 6

ACTION_STARTERS = (
    "iniciar",
    "presentar",
    "reunir",
    "pedir",
    "redactar",
    "ordenar",
    "incluir",
    "verificar",
    "solicitar",
    "acreditar",
    "definir",
    "promover",
    "acompanar",
    "preparar",
    "impulsar",
    "reclamar",
)

DOCUMENT_HINTS = (
    "dni",
    "partida",
    "libreta",
    "acta",
    "escritura",
    "boleto",
    "contrato",
    "recibo",
    "comprobante",
    "certificado",
    "titulo",
    "resumen",
    "constancia",
    "historia clinica",
    "presupuesto",
    "denuncia",
)

PROHIBITED_PHRASES = (
    "necesito un dato",
    "ya hay base suficiente",
    "persisten cuestiones normativas",
    "tengo suficiente para orientarte",
)


def attach_core_legal_response(response: dict[str, Any] | None) -> dict[str, Any]:
    payload = deepcopy(response or {})
    payload["core_legal_response"] = build_core_legal_response(payload)
    return payload


def build_core_legal_response(response: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(response or {})
    case_domain = _clean_text(payload.get("case_domain")).casefold()
    jurisdiction = _clean_text(payload.get("jurisdiction") or "jujuy")
    reasoning = _as_dict(payload.get("reasoning"))
    case_strategy = _as_dict(payload.get("case_strategy"))
    procedural_strategy = _as_dict(payload.get("procedural_strategy"))
    normative_reasoning = _as_dict(payload.get("normative_reasoning"))
    case_profile = _as_dict(payload.get("case_profile"))
    model_match = _as_dict(payload.get("model_match"))
    conversational = _as_dict(payload.get("conversational"))
    known_facts = _as_dict(conversational.get("known_facts"))
    context = _collect_context(
        payload=payload,
        reasoning=reasoning,
        case_strategy=case_strategy,
        case_profile=case_profile,
        known_facts=known_facts,
    )
    practical_domain = _resolve_practical_domain(
        case_domain=case_domain,
        payload=payload,
        context=context,
    )
    context["practical_domain"] = practical_domain
    focus_profile = _resolve_focus_profile(case_domain=practical_domain, context=context)
    context["primary_focus"] = focus_profile["primary_focus"]
    context["secondary_focuses"] = focus_profile["secondary_focuses"]
    context["focus_reason"] = focus_profile["focus_reason"]

    direct_answer = _build_direct_answer(
        case_domain=practical_domain,
        jurisdiction=jurisdiction,
        reasoning=reasoning,
        case_strategy=case_strategy,
        context=context,
    )
    action_steps = _build_action_steps(
        case_domain=practical_domain,
        jurisdiction=jurisdiction,
        payload=payload,
        case_strategy=case_strategy,
        procedural_strategy=procedural_strategy,
        context=context,
    )
    required_documents = _build_required_documents(
        case_domain=practical_domain,
        payload=payload,
        case_strategy=case_strategy,
        procedural_strategy=procedural_strategy,
        case_profile=case_profile,
        context=context,
    )
    local_practice_notes = _build_local_practice_notes(
        jurisdiction=jurisdiction,
        case_domain=practical_domain,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        context=context,
    )
    professional_frame = _build_professional_frame(
        case_domain=practical_domain,
        case_strategy=case_strategy,
        procedural_strategy=procedural_strategy,
        case_profile=case_profile,
        model_match=model_match,
        required_documents=required_documents,
        action_steps=action_steps,
        context=context,
    )
    optional_clarification = _build_optional_clarification(
        payload=payload,
        case_domain=practical_domain,
        jurisdiction=jurisdiction,
        context=context,
    )

    return {
        "direct_answer": _strip_prohibited_phrases(direct_answer),
        "action_steps": [_strip_prohibited_phrases(item) for item in action_steps][:MAX_ACTION_STEPS],
        "required_documents": [_strip_prohibited_phrases(item) for item in required_documents][:MAX_REQUIRED_DOCUMENTS],
        "local_practice_notes": [_strip_prohibited_phrases(item) for item in local_practice_notes][:MAX_LOCAL_NOTES],
        "professional_frame": professional_frame,
        "optional_clarification": _strip_prohibited_phrases(optional_clarification) or None,
        "focus_trace": {
            **focus_profile,
            "practical_domain": practical_domain,
        },
    }


def _build_direct_answer(
    *,
    case_domain: str,
    jurisdiction: str,
    reasoning: dict[str, Any],
    case_strategy: dict[str, Any],
    context: dict[str, Any],
) -> str:
    lead = _first_nonempty_text(
        reasoning.get("short_answer"),
        case_strategy.get("strategic_narrative"),
    )
    lead = _to_user_text(_first_sentences(lead, limit=2))
    local_process = _resolve_local_process_guide(
        case_domain=case_domain,
        jurisdiction=jurisdiction,
        context=context,
    )

    if case_domain == "divorcio":
        focus = context.get("primary_focus")
        opening = lead or (
            "El divorcio puede iniciarse aunque no haya acuerdo de la otra parte, y lo importante es ordenar bien la presentacion inicial."
        )
        if focus == "protection_urgency":
            lines = [
                opening,
                "En este caso el eje no es solo el divorcio: primero hay que resolver la urgencia o la proteccion necesaria para evitar que el conflicto siga perjudicando a la persona o a los hijos.",
                "Si hay violencia, impedimento de contacto grave, falta alimentaria urgente o un bebe recien nacido, conviene pensar primero en medidas inmediatas y recien despues completar el resto de los efectos del divorcio.",
                "La presentacion deberia entrar por ese riesgo prioritario y, en paralelo, dejar ordenados cuidado personal, comunicacion, alimentos o resguardo de vivienda segun corresponda.",
            ]
        elif focus == "children":
            lines = [
                opening,
                "En tu caso, lo mas importante no es solo presentar el divorcio, sino definir como se van a organizar cuidado personal, comunicacion y alimentos de los hijos.",
                "Eso impacta directamente en como conviene armar la propuesta reguladora o la presentacion inicial, porque el eje hijos no deberia quedar relegado detras de vivienda o bienes.",
                "Por eso el primer movimiento util es preparar una propuesta minima sobre esos puntos y recien despues completar lo patrimonial que tambien haga falta.",
            ]
        elif focus == "housing":
            lines = [
                opening,
                "En este escenario el punto dominante es la vivienda, porque definir quien sigue usando el hogar y con que respaldo puede cambiar el modo de presentar el caso.",
                "Conviene separar el pedido de divorcio de la discusion sobre uso de la vivienda y reunir la documentacion que permita sostener ese planteo sin dejarlo en una afirmacion vaga.",
                "Si ademas hay hijos o bienes, esos puntos siguen presentes, pero deberian quedar ordenados despues del conflicto habitacional principal.",
            ]
        elif focus == "property":
            lines = [
                opening,
                "En este escenario el punto que mas ordena el caso es definir como vas a tratar vivienda y bienes dentro de los efectos del divorcio.",
                "Conviene separar que parte del conflicto es estrictamente familiar y que parte requiere respaldo patrimonial, para no mezclar reclamos ni dejar floja la documentacion.",
                "La presentacion inicial deberia mostrar con claridad si ese punto va a discutirse ahora, si se reserva o si ya existe alguna base documental para sostenerlo.",
            ]
        else:
            lines = [
                opening,
                "Conviene definir desde el inicio si la presentacion sera conjunta o unilateral y dejar cubiertos los efectos practicos del caso.",
                "El objetivo no es solo pedir el divorcio, sino armar una presentacion que no deje vacios sobre los puntos que despues suelen trabar el expediente.",
            ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        lines.extend(_build_secondary_focus_lines(context))
        if context["domicile_known"]:
            lines.append(
                f"El dato de domicilio ya sirve para ubicar mejor la competencia y preparar la presentacion en {jurisdiction.title()} con menos riesgo de observaciones."
            )
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain == "alimentos":
        opening = lead or (
            "El reclamo de alimentos puede orientarse aunque todavia no este completa toda la informacion economica."
        )
        lines = [
            opening,
            "Lo practico es ordenar desde ahora quien convive con el nino o la nina, cuales son las necesidades actuales y que datos tenes para estimar ingresos o capacidad economica.",
            "Con esa base ya se puede preparar un reclamo util y despues ajustar monto, prueba y urgencia con mas precision.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        if context["has_children"]:
            lines.append(
                "Si hay un hijo o hija menor, conviene enlazar alimentos con cuidado personal y regimen de comunicacion cuando ese punto tambien este en conflicto."
            )
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain == "cuidado_personal":
        opening = lead or (
            "El cuidado personal puede orientarse aunque todavia falten algunos detalles del conflicto familiar."
        )
        lines = [
            opening,
            "Lo primero es definir con quien convive hoy el nino o la nina, que rutina de cuidado existe y que cambio concreto queres pedir al juzgado.",
            "Con esa base ya se puede preparar un planteo util sobre centro de vida, organizacion cotidiana y, si hace falta, enlazarlo con alimentos o comunicacion.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        if context.get("protection_urgency"):
            lines.append(
                "Si hay urgencia, riesgo o conflicto grave, conviene entrar primero por proteccion o medidas provisorias y despues completar la discusion principal."
            )
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain in {"regimen_comunicacional", "regimen de comunicacion"}:
        opening = lead or (
            "El regimen de comunicacion puede ordenarse aunque todavia no este cerrada toda la situacion familiar."
        )
        lines = [
            opening,
            "Lo importante es mostrar como esta hoy el contacto con el nino o la nina, que obstaculos existen y que esquema concreto queres pedir.",
            "Con esa base ya se puede preparar un planteo util sobre frecuencia, modalidad, dias y resguardos necesarios para que el contacto funcione en la practica.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        if context.get("protection_urgency"):
            lines.append(
                "Si hay impedimento de contacto, riesgo o un conflicto que afecta directamente al nino o la nina, conviene tratarlo con criterio urgente."
            )
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain in {"violencia", "violencia_familiar"}:
        opening = lead or (
            "En un caso de violencia, lo prioritario no es profundizar la conversacion sino ordenar una respuesta de proteccion util e inmediata."
        )
        lines = [
            opening,
            "Lo primero es identificar el riesgo actual, que medida de proteccion hace falta y que respaldo minimo existe para sostenerla.",
            "Aunque despues haya que ampliar hechos o prueba, ya se puede orientar una presentacion inicial con foco en resguardo, urgencia y documentacion basica.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain == "sucesion":
        opening = lead or (
            "La sucesion puede iniciarse cuando ya esta ordenada la documentacion basica del fallecimiento y del parentesco."
        )
        lines = [
            opening,
            "Lo central es acreditar quien fallecio, quienes son las personas con vocacion hereditaria y cuales son los bienes que vale la pena denunciar primero.",
            "Aunque falten detalles sobre todo el patrimonio, ya se puede avanzar con una apertura bien armada y completar informacion despues.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain == "civil_cobro":
        opening = lead or (
            "Si te deben dinero o hubo un incumplimiento contractual, ya se puede ordenar un reclamo civil inicial aunque falten algunos detalles."
        )
        lines = [
            opening,
            "Lo importante es identificar de donde nace la deuda, que respaldo documental tenes y si el incumplimiento ya puede reclamarse sin esperar mas.",
            "Con esa base se puede definir si conviene intimar primero, reclamar cumplimiento o preparar una demanda de cobro con prueba minima suficiente.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain == "civil_danos":
        opening = lead or (
            "Si sufriste un dano por accidente o incumplimiento, ya se puede ordenar un reclamo civil aunque todavia no este cerrada toda la cuantificacion."
        )
        lines = [
            opening,
            "Lo central es fijar que hecho produjo el dano, que perjuicios concretos hay y que respaldo tenes para sostener responsabilidad y monto.",
            "Con esa base se puede decidir si conviene intimar, negociar con seguro o preparar una demanda de danos con prueba medica, material o documental suficiente.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        return _compose_paragraph(lines, minimum_lines=3)

    if case_domain == "civil_inmueble":
        opening = lead or (
            "Si el conflicto civil gira alrededor de un inmueble, alquiler o uso de la propiedad, ya se puede bajar una orientacion inicial util."
        )
        lines = [
            opening,
            "Lo importante es definir si el problema es por contrato, ocupacion, pago, restitucion o uso del inmueble, porque eso cambia el tipo de reclamo y la prueba necesaria.",
            "Con esa base se puede decidir si conviene intimar, reclamar cumplimiento, pedir restitucion o preparar una demanda civil con documentacion del inmueble y del vinculo entre las partes.",
        ]
        if local_process.get("overview_line"):
            lines.append(str(local_process["overview_line"]))
        return _compose_paragraph(lines, minimum_lines=3)

    opening = lead or (
        "Con lo disponible ya se puede dar una orientacion juridica inicial util y bajar un primer camino de trabajo."
    )
    lines = [
        opening,
        "El paso mas importante ahora es encuadrar bien el problema, ubicar que juzgado o tramite podria corresponder y reunir la documentacion minima que sostenga lo que vas a pedir.",
        "Aunque falten detalles, igual conviene definir una base de accion para no quedar en respuestas abstractas o demasiado generales.",
    ]
    if context["domicile_known"]:
        lines.append(
            "El domicilio mencionado ayuda a ubicar competencia territorial y puede ordenar mejor el siguiente movimiento procesal."
        )
    return _compose_paragraph(lines, minimum_lines=3)


def _build_action_steps(
    *,
    case_domain: str,
    jurisdiction: str,
    payload: dict[str, Any],
    case_strategy: dict[str, Any],
    procedural_strategy: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    quick_start = _strip_known_prefix(
        _clean_text(payload.get("quick_start")),
        "Primer paso recomendado:",
    )
    local_process = _resolve_local_process_guide(
        case_domain=case_domain,
        jurisdiction=jurisdiction,
        context=context,
    )
    candidates = [
        quick_start,
        *_as_str_list(case_strategy.get("recommended_actions")),
        *_as_str_list(procedural_strategy.get("next_steps")),
        *_as_str_list(case_strategy.get("procedural_focus")),
    ]
    normalized_candidates = [
        _normalize_action_sentence(_to_user_text(item))
        for item in candidates
        if _looks_like_action(item)
    ]

    defaults: list[str] = []
    local_first_step = _clean_text(local_process.get("first_step"))
    if local_first_step:
        defaults.append(local_first_step)
    if case_domain == "divorcio":
        focus = context.get("primary_focus")
        defaults.append("Reunir DNI, acta o libreta de matrimonio y domicilios de ambas partes.")
        if focus == "protection_urgency":
            defaults.extend([
                "Definir cual es la medida mas urgente: proteccion, cuidado provisorio, alimentos urgentes o resguardo de contacto, segun el riesgo concreto.",
                "Reunir denuncias, constancias medicas, mensajes, comprobantes de gastos urgentes o cualquier respaldo que muestre por que el caso no puede esperar.",
                "Preparar una presentacion que entre primero por la urgencia y deje ordenados despues los efectos generales del divorcio.",
            ])
        elif focus == "children":
            defaults.extend([
                "Definir una propuesta concreta sobre cuidado personal, comunicacion y alimentos de los hijos.",
                "Reunir partidas de nacimiento y cualquier antecedente util sobre gastos, salud o rutina de cuidado.",
                "Preparar la presentacion inicial o la propuesta reguladora haciendo entrar primero el eje hijos y despues vivienda o bienes si tambien estan en juego.",
            ])
        elif focus == "housing":
            defaults.extend([
                "Ordenar quien vive hoy en la vivienda, con quien conviven los hijos y que respaldo hay para sostener un pedido sobre uso del hogar.",
                "Reunir escritura, contrato, boleto, recibos o constancias que permitan explicar la situacion habitacional.",
                "Preparar la presentacion diferenciando el pedido de divorcio del conflicto por vivienda para no mezclar fundamentos.",
            ])
        elif focus == "property":
            defaults.extend([
                "Ordenar escritura, boleto, contrato o constancias de vivienda y bienes para decidir que conviene discutir en esta etapa.",
                "Definir si el conflicto patrimonial va dentro de los efectos del divorcio o si conviene reservarlo con una estrategia separada.",
                "Preparar la presentacion inicial dejando claro como se ubican vivienda, bienes y competencia.",
            ])
        else:
            defaults.append("Preparar la presentacion inicial o la propuesta reguladora con los efectos del divorcio bien ordenados.")
        defaults.extend(_build_secondary_focus_steps(context))
        if context["has_property"] or context["mentions_home"]:
            defaults.append("Ordenar la documentacion de vivienda o bienes para decidir si conviene incluir ese punto desde el inicio.")
    elif case_domain == "alimentos":
        defaults.extend([
            "Reunir comprobantes de gastos del hijo o hija y toda constancia util sobre ingresos o capacidad economica de la otra parte.",
            "Ordenar quien convive actualmente con el nino o la nina y desde cuando existe esa situacion.",
            "Preparar el reclamo inicial con una base clara sobre necesidades, posibilidades y urgencia.",
        ])
    elif case_domain == "cuidado_personal":
        defaults.extend([
            "Ordenar con quien convive hoy el nino o la nina, desde cuando y que cambio concreto queres pedir.",
            "Reunir partidas, constancias escolares, medicas o de rutina que ayuden a sostener centro de vida y cuidado cotidiano.",
            "Preparar una presentacion inicial que deje claros cuidado pedido, urgencia y organizacion practica.",
        ])
    elif case_domain in {"regimen_comunicacional", "regimen de comunicacion"}:
        defaults.extend([
            "Ordenar como es hoy el contacto con el nino o la nina y que obstaculo concreto queres resolver.",
            "Reunir mensajes, constancias o antecedentes que muestren incumplimientos, impedimentos o necesidad de fijar un esquema claro.",
            "Preparar un pedido con dias, modalidad y frecuencia de comunicacion que sea practicable.",
        ])
    elif case_domain in {"violencia", "violencia_familiar"}:
        defaults.extend([
            "Definir que medida de proteccion necesitas pedir y por que el caso requiere intervencion inmediata.",
            "Reunir denuncias, certificados, mensajes, fotos o cualquier respaldo minimo del riesgo actual.",
            "Preparar una presentacion inicial enfocada en resguardo urgente antes de ampliar otros conflictos derivados.",
        ])
    elif case_domain == "sucesion":
        defaults.extend([
            "Reunir partida de defuncion, partidas que acrediten parentesco y datos basicos del grupo familiar.",
            "Hacer un primer listado de bienes, cuentas o inmuebles que valga la pena denunciar.",
            "Preparar la presentacion inicial de la sucesion con la documentacion basica ya ordenada.",
        ])
    elif case_domain == "civil_cobro":
        defaults.extend([
            "Ordenar de donde nace la deuda o el incumplimiento: contrato, prestamo, factura, recibo, transferencia o reconocimiento.",
            "Reunir contrato, presupuesto, mensajes, recibos, transferencias o cualquier documento que permita probar la obligacion reclamada.",
            "Definir si conviene intimar primero o preparar directamente el reclamo judicial segun el respaldo y la exigibilidad de la deuda.",
        ])
    elif case_domain == "civil_danos":
        defaults.extend([
            "Ordenar el hecho danos o accidente con fecha, lugar, personas intervinientes y perjuicios concretos.",
            "Reunir fotos, presupuesto, denuncia, certificado medico, historia clinica, testigos o constancias del seguro segun el caso.",
            "Definir si conviene intimar, reclamar al seguro o preparar una demanda de danos con base documental suficiente.",
        ])
    elif case_domain == "civil_inmueble":
        defaults.extend([
            "Ordenar si el conflicto es por alquiler, ocupacion, restitucion, pago o uso del inmueble.",
            "Reunir contrato, escritura, boleto, recibos, intimaciones o constancias de posesion segun el problema concreto.",
            "Definir si conviene intimar, reclamar cumplimiento o preparar una presentacion civil centrada en el inmueble.",
        ])
    else:
        defaults.extend([
            "Ordenar los hechos principales con fechas, personas involucradas y el problema concreto que queres resolver.",
            "Reunir la documentacion que pruebe lo que paso y sirva para sostener el reclamo o la defensa.",
            "Definir si conviene iniciar un tramite, presentar un reclamo o intimar primero segun el problema planteado.",
        ])

    if context["domicile_known"]:
        defaults.append(
            f"Verificar si el domicilio relevante alcanza para sostener competencia territorial en {jurisdiction.title()}."
        )

    return _dedupe_texts([*normalized_candidates, *defaults])[:MAX_ACTION_STEPS]


def _build_required_documents(
    *,
    case_domain: str,
    payload: dict[str, Any],
    case_strategy: dict[str, Any],
    procedural_strategy: dict[str, Any],
    case_profile: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    explicit_sources = [
        *_as_str_list(procedural_strategy.get("missing_information") or procedural_strategy.get("missing_info")),
        *_as_str_list(case_strategy.get("ordinary_missing_information")),
        *_as_str_list(case_strategy.get("critical_missing_information")),
        *_as_str_list(case_profile.get("missing_information")),
        *_as_str_list(_as_dict(payload.get("conflict_evidence")).get("missing_evidence")),
        *_as_str_list(_as_dict(payload.get("case_theory")).get("evidence_needed")),
    ]

    documents = [
        _normalize_document_item(item)
        for item in explicit_sources
        if _looks_document_related(item)
    ]

    if case_domain == "divorcio":
        documents.extend([
            "DNI de quien consulta y, si lo tenes, datos de la otra parte.",
            "Acta o libreta de matrimonio.",
        ])
        if context["domicile_known"] or context["mentions_home"]:
            documents.append("Constancias de domicilio o cualquier documento que ayude a fijar competencia y situacion de vivienda.")
        if context["has_children"]:
            documents.extend([
                "Partidas de nacimiento de los hijos.",
                "Comprobantes de gastos, salud, cuidado o ingresos vinculados a los hijos.",
            ])
        if context.get("primary_focus") == "protection_urgency":
            documents.append("Denuncias, certificados medicos, mensajes, constancias de incumplimiento o cualquier prueba que muestre la urgencia actual.")
        if context["has_property"] or context["mentions_home"]:
            documents.append("Escritura, boleto, contrato o constancia util sobre la vivienda o bienes en discusion.")
    elif case_domain == "alimentos":
        documents.extend([
            "DNI y partida de nacimiento del hijo o hija.",
            "Comprobantes de gastos de alimentacion, salud, educacion, transporte o cuidado.",
            "Recibos, constancias o datos utiles sobre ingresos de la otra parte.",
        ])
    elif case_domain == "cuidado_personal":
        documents.extend([
            "DNI y partida de nacimiento del nino o la nina.",
            "Constancias de domicilio, escolaridad, salud o rutina que ayuden a mostrar centro de vida y cuidado cotidiano.",
            "Mensajes, acuerdos previos o cualquier documento que muestre como viene funcionando el cuidado hasta ahora.",
        ])
    elif case_domain in {"regimen_comunicacional", "regimen de comunicacion"}:
        documents.extend([
            "DNI y partida de nacimiento del nino o la nina.",
            "Mensajes, acuerdos, denuncias o constancias utiles sobre impedimentos, incumplimientos o modalidad actual de contacto.",
            "Cualquier antecedente que permita proponer un esquema concreto de comunicacion.",
        ])
    elif case_domain in {"violencia", "violencia_familiar"}:
        documents.extend([
            "DNI de quien consulta y todo dato de identificacion de la otra parte que ya tengas.",
            "Denuncias, certificados medicos, mensajes, fotos o constancias que respalden el riesgo actual.",
            "Cualquier documento que ayude a ubicar domicilio, convivencia o necesidad de proteccion inmediata.",
        ])
    elif case_domain == "sucesion":
        documents.extend([
            "Partida de defuncion del causante.",
            "Partidas o documentos que acrediten parentesco.",
            "Primeras constancias de bienes: escritura, cedula, resumen o informe que permita denunciarlos.",
        ])
    elif case_domain == "civil_cobro":
        documents.extend([
            "Contrato, presupuesto, factura, recibo, pagaré, transferencia o documento que muestre de donde nace la deuda.",
            "Mensajes, intimaciones, reconocimiento de deuda o cualquier constancia del incumplimiento.",
            "DNI y datos de la persona o empresa a la que pensas reclamar.",
        ])
    elif case_domain == "civil_danos":
        documents.extend([
            "Fotos, denuncia, presupuesto, factura o constancia del dano material.",
            "Certificados medicos, estudios, historia clinica o constancias de lesiones si hubo dano personal.",
            "Datos de seguro, patente, intervinientes o testigos si el hecho los involucra.",
        ])
    elif case_domain == "civil_inmueble":
        documents.extend([
            "Contrato de alquiler, escritura, boleto o documento que explique el vinculo con el inmueble.",
            "Recibos, intimaciones, mensajes o constancias de pago, ocupacion o incumplimiento.",
            "Datos del inmueble y de las personas involucradas en el conflicto.",
        ])
    else:
        documents.extend([
            "DNI y cualquier constancia que identifique a las partes involucradas.",
            "Documentos, contratos, recibos, mensajes o comprobantes vinculados al problema.",
        ])

    return _dedupe_texts(documents)[:MAX_REQUIRED_DOCUMENTS]


def _build_local_practice_notes(
    *,
    jurisdiction: str,
    case_domain: str,
    normative_reasoning: dict[str, Any],
    procedural_strategy: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    jurisdiction_key = jurisdiction.casefold()
    local_process = _resolve_local_process_guide(
        case_domain=case_domain,
        jurisdiction=jurisdiction,
        context=context,
    )
    notes.extend(_as_str_list(local_process.get("notes")))

    if jurisdiction_key == "jujuy":
        if case_domain == "divorcio":
            focus = context.get("primary_focus")
            if focus == "protection_urgency":
                notes.append(
                    "En Jujuy, si el caso trae urgencia o proteccion, conviene que la presentacion ya muestre con claridad el riesgo actual y el pedido inmediato, en lugar de esconderlo dentro de un divorcio generico."
                )
            else:
                notes.append(
                    "En Jujuy suele convenir presentar el divorcio con la propuesta reguladora ya trabajada, sobre todo si hay hijos, vivienda o bienes."
                )
            if focus == "children":
                notes.append(
                    "Cuando hay hijos, en la practica local ayuda mucho que la presentacion ya traiga cuidado personal, comunicacion y alimentos con un minimo de detalle util."
                )
            elif focus == "housing":
                notes.append(
                    "Si la vivienda es el eje mas sensible, conviene llegar con constancias claras sobre ocupacion, convivencia y respaldo documental del inmueble."
                )
            elif focus == "property":
                notes.append(
                    "Si el punto sensible es vivienda o bienes, conviene llegar con respaldo documental claro para no dejar ese eje en afirmaciones sueltas."
                )
        elif case_domain == "alimentos":
            notes.append(
                "En Jujuy suele ayudar que el reclamo ya llegue con gastos concretos, datos de convivencia y alguna base para ubicar ingresos o capacidad economica."
            )
        elif case_domain == "cuidado_personal":
            notes.append(
                "En Jujuy suele ayudar que el planteo de cuidado personal ya entre con una descripcion concreta de convivencia, centro de vida y rutina del nino o la nina."
            )
        elif case_domain in {"regimen_comunicacional", "regimen de comunicacion"}:
            notes.append(
                "En Jujuy suele ser util que el pedido de comunicacion ya proponga dias, modalidad y resguardos concretos en lugar de una formula abierta."
            )
        elif case_domain in {"violencia", "violencia_familiar"}:
            notes.append(
                "En Jujuy, cuando hay violencia o riesgo actual, conviene priorizar medidas de proteccion y respaldo basico del hecho antes de ampliar otros efectos del conflicto."
            )
        elif case_domain == "sucesion":
            notes.append(
                "En la practica local la sucesion avanza mejor cuando fallecimiento, parentesco y primeros bienes ya estan ordenados desde el inicio."
            )
        elif case_domain == "civil_cobro":
            notes.append(
                "En Jujuy, en reclamos civiles de cobro o incumplimiento, conviene llegar con un documento claro de la deuda y una base minima sobre exigibilidad."
            )
        elif case_domain == "civil_danos":
            notes.append(
                "En Jujuy, en danos y perjuicios, conviene llegar con prueba del hecho, del dano y de la vinculacion entre ambos, no solo con una descripcion general."
            )
        elif case_domain == "civil_inmueble":
            notes.append(
                "En Jujuy, si el conflicto gira sobre inmueble o alquiler, conviene llegar con contrato o titulo y con la ubicacion del bien claramente identificada."
            )
        else:
            notes.append(
                "En Jujuy conviene ubicar temprano fuero, competencia territorial y documentacion basica para evitar observaciones evitables."
            )

    for item in _as_str_list(normative_reasoning.get("key_points")):
        if any(
            token in _normalize_text(item)
            for token in ("jujuy", "juzgado", "competencia", "presentacion", "documentacion")
        ):
            notes.append(_normalize_note(item))

    for item in _as_str_list(procedural_strategy.get("risks")):
        if any(
            token in _normalize_text(item)
            for token in ("competencia", "presentacion", "documentacion", "observacion")
        ):
            notes.append(_normalize_note(item))

    clean_notes = [
        note for note in _dedupe_texts(notes)
        if note and not _looks_generic_note(note)
    ]
    return clean_notes[:MAX_LOCAL_NOTES]


def _build_professional_frame(
    *,
    case_domain: str,
    case_strategy: dict[str, Any],
    procedural_strategy: dict[str, Any],
    case_profile: dict[str, Any],
    model_match: dict[str, Any],
    required_documents: list[str],
    action_steps: list[str],
    context: dict[str, Any],
) -> dict[str, Any]:
    local_process = _resolve_local_process_guide(
        case_domain=case_domain,
        jurisdiction="jujuy",
        context=context,
    )
    checklist = _dedupe_texts([
        *action_steps,
        *_as_str_list(case_strategy.get("procedural_focus")),
        *_as_str_list(case_strategy.get("recommended_actions")),
        *required_documents,
    ])[:MAX_PROFESSIONAL_CHECKLIST]

    drafting_points = _dedupe_texts([
        *_as_str_list(case_profile.get("strategic_focus")),
        *_as_str_list(case_strategy.get("conflict_summary")),
        "Ordenar hechos, competencia, prueba y petitorio con criterio de utilidad procesal.",
    ])[:4]

    strategy = _first_nonempty_text(
        case_strategy.get("strategic_narrative"),
        procedural_strategy.get("summary"),
    )

    if case_domain == "divorcio" and context.get("primary_focus") == "protection_urgency":
        strategy = _first_nonempty_text(
            "La estrategia deberia entrar por urgencia o proteccion, y despues ordenar divorcio, hijos, vivienda o bienes segun el riesgo actual del caso.",
            strategy,
        )
    elif case_domain == "divorcio" and context.get("primary_focus") == "children":
        strategy = _first_nonempty_text(
            "La estrategia deberia entrar por divorcio y efectos, priorizando hijos: cuidado personal, comunicacion y alimentos antes que vivienda o bienes.",
            strategy,
        )
    elif case_domain == "divorcio" and context.get("primary_focus") == "housing":
        strategy = _first_nonempty_text(
            "La estrategia deberia ubicar primero el conflicto de vivienda, sin perder de vista hijos, competencia y el resto de los efectos del divorcio.",
            strategy,
        )
    elif case_domain == "divorcio" and context.get("primary_focus") == "property":
        strategy = _first_nonempty_text(
            "La estrategia deberia ordenar primero como se acreditan vivienda y bienes, sin perder de vista que siguen siendo efectos del divorcio y no un conflicto aislado.",
            strategy,
        )
    elif case_domain == "civil_cobro":
        strategy = _first_nonempty_text(
            "La estrategia deberia fijar origen de la deuda, exigibilidad, respaldo documental y si conviene intimacion previa o demanda directa.",
            strategy,
        )
    elif case_domain == "civil_danos":
        strategy = _first_nonempty_text(
            "La estrategia deberia entrar por hecho, responsabilidad, dano y prueba concreta antes de discutir monto fino.",
            strategy,
        )
    elif case_domain == "civil_inmueble":
        strategy = _first_nonempty_text(
            "La estrategia deberia aclarar si el conflicto es contractual, posesoria o de uso del inmueble, y sostenerlo con documentacion del bien y del vinculo.",
            strategy,
        )

    return {
        "case_domain": case_domain,
        "strategy": _to_user_text(strategy),
        "primary_focus": _clean_text(context.get("primary_focus")),
        "secondary_focuses": _as_str_list(context.get("secondary_focuses")),
        "practical_domain_label": _practical_domain_label(case_domain),
        "checklist": checklist,
        "drafting_points": drafting_points,
        "forum_hint": _clean_text(local_process.get("forum_hint")),
        "filing_shape": _clean_text(local_process.get("filing_shape")),
        "next_move": checklist[0] if checklist else "",
        "model_hint": _clean_text(
            model_match.get("selected_model_name")
            or _as_dict(model_match.get("selected_model")).get("name")
            or model_match.get("selected_model_id")
        ),
    }


def _build_optional_clarification(
    *,
    payload: dict[str, Any],
    case_domain: str,
    jurisdiction: str,
    context: dict[str, Any],
) -> str | None:
    conversational = _as_dict(payload.get("conversational"))
    raw_question = _clean_text(conversational.get("question"))
    if raw_question:
        return _humanize_question(raw_question)

    question_engine_result = _as_dict(payload.get("question_engine_result"))
    questions = question_engine_result.get("questions")
    if isinstance(questions, list):
        for item in questions:
            candidate = _clean_text(item.get("question") if isinstance(item, dict) else item)
            if candidate:
                return _humanize_question(candidate)

    if case_domain == "divorcio" and not context["children_defined"]:
        return "Hay hijos menores o con necesidad de regular cuidado, comunicacion o alimentos?"
    if case_domain == "alimentos" and not context["income_defined"]:
        return "Tenes algun dato concreto sobre ingresos o trabajo de la otra parte?"
    if case_domain in {"cuidado_personal", "regimen_comunicacional", "regimen de comunicacion"} and not context["children_defined"]:
        return "Con quien convive hoy el nino o la nina y que cambio concreto queres pedir?"
    if case_domain in {"violencia", "violencia_familiar"}:
        return "Hay una urgencia actual o una medida de proteccion que necesites pedir de inmediato?"
    if _normalize_text(jurisdiction) == "jujuy":
        return None
    if not context["domicile_known"]:
        return "En que ciudad o domicilio principal se desarrolla el problema?"
    return None


def _collect_context(
    *,
    payload: dict[str, Any],
    reasoning: dict[str, Any],
    case_strategy: dict[str, Any],
    case_profile: dict[str, Any],
    known_facts: dict[str, Any],
) -> dict[str, Any]:
    text_blob = " ".join([
        _clean_text(payload.get("query")),
        _clean_text(payload.get("response_text")),
        _clean_text(reasoning.get("short_answer")),
        _clean_text(reasoning.get("case_analysis")),
        _clean_text(case_strategy.get("strategic_narrative")),
        " ".join(_as_str_list(case_strategy.get("conflict_summary"))),
        " ".join(_as_str_list(case_strategy.get("recommended_actions"))),
        " ".join(_as_str_list(case_profile.get("strategic_focus"))),
    ])
    normalized = _normalize_text(text_blob)

    hay_hijos_fact = known_facts.get("hay_hijos")
    has_children = bool(hay_hijos_fact) or any(
        token in normalized
        for token in ("hijo", "hija", "hijos", "bebe", "bebé", "menor", "alimentos", "cuidado personal", "regimen comunicacional")
    )
    has_property = any(
        token in normalized
        for token in ("bien", "bienes", "patrimonial", "inmueble", "escritura", "liquidacion", "liquidación", "division de bienes", "división de bienes", "dividir la casa")
    )
    has_housing = any(
        token in normalized
        for token in (
            "vivienda",
            "hogar",
            "atribucion del hogar",
            "atribución del hogar",
            "uso de la vivienda",
            "quedarse en la casa",
            "echar de la casa",
            "sacar de la casa",
            "dividir la casa",
            "donde voy a vivir",
            "dónde voy a vivir",
            "no se donde vivir",
            "no sé dónde vivir",
            "sin casa",
            "techo",
        )
    )
    mentions_home = any(
        token in normalized
        for token in ("vivienda", "hogar", "casa", "domicilio conyugal")
    )
    infant_urgency = any(
        token in normalized
        for token in ("bebe de", "bebé de", "recien nacido", "recién nacido", "3 meses", "2 meses", "1 mes", "lactante")
    )
    protection_urgency = any(
        token in normalized
        for token in (
            "violencia",
            "exclusion del hogar",
            "exclusión del hogar",
            "impedimento de contacto",
            "no deja ver",
            "no me deja ver",
            "retiene al hijo",
            "retiene a la hija",
            "urgente",
            "urgencia",
            "cautelar",
            "sin alimentos",
            "no pasa alimentos",
            "no me pasa plata",
            "no pasa plata",
            "no me da plata",
            "no me manda plata",
            "necesidad alimentaria",
        )
    ) or (has_children and infant_urgency)
    domicile_known = bool(
        known_facts.get("domicilio_relevante")
        or known_facts.get("jurisdiccion")
        or known_facts.get("provincia")
    ) or any(
        token in normalized
        for token in ("jujuy", "salta", "tucuman", "domicilio", "vive en", "ciudad", "provincia")
    )
    divorce_mode = _resolve_divorce_mode(normalized=normalized, known_facts=known_facts)
    children_defined = "sin hijos" in normalized or has_children
    income_defined = any(
        token in normalized
        for token in ("sueldo", "ingreso", "trabajo", "recibo", "monotributo", "salario", "cobra", "ingresos")
    )

    return {
        "has_children": has_children,
        "has_property": has_property,
        "has_housing": has_housing,
        "mentions_home": mentions_home,
        "protection_urgency": protection_urgency,
        "infant_urgency": infant_urgency,
        "domicile_known": domicile_known,
        "divorce_mode": divorce_mode,
        "children_defined": children_defined,
        "income_defined": income_defined,
    }


def _resolve_divorce_mode(*, normalized: str, known_facts: dict[str, Any]) -> str:
    raw_mode = _normalize_text(
        known_facts.get("divorcio_modalidad")
        or known_facts.get("modalidad_divorcio")
    )
    if "unilateral" in raw_mode:
        return "unilateral"
    if any(token in raw_mode for token in ("conjunto", "mutuo acuerdo", "comun acuerdo", "común acuerdo")):
        return "joint"
    hay_acuerdo = known_facts.get("hay_acuerdo")
    if hay_acuerdo is True:
        return "joint"
    if hay_acuerdo is False:
        return "unilateral"
    if any(token in normalized for token in ("unilateral", "solo yo quiero", "no quiere divorciarse", "sin acuerdo")):
        return "unilateral"
    if any(token in normalized for token in ("mutuo acuerdo", "comun acuerdo", "común acuerdo", "presentacion conjunta", "de acuerdo ambos")):
        return "joint"
    return "undetermined"


def _resolve_focus_profile(*, case_domain: str, context: dict[str, Any]) -> dict[str, Any]:
    ranked_focuses: list[tuple[str, str]] = []

    if context.get("protection_urgency"):
        ranked_focuses.append(
            (
                "protection_urgency",
                "Se detectaron indicadores de urgencia o proteccion que deberian ir antes que el resto del encuadre.",
            )
        )
    if case_domain == "divorcio" and context.get("has_children"):
        ranked_focuses.append(
            (
                "children",
                "Hay hijos involucrados y eso cambia la prioridad juridica del caso.",
            )
        )
    if case_domain == "divorcio" and context.get("has_housing"):
        ranked_focuses.append(
            (
                "housing",
                "La vivienda aparece como conflicto principal y puede alterar el planteo practico de la presentacion.",
            )
        )
    if case_domain == "divorcio" and context.get("has_property"):
        ranked_focuses.append(
            (
                "property",
                "Hay una dimension patrimonial relevante que no deberia desaparecer del armado del caso.",
            )
        )
    if context.get("domicile_known"):
        ranked_focuses.append(
            (
                "procedure",
                "Ya hay datos para ubicar competencia o forma de inicio, asi que el aspecto procedimental tambien pesa.",
            )
        )

    if not ranked_focuses:
        ranked_focuses.append(
            (
                "general",
                "No hay un eje dominante suficientemente claro, asi que conviene sostener una orientacion general estable.",
            )
        )

    primary_focus, focus_reason = ranked_focuses[0]
    secondary_focuses = [name for name, _reason in ranked_focuses[1:]]
    return {
        "primary_focus": primary_focus,
        "secondary_focuses": secondary_focuses,
        "focus_reason": focus_reason,
    }


def _build_secondary_focus_lines(context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for focus in context.get("secondary_focuses", []):
        if focus == "children":
            lines.append(
                "Despues de ordenar el foco principal, conviene mantener visibles cuidado personal, comunicacion y alimentos para que no queden diluidos."
            )
        elif focus == "housing":
            lines.append(
                "Tambien conviene dejar ordenado el punto de vivienda para que el conflicto habitacional no reaparezca sin respaldo."
            )
        elif focus == "property":
            lines.append(
                "Ademas vale la pena conservar una linea patrimonial clara si hay bienes o documentacion que despues vaya a influir en la estrategia."
            )
        elif focus == "procedure":
            lines.append(
                "Tambien suma definir con precision competencia, domicilios y forma de inicio para que el caso no se desordene por una cuestion procesal evitable."
            )
    return lines[:2]


def _build_secondary_focus_steps(context: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    for focus in context.get("secondary_focuses", []):
        if focus == "children":
            steps.append("Dejar identificados los puntos de cuidado personal, comunicacion y alimentos aunque no sean el conflicto principal.")
        elif focus == "housing":
            steps.append("Ordenar tambien la informacion de vivienda para no perder ese eje secundario.")
        elif focus == "property":
            steps.append("Guardar una base documental minima sobre bienes para que el eje patrimonial no desaparezca del caso.")
        elif focus == "procedure":
            steps.append("Precisar competencia, domicilios y modalidad de inicio para sostener mejor la presentacion.")
    return steps[:2]


def _resolve_local_process_guide(
    *,
    case_domain: str,
    jurisdiction: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    if _normalize_text(jurisdiction) != "jujuy":
        return {}

    if case_domain == "divorcio":
        divorce_mode = _clean_text(context.get("divorce_mode"))
        overview_line = (
            "En Jujuy, de forma orientativa, esto suele tramitar en el fuero de familia y conviene entrar con una presentacion que ya traiga propuesta reguladora."
        )
        if divorce_mode == "joint":
            first_step = (
                "Si el divorcio es de comun acuerdo, preparar la presentacion conjunta con convenio o propuesta reguladora completa."
            )
        elif divorce_mode == "unilateral":
            first_step = (
                "Si el divorcio es unilateral, preparar la peticion de divorcio con propuesta reguladora y domicilios utiles para ubicar competencia."
            )
        else:
            first_step = (
                "Definir si el divorcio va a ser conjunto o unilateral y ordenar la presentacion con propuesta reguladora desde el inicio."
            )
        notes = [
            "En Jujuy, de forma orientativa, el divorcio suele moverse en el fuero de familia.",
            "La propuesta reguladora o el convenio no conviene dejarlo para despues: suele ordenar el tramite desde la primera presentacion.",
        ]
        if context.get("domicile_known"):
            notes.append(
                "Si ya tenes un domicilio relevante, conviene usarlo para ordenar competencia desde el inicio y evitar idas y vueltas."
            )
        else:
            notes.append(
                "Conviene identificar cuanto antes el domicilio relevante de las partes para no desordenar la competencia."
            )
        return {
            "overview_line": overview_line,
            "first_step": first_step,
            "forum_hint": "Fuero de familia de Jujuy.",
            "filing_shape": "Presentacion de divorcio con propuesta reguladora o convenio regulador.",
            "notes": notes,
        }

    if case_domain == "alimentos":
        return {
            "overview_line": "En Jujuy, de forma orientativa, este tipo de reclamo suele tramitar en el fuero de familia y conviene llegar con gastos concretos desde el inicio.",
            "first_step": "Armar una base simple de gastos y, si hay necesidad actual, evaluar un pedido de cuota provisoria desde la presentacion inicial.",
            "forum_hint": "Fuero de familia de Jujuy.",
            "filing_shape": "Reclamo de alimentos con base de gastos y eventual pedido provisorio.",
            "notes": [
                "En Jujuy, de forma orientativa, los alimentos suelen moverse en el fuero de familia.",
                "Si la necesidad es actual, suele sumar llegar con comprobantes concretos y un pedido claro de cuota provisoria.",
            ],
        }

    if case_domain == "cuidado_personal":
        return {
            "overview_line": "En Jujuy, de forma orientativa, estos planteos suelen trabajarse en el fuero de familia con foco en convivencia actual y centro de vida.",
            "first_step": "Preparar un planteo que explique convivencia actual, centro de vida y modalidad de cuidado pedida.",
            "forum_hint": "Fuero de familia de Jujuy.",
            "filing_shape": "Planteo de cuidado personal con foco en convivencia y centro de vida.",
            "notes": [
                "En Jujuy, de forma orientativa, el cuidado personal suele moverse en el fuero de familia.",
                "Sirve llegar con una descripcion concreta de convivencia, rutina y centro de vida, no solo con afirmaciones generales.",
            ],
        }

    if case_domain in {"regimen_comunicacional", "regimen de comunicacion"}:
        return {
            "overview_line": "En Jujuy, de forma orientativa, estos pedidos suelen moverse en el fuero de familia y funcionan mejor cuando el esquema pedido ya es concreto.",
            "first_step": "Preparar un esquema claro de dias, horarios, modalidad, pernocte y vacaciones si corresponde.",
            "forum_hint": "Fuero de familia de Jujuy.",
            "filing_shape": "Pedido de regimen comunicacional con esquema concreto y practicable.",
            "notes": [
                "En Jujuy, de forma orientativa, el regimen comunicacional suele tramitar en el fuero de familia.",
                "Conviene llegar con un esquema concreto y practicable, no con una formula abierta de contacto.",
            ],
        }

    if case_domain in {"violencia", "violencia_familiar"}:
        return {
            "overview_line": "En Jujuy, de forma orientativa, la prioridad es la medida de proteccion urgente y el resguardo inmediato, antes de ampliar otros conflictos derivados.",
            "first_step": "Definir la medida urgente a pedir y reunir respaldo minimo del riesgo actual para una presentacion inmediata.",
            "forum_hint": "Canal de proteccion urgente y familia, segun el caso en Jujuy.",
            "filing_shape": "Presentacion urgente centrada en la medida de proteccion y el riesgo actual.",
            "notes": [
                "En Jujuy, de forma orientativa, estos casos se ordenan por la urgencia de la proteccion, no por una reconstruccion completa del conflicto.",
                "Suele servir llegar con denuncia, constancia medica, mensajes o cualquier respaldo basico que muestre riesgo actual.",
            ],
        }

    if case_domain == "sucesion":
        return {
            "overview_line": "En Jujuy, de forma orientativa, la sucesion suele abrirse en sede civil con base en el ultimo domicilio del causante.",
            "first_step": "Ordenar fallecimiento, parentesco y ultimo domicilio del causante antes de presentar la apertura sucesoria.",
            "forum_hint": "Sede civil de Jujuy.",
            "filing_shape": "Apertura sucesoria con documentacion de fallecimiento, parentesco y competencia.",
            "notes": [
                "En Jujuy, de forma orientativa, la sucesion suele entrar en sede civil y el ultimo domicilio del causante pesa para la competencia.",
                "Conviene llegar con fallecimiento, parentesco y un inventario preliminar de bienes para que la apertura no quede floja.",
            ],
        }

    if case_domain == "civil_cobro":
        return {
            "overview_line": "En Jujuy, de forma orientativa, un reclamo civil de cobro o incumplimiento suele moverse en sede civil y el domicilio del demandado o el lugar de cumplimiento pueden ordenar la competencia.",
            "first_step": "Definir si conviene intimar primero y ordenar el documento base de la deuda antes de presentar el reclamo civil.",
            "forum_hint": "Sede civil de Jujuy.",
            "filing_shape": "Reclamo civil de cobro o cumplimiento con respaldo documental de la obligacion.",
            "notes": [
                "En Jujuy, de forma orientativa, en acciones personales suele pesar el lugar de cumplimiento o el domicilio del demandado para ordenar competencia.",
                "Sirve llegar con documento base de la deuda, exigibilidad e intimacion previa si ya existe.",
            ],
        }

    if case_domain == "civil_danos":
        return {
            "overview_line": "En Jujuy, de forma orientativa, un reclamo de danos suele moverse en sede civil y conviene llegar con hecho, dano y prueba minima ya diferenciados.",
            "first_step": "Ordenar primero el hecho, el dano concreto y la prueba disponible antes de cuantificar fino el reclamo.",
            "forum_hint": "Sede civil de Jujuy.",
            "filing_shape": "Reclamo civil de danos con base en hecho, responsabilidad y perjuicio acreditable.",
            "notes": [
                "En Jujuy, de forma orientativa, en danos conviene no mezclar responsabilidad y cuantificacion sin una base documental minima.",
                "Suele ayudar separar dano material, dano personal y respaldo del hecho desde el inicio.",
            ],
        }

    if case_domain == "civil_inmueble":
        return {
            "overview_line": "En Jujuy, de forma orientativa, si el conflicto gira sobre un inmueble suele pesar la ubicacion del bien y la documentacion del vinculo para ordenar el reclamo civil.",
            "first_step": "Identificar el inmueble, el tipo de conflicto y el documento base antes de intimar o judicializar.",
            "forum_hint": "Sede civil de Jujuy.",
            "filing_shape": "Reclamo civil vinculado a inmueble, locacion, ocupacion o uso del bien.",
            "notes": [
                "En Jujuy, de forma orientativa, si la accion se apoya en un inmueble conviene llegar con la ubicacion del bien y el documento que explique el vinculo.",
                "Contrato, escritura, boleto, recibos o intimaciones suelen ordenar mejor el reclamo que una descripcion general del conflicto.",
            ],
        }

    return {}


def _resolve_practical_domain(
    *,
    case_domain: str,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> str:
    action_slug = _normalize_text(payload.get("action_slug"))
    text = _normalize_text(
        " ".join([
            _clean_text(payload.get("query")),
            _clean_text(payload.get("response_text")),
            _clean_text(_as_dict(payload.get("reasoning")).get("short_answer")),
        ])
    )

    if case_domain in {
        "divorcio",
        "alimentos",
        "cuidado_personal",
        "regimen_comunicacional",
        "regimen de comunicacion",
        "violencia",
        "violencia_familiar",
        "sucesion",
    }:
        return case_domain

    if action_slug == "sucesion_ab_intestato" or any(
        token in text for token in ("sucesion", "herencia", "declaratoria de herederos", "causante", "fallecio", "murio")
    ):
        return "sucesion"

    if any(
        token in text for token in (
            "accidente",
            "choque",
            "lesion",
            "lesiones",
            "danos",
            "daños",
            "perjuicio",
            "indemnizacion",
            "indemnización",
            "seguro",
            "siniestro",
        )
    ):
        return "civil_danos"

    if any(
        token in text for token in (
            "alquiler",
            "locacion",
            "locación",
            "desalojo",
            "inmueble",
            "ocupacion",
            "ocupación",
            "escritura",
            "boleto",
            "propiedad",
            "casa",
            "departamento",
        )
    ):
        return "civil_inmueble"

    if any(
        token in text for token in (
            "deuda",
            "me deben",
            "no me paga",
            "no me pagaron",
            "incumplio",
            "incumplió",
            "incumplimiento",
            "contrato",
            "factura",
            "pagaré",
            "pagare",
            "prestamo",
            "préstamo",
            "cobro",
            "intimar",
        )
    ):
        return "civil_cobro"

    if case_domain in {"civil", "generic", "general"} and context.get("domicile_known"):
        return "civil_cobro"

    return case_domain


def _practical_domain_label(case_domain: str) -> str:
    labels = {
        "divorcio": "Divorcio",
        "alimentos": "Alimentos",
        "cuidado_personal": "Cuidado personal",
        "regimen_comunicacional": "Regimen comunicacional",
        "violencia": "Violencia familiar",
        "violencia_familiar": "Violencia familiar",
        "sucesion": "Sucesion",
        "civil_cobro": "Cobro e incumplimiento civil",
        "civil_danos": "Danos y perjuicios",
        "civil_inmueble": "Conflicto civil sobre inmueble",
    }
    return labels.get(case_domain, _clean_text(case_domain).replace("_", " "))


def _normalize_action_sentence(text: str) -> str:
    cleaned = _clean_text(text).rstrip(".")
    if not cleaned:
        return ""
    cleaned = _strip_leading_noise(cleaned)
    if not cleaned:
        return ""
    first_word = cleaned.split(" ", 1)[0].casefold()
    if first_word not in ACTION_STARTERS:
        return ""
    cleaned = cleaned[0].upper() + cleaned[1:]
    return f"{cleaned}."


def _normalize_document_item(text: str) -> str:
    cleaned = _to_user_text(text).rstrip(".")
    if not cleaned:
        return ""
    if not any(token in _normalize_text(cleaned) for token in DOCUMENT_HINTS):
        return ""
    if cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return f"{cleaned}."


def _normalize_note(text: str) -> str:
    cleaned = _to_user_text(_first_sentences(text, limit=1)).rstrip(".")
    if not cleaned:
        return ""
    if cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return f"{cleaned}."


def _humanize_question(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    lowered = _normalize_text(cleaned)

    if "hijos" in lowered and any(token in lowered for token in ("cuidado", "comunicacion", "alimentos", "menor", "capacidad")):
        return "Hay hijos menores o alguna situacion que obligue a regular cuidado, comunicacion o alimentos?"
    if "hijos" in lowered:
        return "Hay hijos en comun?"
    if "domicilio" in lowered or "jurisdic" in lowered or "provincia" in lowered or "ciudad" in lowered:
        return "En que ciudad o domicilio principal se desarrolla el caso?"
    if "ingreso" in lowered or "trabajo" in lowered or "sueldo" in lowered:
        return "Tenes algun dato concreto sobre ingresos o trabajo de la otra parte?"

    cleaned = cleaned.rstrip(".:;?!")
    cleaned = _strip_leading_noise(cleaned)
    if not cleaned:
        return ""
    return f"{cleaned[0].upper()}{cleaned[1:]}?"


def _strip_leading_noise(text: str) -> str:
    value = _clean_text(text)
    value = re.sub(
        r"^(primer paso recomendado|lo mas conveniente ahora es|esto conviene hacerlo cuanto antes|para avanzar|podes avanzar con este primer paso)\s*:?[\s-]*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip()


def _looks_like_action(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if "?" in str(text):
        return False
    if normalized.startswith(("hay ", "existen ", "si hay ", "tienen ", "dato ", "pregunta ", "aclarar si ")):
        return False
    return normalized.startswith(ACTION_STARTERS)


def _looks_document_related(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(token in normalized for token in DOCUMENT_HINTS)


def _looks_generic_note(text: str) -> bool:
    normalized = _normalize_text(text)
    return normalized.startswith(("es importante", "conviene analizar", "habria que ver"))


def _compose_paragraph(lines: list[str], *, minimum_lines: int = 3) -> str:
    cleaned_lines = [_to_user_text(_clean_text(line)) for line in lines if _clean_text(line)]
    if len(cleaned_lines) < minimum_lines:
        cleaned_lines.extend(
            [
                "Lo util ahora es convertir esa base en un paso concreto y documentado.",
                "Despues se puede afinar estrategia, prueba o alcance sin frenar el avance inicial.",
            ][: max(0, minimum_lines - len(cleaned_lines))]
        )
    return "\n".join(_ensure_sentence(line) for line in cleaned_lines[: max(minimum_lines, len(cleaned_lines))])


def _ensure_sentence(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        return f"{cleaned}."
    return cleaned


def _first_sentences(text: str, *, limit: int) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    return " ".join(parts[:limit]).strip()


def _strip_known_prefix(text: str, prefix: str) -> str:
    value = _clean_text(text)
    if value.casefold().startswith(prefix.casefold()):
        return value[len(prefix):].strip()
    return value


def _to_user_text(text: str) -> str:
    result = _clean_text(text)
    replacements = (
        (r"\bcompetencia\b", "que juzgado corresponde"),
        (r"\bvia procesal\b", "como conviene iniciar el tramite"),
        (r"\batribucion del hogar\b", "uso de la vivienda"),
        (r"\bprogenitor conviviente\b", "quien convive con el hijo o la hija"),
    )
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _strip_prohibited_phrases(text: Any) -> str:
    value = "" if text is None else str(text).strip()
    value = re.sub(r"[ \t]+", " ", value)
    lowered = value.casefold()
    for phrase in PROHIBITED_PHRASES:
        if phrase in lowered:
            value = re.sub(re.escape(phrase), "", value, flags=re.IGNORECASE).strip(" ,.;:")
            lowered = value.casefold()
    return value


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = _clean_text(item)
        key = _normalize_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _first_nonempty_text(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).strip()


def _normalize_text(value: Any) -> str:
    return _clean_text(value).casefold()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]
