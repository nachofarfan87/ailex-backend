from __future__ import annotations

import re
from typing import Any


def build_case_action_plan(
    *,
    api_payload: dict[str, Any] | None,
    case_status: str = "",
    operating_phase: str = "",
) -> list[dict[str, Any]]:
    payload = dict(api_payload or {})
    status = str(case_status or "").strip().lower()
    phase = str(operating_phase or "").strip().lower()

    steps: list[dict[str, Any]] = []
    unblock_steps = _build_unblock_steps(payload, case_status=status, operating_phase=phase)
    steps.extend(unblock_steps)
    blocker_ids = [str(item["id"]) for item in unblock_steps]

    candidate_actions = _collect_candidate_actions(payload)
    for candidate in candidate_actions:
        step = _materialize_action_step(
            candidate,
            blocker_ids=blocker_ids,
            case_status=status,
            operating_phase=phase,
        )
        if step:
            steps.append(step)

    ordered = _order_steps(_dedupe_steps(steps))[:5]
    for index, step in enumerate(ordered):
        step["is_primary"] = index == 0
        step["step_id"] = str(step.get("id") or "")
    return ordered[:5]


def _build_unblock_steps(
    payload: dict[str, Any],
    *,
    case_status: str,
    operating_phase: str,
) -> list[dict[str, Any]]:
    case_progress = dict(payload.get("case_progress") or {})
    case_followup = dict(payload.get("case_followup") or {})
    contradictions = [
        dict(item)
        for item in list(case_progress.get("contradictions") or [])
        if isinstance(item, dict)
    ]
    critical_gaps = [
        dict(item)
        for item in list(case_progress.get("critical_gaps") or [])
        if isinstance(item, dict)
    ]
    steps: list[dict[str, Any]] = []

    if contradictions:
        contradiction = contradictions[0]
        label = _humanize_label(contradiction.get("label") or contradiction.get("key"))
        title = (
            f"Aclarar la contradiccion sobre {label}"
            if label
            else "Aclarar la contradiccion principal del caso"
        )
        steps.append(
            {
                "id": _build_id("clarify", contradiction.get("key") or "contradiction"),
                "step_id": _build_id("clarify", contradiction.get("key") or "contradiction"),
                "title": title,
                "description": str(
                    case_followup.get("question")
                    or f"Confirmar cual es el dato correcto sobre {label}."
                ).strip(),
                "priority": "high",
                "status": "pending",
                "is_primary": False,
                "phase": "clarify",
                "phase_label": _phase_label("clarify"),
                "blocked_by_missing_info": False,
                "why_now": "Lo mas importante ahora es resolver esta contradiccion para no mover el caso sobre una base incierta.",
                "depends_on": [],
                "why_it_matters": "Con lo que ya esta definido, esta contradiccion puede cambiar el sentido de los proximos pasos del caso.",
                "source_hint": "case_progress.contradictions",
            }
        )

    elif bool(case_followup.get("should_ask")):
        gap = critical_gaps[0] if critical_gaps else {}
        gap_key = str(gap.get("key") or case_followup.get("need_key") or "followup").strip()
        label = _humanize_label(gap.get("label") or gap_key)
        title = f"Definir {label}" if label else "Definir el dato faltante prioritario"
        steps.append(
            {
                "id": _build_id("clarify", gap_key),
                "step_id": _build_id("clarify", gap_key),
                "title": title,
                "description": str(case_followup.get("question") or "").strip()
                or f"Precisar {label} antes de seguir avanzando.",
                "priority": "high"
                if case_status in {"needs_information", "blocked", "needs_fact_reconciliation"}
                else "medium",
                "status": "pending",
                "is_primary": False,
                "phase": "clarify" if operating_phase != "review" else "review",
                "phase_label": _phase_label("clarify" if operating_phase != "review" else "review"),
                "blocked_by_missing_info": False,
                "why_now": "Lo mas importante ahora es cerrar este dato porque define como conviene seguir con el caso.",
                "depends_on": [],
                "why_it_matters": str(case_followup.get("reason") or "").strip()
                or "Para avanzar con seguridad, primero hace falta completar este punto dominante.",
                "source_hint": "case_followup.question",
            }
        )

    return steps


