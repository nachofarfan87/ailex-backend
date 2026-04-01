from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
import app.models.conversation_state_snapshot  # noqa: F401
from app.models.conversation_state_snapshot import ConversationStateSnapshot
from app.services.conversation_state_service import conversation_state_service


def _build_db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    return engine, db


def _turn_input(
    *,
    conversation_id: str = "conv-1",
    query: str = "Quiero reclamar alimentos",
    facts: dict | None = None,
) -> dict:
    return {
        "query": query,
        "facts": facts or {},
        "metadata": {
            "conversation_id": conversation_id,
        },
    }


def _pipeline_payload(
    *,
    facts: dict | None = None,
    asked_question: str | None = None,
    action_slug: str = "",
    case_domain: str = "",
    missing_critical: list[str] | None = None,
    missing_optional: list[str] | None = None,
    should_ask_first: bool = False,
) -> dict:
    payload = {
        "facts": facts or {},
        "classification": {"action_slug": action_slug, "case_domain": case_domain},
        "case_profile": {
            "case_domain": case_domain,
            "missing_critical_facts": list(missing_critical or []),
            "missing_optional_facts": list(missing_optional or []),
        },
        "conversational": {
            "should_ask_first": should_ask_first,
        },
    }
    if asked_question:
        payload["conversational"]["question"] = asked_question
    return payload


