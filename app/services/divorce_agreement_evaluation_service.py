from __future__ import annotations

import re
from typing import Any


_VERY_YOUNG_CHILD_PATTERNS = (
    r"\b\d{1,2}\s*mes(?:es)?\b",
    r"\bbebe\b",
    r"\bbebes\b",
    r"\breci[eé]n nacid",
    r"\blactante\b",
)


def build_divorce_agreement_enrichment(response: dict[str, Any]) -> dict[str, Any]:
    data = dict(response or {})
    facts = _collect_known_facts(data)
    if not _applies_to_divorce_agreement_context(data, facts):
        return {}

    query_text = _build_query_context_text(data)
    cuota_porcentaje = _clean_text(facts.get("cuota_alimentaria_porcentaje"))
    has_percentage_quota = bool(cuota_porcentaje)
    has_regimen = bool(facts.get("regimen_comunicacional"))
    has_convenio = bool(facts.get("convenio_regulador"))
    unilateral_or_partial = (
        _clean_text(facts.get("divorcio_modalidad")) == "unilateral"
        or facts.get("hay_acuerdo") is False
    )
    very_young_child = _text_matches_any(query_text, _VERY_YOUNG_CHILD_PATTERNS)

    summary_parts = [
        "El convenio ya cambia la estrategia: ahora conviene revisar si alimentos y comunicacion quedaron redactados con precision suficiente para su homologacion."
    ]
    if has_percentage_quota:
        summary_parts.append(
            "Si la cuota se fija como porcentaje, conviene dejar clara la base de calculo, la forma de pago y los gastos que quedan incluidos o aparte."
        )
    if has_regimen and very_young_child:
        summary_parts.append(
            "Como aparece un nino muy pequeno, el regimen comunicacional conviene analizarlo con gradualidad y cuidados concretos."
        )
    elif has_regimen:
        summary_parts.append(
            "Tambien conviene revisar que el regimen comunicacional tenga dias, horarios, traslados y responsables bien definidos."
        )

    strategic_narrative = (
        "Con hijos y un convenio ya mencionado, la estrategia deja de ser solo abrir el divorcio y pasa a controlar si el texto del acuerdo es suficientemente preciso para homologacion y eventual ejecucion."
    )
    if unilateral_or_partial:
        strategic_narrative += (
            " Como el tramite se perfila unilateral o con acuerdo parcial, conviene verificar que lo ya acordado pueda sostenerse sin dejar zonas grises en alimentos o comunicacion."
        )
    if has_percentage_quota:
        strategic_narrative += (
            " La cuota fijada en porcentaje requiere una redaccion especialmente clara sobre base de calculo, descuentos, fecha de pago y rubros extraordinarios."
        )
    if has_regimen and very_young_child:
        strategic_narrative += (
            " El esquema de comunicacion para un bebe o nino muy pequeno merece una revision prudente de gradualidad, tiempos y cuidados."
        )

    recommended_actions = [
        "Redactar el convenio con precision suficiente para homologacion, incluyendo base de calculo de la cuota y modalidad concreta de comunicacion.",
        "Revisar si el convenio regula de manera ejecutable alimentos, comunicacion y demas efectos del divorcio.",
    ]
    if has_percentage_quota:
        recommended_actions.append(
            "Redactar la clausula de cuota con base de calculo, descuentos, fecha de pago y tratamiento de gastos extraordinarios si se fija como porcentaje."
        )
    if has_regimen:
        action = "Precisar dias, horarios, traslados y responsables del regimen comunicacional."
        if very_young_child:
            action = "Precisar gradualidad, tiempos, traslados y cuidados concretos del regimen comunicacional para un nino muy pequeno."
        recommended_actions.append(action)
    if unilateral_or_partial:
        recommended_actions.append(
            "Separar con claridad lo ya acordado de lo que todavia puede requerir definicion judicial dentro del divorcio."
        )

    risk_analysis = [
        "Un convenio aparentemente acordado puede seguir siendo insuficiente si la redaccion no permite homologarlo o ejecutarlo sin ambiguedades."
    ]
    if has_percentage_quota:
        risk_analysis.append(
            "Una cuota alimentaria fijada solo como porcentaje puede generar observaciones o conflictos posteriores si no se aclara su base de calculo y forma de pago."
        )
    if has_regimen and very_young_child:
        risk_analysis.append(
            "Un regimen comunicacional para un bebe o nino muy pequeno requiere especial prudencia para evitar un esquema dificil de homologar o sostener en la practica."
        )
    elif has_regimen:
        risk_analysis.append(
            "Un regimen comunicacional poco preciso puede volver conflictiva la homologacion o la etapa de cumplimiento."
        )
    if unilateral_or_partial:
        risk_analysis.append(
            "Si el divorcio sigue una via unilateral o hay solo acuerdos parciales, conviene no presentar el convenio como si cerrara todo el conflicto."
        )

    procedural_focus = [
        "El siguiente paso ya no es solo encuadrar el divorcio: conviene auditar la precision ejecutable del convenio.",
        "Controlar que alimentos y comunicacion tengan una redaccion concreta, verificable y homologable.",
    ]
    if has_percentage_quota:
        procedural_focus.append(
            "Revisar que la clausula alimentaria identifique base de calculo, periodicidad y mecanismo de pago."
        )
    if has_regimen and very_young_child:
        procedural_focus.append(
            "Revisar gradualidad, frecuencia y cuidados del regimen comunicacional segun la corta edad del hijo."
        )

    ordinary_missing_information = [
        "Verificar si el convenio describe con precision suficiente alimentos y comunicacion para evitar observaciones al homologarlo."
    ]
    if has_percentage_quota:
        ordinary_missing_information.append(
            "Precisar la base de calculo, fecha de pago y gastos extraordinarios de la cuota alimentaria en porcentaje."
        )
    if has_regimen:
        ordinary_missing_information.append(
            "Precisar dias, horarios, traslados y modalidad concreta del regimen comunicacional."
        )

    return {
        "summary": " ".join(summary_parts).strip(),
        "strategic_narrative": strategic_narrative,
        "recommended_actions": recommended_actions,
        "risk_analysis": risk_analysis,
        "procedural_focus": procedural_focus,
        "ordinary_missing_information": ordinary_missing_information,
    }


