from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.services.conversational.adaptive_policy import (
    apply_adaptive_adjustments,
    build_adaptive_context,
)


@dataclass(slots=True)
class QuestionCandidate:
    key: str
    text: str
    category: str
    base_score: float
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        breakdown = dict(self.score_breakdown)
        breakdown["total"] = round(self.score, 2)
        return {
            "key": self.key,
            "text": self.text,
            "category": self.category,
            "score": round(self.score, 2),
            "reasons": list(self.reasons),
            "score_breakdown": breakdown,
        }


_ALIMENTOS_CANDIDATES: tuple[QuestionCandidate, ...] = (
    QuestionCandidate(
        key="aportes_actuales",
        text="¿El otro progenitor está aportando algo actualmente?",
        category="viabilidad_inmediata",
        base_score=5.4,
    ),
    QuestionCandidate(
        key="convivencia",
        text="¿Tu hija o hijo vive con vos actualmente?",
        category="encuadre_familiar",
        base_score=5.0,
    ),
    QuestionCandidate(
        key="notificacion",
        text="¿Tenés algún domicilio o dato útil para poder ubicar al otro progenitor?",
        category="notificacion",
        base_score=4.9,
    ),
    QuestionCandidate(
        key="ingresos",
        text="¿Sabés si el otro progenitor tiene ingresos o una actividad laboral identificable?",
        category="prueba_economica",
        base_score=4.95,
    ),
    QuestionCandidate(
        key="urgencia",
        text="¿Hay alguna necesidad urgente del hijo o hija que convenga plantear desde el inicio?",
        category="urgencia",
        base_score=4.1,
    ),
    QuestionCandidate(
        key="antecedentes",
        text="¿Ya hubo algún reclamo, acuerdo o intimación previa por alimentos?",
        category="antecedentes",
        base_score=3.45,
    ),
)

_KNOWN_FACT_ALIASES = {
    "aportes_actuales": (
        "aportes_actuales",
        "aporta_actualmente",
        "otro_progenitor_aporta_actualmente",
        "cumplimiento_alimentos",
        "pago_actual_alimentos",
    ),
    "convivencia": (
        "convivencia",
        "convivencia_hijo",
        "convivencia_con_hijo",
        "hijo_convive_consultante",
        "cuidado_personal_de_hecho",
    ),
    "notificacion": (
        "notificacion",
        "domicilio_otro_progenitor",
        "ubicacion_otro_progenitor",
        "puede_notificar_otro_progenitor",
        "otro_progenitor_localizable",
    ),
    "ingresos": (
        "ingresos_otro_progenitor",
        "actividad_otro_progenitor",
        "trabajo_otro_progenitor",
        "otro_progenitor_tiene_ingresos",
    ),
    "urgencia": (
        "urgencia",
        "necesidad_urgente",
        "riesgo_inmediato",
    ),
    "antecedentes": (
        "reclamo_previo",
        "acuerdo_previo",
        "intimacion_previa",
        "incumplimiento_previo",
    ),
}

_QUERY_RESOLUTION_PATTERNS = {
    "aportes_actuales": (
        r"\bno paga\b",
        r"\bno aporta\b",
        r"\bno me pasa plata\b",
        r"\bno me pasa nada\b",
        r"\bno cumple\b",
        r"\bno se hace cargo\b",
        r"\bno ayuda\b",
        r"\bno colabora\b",
        r"\bse hace el desentendido\b",
        r"\bdejo de pagar\b",
        r"\bdejo de depositar\b",
        r"\baporta muy poco\b",
        r"\bpaga muy poco\b",
        r"\bpaga poco\b",
        r"\baporta poco\b",
        r"\bme deposita poco\b",
        r"\bde forma irregular\b",
        r"\birregular\b",
        r"\baporta regularmente\b",
        r"\bpaga regularmente\b",
        r"\bdeposita todos los meses\b",
    ),
    "convivencia": (
        r"\bconvive\b",
        r"\bvive conmigo\b",
        r"\besta conmigo\b",
        r"\besta a mi cargo\b",
        r"\bvive con su madre\b",
        r"\bvive con su padre\b",
        r"\bconvive con su madre\b",
        r"\bconvive con su padre\b",
    ),
    "notificacion": (
        r"\bno se donde vive\b",
        r"\bdesconozco su domicilio\b",
        r"\bno lo puedo ubicar\b",
        r"\bno la puedo ubicar\b",
        r"\bno se nada de el\b",
        r"\bno se nada de ella\b",
        r"\bdesaparecio\b",
        r"\btengo domicilio\b",
        r"\bse donde vive\b",
        r"\bpuedo notificar\b",
        r"\blo puedo ubicar\b",
        r"\bla puedo ubicar\b",
    ),
    "ingresos": (
        r"\btrabaja\b",
        r"\btiene trabajo\b",
        r"\btiene ingresos\b",
        r"\besta en blanco\b",
        r"\best[aá] empleado\b",
        r"\bmonotribut",
        r"\bchangas\b",
    ),
    "urgencia": (
        r"\burgente\b",
        r"\burgencia\b",
        r"\bnecesito resolverlo ya\b",
        r"\bno tengo para comer\b",
        r"\bno alcanza para alimentos\b",
        r"\bno alcanza para el colegio\b",
        r"\bno alcanza para remedios\b",
        r"\bmedicamentos\b",
        r"\btratamiento\b",
    ),
    "antecedentes": (
        r"\bya reclame\b",
        r"\bhubo acuerdo\b",
        r"\bmediacion\b",
        r"\bintimacion\b",
        r"\bcarta documento\b",
        r"\bnunca reclame\b",
    ),
}

