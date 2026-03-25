"""Procedural risk detection for judicial notices."""


_NEXT_STEP_BY_ACTION = {
    "traslado_demanda": "Revisar la demanda y preparar la contestacion o respuesta procesal dentro del plazo aplicable.",
    "traslado": "Verificar el objeto del traslado y preparar la presentacion correspondiente antes del vencimiento.",
    "intimacion": "Cumplir o contestar la intimacion y documentar el cumplimiento antes del apercibimiento.",
    "vista": "Analizar el expediente y evacuar la vista si corresponde dentro del marco procesal aplicable.",
    "audiencia": "Confirmar asistencia, agenda y prueba para la audiencia informada.",
    "integracion_tribunal": "Revisar la integracion del tribunal y verificar si corresponde alguna observacion o recusacion.",
    "providencia": "Revisar la providencia completa y confirmar si abre un plazo o impone una carga procesal.",
    "resolucion": "Analizar el alcance de la resolucion y verificar si habilita recurso, cumplimiento o presentacion inmediata.",
    "desconocida": "Revisar el documento completo y contrastarlo con el expediente antes de definir la proxima actuacion.",
}


def detect_risks(elements: dict, deadline_info: dict) -> dict:
    """Build prudent procedural risks, next step and observations."""
    action_slug = elements.get("procedural_action_slug", "desconocida")
    normalized_text = (elements.get("normalized_text") or "").casefold()
    risks = []
    observations = []

    if action_slug in {"traslado_demanda", "traslado"}:
        if deadline_info.get("deadline"):
            risks.append("La omision de respuesta dentro del plazo puede generar preclusion o rebeldia, segun el tramite aplicable.")
        else:
            risks.append("Hay un traslado detectado, pero el plazo no surge con claridad del texto y debe verificarse en la cedula y el codigo procesal.")

    if action_slug == "intimacion":
        risks.append("La falta de cumplimiento de la intimacion puede activar apercibimientos o sanciones procesales.")

    if action_slug == "audiencia":
        risks.append("La incomparecencia a audiencia puede perjudicar la posicion procesal y la produccion de prueba.")

    if action_slug == "integracion_tribunal":
        risks.append("La notificacion de integracion del tribunal no muestra un plazo expreso, pero conviene revisar si abre oportunidades de planteo o control.")

    if "apercib" in normalized_text:
        risks.append("El texto menciona apercibimiento; debe revisarse la consecuencia procesal especifica antes de dejar vencer el termino.")

    if not deadline_info.get("deadline"):
        observations.append("No se informa un plazo expreso en el texto analizado.")

    if deadline_info.get("critical_date"):
        observations.append(f"Fecha critica inferida: {deadline_info['critical_date']}.")

    observations.extend(deadline_info.get("warnings", []))

    return {
        "procedural_risks": _dedupe(risks),
        "recommended_next_step": _NEXT_STEP_BY_ACTION.get(
            action_slug,
            _NEXT_STEP_BY_ACTION["desconocida"],
        ),
        "observations": " ".join(_dedupe(observations)).strip(),
    }


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
