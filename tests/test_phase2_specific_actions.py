from legal_engine.ailex_pipeline import AilexPipeline


CASES = [
    {
        "query": "Mi esposa no quiere divorciarse pero yo si",
        "action_slug": "divorcio_unilateral",
        "forum": "familia",
        "question_markers": ("domicilio", "propuesta reguladora"),
        "document_markers": ("DICTAMEN JURIDICO", "Consulta: Divorcio unilateral"),
    },
    {
        "query": "El padre de mi hijo no paga alimentos",
        "action_slug": "alimentos_hijos",
        "forum": "familia",
        "question_markers": ("edad", "gastos"),
        "document_markers": ("DICTAMEN JURIDICO", "Consulta: Alimentos para hijos"),
    },
    {
        "query": "Murio mi padre y queremos iniciar la sucesion",
        "action_slug": "sucesion_ab_intestato",
        "forum": "civil",
        "question_markers": ("domicilio", "herederos"),
        "document_markers": ("DICTAMEN JURIDICO", "Consulta: Sucesion ab intestato"),
    },
]


def test_phase2_specific_actions_pipeline_outputs():
    pipeline = AilexPipeline()

    for case in CASES:
        result = pipeline.run(
            query=case["query"],
            jurisdiction="jujuy",
            document_mode="formal",
        )
        payload = result.to_dict()

        assert payload["classification"]["action_slug"] == case["action_slug"]
        assert payload["classification"]["forum"] == case["forum"]

        assert payload["case_structure"]["summary"]
        assert payload["case_structure"]["main_claim"]
        assert payload["case_structure"]["forum"] == case["forum"]

        assert payload["normative_reasoning"]["summary"]
        assert payload["normative_reasoning"]["applied_rules"]
        assert not any(
            "fallback generico" in warning.lower()
            for warning in payload["normative_reasoning"].get("warnings", [])
        )

        assert payload["procedural_strategy"]["next_steps"]
        assert payload["procedural_strategy"]["missing_information"]
        assert payload["procedural_strategy"]["domain"] in {"family", "civil"}

        assert payload["question_engine_result"]["questions"]
        joined_questions = " ".join(
            item["question"].lower() for item in payload["question_engine_result"]["questions"]
        )
        assert any(marker in joined_questions for marker in case["question_markers"])

        assert payload["generated_document"]
        for marker in case["document_markers"]:
            assert marker in payload["generated_document"]
