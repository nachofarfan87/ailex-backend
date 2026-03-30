from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any


_AMBIGUOUS_SHORT_ANSWERS = {
    "si",
    "sí",
    "no",
    "puede ser",
    "tal vez",
    "quizas",
    "quizás",
    "no se",
    "no sé",
}

_DIVORCE_UNILATERAL_PATTERNS = (
    r"\bunilateral(?:mente)?\b",
    r"\bsin acuerdo\b",
    r"\bno hay acuerdo\b",
    r"\bno esta de acuerdo\b",
    r"\bno está de acuerdo\b",
)
_DIVORCE_JOINT_PATTERNS = (
    r"\bconjunto(?:s|amente)?\b",
    r"\bcomun acuerdo\b",
    r"\bcomún acuerdo\b",
    r"\bmutuo acuerdo\b",
    r"\bde acuerdo\b",
)
_YES_PATTERNS = (r"\bsi\b", r"\bsí\b", r"\bclaro\b", r"\bcorrecto\b", r"\bexacto\b")
_NO_PATTERNS = (r"\bno\b", r"\bpara nada\b")
_CHILD_REFERENCE_PATTERNS = (
    r"\bhij[oa]s?\b",
    r"\bhija\b",
    r"\bhijo\b",
    r"\bmi hija\b",
    r"\bmi hijo\b",
    r"\bmis hijas\b",
    r"\bmis hijos\b",
    r"\bmenor(?:es)?\b",
    r"\bbebe\b",
    r"\bnen[ae]\b",
)
_CHILD_AGE_PATTERNS = (
    r"\b\d{1,2}\s*(anos|aÃ±os|meses|dias)\b",
)


@dataclass
class ClarificationPreparation:
    effective_query: str
    merged_facts: dict[str, Any]
    metadata: dict[str, Any]


