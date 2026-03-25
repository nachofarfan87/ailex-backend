from types import SimpleNamespace

from legal_engine.case_profile_builder import build_case_profile
from legal_engine.case_strategy_builder import build_case_strategy
from legal_engine.procedural_strategy import ProceduralPlan, ProceduralStep


def _procedural_plan(*, step_action: str = "Presentar demanda", risks: list[str] | None = None) -> ProceduralPlan:
    return ProceduralPlan(
        query="alimentos",
        domain="family",
        jurisdiction="jujuy",
        steps=[
            ProceduralStep(
                order=1,
                action=step_action,
                deadline_hint=None,
                urgency="immediate",
                notes="",
            )
        ],
        risks=risks or [],
        missing_info=[],
        strategic_notes="",
        citations_used=[],
        warnings=[],
    )


def _reasoning_result() -> SimpleNamespace:
    return SimpleNamespace(
        short_answer="Existe una base inicial para estructurar el planteo.",
        applied_analysis="La estrategia debe conectar conflicto, requisitos y prueba utilizable.",
    )


def test_alimentos_non_payment_includes_urgency_and_provisional_quota():
    procedural_plan = _procedural_plan(step_action="Promover demanda con pedido de cuota provisoria")
    case_theory = {
        "primary_theory": "Existe incumplimiento alimentario actual del progenitor no conviviente.",
        "objective": "Obtener una cuota alimentaria provisoria sin demora.",
    }
    conflict = {
        "core_dispute": "Incumplimiento de la obligacion alimentaria respecto del hijo.",
        "most_vulnerable_point": "Aun falta reconstruccion patrimonial completa del alimentante.",
    }
    normative_reasoning = {
        "requirements": ["Acreditar necesidades del hijo."],
        "inferences": ["La urgencia alimentaria justifica tutela inmediata."],
        "applied_rules": [{"source": "CCyC", "article": "658", "effect": "Obligacion alimentaria."}],
    }
    profile = build_case_profile(
        "el padre no paga alimentos y necesito cuota provisoria urgente",
        {"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos"},
        case_theory,
        conflict,
        normative_reasoning,
        procedural_plan,
        {},
    )

    strategy = build_case_strategy(
        query="el padre no paga alimentos y necesito cuota provisoria urgente",
        case_profile=profile,
        case_theory=case_theory,
        conflict=conflict,
        case_evaluation={},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
    )

    joined_actions = " ".join(strategy["recommended_actions"]).lower()
    narrative = strategy["strategic_narrative"].lower()
    assert "cuota provisoria" in joined_actions
    assert "urgencia" in narrative or "medidas de aseguramiento" in narrative


def test_hijo_mayor_mentions_article_663_and_academic_regularity():
    procedural_plan = _procedural_plan()
    case_theory = {
        "primary_theory": "El hijo mayor continua estudiando y necesita asistencia alimentaria.",
        "objective": "Obtener alimentos para hijo mayor estudiante.",
    }
    conflict = {
        "core_dispute": "Continuidad de asistencia alimentaria para hijo mayor estudiante.",
        "most_vulnerable_point": "Necesidad de acreditar regularidad academica.",
    }
    normative_reasoning = {
        "requirements": ["Acreditar regularidad academica."],
        "applied_rules": [{"source": "CCyC", "article": "663", "effect": "Permite alimentos al hijo mayor que estudia."}],
    }
    profile = build_case_profile(
        "alimentos para hijo mayor estudiante universitario",
        {"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos"},
        case_theory,
        conflict,
        normative_reasoning,
        procedural_plan,
        {},
    )

    strategy = build_case_strategy(
        query="alimentos para hijo mayor estudiante universitario",
        case_profile=profile,
        case_theory=case_theory,
        conflict=conflict,
        case_evaluation={},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
    )

    combined = f"{strategy['strategic_narrative']} {' '.join(strategy['recommended_actions'])}".lower()
    assert "663 ccyc" in combined or "art. 663" in combined
    assert "regularidad academica" in combined


