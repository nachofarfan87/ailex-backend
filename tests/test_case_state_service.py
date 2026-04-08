# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_case_state_service.py
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
import app.models.case_state  # noqa: F401
# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_case_state_service.py
from app.services.case_state_service import case_state_service


def _build_db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    return engine, db


def test_crea_state_si_no_existe():
    engine, db = _build_db_session()
    try:
        state = case_state_service.get_or_create_case_state(db, "conv-case-state")

        assert state.conversation_id == "conv-case-state"
        assert state.case_stage == "consulta_inicial"
        assert state.status == "active"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_upsert_de_fact_nuevo():
    engine, db = _build_db_session()
    try:
        fact = case_state_service.upsert_case_fact(
            db,
            conversation_id="conv-fact-new",
            fact_key="hay_hijos",
            fact_value=True,
            source_type="user_explicit",
            status="confirmed",
            turn_index=1,
        )

        assert fact.fact_key == "hay_hijos"
        assert fact.status == "confirmed"
        assert fact.first_seen_turn == 1
        assert len(case_state_service.get_case_facts(db, "conv-fact-new")) == 1
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_actualizacion_de_fact_existente_registra_evento():
    engine, db = _build_db_session()
    try:
        case_state_service.upsert_case_fact(
            db,
            conversation_id="conv-fact-update",
            fact_key="ingresos_otro_progenitor",
            fact_value="sin dato cierto",
            source_type="pipeline_inferred",
            status="probable",
            turn_index=1,
        )
        updated = case_state_service.upsert_case_fact(
            db,
            conversation_id="conv-fact-update",
            fact_key="ingresos_otro_progenitor",
            fact_value="trabaja en relacion de dependencia",
            source_type="user_explicit",
            status="confirmed",
            turn_index=2,
        )

        snapshot = case_state_service.build_case_snapshot(db, "conv-fact-update")
        assert updated.status == "confirmed"
        assert updated.last_updated_turn == 2
        assert snapshot["confirmed_facts"]["ingresos_otro_progenitor"] == "trabaja en relacion de dependencia"
        assert snapshot["contradictions"] == []
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_override_de_fact_inferido_por_fact_explicito():
    engine, db = _build_db_session()
    try:
        case_state_service.upsert_case_fact(
            db,
            conversation_id="conv-override",
            fact_key="hay_acuerdo",
            fact_value=False,
            source_type="pipeline_inferred",
            status="probable",
            turn_index=1,
        )
        fact = case_state_service.upsert_case_fact(
            db,
            conversation_id="conv-override",
            fact_key="hay_acuerdo",
            fact_value=True,
            source_type="user_explicit",
            status="confirmed",
            turn_index=2,
        )

        assert fact.status == "confirmed"
        assert case_state_service.build_case_snapshot(db, "conv-override")["confirmed_facts"]["hay_acuerdo"] is True
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_upsert_de_need():
    engine, db = _build_db_session()
    try:
        first = case_state_service.upsert_case_need(
            db,
            conversation_id="conv-need",
            need_key="ingresos_otro_progenitor",
            category="economico",
            priority="critical",
            reason="Falta cuantificar ingresos",
            suggested_question="¿Podés precisar ingresos del otro progenitor?",
        )
        second = case_state_service.upsert_case_need(
            db,
            conversation_id="conv-need",
            need_key="ingresos_otro_progenitor",
            category="economico",
            priority="critical",
            reason="Falta cuantificar ingresos con mas precision",
            suggested_question="¿Cuáles son los ingresos del otro progenitor?",
        )

        assert first.id == second.id
        assert second.reason == "Falta cuantificar ingresos con mas precision"
        assert len(case_state_service.get_case_needs(db, "conv-need")) == 1
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_resolve_need():
    engine, db = _build_db_session()
    try:
        case_state_service.upsert_case_need(
            db,
            conversation_id="conv-resolve",
            need_key="ingresos_otro_progenitor",
            category="economico",
            priority="critical",
        )
        need = case_state_service.resolve_need(
            db,
            conversation_id="conv-resolve",
            need_key="ingresos_otro_progenitor",
            fact_key="ingresos_otro_progenitor",
        )

        assert need is not None
        assert need.status == "resolved"
        assert need.resolved_by_fact_key == "ingresos_otro_progenitor"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_snapshot_correcto_con_confirmed_y_open_needs():
    engine, db = _build_db_session()
    try:
        case_state_service.update_case_state(
            db,
            conversation_id="conv-snapshot",
            case_type="alimentos_hijos",
            case_stage="recopilacion_hechos",
            primary_goal="reclamar cuota alimentaria",
            summary_text="Hay base inicial para el reclamo.",
        )
        case_state_service.upsert_case_fact(
            db,
            conversation_id="conv-snapshot",
            fact_key="hay_hijos",
            fact_value=True,
            source_type="user_explicit",
            status="confirmed",
        )
        case_state_service.upsert_case_fact(
            db,
            conversation_id="conv-snapshot",
            fact_key="ingresos_otro_progenitor",
            fact_value="trabajo informal",
            source_type="pipeline_inferred",
            status="probable",
        )
        case_state_service.upsert_case_need(
            db,
            conversation_id="conv-snapshot",
            need_key="domicilio_otro_progenitor",
            category="procesal",
            priority="normal",
            status="open",
            reason="Falta domicilio para notificar",
        )

        snapshot = case_state_service.build_case_snapshot(db, "conv-snapshot")

        assert snapshot["case_state"]["case_type"] == "alimentos_hijos"
        assert snapshot["confirmed_facts"] == {"hay_hijos": True}
        assert snapshot["probable_facts"] == {"ingresos_otro_progenitor": "trabajo informal"}
        assert len(snapshot["open_needs"]) == 1
        assert snapshot["open_needs"][0]["need_key"] == "domicilio_otro_progenitor"
        assert snapshot["recommended_followup"] is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_persistencia_de_summary_text():
    engine, db = _build_db_session()
    try:
        case_state_service.get_or_create_case_state(db, "conv-summary")
        state = case_state_service.update_case_summary_text(
            db,
            conversation_id="conv-summary",
            summary_text="Reclamo de alimentos con hijos involucrados. Falta precisar ingresos.",
        )

        snapshot = case_state_service.build_case_snapshot(db, "conv-summary")
        assert state.summary_text == "Reclamo de alimentos con hijos involucrados. Falta precisar ingresos."
        assert snapshot["case_state"]["summary_text"] == "Reclamo de alimentos con hijos involucrados. Falta precisar ingresos."
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
