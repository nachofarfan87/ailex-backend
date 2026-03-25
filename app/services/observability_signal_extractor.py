"""
AILEX - Extractor de senales heuristicas desde observabilidad e insights.

Convierte un snapshot de observabilidad + lista de insights en senales
simples y defensivas que la adaptive policy v2 puede consumir.
No accede a DB — recibe datos ya consolidados.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Senales posibles
# ---------------------------------------------------------------------------

SIGNAL_HIGH_FAILURE_RATE = "high_failure_rate"
SIGNAL_RECENT_REGRESSION = "recent_regression"
SIGNAL_POSITIVE_TREND = "positive_trend"
SIGNAL_UNSTABLE_PATTERN = "unstable_pattern"
SIGNAL_DRIFT_DETECTED = "drift_detected"
SIGNAL_LOW_SAMPLE_SIZE = "low_sample_size"
SIGNAL_STRONG_POSITIVE_CONSISTENCY = "strong_positive_consistency"
SIGNAL_HIGH_VARIANCE = "high_variance"

ALL_SIGNALS = frozenset({
    SIGNAL_HIGH_FAILURE_RATE,
    SIGNAL_RECENT_REGRESSION,
    SIGNAL_POSITIVE_TREND,
    SIGNAL_UNSTABLE_PATTERN,
    SIGNAL_DRIFT_DETECTED,
    SIGNAL_LOW_SAMPLE_SIZE,
    SIGNAL_STRONG_POSITIVE_CONSISTENCY,
    SIGNAL_HIGH_VARIANCE,
})

# ---------------------------------------------------------------------------
# Umbrales de extraccion
# ---------------------------------------------------------------------------

FAILURE_RATE_THRESHOLD = 0.4
REGRESSION_SCORE_THRESHOLD = -0.25
POSITIVE_SCORE_THRESHOLD = 0.3
CONSISTENCY_SCORE_THRESHOLD = 0.5
CONSISTENCY_MIN_OBS = 5
LOW_SAMPLE_THRESHOLD = 3
VARIANCE_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Extractor principal
# ---------------------------------------------------------------------------

def extract_signals(
    *,
    overview: dict[str, Any] | None = None,
    drift: dict[str, Any] | None = None,
    insights: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extrae senales heuristicas a partir de datos de observabilidad.

    Retorna:
        {
            "signals": list[str],        # senales activas
            "signal_details": dict,       # detalle por senal
            "total_observations": int,
            "has_data": bool,
        }
    """
    overview = overview or {}
    drift = drift or {}
    insights = insights or []

    signals: list[str] = []
    signal_details: dict[str, Any] = {}

    total_obs = _safe_int(overview.get("total_observations"))
    total_decisions = _safe_int(overview.get("total_adaptive_decisions"))
    blocked = _safe_int(overview.get("blocked_decisions"))
    avg_score = _safe_float(overview.get("avg_impact_score"))
    recency_score = _safe_float(overview.get("recency_weighted_avg_score"))

    # 1. Low sample size
    if total_obs < LOW_SAMPLE_THRESHOLD:
        signals.append(SIGNAL_LOW_SAMPLE_SIZE)
        signal_details[SIGNAL_LOW_SAMPLE_SIZE] = {
            "total_observations": total_obs,
            "threshold": LOW_SAMPLE_THRESHOLD,
        }

    # 2. High failure rate
    if total_decisions > 0:
        block_rate = blocked / total_decisions
        if block_rate >= FAILURE_RATE_THRESHOLD:
            signals.append(SIGNAL_HIGH_FAILURE_RATE)
            signal_details[SIGNAL_HIGH_FAILURE_RATE] = {
                "block_rate": round(block_rate, 4),
                "blocked": blocked,
                "total_decisions": total_decisions,
                "threshold": FAILURE_RATE_THRESHOLD,
            }

    # 3. Recent regression
    if recency_score <= REGRESSION_SCORE_THRESHOLD and total_obs >= LOW_SAMPLE_THRESHOLD:
        signals.append(SIGNAL_RECENT_REGRESSION)
        signal_details[SIGNAL_RECENT_REGRESSION] = {
            "recency_weighted_avg_score": recency_score,
            "threshold": REGRESSION_SCORE_THRESHOLD,
        }

    # 4. Positive trend
    if recency_score >= POSITIVE_SCORE_THRESHOLD and total_obs >= LOW_SAMPLE_THRESHOLD:
        signals.append(SIGNAL_POSITIVE_TREND)
        signal_details[SIGNAL_POSITIVE_TREND] = {
            "recency_weighted_avg_score": recency_score,
            "threshold": POSITIVE_SCORE_THRESHOLD,
        }

    # 5. Strong positive consistency
    reinforced = _safe_int(overview.get("reinforced_decisions"))
    if (
        total_obs >= CONSISTENCY_MIN_OBS
        and avg_score >= CONSISTENCY_SCORE_THRESHOLD
        and reinforced > blocked
    ):
        signals.append(SIGNAL_STRONG_POSITIVE_CONSISTENCY)
        signal_details[SIGNAL_STRONG_POSITIVE_CONSISTENCY] = {
            "avg_score": avg_score,
            "reinforced": reinforced,
            "blocked": blocked,
            "total_observations": total_obs,
        }

    # 6. Drift detected
    if drift.get("drift_detected"):
        signals.append(SIGNAL_DRIFT_DETECTED)
        signal_details[SIGNAL_DRIFT_DETECTED] = {
            "drift_level": drift.get("drift_level", "unknown"),
            "drift_signals_count": len(drift.get("drift_signals", [])),
        }

    # 7. High variance (divergencia entre avg y recency scores)
    if total_obs >= LOW_SAMPLE_THRESHOLD:
        score_divergence = abs(avg_score - recency_score)
        if score_divergence >= VARIANCE_THRESHOLD:
            signals.append(SIGNAL_HIGH_VARIANCE)
            signal_details[SIGNAL_HIGH_VARIANCE] = {
                "avg_score": avg_score,
                "recency_score": recency_score,
                "divergence": round(score_divergence, 4),
                "threshold": VARIANCE_THRESHOLD,
            }

    # 8. Unstable pattern (from insight severity)
    _extract_instability_from_insights(insights, signals, signal_details)

    return {
        "signals": signals,
        "signal_details": signal_details,
        "total_observations": total_obs,
        "has_data": total_obs > 0 or bool(drift.get("drift_detected")),
    }


def _extract_instability_from_insights(
    insights: list[dict[str, Any]],
    signals: list[str],
    signal_details: dict[str, Any],
) -> None:
    """Detecta inestabilidad a partir de insights de alta severidad."""
    high_severity_count = 0
    high_types: list[str] = []
    for insight in insights:
        if insight.get("severity") == "high":
            high_severity_count += 1
            high_types.append(str(insight.get("type", "")))

    if high_severity_count >= 2 and SIGNAL_UNSTABLE_PATTERN not in signals:
        signals.append(SIGNAL_UNSTABLE_PATTERN)
        signal_details[SIGNAL_UNSTABLE_PATTERN] = {
            "high_severity_insight_count": high_severity_count,
            "insight_types": high_types[:5],
        }