def test_hijo_mayor_no_estudia_blocks_academic_strategy():
    procedural_plan = _procedural_plan()
    case_theory = {
        "primary_theory": "La hija tiene 22 anos y no estudia; se consulta sobre continuidad de cuota alimentaria.",
        "objective": "Determinar si corresponde sostener o revisar la cuota alimentaria.",
    }
    conflict = {
        "core_dispute": "Alcance de la cuota alimentaria para hija mayor de 21 anos que no estudia.",
        "most_vulnerable_point": "Falta precisar si trabaja o tiene ingresos propios.",
    }
    profile = build_case_profile(
        "hasta que edad mi ex esposo puede pasar cuota alimentaria si mi hija tiene 22 y no estudia",
        {"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos"},
        case_theory,
        conflict,
        {"requirements": ["Precisar edad, estudio e ingresos propios."], "applied_rules": []},
        procedural_plan,
        {},
    )

    strategy = build_case_strategy(
        query="hasta que edad mi ex esposo puede pasar cuota alimentaria si mi hija tiene 22 y no estudia",
        case_profile=profile,
        case_theory=case_theory,
        conflict=conflict,
        case_evaluation={},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
    )

    joined_actions = " ".join(strategy["recommended_actions"]).lower()
    joined_focus = " ".join(strategy["procedural_focus"]).lower()
    joined_risks = " ".join(strategy["risk_analysis"]).lower()
    assert "regularidad academica" not in joined_actions
    assert "alumno regular" not in joined_actions
    assert "regularidad academica" not in joined_focus
    assert "no estudia" in joined_risks


def test_patrimonial_conflict_returns_critical_questions_and_avoids_genericity():
    procedural_plan = _procedural_plan(step_action="Relevar titulo e historia de adquisicion del inmueble")
    case_theory = {
        "primary_theory": "Existe un conflicto por cotitularidad de la casa con el ex esposo y se busca una salida patrimonial.",
        "objective": "Definir si corresponde adjudicacion, liquidacion o alguna otra via para resolver la titularidad.",
        "likely_points_of_conflict": ["Cotitularidad del inmueble con ex esposo."],
    }
    conflict = {
        "core_dispute": "Como resolver la cotitularidad de la vivienda con el ex esposo.",
        "most_vulnerable_point": "No esta claro si el bien es ganancial o propio.",
    }

    strategy = build_case_strategy(
        query="como tendria que proceder para que mi ex esposo renuncie a la cotitularidad de mi casa",
        case_profile={"is_alimentos": False, "scenarios": set(), "strategic_focus": []},
        case_theory=case_theory,
        conflict=conflict,
        case_evaluation={},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
    )

    combined = " ".join(strategy["conflict_summary"] + strategy["recommended_actions"] + strategy["risk_analysis"]).lower()
    assert "conflicto patrimonial" in combined
    assert "ganancial o propio" in combined
    assert "antes o durante el matrimonio" in combined
    assert "convenio de adjudicacion" in combined
    assert "particion" in combined or "condominio" in combined


def test_mixed_children_ages_preserve_multiple_scenarios():
    procedural_plan = _procedural_plan()
    case_theory = {
        "primary_theory": "Existen dos hijos de 13 y 21 anos con necesidades alimentarias diferenciadas.",
        "objective": "Ordenar el reclamo sin mezclar hijo menor con tramo 18 a 21.",
    }
    conflict = {
        "core_dispute": "Definir cuota alimentaria para dos hijos en etapas distintas.",
        "most_vulnerable_point": "No debe colapsarse todo al hijo de mayor edad.",
    }
    profile = build_case_profile(
        "tengo dos hijos de 13 y 21 anos y quiero reclamar cuota alimentaria",
        {"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos"},
        case_theory,
        conflict,
        {"requirements": ["Precisar necesidades concretas de ambos hijos."], "applied_rules": []},
        procedural_plan,
        {},
    )

    assert "hijo_menor" in profile["scenarios"]
    assert "hijo_18_21" in profile["scenarios"]
    assert "mantener el supuesto de hijo menor sin mezclarlo con hijo mayor" not in profile["strategic_focus"]
    assert "separar el tramo 18 a 21 del supuesto de hijo mayor estudiante" in profile["strategic_focus"]


