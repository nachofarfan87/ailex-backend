from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ProceduralCaseState:
    procedural_phase: str
    procedural_status: str
    litigation_friction_score: float
    procedural_risk_score: float
    blocking_factor: str
    enforcement_signal: str
    defense_status: str
    service_status: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProceduralCaseStateBuilder:
    """Deriva señales procesales útiles desde un timeline reconstruido."""

    def build(self, timeline: Any) -> ProceduralCaseState:
        payload = timeline.to_dict() if hasattr(timeline, "to_dict") else dict(timeline or {})
        ordered_events = list(payload.get("ordered_events") or [])
        key_events = list(payload.get("key_events") or [])
        anomalies = list(payload.get("detected_anomalies") or [])
        current_stage = str(payload.get("current_stage") or "unknown")
        pending_actions = list(payload.get("pending_actions") or [])
        labels = [str(event.get("label") or "") for event in key_events]

        defense_status = self._infer_defense_status(labels)
        service_status = self._infer_service_status(labels, anomalies)
        enforcement_signal = self._infer_enforcement_signal(labels)
        blocking_factor = self._infer_blocking_factor(labels, anomalies, current_stage, pending_actions)
        procedural_phase = self._infer_phase(labels, current_stage, enforcement_signal)
        procedural_status = self._infer_status(procedural_phase, blocking_factor, labels)
        friction_score, friction_notes = self._calculate_friction_score(ordered_events, labels, anomalies, blocking_factor)
        risk_score = self._calculate_risk_score(blocking_factor, procedural_phase, anomalies, service_status)
        notes = self._build_notes(
            procedural_phase=procedural_phase,
            procedural_status=procedural_status,
            blocking_factor=blocking_factor,
            defense_status=defense_status,
            service_status=service_status,
            enforcement_signal=enforcement_signal,
            anomalies=anomalies,
            friction_notes=friction_notes,
            pending_actions=pending_actions,
        )

        return ProceduralCaseState(
            procedural_phase=procedural_phase,
            procedural_status=procedural_status,
            litigation_friction_score=friction_score,
            procedural_risk_score=risk_score,
            blocking_factor=blocking_factor,
            enforcement_signal=enforcement_signal,
            defense_status=defense_status,
            service_status=service_status,
            notes=notes,
        )

    def _infer_phase(self, labels: list[str], current_stage: str, enforcement_signal: str) -> str:
        label_set = set(labels)
        if "archived" in label_set:
            return "archived"
        if enforcement_signal == "active":
            return "enforcement"
        if "judgment_entered" in label_set:
            return "judgment"
        if "right_forfeited" in label_set:
            return "pre_judgment"
        if "defense_entered" in label_set or current_stage == "contradictory_stage":
            return "defense"
        if "hearing_held" in label_set or "hearing_failed" in label_set or current_stage == "hearing_stage":
            return "hearing"
        if "service_ordered" in label_set or "service_completed" in label_set or current_stage == "service_pending":
            return "service"
        if "claim_admitted" in label_set or "claim_filed" in label_set:
            return "initial"
        return "initial"

    def _infer_status(self, phase: str, blocking_factor: str, labels: list[str]) -> str:
        if phase == "archived":
            return "closed"
        if phase == "judgment":
            return "resolved"
        if phase == "enforcement":
            return "active_enforcement"
        if blocking_factor not in {"none"}:
            return f"blocked_by_{blocking_factor}"
        if "right_forfeited" in labels:
            return "ready_for_decision"
        return f"in_{phase}"

    def _infer_defense_status(self, labels: list[str]) -> str:
        label_set = set(labels)
        if "right_forfeited" in label_set or "defense_missing" in label_set:
            return "defaulted"
        if "defense_entered" in label_set:
            return "active"
        return "unknown"

    def _infer_service_status(self, labels: list[str], anomalies: list[str]) -> str:
        label_set = set(labels)
        if "service_completed" in label_set:
            return "completed"
        if "service_ordered" in label_set:
            return "pending"
        if "service_ordered_without_completion" in anomalies:
            return "delayed"
        return "unknown"

    def _infer_enforcement_signal(self, labels: list[str]) -> str:
        label_set = set(labels)
        if "judgment_entered" in label_set and ("oficio_issued" in label_set or "oficio_completed" in label_set):
            return "active"
        if "judgment_entered" in label_set:
            return "latent"
        return "none"

    def _infer_blocking_factor(
        self,
        labels: list[str],
        anomalies: list[str],
        current_stage: str,
        pending_actions: list[str],
    ) -> str:
        label_set = set(labels)
        pending_text = " ".join(str(item).lower() for item in pending_actions)

        if "competence_issue" in label_set and "judgment_entered" not in label_set and "archived" not in label_set:
            return "competence"
        if "service_ordered_without_completion" in anomalies or ("service_ordered" in label_set and "service_completed" not in label_set):
            return "service"
        if "judgment_entered" in label_set and ("oficio_issued" in label_set or "oficio_completed" in label_set):
            return "execution"
        if "hearing_failed" in label_set and "defense_entered" in label_set:
            return "evidence"
        if current_stage == "contradictory_stage" and "defense_entered" in label_set:
            return "defense"
        if any(text in pending_text for text in ("diligenciamiento", "notificacion", "oficio")) or any(
            anomaly.startswith("duplicate_or_low_value_events_removed:") or anomaly == "events_without_date"
            for anomaly in anomalies
        ):
            return "administrative_delay"
        return "none"

    def _calculate_friction_score(
        self,
        ordered_events: list[dict[str, Any]],
        labels: list[str],
        anomalies: list[str],
        blocking_factor: str,
    ) -> tuple[float, list[str]]:
        score = 0.0
        notes: list[str] = []
        label_set = set(labels)

        if "hearing_failed" in label_set:
            score += 0.22
            notes.append("audiencia fallida")
        if "defense_entered" in label_set:
            score += 0.18
            notes.append("defensa activa")
        if "competence_issue" in label_set:
            score += 0.25
            notes.append("conflicto de competencia")
        if "service_ordered" in label_set and "service_completed" not in label_set:
            score += 0.18
            notes.append("servicio o notificacion pendientes")
        if "right_forfeited" in label_set or "defense_missing" in label_set:
            score += 0.08
            notes.append("rebeldia o falta de contestacion")
        if any(label.startswith("oficio_") for label in label_set):
            oficio_count = sum(1 for event in ordered_events if str(event.get("label", "")).startswith("oficio_"))
            if oficio_count >= 2:
                score += 0.10
                notes.append("reiteracion de oficios")
        if "events_without_date" in anomalies:
            score += 0.06
            notes.append("secuencia incompleta")
        if any(anomaly.startswith("duplicate_or_low_value_events_removed:") for anomaly in anomalies):
            score += 0.05
            notes.append("friccion administrativa")
        if blocking_factor == "execution":
            score += 0.14
            notes.append("bloqueo de ejecucion")

        return round(min(score, 1.0), 3), notes

    def _calculate_risk_score(
        self,
        blocking_factor: str,
        procedural_phase: str,
        anomalies: list[str],
        service_status: str,
    ) -> float:
        base = 0.15
        risk_by_block = {
            "none": 0.0,
            "service": 0.35,
            "defense": 0.25,
            "evidence": 0.32,
            "competence": 0.45,
            "execution": 0.38,
            "administrative_delay": 0.22,
        }
        score = base + risk_by_block.get(blocking_factor, 0.0)

        if procedural_phase in {"judgment", "archived"}:
            score -= 0.08
        if "judgment_without_clear_contradictory_stage" in anomalies:
            score += 0.10
        if "events_without_date" in anomalies:
            score += 0.06
        if service_status == "pending":
            score += 0.05

        return round(max(0.0, min(score, 1.0)), 3)

    def _build_notes(
        self,
        *,
        procedural_phase: str,
        procedural_status: str,
        blocking_factor: str,
        defense_status: str,
        service_status: str,
        enforcement_signal: str,
        anomalies: list[str],
        friction_notes: list[str],
        pending_actions: list[str],
    ) -> list[str]:
        notes = [
            f"phase={procedural_phase}",
            f"status={procedural_status}",
            f"blocking_factor={blocking_factor}",
            f"defense_status={defense_status}",
            f"service_status={service_status}",
            f"enforcement_signal={enforcement_signal}",
        ]
        for note in friction_notes[:3]:
            notes.append(f"friction:{note}")
        for anomaly in anomalies[:3]:
            notes.append(f"anomaly:{anomaly}")
        for action in pending_actions[:2]:
            notes.append(f"pending:{action}")
        return notes
