# backend/app/services/legal_reasoning_service.py
from __future__ import annotations


def build_legal_reasoning(context: dict) -> dict:
    """
    Construye un análisis de razonamiento jurídico estructurado a partir del contexto del caso.

    Input context keys:
        facts             (str)  — hechos relevantes del caso
        detected_intent   (str)  — intención detectada del usuario
        legal_area        (str)  — área jurídica (divorcio, alimentos, laboral, etc.)
        urgency_level     (str)  — "high"/"alta" | "medium"/"media" | "low"/"baja"
        has_children      (bool) — hay hijos menores involucrados
        agreement_level   (str)  — "full"/"completo" | "partial"/"parcial" | "none" | None
        blocking_factors  (str)  — factor/es de bloqueo procesal o "" / "none"
        procedural_posture (str) — postura procesal actual

    Output dict:
        case_summary         (str)
        legal_framing        (str)
        scenarios            (list[dict])
        recommended_strategy (str)
        reasoning_confidence (float 0-1)
    """
    facts = str(context.get("facts") or "").strip()
    detected_intent = str(context.get("detected_intent") or "").strip()
    legal_area = str(context.get("legal_area") or "").strip()
    urgency_level = str(context.get("urgency_level") or "low").strip().lower()
    has_children = bool(context.get("has_children"))
    agreement_level = str(context.get("agreement_level") or "none").strip().lower()
    blocking_factors = str(context.get("blocking_factors") or "").strip()
    procedural_posture = str(context.get("procedural_posture") or "").strip()

    has_blocking = bool(blocking_factors and blocking_factors.lower() not in ("", "none"))
    is_urgent = urgency_level in ("high", "alta")
    has_agreement = agreement_level in ("full", "partial", "completo", "parcial")

    case_summary = _build_case_summary(
        legal_area=legal_area,
        facts=facts,
        procedural_posture=procedural_posture,
        has_children=has_children,
    )
    legal_framing = _build_legal_framing(
        legal_area=legal_area,
        detected_intent=detected_intent,
        has_children=has_children,
    )
    scenarios = _build_scenarios(
        legal_area=legal_area,
        has_agreement=has_agreement,
        is_urgent=is_urgent,
        has_blocking=has_blocking,
        blocking_factors=blocking_factors,
        has_children=has_children,
    )
    recommended_strategy = _build_recommended_strategy(scenarios, is_urgent=is_urgent)
    reasoning_confidence = _compute_confidence(
        legal_area=legal_area,
        facts=facts,
        has_blocking=has_blocking,
        scenarios=scenarios,
    )

    return {
        "case_summary": case_summary,
        "legal_framing": legal_framing,
        "scenarios": scenarios,
        "recommended_strategy": recommended_strategy,
        "reasoning_confidence": reasoning_confidence,
    }


# ── Builders ──────────────────────────────────────────────────────────────────


def _build_case_summary(
    *,
    legal_area: str,
    facts: str,
    procedural_posture: str,
    has_children: bool,
) -> str:
    area_label = legal_area or "derecho de familia"
    parts = [f"Caso en materia de {area_label}."]
    if procedural_posture:
        parts.append(f"Postura procesal: {procedural_posture}.")
    if has_children:
        parts.append("Involucra hijos menores, lo que activa el régimen de protección especial.")
    if facts:
        snippet = facts[:200].rstrip()
        if len(facts) > 200:
            snippet += "..."
        parts.append(f"Hechos relevantes: {snippet}")
    return " ".join(parts)


def _build_legal_framing(
    *,
    legal_area: str,
    detected_intent: str,
    has_children: bool,
) -> str:
    area = (legal_area or "").lower()

    if "divorcio" in area:
        base = (
            "El régimen de divorcio argentino (arts. 435-438 CCyC) es incausado y unilateral: "
            "cualquier cónyuge puede peticionarlo sin expresar causa. "
        )
        if has_children:
            base += (
                "La presencia de hijos menores impone resolver previamente "
                "cuidado personal, régimen de comunicación y cuota alimentaria (art. 438 CCyC). "
            )
        base += (
            "La vía consensuada reduce tiempos y conflicto; "
            "la unilateral resguarda autonomía cuando no hay acuerdo."
        )
        return base

    if "alimentos" in area:
        base = (
            "La obligación alimentaria surge de la ley y no requiere demostrar culpa. "
            "El proceso puede iniciarse por vía incidental o autónoma. "
        )
        if has_children:
            base += "Para hijos menores aplica el principio de interés superior del niño."
        return base

    if "laboral" in area or "trabajo" in area:
        return (
            "El vínculo laboral está regulado por la LCT y los convenios colectivos aplicables. "
            "La existencia de relación de dependencia es el punto de partida para determinar derechos."
        )

    if "penal" in area:
        return (
            "En materia penal rige el principio de legalidad y la garantía de defensa en juicio. "
            "Es fundamental determinar el tipo penal aplicable y las circunstancias modificatorias."
        )

    intent_note = f" El objetivo declarado es: {detected_intent}." if detected_intent else ""
    return f"El caso se encuadra en materia de {legal_area or 'derecho civil'}.{intent_note}"


