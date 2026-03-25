"""
AILEX — Cálculo básico y prudente de plazos procesales.
"""

from datetime import datetime, timedelta

from app.modules.procedural_deadlines.models import DeadlineDetection


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


def calculate_deadline(
    deadline: DeadlineDetection,
    fecha_notificacion: str = None,
) -> DeadlineDetection:
    """
    Calcular un vencimiento simple como fecha + plazo.

    Limitación: no contempla feriados, días inhábiles ni reglas locales complejas.
    """
    warnings = list(deadline.advertencias)
    effective_date = fecha_notificacion or deadline.fecha_notificacion

    updated = DeadlineDetection(
        tipo_actuacion=deadline.tipo_actuacion,
        plazo_dias=deadline.plazo_dias,
        unidad=deadline.unidad,
        frase_detectada=deadline.frase_detectada,
        requiere_calculo=deadline.requiere_calculo,
        fecha_notificacion=effective_date,
        fecha_vencimiento=deadline.fecha_vencimiento,
        advertencias=warnings,
        confianza=deadline.confianza,
    )

    warnings.append(
        "Cálculo estimado simple: no contempla feriados, días inhábiles ni reglas procesales específicas."
    )

    if not updated.requiere_calculo or updated.plazo_dias is None:
        warnings.append(
            "Se detectó un plazo, pero no hay base suficiente para estimar vencimiento automáticamente."
        )
        return updated

    if not effective_date:
        warnings.append(
            "Falta fecha de notificación para estimar el vencimiento del plazo."
        )
        return updated

    parsed_date = _parse_date(effective_date)
    if not parsed_date:
        warnings.append(
            "La fecha de notificación detectada no pudo interpretarse con el parser básico."
        )
        return updated

    updated.fecha_vencimiento = (parsed_date + timedelta(days=updated.plazo_dias)).date().isoformat()
    return updated


def _parse_date(raw_date: str) -> datetime | None:
    raw_date = raw_date.strip()

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw_date, fmt)
        except ValueError:
            continue

    lowered = raw_date.casefold()
    parts = lowered.split(" de ")
    if len(parts) == 3:
        day_raw, month_raw, year_raw = parts
        try:
            day = int(day_raw.strip())
            month = _MONTHS[month_raw.strip()]
            year = int(year_raw.strip())
            return datetime(year, month, day)
        except (KeyError, ValueError):
            return None

    return None
