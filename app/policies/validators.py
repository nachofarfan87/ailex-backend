"""
AILEX — Validadores de salida.

Pipeline de validación que toda respuesta debe pasar
antes de ser entregada al usuario.

Orden de validación:
1. Estructura (ResponsePolicy) — 8 secciones canónicas
2. Guardrails (LegalGuardrails) — prohibiciones absolutas
3. Confianza (ConfidencePolicy) — coherencia score/nivel
4. Tono (ToneValidator) — lenguaje profesional
5. Inyección de disclaimer
"""

from app.policies.response_policy import ResponsePolicy
from app.policies.confidence_policy import ConfidencePolicy
from app.policies.legal_guardrails import LegalGuardrails
from app.policies.tone_validator import ToneValidator


class ValidationResult:
    """Resultado de una validación completa."""

    def __init__(self):
        self.is_valid = True
        self.errors = []          # Problemas que impiden la entrega
        self.warnings = []        # Advertencias que no bloquean
        self.corrections = []     # Correcciones aplicadas automáticamente

    def add_error(self, error: str):
        self.is_valid = False
        self.errors.append(error)

    def add_warning(self, warning: str):
        self.warnings.append(warning)

    def add_correction(self, correction: str):
        self.corrections.append(correction)

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "corrections": self.corrections,
        }


class OutputValidator:
    """
    Pipeline completo de validación de salida.

    Toda JuridicalResponse pasa por este validador antes
    de entregarse. Si falla en errores críticos, la respuesta
    se retiene o corrige automáticamente donde sea posible.
    """

    @classmethod
    def validate_and_correct(
        cls,
        response: dict,
        available_sources: list = None,
    ) -> tuple[dict, ValidationResult]:
        """
        Validación completa con correcciones automáticas donde sea posible.

        Retorna: (response_corregida, resultado_validación)
        """
        result = ValidationResult()

        if available_sources is None:
            available_sources = []

        # ─── 1. Validar estructura (8 secciones) ──────
        is_valid, struct_errors = ResponsePolicy.validate_completeness(response)
        for err in struct_errors:
            result.add_error(err)

        # ─── 2. Guardrails sobre texto ─────────────────
        resumen = response.get("resumen_ejecutivo", "")
        text_to_check = resumen

        # Incluir texto de acciones sugeridas
        for action in response.get("acciones_sugeridas", []):
            if isinstance(action, dict):
                text_to_check += " " + action.get("action", "")
            elif isinstance(action, str):
                text_to_check += " " + action

        # Incluir encuadre preliminar
        for item in response.get("encuadre_preliminar", []):
            if isinstance(item, str):
                text_to_check += " " + item

        violations = LegalGuardrails.check_output(text_to_check)
        for v in violations:
            if v["severity"] == "critical":
                result.add_error(f"[{v['guardrail']}] {v['issue']}")
            else:
                result.add_warning(f"[{v['guardrail']}] {v['issue']}")

        # ─── 3. Verificar fuentes ──────────────────────
        sources = response.get("fuentes_respaldo", [])
        source_violations = LegalGuardrails.check_sources_exist(
            sources, available_sources if available_sources else None
        )
        for v in source_violations:
            if v["severity"] == "critical":
                result.add_error(f"[{v['guardrail']}] {v['issue']}")
            else:
                result.add_warning(f"[{v['guardrail']}] {v['issue']}")

        # ─── 4. Coherencia de confianza ────────────────
        confidence_errors = ConfidencePolicy.validate_confidence_coherence(response)
        for err in confidence_errors:
            result.add_error(err)

        # Corrección automática: degradar confianza si no hay fuentes
        if not sources and response.get("confianza_score", 0) > 0.3:
            old_score = response.get("confianza_score", 0)
            response["confianza_score"] = min(old_score, 0.2)
            response["nivel_confianza"] = "sin_respaldo"
            result.add_correction(
                f"confianza_score reducido de {old_score} a {response['confianza_score']} "
                "(sin fuentes disponibles)"
            )

        # ─── 5. Validar tono ──────────────────────────
        tone_issues = ToneValidator.validate(text_to_check)
        for issue in tone_issues:
            result.add_warning(f"[TONO] {issue}")

        # ─── 6. Inyectar disclaimer ───────────────────
        if not response.get("advertencia_general"):
            response = ResponsePolicy.enforce_disclaimer(response)
            result.add_correction("Disclaimer obligatorio inyectado.")

        # ─── 7. Placeholders si faltan datos críticos ─
        missing = response.get("datos_faltantes", [])
        if isinstance(missing, list):
            placeholder_violations = LegalGuardrails.check_placeholders_for_missing_data(
                text_to_check, missing
            )
            for v in placeholder_violations:
                result.add_warning(f"[{v['guardrail']}] {v['issue']}")

        # Adjuntar metadata de validación
        response["_validation"] = result.to_dict()

        return response, result

    @classmethod
    def is_safe_to_deliver(cls, result: ValidationResult) -> bool:
        """
        Determina si la respuesta es segura para entregar.
        Errores críticos bloquean la entrega.
        """
        return result.is_valid
