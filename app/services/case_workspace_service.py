from __future__ import annotations

import re
from typing import Any

from app.services.case_action_plan_service import build_case_action_plan
from app.services.case_evidence_service import build_case_evidence_checklist
from app.services.conversation_integrity_service import canonicalize_concept_key
from app.services.utc import utc_now

WORKSPACE_VERSION = "case_workspace_v1"


def build_case_workspace(
    *,
    api_payload: dict[str, Any] | None,
    workspace_version: str = WORKSPACE_VERSION,
) -> dict[str, Any]:
    payload = dict(api_payload or {})
    case_memory = dict(payload.get("case_memory") or {})
    case_progress = dict(payload.get("case_progress") or {})
    case_followup = dict(payload.get("case_followup") or {})

    case_id = _resolve_case_id(payload)
    case_status = resolve_case_status(
        case_progress=case_progress,
        case_followup=case_followup,
        case_confidence=dict(payload.get("case_confidence") or {}),
    )
    operating_phase = resolve_operating_phase(
        case_progress=case_progress,
        case_followup=case_followup,
        case_status=case_status,
    )
    recommended_phase = map_recommended_phase(operating_phase)
    operating_phase_reason = build_operating_phase_reason(
        case_progress=case_progress,
        case_followup=case_followup,
        case_status=case_status,
        operating_phase=operating_phase,
    )
    case_summary = build_workspace_summary(
        api_payload=payload,
        case_status=case_status,
    )
    recommended_next_question = (
        str(case_followup.get("question") or "").strip()
        if bool(case_followup.get("should_ask"))
        else ""
    )
    action_plan = build_case_action_plan(
        api_payload=payload,
        case_status=case_status,
        operating_phase=operating_phase,
    )
    primary_focus = build_primary_focus(
        case_progress=case_progress,
        case_status=case_status,
        operating_phase=operating_phase,
        primary_step=action_plan[0] if action_plan else None,
        recommended_next_question=recommended_next_question,
    )

    workspace = {
        "case_id": case_id,
        "workspace_version": str(workspace_version or WORKSPACE_VERSION),
        "case_status": case_status,
        "case_status_label": _case_status_label(case_status),
        "case_status_helper": _case_status_helper(case_status),
        "operating_phase": operating_phase,
        "recommended_phase": recommended_phase,
        "recommended_phase_label": _recommended_phase_label(recommended_phase),
        "operating_phase_reason": operating_phase_reason,
        "primary_focus": primary_focus,
        "case_summary": case_summary,
        "facts_confirmed": _build_confirmed_facts(case_memory),
        "facts_missing": _build_missing_facts(case_memory),
        "facts_conflicting": _build_conflicting_facts(case_memory),
        "strategy_snapshot": _build_strategy_snapshot(payload),
        "action_plan": action_plan,
        "evidence_checklist": build_case_evidence_checklist(api_payload=payload, action_plan=action_plan),
        "risk_alerts": _build_risk_alerts(payload),
        "recommended_next_question": recommended_next_question,
        "professional_handoff": build_professional_handoff(
            api_payload=payload,
            case_status=case_status,
            operating_phase=operating_phase,
            case_summary=case_summary,
            recommended_next_question=recommended_next_question,
        ),
        "last_updated_at": f"{utc_now().isoformat()}Z",
    }
    return _apply_global_workspace_dedup(workspace)


def resolve_case_status(
    *,
    case_progress: dict[str, Any] | None,
    case_followup: dict[str, Any] | None = None,
    case_confidence: dict[str, Any] | None = None,
) -> str:
    progress = dict(case_progress or {})
    followup = dict(case_followup or {})
    confidence = dict(case_confidence or {})

    stage = str(progress.get("stage") or "").strip().lower()
    readiness = str(progress.get("readiness_label") or "").strip().lower()
    progress_status = str(progress.get("progress_status") or "").strip().lower()
    contradictions = list(progress.get("contradictions") or [])

    if stage == "inconsistente" or contradictions:
        return "needs_fact_reconciliation"
    if stage == "bloqueado" or progress_status == "blocked":
        return "blocked"
    if stage == "ejecucion" and readiness == "high":
        return "ready_for_execution"
    if stage == "decision":
        return "ready_for_strategy_decision"
    if bool(followup.get("should_ask")):
        return "needs_information"
    if stage == "estructuracion":
        return "structuring_case"
    if str(confidence.get("case_stage") or "").strip().lower() in {"substantive", "mature"}:
        return "substantive_review"
    return "intake_in_progress"


