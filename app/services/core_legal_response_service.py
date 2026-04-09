from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


MAX_ACTION_STEPS = 3
MAX_REQUIRED_DOCUMENTS = 4
MAX_LOCAL_NOTES = 3
MAX_PROFESSIONAL_CHECKLIST = 5

_ACTION_STARTERS = (
    "preparar",
    "presentar",
    "reunir",
    "redactar",
    "ordenar",
    "incluir",
    "verificar",
    "impulsar",
    "solicitar",
    "acreditar",
    "definir",
    "promover",
    "iniciar",
    "acompanar",
)

_DOCUMENT_PATTERNS = (
    "dni",
    "partida",
    "libreta",
    "acta",
    "documentacion",
    "documental",
    "documento",
    "escritura",
    "boleto",
    "contrato",
    "recibo",
    "comprobante",
    "certificado",
    "titulo",
)


def attach_core_legal_response(response: dict[str, Any] | None) -> dict[str, Any]:
    payload = deepcopy(response or {})
    payload["core_legal_response"] = build_core_legal_response(payload)
    return payload


def build_core_legal_response(response: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(response or {})
    case_domain = _clean_text(payload.get("case_domain"))
    jurisdiction = _clean_text(payload.get("jurisdiction") or "jujuy")
    reasoning = _as_dict(payload.get("reasoning"))
    case_strategy = _as_dict(payload.get("case_strategy"))
    procedural_strategy = _as_dict(payload.get("procedural_strategy"))
    normative_reasoning = _as_dict(payload.get("normative_reasoning"))
    case_profile = _as_dict(payload.get("case_profile"))
    model_match = _as_dict(payload.get("model_match"))

    direct_answer = _build_direct_answer(
        payload=payload,
        reasoning=reasoning,
        case_strategy=case_strategy,
    )
    action_steps = _build_action_steps(
        payload=payload,
        case_strategy=case_strategy,
        procedural_strategy=procedural_strategy,
    )
    required_documents = _build_required_documents(
        payload=payload,
        case_strategy=case_strategy,
        procedural_strategy=procedural_strategy,
        case_profile=case_profile,
    )
    local_practice_notes = _build_local_practice_notes(
        jurisdiction=jurisdiction,
        case_domain=case_domain,
        normative_reasoning=normative_reasoning,
        procedural_strategy=procedural_strategy,
    )
    professional_frame = _build_professional_frame(
        case_domain=case_domain,
        case_strategy=case_strategy,
        procedural_strategy=procedural_strategy,
        case_profile=case_profile,
        model_match=model_match,
        required_documents=required_documents,
    )
    optional_clarification = _build_optional_clarification(payload)

    return {
        "direct_answer": direct_answer,
        "action_steps": action_steps,
        "required_documents": required_documents,
        "local_practice_notes": local_practice_notes,
        "professional_frame": professional_frame,
        "optional_clarification": optional_clarification,
    }


def _build_direct_answer(
    *,
    payload: dict[str, Any],
    reasoning: dict[str, Any],
    case_strategy: dict[str, Any],
) -> str:
    base = _first_nonempty_text(
        reasoning.get("short_answer"),
        case_strategy.get("strategic_narrative"),
        payload.get("response_text"),
    )
    base = _first_sentences(_to_user_text(base), limit=2)
    if base:
        return base

    case_domain = _clean_text(payload.get("case_domain"))
    if case_domain:
        return f"La consulta se puede orientar como {case_domain.replace('_', ' ')} con la informacion disponible."
    return "La consulta ya permite una orientacion juridica inicial con utilidad practica."


def _build_action_steps(
    *,
    payload: dict[str, Any],
    case_strategy: dict[str, Any],
    procedural_strategy: dict[str, Any],
) -> list[str]:
    quick_start = _strip_known_prefix(
        _clean_text(payload.get("quick_start")),
        "Primer paso recomendado:",
    )
    candidates = _dedupe_texts([
        quick_start,
        *_as_str_list(case_strategy.get("recommended_actions")),
        *_as_str_list(procedural_strategy.get("next_steps")),
        *_as_str_list(case_strategy.get("procedural_focus")),
    ])
    actions = [
        _to_user_text(item)
        for item in candidates
        if _looks_like_action(item)
    ]
    return _dedupe_texts(actions)[:MAX_ACTION_STEPS]


def _build_required_documents(
    *,
    payload: dict[str, Any],
    case_strategy: dict[str, Any],
    procedural_strategy: dict[str, Any],
    case_profile: dict[str, Any],
) -> list[str]:
    sources = [
        *_as_str_list(procedural_strategy.get("missing_information") or procedural_strategy.get("missing_info")),
        *_as_str_list(case_strategy.get("ordinary_missing_information")),
        *_as_str_list(case_strategy.get("critical_missing_information")),
        *_as_str_list(case_profile.get("missing_information")),
        *_as_str_list(payload.get("warnings")),
        *_as_str_list(_as_dict(payload.get("conflict_evidence")).get("missing_evidence")),
        *_as_str_list(_as_dict(payload.get("case_theory")).get("evidence_needed")),
    ]
    docs = []
    for item in sources:
        if _looks_document_related(item):
            docs.append(_normalize_document_item(item))
    if not docs:
        case_domain = _clean_text(payload.get("case_domain")).casefold()
        if case_domain == "divorcio":
            docs.extend([
                "DNI y acta o libreta de matrimonio.",
                "Datos de domicilio de ambas partes.",
            ])
        elif case_domain == "sucesion":
            docs.extend([
                "Partida de defuncion del causante.",
                "Partidas o documentos que acrediten parentesco.",
            ])
    return _dedupe_texts(docs)[:MAX_REQUIRED_DOCUMENTS]


def _build_local_practice_notes(
    *,
    jurisdiction: str,
    case_domain: str,
    normative_reasoning: dict[str, Any],
    procedural_strategy: dict[str, Any],
) -> list[str]:
    normalized_jurisdiction = jurisdiction.casefold()
    notes: list[str] = []
    if normalized_jurisdiction == "jujuy":
        if case_domain.casefold() == "divorcio":
            notes.append(
                "En Jujuy, suele convenir definir desde el inicio si la presentacion sera conjunta o unilateral y no dejar floja la propuesta reguladora."
            )
            notes.append(
                "Si hay hijos, en la practica conviene ordenar desde el arranque cuidado personal, comunicacion y alimentos."
            )
        elif case_domain.casefold() == "alimentos":
            notes.append(
                "En Jujuy, suele ayudar que el reclamo ya llegue con una base concreta sobre convivencia, necesidades e ingresos o posibilidades de acreditarlos."
            )
        elif case_domain.casefold() == "sucesion":
            notes.append(
                "En la practica local, la apertura mejora mucho cuando ya esta ordenada la documentacion basica de fallecimiento, parentesco y primeros bienes."
            )
        else:
            notes.append(
                "En Jujuy, suele ser importante ubicar temprano el fuero, la competencia territorial y la documentacion basica para evitar observaciones evitables."
            )

    for item in _as_str_list(normative_reasoning.get("key_points")):
        if any(token in _normalize_text(item) for token in ("jujuy", "juzgado", "competencia", "presentacion", "propuesta reguladora")):
            notes.append(_to_user_text(item))
    for item in _as_str_list(procedural_strategy.get("risks")):
        if any(token in _normalize_text(item) for token in ("observacion", "competencia", "presentacion", "documentacion")):
            notes.append(_to_user_text(item))
    return _dedupe_texts(notes)[:MAX_LOCAL_NOTES]


def _build_professional_frame(
    *,
    case_domain: str,
    case_strategy: dict[str, Any],
    procedural_strategy: dict[str, Any],
    case_profile: dict[str, Any],
    model_match: dict[str, Any],
    required_documents: list[str],
) -> dict[str, Any]:
    return {
        "case_domain": case_domain,
        "strategy": _first_nonempty_text(
            case_strategy.get("strategic_narrative"),
            procedural_strategy.get("summary"),
        ),
        "checklist": _dedupe_texts([
            *_as_str_list(case_strategy.get("procedural_focus")),
            *_as_str_list(case_strategy.get("recommended_actions")),
            *required_documents,
        ])[:MAX_PROFESSIONAL_CHECKLIST],
        "drafting_points": _dedupe_texts([
            *_as_str_list(case_profile.get("strategic_focus")),
            *_as_str_list(case_strategy.get("conflict_summary")),
        ])[:4],
        "model_hint": _clean_text(
            model_match.get("selected_model_name")
            or _as_dict(model_match.get("selected_model")).get("name")
            or model_match.get("selected_model_id")
        ),
    }


def _build_optional_clarification(payload: dict[str, Any]) -> str | None:
    conversational = _as_dict(payload.get("conversational"))
    question = _clean_text(conversational.get("question"))
    if question:
        return _ensure_question(question)

    question_engine_result = _as_dict(payload.get("question_engine_result"))
    questions = question_engine_result.get("questions")
    if isinstance(questions, list):
        for item in questions:
            if isinstance(item, dict):
                question = _clean_text(item.get("question"))
            else:
                question = _clean_text(item)
            if question:
                return _ensure_question(question)
    return None


def _normalize_document_item(text: str) -> str:
    cleaned = _to_user_text(text).rstrip(".")
    if not cleaned:
        return ""
    if not any(token in _normalize_text(cleaned) for token in _DOCUMENT_PATTERNS):
        return ""
    if cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _ensure_question(text: str) -> str:
    cleaned = _to_user_text(text).rstrip(".:;")
    if not cleaned:
        return ""
    if cleaned.endswith("?"):
        return cleaned if cleaned.startswith("¿") else f"¿{cleaned}"
    return f"¿{cleaned[0].upper()}{cleaned[1:]}?"


def _looks_like_action(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if "?" in text or "¿" in text:
        return False
    if normalized.startswith(("hay ", "existen ", "si hay ", "tienen ", "necesito ", "pregunta ", "dato ")):
        return False
    return normalized.startswith(_ACTION_STARTERS)


def _looks_document_related(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(token in normalized for token in _DOCUMENT_PATTERNS)


def _first_sentences(text: str, *, limit: int) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    return " ".join(parts[:limit]).strip()


def _strip_known_prefix(text: str, prefix: str) -> str:
    value = _clean_text(text)
    if value.casefold().startswith(prefix.casefold()):
        return value[len(prefix):].strip()
    return value


def _to_user_text(text: str) -> str:
    result = _clean_text(text)
    result = re.sub(r"\bcompetencia\b", "que juzgado corresponde", result, flags=re.IGNORECASE)
    result = re.sub(r"\bvia procesal\b", "como conviene iniciar el tramite", result, flags=re.IGNORECASE)
    result = re.sub(r"\bpropuesta reguladora\b", "propuesta reguladora", result, flags=re.IGNORECASE)
    return result


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = _clean_text(item)
        key = _normalize_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _first_nonempty_text(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).strip()


def _normalize_text(value: Any) -> str:
    return _clean_text(value).casefold()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]
