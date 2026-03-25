"""Tests for legal_engine.tag_inference — structured tag detection."""

from legal_engine.tag_inference import (
    TagSignals,
    TagRule,
    collect_tag_signals,
    infer_model_tags,
    _rule_fires,
)


# ---------------------------------------------------------------------------
# collect_tag_signals
# ---------------------------------------------------------------------------

def test_collect_tag_signals_extracts_fields():
    signals = collect_tag_signals(
        request_query="Reclamo de alimentos",
        classification={"action_slug": "alimentos_hijos", "action_label": "Alimentos"},
        case_structure={"main_claim": "Reclamo alimentario", "summary": "Caso de familia"},
        normative_reasoning={"requirements": ["Acreditar necesidad"], "inferences": ["Se presume necesidad"]},
        procedural_strategy={"strategic_notes": "Urgencia por falta de pago", "next_steps": ["Pedir cuota provisoria"]},
        case_theory={"recommended_line_of_action": ["Demandar"], "evidentiary_needs": ["Recibos"]},
        conflict_evidence={"core_dispute": "Incumplimiento", "most_vulnerable_point": "Sin prueba"},
    )
    assert signals.query == "reclamo de alimentos"
    assert signals.action_slug == "alimentos_hijos"
    assert "acreditar necesidad" in signals.requirements_text
    assert "urgencia por falta de pago" in signals.strategic_notes


def test_collect_tag_signals_handles_empty():
    signals = collect_tag_signals("", {}, {}, {}, {}, {}, {})
    assert signals.query == ""
    assert signals.action_slug == ""
    assert signals.facts_text == ""


# ---------------------------------------------------------------------------
# Action-slug structural tags
# ---------------------------------------------------------------------------

def test_alimentos_hijos_slug_emits_structural_tags():
    signals = TagSignals(action_slug="alimentos_hijos")
    tags = infer_model_tags(signals)
    assert "alimentos_hijos" in tags
    assert "estructura_base" in tags


def test_unknown_slug_no_structural_tags():
    signals = TagSignals(action_slug="divorcio")
    tags = infer_model_tags(signals)
    assert "alimentos_hijos" not in tags
    assert "estructura_base" not in tags


# ---------------------------------------------------------------------------
# Rule-based inference: positive cases
# ---------------------------------------------------------------------------

def test_incumplimiento_detected_in_query():
    signals = TagSignals(query="el demandado no paga alimentos")
    tags = infer_model_tags(signals)
    assert "incumplimiento" in tags


def test_incumplimiento_detected_in_facts():
    signals = TagSignals(facts_text="existe incumplimiento reiterado del obligado")
    tags = infer_model_tags(signals)
    assert "incumplimiento" in tags


def test_urgencia_detected():
    signals = TagSignals(query="pedido urgente de alimentos provisorios")
    tags = infer_model_tags(signals)
    assert "urgencia" in tags


def test_vulnerabilidad_detected():
    signals = TagSignals(core_dispute="situacion de vulnerabilidad economica")
    tags = infer_model_tags(signals)
    assert "vulnerabilidad" in tags


def test_hijo_mayor_estudiante_detected():
    signals = TagSignals(query="alimentos hijo mayor estudiante universitario")
    tags = infer_model_tags(signals)
    assert "hijo_mayor_estudiante" in tags


def test_ascendientes_detected():
    signals = TagSignals(query="reclamo contra abuelo paterno")
    tags = infer_model_tags(signals)
    assert "ascendientes" in tags


def test_subsidiariedad_detected():
    signals = TagSignals(requirements_text="acreditar subsidiariedad del reclamo")
    tags = infer_model_tags(signals)
    assert "subsidiariedad" in tags


def test_cuota_provisoria_detected():
    signals = TagSignals(next_steps_text="solicitar cuota provisoria")
    tags = infer_model_tags(signals)
    assert "cuota_provisoria" in tags


def test_violencia_detected():
    signals = TagSignals(facts_text="contexto de violencia familiar comprobada")
    tags = infer_model_tags(signals)
    assert "violencia" in tags
    assert "hechos_sensibles" in tags


