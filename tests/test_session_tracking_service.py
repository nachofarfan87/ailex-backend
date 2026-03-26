from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.session_analytics import get_session_summary, track_session_event
from app.models.session_analytics import AnalyticsSession, AnalyticsSessionEvent
from app.services.session_tracking_service import (
    build_summary,
    ensure_session_id,
    record_event,
    track_legal_query_cycle,
)
from app.db.database import Base
import app.db.user_models  # noqa: F401


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_new_conversation_gets_stable_session_id(db_session):
    session_id = ensure_session_id(None)
    track_legal_query_cycle(
        db_session,
        session_id=session_id,
        user_id=None,
        query="Quiero divorciarme",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )

    session = db_session.get(AnalyticsSession, session_id)
    assert session is not None
    assert session.session_id == session_id
    assert session.total_user_turns == 1
    assert session.total_assistant_turns == 1


def test_same_conversation_reuses_session_id(db_session):
    session_id = "sess-reused"
    track_legal_query_cycle(
        db_session,
        session_id=session_id,
        user_id=None,
        query="Quiero divorciarme",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )
    track_legal_query_cycle(
        db_session,
        session_id=session_id,
        user_id=None,
        query="No hay hijos",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Quiero divorciarme"}},
    )

    session = db_session.get(AnalyticsSession, session_id)
    assert session.total_user_turns == 2
    assert session.total_assistant_turns == 2
    assert session.closure_reached is True


def test_reset_marks_session_abandoned_and_new_session_starts(db_session):
    old_session_id = "sess-old"
    track_legal_query_cycle(
        db_session,
        session_id=old_session_id,
        user_id=None,
        query="Consulta",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )
    record_event(db_session, session_id=old_session_id, event_type="session_reset", payload={"total_turns": 2})

    new_session_id = ensure_session_id(None)
    assert new_session_id != old_session_id
    assert db_session.get(AnalyticsSession, old_session_id).status == "abandoned"


def test_track_legal_query_cycle_registers_clarification_entered_and_exited(db_session):
    session_id = "sess-clarification"
    track_legal_query_cycle(
        db_session,
        session_id=session_id,
        user_id=None,
        query="Quiero divorciarme",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )
    track_legal_query_cycle(
        db_session,
        session_id=session_id,
        user_id=None,
        query="No hay hijos",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Quiero divorciarme"}},
    )

    event_types = [event.event_type for event in db_session.query(AnalyticsSessionEvent).filter_by(session_id=session_id).all()]
    assert "clarification_entered" in event_types
    assert "clarification_exited" in event_types
    assert "closure_reached" in event_types


def test_quick_reply_clicked_and_submitted_are_recorded(db_session):
    record_event(
        db_session,
        session_id="sess-quick",
        event_type="quick_reply_clicked",
        payload={"selected_option": "Unilateral"},
    )
    track_legal_query_cycle(
        db_session,
        session_id="sess-quick",
        user_id=None,
        query="Es unilateral",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={"quick_reply": {"selected_option": "Unilateral", "submitted_text": "Es unilateral"}},
    )

    event_types = [event.event_type for event in db_session.query(AnalyticsSessionEvent).filter_by(session_id="sess-quick").all()]
    assert "quick_reply_clicked" in event_types
    assert "quick_reply_submitted" in event_types


def test_summary_returns_consistent_aggregates(db_session):
    track_legal_query_cycle(
        db_session,
        session_id="sess-1",
        user_id=None,
        query="Quiero divorciarme",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )
    track_legal_query_cycle(
        db_session,
        session_id="sess-1",
        user_id=None,
        query="No hay hijos",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Quiero divorciarme"}},
    )
    record_event(
        db_session,
        session_id="sess-2",
        event_type="quick_reply_clicked",
        payload={"selected_option": "Demandado"},
        case_domain="alimentos",
        jurisdiction="jujuy",
    )
    track_legal_query_cycle(
        db_session,
        session_id="sess-2",
        user_id=None,
        query="Soy demandado",
        jurisdiction="jujuy",
        case_domain="alimentos",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={"quick_reply": {"selected_option": "Demandado", "submitted_text": "Soy demandado"}},
    )
    session_two = db_session.get(AnalyticsSession, "sess-2")
    session_two.started_at = session_two.started_at - timedelta(seconds=10)
    session_two.first_advice_at = session_two.started_at + timedelta(seconds=5)
    db_session.commit()

    summary = build_summary(db_session)

    assert summary["total_sessions"] == 2
    assert summary["completed_sessions"] == 1
    assert summary["clarification_rate"] > 0
    assert summary["closure_rate"] > 0
    assert summary["quick_reply_rate"] > 0
    assert summary["effective_sessions_rate"] > 0
    assert summary["top_case_domains"][0]["value"] in {"divorcio", "alimentos"}
    assert summary["top_clarification_questions"]
    assert summary["top_quick_replies"]
    assert "insights" in summary
    assert "recommended_actions" in summary
    assert "primary_action" in summary


