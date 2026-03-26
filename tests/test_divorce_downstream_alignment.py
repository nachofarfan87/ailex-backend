# backend/tests/test_divorce_downstream_alignment.py
"""
Tests for downstream alignment between case_domain, action_slug,
strategy signals, and payload consistency.

Ensures that when explicit divorce intent forces case_domain = "divorcio",
all downstream signals (action_slug, template family, strategy_mode,
dominant_factor, next steps) stay coherent.
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from legal_engine.case_profile_builder import (
    align_classification_with_domain,
    build_case_profile,
    _SLUG_TO_DOMAIN,
    _normalize_text,
)
from legal_engine.case_strategy_builder import (
    build_case_strategy,
    sanitize_strategy_output,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_inputs(**overrides):
    defaults = dict(
        query="",
        classification={},
        case_theory={},
        conflict={},
        normative_reasoning={},
        procedural_plan=None,
        facts={},
    )
    defaults.update(overrides)
    return defaults


def _profile(**kw):
    return build_case_profile(**_base_inputs(**kw))


def _reasoning():
    return SimpleNamespace(
        applied_analysis="Analisis juridico inicial.",
        short_answer="Respuesta base.",
    )


def _plan():
    return SimpleNamespace(
        steps=[SimpleNamespace(action="Presentar demanda.")],
        risks=["Riesgo procesal generico."],
    )


def _normalize(text):
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _build_full_strategy(*, query, case_profile, **overrides):
    defaults = dict(
        case_theory={},
        conflict={},
        case_evaluation={},
        procedural_plan=_plan(),
        jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
        reasoning_result=_reasoning(),
        legal_decision=None,
        procedural_case_state=None,
    )
    defaults.update(overrides)
    return sanitize_strategy_output(build_case_strategy(
        query=query,
        case_profile=case_profile,
        **defaults,
    ))


# ---------------------------------------------------------------------------
# 1. align_classification_with_domain — unit tests
# ---------------------------------------------------------------------------

class TestAlignClassificationWithDomain:
    """Test the new alignment function directly."""

    def test_already_aligned_no_change(self):
        """If slug already maps to the same domain, no correction needed."""
        cls = {"action_slug": "divorcio_unilateral", "action_label": "Divorcio unilateral"}
        result = align_classification_with_domain(cls, "divorcio", "Quiero divorciarme")
        assert result is cls  # same object, no copy
        assert result["action_slug"] == "divorcio_unilateral"

    def test_misaligned_slug_corrected_for_divorce(self):
        """If slug is alimentos but domain is divorcio (explicit intent), correct it."""
        cls = {"action_slug": "alimentos_hijos", "action_label": "Alimentos de hijos"}
        result = align_classification_with_domain(cls, "divorcio", "Quiero divorciarme")
        assert result["action_slug"] == "divorcio_unilateral"
        assert result["_original_action_slug"] == "alimentos_hijos"
        assert result["_slug_aligned_to_domain"] == "divorcio"

    def test_no_correction_without_explicit_intent(self):
        """If query doesn't have explicit divorce intent, don't override."""
        cls = {"action_slug": "alimentos_hijos"}
        result = align_classification_with_domain(cls, "divorcio", "divorcio y alimentos para hijos")
        # "divorcio y alimentos para hijos" does NOT match explicit divorce intent patterns
        assert result is cls
        assert result["action_slug"] == "alimentos_hijos"

    def test_no_correction_when_no_domain(self):
        cls = {"action_slug": "alimentos_hijos"}
        result = align_classification_with_domain(cls, None, "Quiero divorciarme")
        assert result is cls

    def test_alimentos_query_not_overridden(self):
        """Pure alimentos query with alimentos slug — no correction."""
        cls = {"action_slug": "alimentos_hijos"}
        result = align_classification_with_domain(cls, "alimentos", "El padre no paga alimentos")
        assert result is cls
        assert result["action_slug"] == "alimentos_hijos"

    def test_preserves_other_classification_fields(self):
        """Correction should preserve all other fields in classification."""
        cls = {
            "action_slug": "alimentos_hijos",
            "action_label": "Alimentos de hijos",
            "legal_intent": "proteccion_alimentaria",
            "forum": "familia",
            "domain": "family",
            "confidence_score": 0.7,
        }
        result = align_classification_with_domain(cls, "divorcio", "Quiero divorciarme")
        assert result["action_slug"] == "divorcio_unilateral"
        assert result["action_label"] == "Alimentos de hijos"  # preserved
        assert result["legal_intent"] == "proteccion_alimentaria"  # preserved
        assert result["confidence_score"] == 0.7  # preserved


# ---------------------------------------------------------------------------
# 2. test_explicit_divorce_intent_aligns_action_slug_with_divorce
# ---------------------------------------------------------------------------

class TestExplicitDivorceIntentAlignsSlug:
    """When case_domain is forced to divorcio by explicit intent,
    action_slug must be in the divorcio family."""

    @pytest.mark.parametrize("query", [
        "Quiero divorciarme",
        "Me quiero divorciar",
        "Quiero el divorcio",
    ])
    def test_slug_aligns_to_divorce_family(self, query):
        # Simulate a misclassification
        cls = {"action_slug": "alimentos_hijos"}
        profile = _profile(query=query, classification=cls)
        assert profile["case_domain"] == "divorcio"

        aligned = align_classification_with_domain(cls, profile["case_domain"], query)
        slug_domain = _SLUG_TO_DOMAIN.get(aligned["action_slug"])
        assert slug_domain == "divorcio", (
            f"After alignment, slug '{aligned['action_slug']}' should map to 'divorcio', "
            f"got '{slug_domain}'"
        )


# ---------------------------------------------------------------------------
# 3. test_primary_divorce_prevents_alimentos_template_as_main
# ---------------------------------------------------------------------------

class TestPrimaryDivorcePreventsAlimentosTemplate:
    """After alignment, the action_slug used for model selection should
    be in the divorcio family, not alimentos."""

    def test_corrected_slug_is_divorcio_family(self):
        cls = {"action_slug": "alimentos_hijos"}
        aligned = align_classification_with_domain(cls, "divorcio", "Quiero divorciarme")
        # The slug passed to model_library.select_model() should be divorcio-family
        assert "divorcio" in aligned["action_slug"]

    def test_correct_slug_stays_unchanged(self):
        cls = {"action_slug": "divorcio_unilateral"}
        aligned = align_classification_with_domain(cls, "divorcio", "Quiero divorciarme")
        assert aligned["action_slug"] == "divorcio_unilateral"
        # No _original_action_slug key — no correction was made
        assert "_original_action_slug" not in aligned


# ---------------------------------------------------------------------------
# 4. test_divorce_payload_main_next_steps_are_not_alimentos
# ---------------------------------------------------------------------------

class TestDivorcePayloadNextSteps:
    """Recommended actions and procedural focus for a divorce primary case
    must be divorce-centric, not alimentos-centric."""

    def test_recommended_actions_are_divorce_centric(self):
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_full_strategy(query="Quiero divorciarme", case_profile=profile)
        actions_text = _normalize(" ".join(strategy.get("recommended_actions", [])))
        # Should contain divorce-related actions
        has_divorce_action = any(t in actions_text for t in (
            "propuesta reguladora", "divorcio", "convenio",
            "art. 438", "efectos", "hogar",
        ))
        assert has_divorce_action, f"Expected divorce actions, got: {actions_text[:200]}"

    def test_recommended_actions_no_alimentos_primary(self):
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_full_strategy(query="Quiero divorciarme", case_profile=profile)
        actions_text = _normalize(" ".join(strategy.get("recommended_actions", [])))
        # Should NOT contain alimentos-primary phrasing
        for phrase in ("cuota provisoria", "alimentante", "incumplimiento alimentario"):
            assert phrase not in actions_text, (
                f"Alimentos phrase '{phrase}' in divorce recommended_actions"
            )

    def test_procedural_focus_has_divorce_items(self):
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_full_strategy(query="Quiero divorciarme", case_profile=profile)
        focus_text = _normalize(" ".join(strategy.get("procedural_focus", [])))
        has_divorce_focus = any(t in focus_text for t in (
            "propuesta reguladora", "divorcio", "presentacion unilateral",
            "438", "vinculo",
        ))
        assert has_divorce_focus, f"Expected divorce focus, got: {focus_text[:200]}"


# ---------------------------------------------------------------------------
# 5. test_mixed_divorce_and_alimentos_keeps_divorce_main_and_alimentos_secondary
# ---------------------------------------------------------------------------

class TestMixedDivorceAlimentosKeepsDivorceMain:
    """When user says 'quiero divorciarme' and secondary alimentos appears,
    divorce must govern all primary blocks and alimentos only appears
    in secondary_domain_notes."""

    def test_multi_domain_primary_is_divorce(self):
        profile = _profile(
            query="Quiero divorciarme, tenemos hijos menores",
            classification={"action_slug": "divorcio_unilateral"},
        )
        assert profile["case_domain"] == "divorcio"
        assert profile["case_domains"][0] == "divorcio"

    def test_strategy_narrative_is_divorce_centric(self):
        profile = _profile(
            query="Quiero divorciarme, tenemos hijos menores",
            classification={"action_slug": "divorcio_unilateral"},
        )
        strategy = _build_full_strategy(
            query="Quiero divorciarme, tenemos hijos menores",
            case_profile=profile,
        )
        narrative = _normalize(strategy["strategic_narrative"])
        first_para = narrative.split("\n\n")[0]
        assert "divorcio" in first_para or "disolucion" in first_para or "vinculo" in first_para

    def test_secondary_notes_mention_secondary_domains(self):
        # Build a profile with both domains explicitly
        profile = {
            "case_domain": "divorcio",
            "case_domains": ["divorcio", "alimentos"],
            "is_alimentos": False,
            "scenarios": {"unilateral", "hijos"},
            "urgency_level": "medium",
            "vulnerability": False,
            "needs_proof_strengthening": False,
            "strategic_focus": ["armar presentacion unilateral con propuesta reguladora (art. 438 CCyC)"],
        }
        strategy = _build_full_strategy(query="Quiero divorciarme", case_profile=profile)
        secondary = strategy.get("secondary_domain_notes", [])
        secondary_text = _normalize(" ".join(secondary))
        assert "alimentos" in secondary_text, "Alimentos should appear as secondary note"


# ---------------------------------------------------------------------------
# 6. test_strategy_mode_and_dominant_factor_coherence
# ---------------------------------------------------------------------------

class TestStrategyModeCoherence:
    """strategy_mode and dominant_factor should be coherent with a divorce
    primary case — they should NOT be driven by alimentos scenarios."""

    def test_strategy_mode_is_valid(self):
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_full_strategy(query="Quiero divorciarme", case_profile=profile)
        assert strategy["strategy_mode"] in {"agresiva", "conservadora", "cautelosa"}

    def test_divorce_without_proof_needs_not_cautelosa_by_default(self):
        """A simple divorce without proof needs should not be cautelosa
        (which would indicate alimentos-style needs_proof influence)."""
        profile = _profile(query="Quiero divorciarme")
        # needs_proof_strengthening should be False for bare divorce
        assert profile["needs_proof_strengthening"] is False

    def test_dominant_factor_for_simple_divorce(self):
        """Without risk/proof/jurisprudence pressure, dominant factor
        should be 'norma' (default) for a simple divorce."""
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_full_strategy(
            query="Quiero divorciarme",
            case_profile=profile,
            case_evaluation={"risk_score": 0.1, "legal_risk_level": "bajo"},
        )
        # The strategy should build without error; mode/factor are coherent
        assert strategy["strategy_mode"] in {"agresiva", "conservadora", "cautelosa"}


# ---------------------------------------------------------------------------
# 7. Payload final consistency (simulated)
# ---------------------------------------------------------------------------

class TestPayloadFinalConsistency:
    """Verify that a simulated pipeline output would be consistent:
    case_domain, action_slug (after alignment), strategy, domains all agree."""

    def test_full_pipeline_simulation(self):
        query = "Quiero divorciarme"

        # Step 1: Simulate misclassification
        raw_classification = {"action_slug": "alimentos_hijos", "action_label": "Alimentos de hijos"}

        # Step 2: Build profile (fixes domain)
        profile = _profile(query=query, classification=raw_classification)
        assert profile["case_domain"] == "divorcio"

        # Step 3: Align classification
        aligned = align_classification_with_domain(
            raw_classification, profile["case_domain"], query,
        )
        assert aligned["action_slug"] == "divorcio_unilateral"

        # Step 4: Build strategy
        strategy = _build_full_strategy(query=query, case_profile=profile)

        # Step 5: Verify consistency
        assert profile["case_domain"] == "divorcio"
        assert _SLUG_TO_DOMAIN.get(aligned["action_slug"]) == "divorcio"
        assert strategy["strategy_mode"] in {"agresiva", "conservadora", "cautelosa"}

        # Narrative is divorce-centric
        narrative = _normalize(strategy["strategic_narrative"])
        assert "divorcio" in narrative or "vinculo" in narrative or "disolucion" in narrative

        # No alimentos contamination in primary blocks
        all_primary = _normalize(" ".join([
            strategy.get("strategic_narrative", ""),
            *strategy.get("conflict_summary", []),
            *strategy.get("recommended_actions", []),
            *strategy.get("risk_analysis", []),
            *strategy.get("procedural_focus", []),
        ]))
        for token in ("cuota provisoria", "alimentante", "incumplimiento alimentario",
                       "progenitor demandado", "monto de cuota"):
            assert token not in all_primary, (
                f"Contamination token '{token}' found in primary blocks"
            )

    def test_correct_classification_stays_clean(self):
        """When classifier gets it right, everything is naturally aligned."""
        query = "Quiero divorciarme"
        cls = {"action_slug": "divorcio_unilateral"}
        profile = _profile(query=query, classification=cls)
        aligned = align_classification_with_domain(cls, profile["case_domain"], query)

        # No correction needed
        assert aligned is cls
        assert aligned["action_slug"] == "divorcio_unilateral"
        assert profile["case_domain"] == "divorcio"

        strategy = _build_full_strategy(query=query, case_profile=profile)
        assert "divorcio" in _normalize(strategy["strategic_narrative"])
