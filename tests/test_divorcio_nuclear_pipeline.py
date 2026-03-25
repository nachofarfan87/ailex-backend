from legal_engine.ailex_pipeline import AilexPipeline


DIVORCIO_QUERIES = [
    "Quiero divorciarme",
    "Quiero el divorcio",
    "Me quiero divorciar",
]


def test_pipeline_basic_divorce_queries_do_not_fall_back_to_generic():
    pipeline = AilexPipeline()

    for query in DIVORCIO_QUERIES:
        result = pipeline.run(
            query=query,
            jurisdiction="jujuy",
            document_mode="formal",
        )
        payload = result.to_dict()

        assert payload["classification"]["action_slug"] == "divorcio"
        assert payload["classification"]["forum"] == "familia"
        assert payload["forum"] == "familia"

        assert payload["case_structure"]["action_slug"] == "divorcio"
        assert payload["case_structure"]["forum"] == "familia"
        assert payload["case_structure"]["summary"]

        assert payload["normative_reasoning"]["summary"]
        assert payload["normative_reasoning"]["applied_rules"]
        assert not any(
            "fallback generico" in warning.lower()
            for warning in payload["normative_reasoning"].get("warnings", [])
        )

        assert payload["procedural_strategy"]["next_steps"]
        assert payload["procedural_strategy"]["domain"] == "family"
        assert not any(
            "plan procesal generico" in warning.lower()
            for warning in payload["procedural_strategy"].get("warnings", [])
        )

        assert payload["question_engine_result"]["questions"]
        assert payload["case_theory"]["primary_theory"]
        assert "generica" not in payload["case_theory"]["summary"].lower()

        assert payload["generated_document"]
        assert "DICTAMEN JURIDICO" in payload["generated_document"]
        assert "Consulta: Divorcio" in payload["generated_document"]