def _collect_candidate_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    execution_output = dict(payload.get("execution_output") or {})
    execution_data = dict(execution_output.get("execution_output") or {})
    procedural_strategy = dict(payload.get("procedural_strategy") or {})
    case_strategy = dict(payload.get("case_strategy") or {})
    output_user = dict((payload.get("output_modes") or {}).get("user") or {})

    candidates: list[dict[str, Any]] = []

    for index, text in enumerate(_clean_list(execution_data.get("what_to_do_now"))):
        candidates.append(
            {
                "text": text,
                "source_hint": "execution_output.what_to_do_now",
                "kind": "action",
                "order": index,
            }
        )

    for index, text in enumerate(_clean_list(execution_data.get("where_to_go"))):
        candidates.append(
            {
                "text": f"Confirmar donde tramitarlo: {text}",
                "source_hint": "execution_output.where_to_go",
                "kind": "routing",
                "order": index,
            }
        )

    for index, text in enumerate(_clean_list(execution_data.get("what_to_request"))):
        candidates.append(
            {
                "text": f"Preparar el pedido principal: {text}",
                "source_hint": "execution_output.what_to_request",
                "kind": "request",
                "order": index,
            }
        )

    documents = _clean_list(execution_data.get("documents_needed"))
    if documents:
        doc_summary = ", ".join(documents[:3])
        candidates.append(
            {
                "text": f"Reunir la documentacion clave: {doc_summary}",
                "source_hint": "execution_output.documents_needed",
                "kind": "documents",
                "order": 0,
            }
        )

    for index, text in enumerate(_clean_list(procedural_strategy.get("next_steps"))):
        candidates.append(
            {
                "text": text,
                "source_hint": "procedural_strategy.next_steps",
                "kind": "procedural",
                "order": index,
            }
        )

    for index, text in enumerate(_clean_list(case_strategy.get("recommended_actions"))):
        candidates.append(
            {
                "text": text,
                "source_hint": "case_strategy.recommended_actions",
                "kind": "strategic",
                "order": index,
            }
        )

    for index, text in enumerate(_clean_list(output_user.get("next_steps"))):
        candidates.append(
            {
                "text": text,
                "source_hint": "output_modes.user.next_steps",
                "kind": "guidance",
                "order": index,
            }
        )

    return candidates


def _materialize_action_step(
    candidate: dict[str, Any],
    *,
    blocker_ids: list[str],
    case_status: str,
    operating_phase: str,
) -> dict[str, Any] | None:
    text = str(candidate.get("text") or "").strip()
    if not text:
        return None

    kind = str(candidate.get("kind") or "")
    phase = _resolve_step_phase(text=text, kind=kind, operating_phase=operating_phase)
    title = _derive_title(text=text, kind=kind, phase=phase)
    if not title:
        return None

    blocked_by_missing_info = bool(blocker_ids) and phase in {"decide", "file", "execute", "review"}
    depends_on = list(blocker_ids) if blocked_by_missing_info else []
    return {
        "id": _build_id(str(candidate.get("kind") or "step"), title),
        "step_id": _build_id(str(candidate.get("kind") or "step"), title),
        "title": title,
        "description": text,
        "priority": _resolve_priority(
            text=text,
            kind=kind,
            phase=phase,
            order=int(candidate.get("order") or 0),
            case_status=case_status,
        ),
        "status": "blocked" if blocked_by_missing_info else "pending",
        "is_primary": False,
        "phase": phase,
        "phase_label": _phase_label(phase),
        "blocked_by_missing_info": blocked_by_missing_info,
        "why_now": _build_why_now(
            text=text,
            phase=phase,
            case_status=case_status,
            blocked_by_missing_info=blocked_by_missing_info,
        ),
        "depends_on": depends_on,
        "why_it_matters": _build_why_it_matters(
            text=text,
            kind=kind,
            phase=phase,
            case_status=case_status,
            blocked_by_missing_info=blocked_by_missing_info,
        ),
        "source_hint": str(candidate.get("source_hint") or "").strip() or None,
    }


def _resolve_step_phase(*, text: str, kind: str, operating_phase: str) -> str:
    normalized = _normalize_text(text)
    if kind == "documents":
        return "prepare" if not _looks_like_proof(normalized) else "prove"
    if kind == "routing":
        return "decide"
    if kind == "request":
        return "file"
    if kind == "strategic":
        return "decide"
    if kind == "guidance":
        return "prepare"
    if any(token in normalized for token in ("contradic", "aclar", "confirmar dato", "precisar")):
        return "clarify"
    if any(token in normalized for token in ("prueba", "acreditar", "comprobante", "document", "constancia")):
        return "prove"
    if any(token in normalized for token in ("presentar", "iniciar", "promover", "demanda", "escrito")):
        return "file"
    if any(token in normalized for token in ("elegir", "definir via", "encuadre", "competencia", "tramitar")):
        return "decide"
    if operating_phase in {"clarify", "structure", "decide", "review", "execute"}:
        return operating_phase if operating_phase != "structure" else "prepare"
    return "prepare"


def _resolve_priority(
    *,
    text: str,
    kind: str,
    phase: str,
    order: int,
    case_status: str,
) -> str:
    normalized = _normalize_text(text)
    if phase == "clarify":
        return "high"
    if phase in {"file", "decide"} and case_status in {"ready_for_execution", "ready_for_strategy_decision"}:
        return "high"
    if phase == "prove" and any(token in normalized for token in ("partida", "dni", "domicilio", "recibo", "comprobante")):
        return "high"
    if kind in {"routing", "request"}:
        return "high"
    if order == 0 and any(token in normalized for token in ("presentar", "iniciar", "promover", "definir", "confirmar")):
        return "high"
    if phase in {"prepare", "prove", "review"}:
        return "medium"
    if kind in {"action", "procedural", "strategic"}:
        return "medium"
    return "low"