def test_no_trabaja_is_treated_different_from_estudia_in_case_strategy():
    procedural_plan = _procedural_plan()
    case_theory = {
        "primary_theory": "La hija tiene 22 anos y no trabaja; se consulta continuidad de cuota.",
        "objective": "Delimitar si la falta de empleo cambia la estrategia respecto del caso de hija estudiante.",
    }
    conflict = {
        "core_dispute": "Analizar cuota alimentaria para hija de 22 anos sin trabajo actual.",
        "most_vulnerable_point": "Falta precisar ingresos reales o dependencia economica.",
    }
    profile = build_case_profile(
        "mi hija tiene 22 anos y no trabaja, hasta cuando corresponde cuota alimentaria",
        {"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos"},
        case_theory,
        conflict,
        {"requirements": ["Precisar ingresos reales y dependencia economica."], "applied_rules": []},
        procedural_plan,
        {},
    )

    strategy = build_case_strategy(
        query="mi hija tiene 22 anos y no trabaja, hasta cuando corresponde cuota alimentaria",
        case_profile=profile,
        case_theory=case_theory,
        conflict=conflict,
        case_evaluation={},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
    )

    combined = " ".join(strategy["risk_analysis"] + strategy["recommended_actions"]).lower()
    assert "no debe asumirse autosustento" in combined
    assert "regularidad academica" not in combined


def test_ascendants_mentions_subsidiarity():
    procedural_plan = _procedural_plan()
    case_theory = {
        "primary_theory": "Corresponde desplazar el reclamo hacia ascendientes por insuficiencia del obligado principal.",
        "objective": "Obtener alimentos en caracter subsidiario.",
    }
    conflict = {
        "core_dispute": "Subsidiariedad del reclamo alimentario contra ascendiente.",
        "most_vulnerable_point": "Necesidad de probar imposibilidad del obligado principal.",
    }
    profile = build_case_profile(
        "alimentos contra abuelo por imposibilidad del obligado principal",
        {"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos"},
        case_theory,
        conflict,
        {"requirements": ["Acreditar insuficiencia del obligado principal."], "applied_rules": []},
        procedural_plan,
        {},
    )

    strategy = build_case_strategy(
        query="alimentos contra abuelo por imposibilidad del obligado principal",
        case_profile=profile,
        case_theory=case_theory,
        conflict=conflict,
        case_evaluation={},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
    )

    combined = f"{strategy['strategic_narrative']} {' '.join(strategy['recommended_actions'])}".lower()
    assert "subsidiariedad" in combined
    assert "obligado principal" in combined


def test_without_jurisprudence_does_not_claim_strong_support():
    procedural_plan = _procedural_plan()
    case_theory = {
        "primary_theory": "Existe una pretension juridicamente atendible, pero la prueba todavia es incompleta.",
        "objective": "Delimitar el conflicto y ordenar la prueba.",
    }
    conflict = {
        "core_dispute": "Necesidad de cubrir requisitos legales con soporte probatorio suficiente.",
        "most_vulnerable_point": "La cobertura probatoria todavia es insuficiente.",
    }
    profile = build_case_profile(
        "alimentos",
        {"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos"},
        case_theory,
        conflict,
        {"requirements": ["Acreditar necesidades del alimentado."], "applied_rules": []},
        procedural_plan,
        {},
    )

    strategy = build_case_strategy(
        query="alimentos",
        case_profile=profile,
        case_theory=case_theory,
        conflict=conflict,
        case_evaluation={},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
    )

    narrative = strategy["strategic_narrative"].lower()
    focus = " ".join(strategy["procedural_focus"]).lower()
    assert "precedentes reales recuperados del corpus" not in narrative
    assert "no corresponde presentar la base disponible como jurisprudencia consolidada" in narrative
    assert "evitar presentar la base disponible como jurisprudencia consolidada" in focus


def test_strategy_respects_legal_decision_posture_and_dominant_factor():
    procedural_plan = _procedural_plan(step_action="Ordenar documental y definir monto base")
    strategy = build_case_strategy(
        query="necesito alimentos pero me falta prueba de ingresos",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": {"incumplimiento"},
            "strategic_focus": [],
            "needs_proof_strengthening": True,
        },
        case_theory={
            "primary_theory": "Existe incumplimiento actual.",
            "objective": "Obtener cuota provisoria sin rechazo inicial.",
            "evidentiary_needs": ["recibos", "gastos"],
        },
        conflict={
            "core_dispute": "Incumplimiento alimentario actual.",
            "most_vulnerable_point": "Falta prueba de ingresos.",
        },
        case_evaluation={"legal_risk_level": "alto"},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
        legal_decision={
            "strategic_posture": "cautelosa",
            "dominant_factor": "prueba",
            "decision_notes": ["La prueba debil obliga a una estrategia de saneamiento."],
        },
    )

    assert strategy["strategy_mode"] == "cautelosa"
    narrative = strategy["strategic_narrative"].lower()
    focus = " ".join(strategy["procedural_focus"]).lower()
    alignment = " ".join(strategy["legal_decision_alignment"]).lower()
    assert "saneamiento" in narrative or "prudencia" in narrative
    assert "priorizar saneamiento" in focus
    assert "prueba debil" in alignment