def resolve_operating_phase(
    *,
    case_progress: dict[str, Any] | None,
    case_followup: dict[str, Any] | None,
    case_status: str,
) -> str:
    progress = dict(case_progress or {})
    followup = dict(case_followup or {})
    stage = str(progress.get("stage") or "").strip().lower()
    next_step_type = str(progress.get("next_step_type") or "").strip().lower()
    contradictions = list(progress.get("contradictions") or [])
    critical_gaps = list(progress.get("critical_gaps") or [])
    blocking_issues = list(progress.get("blocking_issues") or [])

    if contradictions or next_step_type == "resolve_contradiction":
        return "clarify"
    if bool(followup.get("should_ask")) or critical_gaps or case_status == "needs_information":
        return "clarify"
    if stage in {"exploracion", "estructuracion"} or case_status in {"structuring_case", "intake_in_progress"}:
        return "structure"
    if blocking_issues or case_status == "blocked":
        return "review"
    if next_step_type == "decide" or stage == "decision" or case_status == "ready_for_strategy_decision":
        return "decide"
    if next_step_type == "execute" or case_status == "ready_for_execution":
        return "execute"
    if case_status == "substantive_review":
        return "review"
    return "structure"


def map_recommended_phase(operating_phase: str) -> str:
    mapping = {
        "clarify": "clarify_facts",
        "review": "resolve_conflicts",
        "decide": "define_strategy",
        "structure": "prepare_action",
        "execute": "execute_action",
    }
    return mapping.get(str(operating_phase or "").strip().lower(), "prepare_action")


def build_operating_phase_reason(
    *,
    case_progress: dict[str, Any] | None,
    case_followup: dict[str, Any] | None,
    case_status: str,
    operating_phase: str,
) -> str:
    progress = dict(case_progress or {})
    contradictions = list(progress.get("contradictions") or [])
    critical_gaps = list(progress.get("critical_gaps") or [])
    blocking_issues = list(progress.get("blocking_issues") or [])
    followup = dict(case_followup or {})

    if operating_phase == "clarify" and contradictions:
        return "Lo mas importante ahora es aclarar la inconsistencia dominante antes de definir un movimiento mayor."
    if operating_phase == "clarify" and (critical_gaps or bool(followup.get("should_ask"))):
        return "Lo mas importante ahora es completar el dato faltante que define como conviene seguir con el caso."
    if operating_phase == "structure":
        return "Con lo que ya esta definido, conviene ordenar mejor la base factica y documental antes de profundizar."
    if operating_phase == "review" and (blocking_issues or case_status == "blocked"):
        return "Para avanzar con seguridad, primero conviene revisar el freno actual antes de pasar a una decision o ejecucion."
    if operating_phase == "decide":
        return "Con lo que ya esta definido, ya se pueden comparar vias y fijar una direccion principal con prudencia."
    if operating_phase == "execute":
        return "Con lo que ya esta definido, ya se puede preparar un paso juridico-operativo concreto."
    return "La fase operativa se definio con la informacion hoy disponible."


