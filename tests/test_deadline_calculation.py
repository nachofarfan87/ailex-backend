"""
Tests for V1 deadline calculation — business days, edge cases, and integration
with infer_deadlines / analyze_notification.
"""

import pytest
from datetime import date

from app.modules.legal.business_days import add_business_days
from app.modules.legal.calculate_deadline import calculate_procedural_deadline
from app.modules.legal.infer_deadlines import infer_deadlines
from app.modules.legal.analyze_notification import analyze_notification


# ---------------------------------------------------------------------------
# business_days.py
# ---------------------------------------------------------------------------

def test_add_business_days_simple_weekday():
    # Friday March 6 + 5 business days = Friday March 13
    # Mon 9, Tue 10, Wed 11, Thu 12, Fri 13
    result = add_business_days(date(2026, 3, 6), 5)
    assert result == date(2026, 3, 13)


def test_add_business_days_spans_weekend():
    # Friday March 6 + 1 business day = Monday March 9 (skips Sat/Sun)
    result = add_business_days(date(2026, 3, 6), 1)
    assert result == date(2026, 3, 9)


def test_add_business_days_zero():
    start = date(2026, 3, 6)
    assert add_business_days(start, 0) == start


def test_add_business_days_from_monday():
    # Monday March 9 + 3 business days = Thursday March 12
    result = add_business_days(date(2026, 3, 9), 3)
    assert result == date(2026, 3, 12)


# ---------------------------------------------------------------------------
# calculate_deadline.py
# ---------------------------------------------------------------------------

def test_calculate_procedural_deadline_5_dias_weekday():
    result = calculate_procedural_deadline(
        plazo_dias=5,
        notification_date="06/03/2026",
        is_procedural=True,
        jurisdiction="Jujuy",
    )
    assert result["estimated_due_date"] == "13/03/2026"
    assert result["deadline_type"] == "habiles"
    assert result["deadline_basis"] == "plazo textual expreso + computo habil estandar"
    assert result["deadline_warning"]
    assert "feriados" in result["deadline_warning"].lower()


def test_calculate_procedural_deadline_spans_weekend():
    # Friday March 6 + 3 business days = Wednesday March 11
    # (skip Sat/Sun: Mon 9, Tue 10, Wed 11)
    result = calculate_procedural_deadline(
        plazo_dias=3,
        notification_date="06/03/2026",
        is_procedural=True,
    )
    assert result["estimated_due_date"] == "11/03/2026"
    assert result["deadline_type"] == "habiles"


def test_calculate_procedural_deadline_missing_notification_date():
    result = calculate_procedural_deadline(
        plazo_dias=5,
        notification_date=None,
    )
    assert result["estimated_due_date"] == ""
    assert result["deadline_type"] == ""
    assert result["deadline_warning"]
    assert "fecha de notificacion" in result["deadline_warning"].lower()


def test_calculate_procedural_deadline_missing_plazo():
    result = calculate_procedural_deadline(
        plazo_dias=None,
        notification_date="06/03/2026",
    )
    assert result["estimated_due_date"] == ""
    assert "sin plazo" in result["deadline_warning"].lower()


def test_calculate_procedural_deadline_corrido():
    # Calendar days: March 6 + 5 = March 11 (includes weekend)
    result = calculate_procedural_deadline(
        plazo_dias=5,
        notification_date="06/03/2026",
        is_procedural=False,
    )
    assert result["estimated_due_date"] == "11/03/2026"
    assert result["deadline_type"] == "corridos"


def test_calculate_procedural_deadline_iso_date():
    result = calculate_procedural_deadline(
        plazo_dias=5,
        notification_date="2026-03-06",
        is_procedural=True,
    )
    assert result["estimated_due_date"] == "13/03/2026"


# ---------------------------------------------------------------------------
# infer_deadlines.py integration
# ---------------------------------------------------------------------------

def _make_elements(notification_date=None, procedural_action="traslado", normalized_text=""):
    return {
        "normalized_text": normalized_text,
        "notification_date": notification_date,
        "hearing_date": "",
        "document_detected": "cedula judicial",
        "procedural_action": procedural_action,
        "procedural_action_slug": "traslado",
    }


def test_infer_deadlines_with_explicit_deadline_and_notification_date():
    elements = _make_elements(
        notification_date="06/03/2026",
        normalized_text="Corrase traslado de la demanda por 5 dias.",
    )
    result = infer_deadlines(elements, jurisdiction="Jujuy")
    assert result["estimated_due_date"] == "13/03/2026"
    assert result["deadline_type"] == "habiles"
    assert result["deadline_basis"]
    assert result["deadline_warning"]


def test_infer_deadlines_missing_notification_date():
    elements = _make_elements(
        notification_date=None,
        normalized_text="Corrase traslado de la demanda por 5 dias.",
    )
    result = infer_deadlines(elements)
    assert result["estimated_due_date"] == ""
    assert result["deadline_warning"]


def test_infer_deadlines_missing_explicit_deadline():
    elements = _make_elements(
        notification_date="06/03/2026",
        normalized_text="Notifiquese la integracion del tribunal.",
        procedural_action="integracion del tribunal",
    )
    result = infer_deadlines(elements)
    assert result["estimated_due_date"] == ""
    assert result["deadline_warning"]


# ---------------------------------------------------------------------------
# analyze_notification — non-procedural text must not force due-date
# ---------------------------------------------------------------------------

async def test_analyze_notification_non_procedural_text_no_due_date():
    memo = await analyze_notification(
        text="Se agrega al expediente el escrito de parte.",
        jurisdiction="Jujuy",
    )
    # No explicit deadline in text → no estimated_due_date
    assert memo["estimated_due_date"] == ""
    assert memo["deadline"] == ""
