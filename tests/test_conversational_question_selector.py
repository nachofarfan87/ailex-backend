from __future__ import annotations

from app.services.conversational.question_selector import (
    build_primary_question_for_alimentos,
    build_question_candidates_for_alimentos,
    derive_canonical_signals,
    select_best_question,
)


def _context(
    query_text: str,
    *,
    known_facts: dict | None = None,
    missing_facts: list[str] | None = None,
    asked_questions: list[str] | None = None,
) -> dict:
    return {
        "query_text": query_text,
        "known_facts": known_facts or {},
        "missing_facts": missing_facts or [],
        "clarification_context": {
            "asked_questions": asked_questions or [],
        },
    }


def test_canonical_signal_detects_non_payment_language():
    signals = derive_canonical_signals("no me pasa plata hace meses")
    assert signals["incumplimiento_aportes"] is True


def test_canonical_signal_detects_start_intent():
    signals = derive_canonical_signals("quiero pedir alimentos, que tengo que hacer")
    assert signals["intencion_inicio_reclamo"] is True


def test_canonical_signal_detects_location_problem():
    signals = derive_canonical_signals("no se nada de el y quiero reclamar")
    assert signals["problema_ubicacion"] is True


def test_candidate_builder_scores_high_value_question_for_starting_claim():
    candidates = build_question_candidates_for_alimentos(
        _context("Quiero iniciar una demanda de alimentos por mi hija de 13 años")
    )

    top = select_best_question(candidates)
    assert top is not None
    assert top.key in {"aportes_actuales", "convivencia"}
    assert "edad" not in top.text.lower()
    assert "hijos" not in top.text.lower()


def test_real_language_non_payment_penalizes_current_support_question():
    candidates = build_question_candidates_for_alimentos(
        _context("No me pasa plata hace meses")
    )

    by_key = {item.key: item for item in candidates}
    assert "aportes_actuales" not in by_key or by_key["aportes_actuales"].score <= 0
    assert select_best_question(candidates).key in {"convivencia", "urgencia", "notificacion", "ingresos"}


def test_non_compliance_plus_intent_does_not_generate_redundant_question():
    candidates = build_question_candidates_for_alimentos(
        _context("No cumple y quiero reclamar alimentos")
    )

    top = select_best_question(candidates)
    assert top is not None
    assert top.key != "aportes_actuales"


def test_unknown_address_penalizes_notification_question_as_redundant():
    candidates = build_question_candidates_for_alimentos(
        _context("No sé nada de él y quiero reclamar")
    )

    keys = {item.key for item in candidates}
    assert "notificacion" not in keys


def test_broad_start_intent_detects_how_to_start_claim():
    selection = build_primary_question_for_alimentos(
        _context("Quiero pedir alimentos, ¿qué tengo que hacer?")
    )

    assert selection is not None
    assert selection["selected"]["key"] in {"aportes_actuales", "convivencia", "notificacion", "ingresos"}


def test_my_child_does_not_resolve_convivencia_if_text_says_lives_with_other_parent():
    candidates = build_question_candidates_for_alimentos(
        _context("Es mi hija pero vive con su padre")
    )

    keys = {item.key for item in candidates}
    assert "convivencia" not in keys


def test_already_asked_question_is_penalized():
    candidates = build_question_candidates_for_alimentos(
        _context(
            "Quiero iniciar una demanda de alimentos",
            asked_questions=["¿El otro progenitor está aportando algo actualmente?"],
        )
    )

    best = select_best_question(candidates)
    assert best is not None
    assert best.key != "aportes_actuales"


def test_selection_returns_serializable_metadata_with_breakdown():
    selection = build_primary_question_for_alimentos(
        _context("Quiero iniciar una demanda de alimentos")
    )

    assert selection is not None
    assert selection["selected"]["text"]
    assert selection["selected"]["score"] > 0
    assert selection["candidates_considered"] >= 1
    breakdown = selection["selected"]["score_breakdown"]
    assert isinstance(breakdown, dict)
    assert breakdown["base"] > 0
    assert breakdown["total"] == selection["selected"]["score"]
