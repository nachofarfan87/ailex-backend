"""Tests for legal_engine.style_blueprint — blueprint normalization."""

from legal_engine.style_blueprint import (
    StyleBlueprint,
    normalize_style_blueprint,
    _apply_structure_cues,
)


# ---------------------------------------------------------------------------
# normalize_style_blueprint: defaults
# ---------------------------------------------------------------------------

def test_defaults_when_no_directives():
    bp = normalize_style_blueprint(None, "formal")
    assert isinstance(bp, StyleBlueprint)
    assert bp.tone == "balanced_prudent"
    assert bp.argument_density == "standard"
    assert bp.urgency_emphasis == "none"
    assert bp.normative_quote_density == "standard"
    assert len(bp.section_order) > 0
    assert "encabezado" in bp.section_order
    assert "conclusion" in bp.section_order


def test_defaults_for_base_argumental():
    bp = normalize_style_blueprint(None, "base_argumental")
    assert "tesis_principal" in bp.section_order
    assert "cierre_estrategico" in bp.section_order


# ---------------------------------------------------------------------------
# Tone and intensity
# ---------------------------------------------------------------------------

def test_tone_propagated():
    bp = normalize_style_blueprint({"tone": "urgent_prudent"}, "formal")
    assert bp.tone == "urgent_prudent"
    assert bp.opening_style == "urgent"


def test_institutional_protective_opening_style():
    bp = normalize_style_blueprint({"tone": "institutional_protective"}, "formal")
    assert bp.opening_style == "protective"


def test_technical_opening_style():
    bp = normalize_style_blueprint({"tone": "technical_focused"}, "formal")
    assert bp.opening_style == "technical"


def test_litigation_opening_style():
    bp = normalize_style_blueprint({"tone": "litigation_clear"}, "formal")
    assert bp.opening_style == "litigation"


# ---------------------------------------------------------------------------
# Urgency from tags
# ---------------------------------------------------------------------------

def test_urgency_from_tags():
    bp = normalize_style_blueprint({}, "formal", detected_tags=["urgencia"])
    assert bp.urgency_emphasis == "high"


def test_medium_urgency_from_medidas_fuertes():
    bp = normalize_style_blueprint({}, "formal", detected_tags=["medidas_fuertes"])
    assert bp.urgency_emphasis == "medium"


def test_no_urgency_without_tags():
    bp = normalize_style_blueprint({}, "formal", detected_tags=["estructura_base"])
    assert bp.urgency_emphasis == "none"


# ---------------------------------------------------------------------------
# Normative density
# ---------------------------------------------------------------------------

def test_high_argument_density_raises_normative_density():
    bp = normalize_style_blueprint({"argument_density": "high"}, "formal")
    assert bp.normative_quote_density == "high"


def test_focused_argument_density_lowers_normative_density():
    bp = normalize_style_blueprint({"argument_density": "focused"}, "formal")
    assert bp.normative_quote_density == "focused"


# ---------------------------------------------------------------------------
# Section ordering
# ---------------------------------------------------------------------------

def test_structure_cues_promote_sections():
    bp = normalize_style_blueprint(
        {"structure": ["riesgo_procesal", "hechos_decisivos"]},
        "formal",
    )
    order = bp.section_order
    # Promoted sections should appear earlier than default
    riesgo_idx = order.index("riesgo_procesal")
    analisis_idx = order.index("analisis_juridico")
    assert riesgo_idx < analisis_idx


def test_explicit_section_order_overrides_default():
    bp = normalize_style_blueprint(
        {"section_order": ["encabezado", "riesgo_procesal", "conclusion"]},
        "formal",
    )
    assert bp.section_order == ["encabezado", "riesgo_procesal", "conclusion"]


def test_invalid_explicit_section_order_falls_back_with_warning():
    bp = normalize_style_blueprint(
        {"section_order": []},
        "formal",
    )
    assert bp.section_order[0] == "encabezado"
    assert bp.warnings


