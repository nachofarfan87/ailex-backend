"""
Tests de integracion Fase 1 -- CaseStructurer + NormativeReasoner en el pipeline.

Ejecutar:
    cd backend && python -m pytest tests/test_phase1_integration.py -v
"""

import json

import pytest

from legal_engine.ailex_pipeline import AilexPipeline, PipelineResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIVORCIO_QUERY = "Dos personas quieren divorciarse de comun acuerdo"
INDIRECT_QUERY = "Ambos conyuges decidieron terminar el matrimonio"


def _run_divorcio(document_mode=None):
    pipeline = AilexPipeline()
    return pipeline.run(
        query=DIVORCIO_QUERY,
        jurisdiction="jujuy",
        document_mode=document_mode,
    )


# ---------------------------------------------------------------------------
# Pipeline includes case_structure
# ---------------------------------------------------------------------------

class TestPipelineCaseStructure:

    def test_case_structure_present_in_result(self):
        result = _run_divorcio()
        payload = result.to_dict()
        assert "case_structure" in payload
        assert isinstance(payload["case_structure"], dict)
        assert payload["case_structure"] != {}

    def test_case_structure_action_slug(self):
        result = _run_divorcio()
        cs = result.to_dict()["case_structure"]
        assert cs["action_slug"] == "divorcio_mutuo_acuerdo"

    def test_case_structure_main_claim_divorcio(self):
        result = _run_divorcio()
        cs = result.to_dict()["case_structure"]
        main_claim = cs.get("main_claim", "").lower()
        assert "divorcio" in main_claim or "peticion conjunta" in main_claim

    def test_case_structure_has_facts(self):
        result = _run_divorcio()
        cs = result.to_dict()["case_structure"]
        assert len(cs.get("facts", [])) > 0

    def test_case_structure_has_applicable_rules(self):
        result = _run_divorcio()
        cs = result.to_dict()["case_structure"]
        rules = cs.get("applicable_rules", [])
        assert len(rules) > 0
        articles = {r["article"] for r in rules if isinstance(r, dict)}
        assert "438" in articles, "Debe incluir art. 438 (propuesta reguladora)"

    def test_case_structure_has_missing_information(self):
        result = _run_divorcio()
        cs = result.to_dict()["case_structure"]
        assert len(cs.get("missing_information", [])) > 0

    def test_case_structure_has_risks(self):
        result = _run_divorcio()
        cs = result.to_dict()["case_structure"]
        assert len(cs.get("risks", [])) > 0


# ---------------------------------------------------------------------------
# Pipeline includes normative_reasoning
# ---------------------------------------------------------------------------

