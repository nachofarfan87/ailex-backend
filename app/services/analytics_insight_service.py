from __future__ import annotations

from typing import Any


_INSIGHT_ACTIONS = {
    "insufficient_sessions": "wait_for_more_data",
    "high_session_abandonment": "review_question_flow",
    "high_dropoff_turn_1": "review_first_question",
    "high_clarification_low_closure": "reduce_questions",
    "high_abandonment_low_closure": "review_question_flow",
    "low_closure_rate": "review_question_flow",
    "low_effectiveness": "improve_advice_generation",
    "low_quick_reply_usage": "improve_quick_reply_visibility",
    "high_clarification_rate": "reduce_questions",
    "high_time_to_advice": "accelerate_advice_transition",
    "healthy_flow": "keep_monitoring",
}


def generate_analytics_insights(summary: dict[str, Any] | None) -> list[dict[str, str]]:
    safe_summary = dict(summary or {})
    insights: list[dict[str, str]] = []
    severity_order = {
        "high": 0,
        "medium": 1,
        "low": 2,
        "info": 3,
        "positive": 4,
    }

    total_sessions = int(safe_summary.get("total_sessions") or 0)
    if total_sessions <= 0:
        return [
            _build_insight(
                code="insufficient_sessions",
                insight_type="info",
                severity="low",
                message="Todavia no hay sesiones suficientes para interpretar la beta.",
            )
        ]

    abandoned_sessions = int(safe_summary.get("abandoned_sessions") or 0)
    closure_rate = float(safe_summary.get("closure_rate") or 0.0)
    quick_reply_rate = float(safe_summary.get("quick_reply_rate") or 0.0)
    clarification_rate = float(safe_summary.get("clarification_rate") or 0.0)
    effective_sessions_rate = float(safe_summary.get("effective_sessions_rate") or 0.0)
    avg_time_to_advice_seconds = safe_summary.get("avg_time_to_advice_seconds")
    top_case_domains = safe_summary.get("top_case_domains") or []
    dropoff_by_turn = safe_summary.get("dropoff_by_turn") or []

    if abandoned_sessions / total_sessions >= 0.4:
        insights.append(
            _build_insight(
                code="high_session_abandonment",
                insight_type="warning",
                severity="high",
                message="Alto abandono general de sesiones en la beta.",
            )
        )

    first_dropoff = next((item for item in dropoff_by_turn if int(item.get("turn") or 0) == 1), None)
    if first_dropoff and float(first_dropoff.get("rate") or 0.0) >= 0.25:
        insights.append(
            _build_insight(
                code="high_dropoff_turn_1",
                insight_type="warning",
                severity="high",
                message="Alto abandono en turno 1.",
            )
        )

    if clarification_rate >= 0.7 and closure_rate < 0.4:
        insights.append(
            _build_insight(
                code="high_clarification_low_closure",
                insight_type="warning",
                severity="high",
                message="La conversacion solicita demasiada informacion pero no logra cerrar.",
            )
        )

    if closure_rate < 0.35 and abandoned_sessions / total_sessions >= 0.4:
        domain_label = _domain_label(top_case_domains)
        insights.append(
            _build_insight(
                code="high_abandonment_low_closure",
                insight_type="warning",
                severity="high",
                message=f"Alto abandono en consultas de {domain_label}" if domain_label else "Alto abandono combinado con baja tasa de cierre.",
            )
        )

    if closure_rate < 0.35:
        domain_label = _domain_label(top_case_domains)
        message = "Baja tasa de cierre conversacional."
        if domain_label:
            message = f"Baja tasa de cierre en {domain_label}."
        insights.append(
            _build_insight(
                code="low_closure_rate",
                insight_type="warning",
                severity="high" if closure_rate < 0.2 else "medium",
                message=message,
            )
        )

    if effective_sessions_rate < 0.3:
        insights.append(
            _build_insight(
                code="low_effectiveness",
                insight_type="warning",
                severity="high",
                message="Muchas sesiones cierran sin generar orientación útil.",
            )
        )

    if quick_reply_rate < 0.15:
        insights.append(
            _build_insight(
                code="low_quick_reply_usage",
                insight_type="info",
                severity="medium",
                message="Quick replies poco usados.",
            )
        )

    if clarification_rate >= 0.7:
        insights.append(
            _build_insight(
                code="high_clarification_rate",
                insight_type="warning",
                severity="medium",
                message="La beta entra en clarification mode con mucha frecuencia.",
            )
        )

    if isinstance(avg_time_to_advice_seconds, (int, float)) and float(avg_time_to_advice_seconds) >= 30:
        insights.append(
            _build_insight(
                code="high_time_to_advice",
                insight_type="warning",
                severity="medium",
                message="Tiempo alto hasta advice mode.",
            )
        )

    if not insights:
        insights.append(
            _build_insight(
                code="healthy_flow",
                insight_type="positive",
                severity="low",
                message="La beta muestra un flujo conversacional estable con las reglas actuales.",
            )
        )

    insights.sort(key=lambda item: severity_order.get(item.get("severity"), 5))
    return insights


def _domain_label(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    top_item = items[0] or {}
    value = str(top_item.get("value") or "").strip().lower()
    if not value:
        return ""
    return value.replace("_", " ")


def _build_insight(
    *,
    code: str,
    insight_type: str,
    severity: str,
    message: str,
) -> dict[str, str]:
    return {
        "type": insight_type,
        "severity": severity,
        "message": message,
        "code": code,
        "suggested_action": _INSIGHT_ACTIONS.get(code, "review_manually"),
    }
