from __future__ import annotations

from legal_engine.procedural_timeline_builder import ProceduralTimelineBuilder


def test_orders_events_chronologically_even_if_uploaded_out_of_order():
    builder = ProceduralTimelineBuilder()
    result = builder.build(
        [
            {"title": "Sentencia", "date": "2024-05-10"},
            {"title": "Demanda presentada", "date": "2024-01-10"},
            {"title": "Corrase traslado y notifíquese", "date": "2024-02-01"},
        ]
    )

    labels = [event["label"] for event in result.ordered_events]
    assert labels[:3] == ["claim_filed", "service_ordered", "judgment_entered"]
    assert "events_uploaded_out_of_order" in result.detected_anomalies


def test_detects_key_events_for_alimentos_with_incompetence():
    builder = ProceduralTimelineBuilder()
    result = builder.build(
        [
            {"title": "Demanda de alimentos", "date": "2024-01-05"},
            {"title": "Cuota provisoria", "summary": "Se fija cuota provisoria", "date": "2024-01-06"},
            {"title": "Incompetencia", "summary": "Se declara incompetencia territorial", "date": "2024-01-20"},
        ]
    )

    key_labels = [event["label"] for event in result.key_events]
    assert "claim_filed" in key_labels
    assert "interim_measure" in key_labels
    assert "competence_issue" in key_labels
    assert result.current_stage == "competence_review"


def test_degrades_noise_and_removes_duplicate_oficios():
    builder = ProceduralTimelineBuilder()
    result = builder.build(
        [
            {"title": "Casillero digital", "date": "2024-02-01"},
            {"title": "Téngase presente", "date": "2024-02-01"},
            {"title": "Oficio librado al banco", "date": "2024-02-03"},
            {"title": "Oficio librado al banco", "date": "2024-02-03"},
            {"title": "Cédula diligenciada", "date": "2024-02-05"},
        ]
    )

    labels = [event["label"] for event in result.ordered_events]
    assert labels.count("oficio_issued") == 1
    assert any(event["is_noise"] for event in result.ordered_events)
    assert any(anomaly.startswith("duplicate_or_low_value_events_removed:") for anomaly in result.detected_anomalies)


def test_infers_current_stage_when_service_pending():
    builder = ProceduralTimelineBuilder()
    result = builder.build(
        [
            {"title": "Demanda presentada", "date": "2024-01-05"},
            {"title": "Admítase demanda", "date": "2024-01-10"},
            {"title": "Corrase traslado y notifíquese", "date": "2024-01-11"},
        ]
    )

    assert result.current_stage == "service_pending"
    assert any("notificacion" in action.lower() for action in result.pending_actions)


def test_detects_incomplete_or_disordered_file_with_missing_steps():
    builder = ProceduralTimelineBuilder()
    result = builder.build(
        [
            {"title": "Audiencia", "summary": "Se celebra audiencia", "date": "2024-03-01"},
            {"title": "Sentencia", "date": "2024-03-20"},
            {"title": "Demanda", "date": None},
        ]
    )

    anomalies = set(result.detected_anomalies)
    assert "events_without_date" in anomalies
    assert "hearing_without_confirmed_service" in anomalies
    assert "judgment_without_clear_contradictory_stage" in anomalies


def test_realistic_pattern_with_failed_hearing_and_defense():
    builder = ProceduralTimelineBuilder()
    result = builder.build(
        [
            {"title": "Demanda de alimentos", "date": "2024-01-10"},
            {"title": "Admítase demanda", "date": "2024-01-15"},
            {"title": "Cédula diligenciada", "date": "2024-01-20"},
            {"title": "Audiencia fallida por incomparecencia", "date": "2024-02-10"},
            {"title": "Contestación de demanda", "date": "2024-02-18"},
        ]
    )

    assert result.current_stage == "contradictory_stage"
    assert any(event["label"] == "hearing_failed" for event in result.key_events)
    assert any(event["label"] == "defense_entered" for event in result.key_events)
    assert "Etapa procesal actual: contradictory_stage." in result.timeline_summary
