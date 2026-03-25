from __future__ import annotations

from legal_engine.procedural_case_state import ProceduralCaseStateBuilder
from legal_engine.procedural_timeline_builder import ProceduralTimelineBuilder


def _state_from_events(events: list[dict]) -> dict:
    timeline = ProceduralTimelineBuilder().build(events)
    return ProceduralCaseStateBuilder().build(timeline).to_dict()


def test_detects_phase_for_service_pending_case():
    state = _state_from_events(
        [
            {"title": "Demanda presentada", "date": "2024-01-05"},
            {"title": "Admítase demanda", "date": "2024-01-10"},
            {"title": "Corrase traslado y notifíquese", "date": "2024-01-11"},
        ]
    )

    assert state["procedural_phase"] == "service"
    assert state["service_status"] == "pending"
    assert state["blocking_factor"] == "service"


def test_competence_issue_drives_legal_blocking_factor():
    state = _state_from_events(
        [
            {"title": "Demanda de alimentos", "date": "2024-01-05"},
            {"title": "Cuota provisoria", "summary": "Se fija cuota provisoria", "date": "2024-01-06"},
            {"title": "Incompetencia", "summary": "Se declara incompetencia territorial", "date": "2024-01-20"},
        ]
    )

    assert state["procedural_phase"] == "initial"
    assert state["blocking_factor"] == "competence"
    assert state["procedural_status"] == "blocked_by_competence"
    assert state["procedural_risk_score"] >= 0.55


def test_friction_increases_with_failed_hearing_and_active_defense():
    state = _state_from_events(
        [
            {"title": "Demanda de alimentos", "date": "2024-01-10"},
            {"title": "Admítase demanda", "date": "2024-01-15"},
            {"title": "Cédula diligenciada", "date": "2024-01-20"},
            {"title": "Audiencia fallida por incomparecencia", "date": "2024-02-10"},
            {"title": "Contestación de demanda", "date": "2024-02-18"},
        ]
    )

    assert state["procedural_phase"] == "defense"
    assert state["defense_status"] == "active"
    assert state["blocking_factor"] == "evidence"
    assert state["litigation_friction_score"] >= 0.35


def test_distinguishes_operational_problem_from_legal_problem():
    operational = _state_from_events(
        [
            {"title": "Demanda presentada", "date": "2024-01-05"},
            {"title": "Admítase demanda", "date": "2024-01-10"},
            {"title": "Oficio librado al banco", "date": "2024-01-20"},
            {"title": "Oficio librado al banco", "date": "2024-01-20"},
            {"title": "Téngase presente", "date": "2024-01-21"},
        ]
    )
    legal = _state_from_events(
        [
            {"title": "Demanda presentada", "date": "2024-01-05"},
            {"title": "Incompetencia", "date": "2024-01-12"},
        ]
    )

    assert operational["blocking_factor"] == "administrative_delay"
    assert legal["blocking_factor"] == "competence"


def test_identifies_default_and_pre_judgment_state():
    state = _state_from_events(
        [
            {"title": "Demanda de aumento de cuota", "date": "2024-01-10"},
            {"title": "Admítase demanda", "date": "2024-01-12"},
            {"title": "Cédula diligenciada", "date": "2024-01-20"},
            {"title": "Decaimiento del derecho de contestar demanda", "date": "2024-02-10"},
        ]
    )

    assert state["procedural_phase"] == "pre_judgment"
    assert state["defense_status"] == "defaulted"
    assert state["procedural_status"] == "ready_for_decision"


def test_timeline_builder_output_is_compatible():
    timeline = ProceduralTimelineBuilder().build(
        [
            {"title": "Sentencia", "date": "2024-05-10"},
            {"title": "Oficio librado al banco", "date": "2024-05-15"},
        ]
    )
    state = ProceduralCaseStateBuilder().build(timeline).to_dict()

    assert state["procedural_phase"] == "enforcement"
    assert state["enforcement_signal"] == "active"
    assert any(note.startswith("phase=") for note in state["notes"])