def _build_scenarios(
    *,
    legal_area: str,
    has_agreement: bool,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
    has_children: bool,
) -> list[dict]:
    area = (legal_area or "").lower()

    if "divorcio" in area:
        return _scenarios_divorcio(
            has_agreement=has_agreement,
            is_urgent=is_urgent,
            has_blocking=has_blocking,
            blocking_factors=blocking_factors,
            has_children=has_children,
        )

    if "alimentos" in area:
        return _scenarios_alimentos(
            is_urgent=is_urgent,
            has_blocking=has_blocking,
            blocking_factors=blocking_factors,
        )
    if "laboral" in area or "trabajo" in area:
        return _scenarios_laboral(
            is_urgent=is_urgent,
            has_blocking=has_blocking,
        )

    return _scenarios_generic(
        has_agreement=has_agreement,
        is_urgent=is_urgent,
        has_blocking=has_blocking,
        blocking_factors=blocking_factors,
    )


def _scenarios_divorcio(
    *,
    has_agreement: bool,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
    has_children: bool,
) -> list[dict]:
    blocking_note = f" Existe bloqueo procesal ({blocking_factors}) que puede demorar el proceso." if has_blocking else ""
    children_note = " Requiere convenio regulador sobre hijos antes de la sentencia." if has_children else ""

    # Blocking always reduces viability, even when there is agreement
    consensual_viability = "baja" if has_blocking else ("alta" if has_agreement else "media")
    s_consensual = {
        "name": "Divorcio consensuado",
        "description": (
            "Ambas partes presentan el convenio regulador acordado. "
            "Es la vía más rápida y menos conflictiva."
            f"{children_note}{blocking_note}"
        ),
        "viability": consensual_viability,
        "risk": "bajo" if has_agreement else "medio",
        "recommended": has_agreement and not has_blocking and not is_urgent,
    }

    unilateral_viability = "media" if has_blocking else "alta"
    s_unilateral = {
        "name": "Divorcio unilateral",
        "description": (
            "Un solo cónyuge peticiona el divorcio. "
            "El otro puede presentar su propio convenio regulador o impugnar el propuesto."
            f"{blocking_note}"
        ),
        "viability": unilateral_viability,
        "risk": "medio" if has_blocking else "bajo",
        "recommended": not has_agreement or is_urgent,
    }

    scenarios = [s_consensual, s_unilateral]

    # Offer mediation only when there's no blocking, no urgency and no agreement yet
    if not has_blocking and not is_urgent and not has_agreement:
        scenarios.append({
            "name": "Mediación previa",
            "description": (
                "Intentar acuerdo mediante mediación familiar antes de iniciar la acción. "
                "Puede reducir costos y fortalecer el convenio regulador."
            ),
            "viability": "media",
            "risk": "bajo",
            "recommended": False,
        })

    return _ensure_single_recommended(scenarios)


def _scenarios_alimentos(
    *,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
) -> list[dict]:
    blocking_note = f" Bloqueo procesal: {blocking_factors}." if has_blocking else ""

    s_incidental = {
        "name": "Cuota alimentaria incidental",
        "description": (
            "Solicitar alimentos como medida cautelar o incidente dentro del proceso principal. "
            "Inicio rápido, efecto inmediato."
            f"{blocking_note}"
        ),
        "viability": "baja" if has_blocking else "alta",
        "risk": "bajo",
        "recommended": is_urgent,
    }
    s_autonomo = {
        "name": "Juicio autónomo de alimentos",
        "description": (
            "Iniciar juicio de alimentos de manera independiente. "
            "Permite reclamar retroactivos desde la interposición."
            f"{blocking_note}"
        ),
        "viability": "baja" if has_blocking else "alta",
        "risk": "medio" if has_blocking else "bajo",
        "recommended": not is_urgent,
    }

    return _ensure_single_recommended([s_incidental, s_autonomo])


def _scenarios_laboral(*, is_urgent: bool, has_blocking: bool) -> list[dict]:
    s_conciliation = {
        "name": "Conciliación laboral (SECLO)",
        "description": (
            "Instancia previa obligatoria de conciliación ante el SECLO. "
            "Rápida y puede evitar juicio."
        ),
        "viability": "alta" if not has_blocking else "media",
        "risk": "bajo",
        "recommended": not is_urgent,
    }
    s_demanda = {
        "name": "Demanda laboral",
        "description": (
            "Acción judicial por despido, derechos laborales o indemnizaciones. "
            "Requiere agotamiento de la instancia conciliatoria previa."
        ),
        "viability": "media" if has_blocking else "alta",
        "risk": "medio",
        "recommended": is_urgent,
    }
    return _ensure_single_recommended([s_conciliation, s_demanda])


