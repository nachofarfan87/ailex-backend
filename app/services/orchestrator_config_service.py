from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from legal_engine.orchestrator_config import OrchestratorAdaptiveConfig


_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "orchestrator_adaptive_config.json"
_AMBIGUITY_THRESHOLD_BOUNDS = (0.05, 0.5)
_LOW_CONFIDENCE_THRESHOLD_BOUNDS = (0.3, 0.85)
_LOW_DECISION_CONFIDENCE_THRESHOLD_BOUNDS = (0.3, 0.85)
_MANUAL_REVIEW_THRESHOLD_BOUNDS = (0.3, 0.9)
_STRATEGY_WEIGHT_BOUNDS = (0.0, 5.0)
_MAX_DOMAIN_ADDITIONS = 5


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _resolve_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else _CONFIG_PATH


def _normalize_domains(items: list[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items or []:
        normalized = str(item or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _semantic_config_dict(config: OrchestratorAdaptiveConfig | dict[str, Any]) -> dict[str, Any]:
    normalized = config if isinstance(config, OrchestratorAdaptiveConfig) else OrchestratorAdaptiveConfig.from_dict(config)
    payload = normalized.to_dict()
    return {
        "ambiguity_threshold": float(payload["ambiguity_threshold"]),
        "manual_review_threshold": float(payload["manual_review_threshold"]),
        "low_confidence_threshold": float(payload["low_confidence_threshold"]),
        "low_decision_confidence_threshold": float(payload["low_decision_confidence_threshold"]),
        "prefer_hybrid_domains": _normalize_domains(payload.get("prefer_hybrid_domains")),
        "force_full_pipeline_domains": _normalize_domains(payload.get("force_full_pipeline_domains")),
        "strategy_weights": {
            str(key): float(value)
            for key, value in sorted((payload.get("strategy_weights") or {}).items())
        },
    }


def _validate_threshold(name: str, value: float, bounds: tuple[float, float]) -> None:
    minimum, maximum = bounds
    if value < minimum or value > maximum:
        raise ValueError(f"{name} debe estar entre {minimum} y {maximum}.")


def load_orchestrator_config(path: str | Path | None = None) -> OrchestratorAdaptiveConfig:
    config_path = _resolve_path(path)
    default_config = OrchestratorAdaptiveConfig.default_config()

    if not config_path.exists():
        return save_orchestrator_config(default_config, path=config_path)

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        return OrchestratorAdaptiveConfig.from_dict(payload)
    except (OSError, ValueError, TypeError):
        return save_orchestrator_config(default_config, path=config_path)


def validate_orchestrator_config_change(
    current_config: OrchestratorAdaptiveConfig | dict[str, Any],
    proposed_config: OrchestratorAdaptiveConfig | dict[str, Any],
) -> None:
    current = current_config if isinstance(current_config, OrchestratorAdaptiveConfig) else OrchestratorAdaptiveConfig.from_dict(current_config)
    proposed = proposed_config if isinstance(proposed_config, OrchestratorAdaptiveConfig) else OrchestratorAdaptiveConfig.from_dict(proposed_config)

    _validate_threshold("ambiguity_threshold", float(proposed.ambiguity_threshold), _AMBIGUITY_THRESHOLD_BOUNDS)
    _validate_threshold("low_confidence_threshold", float(proposed.low_confidence_threshold), _LOW_CONFIDENCE_THRESHOLD_BOUNDS)
    _validate_threshold(
        "low_decision_confidence_threshold",
        float(proposed.low_decision_confidence_threshold),
        _LOW_DECISION_CONFIDENCE_THRESHOLD_BOUNDS,
    )
    _validate_threshold("manual_review_threshold", float(proposed.manual_review_threshold), _MANUAL_REVIEW_THRESHOLD_BOUNDS)

    for key, value in dict(proposed.strategy_weights or {}).items():
        numeric_value = float(value)
        if numeric_value < _STRATEGY_WEIGHT_BOUNDS[0]:
            raise ValueError(f"strategy_weights.{key} no puede ser negativo.")
        if numeric_value > _STRATEGY_WEIGHT_BOUNDS[1]:
            raise ValueError(
                f"strategy_weights.{key} debe estar entre {_STRATEGY_WEIGHT_BOUNDS[0]} y {_STRATEGY_WEIGHT_BOUNDS[1]}."
            )

    current_semantic = _semantic_config_dict(current)
    proposed_semantic = _semantic_config_dict(proposed)
    added_domains = (
        len(set(proposed_semantic["prefer_hybrid_domains"]) - set(current_semantic["prefer_hybrid_domains"]))
        + len(set(proposed_semantic["force_full_pipeline_domains"]) - set(current_semantic["force_full_pipeline_domains"]))
    )
    if added_domains > _MAX_DOMAIN_ADDITIONS:
        raise ValueError(f"No se pueden agregar más de {_MAX_DOMAIN_ADDITIONS} dominios en un solo cambio.")

    if proposed_semantic == current_semantic:
        raise ValueError("El cambio propuesto no modifica la configuración adaptativa.")


def save_orchestrator_config(
    config: OrchestratorAdaptiveConfig | dict[str, Any],
    path: str | Path | None = None,
) -> OrchestratorAdaptiveConfig:
    config_path = _resolve_path(path)
    _ensure_parent(config_path)

    normalized = config if isinstance(config, OrchestratorAdaptiveConfig) else OrchestratorAdaptiveConfig.from_dict(config)
    payload = normalized.to_dict()
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["version"] = str(payload.get("version") or "v1")
    saved = OrchestratorAdaptiveConfig.from_dict(payload)

    config_path.write_text(json.dumps(saved.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return saved
