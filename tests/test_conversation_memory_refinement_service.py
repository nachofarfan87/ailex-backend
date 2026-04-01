# c:\Users\nacho\Documents\APPS\AILEX\backend\tests\test_conversation_memory_refinement_service.py
"""
Tests — Fase 8.3: Conversation Memory Refinement Service

Cubre:
a. normalize_memory(None) → todos los campos con defaults
b. normalize_memory con snapshot viejo sin conversation_memory → defaults
c. build_memory_update registra last_dialogue_action
d. build_memory_update registra last_dominant_missing_key
e. asked_missing_keys_history acumula sin duplicar consecutivos
f. asked_missing_keys_history respeta tamaño máximo
g. used_lead_types acumula correctamente
h. should_vary_lead retorna True cuando el tipo se repite >= LEAD_VARY_WINDOW
i. should_vary_lead retorna False cuando el tipo se usó menos veces
j. was_topic_explained retorna True/False correctamente
k. explained_topics acumula desde build_memory_update
l. memory no se rompe con inputs malformados
"""
from __future__ import annotations

from app.services.conversation_memory_service import (
    LEAD_VARY_WINDOW,
    MAX_ASKED_KEYS_HISTORY,
    build_memory_update,
    get_asked_missing_keys_history,
    normalize_memory,
    should_vary_lead,
    was_topic_explained,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _policy(
    action: str = "ask",
    guidance_strength: str = "medium",
    dominant_missing_key: str = "ingresos_otro_progenitor",
    dominant_missing_purpose: str = "quantify",
) -> dict:
    return {
        "action": action,
        "guidance_strength": guidance_strength,
        "dominant_missing_key": dominant_missing_key,
        "dominant_missing_purpose": dominant_missing_purpose,
    }


def _composer(
    turn_type: str = "clarification",
    composition_strategy: str = "lead_followup",
    repetition_reduced: bool = False,
) -> dict:
    return {
        "turn_type": turn_type,
        "composition_strategy": composition_strategy,
        "repetition_reduced": repetition_reduced,
    }


def _state(working_case_type: str = "alimentos_hijos") -> dict:
    return {"working_case_type": working_case_type}


# ─── Tests: normalize_memory ─────────────────────────────────────────────────


# a.
def test_normalize_memory_none_returns_all_defaults():
    mem = normalize_memory(None)
    assert mem["last_dialogue_action"] == ""
    assert mem["last_guidance_strength"] == ""
    assert mem["last_dominant_missing_key"] == ""
    assert mem["last_turn_type"] == ""
    assert mem["last_composition_strategy"] == ""
    assert mem["asked_missing_keys_history"] == []
    assert mem["explained_topics"] == []
    assert mem["used_lead_types"] == []


# b.
def test_normalize_memory_empty_dict_returns_defaults():
    mem = normalize_memory({})
    assert mem["last_dialogue_action"] == ""
    assert mem["asked_missing_keys_history"] == []


def test_normalize_memory_preserves_existing_values():
    raw = {
        "last_dialogue_action": "hybrid",
        "asked_missing_keys_history": ["convivencia", "ingresos"],
    }
    mem = normalize_memory(raw)
    assert mem["last_dialogue_action"] == "hybrid"
    assert mem["asked_missing_keys_history"] == ["convivencia", "ingresos"]
    assert mem["explained_topics"] == []


def test_normalize_memory_coerces_types():
    raw = {"last_dialogue_action": 123, "asked_missing_keys_history": None}
    mem = normalize_memory(raw)
    assert isinstance(mem["last_dialogue_action"], str)
    assert isinstance(mem["asked_missing_keys_history"], list)


# ─── Tests: build_memory_update ──────────────────────────────────────────────


# c.
def test_build_memory_update_registers_last_dialogue_action():
    result = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(action="hybrid"),
        composer_output=_composer(),
    )
    assert result["last_dialogue_action"] == "hybrid"


# d.
def test_build_memory_update_registers_last_dominant_missing_key():
    result = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(dominant_missing_key="convivencia"),
        composer_output=_composer(),
    )
    assert result["last_dominant_missing_key"] == "convivencia"


def test_build_memory_update_registers_guidance_and_strategy():
    result = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(guidance_strength="high"),
        composer_output=_composer(
            turn_type="guided_followup",
            composition_strategy="followup_with_question_bridge",
        ),
    )
    assert result["last_guidance_strength"] == "high"
    assert result["last_turn_type"] == "guided_followup"
    assert result["last_composition_strategy"] == "followup_with_question_bridge"


# e.
def test_asked_missing_keys_accumulates_without_consecutive_dup():
    mem1 = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(action="ask", dominant_missing_key="convivencia"),
        composer_output=_composer(),
    )
    assert "convivencia" in mem1["asked_missing_keys_history"]

    # Mismo turno siguiente: no duplicar consecutivo
    mem2 = build_memory_update(
        current_memory=mem1,
        dialogue_policy=_policy(action="ask", dominant_missing_key="convivencia"),
        composer_output=_composer(),
    )
    assert mem2["asked_missing_keys_history"].count("convivencia") == 1

    # Key diferente: acumula
    mem3 = build_memory_update(
        current_memory=mem2,
        dialogue_policy=_policy(action="ask", dominant_missing_key="ingresos"),
        composer_output=_composer(),
    )
    assert "ingresos" in mem3["asked_missing_keys_history"]

    # Volver a convivencia (ya no es consecutivo): se agrega de nuevo
    mem4 = build_memory_update(
        current_memory=mem3,
        dialogue_policy=_policy(action="ask", dominant_missing_key="convivencia"),
        composer_output=_composer(),
    )
    assert mem4["asked_missing_keys_history"].count("convivencia") == 2


