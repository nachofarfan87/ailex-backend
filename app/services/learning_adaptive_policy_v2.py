"""
AILEX - Adaptive Policy V2: Observability-Guided Decision Layer.

Combina:
- Impact decision (de learning_adaptation_policy)
- Observability signals (de observability_signal_extractor)

Para producir una AdaptiveDecision final deterministica y explicable.

No accede a DB — recibe datos ya resueltos.
No duplica logica de impact memory ni observability service.
"""

from __future__ import annotations

from typing import Any

from app.services.observability_signal_extractor import (
    SIGNAL_DRIFT_DETECTED,
    SIGNAL_HIGH_FAILURE_RATE,
    SIGNAL_HIGH_VARIANCE,
    SIGNAL_LOW_SAMPLE_SIZE,
    SIGNAL_POSITIVE_TREND,
    SIGNAL_RECENT_REGRESSION,
    SIGNAL_STRONG_POSITIVE_CONSISTENCY,
    SIGNAL_UNSTABLE_PATTERN,
)


# ---------------------------------------------------------------------------
# Ajustes de confianza
# ---------------------------------------------------------------------------

CONFIDENCE_PENALTY_DRIFT = -0.10
CONFIDENCE_PENALTY_INSTABILITY = -0.08
CONFIDENCE_PENALTY_VARIANCE = -0.05
CONFIDENCE_PENALTY_REGRESSION = -0.12
CONFIDENCE_BOOST_POSITIVE = 0.08
CONFIDENCE_BOOST_CONSISTENCY = 0.05

# Limites duros de confidence_adjustment
CONFIDENCE_ADJUSTMENT_MIN = -0.30
CONFIDENCE_ADJUSTMENT_MAX = 0.20

# Maximo de reglas no terminales que se pueden acumular
MAX_NON_TERMINAL_RULES = 2


# ---------------------------------------------------------------------------
# Tipos de resultado
# ---------------------------------------------------------------------------

def _empty_decision() -> dict[str, Any]:
    return {
        "should_apply": True,
        "confidence_adjustment": 0.0,
        "risk_level": "low",
        "reasoning": "no_observability_data",
        "applied_rules": [],
        "observability_signals": {},
    }


# ---------------------------------------------------------------------------
# Reglas heuristicas — BLOCK (terminales)
# ---------------------------------------------------------------------------

def _rule_block_degraded(signals: list[str], signal_details: dict) -> dict[str, Any] | None:
    """Block si hay failure rate alta + regression reciente."""
    if SIGNAL_HIGH_FAILURE_RATE in signals and SIGNAL_RECENT_REGRESSION in signals:
        return {
            "should_apply": False,
            "risk_level": "high",
            "confidence_adjustment": CONFIDENCE_PENALTY_REGRESSION,
            "rule": "block_degraded_pattern",
            "reasoning": (
                "Bloqueado: tasa de fallo alta combinada con regresion reciente. "
                f"block_rate={_detail(signal_details, SIGNAL_HIGH_FAILURE_RATE, 'block_rate')}, "
                f"recency_score={_detail(signal_details, SIGNAL_RECENT_REGRESSION, 'recency_weighted_avg_score')}"
            ),
        }
    return None


def _rule_block_regression_with_drift(signals: list[str], signal_details: dict) -> dict[str, Any] | None:
    """Block si hay regression + drift detectado."""
    if SIGNAL_RECENT_REGRESSION in signals and SIGNAL_DRIFT_DETECTED in signals:
        return {
            "should_apply": False,
            "risk_level": "high",
            "confidence_adjustment": CONFIDENCE_PENALTY_REGRESSION + CONFIDENCE_PENALTY_DRIFT,
            "rule": "block_regression_with_drift",
            "reasoning": (
                "Bloqueado: regresion reciente con drift activo. "
                f"drift_level={_detail(signal_details, SIGNAL_DRIFT_DETECTED, 'drift_level')}"
            ),
        }
    return None


# ---------------------------------------------------------------------------
# Reglas heuristicas — CAUTIOUS (no terminales, acumulables)
# ---------------------------------------------------------------------------