def prepare_legal_query_turn(
    *,
    query: str,
    facts: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> ClarificationPreparation:
    normalized_query = _clean_text(query) or "consulta juridica"
    normalized_facts = _merge_dicts({}, facts or {})
    normalized_metadata = deepcopy(metadata or {})
    clarification_context = _as_dict(normalized_metadata.get("clarification_context"))

    if not clarification_context:
        return ClarificationPreparation(
            effective_query=normalized_query,
            merged_facts=normalized_facts,
            metadata=normalized_metadata,
        )

    base_query = _clean_text(clarification_context.get("base_query")) or normalized_query
    last_question = _clean_text(clarification_context.get("last_question"))
    case_domain = _clean_text(clarification_context.get("case_domain")).casefold()
    known_facts = _merge_dicts(
        {},
        clarification_context.get("known_facts") if isinstance(clarification_context.get("known_facts"), dict) else {},
    )
    known_facts = _merge_dicts(known_facts, normalized_facts)

    extraction = _extract_clarification_answer(
        answer=normalized_query,
        case_domain=case_domain,
        last_question=last_question,
        known_facts=known_facts,
    )
    merged_facts = _merge_dicts(known_facts, extraction["facts"])
    asked_questions = _dedupe_strings([
        *_as_str_list(clarification_context.get("asked_questions")),
        last_question,
    ])
    clarified_fields = _dedupe_strings([
        *_as_str_list(clarification_context.get("clarified_fields")),
        *[str(item).strip() for item in extraction["clarified_fields"] if str(item).strip()],
    ])

    updated_context = {
        "base_query": base_query,
        "case_domain": case_domain or _clean_text(clarification_context.get("case_domain")),
        "last_question": last_question,
        "asked_questions": asked_questions,
        "known_facts": merged_facts,
        "clarified_fields": clarified_fields,
        "last_user_answer": normalized_query,
        "answer_status": extraction["answer_status"],
        "precision_required": extraction["precision_required"],
        "precision_prompt": extraction["precision_prompt"],
    }
    normalized_metadata["clarification_context"] = updated_context

    return ClarificationPreparation(
        effective_query=_compose_effective_query(
            base_query=base_query,
            answer=normalized_query,
            merged_facts=merged_facts,
            precision_required=bool(extraction["precision_required"]),
        ),
        merged_facts=merged_facts,
        metadata=normalized_metadata,
    )


def _extract_clarification_answer(
    *,
    answer: str,
    case_domain: str,
    last_question: str,
    known_facts: dict[str, Any],
) -> dict[str, Any]:
    normalized_answer = _normalize_text(answer)
    normalized_question = _normalize_text(last_question)
    extracted_facts: dict[str, Any] = {}
    clarified_fields: list[str] = []
    precision_required = False
    precision_prompt = ""

    if normalized_answer in _AMBIGUOUS_SHORT_ANSWERS and _question_needs_disambiguation(normalized_question):
        precision_required = True
        precision_prompt = _build_precision_prompt(last_question)
        return {
            "facts": {},
            "clarified_fields": [],
            "answer_status": "ambiguous",
            "precision_required": True,
            "precision_prompt": precision_prompt,
        }

    if case_domain == "divorcio":
        if _matches_any(normalized_answer, _DIVORCE_UNILATERAL_PATTERNS):
            extracted_facts["divorcio_modalidad"] = "unilateral"
            extracted_facts["hay_acuerdo"] = False
            clarified_fields.extend(["divorcio_modalidad", "hay_acuerdo"])
        elif _matches_any(normalized_answer, _DIVORCE_JOINT_PATTERNS):
            extracted_facts["divorcio_modalidad"] = "conjunto"
            extracted_facts["hay_acuerdo"] = True
            clarified_fields.extend(["divorcio_modalidad", "hay_acuerdo"])

    if _question_mentions_children(normalized_question) or _answer_mentions_children(normalized_answer):
        child_value = _extract_boolean_flag(
            normalized_answer,
            positive_hint="hijos|hijas|hija|hijo|mi hija|mi hijo|mis hijas|mis hijos|bebe|nena|nene|menor|menores",
            negative_hint="sin hijos|sin hijas|no hay hijos|no hay hijas|no tenemos hijos|no tenemos hijas|no hay menores",
        )
        if child_value is not None:
            extracted_facts["hay_hijos"] = child_value
            clarified_fields.append("hay_hijos")
        if child_value is True and _answer_mentions_children_age(normalized_answer):
            extracted_facts["hay_hijos_edad"] = "informada"
            clarified_fields.append("hay_hijos_edad")

    if _question_mentions_agreement(normalized_question) and "divorcio_modalidad" not in extracted_facts:
        agreement = _extract_yes_no(normalized_answer)
        if agreement is not None:
            extracted_facts["hay_acuerdo"] = agreement
            clarified_fields.append("hay_acuerdo")

    if "bienes" in normalized_answer or "vivienda" in normalized_answer or "patrimonial" in normalized_answer:
        bienes = _extract_boolean_flag(normalized_answer, positive_hint="bienes|vivienda|departamento|casa", negative_hint="sin bienes|no hay bienes")
        if bienes is not None:
            extracted_facts["hay_bienes"] = bienes
            clarified_fields.append("hay_bienes")
        if "vivienda" in normalized_answer or "casa" in normalized_answer:
            extracted_facts["vivienda_familiar"] = True
            clarified_fields.append("vivienda_familiar")

    if "urgencia" in normalized_question or "urgencia" in normalized_answer:
        urgency = _extract_yes_no(normalized_answer)
        if urgency is not None:
            extracted_facts["urgencia"] = urgency
            clarified_fields.append("urgencia")

    if case_domain == "alimentos" or "alimentos" in normalized_question:
        if re.search(r"\bsoy (el )?demandad[oa]\b|\bme demandan\b|\bme reclam[ae]n? alimentos\b", normalized_answer):
            extracted_facts["rol_procesal"] = "demandado"
            clarified_fields.append("rol_procesal")
        elif re.search(r"\bsoy (el )?actor\b|\bquiero reclamar\b|\bvoy a demandar\b|\biniciar(?:e|é)? reclamo\b", normalized_answer):
            extracted_facts["rol_procesal"] = "actor"
            clarified_fields.append("rol_procesal")

    if "cese de convivencia" in normalized_question or "convivencia" in normalized_answer:
        cese_convivencia = _extract_boolean_flag(normalized_answer, positive_hint="ya no convivimos|separados|cese de convivencia", negative_hint="seguimos conviviendo")
        if cese_convivencia is not None:
            extracted_facts["cese_convivencia"] = cese_convivencia
            clarified_fields.append("cese_convivencia")

    if normalized_answer in _AMBIGUOUS_SHORT_ANSWERS and not clarified_fields:
        precision_required = True
        precision_prompt = "Necesito que lo aclares con un poco mas de precision para no orientarte sobre una base ambigua."

    answer_status = "precise" if clarified_fields else "ambiguous" if precision_required else "unknown"
    if extracted_facts == known_facts:
        answer_status = "unknown"
    return {
        "facts": extracted_facts,
        "clarified_fields": _dedupe_strings(clarified_fields),
        "answer_status": answer_status,
        "precision_required": precision_required,
        "precision_prompt": precision_prompt,
    }


def _compose_effective_query(
    *,
    base_query: str,
    answer: str,
    merged_facts: dict[str, Any],
    precision_required: bool,
) -> str:
    if precision_required:
        return base_query

    clarification_bits = _facts_to_query_clauses(merged_facts)
    if clarification_bits:
        return f"{base_query}. Aclaraciones del usuario: {'; '.join(clarification_bits)}."
    if len(answer.split()) >= 4:
        return f"{base_query}. Aclaracion del usuario: {answer}."
    return base_query


def _facts_to_query_clauses(facts: dict[str, Any]) -> list[str]:
    clauses: list[str] = []
    modalidad = _clean_text(facts.get("divorcio_modalidad"))
    if modalidad:
        clauses.append(f"divorcio {modalidad}")
    if "hay_hijos" in facts:
        clauses.append("hay hijos" if bool(facts.get("hay_hijos")) else "no hay hijos")
    if "hay_acuerdo" in facts:
        clauses.append("hay acuerdo" if bool(facts.get("hay_acuerdo")) else "no hay acuerdo")
    if "rol_procesal" in facts:
        clauses.append(f"rol procesal {facts.get('rol_procesal')}")
    if "urgencia" in facts and bool(facts.get("urgencia")):
        clauses.append("hay urgencia")
    if "hay_bienes" in facts:
        clauses.append("hay bienes" if bool(facts.get("hay_bienes")) else "no hay bienes")
    return _dedupe_strings(clauses)


def _question_needs_disambiguation(question: str) -> bool:
    if not question:
        return False
    return any(
        token in question
        for token in (
            " o ",
            "unilateral",
            "conjunto",
            "actor",
            "demandado",
        )
    )


def _question_mentions_children(question: str) -> bool:
    return "hijos" in question or "menor" in question


def _answer_mentions_children(answer: str) -> bool:
    return any(re.search(pattern, answer) for pattern in _CHILD_REFERENCE_PATTERNS)


def _answer_mentions_children_age(answer: str) -> bool:
    return any(re.search(pattern, answer) for pattern in _CHILD_AGE_PATTERNS)


def _question_mentions_agreement(question: str) -> bool:
    return "acuerdo" in question and "unilateral" not in question


def _build_precision_prompt(last_question: str) -> str:
    question = _clean_text(last_question)
    if question:
        return f"Necesito que me lo aclares mejor. Responde de forma concreta a esta pregunta: {question}"
    return "Necesito que me lo aclares mejor con una respuesta mas concreta."


def _extract_yes_no(text: str) -> bool | None:
    if _matches_any(text, _YES_PATTERNS):
        return True
    if _matches_any(text, _NO_PATTERNS):
        return False
    return None


def _extract_boolean_flag(text: str, *, positive_hint: str, negative_hint: str) -> bool | None:
    if re.search(negative_hint, text):
        return False
    if re.search(positive_hint, text):
        return True
    return _extract_yes_no(text)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _merge_dicts(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
            continue
        result[key] = value
    return result


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _normalize_text(value: Any) -> str:
    return _clean_text(value).lower()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(_clean_text(item))
    return result