def _build_why_now(
    *,
    text: str,
    phase: str,
    case_status: str,
    blocked_by_missing_info: bool,
) -> str:
    normalized = _normalize_text(text)
    if blocked_by_missing_info:
        return "Todavia no conviene avanzar con este paso porque antes hay que cerrar el faltante que manda en el caso."
    if phase == "clarify":
        return "Lo mas importante ahora es aclarar este punto para que el caso no siga abierto a interpretaciones opuestas."
    if phase == "prove":
        return "Ahora conviene reunir este respaldo porque permite sostener el proximo paso con base real."
    if phase == "decide":
        return "Con lo que ya esta definido, ahora conviene fijar criterio para que el caso no siga disperso."
    if phase == "file":
        return "Con la base actual, este ya es un paso que puede transformarse en movimiento procesal concreto."
    if "documentacion" in normalized or "document" in normalized:
        return "Ahora suma porque prepara el soporte minimo antes de dar un paso mas expuesto."
    if case_status in {"blocked", "needs_information", "needs_fact_reconciliation"}:
        return "Ahora sirve para preparar el caso sin forzar una accion que todavia seria prematura."
    return "Con la informacion disponible, este es el paso que mejor ordena lo que sigue."


def _build_why_it_matters(
    *,
    text: str,
    kind: str,
    phase: str,
    case_status: str,
    blocked_by_missing_info: bool,
) -> str:
    normalized = _normalize_text(text)
    if blocked_by_missing_info:
        return "Este paso todavia depende de resolver antes el faltante o bloqueo que hoy domina el caso."
    if phase == "clarify":
        return "Para avanzar con seguridad, primero hay que cerrar este punto que condiciona todo lo demas."
    if phase == "prove":
        return "Ayuda a sostener el caso con respaldo minimo y evita avanzar sobre afirmaciones todavia debiles."
    if phase == "file":
        return "Convierte una linea ya ordenada en un movimiento procesal concreto."
    if phase == "decide":
        return "Define la via principal y condiciona los proximos pasos del caso."
    if "juzgado" in normalized or "tramitar" in normalized or "competencia" in normalized or kind == "routing":
        return "Define donde y como mover el caso, reduciendo el riesgo de pasos inutiles."
    if case_status in {"blocked", "needs_information", "needs_fact_reconciliation"}:
        return "Sirve para preparar el caso mientras se termina de destrabar el punto pendiente."
    return "Convierte el estado actual del caso en un siguiente paso claro y usable."


def _phase_label(phase: str) -> str:
    labels = {
        "clarify": "Reunir informacion clave",
        "prepare": "Preparar la base del paso siguiente",
        "prove": "Reforzar prueba y respaldo",
        "decide": "Definir la via principal",
        "review": "Revisar el punto que frena el caso",
        "file": "Preparar presentacion concreta",
        "execute": "Ejecutar el siguiente paso",
    }
    return labels.get(str(phase or "").strip().lower(), "Ordenar el siguiente paso")


def _derive_title(*, text: str, kind: str, phase: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip()).rstrip(".")
    if not cleaned:
        return ""
    if kind == "routing":
        return "Confirmar donde tramitarlo"
    if kind == "request":
        return "Preparar el pedido principal"
    if kind == "documents":
        return "Reunir documentacion clave"
    if phase == "prove" and cleaned.lower().startswith("acreditar "):
        return _to_title(cleaned)
    return _to_title(cleaned)


def _order_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(steps, key=_step_sort_key)


def _step_sort_key(step: dict[str, Any]) -> tuple[int, int, int, str]:
    phase_rank = {
        "clarify": 0,
        "prepare": 1,
        "prove": 2,
        "decide": 3,
        "review": 4,
        "file": 5,
        "execute": 6,
    }.get(str(step.get("phase") or "").strip().lower(), 7)
    priority_rank = {
        "high": 0,
        "medium": 1,
        "low": 2,
    }.get(str(step.get("priority") or "").strip().lower(), 3)
    blocked_rank = 1 if bool(step.get("blocked_by_missing_info")) else 0
    return (
        blocked_rank,
        phase_rank,
        priority_rank,
        _normalize_text(step.get("title") or step.get("description") or ""),
    )


def _dedupe_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for step in steps:
        normalized = _normalize_text(step.get("title") or step.get("description") or "")
        if not normalized:
            continue
        existing_index = index_by_key.get(normalized)
        if existing_index is None:
            index_by_key[normalized] = len(result)
            result.append(step)
            continue
        if _step_sort_key(step) < _step_sort_key(result[existing_index]):
            result[existing_index] = step
    return result


def _to_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if not cleaned:
        return ""
    trimmed = cleaned.rstrip(".")
    if len(trimmed) <= 84:
        return trimmed[:1].upper() + trimmed[1:]
    shortened = trimmed[:84].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (shortened or trimmed[:84]) + "..."


def _build_id(prefix: str, value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    return f"{prefix}_{slug[:48] or 'step'}"


def _humanize_label(value: Any) -> str:
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    return re.sub(r"\s+", " ", text.replace("_", " ").strip())


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _looks_like_proof(value: str) -> bool:
    return any(
        token in value
        for token in ("prueba", "acreditar", "document", "comprobante", "constancia", "partida", "dni")
    )