def _rule_cautious_drift_instability(signals: list[str], signal_details: dict) -> dict[str, Any] | None:
    """Reduce confianza si hay drift + inestabilidad."""
    if SIGNAL_DRIFT_DETECTED in signals and SIGNAL_UNSTABLE_PATTERN in signals:
        return {
            "should_apply": True,
            "risk_level": "medium",
            "confidence_adjustment": CONFIDENCE_PENALTY_DRIFT + CONFIDENCE_PENALTY_INSTABILITY,
            "rule": "cautious_drift_instability",
            "reasoning": (
                "Cautela: drift detectado con patron inestable. "
                f"drift_level={_detail(signal_details, SIGNAL_DRIFT_DETECTED, 'drift_level')}, "
                f"high_severity_insights={_detail(signal_details, SIGNAL_UNSTABLE_PATTERN, 'high_severity_insight_count')}"
            ),
        }
    return None


def _rule_cautious_drift_alone(signals: list[str], signal_details: dict) -> dict[str, Any] | None:
    """Reduce confianza si hay drift sin inestabilidad asociada."""
    if SIGNAL_DRIFT_DETECTED in signals and SIGNAL_UNSTABLE_PATTERN not in signals:
        return {
            "should_apply": True,
            "risk_level": "medium",
            "confidence_adjustment": CONFIDENCE_PENALTY_DRIFT,
            "rule": "cautious_drift_alone",
            "reasoning": (
                f"Cautela: drift detectado (nivel={_detail(signal_details, SIGNAL_DRIFT_DETECTED, 'drift_level')})"
            ),
        }
    return None


def _rule_cautious_variance(signals: list[str], signal_details: dict) -> dict[str, Any] | None:
    """Reduce confianza si hay varianza alta."""
    if SIGNAL_HIGH_VARIANCE in signals:
        return {
            "should_apply": True,
            "risk_level": "medium",
            "confidence_adjustment": CONFIDENCE_PENALTY_VARIANCE,
            "rule": "cautious_high_variance",
            "reasoning": (
                f"Cautela: varianza alta entre scores "
                f"(divergence={_detail(signal_details, SIGNAL_HIGH_VARIANCE, 'divergence')})"
            ),
        }
    return None


# ---------------------------------------------------------------------------
# Reglas heuristicas — BOOST (no terminales, acumulables)
# ---------------------------------------------------------------------------

def _rule_boost_positive(signals: list[str], signal_details: dict) -> dict[str, Any] | None:
    """Boost si hay tendencia positiva + consistencia y no hay senales rojas."""
    red_signals = {SIGNAL_HIGH_FAILURE_RATE, SIGNAL_RECENT_REGRESSION, SIGNAL_DRIFT_DETECTED, SIGNAL_UNSTABLE_PATTERN}
    has_red = bool(red_signals.intersection(signals))

    if not has_red and SIGNAL_POSITIVE_TREND in signals and SIGNAL_STRONG_POSITIVE_CONSISTENCY in signals:
        return {
            "should_apply": True,
            "risk_level": "low",
            "confidence_adjustment": CONFIDENCE_BOOST_POSITIVE + CONFIDENCE_BOOST_CONSISTENCY,
            "rule": "boost_positive_consistent",
            "reasoning": (
                "Reforzado: tendencia positiva sostenida con consistencia fuerte. "
                f"recency_score={_detail(signal_details, SIGNAL_POSITIVE_TREND, 'recency_weighted_avg_score')}"
            ),
        }
    return None


def _rule_boost_positive_only(signals: list[str], signal_details: dict) -> dict[str, Any] | None:
    """Boost menor si hay tendencia positiva sin consistencia fuerte ni rojas."""
    red_signals = {SIGNAL_HIGH_FAILURE_RATE, SIGNAL_RECENT_REGRESSION, SIGNAL_DRIFT_DETECTED, SIGNAL_UNSTABLE_PATTERN}
    has_red = bool(red_signals.intersection(signals))

    if not has_red and SIGNAL_POSITIVE_TREND in signals and SIGNAL_STRONG_POSITIVE_CONSISTENCY not in signals:
        return {
            "should_apply": True,
            "risk_level": "low",
            "confidence_adjustment": CONFIDENCE_BOOST_POSITIVE,
            "rule": "boost_positive_trend",
            "reasoning": (
                "Reforzado: tendencia positiva reciente. "
                f"recency_score={_detail(signal_details, SIGNAL_POSITIVE_TREND, 'recency_weighted_avg_score')}"
            ),
        }
    return None


# ---------------------------------------------------------------------------
# Cadenas de reglas separadas por tipo
# ---------------------------------------------------------------------------

