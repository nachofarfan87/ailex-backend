from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.user_models import User
from app.models.learning_human_audit import LearningHumanAuditLog
from app.services import learning_runtime_config
from app.services.learning_runtime_config_store import save_runtime_config
from app.services.self_tuning_constants import TUNABLE_PARAMETER_SPECS
from app.services.utc import utc_now


SELF_TUNING_SYSTEM_MODES = {"auto", "review_required", "manual_only", "frozen"}
HARD_BLOCK_PREFIXES = ("guardrail_", "safety_envelope_", "meta_historically_risky_parameter")
OVERRIDE_EXPIRING_SOON_CYCLES = 2


def get_system_mode() -> str:
    return learning_runtime_config.get_self_tuning_system_mode()


def set_system_mode(
    db: Session,
    *,
    mode: str,
    actor: User | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in SELF_TUNING_SYSTEM_MODES:
        raise ValueError("invalid_system_mode")
    before_state = learning_runtime_config.get_self_tuning_human_control()
    learning_runtime_config.set_self_tuning_system_mode(normalized_mode)
    save_runtime_config(db, learning_runtime_config.get_effective_runtime_config())
    _record_human_audit(
        db,
        actor=actor,
        action_type="set_system_mode",
        target_type="system_mode",
        target_id=normalized_mode,
        before_state=before_state,
        after_state=learning_runtime_config.get_self_tuning_human_control(),
        notes=notes,
    )
    db.commit()
    return learning_runtime_config.get_self_tuning_human_control()


def get_active_overrides() -> list[dict[str, Any]]:
    return list(learning_runtime_config.get_active_self_tuning_overrides())


def get_active_override_summary(overrides: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    active_overrides = list(overrides if overrides is not None else get_active_overrides())
    override_count_by_type: dict[str, int] = {}
    overridden_parameters: list[str] = []
    forced_actions_active: list[str] = []
    expiring_overrides: list[dict[str, Any]] = []
    remaining_cycles_total = 0
    finite_remaining_cycles = 0

    for override in active_overrides:
        override_type = str(override.get("override_type") or "unknown")
        override_count_by_type[override_type] = override_count_by_type.get(override_type, 0) + 1

        parameter_name = str(override.get("parameter_name") or "").strip()
        if parameter_name:
            overridden_parameters.append(parameter_name)

        forced_action = str(override.get("forced_action") or "").strip()
        if forced_action:
            forced_actions_active.append(forced_action)

        remaining_cycles = override.get("remaining_cycles")
        if remaining_cycles is not None:
            finite_remaining_cycles += 1
            remaining_cycles_total += int(remaining_cycles)
            if int(remaining_cycles) <= OVERRIDE_EXPIRING_SOON_CYCLES:
                expiring_overrides.append(
                    {
                        "id": override.get("id"),
                        "override_type": override_type,
                        "parameter_name": override.get("parameter_name"),
                        "forced_action": override.get("forced_action"),
                        "remaining_cycles": int(remaining_cycles),
                    }
                )

    return {
        "total_active_overrides": len(active_overrides),
        "override_count_by_type": override_count_by_type,
        "overridden_parameters": sorted(set(overridden_parameters)),
        "forced_actions_active": sorted(set(forced_actions_active)),
        "expiring_overrides": expiring_overrides,
        "remaining_cycles_total": remaining_cycles_total,
        "finite_remaining_cycles_count": finite_remaining_cycles,
    }


def create_override(
    db: Session,
    *,
    override_type: str,
    parameter_name: str | None = None,
    forced_action: str | None = None,
    duration_cycles: int | None = None,
    reason: str | None = None,
    actor: User | None = None,
) -> dict[str, Any]:
    normalized_type = str(override_type or "").strip().lower()
    if normalized_type not in {"freeze_parameter", "block_parameter", "force_action"}:
        raise ValueError("invalid_override_type")
    if normalized_type in {"freeze_parameter", "block_parameter"} and not str(parameter_name or "").strip():
        raise ValueError("parameter_name_required")
    if normalized_type == "force_action" and str(forced_action or "").strip().lower() not in {
        "apply",
        "simulate",
        "observe_only",
        "block",
    }:
        raise ValueError("forced_action_required")

    override = {
        "id": str(uuid4()),
        "override_type": normalized_type,
        "parameter_name": str(parameter_name or "").strip() or None,
        "forced_action": str(forced_action or "").strip().lower() or None,
        "remaining_cycles": max(int(duration_cycles), 1) if duration_cycles else None,
        "reason": str(reason or "").strip() or None,
        "created_at": utc_now().isoformat(),
        "created_by_user_id": getattr(actor, "id", None),
        "created_by_email": getattr(actor, "email", None),
    }
    before_state = learning_runtime_config.get_self_tuning_human_control()
    overrides = get_active_overrides()
    overrides.append(override)
    learning_runtime_config.set_active_self_tuning_overrides(overrides)
    save_runtime_config(db, learning_runtime_config.get_effective_runtime_config())
    _record_human_audit(
        db,
        actor=actor,
        action_type="create_override",
        target_type="self_tuning_override",
        target_id=override["id"],
        before_state=before_state,
        after_state=override,
        notes=reason,
        override_id=override["id"],
    )
    db.commit()
    return override


def clear_override(
    db: Session,
    *,
    override_id: str,
    actor: User | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    overrides = get_active_overrides()
    before_state = learning_runtime_config.get_self_tuning_human_control()
    remaining = [item for item in overrides if str(item.get("id") or "") != override_id]
    if len(remaining) == len(overrides):
        raise ValueError("override_not_found")
    learning_runtime_config.set_active_self_tuning_overrides(remaining)
    save_runtime_config(db, learning_runtime_config.get_effective_runtime_config())
    _record_human_audit(
        db,
        actor=actor,
        action_type="clear_override",
        target_type="self_tuning_override",
        target_id=override_id,
        before_state=before_state,
        after_state=learning_runtime_config.get_self_tuning_human_control(),
        notes=notes,
        override_id=override_id,
    )
    db.commit()
    return learning_runtime_config.get_self_tuning_human_control()


def evaluate_active_overrides(
    db: Session,
    *,
    recommendation: dict[str, Any],
    resolved_action: str,
    meta_snapshot: dict[str, Any],
) -> dict[str, Any]:
    overrides = get_active_overrides()
    if not overrides:
        return {
            "recommendation": recommendation,
            "final_action": resolved_action,
            "applied_overrides": [],
            "blocked_overrides": [],
            "overrides_active": 0,
            "active_override_summary": get_active_override_summary([]),
        }

    updated_recommendation = copy.deepcopy(recommendation)
    final_action = str(resolved_action or "observe_only")
    applied_overrides: list[dict[str, Any]] = []
    blocked_overrides: list[dict[str, Any]] = []
    remaining_overrides: list[dict[str, Any]] = []

    for override in overrides:
        current = dict(override)
        matched = False
        override_type = str(current.get("override_type") or "")
        parameter_name = str(current.get("parameter_name") or "")

        if override_type in {"freeze_parameter", "block_parameter"}:
            for candidate in updated_recommendation.get("candidate_adjustments") or []:
                if str(candidate.get("parameter_name") or "") != parameter_name:
                    continue
                candidate["blocked"] = True
                blocked_reasons = list(candidate.get("blocked_reasons") or [])
                blocked_reasons.append(
                    "human_override_parameter_frozen"
                    if override_type == "freeze_parameter"
                    else "human_override_parameter_blocked"
                )
                candidate["blocked_reasons"] = list(dict.fromkeys(blocked_reasons))
                explanation = dict(candidate.get("explanation") or {})
                why_not = list(explanation.get("why_not") or [])
                why_not.append(str(current.get("reason") or override_type))
                explanation["why_not"] = list(dict.fromkeys(why_not))
                candidate["explanation"] = explanation
                matched = True
        elif override_type == "force_action":
            forced_action = str(current.get("forced_action") or "").strip().lower()
            if _can_force_action(
                forced_action=forced_action,
                current_action=final_action,
                meta_snapshot=meta_snapshot,
                recommendation=updated_recommendation,
            ):
                final_action = forced_action
                matched = True
            else:
                blocked_overrides.append(
                    {
                        "override_id": current.get("id"),
                        "override_type": override_type,
                        "reason": "unsafe_override_rejected",
                    }
                )

        if matched:
            applied_overrides.append(current)
            next_override = _consume_override_cycle(current)
            if next_override is not None:
                remaining_overrides.append(next_override)
        else:
            remaining_overrides.append(current)

    if remaining_overrides != overrides:
        learning_runtime_config.set_active_self_tuning_overrides(remaining_overrides)
        save_runtime_config(db, learning_runtime_config.get_effective_runtime_config())
        db.commit()

    updated_recommendation["blocked_reasons"] = _merge_blocked_reasons(
        list(updated_recommendation.get("blocked_reasons") or []),
        list(updated_recommendation.get("candidate_adjustments") or []),
    )
    if final_action == "apply" and not any(
        not candidate.get("blocked") for candidate in updated_recommendation.get("candidate_adjustments") or []
    ):
        final_action = "block"

    return {
        "recommendation": updated_recommendation,
        "final_action": final_action,
        "applied_overrides": applied_overrides,
        "blocked_overrides": blocked_overrides,
        "overrides_active": len(remaining_overrides),
        "active_override_summary": get_active_override_summary(remaining_overrides),
    }


def get_human_interventions_last_24h(db: Session) -> int:
    return (
        db.query(LearningHumanAuditLog)
        .filter(LearningHumanAuditLog.created_at >= utc_now() - timedelta(hours=24))
        .count()
    )


def _consume_override_cycle(override: dict[str, Any]) -> dict[str, Any] | None:
    remaining_cycles = override.get("remaining_cycles")
    if remaining_cycles is None:
        return override
    next_remaining = int(remaining_cycles) - 1
    if next_remaining <= 0:
        return None
    updated = dict(override)
    updated["remaining_cycles"] = next_remaining
    return updated


def _can_force_action(
    *,
    forced_action: str,
    current_action: str,
    meta_snapshot: dict[str, Any],
    recommendation: dict[str, Any],
) -> bool:
    meta_action = str(meta_snapshot.get("recommended_action") or current_action or "observe_only")
    if meta_action == "block" and forced_action in {"apply", "simulate"}:
        return False
    if forced_action == "apply" and any(
        _has_hard_safety_block(candidate)
        for candidate in recommendation.get("candidate_adjustments") or []
    ):
        return False
    return forced_action in {"apply", "simulate", "observe_only", "block"}


def _has_hard_safety_block(candidate: dict[str, Any]) -> bool:
    return any(
        str(reason).startswith(HARD_BLOCK_PREFIXES)
        for reason in candidate.get("blocked_reasons") or []
    )


def _merge_blocked_reasons(original: list[str], candidates: list[dict[str, Any]]) -> list[str]:
    merged = list(original)
    for candidate in candidates:
        merged.extend(list(candidate.get("blocked_reasons") or []))
    return list(dict.fromkeys(merged))


def _record_human_audit(
    db: Session,
    *,
    actor: User | None,
    action_type: str,
    target_type: str,
    target_id: str | None,
    before_state: Any,
    after_state: Any,
    notes: str | None = None,
    review_id: str | None = None,
    override_id: str | None = None,
) -> LearningHumanAuditLog:
    entry = LearningHumanAuditLog(
        review_id=review_id,
        override_id=override_id,
        user_id=getattr(actor, "id", None),
        user_email=getattr(actor, "email", None),
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        notes=notes,
        before_state_json=json_dumps(before_state),
        after_state_json=json_dumps(after_state),
    )
    db.add(entry)
    return entry


def json_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload, default=str)


def apply_manual_delta_override(
    *,
    recommendation: dict[str, Any],
    parameter_name: str,
    forced_delta: float,
) -> dict[str, Any]:
    updated = copy.deepcopy(recommendation)
    target_found = False
    for candidate in updated.get("candidate_adjustments") or []:
        if str(candidate.get("parameter_name") or "") != parameter_name:
            continue
        spec = dict(TUNABLE_PARAMETER_SPECS.get(parameter_name) or {})
        if not spec:
            raise ValueError("unknown_override_parameter")
        max_shift = float(spec.get("guardrails", {}).get("max_daily_shift") or 0.0)
        if max_shift > 0 and abs(float(forced_delta)) > max_shift:
            raise ValueError("unsafe_override_delta")
        current_value = float(candidate.get("current_value") or 0.0)
        min_value = float(spec.get("min_value"))
        max_value = float(spec.get("max_value"))
        new_value = max(min_value, min(max_value, current_value + float(forced_delta)))
        if spec.get("kind") == "int":
            candidate["strategy_effective_delta"] = int(round(forced_delta))
            candidate["strategy_effective_proposed_value"] = int(round(new_value))
        else:
            candidate["strategy_effective_delta"] = round(float(forced_delta), 4)
            candidate["strategy_effective_proposed_value"] = round(float(new_value), 4)
        explanation = dict(candidate.get("explanation") or {})
        why = list(explanation.get("why") or [])
        why.append("manual human override adjusted candidate delta")
        explanation["why"] = list(dict.fromkeys(why))
        candidate["explanation"] = explanation
        target_found = True
        break
    if not target_found:
        raise ValueError("override_parameter_not_found")
    return updated
