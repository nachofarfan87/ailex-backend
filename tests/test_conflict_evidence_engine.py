import io
from zipfile import ZipFile

from app.services.legal_export import build_legal_query_docx
from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.case_evaluation_engine import CaseEvaluationEngine
from legal_engine.conflict_evidence_engine import ConflictEvidenceEngine, ConflictEvidenceResult


def _payload(
    action_slug: str,
    action_label: str,
    *,
    facts: list[str] | None = None,
    missing_information: list[str] | None = None,
    unresolved_issues: list[str] | None = None,
    critical_questions: list[str] | None = None,
    evidentiary_needs: list[str] | None = None,
    likely_points_of_conflict: list[str] | None = None,
) -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    classification = {
        "action_slug": action_slug,
        "action_label": action_label,
        "confidence_score": 0.9,
    }
    case_structure = {
        "facts": facts if facts is not None else ["Hecho base 1", "Hecho base 2", "Hecho base 3"],
        "missing_information": missing_information if missing_information is not None else ["Dato faltante 1", "Dato faltante 2"],
        "risks": ["Riesgo base 1", "Riesgo base 2"],
    }
    normative_reasoning = {
        "applied_rules": [
            {"article": "1", "source": "CCyC"},
            {"article": "2", "source": "CCyC"},
            {"article": "3", "source": "CCyC"},
            {"article": "4", "source": "CCyC"},
            {"article": "5", "source": "CCyC"},
        ],
        "unresolved_issues": unresolved_issues if unresolved_issues is not None else ["Pendiente 1", "Pendiente 2"],
        "warnings": [],
    }
    procedural_strategy = {
        "next_steps": ["Paso 1", "Paso 2"],
        "risks": ["Riesgo procesal"],
    }
    question_engine_result = {
        "critical_questions": critical_questions if critical_questions is not None else ["Pregunta 1", "Pregunta 2"],
    }
    case_theory = {
        "primary_theory": "Teoria principal del caso.",
        "likely_points_of_conflict": likely_points_of_conflict if likely_points_of_conflict is not None else ["Conflicto 1", "Conflicto 2"],
        "evidentiary_needs": evidentiary_needs if evidentiary_needs is not None else ["Prueba documental 1", "Prueba documental 2"],
        "key_facts_supporting": ["Hecho de soporte 1"],
    }
    case_evaluation = CaseEvaluationEngine().evaluate(
        query="Consulta base",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        case_theory=case_theory,
        question_engine_result=question_engine_result,
    ).to_dict()
    return (
        classification,
        case_structure,
        normative_reasoning,
        procedural_strategy,
        question_engine_result,
        case_theory,
        case_evaluation,
    )


# ------------------------------------------------------------------
# Tests originales
# ------------------------------------------------------------------


def test_conflict_evidence_result_serialization():
    result = ConflictEvidenceResult(
        core_dispute="Conflicto central.",
        strongest_point="Punto fuerte.",
        most_vulnerable_point="Punto vulnerable.",
        critical_evidence_available=["Prueba 1"],
        key_evidence_missing=["Prueba faltante 1"],
        probable_counterarguments=["Contraargumento 1"],
        recommended_evidence_actions=["Accion 1"],
        confidence_score=0.75,
        warnings=["Warning."],
    )

    payload = result.to_dict()

    assert payload["core_dispute"] == "Conflicto central."
    assert payload["confidence_score"] == 0.75