_BLOCK_RULES = [
    _rule_block_degraded,
    _rule_block_regression_with_drift,
]

_NON_TERMINAL_RULES = [
    _rule_cautious_drift_instability,
    _rule_cautious_drift_alone,
    _rule_cautious_variance,
    _rule_boost_positive,
    _rule_boost_positive_only,
]


# ---------------------------------------------------------------------------
# Evaluador principal
# ---------------------------------------------------------------------------

def evaluate_adaptive_decision(
    *,
    impact_decision: dict[str, Any],
    extracted_signals: dict[str, Any],
) -> dict[str, Any]:
    """Evalua la decision adaptativa final guiada por observabilidad.

    Args:
        impact_decision: resultado de evaluate_impact_adaptation()
        extracted_signals: resultado de extract_signals()

    Returns:
        AdaptiveDecision dict con: should_apply, confidence_adjustment,
        risk_level, reasoning, applied_rules, observability_signals
    """
    signals = extracted_signals.get("signals", [])
    signal_details = extracted_signals.get("signal_details", {})
    has_data = extracted_signals.get("has_data", False)

    # Si no hay datos de observabilidad, fallback limpio
    if not has_data:
        decision = _empty_decision()
        decision["observability_signals"] = extracted_signals
        return decision

    # Si impact ya bloqueo, no necesitamos evaluar observability
    if not impact_decision.get("should_apply", True):
        return {
            "should_apply": False,
            "confidence_adjustment": 0.0,
            "risk_level": "high",
            "reasoning": f"blocked_by_impact_policy: {impact_decision.get('reason', '')}",
            "applied_rules": ["impact_policy_block_passthrough"],
            "observability_signals": extracted_signals,
        }

    # --- Guard clause: low sample size tiene prioridad ---
    # Con poca evidencia, no sobrerreaccionar a senales observacionales.
    if SIGNAL_LOW_SAMPLE_SIZE in signals:
        return {
            "should_apply": True,
            "confidence_adjustment": 0.0,
            "risk_level": "low",
            "reasoning": (
                f"Sin evidencia suficiente para ajustar "
                f"(obs={_detail(signal_details, SIGNAL_LOW_SAMPLE_SIZE, 'total_observations')}). "
                "Fallback prudente: se mantiene decision previa."
            ),
            "applied_rules": ["low_sample_passthrough"],
            "observability_signals": extracted_signals,
        }

    # --- Block rules: terminales ---
    block_applied: list[str] = []
    for rule_fn in _BLOCK_RULES:
        result = rule_fn(signals, signal_details)
        if result is not None:
            block_applied.append(result["rule"])
            return {
                "should_apply": False,
                "confidence_adjustment": _clamp(result["confidence_adjustment"]),
                "risk_level": result["risk_level"],
                "reasoning": result["reasoning"],
                "applied_rules": block_applied,
                "observability_signals": extracted_signals,
            }

    # --- Non-terminal rules: acumulables hasta MAX_NON_TERMINAL_RULES ---
    applied_rules: list[str] = []
    total_confidence_adj = 0.0
    final_risk_level = "low"
    reasoning_parts: list[str] = []

    for rule_fn in _NON_TERMINAL_RULES:
        if len(applied_rules) >= MAX_NON_TERMINAL_RULES:
            break
        result = rule_fn(signals, signal_details)
        if result is None:
            continue

        applied_rules.append(result["rule"])
        reasoning_parts.append(result["reasoning"])
        total_confidence_adj += result["confidence_adjustment"]
        if _risk_rank(result["risk_level"]) > _risk_rank(final_risk_level):
            final_risk_level = result["risk_level"]

    if not applied_rules:
        applied_rules.append("no_rule_matched")
        reasoning_parts.append("Sin senales relevantes; se mantiene decision previa.")

    return {
        "should_apply": True,
        "confidence_adjustment": _clamp(total_confidence_adj),
        "risk_level": final_risk_level,
        "reasoning": "; ".join(reasoning_parts),
        "applied_rules": applied_rules,
        "observability_signals": extracted_signals,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float) -> float:
    """Clampea confidence_adjustment dentro de limites seguros."""
    return round(max(CONFIDENCE_ADJUSTMENT_MIN, min(CONFIDENCE_ADJUSTMENT_MAX, value)), 4)


def _risk_rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(level, 0)


def _detail(signal_details: dict, signal: str, key: str) -> Any:
    return signal_details.get(signal, {}).get(key, "?")
