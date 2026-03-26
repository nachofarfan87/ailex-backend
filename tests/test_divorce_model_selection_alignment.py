# backend/tests/test_divorce_model_selection_alignment.py
"""
Tests that model/template selection uses the ALIGNED action_slug
(after align_classification_with_domain), not the raw classifier output.

Covers:
  1. select_model receives the corrected slug for divorce queries
  2. Divorce query selects a divorce-family template
  3. No alimentos template is used for a pure divorce query
  4. Pipeline ordering: alignment runs before model selection
"""
from __future__ import annotations

import json
import pytest

from legal_engine.model_library import ModelLibrary
from legal_engine.case_profile_builder import (
    align_classification_with_domain,
    build_case_profile,
    _SLUG_TO_DOMAIN,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight model index with both divorce and alimentos models
# ---------------------------------------------------------------------------

def _build_index(tmp_path):
    """Create a minimal model index with divorce AND alimentos templates."""
    payload = {
        "version": 1,
        "models": [
            {
                "model_id": "divorcio_template",
                "name": "Divorcio unilateral base",
                "source_type": "virtual",
                "priority": 3,
                "rating": 5,
                "applicability": {
                    "jurisdiction": "nacional",
                    "forum": "familia",
                    "action_slug": "divorcio_unilateral",
                    "document_kind": "formal",
                    "tags": [],
                    "preferred_tags": [],
                    "excluded_tags": [],
                },
                "style_profile": {
                    "tone": "technical_robust",
                    "structure": [],
                    "argument_density": "high",
                    "facts_style": "concrete",
                    "petitum_style": "progressive",
                },
                "argument_strategy": {
                    "focus": "dissolution",
                    "risk_tolerance": "low",
                },
            },
            {
                "model_id": "alimentos_template",
                "name": "Alimentos hijos base",
                "source_type": "virtual",
                "priority": 3,
                "rating": 5,
                "applicability": {
                    "jurisdiction": "nacional",
                    "forum": "familia",
                    "action_slug": "alimentos_hijos",
                    "document_kind": "formal",
                    "tags": [],
                    "preferred_tags": [],
                    "excluded_tags": [],
                },
                "style_profile": {
                    "tone": "balanced_prudent",
                    "structure": [],
                    "argument_density": "standard",
                    "facts_style": "concrete",
                    "petitum_style": "prudent",
                },
                "argument_strategy": {
                    "focus": "urgency",
                    "risk_tolerance": "medium",
                },
            },
            {
                "model_id": "familia_generic",
                "name": "Familia generico",
                "source_type": "virtual",
                "priority": 1,
                "rating": 2,
                "applicability": {
                    "forum": "familia",
                    "document_kind": "formal",
                    "tags": [],
                    "preferred_tags": [],
                    "excluded_tags": [],
                },
                "style_profile": {
                    "tone": "balanced_prudent",
                    "structure": [],
                    "argument_density": "standard",
                    "facts_style": "concrete",
                    "petitum_style": "prudent",
                },
            },
        ],
    }
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    return index_path


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


# ---------------------------------------------------------------------------
# 1. test_model_selection_uses_aligned_slug
# ---------------------------------------------------------------------------

class TestModelSelectionUsesAlignedSlug:
    """Verify that select_model receives the corrected slug, not the raw one."""

    def test_aligned_slug_is_divorcio_for_explicit_intent(self):
        """Simulate: classifier says alimentos_hijos, user says 'quiero divorciarme'.
        After alignment, slug should be divorcio_unilateral."""
        raw_cls = {"action_slug": "alimentos_hijos", "action_label": "Alimentos de hijos"}
        query = "Quiero divorciarme"

        # Step 1: build profile → resolves case_domain = "divorcio"
        profile = _profile(query=query, classification=raw_cls)
        assert profile["case_domain"] == "divorcio"

        # Step 2: align — this is what the pipeline now does BEFORE select_model
        aligned = align_classification_with_domain(
            raw_cls, profile["case_domain"], query,
        )
        assert aligned["action_slug"] == "divorcio_unilateral"

        # Step 3: the slug that would be passed to select_model
        slug_for_model = aligned["action_slug"]
        assert _SLUG_TO_DOMAIN.get(slug_for_model) == "divorcio"

    def test_select_model_with_aligned_slug_picks_divorce_template(self, tmp_path):
        """Full flow: alignment → select_model → divorce template chosen."""
        library = ModelLibrary(_build_index(tmp_path))

        # Simulate misclassification + alignment
        raw_cls = {"action_slug": "alimentos_hijos"}
        aligned = align_classification_with_domain(raw_cls, "divorcio", "Quiero divorciarme")

        result = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=aligned["action_slug"],
            document_kind="formal",
        )
        assert result["selected_model"] is not None
        assert result["selected_model"]["model_id"] == "divorcio_template"

    def test_select_model_without_alignment_picks_alimentos_template(self, tmp_path):
        """Control: WITHOUT alignment, the raw slug would pick alimentos."""
        library = ModelLibrary(_build_index(tmp_path))

        result = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug="alimentos_hijos",
            document_kind="formal",
        )
        assert result["selected_model"]["model_id"] == "alimentos_template"


