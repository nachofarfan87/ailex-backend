from __future__ import annotations

from typing import Any

from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.normative_reasoner import NormativeReasoner


class _StaticRetriever:
    def retrieve(self, query, top_k=5, jurisdiction=None, forum=None):
        _ = query, top_k, jurisdiction, forum
        return [{"source_id": "codigo_civil_comercial", "article": "658", "texto": "texto", "score": 0.8}]


class _StaticContextBuilder:
    def build(self, query, retrieved_items, jurisdiction=None, forum=None):
        return {
            "query": query,
            "jurisdiction": jurisdiction or "jujuy",
            "domain": "family",
            "applicable_norms": retrieved_items,
            "total_chars": 100,
            "truncated": False,
            "source_ids_used": ["codigo_civil_comercial"],
            "context_text": "",
            "formatted_sections": {},
            "warnings": [],
        }


class _StaticReasoner:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def reason(self, query, context, jurisdiction=None, forum=None, classification=None):
        _ = query, context, jurisdiction, forum, classification
        return {
            "query": query,
            "short_answer": self.payload.get("short_answer", "Respuesta estructurada."),
            "applied_analysis": self.payload.get("applied_analysis", "Analisis estructurado."),
            "confidence_score": self.payload.get("confidence_score", 0.75),
            "confidence": self.payload.get("confidence", "medium"),
            "warnings": self.payload.get("warnings", []),
            "normative_grounds": [],
            "citations_used": [],
            "limitations": [],
            "evidence_sufficient": True,
            "domain": "family",
            "jurisdiction": jurisdiction or "jujuy",
        }


class _StaticCitationValidator:
    def validate(self, context, reasoning):
        _ = context, reasoning
        return {"valid": [], "invalid": [], "doubtful": [], "warnings": []}


class _StaticHallucinationGuard:
    def review(self, query, context, reasoning, citation_validation, jurisdiction=None, forum=None):
        _ = query, context, reasoning, citation_validation, jurisdiction, forum
        return {"severity": "low", "warnings": [], "confidence_adjustment": 1.0}


class _StaticProceduralStrategy:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {}

    def build(self, query, context, reasoning, jurisdiction=None, forum=None, facts=None, hallucination_guard=None, classification=None, case_structure=None, normative_reasoning=None, case_domain=None):
        _ = query, context, reasoning, jurisdiction, forum, facts, hallucination_guard, classification, case_structure, normative_reasoning, case_domain
        return {
            "next_steps": self.payload.get("next_steps", ["Ordenar soporte y definir presentacion."]),
            "risks": self.payload.get("risks", []),
            "missing_information": self.payload.get("missing_information", []),
            "warnings": self.payload.get("warnings", []),
        }


class _StaticQuestionEngine:
    def generate(self, query, classification=None, case_structure=None, normative_reasoning=None, procedural_strategy=None, case_domain=None):
        _ = query, classification, case_structure, normative_reasoning, procedural_strategy, case_domain
        return {}


class _StaticClassifier:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def classify(self, query, jurisdiction=None, forum=None, metadata=None):
        _ = query, jurisdiction, forum, metadata
        return self.payload


class _StaticCaseStructurer:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def structure(self, query, classification=None, jurisdiction=None, forum=None):
        _ = query, classification, jurisdiction, forum
        return self.payload


class _StaticNormativeReasoner:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self._delegate = NormativeReasoner()

    def reason(self, query, classification=None, case_structure=None, retrieved_chunks=None):
        _ = query, classification, case_structure, retrieved_chunks
        return self.payload

    def integrate_jurisprudence(self, normative_reasoning, jurisprudence_analysis=None):
        return self._delegate.integrate_jurisprudence(normative_reasoning, jurisprudence_analysis)


class _StaticPayloadEngine:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def build(self, *args, **kwargs):
        _ = args, kwargs
        return self.payload

    def evaluate(self, *args, **kwargs):
        _ = args, kwargs
        return self.payload

    def analyze(self, *args, **kwargs):
        _ = args, kwargs
        return self.payload


