# backend/app/services/case_memory_service.py
"""
FASE 13A — Case Memory

Capa de memoria del caso: consolida hechos, partes, temas y faltantes
por turno, a partir de los datos ya disponibles en api_payload.

Principios de diseño:
- Puras: sin estado interno, sin DB, sin efectos secundarios
- Deterministas: misma entrada → misma salida
- Tolerantes a fallos: cualquier campo faltante produce defaults coherentes
- Backward-compatible: si no se llama, el resto del pipeline no se rompe

Estructura de salida:
{
    "facts": {key: {"value": any, "source": str, "confidence": float}},
    "parties": {"claimant": str | None, "respondent": str | None, "other": []},
    "case_topics": [str],
    "detected_objectives": [str],
    "missing": {
        "critical": [{"key": str, ...}],
        "important": [{"key": str, ...}],
        "optional": [{"key": str, ...}],
    },
    "contradictions": [{"key": str, "prev_value": any, "new_value": any, "detected_at": int}],
    "memory_confidence": "low" | "medium" | "high",
}
"""
from __future__ import annotations

from typing import Any


# ── Patrones para clasificación ────────────────────────────────────────────────

_CRITICAL_KEY_PATTERNS: tuple[str, ...] = (
    "hay_hijos", "vinculo", "rol_procesal", "convivencia",
    "ingresos_otro_progenitor", "domicilio_nnya", "domicilio",
    "notificacion", "nombre", "dni",
)
_OPTIONAL_KEY_PATTERNS: tuple[str, ...] = (
    "distancia", "frecuencia_contacto", "contexto_general",
    "detalle_adicional", "frecuencia", "contexto",
)
_CRITICAL_PRIORITIES: frozenset[str] = frozenset({"critical", "high", "required"})
_OPTIONAL_PRIORITIES: frozenset[str] = frozenset({"optional", "low"})
_BLOCKING_PURPOSES: frozenset[str] = frozenset({"identify", "enable"})

_PARTY_KEYS: dict[str, tuple[str, ...]] = {
    "claimant": ("nombre_actor", "nombre_demandante", "nombre_requirente", "actor"),
    "respondent": ("nombre_demandado", "nombre_requerido", "demandado"),
}

_CATEGORY_RANK: dict[str, int] = {"critical": 3, "important": 2, "optional": 1}


# ── API pública ────────────────────────────────────────────────────────────────


