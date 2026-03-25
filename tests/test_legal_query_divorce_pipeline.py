from legal_engine.ailex_pipeline import AilexPipeline


def test_pipeline_divorcio_mutuo_acuerdo_generates_non_generic_result():
    pipeline = AilexPipeline()

    result = pipeline.run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
        document_mode="formal",
    )
    payload = result.to_dict()

    assert payload["forum"] == "familia"
    assert payload["classification"]["action_slug"] == "divorcio_mutuo_acuerdo"
    assert payload["classification"]["process_type"] == "voluntario"
    assert payload["reasoning"]["normative_foundations"]
    assert any(
        item.get("article") in {"437", "438", "439", "717"}
        for item in payload["reasoning"]["normative_foundations"]
        if isinstance(item, dict)
    )
    assert payload["procedural_strategy"]["next_steps"]
    assert not any(
        "No se encontro un patron procesal especifico" in warning
        for warning in payload["warnings"]
    )
    assert payload["generated_document"]
    assert "Art. 437 CCyC" in payload["generated_document"]
    assert "convenio regulador" in payload["generated_document"].lower()


async def test_api_legal_query_divorcio_mutuo_acuerdo(client):
    response = await client.post(
        "/api/legal-query",
        json={
            "query": "Dos personas quieren divorciarse de comun acuerdo",
            "jurisdiction": "jujuy",
            "document_mode": "formal",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["forum"] == "familia"
    assert payload["classification"]["action_slug"] == "divorcio_mutuo_acuerdo"
    assert payload["reasoning"]["normative_foundations"]
    assert payload["procedural_strategy"]["next_steps"]
    assert payload["generated_document"]


def test_pipeline_divorcio_indirect_phrase_keeps_family_classification():
    pipeline = AilexPipeline()

    result = pipeline.run(
        query="Ambos conyuges decidieron terminar el matrimonio",
        jurisdiction="jujuy",
    )
    payload = result.to_dict()

    assert payload["forum"] == "familia"
    assert payload["classification"]["action_slug"] == "divorcio_mutuo_acuerdo"
    assert payload["reasoning"]["normative_foundations"]