def test_conflict_evidence_divorcio_mutuo_acuerdo():
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "divorcio_mutuo_acuerdo",
        "Divorcio por mutuo acuerdo",
    )

    result = engine.analyze(
        query="Dos personas quieren divorciarse de comun acuerdo",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    assert result.core_dispute
    assert result.strongest_point
    assert result.most_vulnerable_point


def test_conflict_evidence_divorcio_unilateral_counterarguments():
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "divorcio_unilateral",
        "Divorcio unilateral",
    )

    result = engine.analyze(
        query="Me quiero divorciar pero mi pareja no quiere",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    joined = " ".join(result.probable_counterarguments).lower()
    assert "competencia" in joined or "domicilio" in joined or "compensacion" in joined


def test_conflict_evidence_divorcio_not_generic_and_variant_vulnerability():
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "divorcio",
        "Divorcio",
    )

    result = engine.analyze(
        query="Quiero divorciarme",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    assert "handler generico" not in " ".join(result.warnings).lower()
    assert "variante procesal" in result.most_vulnerable_point.lower()


def test_conflict_evidence_alimentos_hijos_missing_evidence():
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "alimentos_hijos",
        "Alimentos para hijos",
        missing_information=["Gastos del hijo.", "Ingresos del obligado.", "Vinculo filial."],
        evidentiary_needs=["Comprobantes de gastos.", "Prueba de ingresos.", "Partida de nacimiento."],
    )

    result = engine.analyze(
        query="El padre de mi hijo no paga alimentos",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    joined = " ".join(result.key_evidence_missing).lower()
    assert "gastos" in joined or "ingresos" in joined or "vinculo" in joined


def test_conflict_evidence_sucesion_counterarguments():
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "sucesion_ab_intestato",
        "Sucesion ab intestato",
    )

    result = engine.analyze(
        query="Murio mi padre y queremos iniciar la sucesion",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    joined = " ".join(result.probable_counterarguments).lower()
    assert "heredero" in joined or "testamento" in joined or "competencia" in joined


def test_conflict_evidence_generic_fallback():
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "accion_generica",
        "Consulta generica",
    )

    result = engine.analyze(
        query="Necesito orientacion sobre un conflicto contractual",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    assert result.core_dispute
    assert any("generico" in item.lower() for item in result.warnings)


def test_conflict_evidence_case_domain_overrides_generic_action_slug():
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "generic",
        "Consulta generica",
        facts=["Existe cotitularidad del inmueble con el ex esposo."],
        missing_information=["No se sabe si el bien fue adquirido antes o durante el matrimonio."],
        unresolved_issues=["Falta precisar si hubo acuerdo de liquidacion previa."],
        likely_points_of_conflict=["Conflicto sobre adjudicacion o division del inmueble."],
    )

    result = engine.analyze(
        query="como proceder para que mi ex renuncie a la cotitularidad de mi casa",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
        case_domain="conflicto_patrimonial",
    )

    combined = " ".join(
        [
            result.core_dispute,
            result.strongest_point,
            result.most_vulnerable_point,
            *result.recommended_evidence_actions,
            *result.warnings,
        ]
    ).lower()

    assert "handler generico" not in combined
    assert "generic" not in combined
    assert "patrimonial" in combined or "cotitularidad" in combined
    assert any(token in combined for token in ("adjudicacion", "liquidacion", "division"))


def test_conflict_evidence_pipeline_integration():
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
    ).to_dict()

    assert payload["conflict_evidence"]
    assert payload["conflict_evidence"]["core_dispute"]
    assert payload["conflict_evidence"]["probable_counterarguments"]


def test_conflict_evidence_docx_integration():
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
        document_mode="formal",
    ).to_dict()

    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": "Dos personas quieren divorciarse de comun acuerdo", "jurisdiction": "jujuy"},
    )
    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Conflicto y prueba" in document_xml


# ------------------------------------------------------------------
# Tests nuevos — refinamiento semántico
# ------------------------------------------------------------------


def test_critical_evidence_no_juridical_terms():
    """critical_evidence_available NO debe contener términos jurídicos."""
    engine = ConflictEvidenceEngine()
    slugs = [
        ("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo"),
        ("divorcio_unilateral", "Divorcio unilateral"),
        ("divorcio", "Divorcio"),
        ("alimentos_hijos", "Alimentos para hijos"),
        ("sucesion_ab_intestato", "Sucesion ab intestato"),
        ("accion_generica", "Consulta generica"),
    ]
    forbidden = ("norma", "articulo", "regla", "sustento normativo", "base normativa", "encuadre juridico", "marco normativo")

    for slug, label in slugs:
        classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
            slug, label,
        )
        result = engine.analyze(
            query="Consulta de prueba",
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            question_engine_result=question_engine_result,
            case_theory=case_theory,
            case_evaluation=case_evaluation,
        )
        for item in result.critical_evidence_available:
            lower = item.lower()
            for word in forbidden:
                assert word not in lower, (
                    f"[{slug}] critical_evidence_available contiene '{word}': {item}"
                )


def test_key_evidence_missing_no_question_marks():
    """key_evidence_missing NO debe contener signos de interrogación."""
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "divorcio_mutuo_acuerdo",
        "Divorcio por mutuo acuerdo",
        critical_questions=[
            "¿Cuál es el último domicilio conyugal?",
            "¿Existen hijos menores?",
            "¿Cuáles son los ingresos del demandado?",
        ],
        missing_information=[
            "¿Quién tiene la tenencia?",
            "¿Hay bienes en común?",
        ],
    )

    result = engine.analyze(
        query="Consulta de prueba",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    for item in result.key_evidence_missing:
        assert "?" not in item, f"key_evidence_missing contiene '?': {item}"
        assert "¿" not in item, f"key_evidence_missing contiene '¿': {item}"


def test_normalize_evidence_item_transforms():
    """_normalize_evidence_item convierte preguntas a formato declarativo."""
    engine = ConflictEvidenceEngine()

    cases = [
        ("¿Cuál fue el último domicilio conyugal?", "acreditacion"),
        ("¿Existen hijos menores?", "existencia"),
        ("¿Cuáles son los ingresos del demandado?", "acreditacion"),
        ("¿Quién tiene la tenencia?", "identificacion"),
        ("Partida de nacimiento.", "partida de nacimiento"),  # no cambia
    ]

    for input_text, expected_substr in cases:
        result = engine._normalize_evidence_item(input_text)
        assert "?" not in result, f"Resultado contiene '?': {result}"
        assert "¿" not in result, f"Resultado contiene '¿': {result}"
        assert expected_substr in result.lower(), (
            f"Se esperaba '{expected_substr}' en: {result}"
        )


def test_counterarguments_sound_like_objections():
    """probable_counterarguments debe contener verbos de objeción real."""
    engine = ConflictEvidenceEngine()
    objection_patterns = (
        "no se ha acreditado",
        "no han sido acreditados",
        "podria alegarse",
        "no existe prueba suficiente",
        "no existen elementos suficientes",
        "no se ha definido",
        "no hay constancia",
        "insuficiente",
        "incompleto",
        "no permite evaluar",
        "no resguarda",
        "podria invalidar",
        "incompetencia",
        "adecuadamente",
    )
    slugs = [
        ("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo"),
        ("divorcio_unilateral", "Divorcio unilateral"),
        ("alimentos_hijos", "Alimentos para hijos"),
        ("sucesion_ab_intestato", "Sucesion ab intestato"),
    ]

    for slug, label in slugs:
        classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
            slug, label,
        )
        result = engine.analyze(
            query="Consulta de prueba",
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            question_engine_result=question_engine_result,
            case_theory=case_theory,
            case_evaluation=case_evaluation,
        )
        for arg in result.probable_counterarguments:
            lower = arg.lower()
            has_objection = any(pattern in lower for pattern in objection_patterns)
            assert has_objection, (
                f"[{slug}] counterargument no suena a objeción: {arg}"
            )


