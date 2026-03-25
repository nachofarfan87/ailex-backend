import io
from zipfile import ZipFile

from app.services.legal_export import build_legal_query_docx
from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.case_evaluation_engine import CaseEvaluationEngine, CaseEvaluationResult


def _payload(
    action_slug: str,
    action_label: str,
    *,
    classification_confidence: float = 0.9,
    facts: list[str] | None = None,
    missing_information: list[str] | None = None,
    risks: list[str] | None = None,
    applied_rules: list[dict] | None = None,
    unresolved_issues: list[str] | None = None,
    critical_questions: list[str] | None = None,
) -> tuple[dict, dict, dict, dict, dict, dict]:
    classification = {
        "action_slug": action_slug,
        "action_label": action_label,
        "confidence_score": classification_confidence,
    }
    case_structure = {
        "facts": facts if facts is not None else ["Hecho 1", "Hecho 2", "Hecho 3"],
        "missing_information": missing_information if missing_information is not None else ["Dato faltante 1", "Dato faltante 2"],
        "risks": risks if risks is not None else ["Riesgo 1", "Riesgo 2"],
    }
    normative_reasoning = {
        "applied_rules": applied_rules if applied_rules is not None else [
            {"article": "1", "source": "CCyC"},
            {"article": "2", "source": "CCyC"},
            {"article": "3", "source": "CCyC"},
            {"article": "4", "source": "CCyC"},
        ],
        "unresolved_issues": unresolved_issues if unresolved_issues is not None else ["Pendiente 1", "Pendiente 2"],
        "warnings": [],
    }
    procedural_strategy = {
        "next_steps": ["Paso 1", "Paso 2"],
        "risks": ["Riesgo procesal 1"],
    }
    case_theory = {
        "evidentiary_needs": ["Prueba documental relevante."],
    }
    question_engine_result = {
        "critical_questions": critical_questions if critical_questions is not None else ["Pregunta 1", "Pregunta 2"],
    }
    return (
        classification,
        case_structure,
        normative_reasoning,
        procedural_strategy,
        case_theory,
        question_engine_result,
    )


def test_case_evaluation_result_serialization():
    result = CaseEvaluationResult(
        case_strength="media",
        legal_risk_level="medio",
        uncertainty_level="baja",
        strength_score=0.6,
        risk_score=0.4,
        uncertainty_score=0.2,
        strategic_observations=["Precisar hechos."],
        possible_scenarios=["Escenario base."],
        warnings=["Warning."],
    )

    payload = result.to_dict()

    assert payload["case_strength"] == "media"
    assert payload["possible_scenarios"] == ["Escenario base."]


def test_case_evaluation_engine_divorcio_mutuo_acuerdo_not_weak():
    engine = CaseEvaluationEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result = _payload(
        "divorcio_mutuo_acuerdo",
        "Divorcio por mutuo acuerdo",
    )

    result = engine.evaluate(
        query="Dos personas quieren divorciarse de comun acuerdo",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        case_theory=case_theory,
        question_engine_result=question_engine_result,
    )

    assert result.case_strength != "debil"


def test_case_evaluation_engine_divorcio_unilateral_scenarios():
    engine = CaseEvaluationEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result = _payload(
        "divorcio_unilateral",
        "Divorcio unilateral",
    )

    result = engine.evaluate(
        query="Me quiero divorciar pero mi pareja no quiere",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        case_theory=case_theory,
        question_engine_result=question_engine_result,
    )

    assert any("sentencia de divorcio" in item.lower() for item in result.possible_scenarios)
    assert any("efectos patrimoniales" in item.lower() for item in result.possible_scenarios)


def test_case_evaluation_engine_alimentos_hijos_risk_level():
    engine = CaseEvaluationEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result = _payload(
        "alimentos_hijos",
        "Alimentos para hijos",
        risks=["Riesgo 1", "Riesgo 2", "Riesgo 3", "Riesgo 4"],
        unresolved_issues=["Pendiente 1", "Pendiente 2", "Pendiente 3"],
        critical_questions=["Pregunta 1", "Pregunta 2", "Pregunta 3"],
    )

    result = engine.evaluate(
        query="El padre de mi hijo no paga alimentos",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        case_theory=case_theory,
        question_engine_result=question_engine_result,
    )

    assert result.legal_risk_level in {"medio", "alto"}


def test_case_evaluation_engine_sucesion_uncertainty():
    engine = CaseEvaluationEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result = _payload(
        "sucesion_ab_intestato",
        "Sucesion ab intestato",
        missing_information=["Dato 1", "Dato 2", "Dato 3", "Dato 4"],
        unresolved_issues=["Pendiente 1", "Pendiente 2", "Pendiente 3", "Pendiente 4"],
        critical_questions=["Pregunta 1", "Pregunta 2", "Pregunta 3", "Pregunta 4"],
    )

    result = engine.evaluate(
        query="Murio mi padre y queremos iniciar la sucesion",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        case_theory=case_theory,
        question_engine_result=question_engine_result,
    )

    assert result.uncertainty_level == "alta"


def test_case_evaluation_engine_generic_fallback():
    engine = CaseEvaluationEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result = _payload(
        "accion_generica",
        "Consulta generica",
    )

    result = engine.evaluate(
        query="Necesito orientacion sobre un conflicto contractual",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        case_theory=case_theory,
        question_engine_result=question_engine_result,
    )

    assert result.possible_scenarios
    assert any("estrategia" in item.lower() or "informacion" in item.lower() for item in result.possible_scenarios)


def test_case_evaluation_engine_case_domain_overrides_generic_action_slug():
    engine = CaseEvaluationEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result = _payload(
        "generic",
        "Consulta generica",
        missing_information=["No esta claro si el bien es ganancial o propio."],
        unresolved_issues=["Falta precisar fecha de adquisicion del inmueble."],
    )

    result = engine.evaluate(
        query="como proceder para que mi ex renuncie a la cotitularidad de mi casa",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        case_theory=case_theory,
        question_engine_result=question_engine_result,
        case_domain="conflicto_patrimonial",
    )

    combined = " ".join(result.possible_scenarios + result.strategic_observations + result.warnings).lower()

    assert "generic" not in combined
    assert "handler generico" not in combined
    assert any(token in combined for token in ("adjudicacion", "liquidacion", "division", "ganancialidad"))


def test_case_evaluation_pipeline_integration_and_export():
    pipeline = AilexPipeline()

    result = pipeline.run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
    )
    payload = result.to_dict()

    assert payload["case_evaluation"]["case_strength"]
    assert payload["case_evaluation"]["possible_scenarios"]
    assert payload["case_evaluation"]["strategic_observations"]

    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": "Dos personas quieren divorciarse de comun acuerdo", "jurisdiction": "jujuy"},
    )
    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Estrategia juridica estructurada" in document_xml
    assert "Riesgos del caso" in document_xml