def test_strategy_mode_falls_back_deterministically_without_legal_decision():
    procedural_plan = _procedural_plan(step_action="Ordenar documental")
    strategy = build_case_strategy(
        query="quiero alimentos pero faltan recibos y hay riesgo de rechazo",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": {"incumplimiento"},
            "strategic_focus": [],
            "needs_proof_strengthening": True,
        },
        case_theory={
            "primary_theory": "Existe incumplimiento actual con soporte debil.",
            "objective": "Evaluar si conviene avanzar.",
        },
        conflict={
            "core_dispute": "Incumplimiento alimentario actual.",
            "most_vulnerable_point": "Falta prueba de ingresos.",
        },
        case_evaluation={"legal_risk_level": "alto", "risk_score": 0.79, "strength_score": 0.61},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none", "precedent_trend": "neutral"},
        reasoning_result=_reasoning_result(),
        legal_decision={},
    )

    assert strategy["strategy_mode"] == "cautelosa"
    assert strategy["strategy_mode"] is not None
    focus = " ".join(strategy["procedural_focus"]).lower()
    assert "saneamiento" in focus or "priorizar saneamiento" in focus


def test_risk_dominant_strategy_surfaces_risk_in_structural_sections():
    procedural_plan = _procedural_plan(step_action="Revisar competencia y plazos", risks=["Riesgo de incompetencia territorial"])
    strategy = build_case_strategy(
        query="quiero demandar pero hay riesgo de incompetencia",
        case_profile={
            "case_domain": "conflicto_patrimonial",
            "scenarios": {"conflicto"},
            "strategic_focus": [],
            "needs_proof_strengthening": False,
        },
        case_theory={"primary_theory": "La principal dificultad es procesal.", "objective": "Evitar rechazo formal."},
        conflict={"core_dispute": "Definir viabilidad procesal.", "most_vulnerable_point": "Competencia territorial discutible."},
        case_evaluation={"legal_risk_level": "alto", "risk_score": 0.84, "strength_score": 0.45},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
        legal_decision={
            "strategic_posture": "cautelosa",
            "dominant_factor": "riesgo",
            "decision_notes": ["El riesgo procesal domina la decision final."],
        },
    )

    assert strategy["strategy_mode"] == "cautelosa"
    support_text = " ".join(strategy["procedural_focus"] + strategy["legal_decision_alignment"] + strategy["risk_analysis"]).lower()
    assert "riesgo" in support_text or "contencion" in support_text


# ---------------------------------------------------------------------------
# blocking_factor-driven strategy tests
# ---------------------------------------------------------------------------

def test_blocking_service_forces_notification_strategy():
    """blocking_factor=service → cautelosa + procesal + narrative about notification."""
    procedural_plan = _procedural_plan(step_action="Diligenciar cedula")
    strategy = build_case_strategy(
        query="alimentos urgentes pero no se notifico al demandado",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": {"incumplimiento"},
            "strategic_focus": [],
            "needs_proof_strengthening": False,
        },
        case_theory={
            "primary_theory": "Existe incumplimiento alimentario actual.",
            "objective": "Obtener cuota provisoria.",
        },
        conflict={
            "core_dispute": "Incumplimiento alimentario actual.",
            "most_vulnerable_point": "",
        },
        case_evaluation={"legal_risk_level": "bajo", "risk_score": 0.2, "strength_score": 0.8},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
        procedural_case_state={
            "blocking_factor": "service",
            "execution_readiness": "requiere_impulso_procesal",
            "procedural_phase": "traba_de_litis",
        },
    )

    assert strategy["strategy_mode"] == "cautelosa"
    narrative = strategy["strategic_narrative"].lower()
    assert "notificacion" in narrative
    assert "cedula" in narrative
    actions = " ".join(strategy["recommended_actions"]).lower()
    assert "notificacion" in actions or "cedula" in actions


