# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\conversation_memory_service.py
"""
Fase 8.3 — Conversational Memory Refinement

Gestiona la sub-estructura `conversation_memory` dentro del snapshot de estado.
Solo contiene funciones puras y testeables — sin estado interno ni acceso a DB.

El campo conversation_memory vive en el snapshot del ConversationStateSnapshot,
persistido por conversation_state_service. Este módulo solo gestiona su contenido.

Contrato de conversation_memory:
{
    "last_dialogue_action":      str,   # acción del policy del último turno
    "last_guidance_strength":    str,   # guidance_strength del último turno
    "last_dominant_missing_key": str,   # dominant_missing_key del último turno
    "last_turn_type":            str,   # turn_type que detectó el composer
    "last_composition_strategy": str,   # estrategia que usó el composer
    "asked_missing_keys_history": list, # missing keys ya preguntadas (acumuladas)
    "explained_topics":          list,  # temas ya explicados (heurística)
    "used_lead_types":           list,  # tipos de apertura usados (acumulados)
}
"""
from __future__ import annotations

from typing import Any


# ─── Límites ──────────────────────────────────────────────────────────────────

MAX_ASKED_KEYS_HISTORY = 15
MAX_EXPLAINED_TOPICS = 10
MAX_USED_LEAD_TYPES = 12

# Cuántos turnos recientes se miran para decidir si variar la apertura
LEAD_VARY_WINDOW = 2


# ─── Valores por defecto ──────────────────────────────────────────────────────

_DEFAULT_MEMORY: dict[str, Any] = {
    "last_dialogue_action": "",
    "last_guidance_strength": "",
    "last_dominant_missing_key": "",
    "last_turn_type": "",
    "last_composition_strategy": "",
    "asked_missing_keys_history": [],
    "explained_topics": [],
    "used_lead_types": [],
}


# ─── API pública ──────────────────────────────────────────────────────────────


def normalize_memory(raw: dict[str, Any] | None) -> dict[str, Any]:
    """
    Asegura que conversation_memory tenga todos los campos con tipos correctos.
    Compatible con snapshots viejos (sin conversation_memory).
    """
    mem = dict(raw or {})
    result: dict[str, Any] = {}

    result["last_dialogue_action"] = str(mem.get("last_dialogue_action") or "")
    result["last_guidance_strength"] = str(mem.get("last_guidance_strength") or "")
    result["last_dominant_missing_key"] = str(mem.get("last_dominant_missing_key") or "")
    result["last_turn_type"] = str(mem.get("last_turn_type") or "")
    result["last_composition_strategy"] = str(mem.get("last_composition_strategy") or "")
    result["asked_missing_keys_history"] = list(mem.get("asked_missing_keys_history") or [])
    result["explained_topics"] = list(mem.get("explained_topics") or [])
    result["used_lead_types"] = list(mem.get("used_lead_types") or [])
    return result


