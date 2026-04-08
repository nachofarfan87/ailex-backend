# backend/app/services/strategy_language_service.py
from __future__ import annotations

from typing import Any


def resolve_strategy_language_profile(
    smart_strategy: dict[str, Any] | None,
    *,
    composition_profile: dict[str, Any] | None = None,
    conversation_state: dict[str, Any] | None = None,
    output_mode: str | None = None,
    turn_type: str | None = None,
    stable_bucket: int | None = None,
) -> dict[str, Any]:
    """
    Resuelve una politica micro-linguistica estable para la respuesta.

    Returns:
    {
        "strategy_mode": str,
        "tone_style": str,
        "opening_style": str,
        "closing_style": str,
        "bridge_style": str,
        "followup_style": str,
        "variation_bucket": int,
        "directiveness_level": "low" | "medium" | "high",
        "prudence_visibility": "low" | "medium" | "high",
        "selected_opening": str,
        "selected_bridge": str,
        "selected_followup_intro": str,
        "selected_closing": str,
        "reason": str,
    }
    """
    smart_strategy = dict(smart_strategy or {})
    composition_profile = dict(composition_profile or {})
    conversation_state = dict(conversation_state or {})

    strategy_mode = str(smart_strategy.get("strategy_mode") or "orient_with_prudence").strip().lower()
    normalized_output_mode = str(output_mode or "orientacion_inicial").strip().lower()
    normalized_turn_type = str(turn_type or "").strip().lower()
    # stable_bucket viene del consistency service (FASE 12.7) y ancla la variación
    # al contexto estratégico, no al turn_count. Si no se provee, se computa localmente.
    variation_bucket = (
        int(stable_bucket) % 3
        if stable_bucket is not None
        else _resolve_variation_bucket(
            strategy_mode=strategy_mode,
            output_mode=normalized_output_mode,
            turn_type=normalized_turn_type,
            conversation_state=conversation_state,
        )
    )

    if strategy_mode == "clarify_critical":
        return _build_profile(
            strategy_mode=strategy_mode,
            tone_style="precise",
            opening_style="minimal",
            closing_style="question_only",
            bridge_style="precise",
            followup_style="single_precise",
            directiveness_level="high",
            prudence_visibility="medium",
            variation_bucket=variation_bucket,
            opening_options=(
                "Hay un punto que define esto ahora.",
                "Lo que falta para cerrar esto es un dato puntual.",
                "El encuadre depende de una sola aclaracion.",
            ),
            bridge_options=(
                "Lo que necesito confirmar es esto:",
                "Necesito precisar solo este punto:",
                "Para destrabarlo, necesito confirmar esto:",
            ),
            followup_options=(
                "Necesito confirmar solo esto:",
                "Antes de seguir, necesito este dato:",
                "Para cerrar esto bien, necesito confirmar:",
            ),
            closing_options=("", "", ""),
            reason="El turno debe sonar preciso, breve y con una sola aclaracion util.",
        )

    if strategy_mode == "action_first":
        bridge_options = (
            "Para avanzar de forma concreta, podes hacer esto:",
            "Si quisieras mover esto ya, estos serian los pasos:",
            "Para avanzar de forma concreta, podes hacer esto:",
        )
        return _build_profile(
            strategy_mode=strategy_mode,
            tone_style="executive",
            opening_style="none",
            closing_style="practical",
            bridge_style="direct_action",
            followup_style="secondary_critical",
            directiveness_level="high",
            prudence_visibility="low",
            variation_bucket=variation_bucket,
            opening_options=("", "", ""),
            bridge_options=bridge_options,
            followup_options=(
                "Si queres afinar el paso siguiente, necesito este dato:",
                "Solo para ajustar el paso inmediato, necesito saber:",
                "Si queres cerrarlo mejor, necesito este dato puntual:",
            ),
            closing_options=(
                "Con esto ya tenes un siguiente paso concreto para mover el caso.",
                "Con esto ya podes activar el caso sin dar vueltas.",
                "Con esto ya podes avanzar de forma bien concreta.",
            ),
            reason="El turno debe ir al punto, priorizar accion y evitar introducciones innecesarias.",
        )

    if strategy_mode == "substantive_analysis":
        return _build_profile(
            strategy_mode=strategy_mode,
            tone_style="analytical",
            opening_style="analysis",
            closing_style="analysis",
            bridge_style="articulated",
            followup_style="disabled",
            directiveness_level="medium",
            prudence_visibility="medium",
            variation_bucket=variation_bucket,
            opening_options=(
                "Con la base que ya reuniste, el caso permite una lectura mas firme.",
                "Con lo que ya esta definido, se puede hacer una lectura estrategica bastante solida.",
                "Con esta base, ya se puede desarrollar una orientacion mas articulada.",
            ),
            bridge_options=(
                "La lectura estrategica quedaria asi:",
                "Si lo ordenamos con mas desarrollo, la conclusion principal es esta:",
                "La via que mejor se sostiene hoy es esta:",
            ),
            followup_options=("", "", ""),
            closing_options=(
                "Con esta base, ya se puede sostener una orientacion mas firme del caso.",
                "Con este cuadro, la estrategia ya tiene una base bastante consistente.",
                "Con esto, la orientacion ya se puede defender con mas solidez.",
            ),
            reason="El turno puede sonar mas articulado y analitico, sin inflarse.",
        )

    if strategy_mode == "guide_next_step":
        opening_options = (
            "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
            "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
            "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
        )
        bridge_options = (
            "Con lo que hay hoy, conviene avanzar asi:",
            "Hoy, lo mas solido es ir por este camino:",
            "Con lo que hay hoy, conviene avanzar asi:",
        ) if normalized_output_mode == "estrategia" else (
            "Para avanzar de forma concreta, podes hacer esto:",
            "Si quisieras mover esto ya, estos serian los pasos:",
            "Para avanzar de forma concreta, podes hacer esto:",
        ) if normalized_output_mode == "ejecucion" else (
            "Lo que conviene mover ahora es esto:",
            "El siguiente movimiento util seria este:",
            "Si tuviera que ordenarlo por utilidad inmediata, iria por aca:",
        )
        return _build_profile(
            strategy_mode=strategy_mode,
            tone_style="guiding",
            opening_style="guided",
            closing_style="practical_guided",
            bridge_style="next_step",
            followup_style="functional",
            directiveness_level="medium",
            prudence_visibility="medium",
            variation_bucket=variation_bucket,
            opening_options=opening_options,
            bridge_options=bridge_options,
            followup_options=(
                "Para orientar bien ese paso, necesito confirmar:",
                "Si queres cerrar mejor ese movimiento, necesito este dato:",
                "Para afinar ese paso sin perder foco, necesito saber:",
            ),
            closing_options=(
                "Con esto ya tenes un siguiente paso claro para seguir.",
                "Con esto ya se ve bien que conviene mover ahora.",
                "Con esta base, el siguiente movimiento queda bastante encaminado.",
            ),
            reason="El turno debe sonar orientador y funcional, sin sobredesarrollar.",
        )

    if strategy_mode == "close_without_more_questions":
        opening_options = (
            "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
            "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
            "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
        ) if normalized_output_mode == "estructuracion" else (
            "Con esta base ya se puede cerrar este turno de forma util.",
            "Con lo que ya hay, conviene cerrar aca con una orientacion clara.",
            "Con esta informacion, hoy suma mas orientar que seguir abriendo preguntas.",
        )
        bridge_options = (
            "Con lo que hay hoy, conviene avanzar asi:",
            "Hoy, lo mas solido es ir por este camino:",
            "Si ordenamos esto estrategicamente, la mejor via es:",
        ) if normalized_output_mode == "estrategia" else (
            "Lo que te conviene llevarte ahora es esto:",
            "La conclusion util hoy seria esta:",
            "Si lo cerramos ordenadamente, queda asi:",
        )
        return _build_profile(
            strategy_mode=strategy_mode,
            tone_style="conclusive",
            opening_style="minimal",
            closing_style="clean",
            bridge_style="conclusive",
            followup_style="disabled",
            directiveness_level="medium",
            prudence_visibility="medium",
            variation_bucket=variation_bucket,
            opening_options=opening_options,
            bridge_options=bridge_options,
            followup_options=("", "", ""),
            closing_options=(
                "Con esto ya tenes una base clara para seguir sin abrir otro frente ahora.",
                "Con esto ya podes continuar con una orientacion util y cerrada.",
                "Con esta base ya conviene seguir, no abrir mas preguntas por ahora.",
            ),
            reason="El turno debe cerrar con elegancia y utilidad, sin reabrir el caso.",
        )

    opening_options = (
        "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
        "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
        "Con lo que me contaste hasta ahora, el caso ya se puede ordenar mejor.",
    ) if normalized_output_mode == "estructuracion" else (
        "Con esta base ya te puedo orientar con prudencia.",
        "Con lo que ya sabemos, hay una orientacion util sin forzar conclusiones.",
        "Con esta informacion ya se puede avanzar con criterio, aunque todavia con prudencia.",
    )
    bridge_options = (
        "Con lo que hay hoy, conviene avanzar asi:",
        "Hoy, lo mas solido es ir por este camino:",
        "Si ordenamos esto estrategicamente, la mejor via es:",
    ) if normalized_output_mode == "estrategia" else (
        "Lo mas util ahora es esto:",
        "Si tuviera que ordenarlo con prudencia, iria por aca:",
        "Hoy conviene mirarlo asi:",
    )

    return _build_profile(
        strategy_mode=strategy_mode or "orient_with_prudence",
        tone_style="prudent",
        opening_style="guided",
        closing_style="prudent",
        bridge_style="prudent_guided",
        followup_style="soft_functional",
        directiveness_level="medium",
        prudence_visibility="high",
        variation_bucket=variation_bucket,
        opening_options=opening_options,
        bridge_options=bridge_options,
        followup_options=(
            "Si queres cerrar mejor este punto, me ayudaria saber:",
            "Solo para no dejar un borde abierto, me serviria confirmar:",
            "Si queres afinarlo un poco mas, necesito saber:",
        ),
        closing_options=(
            "Con esto ya tenes una orientacion util para seguir sin apurarte de mas.",
            "Con esta base ya se puede avanzar con cuidado y con criterio.",
            "Con esto podes seguir con una idea clara, sin cerrar en falso.",
        ),
        reason="El turno debe sonar prudente, util y humano, sin burocracia.",
    )


