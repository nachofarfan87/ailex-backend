from __future__ import annotations

import json

from app.services import conversation_observability_service


def test_detecta_pregunta_repetida():
    assert conversation_observability_service.detect_repeated_question(
        "¿Hay hijos menores o con capacidad restringida?",
        "Hay hijos menores o con capacidad restringida",
    ) is True


def test_detecta_falta_de_progreso():
    progress = conversation_observability_service.compute_progress(
        {"hay_hijos": True, "divorcio_modalidad": "unilateral"},
        {"hay_hijos": True, "divorcio_modalidad": "unilateral"},
    )

    assert progress["delta"] == 0
    assert progress["has_progress"] is False


def test_detecta_loop_en_tres_turnos():
    previous_turns = [
        {
            "output_mode": "clarification",
            "question_asked": "¿Hay hijos menores?",
            "progress": {"has_progress": False},
            "signals": {"no_progress": True},
        },
        {
            "output_mode": "clarification",
            "question_asked": "Hay hijos menores",
            "progress": {"has_progress": False},
            "signals": {"no_progress": True},
        },
    ]
    current_turn = {
        "output_mode": "clarification",
        "question_asked": "¿Hay hijos menores o con capacidad restringida?",
        "progress": {"has_progress": False},
        "signals": {"no_progress": True},
    }

    assert conversation_observability_service.detect_loop(previous_turns, current_turn) is True


def test_progreso_aumenta_correctamente():
    progress = conversation_observability_service.compute_progress(
        {"hay_hijos": True},
        {"hay_hijos": True, "divorcio_modalidad": "unilateral", "hay_acuerdo": False},
    )

    assert progress["previous_count"] == 1
    assert progress["current_count"] == 3
    assert progress["delta"] == 2
    assert progress["has_progress"] is True


def test_no_rompe_si_memory_es_none(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "conversations.jsonl"
    monkeypatch.setattr(conversation_observability_service, "CONVERSATION_LOG_PATH", log_path)

    observation = conversation_observability_service.record_observation(
        turn_input={
            "query": "Quiero divorciarme",
            "metadata": {"conversation_id": "conv-1"},
        },
        response={
            "case_domain": "divorcio",
            "confidence": 0.62,
            "quick_start": "Primer paso recomendado: Definir la via procesal aplicable.",
            "conversational": {"should_ask_first": False},
            "output_modes": {"user": {"missing_information": ["Precisar bienes."]}},
        },
        memory=None,
    )

    assert observation["conversation_id"] == "conv-1"
    assert observation["turn_number"] == 1
    assert observation["signals"]["no_progress"] is True
    assert log_path.exists() is True

    stored_lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    stored = json.loads(stored_lines[0])
    assert stored["conversation_id"] == "conv-1"
