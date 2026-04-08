# backend/app/services/strategy_composition_service.py
from __future__ import annotations

from typing import Any


def resolve_strategy_composition_profile(
    smart_strategy: dict[str, Any] | None,
    *,
    output_mode: str,
    case_followup: dict[str, Any] | None = None,
    case_confidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Traduce smart_strategy a una politica concreta de composicion.

    Salida interna esperada:
    {
        "strategy_mode": str,
        "opening_style": "none" | "minimal" | "guided" | "analysis",
        "closing_style": "question_only" | "action_close" | "clean_close" | "analysis_close",
        "content_density": "brief" | "guided" | "standard" | "extended",
        "allow_followup": bool,
        "prioritize_action": bool,
        "limit_analysis": bool,
        "max_chars": int,
        "block_order": list[str],
        "reason": str,
    }
    """
    smart_strategy = dict(smart_strategy or {})
    case_followup = dict(case_followup or {})
    case_confidence = dict(case_confidence or {})
    strategy_mode = str(smart_strategy.get("strategy_mode") or "orient_with_prudence").strip()
    normalized_output_mode = str(output_mode or "orientacion_inicial").strip().lower()

    if strategy_mode == "clarify_critical":
        return {
            "strategy_mode": strategy_mode,
            "opening_style": "minimal",
            "closing_style": "question_only",
            "content_density": "brief",
            "allow_followup": bool(case_followup.get("should_ask")),
            "prioritize_action": False,
            "limit_analysis": True,
            "max_chars": 480 if normalized_output_mode != "orientacion_inicial" else 620,
            "block_order": ["opening", "known", "priority", "followup"],
            "reason": "La respuesta debe ir al punto y cerrar con una sola aclaracion critica.",
        }

    if strategy_mode == "action_first":
        allow_followup = bool(case_followup.get("should_ask")) and str(
            case_followup.get("adaptive_question_type") or ""
        ).strip().lower() == "critical"
        return {
            "strategy_mode": strategy_mode,
            "opening_style": "none",
            "closing_style": "action_close",
            "content_density": "guided",
            "allow_followup": allow_followup,
            "prioritize_action": True,
            "limit_analysis": True,
            "max_chars": 560 if normalized_output_mode == "ejecucion" else 620,
            "block_order": ["actions", "where", "documents", "requests", "followup"],
            "reason": "La composicion debe priorizar utilidad operativa inmediata.",
        }

    if strategy_mode == "substantive_analysis":
        depth = str(case_confidence.get("recommended_depth") or "").strip().lower()
        return {
            "strategy_mode": strategy_mode,
            "opening_style": "analysis",
            "closing_style": "analysis_close",
            "content_density": "extended" if depth == "extended" else "standard",
            "allow_followup": False,
            "prioritize_action": False,
            "limit_analysis": False,
            "max_chars": 860 if depth == "extended" else 760,
            "block_order": ["recommendation", "justification", "priority_action", "alternative", "closing"],
            "reason": "Hay base para desarrollar una orientacion mas rica sin volverla redundante.",
        }

    if strategy_mode == "guide_next_step":
        return {
            "strategy_mode": strategy_mode,
            "opening_style": "guided",
            "closing_style": "action_close",
            "content_density": "guided",
            "allow_followup": bool(case_followup.get("should_ask")),
            "prioritize_action": True,
            "limit_analysis": True,
            "max_chars": 620,
            "block_order": ["opening", "priority", "actions", "followup", "closing"],
            "reason": "La respuesta debe orientar el siguiente movimiento util sin desplegar un analisis largo.",
        }

    if strategy_mode == "close_without_more_questions":
        return {
            "strategy_mode": strategy_mode,
            "opening_style": "minimal",
            "closing_style": "clean_close",
            "content_density": "brief",
            "allow_followup": False,
            "prioritize_action": False,
            "limit_analysis": True,
            "max_chars": 680 if normalized_output_mode == "estrategia" else 560,
            "block_order": ["opening", "recommendation", "priority", "closing"],
            "reason": "La respuesta debe cerrar limpia y utilmente sin reabrir el turno.",
        }

    return {
        "strategy_mode": strategy_mode,
        "opening_style": "guided",
        "closing_style": "clean_close",
        "content_density": "guided",
        "allow_followup": False,
        "prioritize_action": False,
        "limit_analysis": True,
        "max_chars": 640,
        "block_order": ["opening", "recommendation", "priority", "closing"],
        "reason": "Conviene orientar con prudencia, mostrar limites y dejar un siguiente paso util.",
    }