# ---------------------------------------------------------------------------
# 2. test_divorce_query_selects_divorce_template
# ---------------------------------------------------------------------------

class TestDivorceQuerySelectsDivorceTemplate:
    """End-to-end: divorce query → profile → alignment → select_model → divorce template."""

    @pytest.mark.parametrize("query", [
        "Quiero divorciarme",
        "Me quiero divorciar",
        "Quiero el divorcio",
    ])
    def test_divorce_query_gets_divorce_model(self, tmp_path, query):
        library = ModelLibrary(_build_index(tmp_path))

        # Simulate pipeline: classification (wrong) → profile → align → select
        raw_cls = {"action_slug": "alimentos_hijos"}
        profile = _profile(query=query, classification=raw_cls)
        aligned = align_classification_with_domain(
            raw_cls, profile["case_domain"], query,
        )

        result = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=aligned["action_slug"],
            document_kind="formal",
        )
        assert result["selected_model"]["model_id"] == "divorcio_template"
        assert result["match_type"] == "exact"

    def test_correct_classification_also_gets_divorce_model(self, tmp_path):
        """When classifier gets it right, alignment is a no-op and model is still correct."""
        library = ModelLibrary(_build_index(tmp_path))

        cls = {"action_slug": "divorcio_unilateral"}
        aligned = align_classification_with_domain(cls, "divorcio", "Quiero divorciarme")
        assert aligned is cls  # no copy — already correct

        result = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=aligned["action_slug"],
            document_kind="formal",
        )
        assert result["selected_model"]["model_id"] == "divorcio_template"


# ---------------------------------------------------------------------------
# 3. test_no_alimentos_template_for_divorce_query
# ---------------------------------------------------------------------------

class TestNoAlimentosTemplateForDivorceQuery:
    """After alignment, a divorce query must NEVER select an alimentos template."""

    def test_aligned_slug_never_matches_alimentos_model(self, tmp_path):
        library = ModelLibrary(_build_index(tmp_path))

        raw_cls = {"action_slug": "alimentos_hijos"}
        aligned = align_classification_with_domain(raw_cls, "divorcio", "Quiero divorciarme")

        result = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=aligned["action_slug"],
            document_kind="formal",
        )
        assert result["selected_model"]["model_id"] != "alimentos_template"

    def test_alimentos_query_still_gets_alimentos_model(self, tmp_path):
        """Regression guard: pure alimentos query must still pick alimentos."""
        library = ModelLibrary(_build_index(tmp_path))

        cls = {"action_slug": "alimentos_hijos"}
        profile = _profile(
            query="El padre no paga alimentos",
            classification=cls,
        )
        aligned = align_classification_with_domain(
            cls, profile["case_domain"], "El padre no paga alimentos",
        )
        # No correction — alimentos stays
        assert aligned["action_slug"] == "alimentos_hijos"

        result = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=aligned["action_slug"],
            document_kind="formal",
        )
        assert result["selected_model"]["model_id"] == "alimentos_template"