def test_crea_estado_vacio_si_no_existe():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.load_state(db, conversation_id="conv-empty")

        assert snapshot["conversation_id"] == "conv-empty"
        assert snapshot["turn_count"] == 0
        assert snapshot["known_facts"] == []
        assert snapshot["missing_facts"] == []
        assert snapshot["asked_questions"] == []
        assert snapshot["state_version"] == 1
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_acumula_known_facts_sin_duplicar():
    engine, db = _build_db_session()
    try:
        conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-known",
            turn_input=_turn_input(conversation_id="conv-known", facts={"hay_hijos": True}),
            pipeline_payload=_pipeline_payload(facts={"hay_hijos": True}),
        )
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-known",
            turn_input=_turn_input(conversation_id="conv-known", facts={"hay_hijos": True, "dni_actor": "20111222"}),
            pipeline_payload=_pipeline_payload(facts={"hay_hijos": True, "dni_actor": "20111222"}),
        )

        keys = [item["key"] for item in snapshot["known_facts"]]
        assert keys.count("hay_hijos") == 1
        assert "dni_actor" in keys
        hay_hijos = next(item for item in snapshot["known_facts"] if item["key"] == "hay_hijos")
        assert hay_hijos["fact_type"] == "structural"
        assert hay_hijos["importance"] == "core"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_elimina_missing_facts_ya_resueltos():
    engine, db = _build_db_session()
    try:
        conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-missing",
            turn_input=_turn_input(conversation_id="conv-missing"),
            pipeline_payload=_pipeline_payload(missing_critical=["ingresos_otro_progenitor"], should_ask_first=True),
        )
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-missing",
            turn_input=_turn_input(conversation_id="conv-missing", facts={"ingresos_otro_progenitor": "Empleado en relacion de dependencia"}),
            pipeline_payload=_pipeline_payload(
                facts={"ingresos_otro_progenitor": "Empleado en relacion de dependencia"},
                missing_critical=["ingresos_otro_progenitor"],
            ),
        )

        assert snapshot["missing_facts"] == []
        assert snapshot["progress_signals"]["missing_fact_count"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_deduplica_asked_questions():
    engine, db = _build_db_session()
    try:
        conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-questions",
            turn_input=_turn_input(conversation_id="conv-questions"),
            pipeline_payload=_pipeline_payload(
                asked_question="¿El otro progenitor esta aportando algo actualmente?",
                should_ask_first=True,
            ),
        )
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-questions",
            turn_input=_turn_input(conversation_id="conv-questions"),
            pipeline_payload=_pipeline_payload(
                asked_question="¿El otro progenitor esta aportando algo actualmente?",
                should_ask_first=True,
            ),
        )

        assert snapshot["asked_questions"] == ["¿El otro progenitor esta aportando algo actualmente?"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_known_fact_recibe_fact_type_evidentiary():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-evidence",
            turn_input=_turn_input(conversation_id="conv-evidence", facts={"comprobantes_pago": "Tengo recibos y capturas"}),
            pipeline_payload=_pipeline_payload(facts={"comprobantes_pago": "Tengo recibos y capturas"}),
        )

        fact = next(item for item in snapshot["known_facts"] if item["key"] == "comprobantes_pago")
        assert fact["fact_type"] == "evidentiary"
        assert fact["importance"] == "relevant"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_known_fact_recibe_importance_accessory_en_caso_accesorio():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-accessory",
            turn_input=_turn_input(conversation_id="conv-accessory", facts={"distancia_contacto": "Vive a 20 cuadras"}),
            pipeline_payload=_pipeline_payload(facts={"distancia_contacto": "Vive a 20 cuadras"}),
        )

        fact = next(item for item in snapshot["known_facts"] if item["key"] == "distancia_contacto")
        assert fact["fact_type"] == "contextual"
        assert fact["importance"] == "accessory"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_conserva_working_case_type_previo_si_la_nueva_senal_es_debil():
    engine, db = _build_db_session()
    try:
        conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-case-type",
            turn_input=_turn_input(conversation_id="conv-case-type"),
            pipeline_payload=_pipeline_payload(action_slug="alimentos_hijos", case_domain="alimentos"),
        )
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-case-type",
            turn_input=_turn_input(conversation_id="conv-case-type"),
            pipeline_payload=_pipeline_payload(action_slug="generic", case_domain="generic"),
        )

        assert snapshot["working_case_type"] == "alimentos_hijos"
        assert snapshot["working_domain"] == "alimentos"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_actualiza_working_case_type_si_la_nueva_senal_es_mas_especifica():
    engine, db = _build_db_session()
    try:
        conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-case-type-upgrade",
            turn_input=_turn_input(conversation_id="conv-case-type-upgrade"),
            pipeline_payload=_pipeline_payload(action_slug="alimentos", case_domain="familia"),
        )
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-case-type-upgrade",
            turn_input=_turn_input(conversation_id="conv-case-type-upgrade"),
            pipeline_payload=_pipeline_payload(action_slug="alimentos_hijos", case_domain="alimentos"),
        )

        assert snapshot["working_case_type"] == "alimentos_hijos"
        assert snapshot["working_domain"] == "alimentos"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_no_degrada_working_case_type_ante_turno_ambiguo_posterior():
    engine, db = _build_db_session()
    try:
        conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-ambiguous",
            turn_input=_turn_input(conversation_id="conv-ambiguous"),
            pipeline_payload=_pipeline_payload(action_slug="alimentos_hijos", case_domain="alimentos"),
        )
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-ambiguous",
            turn_input=_turn_input(conversation_id="conv-ambiguous", query="Quiero seguir con esto"),
            pipeline_payload=_pipeline_payload(action_slug="", case_domain=""),
        )

        assert snapshot["working_case_type"] == "alimentos_hijos"
        assert snapshot["working_domain"] == "alimentos"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_update_progression_state_persiste_progression_stage_y_recent_turns():
    engine, db = _build_db_session()
    try:
        conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-progression",
            turn_input=_turn_input(conversation_id="conv-progression"),
            pipeline_payload=_pipeline_payload(action_slug="alimentos_hijos", case_domain="alimentos"),
        )

        conversation_state_service.update_progression_state(
            db,
            conversation_id="conv-progression",
            progression_state={
                "facts_collected": ["hay_hijos"],
                "questions_asked": ["El otro progenitor aporta actualmente?"],
                "topics_covered": ["alimentos"],
                "last_output_mode": "estructuracion",
                "progression_stage": "structuring_case",
                "recent_turns": [
                    {
                        "output_mode": "estructuracion",
                        "intent_type": "general_information",
                        "topics_covered": ["alimentos"],
                        "question_asked": "El otro progenitor aporta actualmente?",
                        "response_fingerprint": "respuesta evolucionada",
                    }
                ],
            },
        )

        snapshot = conversation_state_service.load_state(db, conversation_id="conv-progression")

        assert snapshot["progression_stage"] == "structuring_case"
        assert snapshot["progression_state"]["last_output_mode"] == "estructuracion"
        assert snapshot["progression_state"]["recent_turns"][0]["response_fingerprint"] == "respuesta evolucionada"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_incrementa_turn_count_correctamente():
    engine, db = _build_db_session()
    try:
        snapshot_one = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-turns",
            turn_input=_turn_input(conversation_id="conv-turns"),
            pipeline_payload=_pipeline_payload(),
        )
        snapshot_two = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-turns",
            turn_input=_turn_input(conversation_id="conv-turns", query="Amplio los hechos"),
            pipeline_payload=_pipeline_payload(),
        )

        assert snapshot_one["turn_count"] == 1
        assert snapshot_two["turn_count"] == 2
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_calcula_progress_signals_coherentes():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-progress",
            turn_input=_turn_input(conversation_id="conv-progress", facts={"hay_hijos": True, "convivencia": True}),
            pipeline_payload=_pipeline_payload(
                facts={"hay_hijos": True, "convivencia": True},
                asked_question="¿El otro progenitor esta aportando algo actualmente?",
                missing_critical=["ingresos_otro_progenitor"],
                should_ask_first=True,
                action_slug="alimentos_hijos",
                case_domain="alimentos",
            ),
        )

        assert snapshot["progress_signals"]["known_fact_count"] == 2
        assert snapshot["progress_signals"]["missing_fact_count"] == 1
        assert snapshot["progress_signals"]["question_count"] == 1
        assert snapshot["progress_signals"]["turn_count"] == 1
        assert snapshot["progress_signals"]["structural_fact_count"] == 2
        assert snapshot["progress_signals"]["evidentiary_fact_count"] == 0
        assert snapshot["progress_signals"]["contextual_fact_count"] == 0
        assert snapshot["progress_signals"]["core_fact_count"] == 2
        assert snapshot["progress_signals"]["relevant_fact_count"] == 0
        assert snapshot["progress_signals"]["accessory_fact_count"] == 0
        assert snapshot["progress_signals"]["blocking_missing"] is True
        assert snapshot["progress_signals"]["case_completeness"] == "low"
        assert snapshot["progress_signals"]["repeated_question_risk"] == "low"
        assert snapshot["current_stage"] == "clarification"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_missing_fact_recibe_purpose_quantify():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-quantify",
            turn_input=_turn_input(conversation_id="conv-quantify"),
            pipeline_payload=_pipeline_payload(missing_critical=["ingresos_otro_progenitor"]),
        )

        missing = next(item for item in snapshot["missing_facts"] if item["key"] == "ingresos_otro_progenitor")
        assert missing["purpose"] == "quantify"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_missing_fact_recibe_purpose_prove():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-prove",
            turn_input=_turn_input(conversation_id="conv-prove"),
            pipeline_payload=_pipeline_payload(missing_critical=["comprobantes_de_pago"]),
        )

        missing = next(item for item in snapshot["missing_facts"] if item["key"] == "comprobantes_de_pago")
        assert missing["purpose"] == "prove"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_case_completeness_medium_y_high_en_casos_representativos():
    engine, db = _build_db_session()
    try:
        medium_snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-medium",
            turn_input=_turn_input(
                conversation_id="conv-medium",
                facts={"hay_hijos": True, "convivencia": True, "urgencia": True},
            ),
            pipeline_payload=_pipeline_payload(
                facts={"hay_hijos": True, "convivencia": True, "urgencia": True},
                missing_optional=["comprobantes_de_pago"],
                action_slug="alimentos_hijos",
                case_domain="alimentos",
            ),
        )
        high_snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-high",
            turn_input=_turn_input(
                conversation_id="conv-high",
                facts={
                    "hay_hijos": True,
                    "convivencia": True,
                    "ingresos_otro_progenitor": "Dependencia",
                    "domicilio_nnya": "San Salvador de Jujuy",
                },
            ),
            pipeline_payload=_pipeline_payload(
                facts={
                    "hay_hijos": True,
                    "convivencia": True,
                    "ingresos_otro_progenitor": "Dependencia",
                    "domicilio_nnya": "San Salvador de Jujuy",
                },
                action_slug="alimentos_hijos",
                case_domain="alimentos",
            ),
        )

        assert medium_snapshot["progress_signals"]["case_completeness"] == "medium"
        assert medium_snapshot["progress_signals"]["blocking_missing"] is False
        assert high_snapshot["progress_signals"]["case_completeness"] == "high"
        assert high_snapshot["progress_signals"]["blocking_missing"] is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_snapshots_viejos_sin_fact_type_ni_purpose_se_normalizan_sin_romper():
    engine, db = _build_db_session()
    try:
        legacy = ConversationStateSnapshot(
            conversation_id="conv-legacy",
            state_version=1,
            snapshot_json='{"conversation_id":"conv-legacy","turn_count":2,"known_facts":[{"key":"hay_hijos","value":true,"status":"confirmed","source":"pipeline.facts"}],"missing_facts":[{"key":"ingresos_otro_progenitor","label":"ingresos_otro_progenitor","priority":"critical","source":"case_profile.missing_critical_facts"}],"asked_questions":["¿Hay hijos?"],"working_case_type":"alimentos_hijos","working_domain":"alimentos","current_stage":"clarification","progress_signals":{"repeated_question_risk":"low"}}',
        )
        db.add(legacy)
        db.commit()

        snapshot = conversation_state_service.load_state(db, conversation_id="conv-legacy")

        assert snapshot["known_facts"][0]["fact_type"] == "structural"
        assert snapshot["known_facts"][0]["importance"] == "core"
        assert snapshot["missing_facts"][0]["purpose"] == "quantify"
        assert snapshot["progress_signals"]["blocking_missing"] is True
        assert snapshot["progress_signals"]["case_completeness"] == "low"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_missing_critico_contextual_no_genera_blocking_missing():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-non-blocking",
            turn_input=_turn_input(
                conversation_id="conv-non-blocking",
                facts={"hay_hijos": True, "convivencia": True},
            ),
            pipeline_payload=_pipeline_payload(
                facts={"hay_hijos": True, "convivencia": True},
                missing_critical=["distancia_contacto"],
                action_slug="alimentos_hijos",
                case_domain="alimentos",
            ),
        )

        missing = next(item for item in snapshot["missing_facts"] if item["key"] == "distancia_contacto")
        assert missing["purpose"] == "enable"
        assert snapshot["progress_signals"]["blocking_missing"] is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_missing_central_si_genera_blocking_missing():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-blocking-central",
            turn_input=_turn_input(conversation_id="conv-blocking-central", facts={"hay_hijos": True}),
            pipeline_payload=_pipeline_payload(
                facts={"hay_hijos": True},
                missing_critical=["convivencia"],
                action_slug="alimentos_hijos",
                case_domain="alimentos",
            ),
        )

        assert snapshot["progress_signals"]["blocking_missing"] is True
        assert snapshot["progress_signals"]["case_completeness"] == "low"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_case_completeness_low_si_faltan_facts_core():
    engine, db = _build_db_session()
    try:
        snapshot = conversation_state_service.update_conversation_state(
            db,
            conversation_id="conv-low-core",
            turn_input=_turn_input(conversation_id="conv-low-core", facts={"urgencia": True}),
            pipeline_payload=_pipeline_payload(
                facts={"urgencia": True},
                action_slug="alimentos_hijos",
                case_domain="alimentos",
            ),
        )

        assert snapshot["progress_signals"]["core_fact_count"] == 0
        assert snapshot["progress_signals"]["case_completeness"] == "low"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
