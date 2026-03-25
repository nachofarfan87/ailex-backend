from __future__ import annotations


SELF_TUNING_DEFAULTS = {
    "apply_confidence_delta": 0.0,
    "min_sample_size_delta": 0,
    "uncertain_apply_confidence_min": 0.15,
    "uncertain_apply_max_simulation_risk": 0.45,
}

SELF_TUNING_HUMAN_CONTROL_DEFAULTS = {
    "system_mode": "auto",
    "active_overrides": [],
}


RUNTIME_CONFIG = {
    "prefer_hybrid_domains": set(),
    "force_full_pipeline_domains": set(),
    "thresholds": {
        "low_confidence": 0.5,
        "low_decision_confidence": 0.5,
    },
    "self_tuning_controls": dict(SELF_TUNING_DEFAULTS),
    "self_tuning_human_control": dict(SELF_TUNING_HUMAN_CONTROL_DEFAULTS),
}


def add_prefer_hybrid_domain(domain: str) -> None:
    normalized = str(domain or "").strip().lower()
    if normalized:
        RUNTIME_CONFIG["prefer_hybrid_domains"].add(normalized)


def add_force_full_pipeline_domain(domain: str) -> None:
    normalized = str(domain or "").strip().lower()
    if normalized:
        RUNTIME_CONFIG["force_full_pipeline_domains"].add(normalized)


def update_threshold(key: str, value: float) -> None:
    normalized_key = str(key or "").strip()
    if not normalized_key:
        raise ValueError("threshold_key_required")
    RUNTIME_CONFIG["thresholds"][normalized_key] = float(value)


def set_self_tuning_control(key: str, value) -> None:
    normalized_key = str(key or "").strip()
    if normalized_key not in SELF_TUNING_DEFAULTS:
        raise ValueError("unknown_self_tuning_control")
    if normalized_key == "min_sample_size_delta":
        RUNTIME_CONFIG["self_tuning_controls"][normalized_key] = int(value)
    else:
        RUNTIME_CONFIG["self_tuning_controls"][normalized_key] = float(value)


def get_self_tuning_controls() -> dict:
    return dict(RUNTIME_CONFIG["self_tuning_controls"])


def get_self_tuning_human_control() -> dict:
    payload = dict(RUNTIME_CONFIG["self_tuning_human_control"])
    payload["active_overrides"] = list(payload.get("active_overrides") or [])
    return payload


def get_self_tuning_system_mode() -> str:
    return str(RUNTIME_CONFIG["self_tuning_human_control"].get("system_mode") or "auto")


def set_self_tuning_system_mode(mode: str) -> None:
    normalized_mode = str(mode or "").strip().lower()
    if not normalized_mode:
        raise ValueError("system_mode_required")
    RUNTIME_CONFIG["self_tuning_human_control"]["system_mode"] = normalized_mode


def get_active_self_tuning_overrides() -> list[dict]:
    return list(RUNTIME_CONFIG["self_tuning_human_control"].get("active_overrides") or [])


def set_active_self_tuning_overrides(overrides: list[dict] | None) -> None:
    RUNTIME_CONFIG["self_tuning_human_control"]["active_overrides"] = list(overrides or [])


def get_runtime_config() -> dict:
    return {
        "prefer_hybrid_domains": sorted(RUNTIME_CONFIG["prefer_hybrid_domains"]),
        "force_full_pipeline_domains": sorted(RUNTIME_CONFIG["force_full_pipeline_domains"]),
        "thresholds": dict(RUNTIME_CONFIG["thresholds"]),
    }


def get_persistable_runtime_config() -> dict:
    return {
        **get_runtime_config(),
        "self_tuning_controls": get_self_tuning_controls(),
        "self_tuning_human_control": get_self_tuning_human_control(),
    }


def apply_persisted_runtime_config(config: dict | None) -> None:
    reset_runtime_config()
    config = dict(config or {})
    for domain in config.get("prefer_hybrid_domains", []):
        add_prefer_hybrid_domain(domain)
    for domain in config.get("force_full_pipeline_domains", []):
        add_force_full_pipeline_domain(domain)
    for key, value in config.get("thresholds", {}).items():
        update_threshold(key, value)
    for key, value in dict(config.get("self_tuning_controls") or {}).items():
        set_self_tuning_control(key, value)
    human_control = dict(config.get("self_tuning_human_control") or {})
    if human_control:
        set_self_tuning_system_mode(human_control.get("system_mode") or "auto")
        set_active_self_tuning_overrides(list(human_control.get("active_overrides") or []))


def get_effective_runtime_config() -> dict:
    return {
        **get_runtime_config(),
        "self_tuning_controls": get_self_tuning_controls(),
        "self_tuning_human_control": get_self_tuning_human_control(),
    }


def reset_runtime_config() -> None:
    RUNTIME_CONFIG["prefer_hybrid_domains"].clear()
    RUNTIME_CONFIG["force_full_pipeline_domains"].clear()
    RUNTIME_CONFIG["thresholds"].clear()
    RUNTIME_CONFIG["thresholds"].update(
        {
            "low_confidence": 0.5,
            "low_decision_confidence": 0.5,
        }
    )
    RUNTIME_CONFIG["self_tuning_controls"].clear()
    RUNTIME_CONFIG["self_tuning_controls"].update(dict(SELF_TUNING_DEFAULTS))
    RUNTIME_CONFIG["self_tuning_human_control"].clear()
    RUNTIME_CONFIG["self_tuning_human_control"].update(dict(SELF_TUNING_HUMAN_CONTROL_DEFAULTS))