def build_case_memory(
    *,
    case_state_snapshot: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    api_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Construye el case_memory del turno desde los datos ya disponibles en api_payload.

    No accede a DB. Lee case_state_snapshot, conversation_state y otros campos
    de api_payload que ya fueron resueltos por el postprocessor.
    """
    snapshot = dict(case_state_snapshot or {})
    state = dict(conversation_state or {})
    payload = dict(api_payload or {})

    # ── Hechos confirmados y probables ─────────────────────────────────────────
    confirmed_facts = dict(snapshot.get("confirmed_facts") or {})
    probable_facts = dict(snapshot.get("probable_facts") or {})

    facts: dict[str, Any] = {}
    for key, value in probable_facts.items():
        canon = _canonical_key(key)
        if canon:
            facts[canon] = {"value": value, "source": "probable", "confidence": 0.6}
    for key, value in confirmed_facts.items():
        canon = _canonical_key(key)
        if canon:
            facts[canon] = {"value": value, "source": "confirmed", "confidence": 1.0}

    # Completar desde conversation_state.known_facts si no está en snapshot
    for item in list(state.get("known_facts") or []):
        if not isinstance(item, dict):
            continue
        key = _canonical_key(
            str(item.get("key") or item.get("fact_key") or "")
        )
        value = item.get("value")
        if key and key not in facts:
            facts[key] = {
                "value": value,
                "source": str(item.get("source") or "state"),
                "confidence": 0.5,
            }

    # ── Partes del caso ────────────────────────────────────────────────────────
    parties = _extract_parties(facts)

    # ── Temas del caso ─────────────────────────────────────────────────────────
    case_topics = _extract_case_topics(state)

    # ── Objetivos detectados ───────────────────────────────────────────────────
    detected_objectives = _extract_objectives(payload)

    # ── Faltantes clasificados ─────────────────────────────────────────────────
    raw_missing: list[dict[str, Any]] = []
    for item in list(state.get("missing_facts") or []):
        if isinstance(item, dict):
            raw_missing.append(item)
    for need in list(snapshot.get("open_needs") or []):
        if isinstance(need, dict):
            raw_missing.append({
                "key": str(need.get("need_key") or ""),
                "label": str(need.get("reason") or need.get("need_key") or ""),
                "priority": str(need.get("priority") or "normal"),
                "purpose": str(need.get("category") or ""),
                "source": "open_needs",
            })

    missing = classify_missing_fields(raw_missing)

    # Quitar los que ya están en facts (ya se conocen)
    known_keys = set(facts.keys())
    for category in missing:
        missing[category] = [
            item for item in missing[category]
            if _canonical_key(str(
                item.get("key") or item.get("fact_key") or item.get("need_key") or ""
            )) not in known_keys
        ]

    # ── Contradicciones ────────────────────────────────────────────────────────
    contradictions = _extract_contradictions(snapshot)

    # ── Confianza de la memoria ────────────────────────────────────────────────
    memory_confidence = _compute_memory_confidence(facts, missing, contradictions)

    return {
        "facts": facts,
        "parties": parties,
        "case_topics": case_topics,
        "detected_objectives": detected_objectives,
        "missing": missing,
        "contradictions": contradictions,
        "memory_confidence": memory_confidence,
    }


def merge_case_memory(
    *,
    previous_memory: dict[str, Any] | None,
    case_state_snapshot: dict[str, Any] | None,
    conversation_state: dict[str, Any] | None,
    api_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fusiona la memoria del turno anterior con los datos del turno actual.

    Reglas de merge:
    - Hechos: los de mayor confidence prevalecen; los del turno anterior
      que no aparecen en el nuevo se preservan.
    - Missing: acumulación por key; si el mismo key aparece en categorías
      distintas, prevalece la más crítica.
    - Contradicciones: acumulación sin duplicar por key.
    - Objectives/topics: el turno nuevo tiene precedencia, con fallback al anterior.
    """
    prev = dict(previous_memory or {})
    new_memory = build_case_memory(
        case_state_snapshot=case_state_snapshot,
        conversation_state=conversation_state,
        api_payload=api_payload,          # ← preserva objetivos, policy, strategy
    )

    if not prev:
        return new_memory

    # ── Merge facts ────────────────────────────────────────────────────────────
    # Empezar desde los anteriores, sobreescribir si mayor confidence
    merged_facts: dict[str, Any] = dict(prev.get("facts") or {})
    for key, fact_data in (new_memory.get("facts") or {}).items():
        canon = _canonical_key(key)
        if not canon:
            continue
        prev_fact = merged_facts.get(canon) or {}
        new_confidence = float(fact_data.get("confidence") or 0)
        prev_confidence = float(prev_fact.get("confidence") or 0)
        if new_confidence >= prev_confidence:
            merged_facts[canon] = fact_data

    # ── Merge missing (acumulativo) ────────────────────────────────────────────
    # Los keys ya conocidos se quitan de ambas listas antes de mergear
    known_keys = set(merged_facts.keys())
    prev_missing = {
        cat: [
            item for item in items
            if _canonical_key(str(item.get("key") or item.get("fact_key") or "")) not in known_keys
        ]
        for cat, items in (prev.get("missing") or {}).items()
    }
    new_missing = {
        cat: [
            item for item in items
            if _canonical_key(str(item.get("key") or item.get("fact_key") or "")) not in known_keys
        ]
        for cat, items in (new_memory.get("missing") or {}).items()
    }
    merged_missing = _merge_missing(prev_missing, new_missing)

    # ── Merge contradictions (acumulativas, sin duplicar por key) ──────────────
    merged_contradictions = list(prev.get("contradictions") or [])
    existing_keys = {str(c.get("key") or "") for c in merged_contradictions}
    for contradiction in list(new_memory.get("contradictions") or []):
        if str(contradiction.get("key") or "") not in existing_keys:
            merged_contradictions.append(contradiction)

    # Detectar contradicciones nuevas entre turnos
    detected = detect_memory_contradictions(
        previous_facts={k: v.get("value") for k, v in (prev.get("facts") or {}).items()},
        current_facts={k: v.get("value") for k, v in merged_facts.items()},
        turn_count=int((conversation_state or {}).get("turn_count") or 0),
    )
    for c in detected:
        if str(c.get("key") or "") not in {str(x.get("key") or "") for x in merged_contradictions}:
            merged_contradictions.append(c)

    return {
        "facts": merged_facts,
        "parties": new_memory.get("parties") or prev.get("parties") or {"claimant": None, "respondent": None, "other": []},
        "case_topics": new_memory.get("case_topics") or prev.get("case_topics") or [],
        "detected_objectives": new_memory.get("detected_objectives") or prev.get("detected_objectives") or [],
        "missing": merged_missing,
        "contradictions": merged_contradictions,
        "memory_confidence": _compute_memory_confidence(merged_facts, merged_missing, merged_contradictions),
    }


def extract_case_memory_snapshot(
    case_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Devuelve un snapshot reducido del case_memory para ser consumido
    por servicios downstream (composition, language, strategy, etc.).
    """
    mem = dict(case_memory or {})
    facts = dict(mem.get("facts") or {})
    missing = dict(mem.get("missing") or {})
    parties = dict(mem.get("parties") or {})

    confirmed_fact_keys = [
        key for key, v in facts.items()
        if float((v or {}).get("confidence") or 0) >= 0.9
    ]

    return {
        "confirmed_fact_keys": confirmed_fact_keys,
        "confirmed_fact_count": len(confirmed_fact_keys),
        "total_fact_count": len(facts),
        "missing_critical_count": len(list(missing.get("critical") or [])),
        "missing_important_count": len(list(missing.get("important") or [])),
        "missing_optional_count": len(list(missing.get("optional") or [])),
        "memory_confidence": str(mem.get("memory_confidence") or "low"),
        "has_parties": bool(parties.get("claimant") or parties.get("respondent")),
        "case_topics": list(mem.get("case_topics") or []),
        "contradiction_count": len(list(mem.get("contradictions") or [])),
    }


def classify_missing_fields(
    missing_facts: list[dict[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Clasifica una lista de hechos faltantes en critical/important/optional.

    Criterios:
    - critical: priority en {critical, high, required}, o purpose en {identify, enable},
                o key matches _CRITICAL_KEY_PATTERNS
    - optional: priority en {optional, low}, o importance == 'accessory',
                o key matches _OPTIONAL_KEY_PATTERNS
    - important: todo lo demás
    """
    classified: dict[str, list[dict[str, Any]]] = {
        "critical": [],
        "important": [],
        "optional": [],
    }
    seen_keys: set[str] = set()

    for item in list(missing_facts or []):
        if not isinstance(item, dict):
            continue
        raw_key = str(
            item.get("key") or item.get("fact_key") or item.get("need_key") or ""
        ).strip()
        key = _canonical_key(raw_key)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        priority = str(item.get("priority") or "").strip().lower()
        importance = str(item.get("importance") or "").strip().lower()
        purpose = str(item.get("purpose") or item.get("category") or "").strip().lower()

        category = _classify_single_missing(
            key=key,
            priority=priority,
            importance=importance,
            purpose=purpose,
        )
        classified[category].append(item)

    return classified


def detect_memory_contradictions(
    *,
    previous_facts: dict[str, Any] | None,
    current_facts: dict[str, Any] | None,
    turn_count: int = 0,
) -> list[dict[str, Any]]:
    """
    Detecta contradicciones entre hechos del turno anterior y el actual.

    Solo señala contradicción cuando ambos valores son no-falsy y difieren
    de forma no trivial (string comparison normalizada).
    """
    prev = dict(previous_facts or {})
    curr = dict(current_facts or {})
    contradictions: list[dict[str, Any]] = []

    for key in curr:
        if key not in prev:
            continue
        prev_val = prev[key]
        curr_val = curr[key]
        if _values_contradict(prev_val, curr_val):
            contradictions.append({
                "key": key,
                "prev_value": prev_val,
                "new_value": curr_val,
                "detected_at": turn_count,
            })

    return contradictions


# ── Helpers internos ───────────────────────────────────────────────────────────


def _canonical_key(key: str) -> str:
    """
    Normaliza una clave de hecho: minúsculas y sin espacios extremos.
    Evita duplicación semántica por capitalización o whitespace.
    """
    return str(key or "").strip().lower()


def _merge_missing(
    prev: dict[str, list[dict[str, Any]]],
    new: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Fusiona dos dicts de missing (critical/important/optional) acumulando por key.
    Si el mismo key aparece en categorías distintas, prevalece la más crítica.
    """
    # Recolectar todos los items, tracking la categoría más crítica por key
    all_items: dict[str, tuple[str, dict[str, Any]]] = {}

    for source in (prev, new):
        for category in ("critical", "important", "optional"):
            for item in source.get(category) or []:
                key = _canonical_key(str(
                    item.get("key") or item.get("fact_key") or item.get("need_key") or ""
                ))
                if not key:
                    continue
                existing = all_items.get(key)
                if existing is None or _CATEGORY_RANK[category] > _CATEGORY_RANK[existing[0]]:
                    all_items[key] = (category, item)

    result: dict[str, list[dict[str, Any]]] = {"critical": [], "important": [], "optional": []}
    for _key, (category, item) in all_items.items():
        result[category].append(item)
    return result


def _classify_single_missing(
    *, key: str, priority: str, importance: str, purpose: str
) -> str:
    if (
        priority in _CRITICAL_PRIORITIES
        or purpose in _BLOCKING_PURPOSES
        or any(p in key for p in _CRITICAL_KEY_PATTERNS)
    ):
        return "critical"
    if (
        priority in _OPTIONAL_PRIORITIES
        or importance == "accessory"
        or any(p in key for p in _OPTIONAL_KEY_PATTERNS)
    ):
        return "optional"
    return "important"


def _extract_parties(facts: dict[str, Any]) -> dict[str, Any]:
    parties: dict[str, Any] = {"claimant": None, "respondent": None, "other": []}
    for role, patterns in _PARTY_KEYS.items():
        for pattern in patterns:
            canon = _canonical_key(pattern)
            if canon in facts:
                val = facts[canon]
                if isinstance(val, dict):
                    val = val.get("value")
                if val:
                    parties[role] = str(val)
                    break
    return parties


def _extract_case_topics(state: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    case_type = str(state.get("working_case_type") or "").strip()
    domain = str(state.get("working_domain") or "").strip()
    if case_type:
        topics.append(case_type)
    if domain and domain != case_type:
        topics.append(domain)
    return [t for t in topics if t]


def _extract_objectives(payload: dict[str, Any]) -> list[str]:
    objectives: list[str] = []
    policy = dict(payload.get("dialogue_policy") or {})
    purpose = str(policy.get("dominant_missing_purpose") or "").strip()
    if purpose:
        objectives.append(purpose)
    smart = dict(payload.get("smart_strategy") or {})
    action_bias = str(smart.get("action_bias") or "").strip()
    if action_bias and action_bias not in objectives:
        objectives.append(action_bias)
    return [o for o in objectives if o]


def _extract_contradictions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(snapshot.get("contradictions") or []):
        if isinstance(item, dict):
            result.append(item)
    return result


def _compute_memory_confidence(
    facts: dict[str, Any],
    missing: dict[str, Any],
    contradictions: list[dict[str, Any]] | None = None,
) -> str:
    confirmed_count = sum(
        1 for v in facts.values()
        if float((v or {}).get("confidence") or 0) >= 0.9
    )
    critical_missing_count = len(list(missing.get("critical") or []))
    contradiction_count = len(list(contradictions or []))

    # Contradicciones degradan la confianza
    if contradiction_count >= 2:
        if confirmed_count >= 5 and critical_missing_count == 0:
            return "medium"  # degradado de high por contradicciones
        return "low"

    if confirmed_count >= 5 and critical_missing_count == 0:
        return "high"
    if confirmed_count >= 2 or critical_missing_count <= 2:
        return "medium"
    return "low"


def _values_contradict(prev: Any, curr: Any) -> bool:
    """
    ¿Dos valores se contradicen? Solo si ambos son no-falsy y difieren.
    """
    if prev is None or curr is None:
        return False
    prev_str = str(prev).strip().lower()
    curr_str = str(curr).strip().lower()
    if not prev_str or not curr_str:
        return False
    return prev_str != curr_str
