import io
import json
from zipfile import ZipFile

from app.services.legal_export import build_legal_query_docx
from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.question_engine import (
    QuestionEngine,
    QuestionEngineResult,
    QuestionItem,
)


DIVORCIO_QUERY = "Dos personas quieren divorciarse de comun acuerdo"


def test_question_engine_divorcio_base_case():
    engine = QuestionEngine()

    result = engine.generate(
        query=DIVORCIO_QUERY,
        classification={
            "action_slug": "divorcio_mutuo_acuerdo",
            "action_label": "Divorcio por mutuo acuerdo",
        },
        case_structure={
            "missing_information": [
                "Existencia de hijos menores o con capacidad restringida.",
                "Bienes gananciales o propios en comun.",
                "Ultimo domicilio conyugal.",
            ],
            "risks": [
                "La omision de la propuesta reguladora impide dar tramite a la peticion.",
            ],
            "facts": [],
        },
        normative_reasoning={
            "requirements": [
                "Propuesta reguladora de los efectos del divorcio (art. 438 CCyC).",
                "Determinacion sobre alimentos entre conyuges.",
            ],
            "unresolved_issues": [
                "No se indica si corresponde o se pacta compensacion economica.",
            ],
        },
        procedural_strategy={
            "missing_information": [
                "Ultimo domicilio conyugal o domicilio actual de las partes.",
            ],
            "risks": [
                "Un convenio regulador incompleto puede generar observaciones judiciales.",
            ],
        },
    )

    payload = result.to_dict()

    assert payload["summary"]
    assert payload["confidence_score"] > 0.6
    assert len(payload["questions"]) >= 6
    assert payload["critical_questions"]

    categories = {item["category"] for item in payload["questions"]}
    assert "hijos_menores" in categories
    assert "bienes_gananciales" in categories
    assert "convenio_regulador" in categories
    assert "alimentos" in categories
    assert "compensacion_economica" in categories
    assert "competencia_domicilio" in categories

    priorities = {item["priority"] for item in payload["questions"]}
    assert "alta" in priorities


def test_question_engine_serialization():
    result = QuestionEngineResult(
        summary="Resumen",
        questions=[
            QuestionItem(
                question="¿Hay hijos menores?",
                purpose="Definir plan de parentalidad.",
                priority="alta",
                category="hijos_menores",
            )
        ],
        critical_questions=["¿Hay hijos menores?"],
        confidence_score=0.81,
    )

    payload = result.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)

    assert decoded["summary"] == "Resumen"
    assert decoded["questions"][0]["priority"] == "alta"
    assert decoded["critical_questions"] == ["¿Hay hijos menores?"]


def test_question_engine_generic_fallback():
    engine = QuestionEngine()

    result = engine.generate(
        query="Necesito revisar una situacion societaria",
        classification={
            "action_slug": "accion_no_soportada",
            "action_label": "Consulta societaria",
        },
        case_structure={
            "missing_information": ["Hechos relevantes del caso."],
            "risks": ["Sin informacion suficiente para evaluar riesgos especificos."],
        },
        normative_reasoning={
            "requirements": ["Informacion requerida: documentacion societaria."],
            "unresolved_issues": ["Falta identificar el acto juridico cuestionado."],
        },
        procedural_strategy={
            "missing_information": ["Antecedentes del expediente."],
        },
    )

    payload = result.to_dict()

    assert "fallback generico" in payload["summary"].lower()
    assert payload["questions"]
    assert payload["critical_questions"]
    assert any(item["category"] == "completitud_general" for item in payload["questions"])


def test_question_engine_pipeline_integration():
    pipeline = AilexPipeline()

    result = pipeline.run(query=DIVORCIO_QUERY, jurisdiction="jujuy")
    payload = result.to_dict()

    assert "question_engine_result" in payload
    assert payload["question_engine_result"]["summary"]
    assert payload["question_engine_result"]["questions"]
    assert any(
        item["category"] == "convenio_regulador"
        for item in payload["question_engine_result"]["questions"]
    )


async def test_question_engine_api_integration(client):
    response = await client.post(
        "/api/legal-query",
        json={"query": DIVORCIO_QUERY, "jurisdiction": "jujuy"},
    )

    assert response.status_code == 200
    payload = response.json()

    assert "question_engine_result" in payload
    assert payload["question_engine_result"]["critical_questions"]
    assert any(
        item["priority"] == "alta"
        for item in payload["question_engine_result"]["questions"]
    )


def test_question_engine_export_integration():
    pipeline = AilexPipeline()
    result = pipeline.run(query=DIVORCIO_QUERY, jurisdiction="jujuy")
    payload = result.to_dict()

    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": DIVORCIO_QUERY, "jurisdiction": "jujuy"},
    )

    assert isinstance(content, bytes)
    assert len(content) > 0

    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Preguntas clave para completar el caso" in document_xml
    assert "convenio regulador" in document_xml.lower()
