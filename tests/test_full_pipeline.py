# tests/test_full_pipeline.py

from legal_engine.ailex_pipeline import AilexPipeline, PipelineRequest


class FakeRetriever:
    def retrieve(self, query, top_k=5, jurisdiction=None, forum=None):
        return [
            {
                "source": "CPCC Jujuy",
                "article": "338",
                "title": "Contestación de demanda",
                "jurisdiction": jurisdiction or "jujuy",
                "text": "El demandado deberá contestar demanda dentro del plazo legal.",
                "score": 0.92,
            },
            {
                "source": "CPCC Jujuy",
                "article": "339",
                "title": "Plazo",
                "jurisdiction": jurisdiction or "jujuy",
                "text": "El plazo se computará según las reglas procesales aplicables.",
                "score": 0.88,
            },
        ]


class FakeContextBuilder:
    def build(self, query, retrieved_items, jurisdiction=None, forum=None):
        return {
            "user_query": query,
            "jurisdiction": jurisdiction,
            "applicable_norms": retrieved_items,
            "supporting_materials": [],
        }


class FakeReasoner:
    def reason(self, query, context, jurisdiction=None, forum=None):
        return {
            "short_answer": "Corresponde revisar el plazo procesal previsto en la normativa aplicable.",
            "normative_foundations": [
                {
                    "source": "CPCC Jujuy",
                    "article": "338",
                    "summary": "Regula la contestación de demanda.",
                }
            ],
            "case_analysis": "Con la evidencia recuperada, el plazo debe verificarse contra la notificación.",
            "warnings": ["La fecha de notificación no fue informada."],
            "citations_used": [
                {"source": "CPCC Jujuy", "article": "338"},
            ],
            "confidence": 0.78,
        }


class FakeCitationValidator:
    def validate(self, citations, context, reasoning):
        return {
            "valid": [{"source": "CPCC Jujuy", "article": "338"}],
            "invalid": [],
            "doubtful": [],
            "warnings": [],
        }


class FakeHallucinationGuard:
    def review(self, query, context, reasoning, citation_validation, jurisdiction=None, forum=None):
        return {
            "severity": "low",
            "warnings": [],
            "confidence_adjustment": -0.05,
        }


class FakeProceduralStrategy:
    def build(
        self,
        query,
        context,
        reasoning,
        jurisdiction=None,
        forum=None,
        facts=None,
        hallucination_guard=None,
    ):
        return {
            "next_steps": [
                "Verificar fecha exacta de notificación.",
                "Corroborar si el plazo corre por días hábiles.",
            ],
            "risks": [
                "Vencimiento del plazo si la fecha de notificación ya operó.",
            ],
            "missing_information": [
                "Fecha de notificación",
            ],
            "warnings": [],
        }


class FakeArgumentGenerator:
    def generate(
        self,
        mode,
        query,
        context,
        reasoning,
        strategy,
        citation_validation,
        hallucination_guard,
        jurisdiction=None,
        forum=None,
        facts=None,
    ):
        return {
            "text": (
                "DICTAMEN BREVE\n\n"
                "Consulta: plazo para contestar demanda.\n"
                "Norma citada: CPCC Jujuy art. 338.\n"
                "Advertencia: falta fecha de notificación."
            )
        }


class FakeClassifier:
    def __init__(self, payload):
        self.payload = payload

    def classify(self, query, jurisdiction=None, forum=None, metadata=None):
        _ = query, jurisdiction, forum, metadata
        return self.payload


class FakeCaseStructurer:
    def __init__(self, payload):
        self.payload = payload

    def structure(self, query, classification=None, jurisdiction=None, forum=None):
        _ = query, classification, jurisdiction, forum
        return self.payload


class FakeNormativeReasoner:
    def __init__(self, payload):
        self.payload = payload

    def reason(self, query, classification=None, case_structure=None, retrieved_chunks=None):
        _ = query, classification, case_structure, retrieved_chunks
        return self.payload