_LEGAL_REFERRAL_NOTE = (
    "Si no tenes abogado:\n"
    "- podes pedir orientacion inicial en defensoria o en el organismo publico que corresponda en tu jurisdiccion."
)

# Modos donde la nota de derivacion legal es pertinente (orientacion amplia, sin accion especifica ya definida).
_MODES_WITH_LEGAL_REFERRAL: frozenset[str] = frozenset({"orient_with_prudence", "guide_next_step"})


def _build_profile(
    *,
    strategy_mode: str,
    tone_style: str,
    opening_style: str,
    closing_style: str,
    bridge_style: str,
    followup_style: str,
    directiveness_level: str,
    prudence_visibility: str,
    variation_bucket: int,
    opening_options: tuple[str, ...],
    bridge_options: tuple[str, ...],
    followup_options: tuple[str, ...],
    closing_options: tuple[str, ...],
    reason: str,
) -> dict[str, Any]:
    legal_referral_note = _LEGAL_REFERRAL_NOTE if strategy_mode in _MODES_WITH_LEGAL_REFERRAL else ""
    return {
        "strategy_mode": strategy_mode,
        "tone_style": tone_style,
        "opening_style": opening_style,
        "closing_style": closing_style,
        "bridge_style": bridge_style,
        "followup_style": followup_style,
        "variation_bucket": variation_bucket,
        "directiveness_level": directiveness_level,
        "prudence_visibility": prudence_visibility,
        "selected_opening": _pick_variant(opening_options, variation_bucket),
        "selected_bridge": _pick_variant(bridge_options, variation_bucket),
        "selected_followup_intro": _pick_variant(followup_options, variation_bucket),
        "selected_closing": _pick_variant(closing_options, variation_bucket),
        "selected_legal_referral_note": legal_referral_note,
        "reason": reason,
    }


def _resolve_variation_bucket(
    *,
    strategy_mode: str,
    output_mode: str,
    turn_type: str,
    conversation_state: dict[str, Any],
) -> int:
    progress = dict(conversation_state.get("progress_signals") or {})
    conversation_memory = dict(conversation_state.get("conversation_memory") or {})
    turn_count = int(conversation_state.get("turn_count") or 0)
    seed = (
        len(strategy_mode) * 7
        + len(output_mode) * 5
        + len(turn_type) * 3
        + turn_count
        + len(str(progress.get("case_completeness") or ""))
        + len(str(progress.get("progress_state") or ""))
        + len(str(conversation_memory.get("last_turn_type") or ""))
    )
    return seed % 3


def _pick_variant(options: tuple[str, ...], bucket: int) -> str:
    clean = [str(item or "").strip() for item in options if str(item or "").strip()]
    if not clean:
        return ""
    return clean[bucket % len(clean)]