def test_effective_sessions_rate_is_computed_correctly(db_session):
    track_legal_query_cycle(
        db_session,
        session_id="sess-effective-1",
        user_id=None,
        query="Consulta efectiva",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Consulta efectiva"}},
    )
    track_legal_query_cycle(
        db_session,
        session_id="sess-effective-2",
        user_id=None,
        query="Consulta incompleta",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )
    record_event(db_session, session_id="sess-effective-2", event_type="session_reset", payload={"total_turns": 2})

    summary = build_summary(db_session)

    assert summary["effective_sessions_rate"] == 0.5


def test_summary_includes_warning_insights_for_dropoff_and_low_closure(db_session):
    track_legal_query_cycle(
        db_session,
        session_id="sess-drop-1",
        user_id=None,
        query="Consulta 1",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )
    record_event(db_session, session_id="sess-drop-1", event_type="session_reset", payload={"total_turns": 2})
    track_legal_query_cycle(
        db_session,
        session_id="sess-drop-2",
        user_id=None,
        query="Consulta 2",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )
    record_event(db_session, session_id="sess-drop-2", event_type="session_reset", payload={"total_turns": 2})

    summary = build_summary(db_session)
    messages = [item["message"] for item in summary["insights"]]

    assert any("Alto abandono en turno 1" in message for message in messages)
    assert any("Baja tasa de cierre" in message for message in messages)
    assert summary["dropoff_by_turn"]


def test_summary_includes_low_effectiveness_insight(db_session):
    track_legal_query_cycle(
        db_session,
        session_id="sess-low-effective-1",
        user_id=None,
        query="Consulta cerrada sin advice",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Consulta cerrada sin advice"}},
    )

    session = db_session.get(AnalyticsSession, "sess-low-effective-1")
    session.closure_reached = True
    session.status = "completed"
    session.advice_turns = 0
    db_session.commit()

    summary = build_summary(db_session)
    insights = summary["insights"]
    messages = [item["message"] for item in insights]

    assert any("Muchas sesiones cierran sin generar orientación útil." in message for message in messages)
    low_effectiveness = next(item for item in insights if item["code"] == "low_effectiveness")
    assert low_effectiveness["suggested_action"] == "improve_advice_generation"


def test_summary_includes_combined_clarification_and_low_closure_insight(db_session):
    for index in range(4):
        session_id = f"sess-combined-clar-{index}"
        track_legal_query_cycle(
            db_session,
            session_id=session_id,
            user_id=None,
            query=f"Consulta {index}",
            jurisdiction="jujuy",
            case_domain="divorcio",
            conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
            metadata={},
        )
        record_event(db_session, session_id=session_id, event_type="session_reset", payload={"total_turns": 2})
    track_legal_query_cycle(
        db_session,
        session_id="sess-combined-clar-ok",
        user_id=None,
        query="Consulta ok",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
        metadata={},
    )

    summary = build_summary(db_session)
    insights = summary["insights"]
    messages = [item["message"] for item in insights]

    assert any("La conversacion solicita demasiada informacion pero no logra cerrar." in message for message in messages)
    combined = next(item for item in insights if item["code"] == "high_clarification_low_closure")
    assert combined["suggested_action"] == "reduce_questions"


def test_summary_includes_combined_abandonment_and_low_closure_insight(db_session):
    for index in range(2):
        session_id = f"sess-combined-abandon-{index}"
        track_legal_query_cycle(
            db_session,
            session_id=session_id,
            user_id=None,
            query=f"Consulta abandono {index}",
            jurisdiction="jujuy",
            case_domain="divorcio",
            conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
            metadata={},
        )
        record_event(db_session, session_id=session_id, event_type="session_reset", payload={"total_turns": 2})
    track_legal_query_cycle(
        db_session,
        session_id="sess-combined-abandon-closed",
        user_id=None,
        query="Consulta cerrada",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Consulta cerrada"}},
    )

    summary = build_summary(db_session)
    insights = summary["insights"]
    messages = [item["message"] for item in insights]

    assert any("Alto abandono en consultas de divorcio" in message for message in messages)
    combined = next(item for item in insights if item["code"] == "high_abandonment_low_closure")
    assert combined["suggested_action"] == "review_question_flow"


def test_insights_are_sorted_by_severity(db_session):
    for index in range(3):
        session_id = f"sess-sort-{index}"
        track_legal_query_cycle(
            db_session,
            session_id=session_id,
            user_id=None,
            query=f"Consulta sort {index}",
            jurisdiction="jujuy",
            case_domain="divorcio",
            conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
            metadata={},
        )
        record_event(db_session, session_id=session_id, event_type="session_reset", payload={"total_turns": 2})

    summary = build_summary(db_session)
    severities = [item["severity"] for item in summary["insights"]]
    order = {"high": 0, "medium": 1, "low": 2, "info": 3, "positive": 4}

    assert severities == sorted(severities, key=lambda item: order.get(item, 5))