class FakeQuestionEngine:
    def generate(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy
        return {}


class FakeCaseTheoryEngine:
    def __init__(self, payload):
        self.payload = payload

    def build(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None, question_engine_result=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result
        return self.payload


class FakeCaseEvaluationEngine:
    def __init__(self, payload):
        self.payload = payload

    def evaluate(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None, case_theory=None, question_engine_result=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        return self.payload


class FakeConflictEvidenceEngine:
    def __init__(self, payload):
        self.payload = payload

    def analyze(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None, question_engine_result=None, case_theory=None, case_evaluation=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation
        return self.payload


class FakeEvidenceReasoningLinker:
    def __init__(self, payload):
        self.payload = payload

    def analyze(self, query, classification=None, case_structure=None, normative_reasoning=None, case_theory=None, case_evaluation=None, conflict_evidence=None, question_engine_result=None):
        _ = query, classification, case_structure, normative_reasoning, case_theory, case_evaluation, conflict_evidence, question_engine_result
        return self.payload


class FakeJurisprudenceEngine:
    def __init__(self, payload):
        self.payload = payload

    def analyze(self, query, classification=None, case_structure=None, normative_reasoning=None, case_theory=None, evidence_reasoning_links=None):
        _ = query, classification, case_structure, normative_reasoning, case_theory, evidence_reasoning_links
        return self.payload


class RecordingCaseTheoryEngine:
    def __init__(self):
        self.received_case_domain = None

    def build(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None, question_engine_result=None, case_domain=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result
        self.received_case_domain = case_domain
        return {
            "summary": f"teoria para {case_domain}",
            "primary_theory": "Existe conflicto patrimonial por cotitularidad.",
            "objective": "Definir adjudicacion, liquidacion o division.",
            "recommended_line_of_action": ["Evaluar adjudicacion o liquidacion."],
        }


class RecordingCaseEvaluationEngine:
    def __init__(self):
        self.received_case_domain = None

    def evaluate(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None, case_theory=None, question_engine_result=None, case_domain=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_theory, question_engine_result
        self.received_case_domain = case_domain
        return {
            "possible_scenarios": ["Liquidacion o division del inmueble segun origen del bien."],
            "strategic_observations": ["No asumir genericidad cuando hay conflicto patrimonial."],
            "warnings": [],
        }


class RecordingConflictEvidenceEngine:
    def __init__(self):
        self.received_case_domain = None

    def analyze(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None, question_engine_result=None, case_theory=None, case_evaluation=None, case_domain=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, question_engine_result, case_theory, case_evaluation
        self.received_case_domain = case_domain
        return {
            "core_dispute": "Cotitularidad patrimonial del inmueble.",
            "recommended_evidence_actions": ["Reunir titulo y definir adjudicacion o division."],
            "warnings": [],
        }


class RecordingProceduralStrategy:
    def __init__(self):
        self.received_case_domain = None

    def build(self, query, context, reasoning, jurisdiction=None, forum=None, facts=None, hallucination_guard=None, classification=None, case_structure=None, normative_reasoning=None, case_domain=None):
        _ = query, context, reasoning, jurisdiction, forum, facts, hallucination_guard, classification, case_structure, normative_reasoning
        self.received_case_domain = case_domain
        return {
            "next_steps": ["Definir adjudicacion, liquidacion o division."],
            "risks": ["No esta claro si el bien es ganancial o propio."],
            "missing_information": ["Fecha de adquisicion del inmueble."],
            "warnings": [],
        }


def build_pipeline():
    return AilexPipeline(
        retriever=FakeRetriever(),
        context_builder=FakeContextBuilder(),
        legal_reasoner=FakeReasoner(),
        citation_validator=FakeCitationValidator(),
        hallucination_guard=FakeHallucinationGuard(),
        procedural_strategy=FakeProceduralStrategy(),
        argument_generator=FakeArgumentGenerator(),
    )


def build_strategy_pipeline(*, classification, case_theory, conflict_evidence, normative_reasoning, case_evaluation=None):
    return AilexPipeline(
        retriever=FakeRetriever(),
        context_builder=FakeContextBuilder(),
        legal_reasoner=FakeReasoner(),
        citation_validator=FakeCitationValidator(),
        hallucination_guard=FakeHallucinationGuard(),
        procedural_strategy=FakeProceduralStrategy(),
        question_engine=FakeQuestionEngine(),
        case_theory_engine=FakeCaseTheoryEngine(case_theory),
        case_evaluation_engine=FakeCaseEvaluationEngine(case_evaluation or {}),
        conflict_evidence_engine=FakeConflictEvidenceEngine(conflict_evidence),
        evidence_reasoning_linker=FakeEvidenceReasoningLinker({}),
        jurisprudence_engine=FakeJurisprudenceEngine({}),
        argument_generator=FakeArgumentGenerator(),
        action_classifier=FakeClassifier(classification),
        case_structurer=FakeCaseStructurer({"action_slug": classification.get("action_slug", ""), "facts": [], "applicable_rules": []}),
        normative_reasoner=FakeNormativeReasoner(normative_reasoning),
    )


def test_pipeline_run_end_to_end_without_document_mode():
    pipeline = build_pipeline()

    result = pipeline.run(
        query="plazo para contestar demanda",
        jurisdiction="jujuy",
        top_k=5,
    )

    assert result.query == "plazo para contestar demanda"
    assert result.jurisdiction == "jujuy"
    assert len(result.retrieved_items) == 2
    assert result.context["jurisdiction"] == "jujuy"
    assert result.reasoning["short_answer"]
    assert result.citation_validation["invalid"] == []
    assert result.hallucination_guard["severity"] == "low"
    assert result.procedural_strategy["next_steps"]
    assert isinstance(result.case_profile, dict)
    assert isinstance(result.case_strategy, dict)
    assert isinstance(result.legal_strategy, dict)
    assert isinstance(result.legal_decision, dict)
    assert result.legal_strategy["case_profile"] == result.case_profile
    assert result.legal_strategy["case_strategy"] == result.case_strategy
    assert result.legal_strategy["legal_decision"] == result.legal_decision
    assert result.generated_document is None
    assert 0.18 <= result.confidence <= 0.92


def test_pipeline_run_end_to_end_with_document_mode():
    pipeline = build_pipeline()

    result = pipeline.run(
        query="plazo para contestar demanda",
        jurisdiction="jujuy",
        top_k=5,
        document_mode="formal",
    )

    assert isinstance(result.generated_document, str)
    assert isinstance(result.case_profile, dict)
    assert isinstance(result.case_strategy, dict)
    assert isinstance(result.legal_strategy, dict)
    assert result.generated_document


def test_pipeline_result_to_dict_is_serializable():
    pipeline = build_pipeline()

    result = pipeline.run(
        query="plazo para contestar demanda",
        jurisdiction="jujuy",
        document_mode="breve",
    )

    payload = result.to_dict()

    assert payload["query"] == "plazo para contestar demanda"
    assert isinstance(payload["retrieved_items"], list)
    assert isinstance(payload["context"], dict)
    assert isinstance(payload["reasoning"], dict)
    assert isinstance(payload["citation_validation"], dict)
    assert isinstance(payload["hallucination_guard"], dict)
    assert isinstance(payload["procedural_strategy"], dict)
    assert isinstance(payload["case_profile"], dict)
    assert isinstance(payload["case_strategy"], dict)
    assert isinstance(payload["legal_strategy"], dict)
    assert isinstance(payload["legal_decision"], dict)


def test_pipeline_collects_warnings_from_stages():
    pipeline = build_pipeline()

    result = pipeline.run(
        query="plazo para contestar demanda",
        jurisdiction="jujuy",
    )

    assert "La fecha de notificación no fue informada." in result.warnings


def test_pipeline_run_request_accepts_dataclass_request():
    pipeline = build_pipeline()

    request = PipelineRequest(
        query="plazo para contestar demanda",
        jurisdiction="jujuy",
        document_mode="formal",
    )

    result = pipeline.run_request(request)

    assert result.query == request.query
    assert isinstance(result.generated_document, str)
    assert isinstance(result.case_profile, dict)
    assert isinstance(result.case_strategy, dict)
    assert isinstance(result.legal_strategy, dict)
    assert isinstance(result.legal_decision, dict)


def test_pipeline_gracefully_handles_components_with_missing_methods():
    class NullObject:
        pass

    pipeline = AilexPipeline(
        retriever=NullObject(),
        context_builder=NullObject(),
        legal_reasoner=NullObject(),
        citation_validator=NullObject(),
        hallucination_guard=NullObject(),
        procedural_strategy=NullObject(),
        argument_generator=NullObject(),
    )

    result = pipeline.run(
        query="plazo para contestar demanda",
        jurisdiction="jujuy",
        document_mode="formal",
    )

    assert result.retrieved_items == []
    assert result.context == {}
    assert result.reasoning == {}
    assert result.citation_validation == {}
    assert result.hallucination_guard == {}
    assert result.procedural_strategy == {}
    assert result.generated_document is None
    assert isinstance(result.case_profile, dict)
    assert isinstance(result.case_strategy, dict)
    assert "case_profile" in result.legal_strategy
    assert "case_strategy" in result.legal_strategy
    assert "legal_decision" in result.legal_strategy


def test_pipeline_legal_strategy_is_built_from_case_profile_and_case_strategy():
    pipeline = build_strategy_pipeline(
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos", "forum": "familia", "jurisdiction": "jujuy"},
        case_theory={
            "primary_theory": "La hija tiene 22 anos y no estudia; corresponde revisar continuidad de cuota.",
            "objective": "Determinar si la cuota puede sostenerse.",
        },
        conflict_evidence={
            "core_dispute": "Alcance de cuota alimentaria para hija de 22 anos que no estudia.",
            "most_vulnerable_point": "Falta precisar ingresos propios.",
        },
        normative_reasoning={"requirements": ["Precisar edad, estudio e ingresos."], "applied_rules": []},
    )

    result = pipeline.run(
        query="hasta que edad mi ex esposo puede pasar cuota alimentaria si mi hija tiene 22 y no estudia",
        jurisdiction="jujuy",
    )

    assert "case_profile" in result.legal_strategy
    assert "case_strategy" in result.legal_strategy
    assert "legal_decision" in result.legal_strategy
    assert result.case_domain == "alimentos"
    assert result.case_profile["is_alimentos"] is True
    assert "hijo_mayor_no_estudia" in result.case_profile["scenarios"]
    combined = " ".join(result.case_strategy["recommended_actions"] + result.case_strategy["risk_analysis"]).lower()
    assert "regularidad academica" not in combined


def test_pipeline_patrimonial_case_does_not_fall_back_to_generic_strategy():
    pipeline = build_strategy_pipeline(
        classification={"action_slug": "generic", "action_label": "Consulta general", "forum": "civil", "jurisdiction": "jujuy"},
        case_theory={
            "primary_theory": "Existe conflicto por cotitularidad de la casa con ex esposo.",
            "objective": "Definir si corresponde adjudicacion, liquidacion o particion.",
            "likely_points_of_conflict": ["Cotitularidad del inmueble y falta de acuerdo."],
        },
        conflict_evidence={
            "core_dispute": "Como resolver la cotitularidad de la vivienda con el ex esposo.",
            "most_vulnerable_point": "No esta claro si el bien es ganancial o propio.",
        },
        normative_reasoning={
            "summary": "Se aplico razonamiento normativo generico para la consulta.",
            "warnings": ["No existe handler normativo especifico; se uso fallback generico."],
            "applied_rules": [
                {"source": "Constitucion Nacional", "article": "51", "effect": "Norma irrelevante para la disputa patrimonial."},
            ],
        },
    )

    result = pipeline.run(
        query="como tendria que proceder para que mi ex esposo renuncie a la cotitularidad de mi casa",
        jurisdiction="jujuy",
    )

    combined = " ".join(result.case_strategy["conflict_summary"] + result.case_strategy["recommended_actions"]).lower()
    assert result.case_domain == "conflicto_patrimonial"
    assert result.legal_strategy["case_domain"] == "conflicto_patrimonial"
    assert "generic" not in result.case_domain
    assert result.case_strategy
    assert "conflicto patrimonial" in combined
    assert "convenio de adjudicacion" in combined
    assert any(token in combined for token in ("adjudicacion", "liquidacion", "division"))
    assert "ganancial o propio" in combined
    assert result.case_strategy["conflict_summary"]
    assert result.normative_reasoning["applied_rules"] == []
    assert isinstance(result.legal_decision, dict)


def test_pipeline_passes_case_domain_to_downstream_engines_even_if_classification_is_generic():
    procedural = RecordingProceduralStrategy()
    case_theory_engine = RecordingCaseTheoryEngine()
    case_evaluation_engine = RecordingCaseEvaluationEngine()
    conflict_engine = RecordingConflictEvidenceEngine()

    pipeline = AilexPipeline(
        retriever=FakeRetriever(),
        context_builder=FakeContextBuilder(),
        legal_reasoner=FakeReasoner(),
        citation_validator=FakeCitationValidator(),
        hallucination_guard=FakeHallucinationGuard(),
        procedural_strategy=procedural,
        question_engine=FakeQuestionEngine(),
        case_theory_engine=case_theory_engine,
        case_evaluation_engine=case_evaluation_engine,
        conflict_evidence_engine=conflict_engine,
        evidence_reasoning_linker=FakeEvidenceReasoningLinker({}),
        jurisprudence_engine=FakeJurisprudenceEngine({}),
        argument_generator=FakeArgumentGenerator(),
        action_classifier=FakeClassifier({"action_slug": "generic", "action_label": "Consulta general", "forum": "civil", "jurisdiction": "jujuy"}),
        case_structurer=FakeCaseStructurer({"action_slug": "generic", "facts": [], "applicable_rules": []}),
        normative_reasoner=FakeNormativeReasoner({"warnings": [], "applied_rules": []}),
    )

    result = pipeline.run(
        query="como proceder para que mi ex renuncie a la cotitularidad de mi casa",
        jurisdiction="jujuy",
    )

    assert result.case_domain == "conflicto_patrimonial"
    assert procedural.received_case_domain == "conflicto_patrimonial"
    assert case_theory_engine.received_case_domain == "conflicto_patrimonial"
    assert case_evaluation_engine.received_case_domain == "conflicto_patrimonial"
    assert conflict_engine.received_case_domain == "conflicto_patrimonial"


def test_pipeline_legal_decision_aligns_strategy_with_cautious_posture():
    pipeline = build_strategy_pipeline(
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos para hijos", "forum": "familia", "jurisdiction": "jujuy"},
        case_theory={
            "primary_theory": "Existe incumplimiento alimentario pero la prueba de ingresos aun es debil.",
            "objective": "Obtener cuota provisoria sin exponer un rechazo por falta de soporte.",
            "evidentiary_needs": ["recibos", "constancia de gastos"],
        },
        conflict_evidence={
            "core_dispute": "Incumplimiento alimentario actual.",
            "most_vulnerable_point": "Falta prueba de ingresos del demandado.",
            "key_evidence_missing": ["recibos de sueldo"],
        },
        normative_reasoning={
            "requirements": ["Acreditar necesidades del hijo."],
            "applied_rules": [{"source": "CCyC", "article": "658", "effect": "Obligacion alimentaria."}],
            "unresolved_issues": ["falta prueba de ingresos", "falta documentacion basica"],
            "confidence_score": 0.82,
        },
        case_evaluation={"strength_score": 0.72, "risk_score": 0.81, "legal_risk_level": "alto"},
    )

    result = pipeline.run(
        query="necesito cuota alimentaria pero no tengo recibos del padre",
        jurisdiction="jujuy",
    )

    assert result.legal_decision["strategic_posture"] == "cautelosa"
    narrative = result.case_strategy["strategic_narrative"].lower()
    focus = " ".join(result.case_strategy["procedural_focus"]).lower()
    assert any(term in narrative for term in ("saneamiento", "prudencia", "contencion"))
    assert "priorizar saneamiento" in focus