def build_memory_update(
    *,
    current_memory: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
    composer_output: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Produce la memoria actualizada combinando el estado previo con los resultados
    del turno actual (dialogue_policy + composer_output).

    Diseñado para llamarse DESPUÉS de que policy y composer ya corrieron.
    """
    mem = normalize_memory(current_memory)
    policy = dict(dialogue_policy or {})
    composer = dict(composer_output or {})
    state = dict(conversation_state or {})

    # ── Registrar estado del último turno ──────────────────────────────────────
    action = str(policy.get("action") or "").strip()
    if action:
        mem["last_dialogue_action"] = action

    strength = str(policy.get("guidance_strength") or "").strip()
    if strength:
        mem["last_guidance_strength"] = strength

    dominant_key = str(policy.get("dominant_missing_key") or "").strip()
    if dominant_key:
        mem["last_dominant_missing_key"] = dominant_key

    turn_type = str(composer.get("turn_type") or "").strip()
    if turn_type:
        mem["last_turn_type"] = turn_type

    strategy = str(composer.get("composition_strategy") or "").strip()
    if strategy:
        mem["last_composition_strategy"] = strategy

    # ── Acumular asked_missing_keys_history ────────────────────────────────────
    # Solo cuando se hizo una pregunta sobre ese dato (action ask o hybrid)
    if dominant_key and action in ("ask", "hybrid"):
        mem["asked_missing_keys_history"] = _append_unique_capped(
            mem["asked_missing_keys_history"], dominant_key, MAX_ASKED_KEYS_HISTORY
        )

    # ── Acumular explained_topics ──────────────────────────────────────────────
    new_topics = _infer_explained_topics(policy=policy, composer=composer, state=state)
    for topic in new_topics:
        if topic not in mem["explained_topics"]:
            mem["explained_topics"] = _append_capped(
                mem["explained_topics"], topic, MAX_EXPLAINED_TOPICS
            )

    # ── Acumular used_lead_types ───────────────────────────────────────────────
    # No registrar "initial" (no tiene apertura significativa)
    if turn_type and turn_type != "initial":
        mem["used_lead_types"] = _append_capped(
            mem["used_lead_types"], turn_type, MAX_USED_LEAD_TYPES
        )

    return mem


def get_asked_missing_keys_history(memory: dict[str, Any] | None) -> list[str]:
    """Devuelve el historial de missing keys ya preguntadas en turnos anteriores."""
    return list(normalize_memory(memory).get("asked_missing_keys_history") or [])


def was_topic_explained(memory: dict[str, Any] | None, topic: str) -> bool:
    """
    ¿Ya se explicó este tema en la conversación?
    Los temas se registran en explained_topics via build_memory_update.
    """
    topic_clean = str(topic or "").strip()
    if not topic_clean:
        return False
    return topic_clean in list(normalize_memory(memory).get("explained_topics") or [])


def should_vary_lead(memory: dict[str, Any] | None, candidate_lead_type: str) -> bool:
    """
    ¿Conviene variar el tipo de apertura conversacional?

    Retorna True si candidate_lead_type aparece en los últimos LEAD_VARY_WINDOW
    entradas de used_lead_types, indicando que se repitió demasiado recientemente.
    """
    if not candidate_lead_type:
        return False
    mem = normalize_memory(memory)
    used = mem.get("used_lead_types") or []
    recent = used[-LEAD_VARY_WINDOW:]
    return recent.count(candidate_lead_type) >= LEAD_VARY_WINDOW


# ─── Helpers internos ─────────────────────────────────────────────────────────


def _append_unique_capped(lst: list[str], item: str, max_size: int) -> list[str]:
    """
    Agrega item a la lista SIN duplicar el último elemento.
    Respeta max_size (trunca por la cola si excede).
    """
    new_list = list(lst)
    if new_list and new_list[-1] == item:
        return new_list  # no duplicar consecutivo
    new_list.append(item)
    if len(new_list) > max_size:
        new_list = new_list[-max_size:]
    return new_list


def _append_capped(lst: list[str], item: str, max_size: int) -> list[str]:
    """
    Agrega item a la lista (permite repeticiones).
    Respeta max_size (trunca por la cola si excede).
    """
    new_list = list(lst)
    new_list.append(item)
    if len(new_list) > max_size:
        new_list = new_list[-max_size:]
    return new_list


def _infer_explained_topics(
    *,
    policy: dict[str, Any],
    composer: dict[str, Any],
    state: dict[str, Any],
) -> list[str]:
    """
    Infiere qué temas se explicaron en este turno.

    Heurística: solo registra cuando hubo contenido sustancial,
    no cuando el turno fue puramente de aclaración.
    """
    topics: list[str] = []
    turn_type = str(composer.get("turn_type") or "")
    action = str(policy.get("action") or "")
    strategy = str(composer.get("composition_strategy") or "")
    working_case_type = str(state.get("working_case_type") or "")
    dominant_purpose = str(policy.get("dominant_missing_purpose") or "")

    # Si se dio orientación base (no fue solo initial ni passthrough puro)
    if (
        strategy not in ("passthrough_initial", "passthrough")
        and turn_type not in ("initial", "")
    ):
        topics.append("orientacion_base")

    # Si se explicó el proceso del tipo de caso
    if (
        working_case_type
        and action in ("advise", "hybrid")
        and turn_type not in ("initial", "clarification")
    ):
        topics.append(f"proceso_{working_case_type}")

    # Si se dio orientación sobre cuantificación
    if dominant_purpose == "quantify" and action in ("hybrid", "advise"):
        topics.append("cuantificacion")

    return topics
