# backend/app/services/auto_healing_constants.py
"""
Constantes centralizadas para auto-healing.

Single source of truth para umbrales, allowlist de acciones,
taxonomía de situaciones y configuración de recuperación.
"""

from __future__ import annotations

# ─── Situaciones (de menor a mayor severidad) ────────────────────────────────

SITUATION_NORMAL = "normal"
SITUATION_DEGRADED = "degraded"
SITUATION_UNSTABLE = "unstable"
SITUATION_CRITICAL = "critical"
SITUATION_RECOVERING = "recovering"

SITUATION_SEVERITY_RANK: dict[str, int] = {
    SITUATION_NORMAL: 0,
    SITUATION_RECOVERING: 1,
    SITUATION_DEGRADED: 2,
    SITUATION_UNSTABLE: 3,
    SITUATION_CRITICAL: 4,
}

ALL_SITUATIONS: set[str] = set(SITUATION_SEVERITY_RANK.keys())

# ─── Acciones permitidas (allowlist explícita) ───────────────────────────────

ACTION_ACTIVATE_PROTECTIVE = "activate_protective_mode"
ACTION_HARDEN_PROTECTIVE = "harden_protective_mode"
ACTION_RECOMMEND_REVIEW_REQUIRED = "recommend_review_required"
ACTION_ENFORCE_REVIEW_REQUIRED = "enforce_review_required"
ACTION_RECOMMEND_MANUAL_ONLY = "recommend_manual_only"
ACTION_SUSPEND_AUTO_TUNING = "suspend_auto_tuning"
ACTION_RELAX_PROTECTIVE = "relax_protective_mode"
ACTION_RECOMMEND_AUTO = "recommend_auto_mode"

ALLOWED_ACTIONS: set[str] = {
    ACTION_ACTIVATE_PROTECTIVE,
    ACTION_HARDEN_PROTECTIVE,
    ACTION_RECOMMEND_REVIEW_REQUIRED,
    ACTION_ENFORCE_REVIEW_REQUIRED,
    ACTION_RECOMMEND_MANUAL_ONLY,
    ACTION_SUSPEND_AUTO_TUNING,
    ACTION_RELAX_PROTECTIVE,
    ACTION_RECOMMEND_AUTO,
}

# Acciones que se aplican automáticamente (el resto solo se recomiendan)
AUTO_APPLY_ACTIONS: set[str] = {
    ACTION_ACTIVATE_PROTECTIVE,
    ACTION_HARDEN_PROTECTIVE,
    ACTION_ENFORCE_REVIEW_REQUIRED,
    ACTION_SUSPEND_AUTO_TUNING,
    ACTION_RELAX_PROTECTIVE,
}

# Acciones que solo se recomiendan (nunca auto-apply)
RECOMMEND_ONLY_ACTIONS: set[str] = {
    ACTION_RECOMMEND_REVIEW_REQUIRED,
    ACTION_RECOMMEND_MANUAL_ONLY,
    ACTION_RECOMMEND_AUTO,
}

# ─── Acciones prohibidas (jamás automáticas) ─────────────────────────────────

FORBIDDEN_AUTO_ACTIONS: set[str] = {
    "lift_frozen",
    "disable_hard_safety",
    "relax_critical_guardrails",
    "force_auto_from_frozen",
    "bypass_human_override",
    "delete_safety_events",
}

# ─── Umbrales de señales para clasificación ──────────────────────────────────

# Degraded thresholds (umbral mínimo para degraded)
DEGRADED_FALLBACK_COUNT = 3
DEGRADED_ERROR_COUNT = 2
DEGRADED_REJECTED_COUNT = 3
DEGRADED_STALE_REVIEWS = 2

# Unstable thresholds
UNSTABLE_FALLBACK_COUNT = 6
UNSTABLE_ERROR_COUNT = 4
UNSTABLE_REJECTED_COUNT = 5
UNSTABLE_HIGH_PRIORITY_REVIEWS = 3
UNSTABLE_STALE_REVIEWS = 4

# Critical thresholds
CRITICAL_ERROR_COUNT = 7
CRITICAL_FALLBACK_COUNT = 10
CRITICAL_REJECTED_COUNT = 8

# ─── Configuración de recuperación ───────────────────────────────────────────

# Recuperación requiere más evidencia que degradación (asimetría)
RECOVERY_CONSECUTIVE_EVALUATIONS = 3  # cuántas evaluaciones consecutivas "mejorando" se necesitan
RECOVERY_MAX_ERROR_COUNT = 1  # máximo de errores permitidos durante recuperación
RECOVERY_MAX_FALLBACK_COUNT = 2  # máximo de fallbacks permitidos durante recuperación
RECOVERY_MAX_STALE_REVIEWS = 1  # máximo de reviews stale durante recuperación

# Cooldown: mínimo de segundos entre evaluaciones auto-healing
EVALUATION_COOLDOWN_SECONDS = 60

# ─── Confianza de decisiones ─────────────────────────────────────────────────

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# Confianza mínima para auto-apply de acciones
MIN_CONFIDENCE_FOR_AUTO_APPLY = CONFIDENCE_HIGH

# ─── Acciones por situación ──────────────────────────────────────────────────
# Mapeo de situación → acciones permitidas (en orden de prioridad)

SITUATION_ACTION_MAP: dict[str, list[str]] = {
    SITUATION_NORMAL: [],
    SITUATION_RECOVERING: [
        ACTION_RELAX_PROTECTIVE,
        ACTION_RECOMMEND_AUTO,
    ],
    SITUATION_DEGRADED: [
        ACTION_ACTIVATE_PROTECTIVE,
        ACTION_RECOMMEND_REVIEW_REQUIRED,
    ],
    SITUATION_UNSTABLE: [
        ACTION_ACTIVATE_PROTECTIVE,
        ACTION_HARDEN_PROTECTIVE,
        ACTION_ENFORCE_REVIEW_REQUIRED,
        ACTION_SUSPEND_AUTO_TUNING,
    ],
    SITUATION_CRITICAL: [
        ACTION_HARDEN_PROTECTIVE,
        ACTION_ENFORCE_REVIEW_REQUIRED,
        ACTION_SUSPEND_AUTO_TUNING,
        ACTION_RECOMMEND_MANUAL_ONLY,
    ],
}

# ─── Override duración por defecto (ciclos de self-tuning) ───────────────────

AUTO_HEALING_OVERRIDE_DURATION_CYCLES = 5
AUTO_HEALING_ACTOR_TAG = "auto_healing_system"

# ─── Precedencia ─────────────────────────────────────────────────────────────
# hard_safety > human_control > auto_healing

MODES_THAT_BLOCK_AUTO_HEALING: set[str] = {"frozen"}
MODES_THAT_BLOCK_RELAXATION: set[str] = {"frozen", "manual_only"}