def test_bajos_recursos_detected():
    signals = TagSignals(facts_text="la actora carece de recursos economicos")
    tags = infer_model_tags(signals)
    assert "bajos_recursos" in tags


def test_defensoria_detected():
    signals = TagSignals(facts_text="se presenta con patrocinio de defensoria")
    tags = infer_model_tags(signals)
    assert "defensoria" in tags


def test_embargo_detected():
    signals = TagSignals(recommended_actions_text="solicitar embargo preventivo")
    tags = infer_model_tags(signals)
    assert "embargo" in tags


# ---------------------------------------------------------------------------
# Precision: false-positive guards
# ---------------------------------------------------------------------------

def test_hijo_mayor_excludes_ascendientes_context():
    """hijo_mayor_estudiante should NOT fire when ascendientes context is present."""
    signals = TagSignals(query="reclamo contra abuelo por alimentos")
    tags = infer_model_tags(signals)
    # ascendientes should fire
    assert "ascendientes" in tags
    assert "hijo_mayor_estudiante" not in tags


def test_ambiguous_abuelo_hijo_mayor_neither_fires():
    """When both 'abuelo' and 'hijo mayor' appear, exclusion guards block both."""
    signals = TagSignals(query="reclamo contra abuelo por hijo mayor")
    tags = infer_model_tags(signals)
    # Both exclusion guards fire: ascendientes excludes "hijo mayor",
    # hijo_mayor_estudiante excludes "abuelo".  Neither should emit.
    assert "ascendientes" not in tags
    assert "hijo_mayor_estudiante" not in tags


def test_ascendientes_excludes_hijo_mayor_context():
    """ascendientes should NOT fire when hijo_mayor context dominates."""
    signals = TagSignals(query="alimentos para mayor estudiante universitario")
    tags = infer_model_tags(signals)
    assert "hijo_mayor_estudiante" in tags
    assert "ascendientes" not in tags


def test_no_false_positive_urgencia_from_unrelated():
    """Should not detect urgencia from unrelated text."""
    signals = TagSignals(query="reclamo de alimentos ordinario sin apuro")
    tags = infer_model_tags(signals)
    assert "urgencia" not in tags


def test_no_false_positive_embargo_from_query_only():
    """embargo only fires from specific signal fields, not any text."""
    signals = TagSignals(query="demanda de alimentos comunes")
    tags = infer_model_tags(signals)
    assert "embargo" not in tags


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_tags_are_deduplicated():
    signals = TagSignals(
        query="incumplimiento",
        main_claim="incumplimiento del alimentante",
        core_dispute="incumplimiento reiterado",
    )
    tags = infer_model_tags(signals)
    assert tags.count("incumplimiento") == 1


# ---------------------------------------------------------------------------
# _rule_fires isolation tests
# ---------------------------------------------------------------------------

def test_rule_fires_or_mode():
    rule = TagRule(tag="test", markers=("alpha", "beta"), signal_fields=("query",))
    assert _rule_fires(rule, TagSignals(query="this has alpha"))
    assert _rule_fires(rule, TagSignals(query="this has beta"))
    assert not _rule_fires(rule, TagSignals(query="this has nothing"))


def test_rule_fires_and_mode():
    rule = TagRule(tag="test", markers=("alpha", "beta"), signal_fields=("query",), require_all=True)
    assert _rule_fires(rule, TagSignals(query="alpha and beta together"))
    assert not _rule_fires(rule, TagSignals(query="only alpha here"))


def test_rule_fires_exclusion():
    rule = TagRule(tag="test", markers=("alpha",), signal_fields=("query",), exclude_markers=("gamma",))
    assert _rule_fires(rule, TagSignals(query="has alpha"))
    assert not _rule_fires(rule, TagSignals(query="has alpha and gamma"))


def test_rule_fires_all_fields_when_empty():
    rule = TagRule(tag="test", markers=("alpha",), signal_fields=())
    assert _rule_fires(rule, TagSignals(evidentiary_needs_text="alpha"))
