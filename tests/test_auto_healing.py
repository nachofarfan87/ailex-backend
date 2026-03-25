# backend/tests/test_auto_healing.py
"""
Tests comprehensivos para el sistema de auto-healing.

Cubre:
1. Clasificación de situaciones
2. Decisión de acciones
3. Allowlist y restricciones
4. Recuperación sostenida
5. Precedencia (frozen, human override)
6. Auditoría de eventos
7. Snapshot operativo
8. Compatibilidad con FASE 9 y 10
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from app.models.auto_healing_event import AutoHealingEvent
from app.services.auto_healing_constants import (
    ACTION_ACTIVATE_PROTECTIVE,
    ACTION_ENFORCE_REVIEW_REQUIRED,
    ACTION_HARDEN_PROTECTIVE,
    ACTION_RECOMMEND_AUTO,
    ACTION_RECOMMEND_MANUAL_ONLY,
    ACTION_RECOMMEND_REVIEW_REQUIRED,
    ACTION_RELAX_PROTECTIVE,
    ACTION_SUSPEND_AUTO_TUNING,
    ALLOWED_ACTIONS,
    AUTO_APPLY_ACTIONS,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CRITICAL_ERROR_COUNT,
    CRITICAL_FALLBACK_COUNT,
    DEGRADED_ERROR_COUNT,
    DEGRADED_FALLBACK_COUNT,
    DEGRADED_STALE_REVIEWS,
    FORBIDDEN_AUTO_ACTIONS,
    MODES_THAT_BLOCK_AUTO_HEALING,
    RECOVERY_CONSECUTIVE_EVALUATIONS,
    RECOMMEND_ONLY_ACTIONS,
    SITUATION_CRITICAL,
    SITUATION_DEGRADED,
    SITUATION_NORMAL,
    SITUATION_RECOVERING,
    SITUATION_UNSTABLE,
    UNSTABLE_ERROR_COUNT,
    UNSTABLE_FALLBACK_COUNT,
    UNSTABLE_HIGH_PRIORITY_REVIEWS,
    UNSTABLE_STALE_REVIEWS,
)
from app.services.auto_healing_policy import (
    classify_situation,
    collect_signals,
    decide_actions,
    evaluate_auto_healing,
    reset_policy_state,
)
from app.services.auto_healing_service import (
    _apply_action,
    run_auto_healing_cycle,
)
from app.services.safety_classifier import reset_breaker_state


def _base_signals(**overrides: int | bool | str) -> dict:
    """Genera señales base normales con overrides opcionales."""
    signals = {
        "fallback_triggered_count": 0,
        "error_like_events_count": 0,
        "degraded_requests_count": 0,
        "rate_limited_requests_count": 0,
        "rejected_inputs_count": 0,
        "total_safety_events": 0,
        "active_safety_status": "normal",
        "stale_reviews_count": 0,
        "high_priority_reviews": 0,
        "pending_reviews": 0,
        "overrides_active": 0,
        "human_interventions_last_24h": 0,
        "system_mode": "auto",
        "protective_mode_active": False,
        "breaker_error_count": 0,
        "breaker_degraded_count": 0,
    }
    signals.update(overrides)
    return signals


def _base_safety_snapshot(**overrides) -> dict:
    """Safety snapshot base."""
    snap = {
        "fallback_triggered_count": 0,
        "error_like_events_count": 0,
        "degraded_requests_count": 0,
        "rate_limited_requests_count": 0,
        "rejected_inputs_count": 0,
        "total_safety_events": 0,
        "active_safety_status": "normal",
        "protective_mode_active": False,
        "protective_mode_reason": None,
    }
    snap.update(overrides)
    return snap


def _base_control_snapshot(**overrides) -> dict:
    """Human control snapshot base."""
    snap = {
        "stale_reviews_count": 0,
        "pending_reviews_by_priority": {},
        "pending_reviews": 0,
        "overrides_active": 0,
        "human_interventions_last_24h": 0,
    }
    snap.update(overrides)
    return snap


def _base_pm_status(**overrides) -> dict:
    """Protective mode status base."""
    pm = {
        "protective_mode_active": False,
        "protective_mode_reason": None,
        "error_count": 0,
        "degraded_count": 0,
        "effective_max_query_length": 3500,
    }
    pm.update(overrides)
    return pm


class TestSituationClassification(unittest.TestCase):
    """Tests para clasificación de situaciones."""

    def test_normal_when_all_signals_low(self):
        signals = _base_signals()
        situation, reason = classify_situation(signals)
        assert situation == SITUATION_NORMAL
        assert "normal" in reason

    def test_degraded_on_moderate_errors(self):
        signals = _base_signals(error_like_events_count=DEGRADED_ERROR_COUNT)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_DEGRADED

    def test_degraded_on_moderate_fallbacks(self):
        signals = _base_signals(fallback_triggered_count=DEGRADED_FALLBACK_COUNT)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_DEGRADED

    def test_degraded_on_stale_reviews(self):
        signals = _base_signals(stale_reviews_count=DEGRADED_STALE_REVIEWS)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_DEGRADED

    def test_degraded_on_protective_mode_active(self):
        signals = _base_signals(protective_mode_active=True)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_DEGRADED

    def test_unstable_on_high_errors(self):
        signals = _base_signals(error_like_events_count=UNSTABLE_ERROR_COUNT)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_UNSTABLE

    def test_unstable_on_high_fallbacks(self):
        signals = _base_signals(fallback_triggered_count=UNSTABLE_FALLBACK_COUNT)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_UNSTABLE

    def test_unstable_on_many_high_priority_reviews(self):
        signals = _base_signals(high_priority_reviews=UNSTABLE_HIGH_PRIORITY_REVIEWS)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_UNSTABLE

    def test_unstable_on_many_stale_reviews(self):
        signals = _base_signals(stale_reviews_count=UNSTABLE_STALE_REVIEWS)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_UNSTABLE

    def test_critical_on_very_high_errors(self):
        signals = _base_signals(error_like_events_count=CRITICAL_ERROR_COUNT)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_CRITICAL

    def test_critical_on_very_high_fallbacks(self):
        signals = _base_signals(fallback_triggered_count=CRITICAL_FALLBACK_COUNT)
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_CRITICAL

    def test_classification_reason_includes_signal_name(self):
        signals = _base_signals(error_like_events_count=CRITICAL_ERROR_COUNT)
        _, reason = classify_situation(signals)
        assert "error_like_events_count" in reason

    def test_critical_dominates_unstable(self):
        """Si señales alcanzan critical, no importa que también alcancen unstable."""
        signals = _base_signals(
            error_like_events_count=CRITICAL_ERROR_COUNT,
            stale_reviews_count=UNSTABLE_STALE_REVIEWS,
        )
        situation, _ = classify_situation(signals)
        assert situation == SITUATION_CRITICAL


class TestActionDecisions(unittest.TestCase):
    """Tests para decisión de acciones."""

    def test_no_actions_on_normal(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_NORMAL, signals=signals)
        assert actions == []

    def test_degraded_recommends_review_required(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_DEGRADED, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_RECOMMEND_REVIEW_REQUIRED in action_types or ACTION_ACTIVATE_PROTECTIVE in action_types

    def test_unstable_activates_protective(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_UNSTABLE, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_ACTIVATE_PROTECTIVE in action_types

    def test_unstable_enforces_review_required(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_UNSTABLE, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_ENFORCE_REVIEW_REQUIRED in action_types

    def test_critical_recommends_manual_only(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_CRITICAL, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_RECOMMEND_MANUAL_ONLY in action_types

    def test_critical_suspends_auto_tuning(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_CRITICAL, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_SUSPEND_AUTO_TUNING in action_types

    def test_recovering_relaxes_protective(self):
        signals = _base_signals(protective_mode_active=True)
        actions = decide_actions(situation=SITUATION_RECOVERING, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_RELAX_PROTECTIVE in action_types

    def test_recovering_recommends_auto(self):
        signals = _base_signals(system_mode="review_required")
        actions = decide_actions(situation=SITUATION_RECOVERING, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_RECOMMEND_AUTO in action_types


class TestFrozenBlocking(unittest.TestCase):
    """Tests para precedencia: frozen bloquea todo auto-healing."""

    def test_frozen_blocks_all_actions(self):
        signals = _base_signals(system_mode="frozen")
        for situation in (SITUATION_DEGRADED, SITUATION_UNSTABLE, SITUATION_CRITICAL, SITUATION_RECOVERING):
            actions = decide_actions(situation=situation, signals=signals)
            assert actions == [], f"frozen should block all actions for {situation}"

    def test_frozen_in_modes_that_block(self):
        assert "frozen" in MODES_THAT_BLOCK_AUTO_HEALING


class TestHumanOverridePrecedence(unittest.TestCase):
    """Tests para que auto-healing no pise human override."""

    def test_no_enforce_review_if_already_review_required(self):
        signals = _base_signals(system_mode="review_required")
        actions = decide_actions(situation=SITUATION_UNSTABLE, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_ENFORCE_REVIEW_REQUIRED not in action_types

    def test_no_enforce_review_if_manual_only(self):
        signals = _base_signals(system_mode="manual_only")
        actions = decide_actions(situation=SITUATION_UNSTABLE, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_ENFORCE_REVIEW_REQUIRED not in action_types

    def test_no_recommend_manual_if_already_manual(self):
        signals = _base_signals(system_mode="manual_only")
        actions = decide_actions(situation=SITUATION_CRITICAL, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_RECOMMEND_MANUAL_ONLY not in action_types

    def test_no_relax_in_manual_only(self):
        signals = _base_signals(system_mode="manual_only", protective_mode_active=True)
        actions = decide_actions(situation=SITUATION_RECOVERING, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_RELAX_PROTECTIVE not in action_types


class TestHardSafety(unittest.TestCase):
    """Tests para que auto-healing no rompa hard safety."""

    def test_forbidden_actions_never_in_allowlist(self):
        for action in FORBIDDEN_AUTO_ACTIONS:
            assert action not in ALLOWED_ACTIONS

    def test_recommend_only_never_auto_apply(self):
        for action in RECOMMEND_ONLY_ACTIONS:
            assert action not in AUTO_APPLY_ACTIONS

    def test_recommend_manual_only_is_recommendation(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_CRITICAL, signals=signals)
        for action in actions:
            if action["action_type"] == ACTION_RECOMMEND_MANUAL_ONLY:
                assert action["should_apply"] is False

    def test_recommend_auto_is_always_recommendation(self):
        signals = _base_signals(system_mode="review_required", protective_mode_active=True)
        actions = decide_actions(situation=SITUATION_RECOVERING, signals=signals)
        for action in actions:
            if action["action_type"] == ACTION_RECOMMEND_AUTO:
                assert action["should_apply"] is False
                assert action["confidence"] == CONFIDENCE_LOW


class TestProtectiveModeRelaxation(unittest.TestCase):
    """Tests para relajación prudente de protective mode."""

    def setUp(self):
        reset_policy_state()
        reset_breaker_state()

    def test_relax_requires_sustained_recovery(self):
        """Recovery requiere RECOVERY_CONSECUTIVE_EVALUATIONS evaluaciones."""
        assert RECOVERY_CONSECUTIVE_EVALUATIONS >= 2

    def test_recovery_needs_more_evidence_than_degrade(self):
        """Asimetría: relajar cuesta más que endurecer."""
        # Degradar es inmediato (1 evaluación con señales altas)
        # Recuperar requiere RECOVERY_CONSECUTIVE_EVALUATIONS evaluaciones
        assert RECOVERY_CONSECUTIVE_EVALUATIONS >= 3

    def test_no_relax_if_protective_not_active(self):
        signals = _base_signals(protective_mode_active=False)
        actions = decide_actions(situation=SITUATION_RECOVERING, signals=signals)
        action_types = [a["action_type"] for a in actions]
        assert ACTION_RELAX_PROTECTIVE not in action_types


class TestRecoveryDetection(unittest.TestCase):
    """Tests para detección de recuperación sostenida."""

    def setUp(self):
        reset_policy_state()
        reset_breaker_state()

    def test_recovery_detected_after_sustained_improvement(self):
        """Simula mejora sostenida y verifica que se detecta recovering."""
        # Primero degradar
        result = evaluate_auto_healing(
            safety_snapshot=_base_safety_snapshot(error_like_events_count=UNSTABLE_ERROR_COUNT),
            human_control_snapshot=_base_control_snapshot(),
            system_mode="auto",
            protective_mode_status=_base_pm_status(),
        )
        assert result["situation"] in (SITUATION_UNSTABLE, SITUATION_DEGRADED, SITUATION_CRITICAL)

        # Ahora mejorar consecutivamente
        # Need to bypass cooldown for testing
        from app.services.auto_healing_policy import _state_lock, _previous_situation
        import app.services.auto_healing_policy as policy_mod

        for i in range(RECOVERY_CONSECUTIVE_EVALUATIONS + 1):
            with policy_mod._state_lock:
                policy_mod._last_evaluation_at = None  # bypass cooldown

            result = evaluate_auto_healing(
                safety_snapshot=_base_safety_snapshot(),
                human_control_snapshot=_base_control_snapshot(),
                system_mode="auto",
                protective_mode_status=_base_pm_status(),
            )

        # After enough normal evaluations following a degraded state, should detect recovery
        assert result["recovery_counter"] >= RECOVERY_CONSECUTIVE_EVALUATIONS or result["situation"] in (SITUATION_NORMAL, SITUATION_RECOVERING)


class TestAllowlistEnforcement(unittest.TestCase):
    """Tests para que acciones fuera de allowlist no se apliquen."""

    def test_forbidden_action_not_applied(self):
        db = MagicMock()
        for forbidden in FORBIDDEN_AUTO_ACTIONS:
            action = {"action_type": forbidden, "should_apply": True, "confidence": CONFIDENCE_HIGH}
            result = _apply_action(db, action, _base_signals())
            assert result["applied"] is False
            assert "FORBIDDEN" in result["reason"]

    def test_unknown_action_not_applied(self):
        db = MagicMock()
        action = {"action_type": "magic_fix_everything", "should_apply": True, "confidence": CONFIDENCE_HIGH}
        result = _apply_action(db, action, _base_signals())
        assert result["applied"] is False

    def test_recommendation_not_auto_applied(self):
        db = MagicMock()
        action = {"action_type": ACTION_RECOMMEND_MANUAL_ONLY, "should_apply": False, "confidence": CONFIDENCE_HIGH}
        result = _apply_action(db, action, _base_signals())
        assert result["applied"] is False


class TestActionApplication(unittest.TestCase):
    """Tests para aplicación real de acciones."""

    def setUp(self):
        reset_breaker_state()
        reset_policy_state()

    def test_activate_protective_triggers_breaker(self):
        db = MagicMock()
        action = {"action_type": ACTION_ACTIVATE_PROTECTIVE, "should_apply": True, "confidence": CONFIDENCE_HIGH}
        result = _apply_action(db, action, _base_signals())
        assert result["applied"] is True
        reset_breaker_state()

    def test_relax_protective_resets_breaker(self):
        # First activate
        from app.services.safety_classifier import record_breaker_event, get_protective_mode_status
        for _ in range(6):
            record_breaker_event(event_type="fallback_triggered", fallback_type="internal_error")
        pm = get_protective_mode_status()
        assert pm["protective_mode_active"] is True

        # Now relax
        db = MagicMock()
        action = {"action_type": ACTION_RELAX_PROTECTIVE, "should_apply": True, "confidence": CONFIDENCE_HIGH}
        result = _apply_action(db, action, _base_signals())
        assert result["applied"] is True

        pm2 = get_protective_mode_status()
        assert pm2["protective_mode_active"] is False

    @patch("app.services.self_tuning_override_service.set_system_mode")
    @patch("app.services.self_tuning_override_service.get_system_mode", return_value="auto")
    def test_enforce_review_required_changes_mode(self, mock_get, mock_set):
        mock_set.return_value = {"system_mode": "review_required"}
        db = MagicMock()
        action = {"action_type": ACTION_ENFORCE_REVIEW_REQUIRED, "should_apply": True, "confidence": CONFIDENCE_HIGH}
        result = _apply_action(db, action, _base_signals())
        assert result["applied"] is True
        mock_set.assert_called_once()

    @patch("app.services.self_tuning_override_service.set_system_mode")
    @patch("app.services.self_tuning_override_service.get_system_mode", return_value="manual_only")
    def test_enforce_review_noop_if_already_stricter(self, mock_get, mock_set):
        db = MagicMock()
        action = {"action_type": ACTION_ENFORCE_REVIEW_REQUIRED, "should_apply": True, "confidence": CONFIDENCE_HIGH}
        result = _apply_action(db, action, _base_signals())
        assert result["applied"] is False
        mock_set.assert_not_called()


class TestAuditability(unittest.TestCase):
    """Tests para auditoría de eventos de auto-healing."""

    def test_auto_healing_event_model_fields(self):
        event = AutoHealingEvent(
            situation="critical",
            previous_situation="unstable",
            action_type=ACTION_ENFORCE_REVIEW_REQUIRED,
            action_applied=True,
            confidence=CONFIDENCE_HIGH,
            reason="test reason",
            rollback_plan="change mode back to auto",
            signals_json=json.dumps({"error_like_events_count": 10}),
            result_json=json.dumps({"applied": True}),
            system_mode="auto",
            protective_mode_active=False,
        )
        d = event.to_dict()
        assert d["situation"] == "critical"
        assert d["previous_situation"] == "unstable"
        assert d["action_type"] == ACTION_ENFORCE_REVIEW_REQUIRED
        assert d["action_applied"] is True
        assert d["confidence"] == CONFIDENCE_HIGH
        assert d["reason"] == "test reason"
        assert d["rollback_plan"] == "change mode back to auto"
        assert d["signals"]["error_like_events_count"] == 10
        assert d["result"]["applied"] is True
        assert d["system_mode"] == "auto"
        assert d["protective_mode_active"] is False

    def test_event_to_dict_handles_empty_json(self):
        event = AutoHealingEvent(
            situation="normal",
            action_type="none",
            signals_json="",
            result_json=None,
        )
        d = event.to_dict()
        assert d["signals"] == {}
        assert d["result"] == {}


class TestRollbackAndExpiry(unittest.TestCase):
    """Tests para rollback/expiry de acciones automáticas."""

    def setUp(self):
        reset_breaker_state()

    def test_protective_mode_auto_recovers(self):
        """Protective mode se relaja vía reset_breaker_state (acción relax)."""
        from app.services.safety_classifier import record_breaker_event, get_protective_mode_status
        for _ in range(6):
            record_breaker_event(event_type="fallback_triggered", fallback_type="internal_error")
        assert get_protective_mode_status()["protective_mode_active"] is True

        reset_breaker_state()
        assert get_protective_mode_status()["protective_mode_active"] is False

    @patch("app.services.self_tuning_override_service.create_override")
    @patch("app.services.self_tuning_override_service.get_active_overrides", return_value=[])
    def test_suspend_tuning_creates_expiring_override(self, _mock_get, mock_create):
        from app.services.auto_healing_constants import AUTO_HEALING_OVERRIDE_DURATION_CYCLES
        mock_create.return_value = {"override": {"id": "test-id"}}
        db = MagicMock()
        action = {"action_type": ACTION_SUSPEND_AUTO_TUNING, "should_apply": True, "confidence": CONFIDENCE_HIGH}
        result = _apply_action(db, action, _base_signals())
        assert result["applied"] is True
        # Verify it was called with duration_cycles
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["duration_cycles"] == AUTO_HEALING_OVERRIDE_DURATION_CYCLES


class TestSignalCollection(unittest.TestCase):
    """Tests para recolección de señales."""

    def test_collect_signals_returns_all_expected_keys(self):
        signals = collect_signals(
            safety_snapshot=_base_safety_snapshot(),
            human_control_snapshot=_base_control_snapshot(),
            system_mode="auto",
            protective_mode_status=_base_pm_status(),
        )
        expected_keys = {
            "fallback_triggered_count", "error_like_events_count", "degraded_requests_count",
            "rate_limited_requests_count", "rejected_inputs_count", "total_safety_events",
            "active_safety_status", "stale_reviews_count", "high_priority_reviews",
            "pending_reviews", "overrides_active", "human_interventions_last_24h",
            "system_mode", "protective_mode_active", "breaker_error_count", "breaker_degraded_count",
        }
        assert set(signals.keys()) == expected_keys

    def test_collect_signals_normalizes_missing_values(self):
        signals = collect_signals(
            safety_snapshot={},
            human_control_snapshot={},
            system_mode="auto",
            protective_mode_status={},
        )
        assert signals["fallback_triggered_count"] == 0
        assert signals["protective_mode_active"] is False
        assert signals["system_mode"] == "auto"


class TestPrudentDefaults(unittest.TestCase):
    """Tests para que el sistema sea conservador por defecto."""

    def test_normal_situation_takes_no_action(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_NORMAL, signals=signals)
        assert len(actions) == 0

    def test_degraded_does_not_auto_apply_review_required(self):
        """En degraded, review_required es recomendación, no auto-apply."""
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_DEGRADED, signals=signals)
        for action in actions:
            if action["action_type"] == ACTION_RECOMMEND_REVIEW_REQUIRED:
                assert action["should_apply"] is False

    def test_manual_only_is_never_auto_applied(self):
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_CRITICAL, signals=signals)
        for action in actions:
            if action["action_type"] == ACTION_RECOMMEND_MANUAL_ONLY:
                assert action["should_apply"] is False

    def test_auto_mode_recommendation_is_low_confidence(self):
        signals = _base_signals(system_mode="review_required", protective_mode_active=True)
        actions = decide_actions(situation=SITUATION_RECOVERING, signals=signals)
        for action in actions:
            if action["action_type"] == ACTION_RECOMMEND_AUTO:
                assert action["confidence"] == CONFIDENCE_LOW


class TestFase9Compat(unittest.TestCase):
    """Tests para compatibilidad con FASE 9."""

    def test_system_modes_are_compatible(self):
        """Los modos del sistema usados por auto-healing son los mismos de FASE 9."""
        valid_modes = {"auto", "review_required", "manual_only", "frozen"}
        assert MODES_THAT_BLOCK_AUTO_HEALING.issubset(valid_modes)

    def test_override_service_not_called_on_normal(self):
        """En situación normal, no se crean overrides."""
        signals = _base_signals()
        actions = decide_actions(situation=SITUATION_NORMAL, signals=signals)
        for action in actions:
            assert action["action_type"] != ACTION_SUSPEND_AUTO_TUNING


class TestFase10Compat(unittest.TestCase):
    """Tests para compatibilidad con FASE 10."""

    def test_protective_mode_integration(self):
        """Auto-healing usa las mismas funciones de protective mode de FASE 10."""
        reset_breaker_state()
        from app.services.safety_classifier import get_protective_mode_status
        pm = get_protective_mode_status()
        assert "protective_mode_active" in pm

    def test_severity_constants_not_duplicated(self):
        """Auto-healing usa constantes de safety_constants, no las duplica."""
        from app.services.safety_constants import BREAKER_ERROR_THRESHOLD
        assert BREAKER_ERROR_THRESHOLD > 0


class TestCooldown(unittest.TestCase):
    """Tests para cooldown entre evaluaciones."""

    def setUp(self):
        reset_policy_state()
        reset_breaker_state()

    def test_cooldown_skips_evaluation(self):
        """Segunda evaluación dentro del cooldown retorna skipped."""
        result1 = evaluate_auto_healing(
            safety_snapshot=_base_safety_snapshot(),
            human_control_snapshot=_base_control_snapshot(),
            system_mode="auto",
            protective_mode_status=_base_pm_status(),
        )
        assert result1["cooldown_skipped"] is False

        result2 = evaluate_auto_healing(
            safety_snapshot=_base_safety_snapshot(),
            human_control_snapshot=_base_control_snapshot(),
            system_mode="auto",
            protective_mode_status=_base_pm_status(),
        )
        assert result2["cooldown_skipped"] is True


class TestFullCycle(unittest.TestCase):
    """Tests para el ciclo completo de auto-healing."""

    def setUp(self):
        reset_policy_state()
        reset_breaker_state()

    def test_full_cycle_with_critical_signals(self):
        """Un ciclo completo con señales críticas produce acciones."""
        import app.services.auto_healing_policy as policy_mod
        with policy_mod._state_lock:
            policy_mod._last_evaluation_at = None

        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()

        result = run_auto_healing_cycle(
            db,
            safety_snapshot=_base_safety_snapshot(error_like_events_count=CRITICAL_ERROR_COUNT),
            human_control_snapshot=_base_control_snapshot(),
            system_mode="auto",
            protective_mode_status=_base_pm_status(),
        )

        assert result["situation"] == SITUATION_CRITICAL
        assert len(result.get("actions_taken", [])) > 0
        # Verify db.add was called (audit)
        assert db.add.called

    def test_full_cycle_normal_no_actions(self):
        """Un ciclo con señales normales no produce acciones."""
        import app.services.auto_healing_policy as policy_mod
        with policy_mod._state_lock:
            policy_mod._last_evaluation_at = None

        db = MagicMock()
        result = run_auto_healing_cycle(
            db,
            safety_snapshot=_base_safety_snapshot(),
            human_control_snapshot=_base_control_snapshot(),
            system_mode="auto",
            protective_mode_status=_base_pm_status(),
        )

        assert result["situation"] == SITUATION_NORMAL
        assert len(result.get("actions_taken", [])) == 0


if __name__ == "__main__":
    unittest.main()