def build_benchmark_pipeline(case: dict[str, Any]) -> AilexPipeline:
    reasoning_confidence = float(case["normative_reasoning"].get("confidence_score", 0.75))
    return AilexPipeline(
        retriever=_StaticRetriever(),
        context_builder=_StaticContextBuilder(),
        legal_reasoner=_StaticReasoner(
            {
                "short_answer": "Respuesta estructurada.",
                "applied_analysis": "Analisis estructurado para benchmark.",
                "confidence_score": reasoning_confidence,
                "confidence": "high" if reasoning_confidence >= 0.75 else "medium" if reasoning_confidence >= 0.5 else "low",
            }
        ),
        citation_validator=_StaticCitationValidator(),
        hallucination_guard=_StaticHallucinationGuard(),
        procedural_strategy=_StaticProceduralStrategy(
            {
                "next_steps": ["Ordenar soporte y definir presentacion."],
                "risks": list(case["case_structure"].get("risks", [])),
                "missing_information": list(case["case_structure"].get("missing_information", [])),
            }
        ),
        question_engine=_StaticQuestionEngine(),
        case_theory_engine=_StaticPayloadEngine(case["case_theory"]),
        case_evaluation_engine=_StaticPayloadEngine(case["case_evaluation"]),
        conflict_evidence_engine=_StaticPayloadEngine(case["conflict_evidence"]),
        evidence_reasoning_linker=_StaticPayloadEngine(case["evidence_reasoning_links"]),
        jurisprudence_engine=_StaticPayloadEngine(case["jurisprudence_analysis"]),
        action_classifier=_StaticClassifier(case["classification"]),
        case_structurer=_StaticCaseStructurer(
            {
                "action_slug": case["classification"].get("action_slug", ""),
                "facts": case["case_structure"].get("facts", []),
                "missing_information": case["case_structure"].get("missing_information", []),
                "risks": case["case_structure"].get("risks", []),
                "applicable_rules": [],
            }
        ),
        normative_reasoner=_StaticNormativeReasoner(case["normative_reasoning"]),
        argument_generator=_StaticPayloadEngine({}),
    )


def run_benchmark_case(case: dict[str, Any]) -> dict[str, Any]:
    pipeline = build_benchmark_pipeline(case)
    metadata = {}
    if case.get("procedural_events"):
        metadata["procedural_events"] = list(case.get("procedural_events") or [])
    result = pipeline.run(
        query=case["query"],
        jurisdiction=case["classification"].get("jurisdiction", "jujuy"),
        metadata=metadata or None,
    )
    return result.to_dict()


def caution_rank(value: str) -> int:
    return {"bajo": 1, "moderado": 2, "alto": 3}.get(str(value or "").strip().lower(), 0)


def strategy_alignment_ok(payload: dict[str, Any]) -> bool:
    posture = payload["legal_decision"]["strategic_posture"]
    narrative = str(payload["case_strategy"].get("strategic_narrative", "")).lower()
    focus = " ".join(payload["case_strategy"].get("procedural_focus", [])).lower()
    combined = f"{narrative} {focus}"
    if posture == "agresiva":
        return any(term in combined for term in ("avance", "pretension principal", "priorizar avance"))
    if posture == "cautelosa":
        return any(term in combined for term in ("saneamiento", "prudencia", "contencion", "prevenir rechazo"))
    return any(term in combined for term in ("control", "orden", "alcance", "priorizar"))


def strategy_support_text(payload: dict[str, Any]) -> str:
    strategy = payload["case_strategy"]
    return " ".join(
        [
            " ".join(strategy.get("procedural_focus", [])),
            " ".join(strategy.get("legal_decision_alignment", [])),
            " ".join(strategy.get("risk_analysis", [])),
        ]
    ).lower()


