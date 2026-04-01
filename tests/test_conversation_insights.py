from __future__ import annotations

import json

from app.services import conversation_insights_service


def _write_log(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sample_rows():
    return [
        {
            "conversation_id": "conv-divorcio-1",
            "turn_number": 1,
            "output_mode": "clarification",
            "question_asked": "¿Hay hijos menores?",
            "case_domain": "divorcio",
            "facts_detected": {},
            "missing_information": ["Hay hijos", "Modalidad del divorcio"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": False, "no_progress": True, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-divorcio-1",
            "turn_number": 2,
            "output_mode": "clarification",
            "question_asked": "¿Hay hijos menores?",
            "case_domain": "divorcio",
            "facts_detected": {},
            "missing_information": ["Hay hijos"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": True, "no_progress": True, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-divorcio-1",
            "turn_number": 3,
            "output_mode": "clarification",
            "question_asked": "¿Hay hijos menores o con capacidad restringida?",
            "case_domain": "divorcio",
            "facts_detected": {},
            "missing_information": ["Hay hijos"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": True, "no_progress": True, "loop_detected": True, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-alimentos-1",
            "turn_number": 1,
            "output_mode": "clarification",
            "question_asked": "¿El otro progenitor tiene ingresos identificables?",
            "case_domain": "alimentos",
            "facts_detected": {},
            "missing_information": ["Ingresos del otro progenitor"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": False, "no_progress": True, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-alimentos-1",
            "turn_number": 2,
            "output_mode": "clarification",
            "question_asked": "¿El otro progenitor tiene ingresos identificables?",
            "case_domain": "alimentos",
            "facts_detected": {},
            "missing_information": ["Ingresos del otro progenitor"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": True, "no_progress": True, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-alimentos-1",
            "turn_number": 3,
            "output_mode": "clarification",
            "question_asked": "¿Trabaja en blanco o tiene ingresos fijos?",
            "case_domain": "alimentos",
            "facts_detected": {"hay_ingresos": True},
            "missing_information": ["Ingresos del otro progenitor"],
            "progress": {"delta": 1, "has_progress": True, "new_keys": ["hay_ingresos"]},
            "signals": {"repeat_question": False, "no_progress": False, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-alimentos-1",
            "turn_number": 4,
            "output_mode": "advice",
            "question_asked": "",
            "case_domain": "alimentos",
            "facts_detected": {"hay_ingresos": True, "urgencia": True},
            "missing_information": ["Monto estimado de gastos"],
            "progress": {"delta": 1, "has_progress": True, "new_keys": ["urgencia"]},
            "signals": {"repeat_question": False, "no_progress": False, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-divorcio-2",
            "turn_number": 1,
            "output_mode": "clarification",
            "question_asked": "¿Hay hijos menores?",
            "case_domain": "divorcio",
            "facts_detected": {},
            "missing_information": ["Hay hijos", "Convenio regulador"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": False, "no_progress": True, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": True},
        },
        {
            "conversation_id": "conv-divorcio-2",
            "turn_number": 2,
            "output_mode": "advice",
            "question_asked": "",
            "case_domain": "divorcio",
            "facts_detected": {"hay_hijos": True},
            "missing_information": ["Convenio regulador"],
            "progress": {"delta": 1, "has_progress": True, "new_keys": ["hay_hijos"]},
            "signals": {"repeat_question": False, "no_progress": False, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-alimentos-2",
            "turn_number": 1,
            "output_mode": "clarification",
            "question_asked": "¿El otro progenitor tiene ingresos identificables?",
            "case_domain": "alimentos",
            "facts_detected": {},
            "missing_information": ["Ingresos del otro progenitor"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": False, "no_progress": True, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-alimentos-2",
            "turn_number": 2,
            "output_mode": "clarification",
            "question_asked": "¿El otro progenitor tiene ingresos identificables?",
            "case_domain": "alimentos",
            "facts_detected": {},
            "missing_information": ["Ingresos del otro progenitor", "Gastos del hijo"],
            "progress": {"delta": 0, "has_progress": False, "new_keys": []},
            "signals": {"repeat_question": True, "no_progress": True, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
        {
            "conversation_id": "conv-alimentos-2",
            "turn_number": 3,
            "output_mode": "advice",
            "question_asked": "",
            "case_domain": "alimentos",
            "facts_detected": {"hay_ingresos": True},
            "missing_information": ["Gastos del hijo"],
            "progress": {"delta": 1, "has_progress": True, "new_keys": ["hay_ingresos"]},
            "signals": {"repeat_question": False, "no_progress": False, "loop_detected": False, "domain_shift": False, "unnecessary_clarification": False},
        },
    ]


def test_load_group_and_volume_metrics(tmp_path):
    log_path = tmp_path / "conversations.jsonl"
    _write_log(log_path, _sample_rows())

    turns = conversation_insights_service.load_conversation_logs(log_path=log_path)
    grouped = conversation_insights_service.group_turns_by_conversation(turns)
    metrics = conversation_insights_service.calculate_metrics(turns, grouped)

    assert len(turns) == 12
    assert len(grouped) == 4
    assert metrics["volume"]["total_conversations"] == 4
    assert metrics["volume"]["total_turns"] == 12
    assert metrics["volume"]["avg_turns_per_conversation"] == 3.0


def test_metrics_include_output_modes_progress_and_friction(tmp_path):
    log_path = tmp_path / "conversations.jsonl"
    _write_log(log_path, _sample_rows())

    snapshot = conversation_insights_service.build_snapshot(log_path=log_path)
    metrics = snapshot["metrics"]

    assert metrics["output_modes"]["clarification_turns"] == 9
    assert metrics["output_modes"]["advice_turns"] == 3
    assert metrics["progress"]["conversations_with_progress"] == 3
    assert metrics["progress"]["conversations_without_progress"] == 1
    assert metrics["progress"]["avg_new_facts_per_turn"] == 0.3333
    repeated_questions = {item["question"] for item in metrics["friction"]["most_repeated_questions"]}
    assert "¿Hay hijos menores?" in repeated_questions
    assert metrics["friction"]["top_signals"][0]["signal"] == "no_progress"
    assert metrics["stability"]["unnecessary_clarification_count"] == 1


def test_metrics_include_missing_and_added_facts_breakdowns(tmp_path):
    log_path = tmp_path / "conversations.jsonl"
    _write_log(log_path, _sample_rows())

    turns = conversation_insights_service.load_conversation_logs(log_path=log_path)
    metrics = conversation_insights_service.calculate_metrics(turns)

    top_missing_items = {item["item"] for item in metrics["facts_and_missing"]["top_missing_information"]}
    assert "Hay hijos" in top_missing_items
    assert metrics["facts_and_missing"]["top_added_facts"][0]["fact"] in {"hay_hijos", "hay_ingresos", "urgencia"}
    assert metrics["facts_and_missing"]["missing_by_domain"]["divorcio"][0]["item"] == "Hay hijos"


def test_generate_insights_returns_actionable_messages(tmp_path):
    log_path = tmp_path / "conversations.jsonl"
    _write_log(log_path, _sample_rows())

    snapshot = conversation_insights_service.build_snapshot(log_path=log_path)
    messages = [item["message"] for item in snapshot["insights"]]

    assert any("divorcio muestra alta friccion en preguntas sobre hijos" in message for message in messages)
    assert any("clarification → advice tarda demasiado en alimentos" in message for message in messages)
    assert any("sin progreso real despues del turno 3" in message for message in messages)
    assert any('Se repite demasiado la pregunta "' in message for message in messages)


def test_empty_log_returns_honest_insight(tmp_path):
    log_path = tmp_path / "empty.jsonl"
    log_path.write_text("", encoding="utf-8")

    snapshot = conversation_insights_service.build_snapshot(log_path=log_path)

    assert snapshot["has_data"] is False
    assert snapshot["metrics"]["has_data"] is False
    assert snapshot["insights"][0]["code"] == "no_conversation_data"