def _applies_to_divorce_agreement_context(response: dict[str, Any], facts: dict[str, Any]) -> bool:
    case_domain = _clean_text(response.get("case_domain"))
    case_domains = [_clean_text(item) for item in response.get("case_domains") or []]
    if "divorcio" not in {case_domain, *case_domains}:
        return False
    if facts.get("hay_hijos") is not True:
        return False
    return any(
        facts.get(key)
        for key in (
            "convenio_regulador",
            "cuota_alimentaria_porcentaje",
            "regimen_comunicacional",
            "alimentos_definidos",
        )
    )


def _collect_known_facts(response: dict[str, Any]) -> dict[str, Any]:
    facts = dict(response.get("facts") or {}) if isinstance(response.get("facts"), dict) else {}
    metadata = dict(response.get("metadata") or {}) if isinstance(response.get("metadata"), dict) else {}
    clarification_context = (
        dict(metadata.get("clarification_context") or {})
        if isinstance(metadata.get("clarification_context"), dict)
        else {}
    )
    known_facts = (
        dict(clarification_context.get("known_facts") or {})
        if isinstance(clarification_context.get("known_facts"), dict)
        else {}
    )
    known_facts.update(facts)
    return {key: value for key, value in known_facts.items() if value not in (None, "", [], {})}


def _build_query_context_text(response: dict[str, Any]) -> str:
    parts = [
        _clean_text(response.get("query")),
        _clean_text(response.get("response_text")),
    ]
    metadata = dict(response.get("metadata") or {}) if isinstance(response.get("metadata"), dict) else {}
    clarification_context = (
        dict(metadata.get("clarification_context") or {})
        if isinstance(metadata.get("clarification_context"), dict)
        else {}
    )
    parts.extend(
        [
            _clean_text(clarification_context.get("base_query")),
            _clean_text(clarification_context.get("last_user_answer")),
        ]
    )
    return " ".join(part for part in parts if part).strip()


def _text_matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    normalized = _clean_text(text)
    return any(re.search(pattern, normalized) for pattern in patterns)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())