def has_cautious_exception(payload: dict[str, Any]) -> bool:
    decision = payload["legal_decision"]
    support_text = strategy_support_text(payload)
    return (
        decision["dominant_factor"] in {"riesgo", "prueba", "jurisprudencia"}
        and decision["caution_level"] in {"moderado", "alto"}
        and any(term in support_text for term in ("riesgo", "prueba", "cautela", "saneamiento", "adversa"))
    )


def expected_factors(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        text = value.strip()
        return {text} if text else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value).strip()
    return {text} if text else set()


def summarize_benchmark_case(case: dict[str, Any], payload: dict[str, Any]) -> str:
    decision = payload["legal_decision"]
    return (
        f"{case['id']}: esperado strength={case['expected']['case_strength_label']} posture={case['expected']['strategic_posture']} "
        f"real strength={decision['case_strength_label']} posture={decision['strategic_posture']} "
        f"confidence={decision['confidence_score']} factor={decision['dominant_factor']}"
    )


def benchmark_confidence_midpoint(case: dict[str, Any]) -> float:
    expected = case["expected"]
    return (float(expected["confidence_min"]) + float(expected["confidence_max"])) / 2.0


def benchmark_delta_confidence(case: dict[str, Any], payload: dict[str, Any]) -> float:
    decision = payload["legal_decision"]
    return float(decision.get("confidence_score", 0.0)) - benchmark_confidence_midpoint(case)


def evaluate_benchmark_case(case: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or run_benchmark_case(case)
    decision = payload["legal_decision"]
    expected = case["expected"]
    failures: list[str] = []

    if "legal_decision" not in payload:
        failures.append("no hay legal_decision")
    if not 0.0 <= float(decision.get("confidence_score", -1.0)) <= 1.0:
        failures.append("confidence_score fuera de rango [0,1]")
    if decision.get("case_strength_label") != expected["case_strength_label"]:
        failures.append(
            f"case_strength_label esperado={expected['case_strength_label']} real={decision.get('case_strength_label')}"
        )
    if decision.get("strategic_posture") != expected["strategic_posture"]:
        failures.append(
            f"strategic_posture esperado={expected['strategic_posture']} real={decision.get('strategic_posture')}"
        )
    if payload["case_strategy"].get("strategy_mode") != decision.get("strategic_posture"):
        failures.append(
            f"strategy_mode contradice strategic_posture: mode={payload['case_strategy'].get('strategy_mode')} posture={decision.get('strategic_posture')}"
        )

    acceptable_factors = expected_factors(expected.get("dominant_factor"))
    if acceptable_factors and decision.get("dominant_factor") not in acceptable_factors:
        failures.append(
            f"dominant_factor esperado={sorted(acceptable_factors)} real={decision.get('dominant_factor')}"
        )

    confidence_score = float(decision.get("confidence_score", 0.0))
    if confidence_score < expected["confidence_min"] or confidence_score > expected["confidence_max"]:
        failures.append(
            f"confidence_score fuera de rango esperado=[{expected['confidence_min']}, {expected['confidence_max']}] real={confidence_score:.3f}"
        )
    if expected.get("caution_min") and caution_rank(decision.get("caution_level")) < caution_rank(expected["caution_min"]):
        failures.append(
            f"caution_level por debajo de lo esperado: minimo={expected['caution_min']} real={decision.get('caution_level')}"
        )
    if expected.get("caution_max") and caution_rank(decision.get("caution_level")) > caution_rank(expected["caution_max"]):
        failures.append(
            f"caution_level por encima de lo esperado: maximo={expected['caution_max']} real={decision.get('caution_level')}"
        )
    if not strategy_alignment_ok(payload):
        failures.append("alineacion narrativa insuficiente entre estrategia y decision")

    return {
        "case": case,
        "payload": payload,
        "passed": not failures,
        "failures": failures,
        "delta_confidence": benchmark_delta_confidence(case, payload),
        "summary": summarize_benchmark_case(case, payload),
    }