_QUERY_CONTEXT_HINT_PATTERNS = {
    "convivencia": (
        r"\bmi hija\b",
        r"\bmi hijo\b",
        r"\bpor mi hija\b",
        r"\bpor mi hijo\b",
    ),
}

_MISSING_FACT_PATTERNS = {
    "aportes_actuales": (
        "aporta",
        "aporte",
        "paga",
        "pago",
        "cumplimiento",
        "cuota alimentaria",
        "alimentos adeudados",
    ),
    "convivencia": (
        "convivencia",
        "convive",
        "vive con",
        "cuidado personal",
        "a cargo",
    ),
    "notificacion": (
        "notificacion",
        "notificar",
        "ubicar",
        "domicilio",
        "direccion",
        "localizar",
    ),
    "ingresos": (
        "ingresos",
        "actividad laboral",
        "trabaja",
        "sueldo",
        "salario",
        "recibos",
    ),
    "urgencia": (
        "urgencia",
        "urgente",
        "cuota provisoria",
        "alimentos provisorios",
        "necesidad inmediata",
    ),
    "antecedentes": (
        "reclamo previo",
        "acuerdo previo",
        "mediacion",
        "intimacion",
        "incumplimiento previo",
    ),
}

_CANONICAL_SIGNAL_PATTERNS = {
    "incumplimiento_aportes": (
        r"\bno paga\b",
        r"\bno aporta\b",
        r"\bno me pasa plata\b",
        r"\bno me pasa nada\b",
        r"\bno cumple\b",
        r"\bno se hace cargo\b",
        r"\bno ayuda\b",
        r"\bno colabora\b",
        r"\bse hace el desentendido\b",
        r"\bdejo de pagar\b",
        r"\baporta poco\b",
        r"\baporta muy poco\b",
        r"\bpaga poco\b",
        r"\bme deposita poco\b",
        r"\birregular\b",
    ),
    "intencion_inicio_reclamo": (
        r"\biniciar\b",
        r"\binicio\b",
        r"\bdemanda\b",
        r"\bjuicio\b",
        r"\breclamar\b",
        r"\breclamo\b",
        r"\bquiero reclamar\b",
        r"\bcomo hago\b",
        r"\bque tengo que hacer\b",
        r"\bquiero pedir alimentos\b",
        r"\bnecesito reclamar\b",
        r"\bcomo inicio\b",
        r"\bdonde se hace\b",
        r"\bquiero empezar el tramite\b",
    ),
    "problema_ubicacion": (
        r"\bno se donde vive\b",
        r"\bdesconozco su domicilio\b",
        r"\bno lo puedo ubicar\b",
        r"\bno la puedo ubicar\b",
        r"\bdesaparecio\b",
        r"\bno se nada de el\b",
        r"\bno se nada de ella\b",
    ),
    "urgencia_reclamo": (
        r"\burgente\b",
        r"\burgencia\b",
        r"\bhoy mismo\b",
        r"\bde inmediato\b",
        r"\bno tengo para comer\b",
        r"\bno alcanza para alimentos\b",
        r"\bno alcanza para el colegio\b",
        r"\bno alcanza para remedios\b",
        r"\bmedicamentos\b",
        r"\btratamiento\b",
    ),
    "antecedente_reclamo": (
        r"\bya reclame\b",
        r"\bhubo acuerdo\b",
        r"\bmediacion\b",
        r"\bintimacion\b",
        r"\bcarta documento\b",
        r"\bnunca reclame\b",
    ),
    "encuadre_familiar": (
        r"\bmi hija\b",
        r"\bmi hijo\b",
        r"\bpor mi hija\b",
        r"\bpor mi hijo\b",
    ),
}

_BREAKDOWN_KEYS = (
    "base",
    "viability",
    "urgency",
    "notification",
    "evidence",
    "history",
    "context",
    "adaptive",
    "redundancy_penalty",
    "history_penalty",
)