def test_blocking_competence_forces_competence_strategy():
    """blocking_factor=competence → cautelosa + procesal + narrative about competence."""
    procedural_plan = _procedural_plan(step_action="Resolver competencia")
    strategy = build_case_strategy(
        query="alimentos con incompetencia planteada",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": set(),
            "strategic_focus": [],
            "needs_proof_strengthening": False,
        },
        case_theory={
            "primary_theory": "Pretension alimentaria fuerte con incidente de competencia.",
            "objective": "Sostener tutela pese al planteo.",
        },
        conflict={
            "core_dispute": "Alimentos con incidente de competencia.",
            "most_vulnerable_point": "",
        },
        case_evaluation={"legal_risk_level": "bajo", "risk_score": 0.25, "strength_score": 0.78},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
        procedural_case_state={
            "blocking_factor": "competence",
            "execution_readiness": "bloqueado_procesalmente",
            "procedural_phase": "incidente",
        },
    )

    assert strategy["strategy_mode"] == "cautelosa"
    narrative = strategy["strategic_narrative"].lower()
    assert "competencia" in narrative
    focus = " ".join(strategy["procedural_focus"]).lower()
    assert "competencia" in focus


def test_blocking_execution_forces_execution_strategy():
    """blocking_factor=execution → conservadora + procesal + narrative about enforcement."""
    procedural_plan = _procedural_plan(step_action="Librar oficios de ejecucion")
    strategy = build_case_strategy(
        query="ya tengo sentencia pero no se cumple",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": set(),
            "strategic_focus": [],
            "needs_proof_strengthening": False,
        },
        case_theory={
            "primary_theory": "La cuota esta fijada pero no se cumple.",
            "objective": "Ejecutar la sentencia.",
        },
        conflict={
            "core_dispute": "Incumplimiento de cuota ya fijada.",
            "most_vulnerable_point": "",
        },
        case_evaluation={"legal_risk_level": "bajo", "risk_score": 0.15, "strength_score": 0.85},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
        procedural_case_state={
            "blocking_factor": "execution",
            "execution_readiness": "listo_para_avanzar",
            "procedural_phase": "ejecucion",
        },
    )

    assert strategy["strategy_mode"] == "conservadora"
    narrative = strategy["strategic_narrative"].lower()
    assert "ejecucion" in narrative or "cumplimiento" in narrative
    assert "oficios" in narrative or "embargos" in narrative
    actions = " ".join(strategy["recommended_actions"]).lower()
    assert "ejecucion" in actions or "oficios" in actions or "cumplimiento" in actions


def test_blocking_administrative_delay_forces_unblock_strategy():
    """blocking_factor=administrative_delay → conservadora + procesal + narrative about unblocking."""
    procedural_plan = _procedural_plan(step_action="Reiterar oficios y controlar despacho")
    strategy = build_case_strategy(
        query="el expediente esta trabado por demora del juzgado",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": set(),
            "strategic_focus": [],
            "needs_proof_strengthening": False,
        },
        case_theory={
            "primary_theory": "El merito existe pero el tramite esta demorado.",
            "objective": "Destrabar el expediente.",
        },
        conflict={
            "core_dispute": "Demora operativa en el tramite.",
            "most_vulnerable_point": "",
        },
        case_evaluation={"legal_risk_level": "bajo", "risk_score": 0.2, "strength_score": 0.75},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
        procedural_case_state={
            "blocking_factor": "administrative_delay",
            "execution_readiness": "requiere_impulso_procesal",
            "procedural_phase": "tramite",
        },
    )

    assert strategy["strategy_mode"] == "conservadora"
    narrative = strategy["strategic_narrative"].lower()
    assert "demora" in narrative or "operativa" in narrative
    assert "seguimiento" in narrative or "reiteracion" in narrative or "impulso" in narrative
    actions = " ".join(strategy["recommended_actions"]).lower()
    assert "destrabar" in actions or "impulso" in actions or "oficios" in actions


