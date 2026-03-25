from __future__ import annotations

from typing import Any


def evaluate_operational_risk(recommendation: dict[str, Any] | None) -> dict[str, Any]:
    recommendation = recommendation or {}
    proposed_changes = dict(recommendation.get("proposed_changes") or {})
    event_type = str(recommendation.get("event_type") or "").strip().lower()

    if not proposed_changes:
        return {
            "risk_level": "medium",
            "risk_score": 0.45,
            "reversible": False,
            "blast_radius": "medium",
            "reasoning": "Riesgo operativo medio por falta de detalle sobre el cambio propuesto.",
            "drivers": ["missing_proposed_changes"],
        }

    flattened_paths = _flatten_change_paths(proposed_changes)
    change_count = len(flattened_paths)
    domain_count = _count_domains(proposed_changes)
    drivers: list[str] = [f"change_count={change_count}"]

    additive_only = _is_additive_only(flattened_paths)
    destructive = _is_destructive(flattened_paths)
    sensitive = _is_sensitive_change(event_type, flattened_paths)
    global_scope = _is_global_scope(flattened_paths, proposed_changes)
    multi_domain = domain_count > 1

    if additive_only:
        drivers.append("additive_change")
    if destructive:
        drivers.append("destructive_change")
    if sensitive:
        drivers.append("sensitive_config_change")
    if global_scope:
        drivers.append("global_scope_change")
    if multi_domain:
        drivers.append(f"multi_domain={domain_count}")

    reversible = additive_only and not destructive and not sensitive

    risk_score = 0.20
    if event_type == "threshold_adjustment":
        risk_score += 0.18
    if change_count >= 3:
        risk_score += 0.12
    if change_count >= 6:
        risk_score += 0.10
    if domain_count >= 2:
        risk_score += 0.12
    if domain_count >= 3:
        risk_score += 0.08
    if sensitive:
        risk_score += 0.28
    if global_scope:
        risk_score += 0.22
    if destructive:
        risk_score += 0.18
    if additive_only:
        risk_score -= 0.08

    risk_score = round(max(0.0, min(1.0, risk_score)), 4)
    risk_level = _classify_risk_level(risk_score)
    blast_radius = _classify_blast_radius(
        change_count=change_count,
        domain_count=domain_count,
        global_scope=global_scope,
        sensitive=sensitive,
    )
    reasoning = _build_reasoning(
        risk_level=risk_level,
        reversible=reversible,
        blast_radius=blast_radius,
        drivers=drivers,
    )

    return {
        "risk_level": risk_level,
        "risk_score": risk_score,
        "reversible": reversible,
        "blast_radius": blast_radius,
        "reasoning": reasoning,
        "drivers": drivers,
    }


def _flatten_change_paths(payload: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, value in payload.items():
        normalized_key = str(key or "").strip().lower()
        current = f"{prefix}.{normalized_key}" if prefix else normalized_key
        if isinstance(value, dict):
            nested = _flatten_change_paths(value, current)
            paths.extend(nested or [current])
        elif isinstance(value, list):
            if value:
                for item in value:
                    paths.append(f"{current}:{str(item or '').strip().lower()}")
            else:
                paths.append(current)
        else:
            paths.append(current)
    return paths


def _count_domains(proposed_changes: dict[str, Any]) -> int:
    domains: set[str] = set()
    for key in ("prefer_hybrid_domains_add", "force_full_pipeline_domains_add"):
        for item in proposed_changes.get(key, []) or []:
            normalized = str(item or "").strip().lower()
            if normalized:
                domains.add(normalized)
    classification_review = dict(proposed_changes.get("classification_review") or {})
    for field in ("from_domain", "to_domain"):
        normalized = str(classification_review.get(field) or "").strip().lower()
        if normalized:
            domains.add(normalized)
    return len(domains)


def _is_additive_only(paths: list[str]) -> bool:
    if not paths:
        return False
    additive_tokens = ("_add", ".add", "append", "enable")
    return all(any(token in path for token in additive_tokens) for path in paths)


def _is_destructive(paths: list[str]) -> bool:
    destructive_tokens = ("remove", "delete", "reset", "clear", "replace", "overwrite", "disable")
    return any(any(token in path for token in destructive_tokens) for path in paths)


def _is_sensitive_change(event_type: str, paths: list[str]) -> bool:
    sensitive_tokens = ("threshold", "confidence", "decision_confidence", "fallback", "routing", "global")
    return event_type == "threshold_adjustment" or any(
        any(token in path for token in sensitive_tokens) for path in paths
    )


def _is_global_scope(paths: list[str], proposed_changes: dict[str, Any]) -> bool:
    if any("all" in path or "global" in path or "default" in path for path in paths):
        return True
    if "threshold_review" in proposed_changes:
        return True
    return False


def _classify_risk_level(risk_score: float) -> str:
    if risk_score >= 0.7:
        return "high"
    if risk_score >= 0.4:
        return "medium"
    return "low"


def _classify_blast_radius(
    *,
    change_count: int,
    domain_count: int,
    global_scope: bool,
    sensitive: bool,
) -> str:
    if global_scope or sensitive or domain_count >= 4 or change_count >= 6:
        return "large"
    if domain_count >= 2 or change_count >= 3:
        return "medium"
    return "small"


def _build_reasoning(
    *,
    risk_level: str,
    reversible: bool,
    blast_radius: str,
    drivers: list[str],
) -> str:
    reversibility = "reversible" if reversible else "non_reversible_or_sensitive"
    return (
        f"Riesgo operativo {risk_level} con blast_radius={blast_radius} "
        f"y cambio {reversibility}. Drivers: {', '.join(drivers[:4])}"
    )
