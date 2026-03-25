from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StrategyWeightConfig:
    aggressive: float = 1.0
    cautious: float = 1.0
    conservative: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "StrategyWeightConfig":
        data = dict(payload or {})
        return cls(
            aggressive=float(data.get("aggressive", 1.0) or 1.0),
            cautious=float(data.get("cautious", 1.0) or 1.0),
            conservative=float(data.get("conservative", 1.0) or 1.0),
        )


@dataclass
class ThresholdConfig:
    ambiguity_threshold: float = 0.12
    manual_review_threshold: float = 0.5
    low_confidence_threshold: float = 0.5
    low_decision_confidence_threshold: float = 0.5

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ThresholdConfig":
        data = dict(payload or {})
        return cls(
            ambiguity_threshold=float(data.get("ambiguity_threshold", 0.12) or 0.12),
            manual_review_threshold=float(data.get("manual_review_threshold", 0.5) or 0.5),
            low_confidence_threshold=float(data.get("low_confidence_threshold", 0.5) or 0.5),
            low_decision_confidence_threshold=float(data.get("low_decision_confidence_threshold", 0.5) or 0.5),
        )


@dataclass
class DomainOverrideConfig:
    prefer_hybrid_domains: list[str] = field(default_factory=list)
    force_full_pipeline_domains: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "prefer_hybrid_domains": list(self.prefer_hybrid_domains),
            "force_full_pipeline_domains": list(self.force_full_pipeline_domains),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "DomainOverrideConfig":
        data = dict(payload or {})
        return cls(
            prefer_hybrid_domains=[str(item).strip() for item in data.get("prefer_hybrid_domains", []) if str(item).strip()],
            force_full_pipeline_domains=[str(item).strip() for item in data.get("force_full_pipeline_domains", []) if str(item).strip()],
        )


@dataclass
class OrchestratorAdaptiveConfig:
    ambiguity_threshold: float = 0.12
    manual_review_threshold: float = 0.5
    low_confidence_threshold: float = 0.5
    low_decision_confidence_threshold: float = 0.5
    prefer_hybrid_domains: list[str] = field(default_factory=list)
    force_full_pipeline_domains: list[str] = field(default_factory=list)
    strategy_weights: dict[str, float] = field(default_factory=lambda: StrategyWeightConfig().to_dict())
    version: str = "v1"
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_threshold": self.ambiguity_threshold,
            "manual_review_threshold": self.manual_review_threshold,
            "low_confidence_threshold": self.low_confidence_threshold,
            "low_decision_confidence_threshold": self.low_decision_confidence_threshold,
            "prefer_hybrid_domains": list(self.prefer_hybrid_domains),
            "force_full_pipeline_domains": list(self.force_full_pipeline_domains),
            "strategy_weights": dict(self.strategy_weights),
            "version": self.version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OrchestratorAdaptiveConfig":
        data = dict(payload or {})
        thresholds = ThresholdConfig.from_dict(data)
        overrides = DomainOverrideConfig.from_dict(data)
        weights = StrategyWeightConfig.from_dict(data.get("strategy_weights"))
        return cls(
            ambiguity_threshold=thresholds.ambiguity_threshold,
            manual_review_threshold=thresholds.manual_review_threshold,
            low_confidence_threshold=thresholds.low_confidence_threshold,
            low_decision_confidence_threshold=thresholds.low_decision_confidence_threshold,
            prefer_hybrid_domains=overrides.prefer_hybrid_domains,
            force_full_pipeline_domains=overrides.force_full_pipeline_domains,
            strategy_weights=weights.to_dict(),
            version=str(data.get("version") or "v1"),
            updated_at=data.get("updated_at"),
        )

    @classmethod
    def default_config(cls) -> "OrchestratorAdaptiveConfig":
        return cls()