def test_likely_points_of_conflict_used_in_counterarguments():
    """likely_points_of_conflict del CaseTheoryEngine debe reflejarse en counterarguments."""
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "divorcio_mutuo_acuerdo",
        "Divorcio por mutuo acuerdo",
        likely_points_of_conflict=[
            "Discrepancia sobre la atribucion de la vivienda familiar",
            "Conflicto sobre el regimen de cuidado personal de los hijos",
        ],
    )

    result = engine.analyze(
        query="Consulta de prueba",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    joined = " ".join(result.probable_counterarguments).lower()
    assert "vivienda" in joined or "cuidado" in joined, (
        f"counterarguments no incorpora likely_points_of_conflict: {result.probable_counterarguments}"
    )


def test_likely_points_of_conflict_enrich_vulnerable_point():
    """likely_points_of_conflict debe enriquecer most_vulnerable_point."""
    engine = ConflictEvidenceEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
        "alimentos_hijos",
        "Alimentos para hijos",
        likely_points_of_conflict=[
            "El demandado podria acreditar aportes informales no registrados",
        ],
    )

    result = engine.analyze(
        query="Consulta de prueba",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
        case_theory=case_theory,
        case_evaluation=case_evaluation,
    )

    assert "aportes informales" in result.most_vulnerable_point.lower(), (
        f"most_vulnerable_point no incorpora likely_points_of_conflict: {result.most_vulnerable_point}"
    )


def test_recommended_actions_are_concrete():
    """recommended_evidence_actions no debe contener frases abstractas."""
    engine = ConflictEvidenceEngine()
    abstract_phrases = (
        "reunir mas documentacion",
        "obtener mas informacion",
        "completar datos",
    )
    slugs = [
        ("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo"),
        ("alimentos_hijos", "Alimentos para hijos"),
        ("sucesion_ab_intestato", "Sucesion ab intestato"),
    ]

    for slug, label in slugs:
        classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation = _payload(
            slug, label,
        )
        result = engine.analyze(
            query="Consulta de prueba",
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            question_engine_result=question_engine_result,
            case_theory=case_theory,
            case_evaluation=case_evaluation,
        )
        for action in result.recommended_evidence_actions:
            lower = action.lower()
            for phrase in abstract_phrases:
                assert phrase not in lower, (
                    f"[{slug}] acción abstracta: {action}"
                )


def test_conflict_point_to_objection_transforms():
    """_conflict_point_to_objection debe transformar descripciones en objeciones."""
    engine = ConflictEvidenceEngine()

    cases = [
        ("Conflicto sobre bienes", "no se ha acreditado"),
        ("Discusion sobre ingresos", "podria alegarse"),
        ("Riesgo de heredero omitido", "podria alegarse"),
        ("No se ha acreditado el domicilio", "no se ha acreditado"),  # ya es objeción
    ]

    for input_text, expected_substr in cases:
        result = engine._conflict_point_to_objection(input_text)
        assert expected_substr in result.lower(), (
            f"Se esperaba '{expected_substr}' en: {result}"
        )


def test_pipeline_conflict_evidence_still_works():
    """Pipeline completo debe seguir devolviendo conflict_evidence sin romper."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="El padre de mi hijo no paga alimentos",
        jurisdiction="jujuy",
    ).to_dict()

    ce = payload["conflict_evidence"]
    assert ce["core_dispute"]
    assert ce["strongest_point"]
    assert ce["most_vulnerable_point"]
    assert isinstance(ce["critical_evidence_available"], list)
    assert isinstance(ce["key_evidence_missing"], list)
    assert isinstance(ce["probable_counterarguments"], list)
    assert isinstance(ce["recommended_evidence_actions"], list)
    assert isinstance(ce["confidence_score"], float)