def test_execution_readiness_listo_para_avanzar_boosts_to_agresiva():
    """execution_readiness=listo_para_avanzar with good scores → agresiva."""
    procedural_plan = _procedural_plan(step_action="Ampliar demanda")
    strategy = build_case_strategy(
        query="alimentos con todo en orden",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": set(),
            "strategic_focus": [],
            "needs_proof_strengthening": False,
        },
        case_theory={
            "primary_theory": "Todo alineado para avanzar.",
            "objective": "Obtener cuota.",
        },
        conflict={
            "core_dispute": "Fijacion de cuota.",
            "most_vulnerable_point": "",
        },
        case_evaluation={"legal_risk_level": "bajo", "risk_score": 0.2, "strength_score": 0.75},
        procedural_plan=procedural_plan,
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none", "precedent_trend": "neutral"},
        reasoning_result=_reasoning_result(),
        procedural_case_state={
            "blocking_factor": "",
            "execution_readiness": "listo_para_avanzar",
            "procedural_phase": "prueba",
        },
    )

    assert strategy["strategy_mode"] == "agresiva"


# ---------------------------------------------------------------------------
# blocking_factor overrides explicit legal_decision.strategic_posture
# ---------------------------------------------------------------------------

def _strategy_with_posture_and_blocking(posture: str, blocking: str) -> dict:
    """Helper: build strategy with explicit posture + blocking_factor."""
    return build_case_strategy(
        query="caso de prueba",
        case_profile={
            "case_domain": "alimentos",
            "is_alimentos": True,
            "scenarios": set(),
            "strategic_focus": [],
            "needs_proof_strengthening": False,
        },
        case_theory={
            "primary_theory": "Caso de control.",
            "objective": "Verificar override.",
        },
        conflict={
            "core_dispute": "Test.",
            "most_vulnerable_point": "",
        },
        case_evaluation={"legal_risk_level": "bajo", "risk_score": 0.2, "strength_score": 0.8},
        procedural_plan=_procedural_plan(),
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning_result(),
        legal_decision={"strategic_posture": posture},
        procedural_case_state={"blocking_factor": blocking},
    )


def test_service_overrides_agresiva_to_cautelosa():
    """service forces cautelosa even when legal_decision says agresiva."""
    strategy = _strategy_with_posture_and_blocking("agresiva", "service")
    assert strategy["strategy_mode"] == "cautelosa"


def test_service_overrides_conservadora_to_cautelosa():
    """service forces cautelosa even when legal_decision says conservadora."""
    strategy = _strategy_with_posture_and_blocking("conservadora", "service")
    assert strategy["strategy_mode"] == "cautelosa"


def test_competence_overrides_agresiva_to_cautelosa():
    """competence forces cautelosa even when legal_decision says agresiva."""
    strategy = _strategy_with_posture_and_blocking("agresiva", "competence")
    assert strategy["strategy_mode"] == "cautelosa"


def test_evidence_blocks_agresiva():
    """evidence degrades agresiva to cautelosa."""
    strategy = _strategy_with_posture_and_blocking("agresiva", "evidence")
    assert strategy["strategy_mode"] == "cautelosa"


def test_evidence_preserves_conservadora():
    """evidence keeps conservadora as-is."""
    strategy = _strategy_with_posture_and_blocking("conservadora", "evidence")
    assert strategy["strategy_mode"] == "conservadora"


def test_execution_upgrades_cautelosa_to_conservadora():
    """execution won't allow cautelosa — upgrades to conservadora."""
    strategy = _strategy_with_posture_and_blocking("cautelosa", "execution")
    assert strategy["strategy_mode"] == "conservadora"


def test_execution_preserves_agresiva():
    """execution allows agresiva to pass through."""
    strategy = _strategy_with_posture_and_blocking("agresiva", "execution")
    assert strategy["strategy_mode"] == "agresiva"


def test_administrative_delay_degrades_agresiva():
    """administrative_delay degrades agresiva to conservadora."""
    strategy = _strategy_with_posture_and_blocking("agresiva", "administrative_delay")
    assert strategy["strategy_mode"] == "conservadora"


def test_administrative_delay_preserves_cautelosa():
    """administrative_delay preserves cautelosa."""
    strategy = _strategy_with_posture_and_blocking("cautelosa", "administrative_delay")
    assert strategy["strategy_mode"] == "cautelosa"


def test_no_blocking_respects_explicit_posture():
    """Without blocking_factor, legal_decision.strategic_posture is respected."""
    strategy = _strategy_with_posture_and_blocking("agresiva", "")
    assert strategy["strategy_mode"] == "agresiva"
    strategy2 = _strategy_with_posture_and_blocking("cautelosa", "")
    assert strategy2["strategy_mode"] == "cautelosa"
