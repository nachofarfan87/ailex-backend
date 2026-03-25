from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LegalDecisionResult:
    case_strength_label: str
    confidence_score: float
    execution_score: float
    execution_readiness: str
    strategic_posture: str
    dominant_factor: str
    decision_notes: list[str] = field(default_factory=list)
    caution_level: str = "moderado"
    warning_level: str = "moderado"
    signal_summary: dict[str, float | int | str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_strength_label": self.case_strength_label,
            "confidence_score": self.confidence_score,
            "execution_score": self.execution_score,
            "execution_readiness": self.execution_readiness,
            "strategic_posture": self.strategic_posture,
            "dominant_factor": self.dominant_factor,
            "decision_notes": list(self.decision_notes),
            "caution_level": self.caution_level,
            "warning_level": self.warning_level,
            "signal_summary": dict(self.signal_summary),
        }


class LegalDecisionEngine:
    _CRITICAL_TERMS: tuple[str, ...] = (
        "competencia",
        "legitimacion",
        "domicilio",
        "prueba",
        "ingresos",
        "violencia",
        "riesgo",
        "notificacion",
        "partida",
        "vinculo",
    )

    def decide(
        self,
        *,
        reasoning: Any = None,
        normative_reasoning: Any = None,
        case_evaluation: Any = None,
        jurisprudence_analysis: Any = None,
        evidence_reasoning_links: Any = None,
        conflict_evidence: Any = None,
        procedural_timeline: Any = None,
        procedural_case_state: Any = None,
    ) -> LegalDecisionResult:
        reasoning_data = self._coerce_dict(reasoning)
        normative_data = self._coerce_dict(normative_reasoning)
        evaluation_data = self._coerce_dict(case_evaluation)
        jurisprudence_data = self._coerce_dict(jurisprudence_analysis)
        evidence_data = self._coerce_dict(evidence_reasoning_links)
        conflict_data = self._coerce_dict(conflict_evidence)
        procedural_timeline_data = self._coerce_dict(procedural_timeline)
        procedural_state_data = self._coerce_dict(procedural_case_state)

        reasoning_confidence = self._confidence_from_reasoning(reasoning_data)
        normative_strength = self._normative_strength(reasoning_data, normative_data)
        case_strength = self._clamp01(float(evaluation_data.get("strength_score") or 0.0), floor=0.0)
        risk_score = self._risk_score(evaluation_data)
        evidence_strength = self._evidence_strength(evidence_data)
        precedent_trend = str(jurisprudence_data.get("precedent_trend") or "neutral").strip().lower()
        precedent_delta = float(jurisprudence_data.get("confidence_delta") or 0.0)
        unresolved_count = len(normative_data.get("unresolved_issues") or [])
        evidentiary_gaps = len(evidence_data.get("critical_evidentiary_gaps") or [])
        critical_count = self._critical_issue_count(normative_data, evidence_data, conflict_data)
        procedural_phase = str(procedural_state_data.get("procedural_phase") or "unknown").strip().lower()
        litigation_friction = self._clamp01(float(procedural_state_data.get("litigation_friction_score") or 0.0), floor=0.0, ceiling=1.0)
        blocking_factor = str(procedural_state_data.get("blocking_factor") or "none").strip().lower()
        defense_status = str(procedural_state_data.get("defense_status") or "unknown").strip().lower()
        enforcement_signal = str(procedural_state_data.get("enforcement_signal") or "none").strip().lower()
        service_status = str(procedural_state_data.get("service_status") or "unknown").strip().lower()
        procedural_anomalies = len(procedural_timeline_data.get("detected_anomalies") or [])

        merit_score = (
            (normative_strength * 0.38)
            + (case_strength * 0.32)
            + (evidence_strength * 0.22)
            + (reasoning_confidence * 0.08)
        )
        decision_notes: list[str] = []

        if normative_strength >= 0.65:
            decision_notes.append("La base normativa aparece suficientemente consolidada.")
        elif normative_strength <= 0.42:
            decision_notes.append("La base normativa todavia no permite empujar una postura expansiva.")

        if precedent_trend == "favorable" and normative_strength >= 0.60:
            jurisprudential_impact = min(0.08, max(precedent_delta, 0.02) + 0.02)
            merit_score += jurisprudential_impact
            decision_notes.append("La jurisprudencia favorable refuerza materialmente el encuadre ya sostenido por la norma.")
        elif precedent_trend == "adverse":
            jurisprudential_impact = min(-0.02, precedent_delta or -0.04)
            merit_score += jurisprudential_impact
            decision_notes.append("La jurisprudencia adversa introduce una cautela real sobre el alcance del planteo.")
        elif precedent_trend == "neutral" and jurisprudence_data.get("reasoning_directive"):
            decision_notes.append(str(jurisprudence_data.get("reasoning_directive")))

        penalty = 0.0
        penalty += min(risk_score * 0.22, 0.22)
        penalty += min(unresolved_count * 0.025, 0.15)
        penalty += min(evidentiary_gaps * 0.03, 0.15)
        penalty += min(critical_count * 0.045, 0.18)

        if risk_score >= 0.70 and evidence_strength <= 0.45:
            penalty += 0.12
            decision_notes.append("La combinacion de riesgo alto y prueba debil obliga a bajar la postura final.")
        if critical_count >= 3 or unresolved_count >= 5:
            penalty += 0.10
            decision_notes.append("Las faltas criticas pesan mas que cualquier mejora marginal en otros modulos.")
        elif unresolved_count >= 3:
            decision_notes.append("Persisten cuestiones irresueltas que limitan la ambicion estrategica.")
        if evidence_strength <= 0.40:
            decision_notes.append("La cobertura probatoria actual es insuficiente para sostener afirmaciones amplias.")

        merit_score = self._clamp01(merit_score - penalty + 0.16, floor=0.18, ceiling=0.92)
        execution_score = self._execution_score(
            blocking_factor=blocking_factor,
            service_status=service_status,
            procedural_phase=procedural_phase,
            enforcement_signal=enforcement_signal,
            litigation_friction=litigation_friction,
            defense_status=defense_status,
            procedural_anomalies=procedural_anomalies,
        )
        execution_readiness = self._execution_readiness(execution_score)
        confidence_score = self._clamp01((merit_score * 0.7) + (execution_score * 0.3), floor=0.18, ceiling=0.92)
        strength_label = self._strength_label(merit_score)
        strategic_posture = self._strategic_posture(
            final_score=confidence_score,
            normative_strength=normative_strength,
            risk_score=risk_score,
            evidence_strength=evidence_strength,
            precedent_trend=precedent_trend,
            critical_count=critical_count,
            unresolved_count=unresolved_count,
            blocking_factor=blocking_factor,
            litigation_friction=litigation_friction,
            defense_status=defense_status,
            enforcement_signal=enforcement_signal,
        )
        dominant_factor = self._dominant_factor(
            normative_strength=normative_strength,
            evidence_strength=evidence_strength,
            risk_score=risk_score,
            precedent_trend=precedent_trend,
            precedent_delta=precedent_delta,
            final_score=confidence_score,
            blocking_factor=blocking_factor,
            litigation_friction=litigation_friction,
        )
        caution_level = self._caution_level(
            risk_score=risk_score,
            evidence_strength=evidence_strength,
            critical_count=critical_count,
            unresolved_count=unresolved_count,
            blocking_factor=blocking_factor,
            litigation_friction=litigation_friction,
        )

        if strategic_posture == "agresiva":
            decision_notes.append("El cuadro permite priorizar avance y pretension principal sin forzar cautelas innecesarias.")
        elif strategic_posture == "cautelosa":
            decision_notes.append("La estrategia debe priorizar saneamiento, prueba y control de riesgo antes de ampliar el reclamo.")
        else:
            decision_notes.append("Existe margen para avanzar, pero con control de soporte y alcance.")

        if defense_status == "defaulted":
            decision_notes.append("La rebeldia o el decaimiento del derecho mejoran la posicion litigiosa sin alterar el merito material.")
        if blocking_factor == "competence":
            decision_notes.append("La cuestion de competencia introduce un freno procesal real, aunque no borra el merito sustantivo.")
        elif blocking_factor == "service":
            decision_notes.append("El caso presenta fortaleza juridica, pero su avance esta bloqueado por notificacion.")
        elif blocking_factor == "execution":
            decision_notes.append("El expediente ya se encuentra en fase de ejecucion y requiere remover obstaculos de cumplimiento.")
        elif blocking_factor == "administrative_delay":
            decision_notes.append("El principal obstaculo no es juridico sino operativo.")
        elif blocking_factor == "evidence":
            decision_notes.append("El principal cuello de botella actual es probatorio dentro de la dinamica procesal.")
        elif blocking_factor == "defense":
            decision_notes.append("La defensa activa concentra la friccion del expediente en el tramo contradictorio.")

        if litigation_friction >= 0.45 and defense_status != "defaulted":
            decision_notes.append("La friccion litigiosa acumulada restringe el margen de avance inmediato.")
        if enforcement_signal == "active":
            decision_notes.append("La senal procesal relevante ya no es discutir derecho, sino ejecutar u operacionalizar lo obtenido.")
        if procedural_anomalies >= 2 and blocking_factor == "none":
            decision_notes.append("La secuencia procesal presenta inconsistencias que aconsejan prudencia operativa.")

        if execution_readiness == "listo_para_avanzar":
            decision_notes.append("El expediente esta en condiciones de avanzar inmediatamente.")
        elif execution_readiness == "requiere_impulso_procesal":
            decision_notes.append("El caso requiere impulso procesal concreto para traducir el merito en avance util.")
        else:
            decision_notes.append("El avance inmediato aparece bloqueado por un obstaculo procesal relevante.")

        return LegalDecisionResult(
            case_strength_label=strength_label,
            confidence_score=round(confidence_score, 4),
            execution_score=round(execution_score, 4),
            execution_readiness=execution_readiness,
            strategic_posture=strategic_posture,
            dominant_factor=dominant_factor,
            decision_notes=self._dedupe(decision_notes)[:6],
            caution_level=caution_level,
            warning_level=caution_level,
            signal_summary={
                "normative_strength": round(normative_strength, 4),
                "reasoning_confidence": round(reasoning_confidence, 4),
                "case_strength": round(case_strength, 4),
                "risk_score": round(risk_score, 4),
                "evidence_strength": round(evidence_strength, 4),
                "precedent_trend": precedent_trend,
                "precedent_delta": round(precedent_delta, 4),
                "unresolved_count": unresolved_count,
                "critical_count": critical_count,
                "procedural_phase": procedural_phase,
                "litigation_friction_score": round(litigation_friction, 4),
                "blocking_factor": blocking_factor,
                "defense_status": defense_status,
                "enforcement_signal": enforcement_signal,
                "service_status": service_status,
                "merit_score": round(merit_score, 4),
                "execution_score": round(execution_score, 4),
                "execution_readiness": execution_readiness,
            },
        )

    analyze = decide
    build = decide
    run = decide

    def _confidence_from_reasoning(self, reasoning: dict[str, Any]) -> float:
        raw = reasoning.get("confidence_score", reasoning.get("confidence"))
        if isinstance(raw, str):
            mapping = {"low": 0.32, "medium": 0.58, "high": 0.8}
            return mapping.get(raw.lower().strip(), 0.45)
        return self._clamp01(float(raw or 0.0), floor=0.18)

    def _normative_strength(self, reasoning: dict[str, Any], normative: dict[str, Any]) -> float:
        normative_conf = self._clamp01(float(normative.get("confidence_score") or 0.0), floor=0.18)
        reasoning_conf = self._confidence_from_reasoning(reasoning)
        rule_count = len(normative.get("applied_rules") or [])
        issue_count = len(normative.get("unresolved_issues") or [])
        rule_bonus = min(rule_count * 0.02, 0.08)
        issue_penalty = min(issue_count * 0.015, 0.09)
        return self._clamp01((normative_conf * 0.65) + (reasoning_conf * 0.35) + rule_bonus - issue_penalty, floor=0.18)

    def _risk_score(self, evaluation: dict[str, Any]) -> float:
        raw = evaluation.get("risk_score")
        if raw is not None:
            return self._clamp01(float(raw), floor=0.0)
        label = str(evaluation.get("legal_risk_level") or "").strip().lower()
        return {"bajo": 0.25, "medio": 0.55, "alto": 0.8}.get(label, 0.45)

    def _evidence_strength(self, evidence: dict[str, Any]) -> float:
        confidence = self._clamp01(float(evidence.get("confidence_score") or 0.0), floor=0.18)
        links = evidence.get("requirement_links") or []
        if not links:
            return confidence
        high_support = sum(1 for item in links if str(self._coerce_dict(item).get("support_level") or "").strip().lower() == "alto")
        low_support = sum(1 for item in links if str(self._coerce_dict(item).get("support_level") or "").strip().lower() == "bajo")
        ratio = high_support / max(len(links), 1)
        weakness_penalty = min(low_support * 0.03, 0.12)
        return self._clamp01((confidence * 0.7) + (ratio * 0.3) - weakness_penalty, floor=0.18)

    def _critical_issue_count(
        self,
        normative: dict[str, Any],
        evidence: dict[str, Any],
        conflict: dict[str, Any],
    ) -> int:
        items = [
            *[str(item) for item in (normative.get("unresolved_issues") or [])],
            *[str(item) for item in (evidence.get("critical_evidentiary_gaps") or [])],
            *[str(item) for item in (evidence.get("strategic_warnings") or [])],
        ]
        vulnerable = str(conflict.get("most_vulnerable_point") or "").strip()
        if vulnerable:
            items.append(vulnerable)
        return sum(1 for item in items if any(term in item.lower() for term in self._CRITICAL_TERMS))

    def _strategic_posture(
        self,
        *,
        final_score: float,
        normative_strength: float,
        risk_score: float,
        evidence_strength: float,
        precedent_trend: str,
        critical_count: int,
        unresolved_count: int,
        blocking_factor: str,
        litigation_friction: float,
        defense_status: str,
        enforcement_signal: str,
    ) -> str:
        if risk_score >= 0.70 and evidence_strength <= 0.45:
            return "cautelosa"
        if critical_count >= 3 or unresolved_count >= 5:
            return "cautelosa"
        if precedent_trend == "adverse" and risk_score >= 0.55:
            return "cautelosa"
        if blocking_factor in {"service", "competence"}:
            return "conservadora" if final_score >= 0.55 else "cautelosa"
        if blocking_factor in {"execution", "administrative_delay"} and final_score >= 0.55:
            return "conservadora"
        if blocking_factor == "evidence":
            return "conservadora" if final_score >= 0.48 else "cautelosa"
        if defense_status == "defaulted" and final_score >= 0.68 and risk_score <= 0.5 and blocking_factor not in {"service", "competence"}:
            return "agresiva"
        if litigation_friction >= 0.45 and evidence_strength >= 0.5:
            return "conservadora"
        if enforcement_signal == "active":
            return "conservadora"
        if final_score >= 0.72 and normative_strength >= 0.62 and evidence_strength >= 0.55 and risk_score <= 0.42 and precedent_trend != "adverse":
            return "agresiva"
        return "conservadora"

    def _dominant_factor(
        self,
        *,
        normative_strength: float,
        evidence_strength: float,
        risk_score: float,
        precedent_trend: str,
        precedent_delta: float,
        final_score: float,
        blocking_factor: str,
        litigation_friction: float,
    ) -> str:
        if blocking_factor in {"competence", "service", "execution"}:
            return "procesal"
        if blocking_factor == "evidence":
            return "prueba"
        if blocking_factor in {"competence", "service", "execution", "administrative_delay"} and litigation_friction >= 0.12:
            return "riesgo"
        if risk_score >= max(normative_strength, evidence_strength) and risk_score >= 0.6:
            return "riesgo"
        if evidence_strength <= min(normative_strength, max(0.55, final_score)) and evidence_strength <= 0.5:
            return "prueba"
        if precedent_trend != "neutral" and abs(precedent_delta) >= 0.03 and normative_strength >= 0.58:
            return "jurisprudencia"
        return "norma"

    @staticmethod
    def _strength_label(score: float) -> str:
        if score >= 0.72:
            return "alto"
        if score >= 0.48:
            return "medio"
        return "bajo"

    @staticmethod
    def _caution_level(
        risk_score: float,
        evidence_strength: float,
        critical_count: int,
        unresolved_count: int,
        blocking_factor: str = "none",
        litigation_friction: float = 0.0,
    ) -> str:
        if risk_score >= 0.75 or (evidence_strength <= 0.42 and critical_count >= 2) or unresolved_count >= 5:
            return "alto"
        if blocking_factor in {"competence", "service", "execution", "administrative_delay", "evidence", "defense"}:
            return "moderado"
        if litigation_friction >= 0.35:
            return "moderado"
        if risk_score >= 0.5 or critical_count >= 1 or unresolved_count >= 3:
            return "moderado"
        return "bajo"

    def _execution_score(
        self,
        *,
        blocking_factor: str,
        service_status: str,
        procedural_phase: str,
        enforcement_signal: str,
        litigation_friction: float,
        defense_status: str,
        procedural_anomalies: int,
    ) -> float:
        score = 0.65
        blocking_cap = {
            "competence": 0.25,
            "service": 0.30,
            "evidence": 0.45,
            "administrative_delay": 0.55,
        }.get(blocking_factor)

        if procedural_phase in {"judgment", "enforcement"}:
            score = max(score, 0.78)
        elif procedural_phase == "pre_judgment":
            score = max(score, 0.66)
        elif procedural_phase == "service":
            score = min(score, 0.5)

        if enforcement_signal == "active":
            score = max(score, 0.7)
        elif enforcement_signal == "latent":
            score = max(score, 0.62)

        if service_status == "pending":
            score = min(score, 0.3)
        elif service_status == "delayed":
            score = min(score, 0.35)

        if blocking_cap is not None:
            score = min(score, blocking_cap)
        elif blocking_factor == "execution":
            score = max(score, 0.65)

        score -= min(litigation_friction * 0.18, 0.12)
        if procedural_anomalies >= 2:
            score -= 0.04

        if defense_status == "defaulted":
            score += 0.08

        if enforcement_signal == "active":
            score = max(score, 0.65)
        if procedural_phase in {"judgment", "enforcement"}:
            score = max(score, 0.68)
        if blocking_cap is not None:
            score = min(score, blocking_cap)

        return self._clamp01(score, floor=0.0, ceiling=0.92)

    @staticmethod
    def _execution_readiness(execution_score: float) -> str:
        if execution_score >= 0.65:
            return "listo_para_avanzar"
        if execution_score >= 0.40:
            return "requiere_impulso_procesal"
        return "bloqueado_procesalmente"

    @staticmethod
    def _clamp01(value: float, *, floor: float = 0.0, ceiling: float = 0.95) -> float:
        return max(floor, min(ceiling, float(value)))

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    @staticmethod
    def _coerce_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return value.to_dict()
        if hasattr(value, "__dict__"):
            return vars(value)
        return {}
