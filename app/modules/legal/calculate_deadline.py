"""
AILEX — Production-oriented deadline calculator for judicial notifications (V1).

Rules:
- Only computes when notification_date AND plazo_dias are both available.
- Procedural actions default to business days (habiles), skipping Sat/Sun.
- Does NOT integrate official holidays — warns caller explicitly.
- Returns empty estimated_due_date when safe computation is impossible.
"""

from datetime import datetime

from app.modules.legal.business_days import add_business_days


_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d")

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_WARNING_HOLIDAYS = (
    "Calculo preliminar. Verificar feriados e inhabiles judiciales de {jurisdiction}."
)


def calculate_procedural_deadline(
    plazo_dias: int | None,
    notification_date: str | None,
    is_procedural: bool = True,
    jurisdiction: str = "Jujuy",
) -> dict:
    """
    Return estimated deadline fields from a day-count and a notification date.

    Args:
        plazo_dias: Number of days extracted from the notification text.
        notification_date: Raw date string (dd/mm/yyyy, dd/mm/yy, or ISO).
        is_procedural: True → use business days (Mon–Fri). False → calendar days.
        jurisdiction: Used in the warning message for contextual clarity.

    Returns:
        dict with keys:
            estimated_due_date  — "dd/mm/yyyy" or ""
            deadline_type       — "habiles" | "corridos" | ""
            deadline_basis      — human-readable basis or ""
            deadline_warning    — always non-empty (either a caveat or a reason
                                  why calculation was skipped)
    """
    empty = {
        "estimated_due_date": "",
        "deadline_type": "",
        "deadline_basis": "",
        "deadline_warning": "",
    }

    if not plazo_dias:
        return {
            **empty,
            "deadline_warning": (
                "Sin plazo expreso detectado: no es posible calcular vencimiento estimado."
            ),
        }

    if not notification_date:
        return {
            **empty,
            "deadline_warning": (
                "Plazo detectado, pero falta fecha de notificacion para calcular el vencimiento."
            ),
        }

    parsed = _parse_date(notification_date)
    if not parsed:
        return {
            **empty,
            "deadline_warning": (
                "La fecha de notificacion no pudo interpretarse: verificar formato."
            ),
        }

    deadline_type = "habiles" if is_procedural else "corridos"
    start = parsed.date()

    if is_procedural:
        due_date = add_business_days(start, plazo_dias)
        basis = "plazo textual expreso + computo habil estandar"
    else:
        from datetime import timedelta
        due_date = start + timedelta(days=plazo_dias)
        basis = "plazo textual expreso + computo corrido"

    return {
        "estimated_due_date": due_date.strftime("%d/%m/%Y"),
        "deadline_type": deadline_type,
        "deadline_basis": basis,
        "deadline_warning": _WARNING_HOLIDAYS.format(jurisdiction=jurisdiction),
    }


def _parse_date(raw: str) -> datetime | None:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    # "6 de marzo de 2026" / "06 de marzo de 2026"
    parts = raw.casefold().split(" de ")
    if len(parts) == 3:
        try:
            day = int(parts[0].strip())
            month = _MONTHS[parts[1].strip()]
            year = int(parts[2].strip())
            return datetime(year, month, day)
        except (KeyError, ValueError):
            pass

    return None
