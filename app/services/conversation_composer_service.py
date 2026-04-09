# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\conversation_composer_service.py
"""
Fase 8.2D + 8.3 — Conversation Composer

Capa de composición conversacional: reduce repetición entre turnos, genera
continuidad narrativa y conecta las preguntas con el estado del caso.

Fase 8.3 agrega:
- Uso de conversation_memory para variar aperturas entre turnos
- Corrección de over-trimming: guidance_strength=low conserva al menos 1
  párrafo de contenido útil cuando la orientación base aún no fue dada
- Trim más agresivo cuando orientacion_base ya fue explicada en turnos previos
- Integración con conversation_memory_service (lazy import, sin dependencia dura)

Diseño: funciones pequeñas y testeables. Sin NLP pesado. Sin estado interno.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────

# Largo mínimo para considerar que un párrafo es "orientación genérica"
_MIN_ORIENTATION_LEN = 80

# Rango de longitud para considerar un párrafo como "útil y específico"
# (no es orientación genérica, pero tampoco es trivial)
_MIN_USEFUL_LEN = 30
_MAX_USEFUL_LEN_FOR_LOW = 280  # fix over-trimming: párrafos más cortos → específicos

# Cuántos párrafos de contenido conservar según guidance_strength
_MAX_CONTENT_PARAS_MEDIUM = 2
_MAX_CONTENT_PARAS_MEDIUM_EXPLAINED = 1  # más agresivo si orientación ya fue dada

# Keywords que el LLM usa en bloques de orientación genérica repetitivos
_ORIENTATION_KEYWORDS = (
    "de acuerdo",
    "en base a",
    "a partir de",
    "según la ley",
    "en argentina",
    "para reclamar",
    "el proceso",
    "el trámite",
    "la normativa",
    "el código",
    "a continuación",
    "a efectos de",
)
_ORIENTATION_MIN_HITS = 2

# ─── Lead text: frases por defecto y alternativas ─────────────────────────────
# Cada situación tiene (default, alternate). El alternate se usa cuando
# conversation_memory indica que el mismo tipo de apertura ya se usó recientemente.

_LEAD: dict[str, tuple[str, str]] = {
    "clarification_rich": (
        "Con lo que me contás ya tenemos una base. Necesito aclarar un punto más antes de orientarte.",
        "Eso ayuda a construir el caso. Antes de avanzar, necesito confirmar algo más.",
    ),
    "clarification_some": (
        "Para orientarte mejor, necesito aclarar algo importante primero.",
        "Antes de seguir, necesito que me confirmes un dato clave.",
    ),
    "clarification_none": (
        "Antes de seguir, necesito confirmar un dato clave.",
        "Para orientarte con precisión, necesito un dato importante.",
    ),
    "guided_followup_medium": (
        "Con lo que me explicaste ya hay contexto suficiente para orientarte, aunque todavía necesito precisar algún detalle.",
        "Bien. Hay base para avanzar, aunque me falta confirmar un punto más.",
    ),
    "guided_followup_high": (
        "Con lo que me dijiste ya tengo casi todo para orientarte bien.",
        "Casi tenemos lo que hace falta. Vamos avanzando.",
    ),
    "guided_followup_low": (
        "Con lo que me dijiste podemos seguir avanzando.",
        "Bien. Con esto ya podemos avanzar un poco más.",
    ),
    "partial_closure": (
        "Con todo lo que me explicaste ya tengo lo que necesito para orientarte.",
        "Con esto ya tenemos lo que hace falta para avanzar bien.",
    ),
    "followup_high": (
        "Con lo que me contás ya tenemos una base sólida para seguir.",
        "Muy bien. Con lo que me explicaste ya hay base más que suficiente.",
    ),
    "followup_medium": (
        "Con lo que me contás ya tenemos una base sólida para seguir.",
        "Lo que me dijiste suma. Podemos avanzar con lo que hay.",
    ),
    "followup_low": (
        "Con esto sumamos contexto importante. Sigamos avanzando.",
        "Bien. Con lo que me contás hay base para avanzar.",
    ),
}

_BODY_BRIDGE: dict[str, tuple[str, str]] = {
    "clarification": (
        "Con eso, lo que ya aparece claro es esto:",
        "Con ese contexto, hay algo que ya se puede ordenar mejor:",
    ),
    "guided_followup": (
        "Con eso, lo que conviene tener en cuenta ahora es esto:",
        "A partir de lo que ya sabemos, el cuadro se ordena asi:",
    ),
    "partial_closure": (
        "Con eso, el panorama ya queda bastante claro:",
        "A esta altura, el caso ya se deja encuadrar asi:",
    ),
    "followup": (
        "Con eso, lo que conviene mirar ahora es esto:",
        "Con lo que ya tenemos, el siguiente encuadre seria este:",
    ),
}


# ─── Helpers de memory service (lazy imports para resiliencia) ────────────────


def _should_vary_lead(memory: dict[str, Any] | None, lead_type: str) -> bool:
    """Wrapper resiliente para conversation_memory_service.should_vary_lead."""
    try:
        from app.services.conversation_memory_service import should_vary_lead
        return should_vary_lead(memory, lead_type)
    except Exception:
        return False


def _was_orientation_explained(memory: dict[str, Any] | None) -> bool:
    """¿Ya se explicó orientacion_base en turnos anteriores?"""
    try:
        from app.services.conversation_memory_service import was_topic_explained
        return was_topic_explained(memory, "orientacion_base")
    except Exception:
        return False


def _pick(key: str, vary: bool) -> str:
    """Selecciona default o alternate según flag de variación."""
    pair = _LEAD.get(key, ("", ""))
    return pair[1] if vary else pair[0]


# ─── Helpers de detección ─────────────────────────────────────────────────────


def detect_turn_type(
    conversation_state: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
) -> str:
    """
    Detecta el tipo de turno conversacional.

    Tipos posibles:
    - initial          → primer turno; respuesta completa sin modificar
    - clarification    → turno de aclaración pura (action=ask)
    - guided_followup  → orientación + pregunta (action=hybrid)
    - partial_closure  → orientación completa, falta poco (advise + completeness=high)
    - followup         → seguimiento genérico (resto de casos)
    """
    state = conversation_state or {}
    policy = dialogue_policy or {}

    turn_count = int(state.get("turn_count") or 0)
    action = str(policy.get("action") or "")
    completeness = str(
        (state.get("progress_signals") or {}).get("case_completeness") or "low"
    )

    if turn_count <= 1:
        return "initial"
    if action == "ask":
        return "clarification"
    if action == "hybrid":
        return "guided_followup"
    if action == "advise" and completeness == "high":
        return "partial_closure"
    return "followup"


def resolve_lead_text(
    turn_type: str,
    conversation_state: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
    conversation_memory: dict[str, Any] | None = None,
) -> str:
    """
    Genera una apertura conversacional corta según el tipo de turno.
    Para 'initial' devuelve cadena vacía.
    Para los demás, una frase que retoma el caso.

    Fase 8.3: usa conversation_memory para variar la frase si el mismo tipo
    de apertura se usó recientemente (evitar repetición de framing).
    """
    if turn_type == "initial":
        return ""

    state = conversation_state or {}
    del dialogue_policy  # no usado directamente; info ya extraída antes de esta función

    progress = state.get("progress_signals") or {}
    known_count = int(progress.get("known_fact_count") or 0)
    completeness = str(progress.get("case_completeness") or "low")

    vary = _should_vary_lead(conversation_memory, turn_type)

    if turn_type == "clarification":
        if known_count >= 3:
            return _pick("clarification_rich", vary)
        if known_count >= 1:
            return _pick("clarification_some", vary)
        return _pick("clarification_none", vary)

    if turn_type == "guided_followup":
        if completeness == "high":
            return _pick("guided_followup_high", vary)
        if completeness == "medium":
            return _pick("guided_followup_medium", vary)
        return _pick("guided_followup_low", vary)

    if turn_type == "partial_closure":
        return _pick("partial_closure", vary)

    # followup genérico
    if completeness == "high":
        return _pick("followup_high", vary)
    if completeness == "medium":
        return _pick("followup_medium", vary)
    return _pick("followup_low", vary)


def _is_orientation_paragraph(paragraph: str) -> bool:
    """
    Heurística: ¿este párrafo es un bloque de 'orientación inicial' genérica?

    Criterio: párrafo largo (>= _MIN_ORIENTATION_LEN chars) que contiene
    al menos _ORIENTATION_MIN_HITS palabras clave de orientación genérica.
    """
    if len(paragraph) < _MIN_ORIENTATION_LEN:
        return False
    normalized = paragraph.lower()
    hits = sum(1 for kw in _ORIENTATION_KEYWORDS if kw in normalized)
    return hits >= _ORIENTATION_MIN_HITS


def _is_useful_content_para(paragraph: str) -> bool:
    """
    ¿Es este párrafo útil y específico (no orientación genérica)?
    Se usa para decidir si conservar al menos un párrafo en guidance_strength=low.
    """
    return (
        _MIN_USEFUL_LEN <= len(paragraph) <= _MAX_USEFUL_LEN_FOR_LOW
        and not _is_orientation_paragraph(paragraph)
    )


def _resolve_output_mode(pipeline_payload: dict[str, Any] | None) -> str:
    """Extrae output_mode efectivo sin acoplar el composer al llamador."""
    payload = pipeline_payload or {}
    progression_policy = payload.get("progression_policy") or {}
    output_mode = str(
        progression_policy.get("output_mode")
        or payload.get("output_mode")
        or "orientacion_inicial"
    ).strip()
    return output_mode or "orientacion_inicial"


def _resolve_strategy_profile(pipeline_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = pipeline_payload or {}
    return dict(payload.get("strategy_composition_profile") or {})


def _resolve_strategy_language_profile(pipeline_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = pipeline_payload or {}
    return dict(payload.get("strategy_language_profile") or {})


def _resolve_medium_content_limit(
    *,
    turn_type: str,
    output_mode: str,
    already_explained_orientation: bool,
) -> int:
    """Ajusta la densidad segun tipo de turno y output_mode."""
    if turn_type == "clarification":
        return 1
    if output_mode == "ejecucion":
        return 1
    if already_explained_orientation:
        return _MAX_CONTENT_PARAS_MEDIUM_EXPLAINED
    return _MAX_CONTENT_PARAS_MEDIUM


def _trim_content_before_question(
    *,
    content_paras: list[str],
    turn_type: str,
    output_mode: str,
) -> list[str]:
    """Reduce friccion antes de una pregunta sin volver seca la respuesta."""
    if not content_paras:
        return []
    if turn_type == "clarification":
        return content_paras[:1]
    if output_mode == "ejecucion":
        return content_paras[:1]
    if output_mode == "estrategia":
        return content_paras[:2]
    return content_paras


def _looks_like_followup_prompt(paragraph: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(paragraph or "").strip().lower())
    if not normalized:
        return False
    if "?" in paragraph or "¿" in paragraph:
        return True
    if normalized.startswith(("hay ", "existen ", "si hay ", "tienen ", "ya hay ", "cual ", "como ", "cuando ", "donde ", "quien ")):
        return True
    if normalized.startswith(("definir si", "confirmar si", "precisar si", "verificar si")):
        return True
    return False


def _ensure_question_paragraph(paragraph: str) -> str:
    text = re.sub(r"\s+", " ", str(paragraph or "").strip())
    if not text:
        return ""
    if "?" in text:
        return text
    text = text.rstrip(".:;")
    lowered = text[:1].lower() + text[1:] if len(text) > 1 else text.lower()
    return f"¿{lowered}?"


def _split_followup_paragraphs(body_text: str, action: str) -> tuple[list[str], list[str]]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body_text) if p.strip()]
    question_paras = [p for p in paragraphs if "?" in p or "¿" in p]
    content_paras = [p for p in paragraphs if p not in question_paras]
    if question_paras:
        question_paras = [_ensure_question_paragraph(p) for p in question_paras]
        return content_paras, question_paras
    if action in {"ask", "hybrid"} and paragraphs:
        candidate = paragraphs[-1]
        if _looks_like_followup_prompt(candidate):
            return paragraphs[:-1], [_ensure_question_paragraph(candidate)]
    return paragraphs, []


def estimate_repetition(
    response_text: str,
    turn_count: int,
    already_explained_orientation: bool = False,
) -> bool:
    """
    Estima si response_text contiene un bloque de orientación genérica repetitivo.

    Fase 8.3: si already_explained_orientation=True, usa un umbral menor
    (incluso párrafos más cortos se clasifican como repetición).
    """
    if turn_count <= 1:
        return False
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", response_text) if p.strip()]
    if not paragraphs:
        return False

    # Con orientación ya explicada: más agresivo
    if already_explained_orientation and len(paragraphs[0]) > _MIN_ORIENTATION_LEN // 2:
        return True

    return _is_orientation_paragraph(paragraphs[0])


def trim_body_for_strength(
    body_text: str,
    guidance_strength: str,
    turn_type: str,
    already_explained_orientation: bool = False,
    output_mode: str = "orientacion_inicial",
) -> str:
    """
    Recorta el body_text según guidance_strength para controlar la profundidad.

    Reglas:
    - initial / partial_closure: sin recorte
    - high: sin recorte
    - medium: máx _MAX_CONTENT_PARAS_MEDIUM párrafos + preguntas
      (reducido a _MAX_CONTENT_PARAS_MEDIUM_EXPLAINED si orientación ya fue explicada)
    - low: 1 párrafo útil (si orientación no fue explicada) + preguntas
      Si orientación ya fue explicada: solo preguntas (trim agresivo)

    Siempre preserva párrafos con '?' para no perder la pregunta.
    """
    if turn_type in ("initial", "partial_closure"):
        return body_text
    if guidance_strength == "high":
        return body_text

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body_text) if p.strip()]
    if len(paragraphs) <= 1:
        return body_text

    question_paras = [p for p in paragraphs if "?" in p]
    content_paras = [p for p in paragraphs if "?" not in p]
    if not question_paras and turn_type in ("clarification", "guided_followup") and paragraphs:
        candidate = paragraphs[-1]
        if _looks_like_followup_prompt(candidate):
            question_paras = [_ensure_question_paragraph(candidate)]
            content_paras = paragraphs[:-1]

    if guidance_strength == "low":
        if question_paras:
            if already_explained_orientation:
                # Trim agresivo: solo preguntas
                return "\n\n".join(question_paras)
            # Fix over-trimming: conservar 1 párrafo útil si existe
            useful = [p for p in content_paras if _is_useful_content_para(p)]
            if useful:
                return "\n\n".join([useful[0]] + question_paras)
            return "\n\n".join(question_paras)
        # Sin preguntas: no recortar (no perder contenido)
        return body_text

    # medium
    max_content = _resolve_medium_content_limit(
        turn_type=turn_type,
        output_mode=output_mode,
        already_explained_orientation=already_explained_orientation,
    )
    kept_content = content_paras[:max_content]
    result_paras = kept_content + question_paras

    if len(result_paras) >= len(paragraphs):
        return body_text

    return "\n\n".join(result_paras)


def build_question_intro(
    dialogue_policy: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    output_mode: str = "orientacion_inicial",
) -> str:
    """
    Construye una frase introductoria para la pregunta dominante.
    Conecta la pregunta con el estado del caso en vez de dejarla suelta.

    Retorna cadena vacía si no aplica (no hay pregunta, turno inicial, etc.).
    """
    policy = dialogue_policy or {}
    action = str(policy.get("action") or "")

    if action not in ("ask", "hybrid"):
        return ""

    dominant_key = str(policy.get("dominant_missing_key") or "")
    dominant_purpose = str(policy.get("dominant_missing_purpose") or "")

    if not dominant_key:
        return ""

    progress = (conversation_state or {}).get("progress_signals") or {}
    completeness = str(progress.get("case_completeness") or "low")

    if output_mode == "ejecucion":
        return "Para ajustar bien el paso siguiente, necesito saber:"
    if output_mode == "estrategia" and dominant_purpose in {"enable", "identify"}:
        return "Para cerrar bien esta decision, necesito saber:"

    if dominant_purpose == "enable":
        return "Para seguir sin dejar este punto abierto, necesito que me confirmes un dato clave:"
    if dominant_purpose == "identify":
        return "Para terminar de ubicar bien la situación, necesito aclarar:"
    if dominant_purpose == "quantify":
        if completeness in ("medium", "high"):
            return (
                "Ya tenemos el contexto principal. "
                "Para afinar bien lo que sigue, necesito saber:"
            )
        return "Para poder orientarte mejor en este punto, necesito saber:"
    if dominant_purpose == "prove":
        return "Para medir qué tan firme queda este punto, necesito entender:"
    if dominant_purpose == "situational":
        return "Para completar bien el panorama, me ayudaría saber:"

    return "Para seguir con una orientación útil, necesito aclarar algo:"


def build_body_bridge(
    turn_type: str,
    dialogue_policy: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    conversation_memory: dict[str, Any] | None = None,
    output_mode: str = "orientacion_inicial",
) -> str:
    """
    Frase puente breve entre la apertura y el contenido principal.
    Ayuda a que la respuesta avance con más continuidad.
    """
    if turn_type == "initial":
        return ""

    policy = dialogue_policy or {}
    state = conversation_state or {}
    action = str(policy.get("action") or "")
    completeness = str((state.get("progress_signals") or {}).get("case_completeness") or "low")

    if action not in {"ask", "hybrid", "advise"}:
        return ""
    if action == "ask" and completeness == "low" and turn_type == "clarification":
        return ""
    if output_mode == "ejecucion" and action in {"ask", "hybrid"}:
        return ""

    bridge_key = turn_type if turn_type in _BODY_BRIDGE else "followup"
    vary = _should_vary_lead(conversation_memory, turn_type)
    return _pick_bridge(bridge_key, vary)


# ─── Composición interna ──────────────────────────────────────────────────────


def _strip_leading_orientation(response_text: str) -> tuple[str, bool]:
    """
    Si el primer párrafo es un bloque de orientación genérica, lo elimina.
    Devuelve (texto_sin_orientacion, fue_recortado).
    No modifica si el resultado quedaría vacío.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", response_text) if p.strip()]
    if not paragraphs or len(paragraphs) == 1:
        return response_text, False

    if _is_orientation_paragraph(paragraphs[0]):
        rest = paragraphs[1:]
        return "\n\n".join(rest).strip(), True

    return response_text, False


def _resolve_composition_strategy(
    turn_type: str,
    repetition_reduced: bool,
    body_bridge: str,
    question_intro: str,
    lead_text: str,
) -> str:
    """Nombre de la estrategia aplicada, para observabilidad."""
    if turn_type == "initial":
        return "passthrough_initial"
    if repetition_reduced and question_intro:
        return "dedup_with_question_bridge"
    if repetition_reduced:
        return "dedup_followup"
    if body_bridge and question_intro:
        return "followup_with_flow_glue"
    if question_intro and lead_text:
        return "followup_with_question_bridge"
    if body_bridge and lead_text:
        return "lead_with_body_bridge"
    if lead_text:
        return "lead_followup"
    return "passthrough"


# ─── API pública ──────────────────────────────────────────────────────────────


def compose(
    *,
    conversation_state: dict[str, Any] | None,
    dialogue_policy: dict[str, Any] | None,
    response_text: str,
    pipeline_payload: dict[str, Any] | None = None,
    consistency_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compone la respuesta conversacional final.

    Fase 8.3: extrae conversation_memory de conversation_state y la usa para:
    - variar la apertura si el mismo tipo se usó recientemente
    - decidir agresividad del trim según temas ya explicados
    - reducir mejor la repetición de orientación base

    Fase 12.7: acepta consistency_policy del conversation_consistency_service.
    Aplica suppress flags y lead_type_whitelist antes de ensamblar partes,
    garantizando coherencia entre strategy_mode y la respuesta final.

    Contrato de salida:
    {
        "turn_type":              str,
        "lead_text":              str,
        "body_text":              str,
        "question_intro":         str,
        "composed_response_text": str,
        "repetition_reduced":     bool,
        "composition_strategy":   str,
    }

    En caso de fallo retorna {} — el llamador (postprocessor) usa el texto base.
    """
    state = conversation_state or {}
    policy = dialogue_policy or {}
    turn_count = int(state.get("turn_count") or 0)
    consistency = dict(consistency_policy or {})

    # 8.3: extraer memoria conversacional del snapshot
    conversation_memory = state.get("conversation_memory") or {}
    output_mode = _resolve_output_mode(pipeline_payload)
    strategy_profile = _resolve_strategy_profile(pipeline_payload)
    strategy_language_profile = _resolve_strategy_language_profile(pipeline_payload)
    strategy_mode = str(strategy_profile.get("strategy_mode") or "").strip().lower()

    # 8.3: determinar si orientación base ya fue explicada
    already_explained_orientation = _was_orientation_explained(conversation_memory)

    # 1. Tipo de turno
    turn_type = detect_turn_type(state, policy)

    # 2. Apertura conversacional (8.3: con variación por memoria)
    lead_text = resolve_lead_text(turn_type, state, policy, conversation_memory)
    if output_mode != "orientacion_inicial":
        lead_text = ""
    elif str(strategy_profile.get("opening_style") or "").strip().lower() == "none":
        lead_text = ""
    elif str(strategy_language_profile.get("selected_opening") or "").strip():
        lead_text = str(strategy_language_profile.get("selected_opening") or "").strip()

    # FASE 12.7 — Consistency guard: suppress_lead
    # Aplicar DESPUÉS de la lógica base para tener el turn_type ya resuelto.
    if consistency.get("suppress_lead"):
        lead_text = ""
    elif consistency.get("lead_type_whitelist") is not None:
        # Whitelist no-None y vacía → sin lead. Whitelist con valores → filtrar por tipo.
        whitelist: list[str] = list(consistency["lead_type_whitelist"])
        if not whitelist or turn_type not in whitelist:
            lead_text = ""

    # 3. Reducción de repetición (8.3: con umbral ajustado por memoria)
    repetition_detected = estimate_repetition(
        response_text, turn_count, already_explained_orientation
    )
    body_text = response_text
    repetition_reduced = False

    if repetition_detected and turn_type != "initial":
        stripped, was_stripped = _strip_leading_orientation(response_text)
        if was_stripped and stripped:
            body_text = stripped
            repetition_reduced = True

    # 4. Modular profundidad por guidance_strength (8.3: con flag de orientación explicada)
    guidance_strength = str(policy.get("guidance_strength") or "medium")
    density = str(strategy_profile.get("content_density") or "").strip().lower()
    if density == "brief":
        guidance_strength = "low"
    elif density == "extended":
        guidance_strength = "high"
    if output_mode != "orientacion_inicial" and strategy_mode not in {"clarify_critical", "action_first"}:
        if guidance_strength == "low":
            guidance_strength = "medium"
    body_text = trim_body_for_strength(
        body_text,
        guidance_strength,
        turn_type,
        already_explained_orientation,
        output_mode,
    )

    # FASE 12.7 — Consistency guard: max_body_paragraphs
    max_body_paragraphs = consistency.get("max_body_paragraphs")
    if max_body_paragraphs is not None and turn_type != "initial":
        limit = int(max_body_paragraphs)
        body_paras_raw = [p.strip() for p in re.split(r"\n{2,}", body_text) if p.strip()]
        question_paras_raw = [p for p in body_paras_raw if "?" in p]
        content_paras_raw = [p for p in body_paras_raw if "?" not in p]
        if len(content_paras_raw) > limit:
            body_text = "\n\n".join(content_paras_raw[:limit] + question_paras_raw)

    # 5. Frases puente para el flujo del turno
    body_bridge = build_body_bridge(
        turn_type,
        policy,
        state,
        conversation_memory,
        output_mode,
    )
    question_intro = build_question_intro(policy, state, output_mode)
    if output_mode == "orientacion_inicial" and str(strategy_language_profile.get("selected_bridge") or "").strip():
        body_bridge = str(strategy_language_profile.get("selected_bridge") or "").strip()
    if str(strategy_language_profile.get("selected_followup_intro") or "").strip():
        question_intro = str(strategy_language_profile.get("selected_followup_intro") or "").strip()
    if not bool(strategy_profile.get("allow_followup", True)):
        question_intro = ""
    if bool(strategy_profile.get("prioritize_action")):
        body_bridge = ""

    # FASE 12.7 — Consistency guards: suppress_body_bridge / suppress_question_intro
    if consistency.get("suppress_body_bridge"):
        body_bridge = ""
    if consistency.get("suppress_question_intro"):
        question_intro = ""

    # 6. Ensamblar texto compuesto
    parts: list[str] = []

    if lead_text:
        parts.append(lead_text)

    action = str(policy.get("action") or "")
    if question_intro and action in ("ask", "hybrid") and turn_type != "initial":
        # Separar body en contenido y pregunta para insertar intro como puente
        content_paras, question_paras = _split_followup_paragraphs(body_text, action)
        allow_full_content = (
            turn_type == "guided_followup"
            and guidance_strength in ("medium", "high")
        )
        if not allow_full_content:
            content_paras = _trim_content_before_question(
                content_paras=content_paras,
                turn_type=turn_type,
                output_mode=output_mode,
            )

        if content_paras and question_paras:
            if body_bridge:
                parts.append(body_bridge)
            parts.extend(content_paras)
            parts.append(question_intro)
            parts.extend(question_paras)
        elif question_paras and not content_paras:
            parts.append(question_intro)
            parts.extend(question_paras)
        else:
            if body_text.strip():
                if body_bridge:
                    parts.append(body_bridge)
                parts.append(body_text.strip())
    else:
        if body_text.strip():
            if body_bridge:
                parts.append(body_bridge)
            parts.append(body_text.strip())

    composed = "\n\n".join(p for p in parts if p.strip())

    # Guardia: si la composición quedó vacía, usar el texto original
    if not composed.strip():
        composed = response_text

    strategy = _resolve_composition_strategy(
        turn_type, repetition_reduced, body_bridge, question_intro, lead_text
    )

    return {
        "turn_type": turn_type,
        "lead_text": lead_text,
        "body_text": body_text,
        "body_bridge": body_bridge,
        "question_intro": question_intro,
        "composed_response_text": composed,
        "repetition_reduced": repetition_reduced,
        "composition_strategy": strategy,
    }


def _pick_bridge(key: str, vary: bool) -> str:
    pair = _BODY_BRIDGE.get(key, ("", ""))
    return pair[1] if vary else pair[0]
