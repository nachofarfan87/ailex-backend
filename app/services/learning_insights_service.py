"""
AILEX - Servicio de insights interpretativos sobre observabilidad.

Capa heuristica read-only que genera mensajes humanos a partir de los
datos ya consolidados por learning_observability_service.
No introduce ML ni logica de decision — solo interpreta metricas existentes.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import learning_observability_service
from app.services.learning_observability_service import (
    DRIFT_BLOCK_RATE_THRESHOLD,
    DRIFT_NEGATIVE_APPEARANCE_MIN,
    DRIFT_SCORE_DELTA_THRESHOLD,
)
from app.services.utc import utc_now


# ---------------------------------------------------------------------------
# Umbrales heuristicos
# ---------------------------------------------------------------------------

SIGNATURE_CRITICAL_SCORE = -0.5
SIGNATURE_HIGH_OBS_THRESHOLD = 5
FAMILY_SUSTAINED_REGRESSION_MIN_OBS = 3
FAMILY_SUSTAINED_REGRESSION_SCORE = -0.3
FAMILY_SUSTAINED_IMPROVEMENT_SCORE = 0.4
DECISION_BLOCK_RATE_HIGH = 0.4
DECISION_CONFIDENCE_LOW = 0.5
EXPLANATION_VERSION = "v1"
EXPLANATION_SOURCE = "learning_insights_service"


# ---------------------------------------------------------------------------
# Generador principal
# ---------------------------------------------------------------------------


def generate_insights(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict[str, Any]]:
    """Genera una lista de insights interpretativos a partir de datos existentes."""
    generated_at = date_to or utc_now()
    insights: list[dict[str, Any]] = []

    drift = learning_observability_service.detect_drift(
        db, reference_time=date_to,
    )
    insights.extend(_drift_insights(drift, generated_at=generated_at))

    signatures = learning_observability_service.get_metrics_by_signature(
        db, date_from=date_from, date_to=date_to, limit=500,
    )
    insights.extend(_signature_insights(signatures, generated_at=generated_at))

    families = learning_observability_service.get_metrics_by_family(
        db, date_from=date_from, date_to=date_to, limit=500,
    )
    insights.extend(_family_insights(families, generated_at=generated_at))

    decisions = learning_observability_service.get_recent_decisions(
        db, date_from=date_from, date_to=date_to, limit=200,
    )
    overview = learning_observability_service.get_overview(
        db, date_from=date_from, date_to=date_to,
    )
    insights.extend(_decision_insights(decisions, overview, generated_at=generated_at))

    insights.sort(key=_severity_rank)

    return insights


# ---------------------------------------------------------------------------
# A) Insights de drift
# ---------------------------------------------------------------------------


def _drift_insights(
    drift: dict[str, Any],
    *,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []

    if not drift.get("drift_detected"):
        return insights

    for signal in drift.get("drift_signals", []):
        signal_type = signal.get("type", "")
        severity = signal.get("severity", "low")

        if signal_type == "score_delta":
            delta = signal.get("delta", 0)
            direction = "deterioro" if delta < 0 else "mejora"
            insights.append(_build_insight(
                insight_type="drift",
                severity=severity,
                message=f"Se detecto {direction} significativo del score promedio ({_fmt(delta, sign=True)}).",
                human_summary=(
                    "El score promedio reciente se movio de forma significativa."
                ),
                recommended_target="drift",
                heuristic_key="drift.score_delta",
                generated_at=generated_at,
                key_parts=[signal_type, str(round(delta, 4))],
                metrics={
                    "signal_type": signal_type,
                    "delta": delta,
                    "recent_value": signal.get("recent_value"),
                    "previous_value": signal.get("previous_value"),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la diferencia entre score promedio reciente "
                        "y previo supero el umbral de drift."
                    ),
                    conditions=[
                        f"|score_delta| >= {DRIFT_SCORE_DELTA_THRESHOLD:.2f}",
                        f"delta observado = {_fmt(delta, sign=True)}",
                    ],
                    thresholds={
                        "score_delta_threshold": DRIFT_SCORE_DELTA_THRESHOLD,
                    },
                    evidence={
                        "signal_type": signal_type,
                        "delta": delta,
                        "recent_value": signal.get("recent_value"),
                        "previous_value": signal.get("previous_value"),
                    },
                    interpretation=(
                        "El comportamiento reciente del aprendizaje se alejo materialmente de la "
                        "ventana anterior y conviene revisar drift y timeline."
                    ),
                ),
            ))

        elif signal_type == "block_rate_increase":
            delta = signal.get("delta", 0)
            insights.append(_build_insight(
                insight_type="drift",
                severity=severity,
                message=f"El block_rate aumento un {_fmt_pct(delta)} respecto de la ventana previa.",
                human_summary="El sistema esta bloqueando mas decisiones de lo normal.",
                recommended_target="drift",
                heuristic_key="drift.block_rate_increase",
                generated_at=generated_at,
                key_parts=[signal_type, str(round(delta, 4))],
                metrics={
                    "signal_type": signal_type,
                    "delta": delta,
                    "recent_value": signal.get("recent_value"),
                    "previous_value": signal.get("previous_value"),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la tasa de bloqueo reciente aumento por "
                        "encima del umbral definido para drift."
                    ),
                    conditions=[
                        f"block_rate_delta >= {DRIFT_BLOCK_RATE_THRESHOLD:.2f}",
                        f"delta observado = {_fmt_pct(delta)}",
                    ],
                    thresholds={
                        "block_rate_delta_threshold": DRIFT_BLOCK_RATE_THRESHOLD,
                    },
                    evidence={
                        "signal_type": signal_type,
                        "delta": delta,
                        "recent_value": signal.get("recent_value"),
                        "previous_value": signal.get("previous_value"),
                    },
                    interpretation=(
                        "Una suba del block rate suele indicar que las recomendaciones recientes "
                        "estan siendo frenadas con mas frecuencia de lo esperable."
                    ),
                ),
            ))

        elif signal_type == "trend_inversion":
            insights.append(_build_insight(
                insight_type="drift",
                severity="high",
                message="Se produjo inversion de tendencia: el sistema paso de impacto positivo a negativo.",
                human_summary="Hubo inversion de tendencia entre ventanas.",
                recommended_target="timeline",
                heuristic_key="drift.trend_inversion",
                generated_at=generated_at,
                key_parts=[signal_type],
                metrics={
                    "signal_type": signal_type,
                    "recent_value": signal.get("recent_value"),
                    "previous_value": signal.get("previous_value"),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la ventana previa tenia impacto promedio "
                        "positivo y la ventana reciente paso a impacto negativo."
                    ),
                    conditions=[
                        "previous_avg_score > 0.1",
                        "recent_avg_score < -0.1",
                    ],
                    thresholds={
                        "previous_positive_threshold": 0.1,
                        "recent_negative_threshold": -0.1,
                    },
                    evidence={
                        "signal_type": signal_type,
                        "recent_value": signal.get("recent_value"),
                        "previous_value": signal.get("previous_value"),
                    },
                    interpretation=(
                        "La direccion del aprendizaje se invirtio. Es una senal fuerte para inspeccion "
                        "manual inmediata."
                    ),
                ),
            ))

        elif signal_type == "new_negative_patterns":
            sigs = signal.get("signatures", [])
            insights.append(_build_insight(
                insight_type="drift",
                severity=severity,
                message=f"Aparecieron {len(sigs)} patron(es) negativo(s) nuevo(s): {', '.join(sigs[:3])}{'...' if len(sigs) > 3 else ''}.",
                human_summary="Aparecieron patrones negativos nuevos.",
                recommended_target="drift",
                heuristic_key="drift.new_negative_patterns",
                generated_at=generated_at,
                key_parts=[signal_type, str(len(sigs))],
                metrics={
                    "signal_type": signal_type,
                    "new_negative_signatures": sigs,
                    "count": len(sigs),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque aparecieron signatures negativas nuevas "
                        "con frecuencia suficiente en la ventana reciente."
                    ),
                    conditions=[
                        f"apariciones minimas por signature >= {DRIFT_NEGATIVE_APPEARANCE_MIN}",
                        f"nuevos patrones detectados = {len(sigs)}",
                    ],
                    thresholds={
                        "new_negative_appearance_min": DRIFT_NEGATIVE_APPEARANCE_MIN,
                    },
                    evidence={
                        "signal_type": signal_type,
                        "new_negative_signatures": sigs,
                        "count": len(sigs),
                    },
                    interpretation=(
                        "Esto sugiere que estan emergiendo focos nuevos de deterioro que todavia no "
                        "existian en la ventana anterior."
                    ),
                ),
            ))

    return insights


# ---------------------------------------------------------------------------
# B) Insights de signatures
# ---------------------------------------------------------------------------


def _signature_insights(
    signatures: list[dict[str, Any]],
    *,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []

    for sig in signatures:
        score = sig.get("avg_score", 0)
        obs = sig.get("observation_count", 0)
        name = sig.get("signature", "")

        if score <= SIGNATURE_CRITICAL_SCORE and obs >= SIGNATURE_HIGH_OBS_THRESHOLD:
            insights.append(_build_insight(
                insight_type="signature",
                severity="high",
                message=f"Patron critico detectado: '{name}' con score {_fmt(score)} en {obs} observaciones.",
                human_summary="Esta signature muestra deterioro sostenido.",
                recommended_target="signatures",
                heuristic_key="signature.critical_pattern",
                generated_at=generated_at,
                key_parts=[name, str(obs), str(round(score, 4))],
                metrics={
                    "signature": name,
                    "event_type": sig.get("event_type"),
                    "avg_score": score,
                    "observation_count": obs,
                    "negative_count": sig.get("negative_count", 0),
                    "status": sig.get("status"),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la signature cayo por debajo del score "
                        "critico y ademas acumulo observaciones suficientes."
                    ),
                    conditions=[
                        f"avg_score <= {SIGNATURE_CRITICAL_SCORE:.2f}",
                        f"observation_count >= {SIGNATURE_HIGH_OBS_THRESHOLD}",
                    ],
                    thresholds={
                        "critical_score_threshold": SIGNATURE_CRITICAL_SCORE,
                        "high_observation_threshold": SIGNATURE_HIGH_OBS_THRESHOLD,
                    },
                    evidence={
                        "signature": name,
                        "event_type": sig.get("event_type"),
                        "avg_score": score,
                        "observation_count": obs,
                        "negative_count": sig.get("negative_count", 0),
                    },
                    interpretation=(
                        "Es un patron con deterioro consistente y volumen suficiente como para "
                        "merecer prioridad operativa."
                    ),
                ),
            ))
        elif score <= SIGNATURE_CRITICAL_SCORE:
            insights.append(_build_insight(
                insight_type="signature",
                severity="medium",
                message=f"Patron negativo: '{name}' con score {_fmt(score)} ({obs} obs).",
                human_summary="Esta signature esta mostrando senales negativas.",
                recommended_target="signatures",
                heuristic_key="signature.negative_pattern",
                generated_at=generated_at,
                key_parts=[name, str(obs), str(round(score, 4))],
                metrics={
                    "signature": name,
                    "event_type": sig.get("event_type"),
                    "avg_score": score,
                    "observation_count": obs,
                    "status": sig.get("status"),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la signature cruzo el umbral de score "
                        "negativo, aunque con menor volumen de observaciones."
                    ),
                    conditions=[
                        f"avg_score <= {SIGNATURE_CRITICAL_SCORE:.2f}",
                        f"observation_count < {SIGNATURE_HIGH_OBS_THRESHOLD}",
                    ],
                    thresholds={
                        "critical_score_threshold": SIGNATURE_CRITICAL_SCORE,
                        "high_observation_threshold": SIGNATURE_HIGH_OBS_THRESHOLD,
                    },
                    evidence={
                        "signature": name,
                        "event_type": sig.get("event_type"),
                        "avg_score": score,
                        "observation_count": obs,
                    },
                    interpretation=(
                        "Puede ser un problema incipiente. Conviene seguirlo o inspeccionarlo si "
                        "ya impacta una ruta sensible."
                    ),
                ),
            ))

    return insights


# ---------------------------------------------------------------------------
# C) Insights de families
# ---------------------------------------------------------------------------


def _family_insights(
    families: list[dict[str, Any]],
    *,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []

    for fam in families:
        score = fam.get("avg_score", 0)
        obs = fam.get("observation_count", 0)
        name = fam.get("signature_family", "")

        if score <= FAMILY_SUSTAINED_REGRESSION_SCORE and obs >= FAMILY_SUSTAINED_REGRESSION_MIN_OBS:
            insights.append(_build_insight(
                insight_type="family",
                severity="high" if score <= SIGNATURE_CRITICAL_SCORE else "medium",
                message=f"Familia '{name}' muestra deterioro sostenido: score {_fmt(score)} en {obs} observaciones.",
                human_summary="La familia completa muestra deterioro sostenido.",
                recommended_target="families",
                heuristic_key="family.sustained_regression",
                generated_at=generated_at,
                key_parts=[name, str(obs), str(round(score, 4))],
                metrics={
                    "signature_family": name,
                    "event_type": fam.get("event_type"),
                    "avg_score": score,
                    "observation_count": obs,
                    "negative_count": fam.get("negative_count", 0),
                    "unique_signatures": fam.get("unique_signatures", 0),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la familia completa muestra un score "
                        "negativo sostenido con observaciones suficientes."
                    ),
                    conditions=[
                        f"avg_score <= {FAMILY_SUSTAINED_REGRESSION_SCORE:.2f}",
                        f"observation_count >= {FAMILY_SUSTAINED_REGRESSION_MIN_OBS}",
                    ],
                    thresholds={
                        "sustained_regression_score_threshold": FAMILY_SUSTAINED_REGRESSION_SCORE,
                        "sustained_regression_min_observations": FAMILY_SUSTAINED_REGRESSION_MIN_OBS,
                    },
                    evidence={
                        "signature_family": name,
                        "event_type": fam.get("event_type"),
                        "avg_score": score,
                        "observation_count": obs,
                        "negative_count": fam.get("negative_count", 0),
                        "unique_signatures": fam.get("unique_signatures", 0),
                    },
                    interpretation=(
                        "La degradacion ya no parece aislada a una signature puntual sino que se "
                        "extiende a la familia."
                    ),
                ),
            ))

        elif score >= FAMILY_SUSTAINED_IMPROVEMENT_SCORE and obs >= FAMILY_SUSTAINED_REGRESSION_MIN_OBS:
            insights.append(_build_insight(
                insight_type="family",
                severity="low",
                message=f"Familia '{name}' muestra mejora sostenida: score {_fmt(score, sign=True)} en {obs} observaciones.",
                human_summary="La familia viene mejorando de forma sostenida.",
                recommended_target="families",
                heuristic_key="family.sustained_improvement",
                generated_at=generated_at,
                key_parts=[name, str(obs), str(round(score, 4))],
                metrics={
                    "signature_family": name,
                    "event_type": fam.get("event_type"),
                    "avg_score": score,
                    "observation_count": obs,
                    "positive_count": fam.get("positive_count", 0),
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la familia completo un tramo de mejora "
                        "sostenida por encima del umbral positivo."
                    ),
                    conditions=[
                        f"avg_score >= {FAMILY_SUSTAINED_IMPROVEMENT_SCORE:.2f}",
                        f"observation_count >= {FAMILY_SUSTAINED_REGRESSION_MIN_OBS}",
                    ],
                    thresholds={
                        "sustained_improvement_score_threshold": FAMILY_SUSTAINED_IMPROVEMENT_SCORE,
                        "sustained_regression_min_observations": FAMILY_SUSTAINED_REGRESSION_MIN_OBS,
                    },
                    evidence={
                        "signature_family": name,
                        "event_type": fam.get("event_type"),
                        "avg_score": score,
                        "observation_count": obs,
                        "positive_count": fam.get("positive_count", 0),
                    },
                    interpretation=(
                        "Es una senal favorable: el comportamiento agregado de la familia viene "
                        "mostrando resultados positivos consistentes."
                    ),
                ),
            ))

    return insights


# ---------------------------------------------------------------------------
# D) Insights de decisiones
# ---------------------------------------------------------------------------


def _decision_insights(
    decisions: list[dict[str, Any]],
    overview: dict[str, Any],
    *,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []

    total = overview.get("total_adaptive_decisions", 0)
    blocked = overview.get("blocked_decisions", 0)

    if total > 0:
        block_rate = blocked / total
        if block_rate >= DECISION_BLOCK_RATE_HIGH:
            blocked_decisions = [
                decision
                for decision in decisions
                if str(decision.get("decision_mode") or "") == "blocked"
                or "blocked" in str(decision.get("impact_decision_reason") or "")
                or str(decision.get("final_decision") or "") == "skipped"
            ]
            top_reason = _most_common_nonempty(
                str(decision.get("impact_decision_reason") or "")
                for decision in blocked_decisions
            )
            top_reference = _most_common_nonempty(
                str((decision.get("dominant_signal") or {}).get("reference") or "")
                for decision in blocked_decisions
            )
            insights.append(_build_insight(
                insight_type="decisions",
                severity="high" if block_rate >= 0.6 else "medium",
                message=f"Tasa de bloqueo elevada: {_fmt_pct(block_rate)} de las decisiones fueron bloqueadas ({blocked}/{total}).",
                human_summary="El sistema esta bloqueando mas decisiones de lo normal.",
                recommended_target="decisions",
                heuristic_key="decisions.high_block_rate",
                generated_at=generated_at,
                key_parts=[str(blocked), str(total), str(round(block_rate, 4))],
                metrics={
                    "block_rate": round(block_rate, 4),
                    "blocked": blocked,
                    "total": total,
                    "impact_decision_reason": top_reason,
                    "dominant_signal_reference": top_reference,
                },
                explanation=_build_explanation(
                    summary=(
                        "Este insight se genero porque la tasa de decisiones bloqueadas supero el "
                        "umbral operativo definido."
                    ),
                    conditions=[
                        f"block_rate >= {DECISION_BLOCK_RATE_HIGH:.2f}",
                        f"bloqueadas = {blocked}",
                        f"total = {total}",
                    ],
                    thresholds={
                        "block_rate_high_threshold": DECISION_BLOCK_RATE_HIGH,
                    },
                    evidence={
                        "block_rate": round(block_rate, 4),
                        "blocked": blocked,
                        "total": total,
                        "impact_decision_reason": top_reason,
                        "dominant_signal_reference": top_reference,
                    },
                    interpretation=(
                        "Cuando demasiadas decisiones terminan bloqueadas, puede haber memoria "
                        "negativa dominante o thresholds demasiado restrictivos."
                    ),
                ),
            ))

    low_conf_decisions = [
        d for d in decisions
        if (d.get("confidence_score") or 1.0) < DECISION_CONFIDENCE_LOW
    ]
    if len(low_conf_decisions) >= 3:
        top_reference = _most_common_nonempty(
            str((decision.get("dominant_signal") or {}).get("reference") or "")
            for decision in low_conf_decisions
        )
        top_reason = _most_common_nonempty(
            str(decision.get("impact_decision_reason") or "")
            for decision in low_conf_decisions
        )
        insights.append(_build_insight(
            insight_type="decisions",
            severity="medium",
            message=f"{len(low_conf_decisions)} decisiones recientes tienen confianza baja (< {DECISION_CONFIDENCE_LOW}).",
            human_summary="Hay varias decisiones recientes con baja confianza.",
            recommended_target="decisions",
            heuristic_key="decisions.low_confidence",
            generated_at=generated_at,
            key_parts=[str(len(low_conf_decisions)), str(len(decisions))],
            metrics={
                "low_confidence_count": len(low_conf_decisions),
                "threshold": DECISION_CONFIDENCE_LOW,
                "total_decisions": len(decisions),
                "dominant_signal_reference": top_reference,
                "impact_decision_reason": top_reason,
            },
            explanation=_build_explanation(
                summary=(
                    "Este insight se genero porque varias decisiones recientes quedaron por "
                    "debajo del umbral minimo de confianza."
                ),
                conditions=[
                    f"confidence_score < {DECISION_CONFIDENCE_LOW:.2f}",
                    f"low_confidence_count >= 3",
                ],
                thresholds={
                    "confidence_low_threshold": DECISION_CONFIDENCE_LOW,
                    "minimum_low_confidence_count": 3,
                },
                evidence={
                    "low_confidence_count": len(low_conf_decisions),
                    "total_decisions": len(decisions),
                    "dominant_signal_reference": top_reference,
                    "impact_decision_reason": top_reason,
                },
                interpretation=(
                    "Esto suele indicar recomendacion debil o evidencia de memoria insuficiente "
                    "para decidir con seguridad."
                ),
            ),
        ))

    return insights


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(value: float, sign: bool = False) -> str:
    prefix = "+" if sign and value > 0 else ""
    return f"{prefix}{value:.3f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _most_common_nonempty(values: Any) -> str:
    counts = Counter(value for value in values if str(value or "").strip())
    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def _build_explanation(
    *,
    summary: str,
    conditions: list[str] | None = None,
    thresholds: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    interpretation: str = "",
) -> dict[str, Any]:
    return {
        "version": EXPLANATION_VERSION,
        "source": EXPLANATION_SOURCE,
        "summary": summary,
        "conditions": conditions or [],
        "thresholds": thresholds or {},
        "evidence": evidence or {},
        "interpretation": interpretation,
    }


def _build_insight(
    *,
    insight_type: str,
    severity: str,
    message: str,
    human_summary: str,
    recommended_target: str,
    heuristic_key: str,
    generated_at: datetime,
    key_parts: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    explanation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key_suffix = ".".join(part for part in (key_parts or []) if str(part).strip())
    insight_key = heuristic_key if not key_suffix else f"{heuristic_key}:{key_suffix}"
    return {
        "type": insight_type,
        "severity": severity,
        "message": message,
        "human_summary": human_summary,
        "recommended_target": recommended_target,
        "generated_at": generated_at.isoformat(),
        "heuristic_key": heuristic_key,
        "insight_key": insight_key,
        "metrics": metrics or {},
        "explanation": explanation or _build_explanation(
            summary=message,
            evidence=metrics or {},
            interpretation="No se genero una interpretacion adicional.",
        ),
    }


def _severity_rank(insight: dict[str, Any]) -> tuple[int, str]:
    order = {"high": 0, "medium": 1, "low": 2}
    return (order.get(insight.get("severity", "low"), 3), insight.get("type", ""))
