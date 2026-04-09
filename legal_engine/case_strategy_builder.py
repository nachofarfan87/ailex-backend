from __future__ import annotations

import unicodedata
from typing import Any

from app.services.strategy_reactivity_service import apply_strategy_reactivity


def build_case_strategy(
    query: str,
    case_profile: dict,
    case_theory: dict,
    conflict: dict,
    case_evaluation: dict,
    procedural_plan,
    jurisprudence_analysis: dict,
    reasoning_result,
    legal_decision: dict | None = None,
    procedural_case_state: dict | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    legal_decision = dict(legal_decision or {})
    procedural_case_state = dict(procedural_case_state or {})
    strategy_mode = _resolve_strategy_mode(
        legal_decision=legal_decision,
        case_profile=case_profile,
        case_evaluation=case_evaluation,
        conflict=conflict,
        jurisprudence_analysis=jurisprudence_analysis,
        procedural_case_state=procedural_case_state,
    )
    legal_decision.setdefault("strategic_posture", strategy_mode)
    legal_decision.setdefault(
        "dominant_factor",
        _resolve_strategy_dominant_factor(
            legal_decision=legal_decision,
            case_profile=case_profile,
            case_evaluation=case_evaluation,
            conflict=conflict,
            jurisprudence_analysis=jurisprudence_analysis,
            procedural_case_state=procedural_case_state,
        ),
    )
    jurisprudence_guard = _build_jurisprudence_guard(jurisprudence_analysis)
    relevant_highlights = [
        item
        for item in (jurisprudence_analysis.get("jurisprudence_highlights") or [])
        if isinstance(item, dict) and str(item.get("source_mode") or "").strip() != "internal_fallback_profile"
    ]

    strategy = {
        "strategy_mode": strategy_mode,
        "strategic_narrative": _build_strategic_narrative(
            query=query,
            case_profile=case_profile,
            case_theory=case_theory,
            conflict=conflict,
            case_evaluation=case_evaluation,
            legal_decision=legal_decision,
            procedural_plan=procedural_plan,
            jurisprudence_guard=jurisprudence_guard,
            highlights=relevant_highlights,
            reasoning_result=reasoning_result,
            procedural_case_state=procedural_case_state,
        ),
        "conflict_summary": _build_conflict_summary(
            case_profile=case_profile,
            case_theory=case_theory,
            conflict=conflict,
            jurisprudence_guard=jurisprudence_guard,
        ),
        "risk_analysis": _build_risk_analysis(
            case_profile=case_profile,
            case_theory=case_theory,
            conflict=conflict,
            case_evaluation=case_evaluation,
            legal_decision=legal_decision,
            procedural_plan=procedural_plan,
            procedural_case_state=procedural_case_state,
        ),
        "recommended_actions": _build_recommended_actions(
            case_profile=case_profile,
            case_theory=case_theory,
            conflict=conflict,
            procedural_plan=procedural_plan,
            procedural_case_state=procedural_case_state,
        ),
        "procedural_focus": _build_procedural_focus(
            case_profile=case_profile,
            case_theory=case_theory,
            conflict=conflict,
            legal_decision=legal_decision,
            jurisprudence_guard=jurisprudence_guard,
            jurisprudence_analysis=jurisprudence_analysis,
            procedural_case_state=procedural_case_state,
        ),
        "legal_decision_alignment": _build_decision_alignment_notes(legal_decision),
        "secondary_domain_notes": _build_secondary_domain_notes(case_profile),
    }
    _apply_sensitive_strategy_validations(strategy, query, case_profile)
    strategy = apply_strategy_reactivity(
        strategy,
        case_domain=str(case_profile.get("case_domain") or "").strip(),
        facts=dict(case_profile.get("input_facts") or {}),
        metadata=metadata or {},
        query=query,
    )
    return strategy


def _resolve_strategy_mode(
    *,
    legal_decision: dict[str, Any],
    case_profile: dict[str, Any],
    case_evaluation: dict[str, Any],
    conflict: dict[str, Any],
    jurisprudence_analysis: dict[str, Any],
    procedural_case_state: dict[str, Any] | None = None,
) -> str:
    posture = str(legal_decision.get("strategic_posture") or "").strip().lower()

    # --- blocking_factor can override even an explicit posture ---
    pcs = procedural_case_state or {}
    blocking = str(pcs.get("blocking_factor") or "").strip().lower()
    readiness = str(pcs.get("execution_readiness") or "").strip().lower()

    if blocking in ("service", "competence"):
        return "cautelosa"
    if blocking == "evidence":
        if posture == "agresiva":
            return "cautelosa"
        return posture if posture in {"conservadora", "cautelosa"} else "cautelosa"
    if blocking == "execution":
        if posture == "cautelosa":
            return "conservadora"
        return posture if posture in {"agresiva", "conservadora"} else "conservadora"
    if blocking == "administrative_delay":
        if posture == "agresiva":
            return "conservadora"
        return posture if posture in {"conservadora", "cautelosa"} else "conservadora"

    # --- no blocking: respect explicit posture if set ---
    if posture in {"agresiva", "conservadora", "cautelosa"}:
        return posture

    # --- execution_readiness adjusts when no blocking ---
    if readiness == "bloqueado_procesalmente":
        return "cautelosa"
    if readiness == "requiere_impulso_procesal":
        return "conservadora"

    # --- fallback: score-based resolution ---
    risk_label = str(case_evaluation.get("legal_risk_level") or "").strip().lower()
    risk_score = float(case_evaluation.get("risk_score") or 0.0)
    strength_score = float(case_evaluation.get("strength_score") or 0.0)
    strength_label = str(case_evaluation.get("case_strength") or "").strip().lower()
    precedent_trend = str(jurisprudence_analysis.get("precedent_trend") or "neutral").strip().lower()
    needs_proof = bool(case_profile.get("needs_proof_strengthening"))
    vulnerable = str(conflict.get("most_vulnerable_point") or "").strip()

    if (
        risk_label == "alto"
        or risk_score >= 0.7
        or needs_proof
        or (precedent_trend == "adverse" and (risk_score >= 0.5 or vulnerable))
    ):
        return "cautelosa"
    if (
        (strength_label in {"alto", "fuerte"} or strength_score >= 0.72)
        and risk_score <= 0.35
        and risk_label not in {"alto", "medio"}
        and not needs_proof
        and precedent_trend != "adverse"
    ):
        return "agresiva"

    # listo_para_avanzar with good scores can push to agresiva
    if readiness == "listo_para_avanzar" and strength_score >= 0.65 and risk_score <= 0.4:
        return "agresiva"

    return "conservadora"


def _resolve_strategy_dominant_factor(
    *,
    legal_decision: dict[str, Any],
    case_profile: dict[str, Any],
    case_evaluation: dict[str, Any],
    conflict: dict[str, Any],
    jurisprudence_analysis: dict[str, Any],
    procedural_case_state: dict[str, Any] | None = None,
) -> str:
    factor = str(legal_decision.get("dominant_factor") or "").strip().lower()
    if factor in {"norma", "prueba", "riesgo", "jurisprudencia", "procesal"}:
        return factor

    # --- blocking_factor dominates dominant factor ---
    pcs = procedural_case_state or {}
    blocking = str(pcs.get("blocking_factor") or "").strip().lower()
    _BLOCKING_TO_FACTOR = {
        "service": "procesal",
        "competence": "procesal",
        "execution": "procesal",
        "administrative_delay": "procesal",
        "evidence": "prueba",
    }
    if blocking in _BLOCKING_TO_FACTOR:
        return _BLOCKING_TO_FACTOR[blocking]

    precedent_trend = str(jurisprudence_analysis.get("precedent_trend") or "neutral").strip().lower()
    precedent_delta = float(jurisprudence_analysis.get("confidence_delta") or 0.0)
    risk_score = float(case_evaluation.get("risk_score") or 0.0)
    if risk_score >= 0.65:
        return "riesgo"
    if case_profile.get("needs_proof_strengthening") or str(conflict.get("most_vulnerable_point") or "").strip():
        return "prueba"
    if precedent_trend != "neutral" and abs(precedent_delta) >= 0.03:
        return "jurisprudencia"
    return "norma"


def _build_jurisprudence_guard(jurisprudence_analysis: dict[str, Any]) -> dict[str, Any]:
    source_quality = str(jurisprudence_analysis.get("source_quality") or "none").strip()
    strength = str(jurisprudence_analysis.get("jurisprudence_strength") or "none").strip()
    avoid_assertions = bool(jurisprudence_analysis.get("should_avoid_jurisprudential_assertions", True))
    limit_claims = bool(jurisprudence_analysis.get("should_limit_claims", True))
    if source_quality == "real" and strength == "strong":
        avoid_assertions = False
        limit_claims = False
    elif source_quality == "legacy":
        avoid_assertions = False
        limit_claims = True
    elif source_quality in {"fallback", "none"}:
        avoid_assertions = True
        limit_claims = True
    return {
        "source_quality": source_quality,
        "strength": strength,
        "avoid_assertions": avoid_assertions,
        "limit_claims": limit_claims,
    }


# ---------------------------------------------------------------------------
# Strategic narrative
# ---------------------------------------------------------------------------

def _build_strategic_narrative(
    *,
    query: str,
    case_profile: dict,
    case_theory: dict,
    conflict: dict,
    case_evaluation: dict,
    legal_decision: dict,
    procedural_plan,
    jurisprudence_guard: dict[str, Any],
    highlights: list[dict[str, Any]],
    reasoning_result,
    procedural_case_state: dict[str, Any],
) -> str:
    parts: list[str] = []
    domain = str(case_profile.get("case_domain") or "generic").strip()
    scenarios = set(case_profile.get("scenarios") or set())
    risk_level = str(case_evaluation.get("legal_risk_level") or "").strip()
    evidence_posture = _resolve_evidence_posture(case_profile, case_theory, conflict)
    strategic_posture = str(legal_decision.get("strategic_posture") or "").strip()
    dominant_factor = str(legal_decision.get("dominant_factor") or "").strip()

    applied = str(getattr(reasoning_result, "applied_analysis", "") or "").strip()
    short_answer = str(getattr(reasoning_result, "short_answer", "") or "").strip()

    # --- blocking_factor-driven narrative: direct and actionable ---
    blocking_opening = _blocking_factor_narrative_opening(procedural_case_state)
    if blocking_opening:
        parts.append(blocking_opening)
    else:
        parts.append(
            _narrative_opening(domain=domain, scenarios=scenarios, risk_level=risk_level, evidence_posture=evidence_posture, query=query)
        )

    parts.append(
        applied
        or short_answer
        or f"Analisis inicial sobre '{query}': se requiere completar el desarrollo con mejor precision de hechos y soporte normativo."
    )

    if str(conflict.get("most_vulnerable_point") or "").strip():
        parts.append(
            f"El punto que probablemente condicione la viabilidad practica del planteo es: {str(conflict.get('most_vulnerable_point')).strip()}"
        )

    if strategic_posture == "cautelosa":
        parts.append(
            "El caso requiere un enfoque de prudencia y saneamiento previo. Conviene consolidar la base probatoria antes de avanzar con medidas de mayor exposicion."
        )

    if domain == "alimentos" or case_profile.get("is_alimentos"):
        _narrative_alimentos(parts, case_profile)
    elif domain == "divorcio":
        _narrative_divorcio(parts, case_profile)
    elif domain == "cuidado_personal":
        _narrative_cuidado_personal(parts, case_profile)
    elif domain == "regimen_comunicacional":
        _narrative_regimen_comunicacional(parts, case_profile)
    elif domain == "conflicto_patrimonial":
        _narrative_conflicto_patrimonial(parts, case_profile)

    tension_line = _resolve_tension_line(risk_level, evidence_posture)
    if tension_line:
        parts.append(tension_line)
    decision_line = _resolve_decision_line(strategic_posture, dominant_factor)
    if decision_line:
        parts.append(decision_line)
    procedural_line = _resolve_procedural_state_line(procedural_case_state)
    if procedural_line:
        parts.append(procedural_line)

    # jurisprudence guard — same for all domains
    source_quality = jurisprudence_guard["source_quality"]
    strength = jurisprudence_guard["strength"]
    if source_quality == "real" and strength == "strong":
        parts.append(
            "La linea se sostiene con precedentes reales recuperados del corpus que operan como eje del planteo. Corresponde invocarlos directamente vinculandolos con los hechos decisivos y la prueba disponible."
        )
    elif source_quality == "legacy":
        parts.append(
            "La jurisprudencia importada sirve como apoyo secundario y no debe desplazar el peso de la argumentacion principal, que debe permanecer en la norma positiva, el relato de hechos y la acreditacion de requisitos."
        )
    elif source_quality in {"fallback", "none"}:
        parts.append(
            "No corresponde presentar la base disponible como jurisprudencia consolidada. La consistencia del planteo debe construirse desde el conflicto delimitado, los requisitos legales exigibles y la cobertura probatoria efectiva."
        )

    for item in highlights[:2]:
        criterion = str(item.get("criterion") or "").strip()
        strategic_use = str(item.get("strategic_use") or "").strip()
        if criterion:
            parts.append(f"Criterio util para ordenar el planteo: {criterion}")
        if strategic_use:
            parts.append(f"Uso litigioso sugerido: {strategic_use}")

    for item in (case_theory.get("likely_points_of_conflict") or [])[:2]:
        text = str(item).strip()
        if text:
            parts.append(f"Frente de discusion a anticipar: {text}")

    evidence_needs = [str(item).strip() for item in (case_theory.get("evidentiary_needs") or []) if str(item).strip()]
    if evidence_needs:
        parts.append(
            "Cobertura probatoria prioritaria: "
            + "; ".join(evidence_needs[:2])
            + "."
        )

    for item in (getattr(procedural_plan, "steps", None) or [])[:1]:
        action = str(getattr(item, "action", "") or "").strip()
        if action:
            parts.append(f"Prioridad procesal inmediata: {action}")

    return "\n\n".join(part for part in parts if part)


# ---- per-domain narrative helpers ----

def _narrative_alimentos(parts: list[str], case_profile: dict) -> None:
    scenarios = set(case_profile.get("scenarios") or set())
    if "hijo_mayor_no_estudia" in scenarios:
        parts.append(
            "El caso no debe tratarse como hijo mayor estudiante: si la persona tiene mas de 21 anos y no estudia, corresponde bloquear estrategias apoyadas en regularidad academica o continuidad automatica."
        )
    elif "hijo_mayor_estudiante" in scenarios:
        parts.append(
            "El encuadre no debe tratarse como alimentos estandar de hijo menor: corresponde diferenciar el supuesto del art. 663 CCyC y trabajar regularidad academica, continuidad de estudios y necesidad actual."
        )
    elif "hijo_18_21" in scenarios:
        parts.append(
            "El tramo entre 18 y 21 anos debe separarse del supuesto de hijo menor y tambien del hijo mayor estudiante: la estrategia tiene que centrarse en edad, convivencia, necesidad y autonomia economica concreta."
        )
    elif "ascendientes" in scenarios:
        parts.append(
            "El eje litigioso pasa por explicar desde el inicio la subsidiariedad del reclamo contra ascendientes, mostrando imposibilidad o insuficiencia del obligado principal y una base normativa cerrada."
        )
    else:
        parts.append(
            "En alimentos el escrito debe evitar explicaciones generales y concentrarse en incumplimiento actual, necesidades concretas del alimentado, capacidad economica del alimentante y urgencia practica de la respuesta judicial."
        )
    if {"cuota_provisoria", "incumplimiento"} & scenarios:
        parts.append(
            "Si el incumplimiento y la necesidad actual aparecen prima facie acreditados, conviene empujar una cuota provisoria y una agenda de prueba inmediata, sin esperar una reconstruccion patrimonial completa del alimentante."
        )
    if case_profile.get("vulnerability"):
        parts.append(
            "Si la vulnerabilidad surge de los hechos, debe traducirse en estrategia concreta: acceso a justicia, cobertura minima y referencias institucionales solo cuando el caso ya las aporta."
        )
    if case_profile.get("urgency_level") == "high":
        parts.append(
            "Si el cuadro muestra urgencia real, corresponde traducirla a medidas de aseguramiento concretas, habilitacion de dia y hora o pase a feria solo cuando el soporte factico lo justifique."
        )


def _narrative_divorcio(parts: list[str], case_profile: dict) -> None:
    scenarios = set(case_profile.get("scenarios") or set())
    if "conjunto" in scenarios:
        parts.append(
            "El divorcio por presentacion conjunta exige un convenio regulador completo: verificar que cubra atribucion del hogar, regimen de bienes, alimentos y situacion de hijos si los hay."
        )
    else:
        parts.append(
            "En el divorcio unilateral la presentacion debe incluir una propuesta reguladora (art. 438 CCyC) que cubra efectos patrimoniales y personales, aunque el otro conyuge no haya adherido."
        )
    if "bienes" in scenarios:
        parts.append(
            "El regimen patrimonial debe resolverse dentro de la propuesta reguladora o en incidente separado: identificar si los bienes son gananciales o propios y proponer criterio de liquidacion."
        )
    if "hijos" in scenarios:
        parts.append(
            "La situacion de los hijos debe quedar resuelta en la presentacion: cuidado personal, regimen comunicacional y alimentos, evitando dejar pretensiones abiertas sin propuesta concreta."
        )
    if "violencia" in scenarios:
        parts.append(
            "Si hay violencia, las medidas de proteccion tienen prioridad sobre el tramite de divorcio: exclusion del hogar, restriccion de acercamiento y toda medida cautelar que corresponda deben plantearse de forma autonoma o acumulada."
        )
    if case_profile.get("vulnerability"):
        parts.append(
            "Si la vulnerabilidad surge de los hechos, debe traducirse en estrategia concreta: acceso a justicia, cobertura minima y proteccion reforzada."
        )


def _narrative_cuidado_personal(parts: list[str], case_profile: dict) -> None:
    scenarios = set(case_profile.get("scenarios") or set())
    if "riesgo" in scenarios:
        parts.append(
            "Si existe riesgo para el nino, la estrategia debe priorizar medidas de proteccion urgentes antes que el debate sobre modalidad de cuidado: guarda provisoria, intervencion de organismo de proteccion o medida cautelar."
        )
    elif "cambio_cuidado" in scenarios:
        parts.append(
            "El cambio de cuidado personal exige acreditar modificacion sustancial de circunstancias: no basta la sola voluntad del progenitor sino un cambio factico relevante que afecte el interes superior del nino."
        )
    else:
        parts.append(
            "En cuidado personal el eje es demostrar donde esta el centro de vida del nino, como funciona el esquema actual de convivencia y por que la modalidad propuesta responde al interes superior."
        )
    if "cuidado_compartido" in scenarios:
        parts.append(
            "El cuidado compartido requiere acreditar viabilidad practica: proximidad de domicilios, acuerdos de organizacion y capacidad de ambos progenitores para sostener el esquema."
        )
    if "cuidado_unipersonal" in scenarios:
        parts.append(
            "El cuidado unipersonal debe justificarse con razones concretas de interes superior: no alcanza con la sola convivencia actual si no se explica por que la otra modalidad no resulta viable."
        )
    if case_profile.get("vulnerability"):
        parts.append(
            "Si la vulnerabilidad surge de los hechos, debe traducirse en estrategia concreta: proteccion reforzada y acceso a justicia."
        )


def _narrative_regimen_comunicacional(parts: list[str], case_profile: dict) -> None:
    scenarios = set(case_profile.get("scenarios") or set())
    if "impedimento_contacto" in scenarios:
        parts.append(
            "Si hay impedimento de contacto, la estrategia debe arrancar por medidas cautelares o audiencia inmediata para restablecer el vinculo, antes que el debate sobre el regimen definitivo."
        )
    elif "revinculacion" in scenarios:
        parts.append(
            "La revinculacion exige un plan progresivo: contacto supervisado, eventual intervencion de equipo tecnico y ampliacion gradual, sin forzar un regimen amplio de entrada."
        )
    else:
        parts.append(
            "En regimen comunicacional el planteo debe ser concreto: dias, horarios, modalidad de contacto, pernocte si corresponde, y distribucion de vacaciones y feriados."
        )
    if "modificacion" in scenarios:
        parts.append(
            "La modificacion del regimen exige acreditar cambio de circunstancias posterior al regimen vigente: no basta la sola disconformidad."
        )
    if case_profile.get("urgency_level") == "high":
        parts.append(
            "La urgencia justifica solicitar audiencia inmediata o habilitacion de dia y hora para garantizar el contacto sin demora."
        )
    if case_profile.get("vulnerability"):
        parts.append(
            "Si la vulnerabilidad surge de los hechos, debe traducirse en estrategia concreta: proteccion reforzada y acceso a justicia."
        )


def _narrative_conflicto_patrimonial(parts: list[str], case_profile: dict) -> None:
    scenarios = set(case_profile.get("scenarios") or set())
    parts.append(
        "En conflicto patrimonial el escrito debe evitar formulas genericas y concentrarse en titularidad, origen del bien, regimen aplicable y pretension concreta de particion, liquidacion o adjudicacion."
    )
    if "bien_ganancial" in scenarios:
        parts.append(
            "Si el bien es ganancial, corresponde encuadrar en liquidacion de la sociedad conyugal o comunidad de ganancias segun el momento de adquisicion y el estado del vinculo."
        )
    if "bien_heredado" in scenarios:
        parts.append(
            "Si el bien proviene de herencia, la estrategia debe separar porcion hereditaria de ganancialidad y definir si la via es particion sucesoria o reclamo entre conyuges."
        )
    if "cotitularidad" in scenarios:
        parts.append(
            "La cotitularidad debe acreditarse con titulo y estado registral; si hay condominio, la via es la accion de division o el acuerdo de adjudicacion."
        )
    if "conflicto" in scenarios and "acuerdo" not in scenarios:
        parts.append(
            "Sin acuerdo, la salida es judicial: demanda de division de condominio, liquidacion de sociedad conyugal o la via que corresponda al tipo de bien y regimen."
        )
    if case_profile.get("urgency_level") == "high":
        parts.append(
            "Si hay riesgo de enajenacion o deterioro, solicitar inhibicion general, anotacion de litis o embargo preventivo antes de que el bien se pierda."
        )


def _narrative_opening(
    *,
    domain: str,
    scenarios: set[str],
    risk_level: str,
    evidence_posture: str,
    query: str,
) -> str:
    if domain == "divorcio":
        if "conjunto" in scenarios:
            return "La estrategia debe presentarse como un cierre ordenado del vinculo, con foco en la homologacion inmediata y en evitar observaciones sobre el convenio."
        return "La estrategia debe separar con claridad la disolucion del vinculo de los efectos accesorios para no contaminar el avance principal del divorcio."
    if domain == "alimentos":
        if risk_level == "alto":
            return "La narrativa debe ser de tutela inmediata: incumplimiento actual, necesidad concreta y pedido operativo de cuota o aseguramiento."
        if evidence_posture == "fragil":
            return "La narrativa debe ser precisa y austera: pocos hechos decisivos, gastos trazables y un pedido que no dependa de afirmaciones amplias."
        return "La narrativa debe mostrar necesidad actual y capacidad contributiva desde hechos verificables, evitando desarrollos abstractos sobre deberes alimentarios."
    if domain == "cuidado_personal":
        return "La estrategia debe girar alrededor del interes superior, el centro de vida y la estabilidad cotidiana, no de afirmaciones parentales generales."
    if domain == "regimen_comunicacional":
        return "La narrativa debe convertir el conflicto en un esquema ejecutable de contacto, con medidas inmediatas si el vinculo ya esta obstruido."
    if domain == "conflicto_patrimonial":
        return "La narrativa debe construirse como disputa sobre titularidad y remedio concreto, evitando formulas abiertas sobre bienes sin destino procesal definido."
    return f"Estrategia inicial sobre '{query}': conviene fijar hechos decisivos, encuadre normativo y riesgo principal antes de expandir el planteo."


def _blocking_factor_narrative_opening(procedural_case_state: dict[str, Any]) -> str:
    blocking = str(procedural_case_state.get("blocking_factor") or "").strip().lower()
    readiness = str(procedural_case_state.get("execution_readiness") or "").strip().lower()
    phase = str(procedural_case_state.get("procedural_phase") or "").strip()

    _BLOCKING_NARRATIVES = {
        "service": (
            "El expediente se encuentra bloqueado por falta de notificacion. "
            "Debe priorizarse el diligenciamiento de la cedula, el control de su recepcion "
            "y la verificacion de cumplimiento antes de cualquier otra actuacion."
        ),
        "competence": (
            "El expediente enfrenta un planteo de competencia que paraliza el avance. "
            "Debe resolverse la cuestion de competencia — plantear o contestar la incompetencia "
            "e impulsar su resolucion — antes de acumular actividad sobre el fondo."
        ),
        "evidence": (
            "El expediente esta trabado por deficit probatorio. "
            "Debe priorizarse la produccion de prueba pendiente y la ampliacion de la documental "
            "antes de expandir pretensiones o solicitar medidas que no tienen sustento actual."
        ),
        "execution": (
            "El expediente ya tiene derecho reconocido pero esta trabado en la etapa de cumplimiento. "
            "Debe priorizarse el libramiento de oficios, la traba de embargos "
            "y toda medida concreta de ejecucion para materializar lo resuelto."
        ),
        "administrative_delay": (
            "El expediente sufre demora operativa que no responde a un deficit juridico sino administrativo. "
            "Debe priorizarse el seguimiento del tramite, la reiteracion de oficios pendientes "
            "y el impulso de despacho para destrabar el avance."
        ),
    }

    narrative = _BLOCKING_NARRATIVES.get(blocking, "")
    if narrative:
        # Append readiness tone
        if readiness == "bloqueado_procesalmente":
            narrative += " La situacion procesal exige corregir el bloqueo antes de cualquier avance sustantivo."
        elif readiness == "requiere_impulso_procesal":
            narrative += " El expediente requiere impulso procesal concreto para retomar su curso."
        elif readiness == "listo_para_avanzar":
            narrative += " Una vez removido el obstaculo, el expediente esta en condiciones de avanzar."
        return narrative

    # No blocking but readiness alone sets tone
    if readiness == "bloqueado_procesalmente":
        return (
            "El expediente se encuentra procesalmente bloqueado. "
            "Debe identificarse y removerse el factor de bloqueo antes de impulsar el reclamo de fondo."
        )
    if readiness == "requiere_impulso_procesal":
        if phase:
            return f"El expediente se encuentra en fase de {phase} y requiere impulso procesal para avanzar."
        return "El expediente requiere impulso procesal concreto para retomar su curso normal."

    return ""


def _resolve_evidence_posture(case_profile: dict, case_theory: dict, conflict: dict) -> str:
    evidence_needs = len(case_theory.get("evidentiary_needs") or [])
    recommended_actions = len(conflict.get("recommended_evidence_actions") or [])
    if case_profile.get("needs_proof_strengthening") or evidence_needs >= 3:
        return "fragil"
    if recommended_actions or evidence_needs:
        return "intermedia"
    return "solida"


def _resolve_tension_line(risk_level: str, evidence_posture: str) -> str:
    if risk_level == "alto" and evidence_posture == "fragil":
        return "El planteo debe avanzar con tono defensivo: pedir lo necesario para preservar posicion, pero sin sobreprometer exito mientras falten anclajes criticos."
    if risk_level == "alto":
        return "El caso exige una narrativa de contencion del dano procesal: cada afirmacion relevante debe venir anclada en prueba ya disponible o de produccion inmediata."
    if evidence_posture == "fragil":
        return "La debilidad no esta en el encuadre sino en la demostracion: conviene limitar el planteo a lo que hoy puede probarse con densidad suficiente."
    if risk_level == "medio":
        return "El margen de avance existe, pero depende de ordenar primero los hechos que hoy podrian abrir objeciones evitables."
    return ""


# ---------------------------------------------------------------------------
# Conflict summary
# ---------------------------------------------------------------------------

def _build_conflict_summary(
    *,
    case_profile: dict,
    case_theory: dict,
    conflict: dict,
    jurisprudence_guard: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    labels = [
        ("Eje del conflicto a resolver", "core_dispute"),
        ("Punto factico mas favorable para sostener la pretension", "strongest_point"),
        ("Vulnerabilidad critica que puede comprometer el resultado si no se cubre", "most_vulnerable_point"),
    ]
    for label, key in labels:
        text = str(conflict.get(key) or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    for item in (conflict.get("recommended_evidence_actions") or [])[:3]:
        text = str(item).strip()
        if text:
            lines.append(f"Accion probatoria a ejecutar sin demora: {text}")

    domain = case_profile.get("case_domain")
    scenarios = set(case_profile.get("scenarios") or set())

    if domain == "alimentos" or case_profile.get("is_alimentos"):
        _conflict_summary_alimentos(lines, scenarios)
    elif domain == "divorcio":
        _conflict_summary_divorcio(lines, scenarios)
    elif domain == "cuidado_personal":
        _conflict_summary_cuidado_personal(lines, scenarios)
    elif domain == "regimen_comunicacional":
        _conflict_summary_regimen_comunicacional(lines, scenarios)
    elif domain == "conflicto_patrimonial":
        _conflict_summary_conflicto_patrimonial(lines, scenarios)

    if jurisprudence_guard["source_quality"] == "real" and jurisprudence_guard["strength"] == "strong" and lines:
        lines.append("Los precedentes reales disponibles refuerzan este planteo y deben invocarse de forma directa en la presentacion.")
    patrimonial = _detect_patrimonial_conflict(case_theory, conflict, case_profile)
    if patrimonial["detected"]:
        lines.append("Conflicto patrimonial detectado: no corresponde responder con formula generica sino ordenar titularidad, origen del bien y eventual liquidacion.")
        lines.append("Orientacion estrategica minima: explorar convenio de adjudicacion, liquidacion de comunidad o gananciales, o particion/condominio segun como este estructurada la titularidad.")
        for question in patrimonial["missing_questions"]:
            lines.append(f"Pregunta critica pendiente: {question}")
    return lines


def _conflict_summary_alimentos(lines: list[str], scenarios: set[str]) -> None:
    if "incumplimiento" in scenarios:
        lines.append("Incumplimiento a dejar explicitado: falta de pago o aportes insuficientes del alimentante.")
    if "vivienda" in scenarios:
        lines.append("La vivienda o el alquiler pueden integrar el contenido alimentario si eso surge del caso.")
    if "mixto_conyuge" in scenarios:
        lines.append("La formulacion debe separar rubros de hijos y de conyuge para evitar solapamientos o confusiones.")
    if "ascendientes" in scenarios:
        lines.append("Debe explicarse la razon por la cual el reclamo se desplaza subsidiariamente hacia ascendientes.")
    if "hijo_mayor_estudiante" in scenarios:
        lines.append("El conflicto principal debe formularse como continuidad de asistencia para hijo mayor estudiante, no como alimentos estandar.")
    if "hijo_mayor_no_estudia" in scenarios:
        lines.append("El conflicto principal debe formularse como limite o cese de cuota para mayor de 21 que no estudia, sin mezclar art. 663 CCyC.")


def _conflict_summary_divorcio(lines: list[str], scenarios: set[str]) -> None:
    if "bienes" in scenarios:
        lines.append("El conflicto patrimonial debe definirse dentro de la propuesta reguladora: inventario, valuacion y criterio de adjudicacion.")
    if "hijos" in scenarios:
        lines.append("La situacion de los hijos es un eje del conflicto que debe resolverse en la misma presentacion: cuidado, comunicacion y alimentos.")
    if "violencia" in scenarios:
        lines.append("La violencia condiciona todo el planteo: las medidas de proteccion son previas y autonomas respecto del tramite de divorcio.")
    if "convenio_regulador" in scenarios:
        lines.append("El convenio regulador debe cubrir todos los efectos del divorcio; un convenio incompleto puede ser rechazado o generar incidentes posteriores.")


def _conflict_summary_cuidado_personal(lines: list[str], scenarios: set[str]) -> None:
    if "centro_de_vida" in scenarios:
        lines.append("El centro de vida es el dato factico determinante: acreditar arraigo, continuidad y estabilidad del nino en su entorno actual.")
    if "riesgo" in scenarios:
        lines.append("La situacion de riesgo debe quedar documentada con prueba concreta antes de solicitar cambio de cuidado o medida de proteccion.")
    if "cambio_cuidado" in scenarios:
        lines.append("El cambio de cuidado exige demostrar que las circunstancias cambiaron de forma sustancial respecto del regimen vigente.")
    if "cuidado_unipersonal" in scenarios:
        lines.append("El cuidado unipersonal debe fundarse en razones de interes superior concretas, no en la sola convivencia actual.")
    if "cuidado_compartido" in scenarios:
        lines.append("El cuidado compartido necesita acreditar viabilidad operativa y cooperacion entre ambos progenitores.")


def _conflict_summary_regimen_comunicacional(lines: list[str], scenarios: set[str]) -> None:
    if "impedimento_contacto" in scenarios:
        lines.append("El impedimento de contacto es la vulnerabilidad central: debe probarse con precision y traducirse en medida cautelar inmediata.")
    if "revinculacion" in scenarios:
        lines.append("La revinculacion exige un abordaje progresivo: no forzar contacto amplio de entrada sino construir gradualmente.")
    if "fijacion" in scenarios:
        lines.append("La fijacion del regimen debe incluir esquema concreto: dias, horarios, lugar de retiro y entrega, pernocte y vacaciones.")
    if "modificacion" in scenarios:
        lines.append("La modificacion debe justificarse con cambio de circunstancias relevante; la sola disconformidad no alcanza.")


def _conflict_summary_conflicto_patrimonial(lines: list[str], scenarios: set[str]) -> None:
    lines.append("Existe un conflicto patrimonial relevante.")
    if "bien_ganancial" in scenarios:
        lines.append("El caracter ganancial del bien debe acreditarse con titulo, fecha de adquisicion y estado del vinculo matrimonial al momento de la compra.")
    if "bien_heredado" in scenarios:
        lines.append("El bien heredado debe vincularse a la sucesion concreta: acreditar declaratoria de herederos, porcion y estado registral.")
    if "cotitularidad" in scenarios:
        lines.append("La cotitularidad debe probarse con titulo y datos registrales; sin esto, la pretension carece de base.")
    if "liquidacion" in scenarios:
        lines.append("La liquidacion requiere inventario, valuacion y criterio de adjudicacion; sin estos datos el planteo queda prematuro.")
    if "conflicto" in scenarios:
        lines.append("Sin acuerdo entre las partes, la via judicial es inevitable: enfocar la pretension concreta y la prueba de soporte.")


# ---------------------------------------------------------------------------
# Risk analysis
# ---------------------------------------------------------------------------

def _build_risk_analysis(
    *,
    case_profile: dict,
    case_theory: dict,
    conflict: dict,
    case_evaluation: dict,
    legal_decision: dict,
    procedural_plan,
    procedural_case_state: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    vulnerable = str(conflict.get("most_vulnerable_point") or "").strip()
    if vulnerable:
        lines.append(f"Vulnerabilidad que requiere cobertura inmediata: {vulnerable}")
    for item in (getattr(procedural_plan, "risks", None) or [])[:4]:
        text = str(item).strip()
        if text:
            lines.append(f"Riesgo procesal: {text}")
    for item in (case_evaluation.get("strategic_observations") or [])[:3]:
        text = str(item).strip()
        if text:
            lines.append(f"Observacion estrategica: {text}")
    for item in (case_evaluation.get("possible_scenarios") or [])[:2]:
        text = str(item).strip()
        if text:
            lines.append(f"Escenario posible: {text}")
    posture = str(legal_decision.get("strategic_posture") or "").strip()
    dominant_factor = str(legal_decision.get("dominant_factor") or "").strip()
    if posture == "cautelosa":
        lines.append("Marco de decision final: no conviene sobreactuar la pretension mientras subsistan riesgos o huecos de soporte.")
    if dominant_factor == "prueba":
        lines.append("Factor dominante: la prueba condiciona el resultado mas que la amplitud del encuadre normativo.")
    elif dominant_factor == "riesgo":
        lines.append("Factor dominante: el riesgo procesal actual manda sobre cualquier expansion prematura del planteo.")
    blocking_factor = str(procedural_case_state.get("blocking_factor") or "").strip()
    procedural_phase = str(procedural_case_state.get("procedural_phase") or "").strip()
    if blocking_factor and blocking_factor != "none":
        lines.append(f"Bloqueo procesal principal: {blocking_factor}.")
    if procedural_phase:
        lines.append(f"Fase procesal detectada: {procedural_phase}.")
    defense_status = str(procedural_case_state.get("defense_status") or "").strip()
    if defense_status == "defaulted":
        lines.append("Ventaja litigiosa: la contraparte aparece en rebeldia o con derecho defensivo decaido.")
    elif defense_status == "active":
        lines.append("Friccion procesal: existe defensa activa y controversia contradictoria.")

    domain = case_profile.get("case_domain")

    if (domain == "alimentos" or case_profile.get("is_alimentos")) and case_profile.get("needs_proof_strengthening"):
        lines.append("Riesgo material: si la prueba de gastos, ingresos o situacion de vulnerabilidad queda debil, la pretension pierde densidad inmediata.")

    if domain == "divorcio":
        scenarios = set(case_profile.get("scenarios") or set())
        if "bienes" in scenarios:
            lines.append("Riesgo material: si no se define el regimen de bienes en la propuesta reguladora, puede generar incidentes posteriores y demora.")
        if "hijos" in scenarios:
            lines.append("Riesgo material: dejar la situacion de los hijos sin resolver en la presentacion compromete la admisibilidad de la propuesta reguladora.")

    if domain == "cuidado_personal":
        scenarios = set(case_profile.get("scenarios") or set())
        if "cambio_cuidado" in scenarios:
            lines.append("Riesgo material: sin prueba de cambio sustancial de circunstancias, el pedido de cambio de cuidado puede ser rechazado.")
        if "riesgo" in scenarios:
            lines.append("Riesgo material: si la situacion de riesgo no queda documentada con prueba autonoma, la medida de proteccion pierde sustento.")

    if domain == "regimen_comunicacional":
        scenarios = set(case_profile.get("scenarios") or set())
        if "impedimento_contacto" in scenarios:
            lines.append("Riesgo material: si el impedimento no queda probado con elementos concretos, la medida cautelar puede ser denegada.")

    if domain == "conflicto_patrimonial":
        scenarios = set(case_profile.get("scenarios") or set())
        if case_profile.get("needs_proof_strengthening"):
            lines.append("Riesgo material: sin acreditar titularidad, origen y regimen del bien, la pretension patrimonial queda prematura.")

    patrimonial = _detect_patrimonial_conflict(case_theory, conflict, case_profile)
    if patrimonial["detected"] and patrimonial["missing_questions"]:
        lines.append("Riesgo material: sin precisar ganancialidad, origen del bien y estado del divorcio, la salida patrimonial queda prematura.")
    return lines


# ---------------------------------------------------------------------------
# Recommended actions
# ---------------------------------------------------------------------------

def _build_recommended_actions(
    *,
    case_profile: dict,
    case_theory: dict,
    conflict: dict,
    procedural_plan,
    procedural_case_state: dict[str, Any],
) -> list[str]:
    lines: list[str] = []
    domain = case_profile.get("case_domain")
    scenarios = set(case_profile.get("scenarios") or set())

    if domain == "alimentos" or case_profile.get("is_alimentos"):
        _actions_alimentos(lines, case_profile, scenarios)
    elif domain == "divorcio":
        _actions_divorcio(lines, case_profile, scenarios)
    elif domain == "cuidado_personal":
        _actions_cuidado_personal(lines, case_profile, scenarios)
    elif domain == "regimen_comunicacional":
        _actions_regimen_comunicacional(lines, case_profile, scenarios)
    elif domain == "conflicto_patrimonial":
        _actions_conflicto_patrimonial(lines, case_profile, scenarios)

    lines.extend(_procedural_state_actions(procedural_case_state))

    patrimonial = _detect_patrimonial_conflict(case_theory, conflict, case_profile, procedural_plan=procedural_plan)
    if patrimonial["detected"]:
        lines.append("Conflicto patrimonial detectado: la estrategia debe leerse como disputa patrimonial concreta y no como planteo abierto sobre bienes.")
        lines.append("No usar salida generica sobre bienes: enfocar el caso como conflicto patrimonial por inmueble en cotitularidad o adjudicacion.")
        lines.append("Determinar primero si el bien es ganancial o propio y si la solucion viable es convenio, liquidacion o demanda de division.")
        lines.append("Mantener una orientacion minima no conclusiva: convenio de adjudicacion si hay acuerdo, liquidacion de comunidad o gananciales si corresponde, o particion/condominio si la disputa es puramente dominial.")
        for question in patrimonial["missing_questions"]:
            lines.append(f"Relevar de inmediato: {question}")

    for item in (getattr(procedural_plan, "steps", None) or [])[:4]:
        action = str(getattr(item, "action", "") or "").strip()
        if action:
            lines.append(action)
    for item in (case_theory.get("recommended_line_of_action") or [])[:4]:
        text = str(item).strip()
        if text:
            lines.append(text)
    return _dedupe(lines)


def _actions_alimentos(lines: list[str], case_profile: dict, scenarios: set[str]) -> None:
    if {"cuota_provisoria", "incumplimiento"} & scenarios:
        lines.append("Empujar cuota provisoria con comprobantes concretos de gastos, esquema de cuidado e indicios utiles sobre capacidad contributiva.")
    if case_profile.get("vulnerability"):
        lines.append("Si el caso lo acredita, ordenar justicia gratuita y respaldo institucional util como ANSES, AUH, CBU o SMVM sin convertirlos en formulas vacias.")
    if case_profile.get("urgency_level") == "high":
        lines.append("Traducir la urgencia a medidas concretas de aseguramiento: embargo, retencion, habilitacion de dia y hora o pase a feria, solo si el cuadro factico ya lo sostiene.")
    if "ascendientes" in scenarios:
        lines.append("Explicar subsidiariedad, insuficiencia del obligado principal y eventual necesidad de litisexpensas antes de avanzar contra ascendientes.")
    if "hijo_mayor_estudiante" in scenarios:
        lines.append("Acompanhar regularidad academica, plan de estudios y continuidad de asistencia para no tratar el caso como alimentos estandar.")
    if "hijo_mayor_no_estudia" in scenarios:
        lines.append("Bloquear estrategias incompatibles con el caso: si tiene mas de 21 anos y no estudia, no corresponde pedir certificado de alumno regular.")
        lines.append("Precisar si trabaja, tiene ingresos propios o mantiene dependencia economica relevante antes de sostener continuidad de cuota.")
    if "hijo_18_21" in scenarios:
        lines.append("Precisar edad exacta, convivencia e ingresos propios para no mezclar el tramo 18 a 21 con hijo menor ni con hijo mayor estudiante.")
    if "mixto_conyuge" in scenarios:
        lines.append("Separar montos o rubros de hijos y conyuge en forma clara desde la pretension y la prueba.")


def _actions_divorcio(lines: list[str], case_profile: dict, scenarios: set[str]) -> None:
    if "hijos" in scenarios:
        lines.append("Ordenar primero cuidado personal, regimen comunicacional y alimentos de los hijos dentro de la propuesta reguladora.")
    if "unilateral" in scenarios:
        lines.append("Redactar propuesta reguladora unilateral con todos los efectos del divorcio (art. 438 CCyC): atribucion del hogar, bienes, alimentos y situacion de hijos.")
    if "conjunto" in scenarios:
        lines.append("Verificar que el convenio regulador conjunto cubra atribucion del hogar, regimen de bienes, alimentos y situacion de hijos.")
    if "hijos" in scenarios:
        lines.append("Incluir en la propuesta cuidado personal, regimen comunicacional y alimentos para los hijos.")
    if "bienes" in scenarios:
        lines.append("Inventariar bienes, definir caracter ganancial o propio y proponer criterio de liquidacion o adjudicacion.")
    if "violencia" in scenarios:
        lines.append("Solicitar de forma autonoma o acumulada las medidas de proteccion: exclusion del hogar, restriccion perimetral y toda cautelar que corresponda.")
    if case_profile.get("vulnerability"):
        lines.append("Gestionar justicia gratuita y acompanamiento institucional si la situacion de vulnerabilidad lo requiere.")


def _actions_cuidado_personal(lines: list[str], case_profile: dict, scenarios: set[str]) -> None:
    if "centro_de_vida" in scenarios:
        lines.append("Reunir prueba de centro de vida: constancias escolares, certificados medicos, testimonios de vecinos y todo elemento que acredite arraigo.")
    if "cambio_cuidado" in scenarios:
        lines.append("Documentar el cambio de circunstancias con precision: que cambio, cuando y como afecta al nino.")
    if "riesgo" in scenarios:
        lines.append("Solicitar medida de proteccion urgente con prueba autonoma de la situacion de riesgo: informes, denuncias previas, testimonios.")
    if "cuidado_compartido" in scenarios:
        lines.append("Acreditar viabilidad del cuidado compartido: proximidad de domicilios, organizacion propuesta y capacidad de ambos progenitores.")
    if "cuidado_unipersonal" in scenarios:
        lines.append("Justificar el cuidado unipersonal con razones concretas de interes superior y prueba de que la otra modalidad no resulta viable.")
    if case_profile.get("vulnerability"):
        lines.append("Gestionar proteccion reforzada y acceso a justicia si la situacion de vulnerabilidad lo requiere.")


def _actions_regimen_comunicacional(lines: list[str], case_profile: dict, scenarios: set[str]) -> None:
    if "impedimento_contacto" in scenarios:
        lines.append("Solicitar audiencia inmediata o medida cautelar para restablecer el contacto con prueba concreta del impedimento.")
    if "revinculacion" in scenarios:
        lines.append("Proponer plan de revinculacion progresiva: contacto supervisado, equipo tecnico y ampliacion gradual.")
    if "fijacion" in scenarios:
        lines.append("Presentar esquema concreto de regimen comunicacional: dias, horarios, lugar de retiro y entrega, pernocte y vacaciones.")
    if "modificacion" in scenarios:
        lines.append("Acreditar cambio de circunstancias que justifique la modificacion del regimen vigente.")
    if "pernocte" in scenarios:
        lines.append("Fundamentar el pernocte con condiciones de habitabilidad y edad del nino.")
    if "vacaciones" in scenarios:
        lines.append("Incluir distribucion de vacaciones, feriados y fechas especiales en la propuesta.")
    if case_profile.get("urgency_level") == "high":
        lines.append("Traducir la urgencia a pedido de audiencia inmediata o habilitacion de dia y hora.")


def _actions_conflicto_patrimonial(lines: list[str], case_profile: dict, scenarios: set[str]) -> None:
    lines.append("Evaluar vias para resolver el conflicto patrimonial (adjudicacion, liquidacion o division).")
    if "cotitularidad" in scenarios:
        lines.append("Acreditar cotitularidad con titulo y estado registral actualizado.")
    if "bien_ganancial" in scenarios:
        lines.append("Acreditar caracter ganancial con titulo, fecha de adquisicion y estado del vinculo matrimonial.")
    if "bien_propio" in scenarios:
        lines.append("Probar caracter propio con titulo anterior al matrimonio o causa de adquisicion gratuita.")
    if "bien_heredado" in scenarios:
        lines.append("Vincular el bien a la sucesion: declaratoria de herederos, porcion hereditaria y estado registral.")
    if "liquidacion" in scenarios:
        lines.append("Proponer inventario, valuacion actualizada y criterio de adjudicacion o division.")
    if "conflicto" in scenarios:
        lines.append("Plantear la pretension patrimonial con precision: que se pide, sobre que bien y con que fundamento.")
    if "acuerdo" in scenarios:
        lines.append("Verificar que el acuerdo cubra todos los bienes y sea susceptible de homologacion judicial.")
    if case_profile.get("urgency_level") == "high":
        lines.append("Solicitar medidas cautelares patrimoniales: inhibicion, anotacion de litis o embargo preventivo.")


# ---------------------------------------------------------------------------
# Procedural focus
# ---------------------------------------------------------------------------

def _build_procedural_focus(
    *,
    case_profile: dict,
    case_theory: dict,
    conflict: dict,
    legal_decision: dict,
    jurisprudence_guard: dict[str, Any],
    jurisprudence_analysis: dict[str, Any],
    procedural_case_state: dict[str, Any],
) -> list[str]:
    focus = [str(item).strip() for item in (case_profile.get("strategic_focus") or []) if str(item).strip()]

    source_quality = jurisprudence_guard["source_quality"]
    strength = jurisprudence_guard["strength"]
    if source_quality == "real" and strength == "strong":
        focus.append("integrar precedentes reales como respaldo directo del planteo")
    elif source_quality == "legacy":
        focus.append("usar jurisprudencia solo como apoyo secundario")
    elif source_quality in {"fallback", "none"}:
        focus.append("evitar presentar la base disponible como jurisprudencia consolidada")

    summary = str(jurisprudence_analysis.get("source_mode_summary") or "").strip()
    if summary:
        focus.append(summary)
    dominant_factor = str(legal_decision.get("dominant_factor") or "").strip()
    posture = str(legal_decision.get("strategic_posture") or "").strip()
    if dominant_factor == "jurisprudencia":
        focus.append("usar la jurisprudencia como factor de cierre del criterio decisorio, no como cita lateral")
    if posture == "cautelosa":
        focus.append("priorizar saneamiento probatorio y reduccion de riesgo")
        focus.append("priorizar saneamiento, cobertura probatoria y prevencion de rechazo antes de ampliar el planteo")
    elif posture == "agresiva":
        focus.append("priorizar avance de la pretension principal con apoyo normativo y probatorio ya suficiente")
    focus.extend(_procedural_state_focus(procedural_case_state))
    patrimonial = _detect_patrimonial_conflict(case_theory, conflict, case_profile)
    if patrimonial["detected"]:
        focus.append("evitar fallback generico y cerrar datos de titularidad, origen y estado del divorcio")
    return _dedupe(focus)


def _build_decision_alignment_notes(legal_decision: dict[str, Any]) -> list[str]:
    notes = [str(item).strip() for item in (legal_decision.get("decision_notes") or []) if str(item).strip()]
    return _dedupe(notes)


def _resolve_decision_line(strategic_posture: str, dominant_factor: str) -> str:
    if strategic_posture == "agresiva":
        if dominant_factor == "jurisprudencia":
            return "La decision final habilita una narrativa de avance: la jurisprudencia acompana y puede usarse como palanca expresa del planteo."
        return "La decision final habilita una narrativa de avance: corresponde empujar la pretension principal con foco en resultado y ejecucion."
    if strategic_posture == "cautelosa":
        if dominant_factor == "prueba":
            return "La decision final impone una narrativa de saneamiento: primero cerrar soporte probatorio y despues ampliar alcance."
        if dominant_factor == "riesgo":
            return "La decision final impone una narrativa de contencion: prevenir rechazo, objeciones y perdida de posicion procesal."
        if dominant_factor == "procesal":
            return "La decision final impone una narrativa de impulso procesal: remover bloqueos de tramite antes de forzar expansion del reclamo."
        if dominant_factor == "jurisprudencia":
            return "La decision final exige cautela porque la jurisprudencia disponible condiciona el alcance util del planteo."
        return "La decision final exige prudencia operativa: conviene depurar hechos, cobertura y pretension antes de forzar avance."
    if dominant_factor == "procesal":
        return "La decision final queda ordenada por la ejecutabilidad real del expediente y no por un deficit de merito juridico."
    if dominant_factor == "jurisprudencia":
        return "La decision final queda especialmente ordenada por la linea jurisprudencial recuperada, que debe notarse en el encuadre."
    return ""


def _resolve_procedural_state_line(procedural_case_state: dict[str, Any]) -> str:
    phase = str(procedural_case_state.get("procedural_phase") or "").strip()
    blocking = str(procedural_case_state.get("blocking_factor") or "").strip()
    defense_status = str(procedural_case_state.get("defense_status") or "").strip()
    enforcement = str(procedural_case_state.get("enforcement_signal") or "").strip()
    if blocking == "execution" or enforcement == "active":
        return "La prioridad real ya no es discutir el derecho sino insistir el tramite ejecutivo y remover fricciones operativas de cumplimiento."
    if blocking == "service":
        return "La prioridad real es notificar eficazmente y cerrar el problema de traslado antes de expandir la discusion de fondo."
    if blocking == "competence":
        return "La incidencia de competencia obliga a reencuadrar el impulso procesal sin perder de vista que el merito material puede seguir siendo favorable."
    if blocking == "evidence":
        return "El cuello de botella actual esta en la prueba y en la fijacion de hechos controvertidos dentro del expediente."
    if defense_status == "defaulted":
        return "La secuencia procesal muestra rebeldia o decaimiento del derecho, por lo que corresponde pedir pase a resolver sin desperdiciar esa ventaja litigiosa."
    if defense_status == "active":
        return "La defensa ya ingreso al expediente y la estrategia debe concentrarse en contestar frentes controvertidos concretos."
    if phase == "judgment":
        return "El expediente aparece en etapa de sentencia o posterior, por lo que la prioridad pasa por decision, notificacion y eventual ejecucion."
    return ""


def _procedural_state_focus(procedural_case_state: dict[str, Any]) -> list[str]:
    blocking = str(procedural_case_state.get("blocking_factor") or "").strip()
    defense_status = str(procedural_case_state.get("defense_status") or "").strip()
    enforcement = str(procedural_case_state.get("enforcement_signal") or "").strip()
    service_status = str(procedural_case_state.get("service_status") or "").strip()

    focus: list[str] = []
    if blocking == "execution" or enforcement == "active":
        focus.append("priorizar tramite ejecutivo, oficios y medidas de cumplimiento efectivo")
    if blocking == "service" or service_status == "pending":
        focus.append("priorizar notificacion valida, diligenciamiento y cierre del traslado")
    if blocking == "competence":
        focus.append("priorizar resolver competencia y evitar que el incidente procesal eclipse el merito material")
    if blocking == "evidence":
        focus.append("priorizar prueba util y fijar hechos controvertidos antes de ampliar el reclamo")
    if blocking == "administrative_delay":
        focus.append("priorizar destrabar demoras operativas y reiteraciones administrativas sin sobredimensionar el conflicto juridico")
    if defense_status == "defaulted":
        focus.append("priorizar pase a resolver por rebeldia o decaimiento del derecho de defensa")
    elif defense_status == "active":
        focus.append("priorizar replica, contradiccion y cierre de puntos litigiosos activos")
    return focus


def _procedural_state_actions(procedural_case_state: dict[str, Any]) -> list[str]:
    blocking = str(procedural_case_state.get("blocking_factor") or "").strip()
    defense_status = str(procedural_case_state.get("defense_status") or "").strip()
    enforcement = str(procedural_case_state.get("enforcement_signal") or "").strip()

    actions: list[str] = []
    if blocking == "service":
        actions.append("Impulsar notificacion efectiva, controlar cedulas y pedir pronto despacho del traslado si corresponde.")
    if blocking == "competence":
        actions.append("Atacar o encauzar la cuestion de competencia antes de seguir acumulando actividad estéril en el expediente.")
    if blocking == "evidence":
        actions.append("Reordenar prueba y fijar hechos controvertidos antes de pedir medidas expansivas.")
    if blocking == "execution" or enforcement == "active":
        actions.append("Insistir ejecucion, reiterar oficios utiles y pedir medidas concretas de cumplimiento.")
    if blocking == "administrative_delay":
        actions.append("Destrabar el expediente con impulso de despacho, control de oficios y saneamiento operativo.")
    if defense_status == "defaulted":
        actions.append("Pedir pase a resolver o decision inmediata aprovechando la rebeldia o el decaimiento del derecho.")
    elif defense_status == "active":
        actions.append("Responder la defensa y concentrar el litigio en los puntos realmente controvertidos.")
    return actions


# ---------------------------------------------------------------------------
# Secondary domain notes
# ---------------------------------------------------------------------------

def _build_secondary_domain_notes(case_profile: dict) -> list[str]:
    """Build notes for secondary (non-primary) domains detected in the case."""
    domains = case_profile.get("case_domains") or []
    if len(domains) <= 1:
        return []

    notes: list[str] = []
    for domain in domains[1:]:
        note = _SECONDARY_DOMAIN_NOTES.get(domain)
        if note:
            notes.append(note)
    return notes


_SECONDARY_DOMAIN_NOTES: dict[str, str] = {
    "alimentos": (
        "Pretension secundaria: alimentos. "
        "Verificar necesidades del alimentado, capacidad contributiva del alimentante "
        "e incluir pedido de cuota en la presentacion principal o como pretension acumulada."
    ),
    "cuidado_personal": (
        "Pretension secundaria: cuidado personal. "
        "Definir con quien convive el nino, acreditar centro de vida "
        "y proponer modalidad de cuidado dentro de la propuesta reguladora o en pretension autonoma."
    ),
    "regimen_comunicacional": (
        "Pretension secundaria: regimen comunicacional. "
        "Incluir esquema concreto de contacto (dias, horarios, pernocte, vacaciones) "
        "en la propuesta reguladora o como pretension independiente."
    ),
    "divorcio": (
        "Pretension secundaria: divorcio. "
        "El divorcio es el marco procesal que contiene las demas pretensiones; "
        "verificar que la propuesta reguladora cubra todos los efectos."
    ),
    "conflicto_patrimonial": (
        "Pretension secundaria: conflicto patrimonial. "
        "Identificar bienes en juego, definir caracter ganancial o propio "
        "y resolver si la via es liquidacion, particion o adjudicacion."
    ),
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


# ---------------------------------------------------------------------------
# Anti-contamination guard: divorce-primary cases
# ---------------------------------------------------------------------------

# Phrases that belong to the alimentos domain and must not appear in
# primary-block text when the case domain is divorcio *and* alimentos
# is not substantiated by concrete facts.
_ALIMENTOS_CONTAMINANT_TOKENS: tuple[str, ...] = (
    "cuota provisoria",
    "alimentante",
    "incumplimiento alimentario",
    "gastos del hijo",
    "gastos de la hija",
    "progenitor demandado",
    "partida de nacimiento del hijo",
    "monto de cuota",
    "retencion alimentaria",
    "cuota alimentaria",
    "deuda alimentaria",
)


def _has_alimentos_contaminant(text: str) -> bool:
    """Return True if text contains language that belongs to alimentos domain."""
    normalized = _normalize(text)
    return any(token in normalized for token in _ALIMENTOS_CONTAMINANT_TOKENS)


def _guard_divorce_primary_contamination(strategy: dict[str, Any], case_profile: dict[str, Any]) -> None:
    """When case_domain is 'divorcio' and alimentos is NOT a substantiated
    scenario (i.e. no concrete alimentos facts exist), remove alimentos-
    specific language from the primary strategy blocks.

    This prevents the strategy builder from contaminating the divorce
    narrative with cuota provisoria, alimentante, incumplimiento alimentario
    etc. when the user simply asked for a divorce.

    When 'hijos' IS a divorce scenario, generic references to 'resolver
    alimentos de los hijos' are allowed — they are part of the propuesta
    reguladora, not an alimentos-primary strategy.
    """
    domain = str(case_profile.get("case_domain") or "").strip()
    if domain != "divorcio":
        return

    scenarios = set(case_profile.get("scenarios") or set())
    # If the divorce case legitimately includes explicit alimentos facts
    # (incumplimiento, cuota_provisoria, etc.) don't filter.
    alimentos_substantiated = bool(scenarios & {
        "incumplimiento", "cuota_provisoria", "ascendientes",
        "hijo_mayor", "hijo_mayor_estudiante", "mixto_conyuge",
    })
    if alimentos_substantiated:
        return

    # Filter contaminants from list-based sections
    for key in ("conflict_summary", "recommended_actions", "risk_analysis", "procedural_focus"):
        section = strategy.get(key)
        if isinstance(section, list):
            strategy[key] = [
                item for item in section
                if not _has_alimentos_contaminant(item)
            ]

    # Filter contaminant paragraphs from narrative
    narrative = strategy.get("strategic_narrative", "")
    if isinstance(narrative, str) and _has_alimentos_contaminant(narrative):
        paragraphs = narrative.split("\n\n")
        clean = [p for p in paragraphs if not _has_alimentos_contaminant(p)]
        strategy["strategic_narrative"] = "\n\n".join(clean)


def _apply_sensitive_strategy_validations(strategy: dict[str, Any], query: str, case_profile: dict[str, Any]) -> None:
    normalized_query = _normalize(query)
    scenarios = set(case_profile.get("scenarios") or set())

    # --- Anti-contamination: divorce primary must not be overridden by alimentos language ---
    _guard_divorce_primary_contamination(strategy, case_profile)

    if "hijo_mayor_no_estudia" in scenarios or "no estudia" in normalized_query:
        strategy["recommended_actions"] = [
            item for item in strategy.get("recommended_actions", [])
            if "regularidad academica" not in item.casefold() and "alumno regular" not in item.casefold()
        ]
        strategy["procedural_focus"] = [
            item for item in strategy.get("procedural_focus", [])
            if "regularidad academica" not in item.casefold()
        ]
        strategy["risk_analysis"] = _dedupe(strategy.get("risk_analysis", []) + [
            "Validacion estrategica: se bloqueo toda sugerencia academica porque la consulta indica que no estudia.",
        ])

    if any(token in normalized_query for token in ("no trabaja", "desocupado", "desocupada", "sin empleo", "no tiene trabajo")):
        strategy["risk_analysis"] = _dedupe(strategy.get("risk_analysis", []) + [
            "Validacion estrategica: si no trabaja, no debe asumirse autosustento por la sola edad y corresponde precisar ingresos reales.",
        ])

    if "sin ingresos formales" in normalized_query:
        strategy["risk_analysis"] = _dedupe(strategy.get("risk_analysis", []) + [
            "Validacion estrategica: no asumir embargo directo sin explicar antes de donde surgen ingresos o bienes embargables.",
        ])


def _detect_patrimonial_conflict(
    case_theory: dict[str, Any],
    conflict: dict[str, Any],
    case_profile: dict[str, Any],
    procedural_plan: Any | None = None,
) -> dict[str, Any]:
    text = _normalize(" ".join([
        str(case_theory.get("primary_theory") or ""),
        str(case_theory.get("objective") or ""),
        " ".join(str(item) for item in (case_theory.get("likely_points_of_conflict") or [])),
        str(conflict.get("core_dispute") or ""),
        str(conflict.get("strongest_point") or ""),
        str(conflict.get("most_vulnerable_point") or ""),
    ]))

    score = 0
    if any(token in text for token in ("cotitularidad", "cotitular", "condominio")):
        score += 2
    if any(token in text for token in ("casa", "inmueble", "vivienda", "propiedad")):
        score += 1
    if any(token in text for token in ("ex esposo", "ex esposa", "divorcio", "conyuge")):
        score += 1
    if any(token in text for token in ("herencia", "heredado", "ganancial", "propio")):
        score += 1
    if any(token in text for token in ("division", "adjudicacion", "renuncia", "liquidacion")):
        score += 1

    missing_questions: list[str] = []
    if score >= 3:
        if "ganancial" not in text and "propio" not in text:
            missing_questions.append("el bien es ganancial o propio")
        if "antes del matrimonio" not in text and "durante el matrimonio" not in text:
            missing_questions.append("fue adquirido antes o durante el matrimonio")
        if "herencia" not in text and "compra" not in text and "compraventa" not in text:
            missing_questions.append("proviene de herencia o de compra")
        if "divorcio previo" not in text and "ya divorciados" not in text and "ya nos divorciamos" not in text:
            missing_questions.append("existe divorcio previo o no")
        if "acuerdo" not in text and "conflicto" not in text and "se niega" not in text:
            missing_questions.append("hay acuerdo o conflicto")

    return {"detected": score >= 3, "missing_questions": missing_questions}


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(char for char in nfkd if not unicodedata.combining(char))


# ---------------------------------------------------------------------------
# Output sanitization — removes internal noise, deduplicates, reorders
# ---------------------------------------------------------------------------

_NOISE_PATTERNS: list[str] = [
    "no se encontro un patron",
    "no se encontro un modelo aplicable",
    "fallback generico",
    "no existe handler",
    "modelo no aplicable",
    "se rechazaron",
    "no hay coincidencias en corpus",
    "generic",
    "fallback",
    "internal_fallback",
]


def _is_noise(text: str) -> bool:
    normalized = _normalize(text)
    return any(pattern in normalized for pattern in _NOISE_PATTERNS)


def _sanitize_text_block(text: str) -> str:
    lines = text.split("\n\n")
    clean = [line for line in lines if line.strip() and not _is_noise(line)]
    return "\n\n".join(clean)


def _sanitize_list(items: list[str]) -> list[str]:
    return [item for item in items if item.strip() and not _is_noise(item)]


def _dedupe_cross_sections(strategy: dict[str, Any]) -> None:
    seen: set[str] = set()
    list_keys = [
        "conflict_summary",
        "recommended_actions",
        "risk_analysis",
        "procedural_focus",
        "legal_decision_alignment",
        "secondary_domain_notes",
    ]
    for key in list_keys:
        section = strategy.get(key)
        if not isinstance(section, list):
            continue
        deduped: list[str] = []
        for item in section:
            normalized = _normalize(str(item).strip())
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(item)
        strategy[key] = deduped


_SECTION_ORDER: list[str] = [
    "strategy_mode",
    "strategic_narrative",
    "conflict_summary",
    "recommended_actions",
    "risk_analysis",
    "procedural_focus",
    "legal_decision_alignment",
    "secondary_domain_notes",
]


def sanitize_strategy_output(strategy: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}

    narrative = strategy.get("strategic_narrative", "")
    if isinstance(narrative, str):
        clean["strategic_narrative"] = _sanitize_text_block(narrative)
    else:
        clean["strategic_narrative"] = narrative

    for key in ("conflict_summary", "recommended_actions", "risk_analysis",
                "procedural_focus", "legal_decision_alignment", "secondary_domain_notes"):
        section = strategy.get(key)
        if isinstance(section, list):
            clean[key] = _dedupe(_sanitize_list(section))
        else:
            clean[key] = section

    _dedupe_cross_sections(clean)

    for extra_key in strategy:
        if extra_key not in clean:
            clean[extra_key] = strategy[extra_key]

    ordered: dict[str, Any] = {}
    for key in _SECTION_ORDER:
        if key in clean:
            ordered[key] = clean[key]
    for key in clean:
        if key not in ordered:
            ordered[key] = clean[key]

    return ordered


def dedupe_domains(domains: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for d in domains:
        key = _normalize(str(d).strip())
        if key and key not in seen:
            seen.add(key)
            result.append(str(d).strip())
    return result