def derive_canonical_signals(normalized_query: str) -> dict[str, bool]:
    return {
        signal: any(re.search(pattern, normalized_query) for pattern in patterns)
        for signal, patterns in _CANONICAL_SIGNAL_PATTERNS.items()
    }


def build_primary_question_for_alimentos(context: dict[str, Any]) -> dict[str, Any] | None:
    adaptive_context = build_adaptive_context(
        context.get("conversation_memory"),
        last_exchange=context.get("last_exchange"),
    )
    candidates = build_question_candidates_for_alimentos(context)
    selected = select_best_question(candidates)
    if not selected:
        return None

    return {
        "selected": selected.to_dict(),
        "candidates_considered": len(candidates),
        "adaptive_context": adaptive_context,
    }


def select_primary_question_for_alimentos(
    *,
    known_facts: dict[str, Any] | None,
    missing_facts: list[str] | None,
    query_text: str | None,
    clarification_context: dict[str, Any] | None = None,
    conversation_memory: dict[str, Any] | None = None,
) -> str | None:
    selection = build_primary_question_for_alimentos(
        {
            "known_facts": known_facts or {},
            "missing_facts": missing_facts or [],
            "query_text": query_text or "",
            "clarification_context": clarification_context or {},
            "conversation_memory": conversation_memory or {},
        }
    )
    if not selection:
        return None
    return str(selection["selected"]["text"])


def build_question_candidates_for_alimentos(context: dict[str, Any]) -> list[QuestionCandidate]:
    candidates: list[QuestionCandidate] = []
    for template in _ALIMENTOS_CANDIDATES:
        candidate = QuestionCandidate(
            key=template.key,
            text=template.text,
            category=template.category,
            base_score=template.base_score,
        )
        _score_question_candidate(candidate, context)
        if candidate.score > 0:
            candidates.append(candidate)
    return candidates


def select_best_question(candidates: list[QuestionCandidate]) -> QuestionCandidate | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda candidate: (-candidate.score, len(candidate.text), candidate.key),
    )[0]