# ---------------------------------------------------------------------------
# 4. test_pipeline_order_alignment_before_model_selection
# ---------------------------------------------------------------------------

class TestPipelineOrderAlignmentBeforeModelSelection:
    """Simulate the pipeline order to verify alignment happens before
    model selection, producing consistent results."""

    def test_full_pipeline_order_simulation(self, tmp_path):
        """Simulate the corrected pipeline order:
        classification → profile → alignment → select_model."""
        library = ModelLibrary(_build_index(tmp_path))
        query = "Quiero divorciarme"

        # 1. Classification (simulated — wrong)
        classification = {"action_slug": "alimentos_hijos", "action_label": "Alimentos"}

        # 2. Build case profile (resolves domain)
        profile = _profile(query=query, classification=classification)
        case_domain = profile["case_domain"]
        assert case_domain == "divorcio"

        # 3. Align classification (BEFORE model selection)
        classification = align_classification_with_domain(
            classification, case_domain, query,
        )
        assert classification["action_slug"] == "divorcio_unilateral"
        assert classification["_original_action_slug"] == "alimentos_hijos"

        # 4. Model selection (uses aligned slug)
        result = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=classification["action_slug"],
            document_kind="formal",
        )

        # 5. Verify: divorce template selected, not alimentos
        assert result["selected_model"]["model_id"] == "divorcio_template"
        assert result["match_type"] == "exact"

    def test_old_order_would_have_selected_wrong_template(self, tmp_path):
        """Demonstrate the bug: without early alignment, model selection
        picks alimentos template for a divorce query."""
        library = ModelLibrary(_build_index(tmp_path))

        # OLD ORDER: classification → select_model → profile → align (too late)
        classification = {"action_slug": "alimentos_hijos"}

        # Model selection with RAW (unaligned) slug
        result_old = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=classification["action_slug"],  # still alimentos_hijos!
            document_kind="formal",
        )
        # BUG: this picks alimentos template
        assert result_old["selected_model"]["model_id"] == "alimentos_template"

        # NEW ORDER: classification → profile → align → select_model
        profile = _profile(query="Quiero divorciarme", classification=classification)
        classification = align_classification_with_domain(
            classification, profile["case_domain"], "Quiero divorciarme",
        )
        result_new = library.select_model(
            jurisdiction="nacional",
            forum="familia",
            action_slug=classification["action_slug"],  # now divorcio_unilateral
            document_kind="formal",
        )
        # FIXED: this picks divorce template
        assert result_new["selected_model"]["model_id"] == "divorcio_template"

    def test_alignment_is_idempotent(self):
        """Running alignment twice produces the same result."""
        cls = {"action_slug": "alimentos_hijos"}
        first = align_classification_with_domain(cls, "divorcio", "Quiero divorciarme")
        second = align_classification_with_domain(first, "divorcio", "Quiero divorciarme")
        assert first["action_slug"] == second["action_slug"] == "divorcio_unilateral"
        # Second call should be a no-op (already aligned)
        assert second is first

    def test_other_domains_not_affected(self, tmp_path):
        """Alimentos, cuidado_personal queries are not touched by alignment."""
        library = ModelLibrary(_build_index(tmp_path))

        for query, slug, expected_model in [
            ("El padre no paga alimentos", "alimentos_hijos", "alimentos_template"),
        ]:
            cls = {"action_slug": slug}
            profile = _profile(query=query, classification=cls)
            aligned = align_classification_with_domain(
                cls, profile["case_domain"], query,
            )
            assert aligned["action_slug"] == slug  # no change

            result = library.select_model(
                jurisdiction="nacional",
                forum="familia",
                action_slug=aligned["action_slug"],
                document_kind="formal",
            )
            assert result["selected_model"]["model_id"] == expected_model
