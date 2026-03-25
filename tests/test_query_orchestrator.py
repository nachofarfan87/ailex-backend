from __future__ import annotations

from legal_engine.query_orchestrator import QueryOrchestrator


class _FakePipelineResult:
    def __init__(self, payload: dict):
        self.payload = payload

    def to_dict(self) -> dict:
        return dict(self.payload)


class _FakePipeline:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def run_request(self, request, db=None, config=None):
        self.calls.append(
            {
                "request": request,
                "db": db,
                "config": dict(config or {}),
            }
        )
        return _FakePipelineResult(self.payload)


def _base_payload() -> dict:
    return {
        "query": "consulta legal",
        "jurisdiction": "jujuy",
        "forum": "familia",
        "classification": {
            "action_slug": "consulta_general",
            "action_label": "Consulta general",
            "jurisdiction": "jujuy",
            "forum": "familia",
        },
        "case_domain": "familia",
        "case_profile": {"case_domain": "familia"},
        "context": {"applicable_norms": [{"source_id": "CCyC", "article": "658", "score": 0.81}]},
        "retrieved_items": [{"source_id": "CCyC", "article": "658", "score": 0.81}],
        "normative_reasoning": {"applied_rules": [{"source": "CCyC", "article": "658"}]},
        "jurisprudence_analysis": {},
        "reasoning": {"short_answer": "Respuesta breve."},
        "legal_decision": {"dominant_factor": "norma", "confidence_score": 0.66, "execution_readiness": "lista"},
        "procedural_case_state": {"blocking_factor": "none"},
        "case_theory": {},
        "case_evaluation": {},
        "conflict_evidence": {},
        "warnings": [],
    }


def test_hybrid_retrieval_when_article_detected():
    pipeline = _FakePipeline(_base_payload())
    orchestrator = QueryOrchestrator(pipeline=pipeline)

    result = orchestrator.run(query="Que dice el art 658 CCyC sobre alimentos?", db=object())

    assert result.decision.retrieval_mode == "hybrid"
    assert pipeline.calls[0]["config"]["retrieval_mode"] == "hybrid"


def test_strategy_scoring_priority():
    pipeline = _FakePipeline(_base_payload())
    orchestrator = QueryOrchestrator(pipeline=pipeline)

    scores = orchestrator._score_strategy("No me notificaron y no puedo avanzar con la demanda")
    result = orchestrator.run(query="No me notificaron y no puedo avanzar con la demanda")

    assert round(sum(scores.values()), 4) == 1.0
    assert scores["cautious"] > scores["aggressive"]
    assert scores["cautious"] > scores["conservative"]
    assert result.decision.strategy_mode == "cautious"


def test_light_mode_outputs_not_empty():
    pipeline = _FakePipeline(_base_payload())
    orchestrator = QueryOrchestrator(pipeline=pipeline)

    result = orchestrator.run(query="Que es la filiacion?")

    assert result.decision.pipeline_mode == "light"
    assert result.pipeline_payload["case_theory"] == {"status": "skipped_light_mode"}
    assert result.pipeline_payload["case_evaluation"] == {"status": "skipped_light_mode"}
    assert result.pipeline_payload["conflict_evidence"] == {"status": "skipped_light_mode"}


def test_orchestrator_confidence_levels():
    pipeline = _FakePipeline(_base_payload())
    orchestrator = QueryOrchestrator(pipeline=pipeline)

    high = orchestrator.run(query="Quiero iniciar una demanda y presentar medida cautelar urgente")
    medium = orchestrator.run(query="Que dice el art 658 CCyC?")
    low = orchestrator.run(query="Consulta")

    assert high.decision.decision_confidence >= 0.75
    assert 0.5 <= medium.decision.decision_confidence < 0.75
    assert low.decision.decision_confidence < 0.5


def test_ambiguous_query_forces_full_mode():
    pipeline = _FakePipeline(_base_payload())
    orchestrator = QueryOrchestrator(pipeline=pipeline)

    scores = orchestrator._score_strategy("puedo reclamar alimentos o iniciar divorcio?")
    result = orchestrator.run(query="puedo reclamar alimentos o iniciar divorcio?")

    assert orchestrator._detect_ambiguity(scores, query_text="puedo reclamar alimentos o iniciar divorcio?") is True
    assert result.decision.pipeline_mode == "full"
    assert pipeline.calls[0]["config"]["light_mode"] is False


def test_disjunctive_branch_detects_ambiguity_without_multiple_action_verbs():
    pipeline = _FakePipeline(_base_payload())
    orchestrator = QueryOrchestrator(pipeline=pipeline)

    scores = orchestrator._score_strategy("Quiero saber alimentos o cuidado personal para mi hijo")
    result = orchestrator.run(query="Quiero saber alimentos o cuidado personal para mi hijo")

    assert orchestrator._detect_ambiguity(
        scores,
        query_text="Quiero saber alimentos o cuidado personal para mi hijo",
    ) is True
    assert result.decision.pipeline_mode == "full"