def _scenarios_generic(
    *,
    has_agreement: bool,
    is_urgent: bool,
    has_blocking: bool,
    blocking_factors: str,
) -> list[dict]:
    blocking_note = f" Existe bloqueo: {blocking_factors}." if has_blocking else ""

    s1 = {
        "name": "Vía consensuada / extrajudicial",
        "description": f"Resolución mediante acuerdo entre las partes o gestión extrajudicial.{blocking_note}",
        "viability": "alta" if has_agreement else ("baja" if has_blocking else "media"),
        "risk": "bajo",
        "recommended": has_agreement and not has_blocking and not is_urgent,
    }
    s2 = {
        "name": "Vía judicial / unilateral",
        "description": f"Inicio de acción judicial para resolver el conflicto.{blocking_note}",
        "viability": "baja" if has_blocking else "alta",
        "risk": "alto" if has_blocking else "medio",
        "recommended": not has_agreement or is_urgent,
    }

    return _ensure_single_recommended([s1, s2])


# ── Strategy & confidence ──────────────────────────────────────────────────────


def _ensure_single_recommended(scenarios: list[dict]) -> list[dict]:
    """Garantiza que exactamente 1 escenario tenga recommended=True."""
    recommended_indices = [i for i, s in enumerate(scenarios) if s.get("recommended")]

    if len(recommended_indices) == 1:
        return scenarios

    # None recommended → recommend the scenario with highest viability
    if len(recommended_indices) == 0:
        viability_order = {"alta": 3, "media": 2, "baja": 1}
        best_idx = max(
            range(len(scenarios)),
            key=lambda i: viability_order.get(scenarios[i].get("viability", "baja"), 0),
        )
        scenarios[best_idx]["recommended"] = True
        return scenarios

    # Multiple recommended → keep only the first
    for i, idx in enumerate(recommended_indices):
        if i > 0:
            scenarios[idx]["recommended"] = False
    return scenarios


def _build_recommended_strategy(scenarios: list[dict], *, is_urgent: bool) -> str:
    recommended = next((s for s in scenarios if s.get("recommended")), None)

    if not recommended:
        # Fallback: highest viability
        viability_order = {"alta": 3, "media": 2, "baja": 1}
        recommended = max(
            scenarios,
            key=lambda s: viability_order.get(s.get("viability", "baja"), 0),
        )

    name = recommended.get("name", "estrategia principal")
    viability = recommended.get("viability", "")
    risk = recommended.get("risk", "")

    strategy = f"Se recomienda la estrategia: {name}."
    if viability:
        strategy += f" Viabilidad: {viability}."
    if risk:
        strategy += f" Riesgo estimado: {risk}."
    if is_urgent:
        strategy += " Dado el nivel de urgencia, se prioriza la respuesta más rápida disponible."

    return strategy


def _compute_confidence(
    *,
    legal_area: str,
    facts: str,
    has_blocking: bool,
    scenarios: list[dict],
) -> float:
    confidence = 0.5

    if legal_area:
        confidence += 0.15
    if facts and len(facts) > 50:
        confidence += 0.10
    if len(scenarios) >= 2:
        confidence += 0.10
    if has_blocking:
        confidence -= 0.15

    return round(max(0.1, min(0.95, confidence)), 2)


# ── Text formatter ─────────────────────────────────────────────────────────────


def format_legal_reasoning_as_text(reasoning: dict) -> str:
    """
    Convierte el dict de razonamiento jurídico en texto natural para insertar en la respuesta,
    ubicado ANTES de los pasos prácticos.
    """
    if not reasoning:
        return ""

    parts: list[str] = []

    legal_framing = str(reasoning.get("legal_framing") or "").strip()
    if legal_framing:
        parts.append(f"Encuadre jurídico: {legal_framing}")

    scenarios = reasoning.get("scenarios") or []
    if scenarios:
        lines = ["Escenarios posibles:"]
        for i, s in enumerate(scenarios, 1):
            name = s.get("name", f"Escenario {i}")
            viability = s.get("viability", "")
            risk = s.get("risk", "")
            description = s.get("description", "")
            recommended = s.get("recommended", False)

            rec_marker = " (recomendado)" if recommended else ""
            meta_parts = []
            if viability:
                meta_parts.append(f"viabilidad {viability}")
            if risk:
                meta_parts.append(f"riesgo {risk}")
            meta_str = f" [{', '.join(meta_parts)}]" if meta_parts else ""

            lines.append(f"{i}. {name}{meta_str}{rec_marker}")
            if description:
                lines.append(f"   {description}")

        parts.append("\n".join(lines))

    recommended_strategy = str(reasoning.get("recommended_strategy") or "").strip()
    if recommended_strategy:
        parts.append(recommended_strategy)

    return "\n\n".join(parts)