def build_primary_focus(
    *,
    case_progress: dict[str, Any] | None,
    case_status: str,
    operating_phase: str,
    primary_step: dict[str, Any] | None = None,
    recommended_next_question: str = "",
) -> dict[str, str]:
    progress = dict(case_progress or {})
    contradictions = [dict(item) for item in list(progress.get("contradictions") or []) if isinstance(item, dict)]
    critical_gaps = [dict(item) for item in list(progress.get("critical_gaps") or []) if isinstance(item, dict)]
    important_gaps = [dict(item) for item in list(progress.get("important_gaps") or []) if isinstance(item, dict)]
    primary = dict(primary_step or {})
    primary_label = str(primary.get("title") or "").strip()

    if contradictions:
        label = primary_label or _humanize_label(contradictions[0].get("label") or contradictions[0].get("key"))
        return {
            "type": "contradiction",
            "label": label or "Aclarar la inconsistencia principal del caso",
            "reason": "Mientras esta contradiccion siga abierta, cualquier definicion procesal o paso operativo puede apoyarse en una base equivocada.",
        }
    if critical_gaps:
        label = _humanize_label(critical_gaps[0].get("label") or critical_gaps[0].get("key"))
        return {
            "type": "missing_info",
            "label": primary_label or (f"Definir {label}" if label else "Completar el dato faltante principal"),
            "reason": _missing_focus_reason(critical_gaps[0]),
        }
    if case_status == "ready_for_execution" or operating_phase == "execute":
        return {
            "type": "action",
            "label": primary_label or "Pasar al siguiente paso concreto del caso",
            "reason": "Con lo que ya esta definido, este es el paso que convierte la orientacion en una accion concreta del caso.",
        }
    if important_gaps or operating_phase in {"decide", "review"}:
        return {
            "type": "strategy",
            "label": primary_label or "Definir la via principal del caso",
            "reason": "Esto define la via principal y condiciona los proximos pasos, el riesgo asumido y el esfuerzo probatorio del caso.",
        }
    return {
        "type": "strategy",
        "label": primary_label or recommended_next_question or "Ordenar el siguiente criterio de trabajo",
        "reason": "Con lo que ya esta definido, lo mas importante ahora es fijar una direccion clara para que el caso no siga disperso.",
    }


def build_workspace_summary(
    *,
    api_payload: dict[str, Any] | None,
    case_status: str | None = None,
) -> str:
    payload = dict(api_payload or {})
    case_summary = dict(payload.get("case_summary") or {})
    summary_text = str(case_summary.get("summary_text") or "").strip()
    if summary_text:
        return summary_text

    case_progress = dict(payload.get("case_progress") or {})
    case_followup = dict(payload.get("case_followup") or {})
    case_memory = dict(payload.get("case_memory") or {})

    confirmed_count = len(list((case_memory.get("facts") or {}).keys()))
    missing_critical = len(list((case_memory.get("missing") or {}).get("critical") or []))
    contradiction_count = len(list(case_memory.get("contradictions") or []))
    status = str(
        case_status
        or resolve_case_status(case_progress=case_progress, case_followup=case_followup)
    ).strip()
    domain = str(
        payload.get("case_domain")
        or (payload.get("case_profile") or {}).get("case_domain")
        or ""
    ).strip()

    fragments: list[str] = []
    if domain:
        fragments.append(f"Caso de {domain}.")
    if status == "needs_fact_reconciliation":
        fragments.append("Hay datos del caso que requieren validacion antes de consolidar una linea operativa.")
    elif status == "blocked":
        fragments.append("El caso presenta un bloqueo operativo o procesal que limita avanzar con seguridad.")
    elif status == "ready_for_execution":
        fragments.append("La base actual permite pasar a un siguiente paso operativo concreto.")
    elif status == "ready_for_strategy_decision":
        fragments.append("La base actual permite definir una via principal con prudencia.")
    elif status == "needs_information":
        fragments.append("Todavia falta un dato relevante para consolidar el caso.")
    elif status == "structuring_case":
        fragments.append("El caso ya tiene una base inicial y esta en etapa de ordenamiento.")
    else:
        fragments.append("El caso sigue en consolidacion inicial.")

    if confirmed_count:
        fragments.append(f"Hay {confirmed_count} hechos ya registrados.")
    if missing_critical:
        fragments.append(f"Quedan {missing_critical} faltantes criticos.")
    if contradiction_count:
        fragments.append(f"Hay {contradiction_count} contradicciones pendientes de aclaracion.")

    return _normalize_sentence(" ".join(fragment for fragment in fragments if fragment))


