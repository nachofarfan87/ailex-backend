from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def _normalize_dataclass(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _normalize_dataclass(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_dataclass(item) for item in value]
    return value


@dataclass
class NormalizedOrchestratorInput:
    request_id: str
    query: str
    jurisdiction: str | None = None
    forum: str | None = None
    top_k: int = 5
    document_mode: str | None = None
    document_kind: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratorClassification:
    action_slug: str = ""
    action_label: str = ""
    case_domain: str = ""
    jurisdiction: str | None = None
    forum: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalBundle:
    source_mode: str = "unknown"
    sources_used: list[str] = field(default_factory=list)
    normative_references: list[dict[str, Any]] = field(default_factory=list)
    jurisprudence_references: list[dict[str, Any]] = field(default_factory=list)
    documents_considered: int = 0
    top_retrieval_scores: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyBundle:
    strategy_mode: str = ""
    dominant_factor: str = ""
    blocking_factor: str = ""
    execution_readiness: str = ""
    confidence_score: float | None = None
    confidence_label: str = "low"
    fallback_used: bool = False
    fallback_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratorDecision:
    retrieval_mode: str = "offline"
    strategy_mode: str = "conservative"
    pipeline_mode: str = "full"
    use_jurisprudence: bool = True
    use_argument_generation: bool = True
    decision_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinalOutput:
    request_id: str
    response_text: str
    pipeline_version: str = ""
    case_domain: str = ""
    action_slug: str = ""
    source_mode: str = "unknown"
    documents_considered: int = 0
    strategy_mode: str = ""
    dominant_factor: str = ""
    blocking_factor: str = ""
    execution_readiness: str = ""
    confidence_score: float | None = None
    confidence_label: str = "low"
    fallback_used: bool = False
    fallback_reason: str = ""
    sanitized_output: bool = False
    warnings: list[str] = field(default_factory=list)
    api_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratorTimings:
    normalization_ms: int = 0
    pipeline_ms: int = 0
    classification_ms: int = 0
    retrieval_ms: int = 0
    strategy_ms: int = 0
    response_generation_ms: int = 0
    postprocess_ms: int = 0
    final_assembly_ms: int = 0
    total_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestratorResult:
    pipeline_version: str
    normalized_input: NormalizedOrchestratorInput
    classification: OrchestratorClassification
    retrieval: RetrievalBundle
    strategy: StrategyBundle
    final_output: FinalOutput
    timings: OrchestratorTimings
    pipeline_payload: dict[str, Any] = field(default_factory=dict)
    decision: OrchestratorDecision = field(default_factory=OrchestratorDecision)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "normalized_input": _normalize_dataclass(self.normalized_input),
            "decision": _normalize_dataclass(self.decision),
            "classification": _normalize_dataclass(self.classification),
            "retrieval": _normalize_dataclass(self.retrieval),
            "strategy": _normalize_dataclass(self.strategy),
            "final_output": _normalize_dataclass(self.final_output),
            "timings": _normalize_dataclass(self.timings),
            "pipeline_payload": _normalize_dataclass(self.pipeline_payload),
            "metadata": _normalize_dataclass(self.metadata),
        }