class TestPipelineNormativeReasoning:

    def test_normative_reasoning_present_in_result(self):
        result = _run_divorcio()
        payload = result.to_dict()
        assert "normative_reasoning" in payload
        assert isinstance(payload["normative_reasoning"], dict)
        assert payload["normative_reasoning"] != {}

    def test_normative_reasoning_inferences_not_empty(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        inferences = nr.get("inferences", [])
        assert len(inferences) > 0, "inferences debe ser no vacio"

    def test_normative_reasoning_requirements_not_empty(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        requirements = nr.get("requirements", [])
        assert len(requirements) > 0, "requirements debe ser no vacio"

    def test_normative_reasoning_applied_rules_not_empty(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        applied_rules = nr.get("applied_rules", [])
        assert len(applied_rules) > 0

    def test_normative_reasoning_inferences_mention_incausado(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        text = " ".join(nr.get("inferences", [])).lower()
        assert "incausado" in text

    def test_normative_reasoning_inferences_mention_conjunta(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        text = " ".join(nr.get("inferences", [])).lower()
        assert "conjunta" in text

    def test_normative_reasoning_inferences_mention_propuesta(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        text = " ".join(nr.get("inferences", [])).lower()
        assert "propuesta reguladora" in text

    def test_normative_reasoning_confidence_reasonable(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        assert nr.get("confidence_score", 0) > 0.50

    def test_normative_reasoning_has_summary(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        assert nr.get("summary", "").strip()


# ---------------------------------------------------------------------------
# Procedural strategy coherent
# ---------------------------------------------------------------------------

class TestPipelineProceduralStrategy:

    def test_strategy_not_generic(self):
        result = _run_divorcio()
        payload = result.to_dict()
        assert not any(
            "No se encontro un patron procesal especifico" in w
            for w in payload.get("warnings", [])
        )

    def test_strategy_has_steps(self):
        result = _run_divorcio()
        ps = result.to_dict()["procedural_strategy"]
        assert len(ps.get("next_steps", [])) > 0 or len(ps.get("steps", [])) > 0

    def test_strategy_mentions_propuesta(self):
        result = _run_divorcio()
        ps = result.to_dict()["procedural_strategy"]
        full_text = json.dumps(ps, ensure_ascii=False).lower()
        assert "propuesta" in full_text or "convenio" in full_text


# ---------------------------------------------------------------------------
# Generated document not generic
# ---------------------------------------------------------------------------

class TestPipelineGeneratedDocument:

    def test_formal_document_generated(self):
        result = _run_divorcio(document_mode="formal")
        assert result.to_dict()["generated_document"]

    def test_formal_document_has_inferences(self):
        """Document should include normative reasoning inferences."""
        result = _run_divorcio(document_mode="formal")
        doc = result.to_dict()["generated_document"].lower()
        assert "incausado" in doc or "propuesta reguladora" in doc

    def test_formal_document_has_applied_rules(self):
        """Document should mention specific articles with effects."""
        result = _run_divorcio(document_mode="formal")
        doc = result.to_dict()["generated_document"]
        assert "Art. 438" in doc or "art. 438" in doc or "438" in doc

    def test_base_argumental_has_inferences(self):
        """base_argumental mode should include normative reasoning inferences."""
        pipeline = AilexPipeline()
        result = pipeline.run(
            query=DIVORCIO_QUERY,
            jurisdiction="jujuy",
            document_mode="base_argumental",
        )
        doc = result.to_dict()["generated_document"]
        assert doc
        doc_lower = doc.lower()
        assert "incausado" in doc_lower or "inferencias" in doc_lower


# ---------------------------------------------------------------------------
# Indirect phrase
# ---------------------------------------------------------------------------

class TestPipelineIndirectPhrase:

    def test_indirect_phrase_classified_correctly(self):
        pipeline = AilexPipeline()
        result = pipeline.run(query=INDIRECT_QUERY, jurisdiction="jujuy")
        payload = result.to_dict()
        assert payload["classification"]["action_slug"] == "divorcio_mutuo_acuerdo"

    def test_indirect_phrase_has_case_structure(self):
        pipeline = AilexPipeline()
        result = pipeline.run(query=INDIRECT_QUERY, jurisdiction="jujuy")
        cs = result.to_dict()["case_structure"]
        assert cs.get("action_slug") == "divorcio_mutuo_acuerdo"

    def test_indirect_phrase_has_normative_reasoning(self):
        pipeline = AilexPipeline()
        result = pipeline.run(query=INDIRECT_QUERY, jurisdiction="jujuy")
        nr = result.to_dict()["normative_reasoning"]
        assert len(nr.get("inferences", [])) > 0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestPipelineSerialization:

    def test_full_result_json_serializable(self):
        result = _run_divorcio(document_mode="formal")
        payload = result.to_dict()
        json_str = json.dumps(payload, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert "case_structure" in parsed
        assert "normative_reasoning" in parsed

    def test_case_structure_serializable(self):
        result = _run_divorcio()
        cs = result.to_dict()["case_structure"]
        json.dumps(cs, ensure_ascii=False)

    def test_normative_reasoning_serializable(self):
        result = _run_divorcio()
        nr = result.to_dict()["normative_reasoning"]
        json.dumps(nr, ensure_ascii=False)


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_legal_query_returns_case_structure(client):
    response = await client.post(
        "/api/legal-query",
        json={"query": DIVORCIO_QUERY, "jurisdiction": "jujuy"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "case_structure" in payload
    assert payload["case_structure"]["action_slug"] == "divorcio_mutuo_acuerdo"


@pytest.mark.asyncio
async def test_api_legal_query_returns_normative_reasoning(client):
    response = await client.post(
        "/api/legal-query",
        json={"query": DIVORCIO_QUERY, "jurisdiction": "jujuy"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "normative_reasoning" in payload
    assert len(payload["normative_reasoning"].get("inferences", [])) > 0
    assert len(payload["normative_reasoning"].get("requirements", [])) > 0


# ---------------------------------------------------------------------------
# Export does not break
# ---------------------------------------------------------------------------

def test_export_with_new_fields_does_not_break():
    from app.services.legal_export import build_legal_query_docx

    result = _run_divorcio(document_mode="formal")
    payload = result.to_dict()

    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": DIVORCIO_QUERY, "jurisdiction": "jujuy"},
    )
    assert isinstance(content, bytes)
    assert len(content) > 0


# ---------------------------------------------------------------------------
# Backward compat: old fake components still work
# ---------------------------------------------------------------------------

def test_pipeline_backward_compat_with_fake_components():
    """Pipeline works with components that don't know about new steps."""

    class FakeRetriever:
        def retrieve(self, query, top_k=5, jurisdiction=None, forum=None):
            return [{"source": "test", "article": "1", "text": "test", "score": 0.9}]

    class FakeContextBuilder:
        def build(self, query, retrieved_items, jurisdiction=None, forum=None):
            return {"applicable_norms": retrieved_items}

    class FakeReasoner:
        def reason(self, query, context, jurisdiction=None, forum=None):
            return {"short_answer": "test", "confidence": 0.8}

    class NullObject:
        pass

    pipeline = AilexPipeline(
        retriever=FakeRetriever(),
        context_builder=FakeContextBuilder(),
        legal_reasoner=FakeReasoner(),
        citation_validator=NullObject(),
        hallucination_guard=NullObject(),
        procedural_strategy=NullObject(),
        argument_generator=NullObject(),
    )

    result = pipeline.run(query="test query", jurisdiction="jujuy")
    payload = result.to_dict()

    assert payload["query"] == "test query"
    assert isinstance(payload["case_structure"], dict)
    assert isinstance(payload["normative_reasoning"], dict)
    assert len(payload["retrieved_items"]) == 1