def build_professional_handoff(
    *,
    api_payload: dict[str, Any] | None,
    case_status: str,
    operating_phase: str,
    case_summary: str,
    recommended_next_question: str = "",
) -> dict[str, Any]:
    payload = dict(api_payload or {})
    case_progress = dict(payload.get("case_progress") or {})
    case_followup = dict(payload.get("case_followup") or {})

    blocking_issues = [
        dict(item)
        for item in list(case_progress.get("blocking_issues") or [])
        if isinstance(item, dict)
    ]
    critical_gaps = [
        dict(item)
        for item in list(case_progress.get("critical_gaps") or [])
        if isinstance(item, dict)
    ]
    contradictions = [
        dict(item)
        for item in list(case_progress.get("contradictions") or [])
        if isinstance(item, dict)
    ]

    open_items = [
        *[_summarize_contradiction(item) for item in contradictions[:2]],
        *[_humanize_label(item.get("label") or item.get("key")) for item in critical_gaps[:3]],
        *[_humanize_label(item.get("reason") or item.get("key")) for item in blocking_issues[:2]],
    ]
    open_items = [item for item in open_items if item]

    suggested_focus = _resolve_handoff_focus(
        case_status=case_status,
        operating_phase=operating_phase,
        blocking_issues=blocking_issues,
        contradictions=contradictions,
        critical_gaps=critical_gaps,
    )

    handoff_reason = str(case_followup.get("reason") or "").strip()
    if not handoff_reason:
        handoff_reason = _default_handoff_reason(case_status)

    primary_friction = _resolve_primary_friction(
        contradictions=contradictions,
        critical_gaps=critical_gaps,
        blocking_issues=blocking_issues,
    )
    review_readiness = _resolve_review_readiness(
        case_status=case_status,
        operating_phase=operating_phase,
        contradictions=contradictions,
        critical_gaps=critical_gaps,
        blocking_issues=blocking_issues,
    )

    return {
        "ready_for_professional_review": review_readiness in {"reviewable", "decision_ready", "execution_ready"},
        "status": case_status,
        "review_readiness": review_readiness,
        "handoff_reason": handoff_reason,
        "primary_friction": primary_friction,
        "recommended_professional_focus": suggested_focus,
        "professional_entry_point": _resolve_professional_entry_point(
            review_readiness=review_readiness,
            primary_friction=primary_friction,
            suggested_focus=suggested_focus,
        ),
        "suggested_focus": suggested_focus,
        "open_items": open_items,
        "next_question": recommended_next_question,
        "summary_for_professional": case_summary,
    }


def _resolve_case_id(payload: dict[str, Any]) -> str:
    conversation_state = dict(payload.get("conversation_state") or {})
    for candidate in (
        payload.get("conversation_id"),
        conversation_state.get("conversation_id"),
        payload.get("session_id"),
        payload.get("request_id"),
    ):
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return "case-unassigned"


def _build_confirmed_facts(case_memory: dict[str, Any]) -> list[dict[str, Any]]:
    facts = dict(case_memory.get("facts") or {})
    items: list[dict[str, Any]] = []
    for key, value in facts.items():
        fact = dict(value or {})
        items.append(
            {
                "key": str(key),
                "label": _humanize_label(key),
                "value": fact.get("value"),
                "source": str(fact.get("source") or ""),
                "confidence": _safe_float_or_none(fact.get("confidence")),
                "category": "",
                "priority": "",
                "purpose": "",
            }
        )
    return sorted(items, key=lambda item: (-float(item.get("confidence") or 0.0), item["key"]))


def _build_missing_facts(case_memory: dict[str, Any]) -> list[dict[str, Any]]:
    missing = dict(case_memory.get("missing") or {})
    items: list[dict[str, Any]] = []
    for category in ("critical", "important", "optional"):
        for raw_item in list(missing.get(category) or []):
            item = dict(raw_item or {})
            key = str(item.get("key") or item.get("fact_key") or item.get("need_key") or "").strip()
            if not key:
                continue
            items.append(
                {
                    "key": _canonical_key(key),
                    "label": _humanize_label(item.get("label") or key),
                    "value": None,
                    "source": str(item.get("source") or "case_memory"),
                    "confidence": None,
                    "category": category,
                    "priority": str(item.get("priority") or "").strip().lower(),
                    "purpose": str(item.get("purpose") or item.get("category") or "").strip().lower(),
                }
            )
    return sorted(items, key=_missing_fact_sort_key)