def test_insights_include_suggested_action_mapping_for_first_question_and_closure():
    from app.services.analytics_insight_service import generate_analytics_insights

    insights = generate_analytics_insights(
        {
            "total_sessions": 10,
            "abandoned_sessions": 5,
            "closure_rate": 0.1,
            "quick_reply_rate": 0.05,
            "clarification_rate": 0.8,
            "effective_sessions_rate": 0.1,
            "avg_time_to_advice_seconds": 45,
            "top_case_domains": [{"value": "divorcio", "count": 6}],
            "dropoff_by_turn": [{"turn": 1, "count": 4, "rate": 0.4}],
        }
    )

    by_code = {item["code"]: item for item in insights}

    assert by_code["high_dropoff_turn_1"]["suggested_action"] == "review_first_question"
    assert by_code["low_closure_rate"]["suggested_action"] == "review_question_flow"


def test_auto_healing_recommended_actions_are_derived_from_insights():
    from app.services.auto_healing_service import build_recommended_actions, get_primary_action

    insights = [
        {
            "code": "high_dropoff_turn_1",
            "severity": "high",
            "suggested_action": "review_first_question",
        },
        {
            "code": "low_effectiveness",
            "severity": "high",
            "suggested_action": "improve_advice_generation",
        },
        {
            "code": "high_clarification_rate",
            "severity": "medium",
            "suggested_action": "reduce_questions",
        },
    ]

    actions = build_recommended_actions(insights)

    assert actions == [
        {
            "action": "improve_advice_generation",
            "reason": "low_effectiveness",
            "priority": "high",
        },
        {
            "action": "review_first_question",
            "reason": "high_dropoff_turn_1",
            "priority": "high",
        },
        {
            "action": "reduce_questions",
            "reason": "high_clarification_rate",
            "priority": "medium",
        },
    ]
    assert get_primary_action(insights) == actions[0]


def test_summary_includes_recommended_actions_and_primary_action(db_session):
    for index in range(3):
        session_id = f"sess-action-{index}"
        track_legal_query_cycle(
            db_session,
            session_id=session_id,
            user_id=None,
            query=f"Consulta action {index}",
            jurisdiction="jujuy",
            case_domain="divorcio",
            conversational={"should_ask_first": True, "question": "Hay hijos?", "case_completeness": {"missing_critical": ["hay_hijos"], "missing_optional": []}},
            metadata={},
        )
        record_event(db_session, session_id=session_id, event_type="session_reset", payload={"total_turns": 2})

    summary = build_summary(db_session)

    assert summary["recommended_actions"]
    assert summary["primary_action"] is not None
    assert summary["primary_action"]["action"] in {
        "review_first_question",
        "review_question_flow",
        "reduce_questions",
        "improve_advice_generation",
    }


def test_summary_includes_positive_insight_when_metrics_are_healthy(db_session):
    track_legal_query_cycle(
        db_session,
        session_id="sess-ok-1",
        user_id=None,
        query="Quiero divorciarme",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Quiero divorciarme"}, "quick_reply": {"selected_option": "Unilateral", "submitted_text": "Es unilateral"}},
    )
    track_legal_query_cycle(
        db_session,
        session_id="sess-ok-2",
        user_id=None,
        query="Necesito alimentos",
        jurisdiction="jujuy",
        case_domain="alimentos",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Necesito alimentos"}, "quick_reply": {"selected_option": "Demandado", "submitted_text": "Soy demandado"}},
    )
    for session_id in ("sess-ok-1", "sess-ok-2"):
        session = db_session.get(AnalyticsSession, session_id)
        session.first_advice_at = session.started_at + timedelta(seconds=10)
    db_session.commit()

    summary = build_summary(db_session)

    assert summary["insights"][0]["type"] == "positive"


def test_summary_endpoint_returns_aggregates(db_session):
    track_legal_query_cycle(
        db_session,
        session_id="sess-endpoint",
        user_id="user-1",
        query="Consulta",
        jurisdiction="jujuy",
        case_domain="divorcio",
        conversational={"should_ask_first": False, "message": "Con esto ya tengo una base clara para orientarte.", "case_completeness": {"missing_critical": [], "missing_optional": []}},
        metadata={"clarification_context": {"base_query": "Consulta"}},
    )

    payload = get_session_summary(db=db_session, _current_user=SimpleNamespace(id="user-1"))

    assert payload["total_sessions"] == 1
    assert payload["completed_sessions"] == 1


def test_track_session_event_endpoint_creates_event(db_session):
    payload = track_session_event(
        payload=SimpleNamespace(
            session_id="sess-event-endpoint",
            event_type="quick_reply_clicked",
            turn_index=None,
            case_domain="divorcio",
            jurisdiction="jujuy",
            payload={"selected_option": "Unilateral"},
        ),
        db=db_session,
        current_user=SimpleNamespace(id="user-1"),
    )

    assert payload["ok"] is True
    assert payload["event"]["event_type"] == "quick_reply_clicked"