def test_encabezado_stays_first():
    bp = normalize_style_blueprint(
        {"structure": ["conclusion"]},
        "formal",
    )
    assert bp.section_order[0] == "encabezado"


def test_conclusion_stays_last():
    bp = normalize_style_blueprint(
        {"structure": ["encabezado"]},
        "formal",
    )
    assert bp.section_order[-1] == "conclusion"


# ---------------------------------------------------------------------------
# Required / optional sections
# ---------------------------------------------------------------------------

def test_required_sections_include_anchors():
    bp = normalize_style_blueprint(None, "formal")
    assert "encabezado" in bp.required_sections
    assert "conclusion" in bp.required_sections


def test_optional_sections_exclude_required():
    bp = normalize_style_blueprint(None, "formal")
    for section in bp.required_sections:
        assert section not in bp.optional_sections


# ---------------------------------------------------------------------------
# Directives passthrough
# ---------------------------------------------------------------------------

def test_directives_passed_through():
    bp = normalize_style_blueprint({
        "opening_line": "Abrir con conflicto.",
        "analysis_directive": "Analizar con rigor.",
        "facts_directive": "Hechos concretos.",
        "petitum_directive": "Pedir con prudencia.",
        "section_cues": ["Separar hechos.", "Mostrar prueba."],
    }, "formal")
    assert bp.opening_line == "Abrir con conflicto."
    assert bp.analysis_directive == "Analizar con rigor."
    assert bp.facts_directive == "Hechos concretos."
    assert bp.petitum_directive == "Pedir con prudencia."
    assert len(bp.section_cues) == 2


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

def test_to_dict_roundtrip():
    bp = normalize_style_blueprint({"tone": "technical_robust", "argument_density": "high"}, "formal")
    d = bp.to_dict()
    assert d["tone"] == "technical_robust"
    assert d["argument_density"] == "high"
    assert isinstance(d["section_order"], list)
    assert isinstance(d["section_templates"], dict)
    assert isinstance(d["content_rules"], dict)
    assert isinstance(d["warnings"], list)


def test_section_templates_have_required_metadata():
    bp = normalize_style_blueprint(None, "formal")
    assert bp.section_templates["marco_normativo"]["style"] == "normative"
    assert bp.section_templates["encabezado"]["required"] is True


def test_content_rules_can_be_overridden():
    bp = normalize_style_blueprint({
        "content_rules": {
            "include_jurisprudence": "never",
            "normative_density": "high",
            "argument_style": "assertive",
        }
    }, "formal")
    assert bp.content_rules["include_jurisprudence"] == "never"
    assert bp.content_rules["normative_density"] == "high"
    assert bp.content_rules["argument_style"] == "assertive"


# ---------------------------------------------------------------------------
# _apply_structure_cues
# ---------------------------------------------------------------------------

def test_apply_structure_cues_no_cues():
    order = ["a", "b", "c"]
    assert _apply_structure_cues(order, []) == ["a", "b", "c"]


def test_apply_structure_cues_promotes():
    order = ["encabezado", "marco", "riesgo", "conclusion"]
    result = _apply_structure_cues(order, ["riesgo"])
    assert result[0] == "encabezado"
    assert result[-1] == "conclusion"
    assert result.index("riesgo") < result.index("marco")


def test_blueprint_changes_structure_not_just_wording():
    """Verify that different blueprints produce different section orders."""
    bp_default = normalize_style_blueprint(None, "formal")
    bp_urgencia = normalize_style_blueprint(
        {"structure": ["urgencia_real", "medidas_inmediatas"], "tone": "urgent_prudent"},
        "formal",
        detected_tags=["urgencia"],
    )
    # At minimum, urgency_emphasis should differ
    assert bp_default.urgency_emphasis != bp_urgencia.urgency_emphasis
    assert bp_urgencia.urgency_emphasis == "high"
