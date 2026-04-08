from __future__ import annotations

from typing import Any


STAGES = (
    "exploracion",
    "estructuracion",
    "decision",
    "ejecucion",
    "bloqueado",
    "inconsistente",
)

READINESS_LABELS = ("low", "medium", "high")
PROGRESS_STATUS_VALUES = ("initial", "advancing", "stalled", "ready", "blocked")
NEXT_STEP_TYPES = ("ask", "orient", "decide", "execute", "resolve_contradiction")
PROGRESS_DELTAS = ("positive", "neutral", "negative", "unknown")

_STRONG_BLOCKING_VALUES = {
    "blocked",
    "block",
    "bloqueado",
    "service",
    "procedural_block",
    "procesal",
    "high",
    "critical",
}
_NONE_VALUES = {"", "none", "no", "false", "normal", "ok", "n/a", "na"}
_CORE_PATTERNS = (
    "hay_hijos",
    "vinculo",
    "rol_procesal",
    "convivencia",
    "ingresos",
    "domicilio",
    "jurisdic",
    "notificacion",
    "modalidad_divorcio",
    "competencia",
    "dni",
    "nombre",
)
_EXECUTION_STRATEGIES = {"action_first", "guide_next_step"}
_READINESS_CAP_ONE_CONTRADICTION = 0.55
_READINESS_CAP_MULTI_CONTRADICTION = 0.4


