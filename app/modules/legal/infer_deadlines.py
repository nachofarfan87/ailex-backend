"""Prudent deadline inference for judicial notices."""

from app.modules.legal.calculate_deadline import calculate_procedural_deadline
from app.modules.procedural_deadlines import calculate_deadline, detect_deadlines


def infer_deadlines(elements: dict, jurisdiction: str = "Jujuy") -> dict:
    """Infer explicit deadlines and critical dates without inventing them."""
    text = elements.get("normalized_text", "")
    notification_date = elements.get("notification_date") or None
    hearing_date = elements.get("hearing_date") or ""
    detections = [calculate_deadline(item, notification_date) for item in detect_deadlines(text)]
    warnings = []

    explicit_deadline = ""
    critical_date = ""

    if detections:
        primary = detections[0]
        explicit_deadline = _format_deadline(primary)
        if primary.fecha_vencimiento:
            critical_date = primary.fecha_vencimiento
        warnings.extend(primary.advertencias)
    elif hearing_date:
        critical_date = hearing_date
        warnings.append("Se detecto una audiencia con fecha, pero no un plazo expreso en la notificacion.")
    else:
        warnings.append("El plazo no surge de forma expresa del texto disponible.")

    if explicit_deadline and not critical_date and notification_date:
        warnings.append(
            f"Se detecto plazo, pero su computo depende de las reglas procesales de {jurisdiction} y no puede cerrarse automaticamente."
        )
    elif explicit_deadline and not notification_date:
        warnings.append(
            "Hay una referencia a plazo, pero falta fecha de notificacion suficiente para estimar vencimiento."
        )

    if not explicit_deadline:
        warnings.append(
            f"Si la actuacion genera plazo por ministerio de la ley, debe verificarse en el codigo procesal aplicable de {jurisdiction}."
        )

    # V1 business-day deadline calculation
    primary_plazo_dias = detections[0].plazo_dias if detections else None
    deadline_calc = calculate_procedural_deadline(
        plazo_dias=primary_plazo_dias,
        notification_date=notification_date,
        is_procedural=_is_procedural(elements),
        jurisdiction=jurisdiction,
    )

    return {
        "deadline": explicit_deadline,
        "critical_date": critical_date,
        "notification_date": notification_date or "",
        "detections": [item.to_dict() for item in detections],
        "warnings": _dedupe(warnings),
        "estimated_due_date": deadline_calc["estimated_due_date"],
        "deadline_type": deadline_calc["deadline_type"],
        "deadline_basis": deadline_calc["deadline_basis"],
        "deadline_warning": deadline_calc["deadline_warning"],
    }


def _is_procedural(elements: dict) -> bool:
    """
    Return True if the document appears to be a procedural notification.
    Conservative default: True, since the module is focused on judicial notices.
    Treat as non-procedural only when no action was identified at all.
    """
    slug = (elements.get("procedural_action_slug") or "").strip()
    action = (elements.get("procedural_action") or "").strip()
    if slug and slug != "desconocida":
        return True
    if action and action not in ("actuacion no determinada", ""):
        return True
    doc = (elements.get("document_detected") or "").casefold()
    return bool(doc)


def _format_deadline(detection) -> str:
    if detection.plazo_dias is not None and detection.unidad:
        return f"{detection.plazo_dias} {detection.unidad} (texto: {detection.frase_detectada})"
    return detection.frase_detectada


def _dedupe(items: list[str]) -> list[str]:
    unique = []
    seen = set()
    for item in items:
        normalized = (item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique
