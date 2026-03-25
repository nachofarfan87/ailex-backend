import io
import json
from zipfile import ZipFile

from app.services.legal_export import build_legal_query_docx
from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.case_theory_engine import CaseTheoryEngine, CaseTheoryResult


def _base_payload(action_slug: str, action_label: str, forum: str) -> tuple[dict, dict, dict, dict, dict]:
    classification = {
        "action_slug": action_slug,
        "action_label": action_label,
        "forum": forum,
        "confidence_score": 0.85,
    }
    case_structure = {
        "facts": ["Hecho base del caso."],
        "missing_information": ["Dato faltante relevante."],
        "risks": ["Riesgo base."],
    }
    normative_reasoning = {
        "applied_rules": [{"article": "1", "source": "CCyC"}],
        "requirements": ["Requisito base."],
        "unresolved_issues": ["Cuestion pendiente base."],
        "warnings": [],
    }
    procedural_strategy = {
        "next_steps": ["Paso procesal base."],
        "missing_information": ["Informacion procesal faltante."],
    }
    question_engine_result = {
        "critical_questions": ["¿Pregunta critica base?"],
    }
    return classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result


def test_case_theory_engine_divorcio_mutuo_acuerdo():
    engine = CaseTheoryEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result = _base_payload(
        "divorcio_mutuo_acuerdo",
        "Divorcio por mutuo acuerdo",
        "familia",
    )

    result = engine.build(
        query="Dos personas quieren divorciarse de comun acuerdo",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
    )

    assert "voluntad concurrente" in result.primary_theory.lower()
    assert "sentencia de divorcio" in result.objective.lower()
    assert any("partida de matrimonio" in item.lower() for item in result.evidentiary_needs)


def test_case_theory_engine_divorcio_unilateral():
    engine = CaseTheoryEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result = _base_payload(
        "divorcio_unilateral",
        "Divorcio unilateral",
        "familia",
    )

    result = engine.build(
        query="Mi esposa no quiere divorciarse pero yo si",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
    )

    assert "unilateralmente" in result.primary_theory.lower()
    assert any("notificacion" in item.lower() for item in result.likely_points_of_conflict)


def test_case_theory_engine_alimentos_hijos():
    engine = CaseTheoryEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result = _base_payload(
        "alimentos_hijos",
        "Alimentos para hijos",
        "familia",
    )

    result = engine.build(
        query="El padre de mi hijo no paga alimentos",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
    )

    assert "incumplimiento" in result.primary_theory.lower()
    assert "cuota alimentaria" in " ".join(result.likely_points_of_conflict).lower() or "monto" in " ".join(result.likely_points_of_conflict).lower()


def test_case_theory_engine_sucesion_ab_intestato():
    engine = CaseTheoryEngine()
    classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result = _base_payload(
        "sucesion_ab_intestato",
        "Sucesion ab intestato",
        "civil",
    )

    result = engine.build(
        query="Murio mi padre y queremos iniciar la sucesion",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
        question_engine_result=question_engine_result,
    )

    assert "sucesion" in result.primary_theory.lower()
    assert any("partida de defuncion" in item.lower() for item in result.evidentiary_needs)


def test_case_theory_engine_generic_fallback():
    engine = CaseTheoryEngine()

    result = engine.build(
        query="Necesito revisar una situacion societaria",
        classification={"action_slug": "societario", "action_label": "Consulta societaria"},
        case_structure={"facts": ["Hecho."], "missing_information": ["Dato faltante."]},
        normative_reasoning={"unresolved_issues": ["Cuestion pendiente."]},
        procedural_strategy={"next_steps": ["Definir estrategia."]},
    )

    assert "fallback generico" in " ".join(result.warnings).lower()
    assert "teoria inicial generica" in result.summary.lower()


def test_case_theory_engine_case_domain_overrides_generic_action_slug():
    engine = CaseTheoryEngine()

    result = engine.build(
        query="como proceder para que mi ex renuncie a la cotitularidad de mi casa",
        classification={"action_slug": "generic", "action_label": "Consulta generica"},
        case_structure={"facts": ["Existe disputa por la cotitularidad del inmueble."]},
        normative_reasoning={"unresolved_issues": ["Falta definir si el bien es ganancial o propio."]},
        procedural_strategy={"next_steps": ["Ordenar titulo y estado registral del inmueble."]},
        question_engine_result={"critical_questions": ["¿El bien fue adquirido durante el matrimonio?"]},
        case_domain="conflicto_patrimonial",
    )

    combined = " ".join(
        [
            result.summary,
            result.primary_theory,
            result.objective,
            *result.recommended_line_of_action,
            *result.warnings,
        ]
    ).lower()

    assert "fallback generico" not in combined
    assert "generic" not in combined
    assert "cotitularidad" in combined or "patrimonial" in combined
    assert any(token in combined for token in ("adjudicacion", "liquidacion", "division"))


def test_case_theory_engine_serialization():
    result = CaseTheoryResult(
        summary="Resumen",
        primary_theory="Teoria principal",
        alternative_theories=["Alternativa"],
        objective="Objetivo",
        key_facts_supporting=["Hecho"],
        missing_facts=["Dato faltante"],
        likely_points_of_conflict=["Conflicto"],
        evidentiary_needs=["Prueba"],
        recommended_line_of_action=["Accion"],
        confidence_score=0.8,
        warnings=["Warning"],
    )

    payload = result.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)

    assert decoded["primary_theory"] == "Teoria principal"
    assert decoded["confidence_score"] == 0.8


def test_case_theory_engine_pipeline_and_export_integration():
    pipeline = AilexPipeline()
    result = pipeline.run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
        document_mode="formal",
    )
    payload = result.to_dict()

    assert payload["case_theory"]["primary_theory"]
    assert payload["case_theory"]["objective"]
    assert payload["case_theory"]["recommended_line_of_action"]

    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": "Dos personas quieren divorciarse de comun acuerdo", "jurisdiction": "jujuy"},
    )
    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Estrategia juridica estructurada" in document_xml
    assert "Estrategia:" in document_xml


async def test_case_theory_engine_api_integration(client):
    response = await client.post(
        "/api/legal-query",
        json={
            "query": "Dos personas quieren divorciarse de comun acuerdo",
            "jurisdiction": "jujuy",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_theory"]["primary_theory"]
    assert payload["case_theory"]["objective"]