def build_case_progress(
    *,
    case_memory: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    case_state_snapshot: dict[str, Any] | None,
    api_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    basis = _collect_progress_basis(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
    )
    blockers = detect_progress_blockers(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        basis=basis,
    )
    readiness_level = compute_case_readiness(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        basis=basis,
        blockers=blockers,
    )
    readiness_label = _readiness_label(readiness_level)
    stage = resolve_case_stage(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        basis=basis,
        blockers=blockers,
        readiness_level=readiness_level,
    )
    next_step_type = _resolve_next_step_type(
        stage=stage,
        readiness_level=readiness_level,
        blockers=blockers,
        basis=basis,
    )

    progress: dict[str, Any] = {
        "stage": stage,
        "readiness_level": readiness_level,
        "readiness_label": readiness_label,
        "progress_status": _resolve_progress_status(
            stage=stage,
            readiness_level=readiness_level,
            basis=basis,
            blockers=blockers,
        ),
        "blocking_issues": blockers["blocking_issues"],
        "critical_gaps": blockers["critical_gaps"],
        "important_gaps": blockers["important_gaps"],
        "contradictions": blockers["contradictions"],
        "contradiction_count": blockers["contradiction_count"],
        "has_contradictions": blockers["has_contradictions"],
        "next_step_type": next_step_type,
        "progress_delta": "unknown",
        "basis": {
            "confirmed_fact_count": basis["confirmed_fact_count"],
            "total_fact_count": basis["total_fact_count"],
            "missing_critical_count": basis["missing_critical_count"],
            "missing_important_count": basis["missing_important_count"],
            "contradiction_count": basis["contradiction_count"],
            "memory_confidence": basis["memory_confidence"],
            "blocking_factor": basis["blocking_factor"],
            "progress_state": basis["progress_state"],
            "output_mode": basis["output_mode"],
            "strategy_mode": basis["strategy_mode"],
            "has_execution_steps": basis["has_execution_steps"],
            "should_ask_followup": basis["should_ask_followup"],
            "contradictions": basis["contradictions"],
        },
    }
    progress["progress_delta"] = detect_progress_delta(
        current_progress=progress,
        previous_progress=basis["previous_progress"],
        basis=basis,
    )
    return progress


def resolve_progress_behavior_intent(case_progress: dict[str, Any] | None) -> dict[str, Any]:
    """
    Condensa señales de case_progress en intenciones operativas nombradas.

    Consumido por smart_strategy_service y case_followup_service para evitar
    que cada uno extraiga e interprete señales de forma independiente,
    reduciendo el riesgo de divergencia entre follow-up y estrategia.

    No replica toda la lógica del pipeline: solo centraliza las señales
    más sensibles que hoy se duplican o pueden divergir.

    Returns:
    {
        "stage": str,
        "next_step_type": str,
        "progress_status": str,
        "readiness_label": str,
        "has_critical_gaps": bool,
        "has_blockers": bool,
        "has_important_gaps": bool,
        "has_contradictions": bool,
        "has_strong_blocker": bool,
        "has_non_blocking_critical_gaps": bool,
        "has_high_impact_important_gaps": bool,
        "should_prioritize_contradiction": bool,
        "should_block_execution": bool,
        "should_allow_execution": bool,
        "should_reduce_followup": bool,
        "should_allow_decision_followup": bool,
    }
    """
    p = dict(case_progress or {})
    stage = _normalized_choice(p.get("stage"), STAGES, "")
    readiness_label = str(p.get("readiness_label") or "").strip().lower()
    next_step_type = _normalized_choice(p.get("next_step_type"), NEXT_STEP_TYPES, "")
    progress_status = _normalized_choice(p.get("progress_status"), PROGRESS_STATUS_VALUES, "")
    critical_gaps = _as_list(p.get("critical_gaps"))
    important_gaps = _as_list(p.get("important_gaps"))
    blocking_issues = _as_list(p.get("blocking_issues"))
    contradiction_count = _safe_int(p.get("contradiction_count"))

    has_critical_gaps = bool(critical_gaps)
    has_blockers = bool(blocking_issues)
    has_important_gaps = bool(important_gaps)
    has_contradictions = contradiction_count > 0

    # Bloqueador fuerte: stage bloqueado/inconsistente o cualquier blocking_issue de severidad alta
    has_strong_blocker = (
        stage in {"bloqueado", "inconsistente"}
        or (has_blockers and any(
            str(_as_dict(b).get("severity") or "").strip().lower() == "high"
            for b in blocking_issues
        ))
    )

    # Gaps críticos que NO bloquean la ejecución: hay datos sensibles pendientes
    # pero el sistema puede seguir avanzando (sin strong blocker, sin stage bloqueado)
    has_non_blocking_critical_gaps = (
        has_critical_gaps
        and not has_strong_blocker
        and stage not in {"bloqueado", "inconsistente"}
    )

    # Faltantes importantes con alto impacto estratégico (sin critical gaps):
    # al menos uno tiene purpose/category procesal, estrategia, identify o enable
    has_high_impact_important_gaps = (
        has_important_gaps
        and not has_critical_gaps
        and any(
            str(_as_dict(item).get("purpose") or _as_dict(item).get("category") or "").strip().lower()
            in {"procesal", "estrategia", "identify", "enable"}
            for item in important_gaps
            if isinstance(item, dict)
        )
    )

    return {
        # Signals
        "stage": stage,
        "next_step_type": next_step_type,
        "progress_status": progress_status,
        "readiness_label": readiness_label,
        "has_critical_gaps": has_critical_gaps,
        "has_blockers": has_blockers,
        "has_important_gaps": has_important_gaps,
        "has_contradictions": has_contradictions,
        "has_strong_blocker": has_strong_blocker,
        "has_non_blocking_critical_gaps": has_non_blocking_critical_gaps,
        "has_high_impact_important_gaps": has_high_impact_important_gaps,
        # Named operational intents
        "should_prioritize_contradiction": next_step_type == "resolve_contradiction" and has_contradictions,
        "should_block_execution": has_strong_blocker,
        "should_allow_execution": (
            stage == "ejecucion"
            and readiness_label == "high"
            and not has_strong_blocker
            and next_step_type != "resolve_contradiction"
        ),
        "should_reduce_followup": (
            stage in {"decision", "ejecucion"}
            and not has_critical_gaps
            and not has_strong_blocker
        ),
        # Excepción controlada: en decision sin critical gaps pero con faltante estratégico relevante,
        # se permite una única pregunta estratégica útil
        "should_allow_decision_followup": (
            stage == "decision"
            and not has_critical_gaps
            and has_high_impact_important_gaps
            and not has_strong_blocker
        ),
    }


def extract_case_progress_snapshot(case_progress: dict[str, Any] | None) -> dict[str, Any]:
    progress = dict(case_progress or {})
    critical_gaps = _as_list(progress.get("critical_gaps"))
    important_gaps = _as_list(progress.get("important_gaps"))
    blocking_issues = _as_list(progress.get("blocking_issues"))
    return {
        "stage": _normalized_choice(progress.get("stage"), STAGES, "exploracion"),
        "readiness_label": _readiness_label(_safe_float(progress.get("readiness_level"))),
        "progress_status": _normalized_choice(progress.get("progress_status"), PROGRESS_STATUS_VALUES, "initial"),
        "next_step_type": _normalized_choice(progress.get("next_step_type"), NEXT_STEP_TYPES, "ask"),
        "critical_gap_count": len(critical_gaps),
        "important_gap_count": len(important_gaps),
        "blocking_issue_count": len(blocking_issues),
        "contradiction_count": _safe_int(progress.get("contradiction_count")),
        "has_contradictions": bool(progress.get("has_contradictions")),
        "progress_delta": _normalized_choice(progress.get("progress_delta"), PROGRESS_DELTAS, "unknown"),
    }


def resolve_case_stage(
    *,
    case_memory: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    case_state_snapshot: dict[str, Any] | None,
    api_payload: dict[str, Any] | None = None,
    basis: dict[str, Any] | None = None,
    blockers: dict[str, Any] | None = None,
    readiness_level: float | None = None,
) -> str:
    computed_basis = basis or _collect_progress_basis(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
    )
    computed_blockers = blockers or detect_progress_blockers(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        basis=computed_basis,
    )
    readiness = _clamp(readiness_level if readiness_level is not None else compute_case_readiness(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        basis=computed_basis,
        blockers=computed_blockers,
    ))

    contradiction_count = computed_blockers["contradiction_count"]
    if contradiction_count >= 2 or (
        contradiction_count >= 1 and _has_relevant_contradiction(computed_basis["contradictions"])
    ):
        return "inconsistente"

    if computed_blockers["has_strong_blocker"] and readiness < 0.8:
        return "bloqueado"

    if readiness >= 0.82 and not computed_blockers["critical_gaps"] and not computed_blockers["has_strong_blocker"]:
        return "ejecucion"

    if (
        computed_basis["confirmed_fact_count"] >= 3
        and computed_basis["total_fact_count"] >= 4
        and computed_basis["missing_critical_count"] == 0
        and computed_basis["contradiction_count"] == 0
        and (readiness >= 0.56 or computed_basis["decision_signal"])
    ):
        return "decision"

    if (
        computed_basis["confirmed_fact_count"] >= 2
        or computed_basis["total_fact_count"] >= 3
        or computed_basis["missing_important_count"] > 0
    ):
        return "estructuracion"

    return "exploracion"


def compute_case_readiness(
    *,
    case_memory: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    case_state_snapshot: dict[str, Any] | None,
    api_payload: dict[str, Any] | None = None,
    basis: dict[str, Any] | None = None,
    blockers: dict[str, Any] | None = None,
) -> float:
    computed_basis = basis or _collect_progress_basis(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
    )
    computed_blockers = blockers or detect_progress_blockers(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        basis=computed_basis,
    )

    confirmed_fact_count = computed_basis["confirmed_fact_count"]
    total_fact_count = computed_basis["total_fact_count"]
    probable_fact_count = max(0, total_fact_count - confirmed_fact_count)

    score = 0.0
    score += min(0.5, confirmed_fact_count * 0.12)
    score += min(0.12, probable_fact_count * 0.03)
    score += _memory_confidence_bonus(computed_basis["memory_confidence"])
    score += _case_confidence_bonus(computed_basis["case_confidence_score"])
    score += _completeness_bonus(computed_basis["case_completeness"])

    score -= min(0.54, computed_basis["missing_critical_count"] * 0.18)
    score -= min(0.18, computed_basis["missing_important_count"] * 0.05)
    score -= min(0.5, computed_basis["contradiction_count"] * 0.22)
    if computed_blockers["has_strong_blocker"]:
        score -= 0.2
    if computed_basis["should_ask_followup"] and computed_basis["missing_critical_count"] > 0:
        score -= 0.1

    if computed_basis["has_execution_steps"] and computed_basis["missing_critical_count"] == 0:
        score += 0.08
    if computed_basis["decision_signal"] and computed_basis["missing_critical_count"] == 0:
        score += 0.05

    score = _apply_contradiction_readiness_cap(
        score=score,
        contradiction_count=computed_basis["contradiction_count"],
    )
    return round(_clamp(score), 3)


def detect_progress_blockers(
    *,
    case_memory: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    case_state_snapshot: dict[str, Any] | None,
    api_payload: dict[str, Any] | None = None,
    basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    computed_basis = basis or _collect_progress_basis(
        case_memory=case_memory,
        conversation_state=conversation_state,
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
    )

    critical_gaps = [_normalize_gap(item) for item in computed_basis["critical_gaps"]]
    important_gaps = [_normalize_gap(item) for item in computed_basis["important_gaps"]]
    contradictions = [_normalize_contradiction(item) for item in computed_basis["contradictions"]]
    blocking_issues: list[dict[str, Any]] = []

    if computed_basis["blocking_factor"] and computed_basis["blocking_factor"] not in _NONE_VALUES:
        blocking_issues.append(
            {
                "type": "blocking_factor",
                "severity": "high",
                "source": "pipeline",
                "key": computed_basis["blocking_factor"],
                "reason": f"blocking_factor={computed_basis['blocking_factor']}",
            }
        )
    if computed_basis["progress_state"] == "blocked":
        blocking_issues.append(
            {
                "type": "progress_state",
                "severity": "high",
                "source": "conversation_state",
                "key": "progress_state",
                "reason": "conversation progress is marked as blocked",
            }
        )
    if computed_basis["user_cannot_answer"]:
        blocking_issues.append(
            {
                "type": "user_constraint",
                "severity": "medium",
                "source": "case_followup",
                "key": "user_cannot_answer",
                "reason": "user cannot currently provide the blocking detail",
            }
        )
    if computed_basis["detected_loop"]:
        blocking_issues.append(
            {
                "type": "conversation_loop",
                "severity": "medium",
                "source": "case_followup",
                "key": "detected_loop",
                "reason": "recent follow-up loop detected",
            }
        )
    if contradictions:
        blocking_issues.append(
            {
                "type": "contradictions",
                "severity": "high" if len(contradictions) >= 2 or _has_relevant_contradiction(contradictions) else "medium",
                "source": "case_memory",
                "key": "contradictions",
                "reason": f"{len(contradictions)} contradiction(s) detected",
            }
        )

    return {
        "blocking_issues": blocking_issues,
        "critical_gaps": critical_gaps,
        "important_gaps": important_gaps,
        "contradictions": contradictions,
        "contradiction_count": len(contradictions),
        "has_contradictions": bool(contradictions),
        "has_strong_blocker": any(
            item.get("severity") == "high"
            for item in blocking_issues
        ),
    }


def detect_progress_delta(
    *,
    current_progress: dict[str, Any] | None,
    previous_progress: dict[str, Any] | None,
    basis: dict[str, Any] | None = None,
) -> str:
    current = dict(current_progress or {})
    previous = dict(previous_progress or {})
    if not previous:
        return "unknown"

    current_basis = dict(current.get("basis") or basis or {})
    previous_basis = dict(previous.get("basis") or {})

    current_confirmed = _safe_int(current_basis.get("confirmed_fact_count"))
    previous_confirmed = _safe_int(previous_basis.get("confirmed_fact_count"))
    current_missing = _safe_int(current_basis.get("missing_critical_count"))
    previous_missing = _safe_int(previous_basis.get("missing_critical_count"))
    current_contradictions = _safe_int(current.get("contradiction_count"))
    previous_contradictions = _safe_int(previous.get("contradiction_count"))
    current_readiness = _safe_float(current.get("readiness_level"))
    previous_readiness = _safe_float(previous.get("readiness_level"))

    if current_contradictions > previous_contradictions:
        return "negative"
    if current_missing > previous_missing:
        return "negative"
    if current_readiness <= previous_readiness - 0.08:
        return "negative"

    if current_confirmed > previous_confirmed:
        return "positive"
    if current_missing < previous_missing:
        return "positive"
    if current_readiness >= previous_readiness + 0.08:
        return "positive"

    return "neutral"


def _collect_progress_basis(
    *,
    case_memory: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    case_state_snapshot: dict[str, Any] | None,
    api_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    memory = dict(case_memory or {})
    state = dict(conversation_state or {})
    snapshot = dict(case_state_snapshot or {})
    payload = dict(api_payload or {})
    progress_signals = _as_dict(state.get("progress_signals"))
    case_followup = _as_dict(payload.get("case_followup"))
    case_confidence = _as_dict(payload.get("case_confidence"))
    progression_policy = _as_dict(payload.get("progression_policy"))
    smart_strategy = _as_dict(payload.get("smart_strategy"))

    facts = _build_facts_map(memory=memory, state=state, snapshot=snapshot)
    missing = _resolve_missing(memory=memory, snapshot=snapshot)
    contradictions = _resolve_contradictions(memory=memory, snapshot=snapshot)

    confirmed_fact_count = sum(
        1 for data in facts.values()
        if _safe_float(_as_dict(data).get("confidence"), default=1.0) >= 0.9
    )
    if not facts and _safe_int(progress_signals.get("known_fact_count")) > 0:
        confirmed_fact_count = _safe_int(progress_signals.get("core_fact_count")) or _safe_int(progress_signals.get("known_fact_count"))
    total_fact_count = len(facts) or _safe_int(progress_signals.get("known_fact_count"))

    critical_gaps = _as_list(missing.get("critical"))
    important_gaps = _as_list(missing.get("important"))
    if not critical_gaps and not important_gaps:
        derived_critical, derived_important = _derive_missing_from_open_needs(snapshot)
        critical_gaps = critical_gaps or derived_critical
        important_gaps = important_gaps or derived_important

    blocking_factor = _resolve_blocking_factor(payload=payload, snapshot=snapshot, state=state)
    progress_state = _resolve_progress_state(state=state, payload=payload)
    output_mode = str(
        progression_policy.get("output_mode")
        or payload.get("output_mode")
        or ""
    ).strip().lower()
    strategy_mode = str(smart_strategy.get("strategy_mode") or "").strip().lower()
    has_execution_steps = _has_execution_steps(payload)
    should_ask_followup = bool(case_followup.get("should_ask"))
    case_completeness = str(progress_signals.get("case_completeness") or "").strip().lower()

    return {
        "confirmed_fact_count": confirmed_fact_count,
        "total_fact_count": total_fact_count,
        "missing_critical_count": len(critical_gaps),
        "missing_important_count": len(important_gaps),
        "critical_gaps": critical_gaps,
        "important_gaps": important_gaps,
        "contradiction_count": len(contradictions),
        "contradictions": contradictions,
        "memory_confidence": str(memory.get("memory_confidence") or "low").strip().lower() or "low",
        "blocking_factor": blocking_factor,
        "progress_state": progress_state,
        "output_mode": output_mode,
        "strategy_mode": strategy_mode,
        "has_execution_steps": has_execution_steps,
        "should_ask_followup": should_ask_followup,
        "case_confidence_score": _safe_float(case_confidence.get("confidence_score")),
        "case_completeness": case_completeness,
        "decision_signal": bool(
            progression_policy.get("decision_required")
            or output_mode == "estrategia"
            or strategy_mode == "substantive_analysis"
        ),
        "previous_progress": _as_dict(state.get("case_progress")),
        "user_cannot_answer": bool(case_followup.get("user_cannot_answer") or state.get("user_cannot_answer")),
        "detected_loop": bool(case_followup.get("detected_loop") or state.get("detected_loop")),
    }


def _resolve_next_step_type(
    *,
    stage: str,
    readiness_level: float,
    blockers: dict[str, Any],
    basis: dict[str, Any],
) -> str:
    if blockers["contradiction_count"] >= 1 and _has_relevant_contradiction(blockers["contradictions"]):
        return "resolve_contradiction"
    if blockers["has_strong_blocker"]:
        return "ask"
    if blockers["critical_gaps"]:
        return "ask"
    if stage == "ejecucion" or (readiness_level >= 0.82 and not blockers["has_strong_blocker"]):
        return "execute"
    if stage == "decision" or basis["decision_signal"]:
        return "decide"
    return "orient"


def _resolve_progress_status(
    *,
    stage: str,
    readiness_level: float,
    basis: dict[str, Any],
    blockers: dict[str, Any],
) -> str:
    if stage in {"bloqueado", "inconsistente"} or blockers["has_strong_blocker"]:
        return "blocked"
    if basis["missing_critical_count"] > 0:
        return "stalled"
    if readiness_level >= 0.82 and not blockers["critical_gaps"]:
        return "ready"
    if basis["confirmed_fact_count"] == 0 and basis["total_fact_count"] == 0:
        return "initial"
    return "advancing"


def _build_facts_map(
    *,
    memory: dict[str, Any],
    state: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    facts = {
        str(key): dict(value)
        for key, value in _as_dict(memory.get("facts")).items()
        if str(key).strip()
    }
    if facts:
        return facts

    result: dict[str, dict[str, Any]] = {}
    for key, value in _as_dict(snapshot.get("probable_facts")).items():
        normalized = _canonical_key(key)
        if normalized:
            result[normalized] = {"value": value, "confidence": 0.6, "source": "probable"}
    for key, value in _as_dict(snapshot.get("confirmed_facts")).items():
        normalized = _canonical_key(key)
        if normalized:
            result[normalized] = {"value": value, "confidence": 1.0, "source": "confirmed"}
    for item in _as_list(state.get("known_facts")):
        item_data = _as_dict(item)
        normalized = _canonical_key(item_data.get("key") or item_data.get("fact_key"))
        if normalized and normalized not in result:
            result[normalized] = {
                "value": item_data.get("value"),
                "confidence": 1.0 if str(item_data.get("status") or "").strip().lower() == "confirmed" else 0.5,
                "source": str(item_data.get("source") or "state"),
            }
    return result


def _resolve_missing(
    *,
    memory: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    raw_missing = _as_dict(memory.get("missing"))
    if raw_missing:
        return {
            "critical": [_as_dict(item) for item in _as_list(raw_missing.get("critical")) if _as_dict(item)],
            "important": [_as_dict(item) for item in _as_list(raw_missing.get("important")) if _as_dict(item)],
            "optional": [_as_dict(item) for item in _as_list(raw_missing.get("optional")) if _as_dict(item)],
        }
    critical, important = _derive_missing_from_open_needs(snapshot)
    return {
        "critical": critical,
        "important": important,
        "optional": [],
    }


def _derive_missing_from_open_needs(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    critical: list[dict[str, Any]] = []
    important: list[dict[str, Any]] = []
    for item in _as_list(snapshot.get("open_needs")):
        need = _as_dict(item)
        if not need:
            continue
        normalized = _normalize_gap(need)
        priority = str(need.get("priority") or "").strip().lower()
        if priority in {"critical", "high"}:
            critical.append(normalized)
        else:
            important.append(normalized)
    return critical, important


def _resolve_contradictions(
    *,
    memory: dict[str, Any],
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    raw = _as_list(memory.get("contradictions")) or _as_list(snapshot.get("contradictions"))
    return [_normalize_contradiction(item) for item in raw if _as_dict(item)]


def _resolve_blocking_factor(
    *,
    payload: dict[str, Any],
    snapshot: dict[str, Any],
    state: dict[str, Any],
) -> str:
    procedural = _as_dict(payload.get("procedural_case_state"))
    case_state = _as_dict(snapshot.get("case_state"))
    progress_signals = _as_dict(state.get("progress_signals"))
    for candidate in (
        payload.get("blocking_factor"),
        procedural.get("blocking_factor"),
        case_state.get("blocking_factor"),
        progress_signals.get("blocking_factor"),
    ):
        normalized = str(candidate or "").strip().lower()
        if normalized:
            return normalized
    if bool(progress_signals.get("blocking_missing")):
        return "blocking_missing"
    return "none"


def _resolve_progress_state(*, state: dict[str, Any], payload: dict[str, Any]) -> str:
    case_followup = _as_dict(payload.get("case_followup"))
    progress_signals = _as_dict(state.get("progress_signals"))
    for candidate in (
        case_followup.get("adaptive_progress_state"),
        state.get("progress_state"),
        progress_signals.get("progress_state"),
    ):
        normalized = str(candidate or "").strip().lower()
        if normalized in {"initial", "advancing", "stalled", "blocked", "complete", "ready"}:
            return normalized
    return "advancing"


def _normalize_gap(item: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(item)
    key = _canonical_key(data.get("key") or data.get("fact_key") or data.get("need_key"))
    return {
        "key": key,
        "label": str(data.get("label") or data.get("reason") or data.get("suggested_question") or key).strip(),
        "priority": str(data.get("priority") or "medium").strip().lower(),
        "purpose": str(data.get("purpose") or data.get("category") or "").strip().lower(),
        "source": str(data.get("source") or "case_memory").strip().lower(),
    }


def _normalize_contradiction(item: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(item)
    return {
        "key": _canonical_key(data.get("key") or data.get("fact_key")),
        "prev_value": data.get("prev_value") if "prev_value" in data else data.get("stored_value"),
        "new_value": data.get("new_value") if "new_value" in data else data.get("incoming_value"),
        "detected_at": _safe_int(data.get("detected_at")),
    }


def _memory_confidence_bonus(value: str) -> float:
    normalized = str(value or "").strip().lower()
    if normalized == "high":
        return 0.14
    if normalized == "medium":
        return 0.08
    return 0.02


def _case_confidence_bonus(value: float) -> float:
    score = _clamp(value)
    return round(score * 0.12, 3)


def _completeness_bonus(value: str) -> float:
    normalized = str(value or "").strip().lower()
    if normalized == "high":
        return 0.08
    if normalized == "medium":
        return 0.04
    return 0.0


def _has_execution_steps(payload: dict[str, Any]) -> bool:
    execution_output = _as_dict(payload.get("execution_output"))
    execution_data = _as_dict(execution_output.get("execution_output"))
    actions = [item for item in _as_list(execution_data.get("what_to_do_now")) if str(item or "").strip()]
    where_to_go = [item for item in _as_list(execution_data.get("where_to_go")) if str(item or "").strip()]
    documents = [item for item in _as_list(execution_data.get("documents_needed")) if str(item or "").strip()]
    requests = [item for item in _as_list(execution_data.get("what_to_request")) if str(item or "").strip()]
    if len(actions) >= 2:
        return True
    return bool(actions and (where_to_go or documents or requests or execution_output.get("applies")))


def _has_relevant_contradiction(contradictions: list[dict[str, Any]]) -> bool:
    for item in contradictions:
        key = _canonical_key(_as_dict(item).get("key"))
        if any(pattern in key for pattern in _CORE_PATTERNS):
            return True
    return False


def _readiness_label(value: float) -> str:
    score = _clamp(value)
    if score >= 0.72:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _apply_contradiction_readiness_cap(*, score: float, contradiction_count: int) -> float:
    if contradiction_count >= 2:
        return min(score, _READINESS_CAP_MULTI_CONTRADICTION)
    if contradiction_count >= 1:
        return min(score, _READINESS_CAP_ONE_CONTRADICTION)
    return score


def _normalized_choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _canonical_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []
