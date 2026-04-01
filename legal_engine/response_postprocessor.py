# backend/legal_engine/response_postprocessor.py

def _render_strategy_response(
    self,
    *,
    pipeline_payload: dict[str, Any],
    api_payload: dict[str, Any],
) -> str:
    conversation_state = dict(api_payload.get("conversation_state") or {})
    progression_policy = dict(api_payload.get("progression_policy") or {})
    execution_output = dict(api_payload.get("execution_output") or {})

    strategic_decision = resolve_strategic_decision(
        conversation_state=conversation_state,
        pipeline_payload=pipeline_payload,
        progression_policy=progression_policy,
    )

    api_payload["strategic_decision"] = strategic_decision

    recommended_path = self._strip_known_quick_start(
        str(strategic_decision.get("recommended_path") or "").strip()
    )
    priority_action = self._strip_known_quick_start(
        str(strategic_decision.get("priority_action") or "").strip()
    )
    justification = str(strategic_decision.get("justification") or "").strip()
    alternative_path = self._strip_known_quick_start(
        str(strategic_decision.get("alternative_path") or "").strip()
    )
    alternative_reason = str(strategic_decision.get("alternative_reason") or "").strip()

    followup_question = self._resolve_followup_question(api_payload, execution_output)

    # ---------------------------
    # FALLBACK
    # ---------------------------
    if not recommended_path:
        return (
            "Todavia no hay una base suficiente para definir una estrategia clara.\n"
            "Conviene primero completar los datos clave del caso antes de avanzar."
        )

    parts: list[str] = []

    # ---------------------------
    # 1. DECISIÓN (PRIMERO Y CLARO)
    # ---------------------------
    parts.append("Qué conviene hacer en tu caso:\n")
    parts.append(f"👉 {recommended_path}.\n")

    # ---------------------------
    # 2. JUSTIFICACIÓN
    # ---------------------------
    if justification:
        clean_just = justification[0].upper() + justification[1:] if len(justification) > 1 else justification
        parts.append("\nPor qué:\n")
        parts.append(f"{clean_just}\n")

    # ---------------------------
    # 3. ACCIÓN CONCRETA
    # ---------------------------
    if priority_action:
        parts.append("\nPrimer paso concreto:\n")
        parts.append(f"{self._normalize_strategy_action(priority_action)}\n")

    # ---------------------------
    # 4. ALTERNATIVA
    # ---------------------------
    if alternative_path:
        alt = alternative_path
        if alternative_reason:
            alt += f", pero suele ser menos conveniente porque {alternative_reason}"
        parts.append("\nOtra opción:\n")
        parts.append(f"{alt}.\n")

    # ---------------------------
    # 5. FOLLOW-UP (solo si suma)
    # ---------------------------
    if followup_question:
        parts.append("\nPara afinar la estrategia:\n")
        parts.append(f"{followup_question}")

    return "".join(parts).strip()


def _normalize_strategy_action(self, action: str) -> str:
    """
    Convierte texto técnico en instrucción accionable.
    """
    action = action.strip()

    replacements = [
        ("redactar", "Preparar y presentar"),
        ("iniciar", "Iniciar formalmente"),
        ("presentar", "Presentar"),
        ("evaluar", "Revisar"),
        ("analizar", "Revisar"),
    ]

    for old, new in replacements:
        if action.lower().startswith(old):
            return action.replace(old, new, 1)

    return action