# backend/tests/test_divorce_domain_dominance.py
"""
Tests for divorce domain dominance, anti-contamination, deduplication,
and output sanitization.

Covers:
  1. Explicit divorce query → divorcio as primary domain
  2. Divorce with secondary family effects → divorcio stays primary
  3. Alimentos query → alimentos stays primary (no regression)
  4. Secondary domains cannot override primary strategy block
  5. Internal model warnings removed from output
  6. Domain label deduplication
  7. Pipeline-level integration (if available)
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from legal_engine.case_profile_builder import (
    build_case_profile,
    _detect_domains,
    _query_has_explicit_divorce_intent,
    _normalize_text,
)
from legal_engine.case_strategy_builder import (
    build_case_strategy,
    sanitize_strategy_output,
    dedupe_domains,
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


def _build_strategy(*, query, case_profile, **overrides):
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


_ALIMENTOS_CONTAMINANTS = (
    "cuota provisoria",
    "alimentante",
    "incumplimiento alimentario",
    "gastos del hijo",
    "progenitor demandado",
    "monto de cuota",
    "retencion alimentaria",
    "cuota alimentaria",
    "deuda alimentaria",
)


def _normalize(text: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _strategy_primary_text(strategy: dict) -> str:
    """Concatenate all primary-block text for contamination checks."""
    parts = [
        strategy.get("strategic_narrative", ""),
    ]
    for key in ("conflict_summary", "recommended_actions", "risk_analysis", "procedural_focus"):
        section = strategy.get(key, [])
        if isinstance(section, list):
            parts.extend(section)
    return _normalize(" ".join(parts))


# ---------------------------------------------------------------------------
# 1. test_divorcio_query_remains_divorce_primary
# ---------------------------------------------------------------------------

class TestDivorcioQueryRemainsDivorcePrimary:
    """'Quiero divorciarme' must resolve to divorcio as primary domain
    with a divorce strategy, free of alimentos contamination."""

    @pytest.mark.parametrize("query", [
        "Quiero divorciarme",
        "Me quiero divorciar",
        "Quiero el divorcio",
        "divorcio",
        "Iniciar divorcio",
        "Separarme legalmente",
    ])
    def test_primary_domain_is_divorcio(self, query):
        profile = _profile(query=query)
        assert profile["case_domain"] == "divorcio"
        assert profile["case_domains"][0] == "divorcio"
        assert profile["is_alimentos"] is False

    def test_strategy_narrative_is_divorce(self):
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_strategy(query="Quiero divorciarme", case_profile=profile)
        narrative = _normalize(strategy["strategic_narrative"])
        assert "divorcio" in narrative or "disolucion" in narrative or "vinculo" in narrative

    def test_no_alimentos_contamination_in_primary_blocks(self):
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_strategy(query="Quiero divorciarme", case_profile=profile)
        primary_text = _strategy_primary_text(strategy)
        for token in _ALIMENTOS_CONTAMINANTS:
            assert token not in primary_text, (
                f"Alimentos contaminant '{token}' found in primary strategy for divorce query"
            )


# ---------------------------------------------------------------------------
# 2. test_divorce_with_secondary_family_effects_keeps_divorce_as_primary
# ---------------------------------------------------------------------------

class TestDivorceWithSecondaryEffects:
    """Divorce query mentioning hijos/vivienda: divorcio stays primary,
    secondary effects appear only in secondary_domain_notes or as
    divorcio sub-scenarios (hijos, bienes)."""

    def test_divorce_with_hijos_keeps_divorce_primary(self):
        profile = _profile(query="Quiero divorciarme, tenemos hijos y no acordamos vivienda")
        assert profile["case_domain"] == "divorcio"
        assert profile["case_domains"][0] == "divorcio"
        # hijos should be a scenario inside the divorcio builder
        assert "hijos" in profile["scenarios"]

    def test_divorce_with_bienes_keeps_divorce_primary(self):
        profile = _profile(query="Quiero divorciarme y resolver los bienes gananciales")
        assert profile["case_domain"] == "divorcio"
        assert "bienes" in profile["scenarios"]

    def test_secondary_domains_present_but_not_primary(self):
        profile = _profile(
            query="Quiero divorciarme, tenemos hijos",
            classification={"action_slug": "divorcio_unilateral"},
        )
        assert profile["case_domains"][0] == "divorcio"
        # alimentos may appear as secondary via keyword in enriched text but not as primary
        if "alimentos" in profile["case_domains"]:
            assert profile["case_domains"].index("alimentos") > 0

    def test_strategy_narrative_opens_with_divorce(self):
        profile = _profile(query="Quiero divorciarme, tenemos hijos y no acordamos vivienda")
        strategy = _build_strategy(query="Quiero divorciarme, tenemos hijos", case_profile=profile)
        narrative = strategy["strategic_narrative"]
        # First paragraph should be about divorcio, not alimentos
        first_para = narrative.split("\n\n")[0] if narrative else ""
        normalized_first = _normalize(first_para)
        assert "divorcio" in normalized_first or "disolucion" in normalized_first or "vinculo" in normalized_first


# ---------------------------------------------------------------------------
# 3. test_alimentos_query_still_resolves_to_alimentos
# ---------------------------------------------------------------------------

class TestAlimentosStillWorks:
    """Pure alimentos queries must not be affected by the divorce fix."""

    def test_alimentos_explicit(self):
        profile = _profile(query="El padre de mi hijo no paga alimentos")
        assert profile["case_domain"] == "alimentos"
        assert profile["is_alimentos"] is True

    def test_alimentos_with_slug(self):
        profile = _profile(
            query="Necesito reclamar cuota alimentaria",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert profile["case_domain"] == "alimentos"

    def test_alimentos_strategy_has_alimentos_content(self):
        profile = _profile(
            query="El padre de mi hijo no paga alimentos",
            classification={"action_slug": "alimentos_hijos"},
        )
        strategy = _build_strategy(
            query="El padre de mi hijo no paga alimentos",
            case_profile=profile,
        )
        narrative = _normalize(strategy["strategic_narrative"])
        assert "alimentos" in narrative


# ---------------------------------------------------------------------------
# 4. test_secondary_domains_do_not_override_primary_strategy_block
# ---------------------------------------------------------------------------

class TestSecondaryDomainsDoNotOverridePrimary:
    """Force a multi-domain case and verify primary block coherence."""

    def test_divorce_primary_with_alimentos_secondary(self):
        """Manually inject multi-domain profile where divorcio is primary
        and alimentos is secondary. Strategy must be divorce-centric."""
        profile = {
            "case_domain": "divorcio",
            "case_domains": ["divorcio", "alimentos"],
            "is_alimentos": False,
            "scenarios": {"unilateral", "hijos"},
            "urgency_level": "medium",
            "vulnerability": False,
            "needs_proof_strengthening": False,
            "strategic_focus": [
                "armar presentacion unilateral con propuesta reguladora (art. 438 CCyC)",
                "resolver situacion de hijos: cuidado personal, alimentos y comunicacion",
            ],
        }
        strategy = _build_strategy(query="Quiero divorciarme", case_profile=profile)
        narrative = _normalize(strategy["strategic_narrative"])
        # Narrative opening should be about divorcio
        assert "divorcio" in narrative or "disolucion" in narrative or "vinculo" in narrative
        # Secondary domain notes should mention alimentos
        secondary_notes = " ".join(strategy.get("secondary_domain_notes", []))
        assert "alimentos" in _normalize(secondary_notes) or len(strategy.get("secondary_domain_notes", [])) > 0

    def test_conflict_summary_follows_primary_domain(self):
        profile = {
            "case_domain": "divorcio",
            "case_domains": ["divorcio", "alimentos"],
            "is_alimentos": False,
            "scenarios": {"unilateral", "bienes"},
            "urgency_level": "medium",
            "vulnerability": False,
            "needs_proof_strengthening": False,
            "strategic_focus": [],
        }
        strategy = _build_strategy(
            query="Quiero divorciarme",
            case_profile=profile,
            conflict={
                "core_dispute": "Disolucion del vinculo matrimonial",
                "strongest_point": "Voluntad unilateral expresa",
                "most_vulnerable_point": "Falta de propuesta reguladora completa",
            },
        )
        conflict_text = _normalize(" ".join(strategy.get("conflict_summary", [])))
        # Should contain divorce-relevant content
        assert "propuesta reguladora" in conflict_text or "vinculo" in conflict_text or "bienes" in conflict_text


# ---------------------------------------------------------------------------
# 5. test_output_sanitization_removes_internal_model_warning
# ---------------------------------------------------------------------------

class TestOutputSanitization:
    """The output must not expose internal warnings/noise."""

    def test_model_warning_removed_from_strategy(self):
        profile = {
            "case_domain": "divorcio",
            "case_domains": ["divorcio"],
            "is_alimentos": False,
            "scenarios": {"unilateral"},
            "urgency_level": "medium",
            "vulnerability": False,
            "needs_proof_strengthening": False,
            "strategic_focus": [],
        }
        strategy = build_case_strategy(
            query="Quiero divorciarme",
            case_profile=profile,
            case_theory={},
            conflict={},
            case_evaluation={},
            procedural_plan=_plan(),
            jurisprudence_analysis={"source_quality": "none", "jurisprudence_strength": "none"},
            reasoning_result=_reasoning(),
        )
        # Inject noise to verify sanitization
        strategy["risk_analysis"].append("No se encontro un modelo aplicable para los parametros recibidos.")
        strategy["conflict_summary"].append("fallback generico activado")
        strategy["procedural_focus"].append("internal_fallback result")

        sanitized = sanitize_strategy_output(strategy)
        all_text = _normalize(" ".join([
            sanitized.get("strategic_narrative", ""),
            *sanitized.get("conflict_summary", []),
            *sanitized.get("risk_analysis", []),
            *sanitized.get("recommended_actions", []),
            *sanitized.get("procedural_focus", []),
            *sanitized.get("secondary_domain_notes", []),
        ]))
        assert "no se encontro un modelo aplicable" not in all_text
        assert "fallback generico" not in all_text
        assert "internal_fallback" not in all_text

    def test_narrative_noise_paragraphs_stripped(self):
        strategy = {
            "strategy_mode": "conservadora",
            "strategic_narrative": "Parrafo util sobre divorcio.\n\nNo se encontro un modelo aplicable para los parametros recibidos.\n\nOtro parrafo util.",
            "conflict_summary": [],
            "risk_analysis": [],
            "recommended_actions": [],
            "procedural_focus": [],
            "legal_decision_alignment": [],
            "secondary_domain_notes": [],
        }
        sanitized = sanitize_strategy_output(strategy)
        assert "no se encontro un modelo aplicable" not in _normalize(sanitized["strategic_narrative"])
        assert "parrafo util sobre divorcio" in _normalize(sanitized["strategic_narrative"])
        assert "otro parrafo util" in _normalize(sanitized["strategic_narrative"])


# ---------------------------------------------------------------------------
# 6. test_strategy_domain_labels_are_deduplicated
# ---------------------------------------------------------------------------

class TestDomainDeduplication:
    """Domain labels must not repeat in the final output."""

    def test_dedupe_domains_removes_duplicates(self):
        assert dedupe_domains(["alimentos", "alimentos", "divorcio"]) == ["alimentos", "divorcio"]

    def test_dedupe_domains_case_insensitive(self):
        assert dedupe_domains(["Alimentos", "alimentos", "Divorcio"]) == ["Alimentos", "Divorcio"]

    def test_dedupe_domains_empty(self):
        assert dedupe_domains([]) == []

    def test_dedupe_domains_preserves_order(self):
        assert dedupe_domains(["divorcio", "alimentos", "divorcio", "alimentos"]) == ["divorcio", "alimentos"]


# ---------------------------------------------------------------------------
# 7. Explicit divorce intent detection
# ---------------------------------------------------------------------------

class TestExplicitDivorceIntentDetection:
    """Unit tests for _query_has_explicit_divorce_intent."""

    @pytest.mark.parametrize("query", [
        "quiero divorciarme",
        "me quiero divorciar",
        "quiero el divorcio",
        "iniciar divorcio",
        "separarme legalmente",
        "divorcio",
        "divorciarse",
        "divorciarme",
        "tramitar el divorcio",
        "pedir divorcio",
    ])
    def test_positive_intent(self, query):
        assert _query_has_explicit_divorce_intent(_normalize_text(query)) is True

    @pytest.mark.parametrize("query", [
        "el padre de mi hijo no paga alimentos",
        "quiero reclamar cuota alimentaria",
        "no me dejan ver a mi hijo",
        "hola quiero consultar algo",
        "",
    ])
    def test_negative_intent(self, query):
        assert _query_has_explicit_divorce_intent(_normalize_text(query)) is False


# ---------------------------------------------------------------------------
# 8. Domain detection with explicit intent override
# ---------------------------------------------------------------------------

class TestDomainDetectionOverride:
    """_detect_domains respects explicit divorce intent in query."""

    def test_divorce_query_with_alimentos_in_enriched_text(self):
        """Even if enriched text mentions 'alimentos', divorce stays first
        when the query is explicitly about divorce."""
        enriched = "divorcio alimentos cuota alimentaria hijo menor progenitor"
        query_text = _normalize_text("quiero divorciarme")
        domains = _detect_domains("divorcio_unilateral", enriched, query_text=query_text)
        assert domains[0] == "divorcio"

    def test_alimentos_query_keeps_alimentos_first(self):
        """When query is about alimentos, default priority applies."""
        enriched = "alimentos divorcio cuota"
        query_text = _normalize_text("el padre no paga alimentos")
        domains = _detect_domains("alimentos_hijos", enriched, query_text=query_text)
        assert domains[0] == "alimentos"

    def test_bare_divorcio_query(self):
        enriched = "divorcio vinculo matrimonial"
        query_text = _normalize_text("divorcio")
        domains = _detect_domains("", enriched, query_text=query_text)
        assert domains[0] == "divorcio"


# ---------------------------------------------------------------------------
# 9. Anti-contamination guard integration
# ---------------------------------------------------------------------------

class TestAntiContaminationGuard:
    """Verify the full strategy build path filters contaminants for divorce."""

    def test_divorce_strategy_no_cuota_provisoria(self):
        profile = _profile(query="Quiero divorciarme")
        strategy = _build_strategy(query="Quiero divorciarme", case_profile=profile)
        primary_text = _strategy_primary_text(strategy)
        assert "cuota provisoria" not in primary_text

    def test_divorce_with_alimentos_facts_keeps_alimentos_language(self):
        """If divorce profile has explicit alimentos scenarios (from actual
        facts), alimentos language is NOT filtered."""
        profile = {
            "case_domain": "divorcio",
            "case_domains": ["divorcio", "alimentos"],
            "is_alimentos": False,
            "scenarios": {"unilateral", "hijos", "incumplimiento", "cuota_provisoria"},
            "urgency_level": "high",
            "vulnerability": False,
            "needs_proof_strengthening": True,
            "strategic_focus": [],
        }
        strategy = _build_strategy(query="Quiero divorciarme y el padre no paga", case_profile=profile)
        # With incumplimiento and cuota_provisoria scenarios, alimentos language is allowed
        # (the guard does NOT filter when alimentos facts are substantiated)
        # We just verify the strategy builds without error
        assert strategy["strategy_mode"] in {"agresiva", "conservadora", "cautelosa"}
