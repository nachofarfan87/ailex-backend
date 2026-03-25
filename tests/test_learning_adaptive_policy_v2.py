"""
AILEX - Tests de FASE 5: Observability-Guided Adaptive Policy.

Cubre:
1. Signal extractor — extraction correcta desde overview/drift/insights
2. Adaptive policy v2 — reglas heuristicas
3. Integracion en learning cycle
4. Persistencia de adaptive decision
5. Fallback sin datos
6. Compatibilidad con logica previa
7. Low sample priority
8. Confidence adjustment clamp
9. Multi-rule acumulacion limitada
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
import app.models.learning_action_log  # noqa: F401
import app.models.learning_impact_log  # noqa: F401
import app.models.learning_log  # noqa: F401
from app.models.learning_action_log import LearningActionLog
from app.models.learning_impact_log import LearningImpactLog
from app.services.impact_memory_service import (
    SIGNATURE_METADATA_VERSION,
    build_impact_signature,
    build_impact_signature_family,
)
from app.services.observability_signal_extractor import (
    SIGNAL_DRIFT_DETECTED,
    SIGNAL_HIGH_FAILURE_RATE,
    SIGNAL_HIGH_VARIANCE,
    SIGNAL_LOW_SAMPLE_SIZE,
    SIGNAL_POSITIVE_TREND,
    SIGNAL_RECENT_REGRESSION,
    SIGNAL_STRONG_POSITIVE_CONSISTENCY,
    SIGNAL_UNSTABLE_PATTERN,
    extract_signals,
)
from app.services.learning_adaptive_policy_v2 import (
    CONFIDENCE_ADJUSTMENT_MAX,
    CONFIDENCE_ADJUSTMENT_MIN,
    MAX_NON_TERMINAL_RULES,
    evaluate_adaptive_decision,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'adaptive_v2.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_local()


def _make_overview(**overrides) -> dict:
    base = {
        "total_observations": 20,
        "total_adaptive_decisions": 20,
        "unique_signatures": 3,
        "unique_signature_families": 2,
        "unique_event_types": 2,
        "reinforced_decisions": 12,
        "blocked_decisions": 3,
        "neutral_decisions": 5,
        "avg_impact_score": 0.2,
        "recency_weighted_avg_score": 0.15,
    }
    base.update(overrides)
    return base


def _make_drift(detected=False, level="none", signals=None) -> dict:
    return {
        "drift_detected": detected,
        "drift_level": level,
        "drift_signals": signals or [],
        "compared_windows": {},
    }


def _make_impact_decision(should_apply=True, reason="eligible", **overrides) -> dict:
    base = {
        "should_apply": should_apply,
        "reason": reason,
        "decision_source": "signature",
        "decision_level": "signature",
        "decision_mode": "allowed" if should_apply else "blocked",
        "impact_signature": "test_sig",
        "impact_signature_family": "test_fam",
        "signature_evidence": {},
        "signature_family_evidence": {},
        "event_type_evidence": {},
        "decision_path": [],
        "conflict_summary": {"has_conflict": False, "conflicts": []},
        "boost_applied": False,
        "observation_only": False,
    }
    base.update(overrides)
    return base


def _make_insights(types_severities: list[tuple[str, str]] | None = None) -> list[dict]:
    if not types_severities:
        return []
    return [
        {"type": t, "severity": s, "message": f"test {t}", "heuristic_key": f"{t}.test"}
        for t, s in types_severities
    ]


# ===========================================================================
# 1. Signal Extractor Tests
# ===========================================================================


class TestSignalExtractor:
    def test_empty_input_returns_no_signals(self):
        result = extract_signals()
        assert result["signals"] == [SIGNAL_LOW_SAMPLE_SIZE]
        assert result["has_data"] is False

    def test_low_sample_detected(self):
        result = extract_signals(overview=_make_overview(total_observations=2))
        assert SIGNAL_LOW_SAMPLE_SIZE in result["signals"]

    def test_high_failure_rate(self):
        result = extract_signals(overview=_make_overview(
            total_adaptive_decisions=10,
            blocked_decisions=5,
        ))
        assert SIGNAL_HIGH_FAILURE_RATE in result["signals"]
        assert result["signal_details"][SIGNAL_HIGH_FAILURE_RATE]["block_rate"] == 0.5

    def test_recent_regression(self):
        result = extract_signals(overview=_make_overview(
            recency_weighted_avg_score=-0.3,
        ))
        assert SIGNAL_RECENT_REGRESSION in result["signals"]

    def test_positive_trend(self):
        result = extract_signals(overview=_make_overview(
            recency_weighted_avg_score=0.4,
        ))
        assert SIGNAL_POSITIVE_TREND in result["signals"]

    def test_strong_positive_consistency(self):
        result = extract_signals(overview=_make_overview(
            total_observations=10,
            avg_impact_score=0.6,
            reinforced_decisions=8,
            blocked_decisions=1,
        ))
        assert SIGNAL_STRONG_POSITIVE_CONSISTENCY in result["signals"]

    def test_drift_detected(self):
        result = extract_signals(
            overview=_make_overview(),
            drift=_make_drift(detected=True, level="high"),
        )
        assert SIGNAL_DRIFT_DETECTED in result["signals"]
        assert result["signal_details"][SIGNAL_DRIFT_DETECTED]["drift_level"] == "high"

    def test_high_variance(self):
        result = extract_signals(overview=_make_overview(
            avg_impact_score=0.5,
            recency_weighted_avg_score=-0.1,
        ))
        assert SIGNAL_HIGH_VARIANCE in result["signals"]

    def test_unstable_pattern_from_insights(self):
        insights = _make_insights([
            ("drift", "high"),
            ("signature", "high"),
            ("family", "medium"),
        ])
        result = extract_signals(overview=_make_overview(), insights=insights)
        assert SIGNAL_UNSTABLE_PATTERN in result["signals"]

    def test_no_unstable_with_one_high(self):
        insights = _make_insights([("drift", "high"), ("family", "low")])
        result = extract_signals(overview=_make_overview(), insights=insights)
        assert SIGNAL_UNSTABLE_PATTERN not in result["signals"]

    def test_missing_fields_dont_crash(self):
        result = extract_signals(
            overview={"random_field": 123},
            drift={"unexpected": True},
            insights=[{"no_severity": True}],
        )
        assert isinstance(result["signals"], list)
        assert result["has_data"] is False


# ===========================================================================
# 2. Adaptive Policy V2 — Block rules
# ===========================================================================


class TestAdaptivePolicyBlock:
    def test_block_degraded_pattern(self):
        """high_failure_rate + recent_regression => block"""
        signals = extract_signals(overview=_make_overview(
            total_adaptive_decisions=10,
            blocked_decisions=5,
            recency_weighted_avg_score=-0.3,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is False
        assert decision["risk_level"] == "high"
        assert "block_degraded_pattern" in decision["applied_rules"]

    def test_block_regression_with_drift(self):
        """recent_regression + drift => block"""
        signals = extract_signals(
            overview=_make_overview(recency_weighted_avg_score=-0.3),
            drift=_make_drift(detected=True, level="high"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is False
        assert decision["risk_level"] == "high"
        assert "block_regression_with_drift" in decision["applied_rules"]

    def test_block_rules_are_terminal(self):
        """Block rule termina evaluacion, no se acumulan mas reglas."""
        signals = extract_signals(
            overview=_make_overview(
                total_adaptive_decisions=10,
                blocked_decisions=5,
                recency_weighted_avg_score=-0.3,
                avg_impact_score=0.5,
            ),
            drift=_make_drift(detected=True, level="high"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is False
        assert len(decision["applied_rules"]) == 1

    def test_block_confidence_is_clamped(self):
        """Block rules tambien tienen confidence clampado."""
        signals = extract_signals(
            overview=_make_overview(recency_weighted_avg_score=-0.3),
            drift=_make_drift(detected=True, level="high"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["confidence_adjustment"] >= CONFIDENCE_ADJUSTMENT_MIN
        assert decision["confidence_adjustment"] <= CONFIDENCE_ADJUSTMENT_MAX


# ===========================================================================
# 3. Adaptive Policy V2 — Cautious rules
# ===========================================================================


class TestAdaptivePolicyCautious:
    def test_cautious_drift_instability(self):
        """drift + unstable pattern => should_apply=True, risk=medium"""
        insights = _make_insights([("drift", "high"), ("signature", "high")])
        signals = extract_signals(
            overview=_make_overview(),
            drift=_make_drift(detected=True, level="medium"),
            insights=insights,
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert decision["risk_level"] == "medium"
        assert decision["confidence_adjustment"] < 0

    def test_cautious_drift_alone(self):
        """drift solo => should_apply=True, confianza reducida"""
        signals = extract_signals(
            overview=_make_overview(),
            drift=_make_drift(detected=True, level="low"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert decision["confidence_adjustment"] < 0
        assert "cautious_drift_alone" in decision["applied_rules"]

    def test_cautious_high_variance(self):
        """high variance => should_apply=True, confianza reducida"""
        signals = extract_signals(overview=_make_overview(
            avg_impact_score=0.5,
            recency_weighted_avg_score=-0.05,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert decision["confidence_adjustment"] < 0
        assert "cautious_high_variance" in decision["applied_rules"]

    def test_drift_plus_variance_accumulate(self):
        """drift + variance => ambas cautelas se acumulan (multi-rule)."""
        signals = extract_signals(
            overview=_make_overview(
                avg_impact_score=0.5,
                recency_weighted_avg_score=-0.05,
            ),
            drift=_make_drift(detected=True, level="low"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert decision["risk_level"] == "medium"
        assert "cautious_drift_alone" in decision["applied_rules"]
        assert "cautious_high_variance" in decision["applied_rules"]
        assert len(decision["applied_rules"]) == 2
        # Acumulado pero clampado
        assert decision["confidence_adjustment"] >= CONFIDENCE_ADJUSTMENT_MIN


# ===========================================================================
# 4. Adaptive Policy V2 — Boost rules
# ===========================================================================


class TestAdaptivePolicyBoost:
    def test_boost_positive_consistent(self):
        """positive_trend + strong_consistency + no rojas => boost"""
        signals = extract_signals(overview=_make_overview(
            total_observations=10,
            avg_impact_score=0.6,
            recency_weighted_avg_score=0.5,
            reinforced_decisions=8,
            blocked_decisions=1,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert decision["confidence_adjustment"] > 0
        assert decision["risk_level"] == "low"
        assert "boost_positive_consistent" in decision["applied_rules"]

    def test_boost_positive_only(self):
        """positive_trend sin consistency => boost menor"""
        signals = extract_signals(overview=_make_overview(
            total_observations=10,
            avg_impact_score=0.3,
            recency_weighted_avg_score=0.4,
            reinforced_decisions=5,
            blocked_decisions=4,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert decision["confidence_adjustment"] > 0
        assert "boost_positive_trend" in decision["applied_rules"]

    def test_no_boost_if_red_signal_present(self):
        """positive_trend + drift => no boost, se aplica cautela"""
        signals = extract_signals(
            overview=_make_overview(recency_weighted_avg_score=0.4),
            drift=_make_drift(detected=True, level="medium"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert "boost_positive_consistent" not in decision["applied_rules"]
        assert "boost_positive_trend" not in decision["applied_rules"]

    def test_boost_clamped_at_max(self):
        """Boost positivo no puede exceder CONFIDENCE_ADJUSTMENT_MAX."""
        signals = extract_signals(overview=_make_overview(
            total_observations=10,
            avg_impact_score=0.6,
            recency_weighted_avg_score=0.5,
            reinforced_decisions=8,
            blocked_decisions=1,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["confidence_adjustment"] <= CONFIDENCE_ADJUSTMENT_MAX


# ===========================================================================
# 5. Fallback sin datos
# ===========================================================================


class TestAdaptivePolicyFallback:
    def test_no_data_fallback(self):
        """Sin observability data => passthrough limpio"""
        signals = extract_signals()
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert decision["reasoning"] == "no_observability_data"
        assert decision["confidence_adjustment"] == 0.0

    def test_low_sample_no_aggressive_block(self):
        """low_sample_size => no bloquear"""
        signals = extract_signals(overview=_make_overview(
            total_observations=2,
            total_adaptive_decisions=2,
            blocked_decisions=0,
            recency_weighted_avg_score=0.0,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert "low_sample_passthrough" in decision["applied_rules"]

    def test_impact_already_blocked_passthrough(self):
        """Si impact policy ya bloqueo, adaptive pasa eso directo"""
        signals = extract_signals(overview=_make_overview())
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(
                should_apply=False,
                reason="blocked_by_negative_signature_impact",
            ),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is False
        assert "impact_policy_block_passthrough" in decision["applied_rules"]


# ===========================================================================
# 6. Senales contradictorias priorizan seguridad
# ===========================================================================


class TestContradictorySignals:
    def test_positive_trend_with_failure_rate(self):
        """positive + high failure => la regla de block prevalece"""
        signals = extract_signals(overview=_make_overview(
            total_adaptive_decisions=10,
            blocked_decisions=5,
            recency_weighted_avg_score=-0.3,
            avg_impact_score=0.1,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is False
        assert decision["risk_level"] == "high"


# ===========================================================================
# 7. Campos faltantes no crashean
# ===========================================================================


class TestDefensiveBehavior:
    def test_empty_impact_decision(self):
        decision = evaluate_adaptive_decision(
            impact_decision={},
            extracted_signals={"signals": [], "signal_details": {}, "has_data": False},
        )
        assert decision["should_apply"] is True

    def test_malformed_signals(self):
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals={"signals": ["unknown_signal"], "signal_details": {}, "has_data": True, "total_observations": 5},
        )
        assert decision["should_apply"] is True
        assert "no_rule_matched" in decision["applied_rules"]


# ===========================================================================
# 8. Adaptive decision structure
# ===========================================================================


class TestAdaptiveDecisionStructure:
    def test_all_fields_present(self):
        signals = extract_signals(overview=_make_overview())
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert "should_apply" in decision
        assert "confidence_adjustment" in decision
        assert "risk_level" in decision
        assert "reasoning" in decision
        assert "applied_rules" in decision
        assert "observability_signals" in decision
        assert isinstance(decision["applied_rules"], list)
        assert decision["risk_level"] in ("low", "medium", "high")

    def test_reasoning_is_nonempty(self):
        signals = extract_signals(overview=_make_overview())
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert len(decision["reasoning"]) > 0


# ===========================================================================
# 9. Low sample priority — guard clause
# ===========================================================================


class TestLowSamplePriority:
    def test_low_sample_prevents_block_from_negative_signals(self):
        """Con pocas obs + senales negativas, low_sample tiene prioridad."""
        # 2 obs, block_rate=100%, recency negativa => sin guard, esto blockea
        signals = extract_signals(overview=_make_overview(
            total_observations=2,
            total_adaptive_decisions=2,
            blocked_decisions=2,
            recency_weighted_avg_score=-0.5,
            avg_impact_score=-0.5,
        ))
        # Verificar que las senales negativas existen
        assert SIGNAL_LOW_SAMPLE_SIZE in signals["signals"]
        assert SIGNAL_HIGH_FAILURE_RATE in signals["signals"]

        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        # low_sample tiene prioridad: no bloquea
        assert decision["should_apply"] is True
        assert "low_sample_passthrough" in decision["applied_rules"]
        assert decision["confidence_adjustment"] == 0.0

    def test_low_sample_prevents_cautious_from_drift(self):
        """Con pocas obs + drift, low_sample evita penalizacion."""
        signals = extract_signals(
            overview=_make_overview(total_observations=1),
            drift=_make_drift(detected=True, level="high"),
        )
        assert SIGNAL_LOW_SAMPLE_SIZE in signals["signals"]
        assert SIGNAL_DRIFT_DETECTED in signals["signals"]

        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is True
        assert "low_sample_passthrough" in decision["applied_rules"]

    def test_low_sample_does_not_override_impact_block(self):
        """Impact block se mantiene incluso con low sample."""
        signals = extract_signals(overview=_make_overview(total_observations=1))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(
                should_apply=False,
                reason="blocked_by_negative_signature_impact",
            ),
            extracted_signals=signals,
        )
        assert decision["should_apply"] is False
        assert "impact_policy_block_passthrough" in decision["applied_rules"]


# ===========================================================================
# 10. Confidence adjustment clamp
# ===========================================================================


class TestConfidenceClamp:
    def test_clamp_constants_exist(self):
        assert CONFIDENCE_ADJUSTMENT_MIN == -0.30
        assert CONFIDENCE_ADJUSTMENT_MAX == 0.20

    def test_negative_clamp_on_accumulated_cautious(self):
        """Acumulacion de cautelas no puede bajar de CONFIDENCE_ADJUSTMENT_MIN."""
        # drift_instability (-0.18) + variance (-0.05) = -0.23 => clampado a -0.23 (dentro de rango)
        # Pero si forzamos un escenario extremo con signal injection:
        signals = {
            "signals": [
                SIGNAL_DRIFT_DETECTED, SIGNAL_UNSTABLE_PATTERN, SIGNAL_HIGH_VARIANCE,
            ],
            "signal_details": {
                SIGNAL_DRIFT_DETECTED: {"drift_level": "high", "drift_signals_count": 3},
                SIGNAL_UNSTABLE_PATTERN: {"high_severity_insight_count": 5, "insight_types": ["drift", "signature"]},
                SIGNAL_HIGH_VARIANCE: {"avg_score": 0.5, "recency_score": -0.3, "divergence": 0.8, "threshold": 0.35},
            },
            "has_data": True,
            "total_observations": 20,
        }
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["confidence_adjustment"] >= CONFIDENCE_ADJUSTMENT_MIN
        assert decision["confidence_adjustment"] <= CONFIDENCE_ADJUSTMENT_MAX

    def test_positive_clamp_on_boost(self):
        """Boost no puede exceder CONFIDENCE_ADJUSTMENT_MAX."""
        signals = extract_signals(overview=_make_overview(
            total_observations=10,
            avg_impact_score=0.6,
            recency_weighted_avg_score=0.5,
            reinforced_decisions=8,
            blocked_decisions=1,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["confidence_adjustment"] <= CONFIDENCE_ADJUSTMENT_MAX

    def test_block_rule_also_clamped(self):
        """Block rules aplican clamp tambien."""
        signals = extract_signals(
            overview=_make_overview(recency_weighted_avg_score=-0.3),
            drift=_make_drift(detected=True, level="high"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert decision["confidence_adjustment"] >= CONFIDENCE_ADJUSTMENT_MIN


# ===========================================================================
# 11. Multi-rule limitada
# ===========================================================================


class TestMultiRule:
    def test_max_non_terminal_rules_constant(self):
        assert MAX_NON_TERMINAL_RULES == 2

    def test_two_cautious_rules_accumulate(self):
        """drift_alone + variance => ambas aplican."""
        signals = extract_signals(
            overview=_make_overview(
                avg_impact_score=0.5,
                recency_weighted_avg_score=-0.05,
            ),
            drift=_make_drift(detected=True, level="low"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert len(decision["applied_rules"]) == 2
        assert "cautious_drift_alone" in decision["applied_rules"]
        assert "cautious_high_variance" in decision["applied_rules"]

    def test_multi_rule_capped_at_max(self):
        """No mas de MAX_NON_TERMINAL_RULES reglas no terminales."""
        # drift_instability (drift+unstable) + variance => 3 candidatas, solo 2 aplican
        insights = _make_insights([("drift", "high"), ("signature", "high")])
        signals = extract_signals(
            overview=_make_overview(
                avg_impact_score=0.5,
                recency_weighted_avg_score=-0.05,
            ),
            drift=_make_drift(detected=True, level="medium"),
            insights=insights,
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert len(decision["applied_rules"]) <= MAX_NON_TERMINAL_RULES

    def test_reasoning_reflects_multiple_rules(self):
        """Reasoning contiene ambas explicaciones separadas por ;"""
        signals = extract_signals(
            overview=_make_overview(
                avg_impact_score=0.5,
                recency_weighted_avg_score=-0.05,
            ),
            drift=_make_drift(detected=True, level="low"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert ";" in decision["reasoning"]
        assert "drift" in decision["reasoning"].lower()
        assert "varianza" in decision["reasoning"].lower() or "variance" in decision["reasoning"].lower()

    def test_risk_level_is_highest_of_accumulated(self):
        """Risk level toma el peor de las reglas acumuladas."""
        signals = extract_signals(
            overview=_make_overview(
                avg_impact_score=0.5,
                recency_weighted_avg_score=-0.05,
            ),
            drift=_make_drift(detected=True, level="low"),
        )
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        # drift_alone=medium, variance=medium => final=medium
        assert decision["risk_level"] == "medium"


# ===========================================================================
# 11b. Overlap fix — mutual exclusion between related rules
# ===========================================================================


class TestOverlapExclusion:
    def test_drift_unstable_excludes_drift_alone(self):
        """drift + unstable_pattern => cautious_drift_instability, NOT cautious_drift_alone."""
        insights = _make_insights([("drift", "high"), ("signature", "high")])
        signals = extract_signals(
            overview=_make_overview(),
            drift=_make_drift(detected=True, level="medium"),
            insights=insights,
        )
        assert SIGNAL_DRIFT_DETECTED in signals["signals"]
        assert SIGNAL_UNSTABLE_PATTERN in signals["signals"]

        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert "cautious_drift_instability" in decision["applied_rules"]
        assert "cautious_drift_alone" not in decision["applied_rules"]

    def test_positive_consistent_excludes_positive_only(self):
        """positive_trend + strong_consistency => boost_positive_consistent, NOT boost_positive_trend."""
        signals = extract_signals(overview=_make_overview(
            total_observations=10,
            avg_impact_score=0.6,
            recency_weighted_avg_score=0.5,
            reinforced_decisions=8,
            blocked_decisions=1,
        ))
        assert SIGNAL_POSITIVE_TREND in signals["signals"]
        assert SIGNAL_STRONG_POSITIVE_CONSISTENCY in signals["signals"]

        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert "boost_positive_consistent" in decision["applied_rules"]
        assert "boost_positive_trend" not in decision["applied_rules"]

    def test_drift_unstable_variance_takes_second_slot(self):
        """drift + unstable + variance => drift_instability + variance (drift_alone excluded)."""
        insights = _make_insights([("drift", "high"), ("signature", "high")])
        signals = extract_signals(
            overview=_make_overview(
                avg_impact_score=0.5,
                recency_weighted_avg_score=-0.05,
            ),
            drift=_make_drift(detected=True, level="medium"),
            insights=insights,
        )
        assert SIGNAL_DRIFT_DETECTED in signals["signals"]
        assert SIGNAL_UNSTABLE_PATTERN in signals["signals"]
        assert SIGNAL_HIGH_VARIANCE in signals["signals"]

        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        assert "cautious_drift_instability" in decision["applied_rules"]
        assert "cautious_high_variance" in decision["applied_rules"]
        assert "cautious_drift_alone" not in decision["applied_rules"]
        assert len(decision["applied_rules"]) == 2

    def test_positive_consistent_no_duplicate_boost(self):
        """positive + consistency no produce dos reglas de boost redundantes."""
        signals = extract_signals(overview=_make_overview(
            total_observations=10,
            avg_impact_score=0.6,
            recency_weighted_avg_score=0.5,
            reinforced_decisions=8,
            blocked_decisions=1,
        ))
        decision = evaluate_adaptive_decision(
            impact_decision=_make_impact_decision(),
            extracted_signals=signals,
        )
        boost_rules = [r for r in decision["applied_rules"] if r.startswith("boost_")]
        assert len(boost_rules) == 1
        assert boost_rules[0] == "boost_positive_consistent"


# ===========================================================================
# 12. Integration — learning cycle persists adaptive decision
# ===========================================================================


def _add_impact_entry(
    db: Session,
    *,
    recommendation: dict,
    status: str,
    created_at: datetime,
    applied: bool = True,
    reason: str = "historical",
    impact_score: float = 0.0,
    confidence_score: float | None = None,
) -> str:
    sig = build_impact_signature(recommendation)
    fam = build_impact_signature_family(recommendation)
    payload = {
        "impact_metadata_version": SIGNATURE_METADATA_VERSION,
        "impact_signature": sig,
        "impact_signature_family": fam,
        "impact_decision_level": "signature",
        "impact_decision_reason": reason,
        "impact_decision_source": "signature",
        "impact_score_reference": {},
    }
    action_log = LearningActionLog(
        event_type=recommendation["event_type"],
        recommendation_type=recommendation.get("title"),
        applied=applied,
        reason=reason,
        confidence_score=confidence_score if confidence_score is not None else recommendation.get("confidence_score"),
        priority=recommendation.get("priority"),
        evidence_json=json.dumps(recommendation.get("evidence", {})),
        changes_applied_json=json.dumps(payload),
        impact_status=status if applied else None,
        created_at=created_at,
    )
    db.add(action_log)
    db.flush()
    db.add(
        LearningImpactLog(
            learning_action_log_id=action_log.id,
            event_type=recommendation["event_type"],
            status=status,
            before_metrics_json="{}",
            after_metrics_json="{}",
            delta_metrics_json="{}",
            evaluation_window_hours=24,
            created_at=created_at,
            updated_at=created_at,
            impact_score=impact_score,
            impact_label=status,
        )
    )
    return action_log.id


class TestLearningCycleIntegration:
    def test_cycle_persists_adaptive_decision(self, tmp_path, monkeypatch):
        db = _build_session(tmp_path)

        from app.services import learning_runtime_config, learning_cycle_service

        learning_runtime_config.reset_runtime_config()

        recommendation = {
            "event_type": "domain_override",
            "title": "Prefer alimentos",
            "confidence_score": 0.9,
            "priority": 0.8,
            "evidence": {"sample_size": 10},
            "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
        }

        monkeypatch.setattr(
            learning_cycle_service,
            "get_learning_summary",
            lambda _db, last_hours=24: {"total_queries": 10},
        )
        monkeypatch.setattr(
            learning_cycle_service,
            "get_recent_learning_logs",
            lambda _db, limit=200: [],
        )
        monkeypatch.setattr(
            learning_cycle_service.AdaptiveLearningEngine,
            "analyze",
            lambda self, summary, recent_logs: [recommendation],
        )

        result = learning_cycle_service.run_learning_cycle(db)
        assert result["total_recommendations"] == 1

        # Verify adaptive_decision is in the result
        rec_result = result["results"][0]
        assert "adaptive_decision" in rec_result
        ad = rec_result["adaptive_decision"]
        assert "should_apply" in ad
        assert "confidence_adjustment" in ad
        assert "risk_level" in ad
        assert "reasoning" in ad
        assert "applied_rules" in ad

        # Verify it's persisted in the action log
        action_log = db.query(LearningActionLog).first()
        payload = json.loads(action_log.changes_applied_json)
        assert "adaptive_decision" in payload
        assert "observability_snapshot" in payload
        assert "insight_snapshot" in payload
        assert isinstance(payload["adaptive_decision"]["applied_rules"], list)

    def test_cycle_compatible_with_previous_behavior(self, tmp_path, monkeypatch):
        """Low confidence recommendation still gets skipped by base policy"""
        db = _build_session(tmp_path)

        from app.services import learning_runtime_config, learning_cycle_service

        learning_runtime_config.reset_runtime_config()

        recommendation = {
            "event_type": "domain_override",
            "title": "Prefer alimentos",
            "confidence_score": 0.5,
            "priority": 0.8,
            "evidence": {"sample_size": 12},
            "proposed_changes": {"prefer_hybrid_domains_add": ["alimentos"]},
        }

        monkeypatch.setattr(
            learning_cycle_service,
            "get_learning_summary",
            lambda _db, last_hours=24: {"total_queries": 10},
        )
        monkeypatch.setattr(
            learning_cycle_service,
            "get_recent_learning_logs",
            lambda _db, limit=200: [],
        )
        monkeypatch.setattr(
            learning_cycle_service.AdaptiveLearningEngine,
            "analyze",
            lambda self, summary, recent_logs: [recommendation],
        )

        result = learning_cycle_service.run_learning_cycle(db)
        assert result["applied_count"] == 0
        assert result["skipped_count"] == 1
        assert result["results"][0]["reason"] == "below_threshold"