def _build_conflicting_facts(case_memory: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_item in list(case_memory.get("contradictions") or []):
        item = dict(raw_item or {})
        key = _canonical_key(item.get("key") or item.get("fact_key"))
        if not key:
            continue
        items.append(
            {
                "key": key,
                "label": _humanize_label(key),
                "prev_value": item.get("prev_value"),
                "new_value": item.get("new_value"),
                "detected_at": _safe_int_or_none(item.get("detected_at")),
            }
        )
    return items


def _build_strategy_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    smart_strategy = dict(payload.get("smart_strategy") or {})
    composition = dict(payload.get("strategy_composition_profile") or {})
    language = dict(payload.get("strategy_language_profile") or {})
    progression = dict(payload.get("progression_policy") or {})

    return {
        "strategy_mode": str(smart_strategy.get("strategy_mode") or payload.get("strategy_mode") or "").strip(),
        "response_goal": str(smart_strategy.get("response_goal") or "").strip(),
        "reason": str(smart_strategy.get("reason") or "").strip(),
        "output_mode": str(progression.get("output_mode") or payload.get("output_mode") or "").strip(),
        "recommended_tone": str(language.get("tone_style") or smart_strategy.get("recommended_tone") or "").strip(),
        "recommended_structure": str(smart_strategy.get("recommended_structure") or "").strip(),
        "allow_followup": bool(composition.get("allow_followup")),
        "prioritize_action": bool(composition.get("prioritize_action") or smart_strategy.get("should_prioritize_action")),
    }


def _build_risk_alerts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    case_progress = dict(payload.get("case_progress") or {})

    for blocker in list(case_progress.get("blocking_issues") or []):
        issue = dict(blocker or {})
        reason = str(issue.get("reason") or issue.get("key") or "").strip()
        if not reason:
            continue
        alerts.append(
            {
                "type": str(issue.get("type") or "blocking_issue"),
                "severity": str(issue.get("severity") or "medium"),
                "message": _normalize_sentence(reason),
                "source": str(issue.get("source") or "case_progress"),
            }
        )

    contradictions = list(case_progress.get("contradictions") or [])
    if contradictions:
        alerts.append(
            {
                "type": "fact_conflict",
                "severity": "high",
                "message": "Hay hechos contradictorios que conviene aclarar antes de consolidar el caso.",
                "source": "case_memory",
            }
        )

    if bool(payload.get("fallback_used")):
        alerts.append(
            {
                "type": "internal_fallback",
                "severity": "medium",
                "message": "La orientacion incluye fallback interno y requiere prudencia reforzada.",
                "source": "postprocessor",
            }
        )

    return alerts[:5]


def _resolve_handoff_focus(
    *,
    case_status: str,
    operating_phase: str,
    blocking_issues: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    critical_gaps: list[dict[str, Any]],
) -> str:
    if contradictions or case_status == "needs_fact_reconciliation":
        return "Resolver primero que version factica conviene sostener antes de fijar una linea profesional mas cerrada."
    if blocking_issues or case_status == "blocked":
        return "Revisar primero el bloqueo procesal u operativo que hoy impide recomendar un movimiento mas claro."
    if critical_gaps or operating_phase == "clarify":
        return "Cerrar primero el faltante critico dominante antes de profundizar la estrategia o sugerir ejecucion."
    if operating_phase == "decide" or case_status == "ready_for_strategy_decision":
        return "Definir la via principal y justificar por que las alternativas secundarias quedan relegadas."
    if operating_phase == "execute" or case_status == "ready_for_execution":
        return "Confirmar el paso inmediato, la competencia y el soporte documental minimo antes de ejecutar."
    if case_status == "substantive_review":
        return "Aprovechar la base actual para una revision sustantiva mas completa y accionable."
    return "Consolidar el estado del caso con la informacion ya disponible."


def _resolve_professional_entry_point(
    *,
    review_readiness: str,
    primary_friction: str,
    suggested_focus: str,
) -> str:
    if review_readiness == "needs_reconciliation":
        return "Definir que version factica conviene sostener como base del caso."
    if review_readiness in {"limited", "preliminary"}:
        return primary_friction or "Definir el faltante o freno que hoy impide recomendar un paso mas concreto."
    if review_readiness == "decision_ready":
        return "Comparar la via principal con sus alternativas y elegir cual conviene sostener primero."
    if review_readiness == "execution_ready":
        return "Validar el paso inmediato a ejecutar y el respaldo minimo necesario para sostenerlo."
    return suggested_focus or "Entrar por el punto que hoy mas ordena el caso."


def _resolve_primary_friction(
    *,
    contradictions: list[dict[str, Any]],
    critical_gaps: list[dict[str, Any]],
    blocking_issues: list[dict[str, Any]],
) -> str:
    if contradictions:
        return "Hay una inconsistencia factica que hoy domina el caso."
    if critical_gaps:
        label = _humanize_label(critical_gaps[0].get("label") or critical_gaps[0].get("key"))
        return (
            f"Falta cerrar {label} para orientar el caso con mas seguridad."
            if label
            else "Hay un faltante critico que condiciona la orientacion."
        )
    if blocking_issues:
        return _humanize_label(blocking_issues[0].get("reason") or blocking_issues[0].get("key"))
    return "No aparece una friccion dominante adicional con la informacion actual."


def _missing_focus_reason(item: dict[str, Any]) -> str:
    key = str(item.get("key") or "").strip().lower()
    purpose = str(item.get("purpose") or item.get("category") or "").strip().lower()
    if key in {"jurisdiccion", "domicilio_relevante"}:
        return "Esto define la via procesal y condiciona los proximos pasos concretos del caso."
    if purpose == "prove":
        return "Sin este punto, la linea del caso queda mas expuesta y cuesta sostener el paso siguiente con respaldo real."
    if purpose == "quantify":
        return "Esto condiciona el alcance del reclamo y cambia como conviene preparar el caso."
    return "Sin este dato, el siguiente paso puede quedar mal orientado o ser prematuro."


def _resolve_review_readiness(
    *,
    case_status: str,
    operating_phase: str,
    contradictions: list[dict[str, Any]],
    critical_gaps: list[dict[str, Any]],
    blocking_issues: list[dict[str, Any]],
) -> str:
    if contradictions:
        return "needs_reconciliation"
    if blocking_issues or case_status == "blocked":
        return "limited"
    if critical_gaps or operating_phase == "clarify":
        return "preliminary"
    if operating_phase == "execute" or case_status == "ready_for_execution":
        return "execution_ready"
    if operating_phase == "decide" or case_status in {"ready_for_strategy_decision", "substantive_review"}:
        return "decision_ready"
    return "reviewable"


def _default_handoff_reason(case_status: str) -> str:
    reasons = {
        "needs_fact_reconciliation": "Hay una inconsistencia material que conviene resolver antes de avanzar.",
        "blocked": "Existe un bloqueo que limita una recomendacion operativa cerrada.",
        "ready_for_execution": "La base actual ya permite preparar un siguiente paso concreto.",
        "ready_for_strategy_decision": "La base actual ya permite priorizar una via principal.",
        "needs_information": "Todavia falta al menos un dato relevante para consolidar el caso.",
        "structuring_case": "El caso esta en etapa de ordenamiento y consolidacion.",
        "substantive_review": "La base del caso permite una revision profesional mas sustantiva.",
    }
    return reasons.get(case_status, "Estado del caso consolidado con la informacion disponible.")


def _case_status_label(case_status: str) -> str:
    labels = {
        "needs_fact_reconciliation": "Hay que aclarar un dato clave",
        "blocked": "Hay un freno para avanzar",
        "ready_for_execution": "Ya se puede avanzar",
        "ready_for_strategy_decision": "Ya se puede elegir camino",
        "needs_information": "Falta una aclaracion importante",
        "structuring_case": "Estamos ordenando el caso",
        "substantive_review": "Listo para revision mas profunda",
        "intake_in_progress": "Base inicial del caso",
    }
    return labels.get(case_status, _humanize_label(case_status))


def _case_status_helper(case_status: str) -> str:
    helpers = {
        "needs_fact_reconciliation": "Conviene resolver primero la inconsistencia que hoy mas condiciona el caso.",
        "blocked": "Antes del siguiente movimiento conviene ordenar el bloqueo actual.",
        "ready_for_execution": "Ya hay base suficiente para pasar a una accion concreta.",
        "ready_for_strategy_decision": "La informacion disponible ya permite comparar vias con prudencia.",
        "needs_information": "Todavia falta una aclaracion que puede cambiar la orientacion practica.",
        "structuring_case": "Ya hay base util, pero todavia conviene ordenar mejor el caso.",
        "substantive_review": "La base actual ya da para una revision profesional mas completa.",
        "intake_in_progress": "Todavia estamos reuniendo la base minima para orientar el caso.",
    }
    return helpers.get(case_status, "")


def _recommended_phase_label(phase: str) -> str:
    labels = {
        "clarify_facts": "Aclarar hechos",
        "resolve_conflicts": "Resolver conflictos",
        "define_strategy": "Definir estrategia",
        "prepare_action": "Preparar accion",
        "execute_action": "Ejecutar accion",
    }
    return labels.get(phase, _humanize_label(phase))


def _missing_fact_sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    category_rank = {
        "critical": 0,
        "important": 1,
        "optional": 2,
    }.get(str(item.get("category") or "").strip().lower(), 3)
    priority_rank = {
        "critical": 0,
        "high": 0,
        "medium": 1,
        "low": 2,
    }.get(str(item.get("priority") or "").strip().lower(), 3)
    purpose_rank = {
        "identify": 0,
        "prove": 1,
        "quantify": 2,
        "context": 3,
    }.get(str(item.get("purpose") or "").strip().lower(), 4)
    return (
        category_rank,
        priority_rank,
        purpose_rank,
        str(item.get("label") or item.get("key") or "").strip().casefold(),
    )


def _summarize_contradiction(item: dict[str, Any]) -> str:
    key = _humanize_label(item.get("label") or item.get("key"))
    prev_value = str(item.get("prev_value") or "").strip()
    new_value = str(item.get("new_value") or "").strip()
    if key and prev_value and new_value:
        return f"{key}: aparece con dos versiones incompatibles"
    return key


def _humanize_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    return re.sub(r"\s+", " ", text.replace("_", " ").strip())


def _canonical_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _normalize_sentence(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    return text


def _safe_float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _apply_global_workspace_dedup(workspace: dict[str, Any]) -> dict[str, Any]:
    seen_concepts: set[str] = set()
    deduped = dict(workspace)

    action_plan = [
        item for item in list(deduped.get("action_plan") or [])
        if _should_keep_workspace_item(item, seen_concepts, fields=("title", "description"))
    ]
    deduped["action_plan"] = action_plan

    evidence = dict(deduped.get("evidence_checklist") or {})
    deduped["evidence_checklist"] = {
        "critical": [
            item for item in list(evidence.get("critical") or [])
            if _should_keep_workspace_item(item, seen_concepts, fields=("label", "description", "reason"))
        ],
        "recommended": [
            item for item in list(evidence.get("recommended") or [])
            if _should_keep_workspace_item(item, seen_concepts, fields=("label", "description", "reason"))
        ],
        "optional": [
            item for item in list(evidence.get("optional") or [])
            if _should_keep_workspace_item(item, seen_concepts, fields=("label", "description", "reason"))
        ],
    }

    deduped["facts_missing"] = [
        item for item in list(deduped.get("facts_missing") or [])
        if _should_keep_workspace_item(item, seen_concepts, fields=("label", "key"))
    ]

    handoff = dict(deduped.get("professional_handoff") or {})
    handoff["open_items"] = [
        item for item in list(handoff.get("open_items") or [])
        if _should_keep_workspace_item(item, seen_concepts, fields=())
    ]
    deduped["professional_handoff"] = handoff
    return deduped


def _should_keep_workspace_item(
    item: Any,
    seen_concepts: set[str],
    *,
    fields: tuple[str, ...],
) -> bool:
    if isinstance(item, dict):
        text = " ".join(str(item.get(field) or "").strip() for field in fields if str(item.get(field) or "").strip())
    else:
        text = str(item or "").strip()
    concept_key = canonicalize_concept_key(text)
    if not concept_key:
        return True
    if concept_key in seen_concepts:
        return False
    seen_concepts.add(concept_key)
    return True