def test_asked_missing_keys_not_added_when_action_advise():
    result = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(action="advise", dominant_missing_key="convivencia"),
        composer_output=_composer(),
    )
    assert "convivencia" not in result["asked_missing_keys_history"]


# f.
def test_asked_missing_keys_history_respects_max_size():
    mem: dict = {}
    for i in range(MAX_ASKED_KEYS_HISTORY + 5):
        mem = build_memory_update(
            current_memory=mem,
            dialogue_policy=_policy(action="ask", dominant_missing_key=f"key_{i}"),
            composer_output=_composer(),
        )
    assert len(mem["asked_missing_keys_history"]) <= MAX_ASKED_KEYS_HISTORY


# g.
def test_used_lead_types_accumulates():
    mem1 = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(),
        composer_output=_composer(turn_type="clarification"),
    )
    assert "clarification" in mem1["used_lead_types"]

    mem2 = build_memory_update(
        current_memory=mem1,
        dialogue_policy=_policy(),
        composer_output=_composer(turn_type="guided_followup"),
    )
    assert "clarification" in mem2["used_lead_types"]
    assert "guided_followup" in mem2["used_lead_types"]


def test_used_lead_types_does_not_add_initial():
    result = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(),
        composer_output=_composer(turn_type="initial"),
    )
    assert "initial" not in result["used_lead_types"]


# h.
def test_should_vary_lead_true_when_repeated():
    mem: dict = {}
    for _ in range(LEAD_VARY_WINDOW):
        mem = build_memory_update(
            current_memory=mem,
            dialogue_policy=_policy(),
            composer_output=_composer(turn_type="clarification"),
        )
    assert should_vary_lead(mem, "clarification") is True


# i.
def test_should_vary_lead_false_when_not_repeated_enough():
    mem = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(),
        composer_output=_composer(turn_type="clarification"),
    )
    assert should_vary_lead(mem, "clarification") is False


def test_should_vary_lead_false_for_none_memory():
    assert should_vary_lead(None, "clarification") is False


def test_should_vary_lead_false_for_different_type():
    mem: dict = {}
    for _ in range(LEAD_VARY_WINDOW):
        mem = build_memory_update(
            current_memory=mem,
            dialogue_policy=_policy(),
            composer_output=_composer(turn_type="clarification"),
        )
    assert should_vary_lead(mem, "guided_followup") is False


# j.
def test_was_topic_explained_true_when_present():
    mem = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(action="hybrid"),
        composer_output=_composer(
            turn_type="guided_followup",
            composition_strategy="followup_with_question_bridge",
        ),
        conversation_state=_state(),
    )
    assert was_topic_explained(mem, "orientacion_base") is True


def test_was_topic_explained_false_when_not_present():
    assert was_topic_explained(normalize_memory(None), "orientacion_base") is False


def test_was_topic_explained_empty_topic_returns_false():
    mem = normalize_memory({"explained_topics": ["orientacion_base"]})
    assert was_topic_explained(mem, "") is False


# k.
def test_explained_topics_accumulate_across_turns():
    mem1 = build_memory_update(
        current_memory={},
        dialogue_policy=_policy(action="hybrid", dominant_missing_purpose="quantify"),
        composer_output=_composer(
            turn_type="guided_followup",
            composition_strategy="lead_followup",
        ),
        conversation_state=_state(working_case_type="alimentos_hijos"),
    )
    assert "orientacion_base" in mem1["explained_topics"]

    mem2 = build_memory_update(
        current_memory=mem1,
        dialogue_policy=_policy(action="advise", dominant_missing_purpose="quantify"),
        composer_output=_composer(
            turn_type="followup",
            composition_strategy="lead_followup",
        ),
        conversation_state=_state(working_case_type="alimentos_hijos"),
    )
    assert "cuantificacion" in mem2["explained_topics"]
    assert mem2["explained_topics"].count("orientacion_base") == 1


# l.
def test_build_memory_update_handles_none_inputs():
    result = build_memory_update(
        current_memory=None,
        dialogue_policy=None,
        composer_output=None,
    )
    assert isinstance(result, dict)
    assert isinstance(result["asked_missing_keys_history"], list)
    assert isinstance(result["used_lead_types"], list)


def test_get_asked_missing_keys_history_helper():
    mem = {"asked_missing_keys_history": ["convivencia", "ingresos"]}
    assert get_asked_missing_keys_history(mem) == ["convivencia", "ingresos"]


def test_get_asked_missing_keys_history_none():
    assert get_asked_missing_keys_history(None) == []