def _score_question_candidate(candidate: QuestionCandidate, context: dict[str, Any]) -> None:
    conversation_memory = dict(context.get("conversation_memory") or {})
    known_facts = dict(conversation_memory.get("known_facts") or {})
    known_facts.update(dict(context.get("known_facts") or {}))
    missing_facts = [str(item).strip() for item in (context.get("missing_facts") or []) if str(item or "").strip()]
    query_text = str(context.get("query_text") or "")
    clarification_context = dict(context.get("clarification_context") or {})
    asked_questions = [
        str(item).strip()
        for item in (
            list(conversation_memory.get("asked_questions") or [])
            + list(clarification_context.get("asked_questions") or [])
        )
        if str(item or "").strip()
    ]
    normalized_query = _normalize_text(query_text)
    signals = derive_canonical_signals(normalized_query)
    for key, value in dict(conversation_memory.get("canonical_signals") or {}).items():
        signals[str(key)] = signals.get(str(key), False) or bool(value)
    resolved_slots = set(str(item).strip() for item in (conversation_memory.get("resolved_slots") or []) if str(item or "").strip())

    candidate.score_breakdown = {key: 0.0 for key in _BREAKDOWN_KEYS}
    candidate.score_breakdown["base"] = candidate.base_score
    candidate.score = candidate.base_score
    candidate.reasons.append(f"base:{candidate.base_score}")

    if candidate.key in resolved_slots or _slot_is_resolved(candidate.key, known_facts=known_facts, normalized_query=normalized_query):
        candidate.score_breakdown["redundancy_penalty"] -= 100.0
        candidate.score = -100.0
        candidate.reasons.append("slot_resuelto")
        return

    if _question_was_already_asked(candidate.text, asked_questions):
        _apply_component(candidate, "history_penalty", -8.0, "ya_preguntada")

    if _slot_has_hint(candidate.key, missing_facts=missing_facts):
        _apply_component(candidate, "context", 0.9, "hint_en_missing_facts")

    if signals["intencion_inicio_reclamo"]:
        if candidate.key == "aportes_actuales":
            _apply_component(candidate, "viability", 1.35, "util_para_iniciar_reclamo")
        elif candidate.key == "notificacion":
            _apply_component(candidate, "notification", 1.15, "impacta_en_viabilidad_inicial")
        elif candidate.key == "ingresos":
            _apply_component(candidate, "evidence", 0.75, "sirve_para_prueba_y_cuantificacion")
        elif candidate.key == "convivencia":
            _apply_component(candidate, "context", 0.45, "ayuda_a_orientar_legitimacion_y_prueba")
        elif candidate.key == "urgencia":
            _apply_component(candidate, "urgency", 0.35, "sirve_para_medidas_iniciales")

    if signals["incumplimiento_aportes"]:
        if candidate.key == "convivencia":
            _apply_component(candidate, "viability", 1.35, "destraba_encuadre_familiar")
        elif candidate.key == "urgencia":
            _apply_component(candidate, "urgency", 0.95, "incumplimiento_puede_requerir_urgencia")
        elif candidate.key == "notificacion":
            _apply_component(candidate, "notification", 0.85, "ayuda_a_ejecutar_reclamo")
        elif candidate.key == "ingresos":
            _apply_component(candidate, "evidence", 0.7, "mejora_prueba_y_cuantificacion")
        elif candidate.key == "antecedentes":
            _apply_component(candidate, "history", 0.35, "aporta_historial_si_hay_senal")
        elif candidate.key == "aportes_actuales":
            _apply_component(candidate, "redundancy_penalty", -6.0, "seria_redundante_preguntar_si_aporta")

    if signals["problema_ubicacion"]:
        if candidate.key == "notificacion":
            candidate.score_breakdown["redundancy_penalty"] -= 100.0
            candidate.score = -100.0
            candidate.reasons.append("ubicacion_ya_informada_como_problema")
            return
        if candidate.key == "ingresos":
            _apply_component(candidate, "notification", 0.95, "puede_dar_pista_sobre_ubicacion_o_prueba")
        elif candidate.key == "aportes_actuales":
            _apply_component(candidate, "viability", 0.6, "conviene_medir_incumplimiento_antes_de_notificar")

    if signals["urgencia_reclamo"]:
        if candidate.key == "urgencia":
            candidate.score_breakdown["redundancy_penalty"] -= 100.0
            candidate.score = -100.0
            candidate.reasons.append("urgencia_ya_explicita")
            return
        if candidate.key in {"aportes_actuales", "notificacion", "convivencia"}:
            _apply_component(candidate, "urgency", 0.7, "urgencia_vuelve_mas_util_la_pregunta")

    if signals["antecedente_reclamo"] and candidate.key == "antecedentes":
        candidate.score_breakdown["history_penalty"] -= 100.0
        candidate.score = -100.0
        candidate.reasons.append("antecedente_ya_mencionado")
        return

    if candidate.key == "antecedentes":
        if _slot_has_hint(candidate.key, missing_facts=missing_facts):
            _apply_component(candidate, "history", 0.45, "hint_sobre_historial")
        elif not signals["antecedente_reclamo"]:
            _apply_component(candidate, "history_penalty", -0.95, "menos_util_que_otras_preguntas_inmediatas")

    if candidate.key == "urgencia" and not (
        signals["urgencia_reclamo"]
        or _slot_has_hint(candidate.key, missing_facts=missing_facts)
        or signals["incumplimiento_aportes"]
    ):
        _apply_component(candidate, "urgency", -0.9, "pregunta_urgencia_no_prioritaria_ahora")

    if _slot_has_context_hint(candidate.key, normalized_query=normalized_query):
        _apply_component(candidate, "context", 0.2, "senal_contextual")

    adaptive_context = build_adaptive_context(
        conversation_memory,
        last_exchange=context.get("last_exchange"),
    )
    apply_adaptive_adjustments(candidate, adaptive_context)
    candidate.score = round(sum(candidate.score_breakdown.values()), 2)


def _apply_component(candidate: QuestionCandidate, component: str, value: float, reason: str) -> None:
    candidate.score_breakdown[component] += value
    candidate.reasons.append(reason)


def _slot_is_resolved(slot: str, *, known_facts: dict[str, Any], normalized_query: str) -> bool:
    for alias in _KNOWN_FACT_ALIASES.get(slot, ()):
        if _has_meaningful_value(known_facts.get(alias)):
            return True

    return any(re.search(pattern, normalized_query) for pattern in _QUERY_RESOLUTION_PATTERNS.get(slot, ()))


def _slot_has_hint(slot: str, *, missing_facts: list[str]) -> bool:
    patterns = _MISSING_FACT_PATTERNS.get(slot, ())
    normalized_missing = [_normalize_text(item) for item in missing_facts]
    return any(pattern in item for item in normalized_missing for pattern in patterns)


def _slot_has_context_hint(slot: str, *, normalized_query: str) -> bool:
    return any(re.search(pattern, normalized_query) for pattern in _QUERY_CONTEXT_HINT_PATTERNS.get(slot, ()))


def _question_was_already_asked(question_text: str, asked_questions: list[str]) -> bool:
    normalized_question = _normalize_text(question_text)
    return any(_normalize_text(item) == normalized_question for item in asked_questions)


def _has_meaningful_value(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return normalized not in {"desconocido", "sin dato", "pendiente"}
    return True


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()
