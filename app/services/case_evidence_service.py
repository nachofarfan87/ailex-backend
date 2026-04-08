from __future__ import annotations

import re
from typing import Any

from app.services.conversation_integrity_service import canonicalize_concept_key


def build_case_evidence_checklist(
    *,
    api_payload: dict[str, Any] | None,
    action_plan: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    payload = dict(api_payload or {})
    context = _build_case_context(payload)
    buckets: dict[str, list[dict[str, Any]]] = {
        "critical": [],
        "recommended": [],
        "optional": [],
    }

    for item in _from_evidence_reasoning_links(payload):
        _add_item(buckets, item, context=context)
    for item in _from_execution_output_documents(payload):
        _add_item(buckets, item, context=context)
    for item in _from_conflict_evidence(payload):
        _add_item(buckets, item, context=context)
    for item in _from_case_theory(payload):
        _add_item(buckets, item, context=context)
    for item in _from_missing_fact_signals(payload):
        _add_item(buckets, item, context=context)

    checklist = {
        "critical": _sort_bucket(buckets["critical"]),
        "recommended": _sort_bucket(buckets["recommended"]),
        "optional": _sort_bucket(buckets["optional"]),
    }
    return _link_items_to_steps(checklist, action_plan=action_plan)


def _from_evidence_reasoning_links(payload: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = dict(payload.get("evidence_reasoning_links") or {})
    items: list[dict[str, Any]] = []

    for gap in _clean_list(evidence.get("critical_evidentiary_gaps")):
        items.append(
            _build_item(
                key_source=gap,
                label=gap,
                description="Elemento probatorio hoy sensible para sostener el caso con prudencia.",
                reason="El propio analisis probatorio lo marca como gap critico.",
                missing_level="critical",
                evidence_role="gap_unlock",
                resolves=[],
            )
        )

    for raw_link in list(evidence.get("requirement_links") or []):
        link = dict(raw_link or {})
        requirement = str(link.get("requirement") or "").strip()
        support_level = str(link.get("support_level") or "").strip().lower()
        strategic_note = str(link.get("strategic_note") or "").strip()
        for missing in _clean_list(link.get("evidence_missing")):
            missing_level = "critical" if support_level == "bajo" else "recommended"
            evidence_role = "gap_unlock" if support_level == "bajo" else _infer_evidence_role(missing)
            items.append(
                _build_item(
                    key_source=f"{requirement}::{missing}",
                    label=missing,
                    description=(
                        f"Prueba faltante vinculada a: {requirement}"
                        if requirement
                        else "Prueba faltante vinculada a un requisito del caso."
                    ),
                    reason=strategic_note or "Ayuda a cubrir un requisito que hoy no esta suficientemente respaldado.",
                    missing_level=missing_level,
                    evidence_role=evidence_role,
                    resolves=[_build_key(requirement)] if requirement else [],
                )
            )

    return items


def _from_execution_output_documents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    execution_output = dict(payload.get("execution_output") or {})
    execution_data = dict(execution_output.get("execution_output") or {})
    case_progress = dict(payload.get("case_progress") or {})
    has_critical_gaps = bool(list(case_progress.get("critical_gaps") or []))

    items: list[dict[str, Any]] = []
    for document in _clean_list(execution_data.get("documents_needed")):
        role = "gap_unlock" if has_critical_gaps else _infer_evidence_role(document)
        items.append(
            _build_item(
                key_source=document,
                label=document,
                description="Documento o respaldo mencionado por la salida operativa del caso.",
                reason="Conviene tenerlo preparado antes de ejecutar el siguiente paso.",
                missing_level="critical" if has_critical_gaps else "recommended",
                evidence_role=role,
                resolves=[_build_key(item.get("key")) for item in list(case_progress.get("critical_gaps") or []) if isinstance(item, dict) and str(item.get("key") or "").strip()] if has_critical_gaps else [],
            )
        )
    return items


def _from_conflict_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    conflict_evidence = dict(payload.get("conflict_evidence") or {})
    items: list[dict[str, Any]] = []
    for text in _clean_list(conflict_evidence.get("key_evidence_missing")):
        items.append(
            _build_item(
                key_source=text,
                label=text,
                description="Prueba faltante detectada en el analisis de conflicto y cobertura.",
                reason="Puede fortalecer el punto mas vulnerable del caso.",
                missing_level="recommended",
                evidence_role="corroboration",
                resolves=[],
            )
        )
    return items


def _from_case_theory(payload: dict[str, Any]) -> list[dict[str, Any]]:
    case_theory = dict(payload.get("case_theory") or {})
    items: list[dict[str, Any]] = []
    for text in _clean_list(case_theory.get("evidentiary_needs")):
        items.append(
            _build_item(
                key_source=text,
                label=text,
                description="Necesidad probatoria detectada por la teoria del caso.",
                reason="Sirve para sostener la narrativa juridica con mejor base.",
                missing_level="recommended",
                evidence_role="corroboration",
                resolves=[],
            )
        )
    return items


def _from_missing_fact_signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    case_memory = dict(payload.get("case_memory") or {})
    conversation_state = dict(payload.get("conversation_state") or {})
    missing_groups = dict(case_memory.get("missing") or {})
    conversation_missing = list(conversation_state.get("missing_facts") or [])

    items: list[dict[str, Any]] = []

    for category in ("critical", "important", "optional"):
        for raw_item in list(missing_groups.get(category) or []):
            item = dict(raw_item or {})
            purpose = str(item.get("purpose") or item.get("category") or "").strip().lower()
            key_or_label = str(item.get("key") or item.get("label") or "")
            if purpose != "prove" and not _looks_like_evidence(key_or_label):
                continue
            label = str(item.get("label") or item.get("key") or "").strip()
            if not label:
                continue
            role = "gap_unlock" if category == "critical" else _infer_evidence_role(label)
            items.append(
                _build_item(
                    key_source=label,
                    label=label,
                    description="Elemento de respaldo inferido desde un faltante del caso.",
                    reason="Todavia falta cobertura documental o probatoria sobre ese punto.",
                    missing_level=(
                        "critical"
                        if category == "critical"
                        else "recommended"
                        if category == "important"
                        else "optional"
                    ),
                    evidence_role=role,
                    resolves=[_build_key(item.get("key") or item.get("label"))],
                )
            )

    for raw_item in conversation_missing:
        item = dict(raw_item or {})
        key = str(item.get("key") or item.get("label") or "").strip()
        purpose = str(item.get("purpose") or "").strip().lower()
        if not key or (purpose != "prove" and not _looks_like_evidence(key)):
            continue
        importance = str(item.get("importance") or "").strip().lower()
        items.append(
            _build_item(
                key_source=key,
                label=item.get("label") or key,
                description="Dato o soporte que conviene reunir para completar la base del caso.",
                reason="Aparece como faltante en el estado conversacional actual.",
                missing_level="critical" if importance == "core" else "recommended",
                evidence_role="gap_unlock" if importance == "core" else _infer_evidence_role(key),
                resolves=[_build_key(key)],
            )
        )

    return items


def _add_item(
    buckets: dict[str, list[dict[str, Any]]],
    item: dict[str, Any],
    *,
    context: dict[str, Any],
) -> None:
    missing_level = str(item.get("missing_level") or "recommended").strip().lower()
    if missing_level not in {"critical", "recommended", "optional"}:
        missing_level = "recommended"
    item["missing_level"] = missing_level
    key = str(item.get("key") or "").strip()
    if not key:
        return
    if _item_is_inapplicable(item, context=context):
        return

    group_key = _semantic_group_key(item)
    existing_level = _find_existing_level(buckets, key, group_key=group_key)
    if existing_level is None:
        buckets[missing_level].append(item)
        return

    existing_index = next(
        (
            index
            for index, existing in enumerate(buckets[existing_level])
            if str(existing.get("key") or "") == key
            or (group_key and _semantic_group_key(existing) == group_key)
        ),
        None,
    )
    if existing_index is None:
        buckets[missing_level].append(item)
        return

    existing_item = buckets[existing_level][existing_index]
    merged_item = _merge_items(existing_item, item)
    merged_level = str(merged_item.get("missing_level") or existing_level).strip().lower()
    buckets[existing_level].pop(existing_index)
    buckets[merged_level].append(merged_item)


def _find_existing_level(
    buckets: dict[str, list[dict[str, Any]]],
    key: str,
    *,
    group_key: str = "",
) -> str | None:
    for level in ("critical", "recommended", "optional"):
        if any(
            str(item.get("key") or "") == key
            or (group_key and _semantic_group_key(item) == group_key)
            for item in buckets[level]
        ):
            return level
    return None


def _level_rank(level: str) -> int:
    if level == "critical":
        return 0
    if level == "recommended":
        return 1
    return 2


def _build_item(
    *,
    key_source: Any,
    label: Any,
    description: str,
    reason: str,
    missing_level: str,
    evidence_role: str,
    resolves: list[str],
) -> dict[str, Any]:
    role = evidence_role or _infer_evidence_role(str(label or key_source or ""))
    return {
        "key": _build_key(key_source),
        "label": _to_label(label),
        "description": description,
        "reason": reason,
        "missing_level": missing_level,
        "priority_rank": _priority_rank_for_role(role),
        "evidence_role": role,
        "why_it_matters": _why_it_matters_for_role(role),
        "resolves": [item for item in resolves if item],
        "supports_step": "",
    }


def _infer_evidence_role(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if any(token in normalized for token in ("dni", "partida", "domicilio", "constancia", "certificado")):
        return "structural_document"
    if any(token in normalized for token in ("recibo", "comprobante", "extracto", "factura", "gasto", "ingreso")):
        return "corroboration"
    if any(token in normalized for token in ("captura", "mensaje", "chat", "audio", "testigo", "pericia")):
        return "corroboration"
    return "complementary"


def _priority_rank_for_role(role: str) -> int:
    ranks = {
        "gap_unlock": 1,
        "structural_document": 2,
        "corroboration": 3,
        "complementary": 4,
    }
    return ranks.get(str(role or "").strip().lower(), 4)


def _why_it_matters_for_role(role: str) -> str:
    messages = {
        "gap_unlock": "Para avanzar con seguridad, esto puede destrabar un faltante que hoy frena la orientacion o el movimiento del caso.",
        "structural_document": "Con lo que ya esta definido, esto fija la base minima del caso y evita pasos sin sustento formal.",
        "corroboration": "Con lo que ya esta definido, esto refuerza un punto relevante del caso con mejor respaldo.",
        "complementary": "Aporta contexto o refuerzo, pero por si solo no suele cambiar el rumbo del caso.",
    }
    return messages.get(str(role or "").strip().lower(), "Aporta respaldo util para entender mejor el caso.")


def _link_items_to_steps(
    checklist: dict[str, list[dict[str, Any]]],
    *,
    action_plan: list[dict[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]]:
    steps = [dict(step) for step in list(action_plan or []) if isinstance(step, dict)]
    if not steps:
        return checklist

    primary_step = next((step for step in steps if bool(step.get("is_primary"))), None)
    proof_steps = [
        step for step in steps if str(step.get("phase") or "").strip().lower() in {"prove", "prepare", "file"}
    ]
    fallback_step = proof_steps[0] if proof_steps else primary_step

    for bucket_name in ("critical", "recommended", "optional"):
        for item in checklist.get(bucket_name, []):
            role = str(item.get("evidence_role") or "").strip().lower()
            resolves = list(item.get("resolves") or [])
            if primary_step and (role == "gap_unlock" or resolves):
                item["supports_step"] = str(primary_step.get("step_id") or primary_step.get("id") or "")
            elif fallback_step and role in {"structural_document", "corroboration"}:
                item["supports_step"] = str(fallback_step.get("step_id") or fallback_step.get("id") or "")
    return checklist


def _item_score(item: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _level_rank(str(item.get("missing_level") or "")),
        int(item.get("priority_rank") or 0) or 99,
        str(item.get("label") or "").strip().casefold(),
    )


def _merge_items(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    better, other = (left, right) if _item_score(left) <= _item_score(right) else (right, left)
    merged = dict(better)
    merged["missing_level"] = (
        str(left.get("missing_level") or "").strip().lower()
        if _level_rank(str(left.get("missing_level") or "").strip().lower())
        <= _level_rank(str(right.get("missing_level") or "").strip().lower())
        else str(right.get("missing_level") or "").strip().lower()
    )
    merged["resolves"] = sorted(
        {
            str(item).strip()
            for item in list(left.get("resolves") or []) + list(right.get("resolves") or [])
            if str(item).strip()
        }
    )
    merged["supports_step"] = str(merged.get("supports_step") or left.get("supports_step") or right.get("supports_step") or "")
    if len(str(other.get("label") or "").strip()) < len(str(merged.get("label") or "").strip()):
        merged["label"] = str(other.get("label") or "").strip() or merged.get("label")
    return merged


def _semantic_group_key(item: dict[str, Any]) -> str:
    text = " ".join(
        str(item.get(field) or "").strip().casefold()
        for field in ("label", "description", "reason")
    )
    return canonicalize_concept_key(text)


def _item_is_inapplicable(item: dict[str, Any], *, context: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(field) or "").strip().casefold()
        for field in ("label", "description", "reason", "why_it_matters")
    )
    if not text:
        return False
    if _contains_student_requirement(text):
        age_years = context.get("child_age_years")
        if age_years is not None and age_years < 5:
            return True
        if context.get("has_minor_children") and age_years is None:
            return True
    if any(token in text for token in ("art. 663", "art 663", "hijo mayor estudiante")) and context.get("has_minor_children"):
        return True
    return False


def _contains_student_requirement(text: str) -> bool:
    return any(
        token in text
        for token in (
            "regularidad academica",
            "alumno regular",
            "plan de estudios",
            "continuidad de asistencia",
            "escolaridad",
            "certificado de estudios",
        )
    )


def _build_case_context(payload: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    case_memory = dict(payload.get("case_memory") or {})
    for key, value in dict(case_memory.get("facts") or {}).items():
        facts[str(key)] = dict(value or {}).get("value") if isinstance(value, dict) else value
    facts.update(dict(payload.get("facts") or {}))
    facts.update(dict((payload.get("conversation_state") or {}).get("known_facts_map") or {}))

    query = str(payload.get("query") or payload.get("effective_query") or "").strip().casefold()
    age_years = _resolve_child_age_years(facts, query)
    return {
        "child_age_years": age_years,
        "has_minor_children": bool(
            facts.get("hay_hijos")
            or facts.get("has_children")
            or (age_years is not None and age_years < 18)
            or re.search(r"\b\d+\s*(mes|meses)\b", query)
            or (re.search(r"\b\d+\s*(ano|anos|año|años)\b", query) and (age_years or 0) < 18)
        ),
    }


def _resolve_child_age_years(facts: dict[str, Any], query: str) -> float | None:
    for key in ("edad_hijo", "edad_hija", "edad_hijos", "child_age"):
        resolved = _numeric_age_to_years(facts.get(key))
        if resolved is not None:
            return resolved
    months_match = re.search(r"\b(\d+)\s*(mes|meses)\b", query)
    if months_match:
        return round(int(months_match.group(1)) / 12.0, 2)
    years_match = re.search(r"\b(\d+)\s*(ano|anos|año|años)\b", query)
    if years_match:
        return float(years_match.group(1))
    return None


def _numeric_age_to_years(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().casefold()
    if not text:
        return None
    months_match = re.search(r"\b(\d+)\s*(mes|meses)\b", text)
    if months_match:
        return round(int(months_match.group(1)) / 12.0, 2)
    years_match = re.search(r"\b(\d+)\s*(ano|anos|año|años)\b", text)
    if years_match:
        return float(years_match.group(1))
    try:
        return float(text)
    except ValueError:
        return None


def _to_label(value: Any) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    return re.sub(r"\s+", " ", text.replace("_", " ").strip())


def _build_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")[:80]


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _looks_like_evidence(value: str) -> bool:
    normalized = str(value or "").strip().casefold()
    return any(
        token in normalized
        for token in (
            "document",
            "prueba",
            "comprobante",
            "recibo",
            "constancia",
            "certificado",
            "partida",
            "dni",
            "testigo",
            "captura",
            "mensaje",
            "expediente",
            "pericia",
        )
    )


def _sort_bucket(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            int(item.get("priority_rank") or 99),
            str(item.get("label") or "").strip().casefold(),
            str(item.get("reason") or "").strip().casefold(),
        ),
    )
