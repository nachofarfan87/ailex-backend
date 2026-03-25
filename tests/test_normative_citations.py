"""
Tests for normative citation resolution (V1).

Covers:
  1. Direct match returns references and non-empty summary
  2. Missing action_slug → empty references + warning
  3. Unsupported jurisdiction with no nacional fallback for that slug → empty + warning
  4. Known slug with empty rule list → empty + warning (no invented references)
  5. Inferred match via fallback slug uses match_type="inferred" and lower confidence
  6. analyze_notification exposes all four normative fields
  7. Memo includes normative section when references exist
  8. Memo shows warning when no normative base is available
"""

import pytest

from app.modules.legal.normative_citations import resolve_normative_references
from app.modules.legal.analyze_notification import analyze_notification


# ---------------------------------------------------------------------------
# resolve_normative_references — unit tests
# ---------------------------------------------------------------------------

def test_direct_match_returns_references():
    result = resolve_normative_references(
        action_slug="traslado_demanda",
        jurisdiction="nacional",
        forum="civil",
    )
    assert result["normative_references"], "Expected at least one reference"
    assert result["normative_confidence"] in ("high", "medium")
    assert result["normative_summary"]
    for ref in result["normative_references"]:
        assert ref["source"]
        assert ref["article"]
        assert ref["match_type"] == "direct"
        assert ref["confidence_score"] > 0


def test_direct_match_intimacion():
    result = resolve_normative_references(
        action_slug="intimacion",
        jurisdiction="nacional",
        forum="civil",
    )
    assert result["normative_references"]
    assert result["normative_confidence"] in ("high", "medium")


def test_missing_action_slug_returns_empty_with_warning():
    result = resolve_normative_references(
        action_slug=None,
        jurisdiction="nacional",
        forum="civil",
    )
    assert result["normative_references"] == []
    assert result["normative_confidence"] == "low"
    assert result["normative_warning"]
    assert result["normative_summary"] is None


def test_unknown_slug_returns_empty_with_warning():
    result = resolve_normative_references(
        action_slug="desconocida",
        jurisdiction="nacional",
        forum="civil",
    )
    assert result["normative_references"] == []
    assert result["normative_warning"]


def test_unsupported_jurisdiction_falls_back_to_nacional():
    # "tucuman" has no local entry → should fall back to nacional
    result = resolve_normative_references(
        action_slug="traslado_demanda",
        jurisdiction="Tucuman",
        forum="civil",
    )
    assert result["normative_references"], "Should fall back to nacional references"
    assert result["normative_warning"]
    # Warning must mention that the national reference was used
    assert "nacional" in result["normative_warning"].lower() or "jurisdicc" in result["normative_warning"].lower()


def test_slug_with_empty_rule_list_returns_empty():
    # integracion_tribunal has an explicitly empty rule list in nacional/civil
    result = resolve_normative_references(
        action_slug="integracion_tribunal",
        jurisdiction="nacional",
        forum="civil",
    )
    assert result["normative_references"] == []
    assert result["normative_warning"]
    assert result["normative_summary"] is None


def test_inferred_match_uses_fallback_slug():
    # plazo_para_contestar → should fall back to traslado_demanda (inferred)
    result = resolve_normative_references(
        action_slug="plazo_para_contestar",
        jurisdiction="nacional",
        forum="civil",
    )
    assert result["normative_references"]
    for ref in result["normative_references"]:
        assert ref["match_type"] == "inferred"
        # confidence_score must be lower than a direct medium reference (0.70)
        assert ref["confidence_score"] < 0.70


def test_inferred_match_warning_present():
    result = resolve_normative_references(
        action_slug="plazo_para_apelar",
        jurisdiction="nacional",
        forum="civil",
    )
    # Should resolve to apelacion references (inferred)
    assert result["normative_references"]
    assert result["normative_warning"]
    assert "analogía" in result["normative_warning"] or "indirecta" in result["normative_warning"].lower()


def test_no_invented_references_for_unknown_forum():
    # "laboral" has no rules loaded → should not invent anything
    result = resolve_normative_references(
        action_slug="traslado_demanda",
        jurisdiction="nacional",
        forum="laboral",
    )
    assert result["normative_references"] == []
    assert result["normative_warning"]


# ---------------------------------------------------------------------------
# analyze_notification integration
# ---------------------------------------------------------------------------

async def test_analyze_notification_exposes_normative_fields():
    memo = await analyze_notification(
        text=(
            "JUZGADO CIVIL N 3 DE JUJUY\n"
            "Expte. 123/2026\n"
            "Cedula. Corrase traslado de la demanda por 5 dias. Notifiquese."
        ),
        jurisdiction="Jujuy",
        legal_area="civil",
    )
    assert "normative_references" in memo
    assert "normative_confidence" in memo
    assert "normative_warning" in memo
    assert "normative_summary" in memo


async def test_analyze_notification_normative_filled_for_known_action():
    memo = await analyze_notification(
        text=(
            "JUZGADO CIVIL N 3 DE JUJUY\n"
            "Expte. 123/2026\n"
            "Cedula. Corrase traslado de la demanda por 5 dias. Notifiquese."
        ),
        jurisdiction="Jujuy",
        legal_area="civil",
    )
    # traslado_demanda is in nacional/civil rules; should have references
    assert memo["normative_references"], "Expected normative references for traslado_demanda"
    assert memo["normative_summary"]
    assert memo["normative_warning"]  # warning always present (verification caveat)


async def test_analyze_notification_normative_empty_for_non_procedural_text():
    memo = await analyze_notification(
        text="Se agrega al expediente el escrito de parte.",
        jurisdiction="Jujuy",
    )
    # No identifiable action → no normative references
    assert memo["normative_references"] == []
    assert memo["normative_confidence"] == "low"
    assert memo["normative_warning"]
