from legal_engine.argument_generator import ArgumentGenerator
from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.procedural_strategy import ProceduralStrategy


DIVORCIO_QUERY = "Dos personas quieren divorciarse de comun acuerdo"


def test_procedural_strategy_dedupes_near_duplicate_risks():
    strategy = ProceduralStrategy()

    plan = strategy.generate(
        query=DIVORCIO_QUERY,
        jurisdiction="jujuy",
        classification={
            "action_slug": "divorcio_mutuo_acuerdo",
            "action_label": "Divorcio por mutuo acuerdo",
            "forum": "familia",
            "domain": "family",
        },
        case_structure={
            "risks": [
                "La omision de la propuesta reguladora impide dar tramite a la peticion.",
            ],
        },
        normative_reasoning={
            "unresolved_issues": [],
            "requirements": [],
        },
    )

    matching = [
        risk for risk in plan.risks
        if "propuesta reguladora" in risk.lower() and "dar tramite" in risk.lower()
    ]

    assert len(matching) == 1


def test_procedural_strategy_dedupes_semantic_missing_information():
    strategy = ProceduralStrategy()

    plan = strategy.generate(
        query=DIVORCIO_QUERY,
        jurisdiction="jujuy",
        classification={
            "action_slug": "divorcio_mutuo_acuerdo",
            "action_label": "Divorcio por mutuo acuerdo",
            "forum": "familia",
            "domain": "family",
        },
        case_structure={
            "missing_information": [
                "Existencia de hijos menores o con capacidad restringida.",
                "Bienes comunes, vivienda familiar y eventual compensacion economica.",
            ],
        },
        normative_reasoning={
            "unresolved_issues": [
                "No se informa sobre existencia de hijos menores o con capacidad restringida.",
                "No se informa sobre bienes gananciales o situacion patrimonial.",
            ],
            "requirements": [],
        },
    )

    children_items = [
        item for item in plan.missing_info
        if "hijos" in item.lower() and "capacidad restringida" in item.lower()
    ]
    patrimonial_items = [
        item for item in plan.missing_info
        if "bienes" in item.lower() or "compensacion economica" in item.lower()
    ]

    assert len(children_items) == 1
    assert len(patrimonial_items) == 1
    assert not any(item.lower().startswith("no se informa sobre") for item in plan.missing_info)


def test_argument_generator_formal_uses_professional_header():
    generator = ArgumentGenerator()

    result = generator.generate(
        query=DIVORCIO_QUERY,
        mode="formal",
        reasoning={
            "short_answer": "Procede el divorcio por presentacion conjunta.",
            "jurisdiction": "jujuy",
            "domain": "family",
            "confidence": 0.82,
        },
        classification={
            "action_label": "Divorcio por presentacion conjunta",
            "forum": "familia",
        },
        case_structure={
            "main_claim": "Peticion conjunta de divorcio con propuesta reguladora.",
            "forum": "familia",
        },
    )

    assert "DICTAMEN JURIDICO" in result.full_text
    assert "Consulta: Divorcio por presentacion conjunta" in result.full_text
    assert "Fuero: Familia" in result.full_text
    assert "Jurisdiccion: Jujuy" in result.full_text
    assert "DICTAMEN LEGAL: DOS PERSONAS QUIEREN DIVORCIARSE DE COMUN ACUERDO" not in result.full_text


def test_pipeline_divorcio_case_still_works_after_cleanup_changes():
    pipeline = AilexPipeline()

    result = pipeline.run(
        query=DIVORCIO_QUERY,
        jurisdiction="jujuy",
        document_mode="formal",
    )
    payload = result.to_dict()

    assert payload["classification"]["action_slug"] == "divorcio_mutuo_acuerdo"
    assert payload["procedural_strategy"]["risks"]
    assert payload["procedural_strategy"]["missing_information"]
    assert payload["generated_document"]
    assert "DICTAMEN JURIDICO" in payload["generated_document"]
