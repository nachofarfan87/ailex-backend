from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import re
from typing import Any


_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
)

_EVENT_RULES: list[tuple[str, tuple[str, ...], int]] = [
    ("judgment_entered", ("sentencia", "resuelvo", "fallo", "dictar sentencia"), 100),
    ("archived", ("archivo", "archivese", "archívese", "pase a archivo"), 95),
    ("competence_issue", ("incompetencia", "declinatoria", "remitase", "remítase"), 92),
    ("right_forfeited", ("rebeldia", "rebeldía", "decaimiento del derecho", "perdida del derecho", "pierde el derecho"), 90),
    ("defense_entered", ("contestacion de demanda", "contesta demanda", "contestación", "presenta responde", "evacua traslado"), 85),
    ("defense_missing", ("sin contestacion", "sin contestación", "no contesta", "falta contestacion"), 82),
    ("hearing_failed", ("audiencia fallida", "audiencia fracasada", "incomparecencia", "no comparece", "fracasa la audiencia"), 80),
    ("hearing_held", ("audiencia", "comparecen las partes", "se celebra audiencia"), 78),
    ("service_completed", ("cedula diligenciada", "cédula diligenciada", "notificacion cumplida", "notificación cumplida", "notificado", "diligencia cumplida"), 75),
    ("service_ordered", ("corrase traslado", "córrase traslado", "notifíquese", "notifiquese", "cedula", "cédula", "librar cedula", "librar cédula"), 72),
    ("interim_measure", ("cuota provisoria", "alimentos provisorios", "medida cautelar", "medida provisoria", "provisoria"), 88),
    ("oficio_completed", ("oficio diligenciado", "oficio contestado", "oficio cumplido"), 62),
    ("oficio_issued", ("oficio", "librar oficio", "oficio librado"), 60),
    ("claim_admitted", ("admítase", "admitase", "proveido inicial", "proveyendo demanda", "téngase por presentada la demanda"), 70),
    ("claim_filed", ("demanda", "promueve demanda", "interpone demanda", "inicio de demanda"), 68),
    ("notification", ("notificacion", "notificación", "cedula electronica", "cédula electrónica"), 55),
    ("administrative_noise", ("casillero digital", "téngase presente", "tengase presente", "agréguese", "agreguese", "por acompañado", "por acompanado"), 10),
]

_EVENT_PRIORITY = {
    "claim_filed": 10,
    "claim_admitted": 20,
    "interim_measure": 25,
    "service_ordered": 30,
    "notification": 35,
    "service_completed": 40,
    "hearing_held": 50,
    "hearing_failed": 52,
    "defense_entered": 60,
    "defense_missing": 62,
    "right_forfeited": 64,
    "oficio_issued": 70,
    "oficio_completed": 72,
    "competence_issue": 80,
    "judgment_entered": 90,
    "archived": 100,
    "administrative_noise": 999,
    "unknown": 900,
}

_NOISE_LABELS = {"administrative_noise"}


@dataclass
class ProceduralTimelineEvent:
    raw_index: int
    label: str
    title: str
    summary: str
    timestamp: str | None
    date: str | None
    sort_key: tuple[int, int, int] = field(default_factory=tuple)
    relevance_score: int = 0
    is_noise: bool = False
    deduplicated: bool = False
    inferred: bool = False
    source_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sort_key"] = list(self.sort_key)
        return payload


@dataclass
class ProceduralTimelineResult:
    ordered_events: list[dict[str, Any]]
    key_events: list[dict[str, Any]]
    timeline_summary: str
    current_stage: str
    pending_actions: list[str]
    detected_anomalies: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProceduralTimelineBuilder:
    """Reconstruye una linea de tiempo procesal limpia a partir de eventos crudos."""

    def build(self, events: list[dict[str, Any]] | None) -> ProceduralTimelineResult:
        raw_events = list(events or [])
        normalized = [self._normalize_event(item, index) for index, item in enumerate(raw_events)]
        ordered = sorted(normalized, key=lambda item: item.sort_key)
        anomalies = self._detect_anomalies(raw_events, ordered)
        deduped = self._deduplicate_events(ordered, anomalies)
        key_events = [item for item in deduped if not item.is_noise and item.relevance_score >= 60]
        current_stage = self._infer_current_stage(key_events)
        pending_actions = self._infer_pending_actions(key_events, current_stage)
        summary = self._build_timeline_summary(key_events, current_stage, pending_actions)
        return ProceduralTimelineResult(
            ordered_events=[item.to_dict() for item in deduped],
            key_events=[item.to_dict() for item in key_events],
            timeline_summary=summary,
            current_stage=current_stage,
            pending_actions=pending_actions,
            detected_anomalies=sorted(set(anomalies)),
        )

    def _normalize_event(self, event: dict[str, Any], index: int) -> ProceduralTimelineEvent:
        source_fields = dict(event or {})
        title = self._pick_first_text(source_fields, ("title", "label", "name", "document_title", "movement"))
        summary = self._pick_first_text(source_fields, ("summary", "description", "text", "detail", "notes"))
        combined = " ".join(part for part in (title, summary) if part).strip()
        label, relevance = self._classify_event(combined)
        timestamp = self._extract_timestamp(source_fields)
        sort_key = self._build_sort_key(timestamp, label, index)
        return ProceduralTimelineEvent(
            raw_index=index,
            label=label,
            title=title or f"evento_{index + 1}",
            summary=summary or title or "",
            timestamp=timestamp.isoformat(sep=" ") if timestamp else None,
            date=timestamp.date().isoformat() if timestamp else None,
            sort_key=sort_key,
            relevance_score=relevance,
            is_noise=label in _NOISE_LABELS or relevance <= 15,
            source_fields=source_fields,
        )

    def _classify_event(self, text: str) -> tuple[str, int]:
        normalized = self._normalize_text(text)
        for label, keywords, relevance in _EVENT_RULES:
            if any(keyword in normalized for keyword in keywords):
                return label, relevance
        return "unknown", 25 if normalized else 0

    def _extract_timestamp(self, event: dict[str, Any]) -> datetime | None:
        for field in ("timestamp", "datetime", "date_time", "fecha_hora", "date", "fecha", "uploaded_at"):
            value = event.get(field)
            parsed = self._parse_datetime(value)
            if parsed is not None:
                return parsed
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        text = str(value).strip()
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def _build_sort_key(self, timestamp: datetime | None, label: str, index: int) -> tuple[int, int, int]:
        if timestamp is None:
            return (9999999999, _EVENT_PRIORITY.get(label, 900), index)
        dt_value = int(timestamp.strftime("%Y%m%d%H%M%S"))
        return (dt_value, _EVENT_PRIORITY.get(label, 900), index)

    def _deduplicate_events(self, events: list[ProceduralTimelineEvent], anomalies: list[str]) -> list[ProceduralTimelineEvent]:
        seen: dict[tuple[str, str, str | None], ProceduralTimelineEvent] = {}
        result: list[ProceduralTimelineEvent] = []
        duplicate_count = 0

        for event in events:
            signature = (event.label, self._normalize_text(event.title), event.date)
            previous = seen.get(signature)
            if previous and (event.label.startswith("oficio_") or event.is_noise or previous.is_noise):
                duplicate_count += 1
                continue
            seen[signature] = event
            result.append(event)

        if duplicate_count:
            anomalies.append(f"duplicate_or_low_value_events_removed:{duplicate_count}")
        return result

    def _detect_anomalies(self, raw_events: list[dict[str, Any]], ordered: list[ProceduralTimelineEvent]) -> list[str]:
        anomalies: list[str] = []
        chronological_indices = [event.raw_index for event in ordered if event.timestamp]
        if chronological_indices and chronological_indices != sorted(chronological_indices):
            anomalies.append("events_uploaded_out_of_order")

        labels = [event.label for event in ordered if not event.is_noise]
        if "claim_filed" in labels and "claim_admitted" not in labels:
            anomalies.append("claim_without_admission")
        if "service_ordered" in labels and "service_completed" not in labels:
            anomalies.append("service_ordered_without_completion")
        if "judgment_entered" in labels and "service_completed" not in labels and "defense_entered" not in labels:
            anomalies.append("judgment_without_clear_contradictory_stage")
        if "hearing_held" in labels and "service_completed" not in labels:
            anomalies.append("hearing_without_confirmed_service")
        if any(event.timestamp is None for event in ordered):
            anomalies.append("events_without_date")
        return anomalies

    def _infer_current_stage(self, key_events: list[ProceduralTimelineEvent]) -> str:
        if not key_events:
            return "unknown"

        labels = {event.label for event in key_events}
        last_label = key_events[-1].label

        if "archived" in labels:
            return "archived"
        if "judgment_entered" in labels:
            return "judgment"
        if last_label == "competence_issue":
            return "competence_review"
        if last_label == "right_forfeited":
            return "awaiting_decision_after_forfeiture"
        if last_label in {"hearing_held", "hearing_failed"}:
            return "hearing_stage"
        if last_label == "defense_entered":
            return "contradictory_stage"
        if "service_ordered" in labels and "service_completed" not in labels:
            return "service_pending"
        if "claim_filed" in labels and "claim_admitted" not in labels:
            return "awaiting_admission"
        if "claim_admitted" in labels:
            return "post_admission"
        return "procedural_review"

    def _infer_pending_actions(self, key_events: list[ProceduralTimelineEvent], current_stage: str) -> list[str]:
        labels = {event.label for event in key_events}
        actions: list[str] = []

        if current_stage == "awaiting_admission":
            actions.append("Obtener proveido inicial o admision de la demanda.")
        if "service_ordered" in labels and "service_completed" not in labels:
            actions.append("Verificar diligenciamiento y cumplimiento de la notificacion.")
        if "hearing_failed" in labels:
            actions.append("Reprogramar audiencia o impulsar medida para asegurar comparecencia.")
        if "competence_issue" in labels and "judgment_entered" not in labels and "archived" not in labels:
            actions.append("Resolver la cuestion de competencia antes de continuar el tramite.")
        if "defense_missing" in labels or "right_forfeited" in labels:
            actions.append("Impulsar pase a resolver o decision sin mas tramite defensivo.")
        if "judgment_entered" in labels and "archived" not in labels:
            actions.append("Evaluar notificacion de sentencia y eventuales pasos de ejecucion o recursos.")
        return actions

    def _build_timeline_summary(
        self,
        key_events: list[ProceduralTimelineEvent],
        current_stage: str,
        pending_actions: list[str],
    ) -> str:
        if not key_events:
            return "No se detectaron eventos procesales con relevancia suficiente."

        first = key_events[0]
        last = key_events[-1]
        labels = [event.label for event in key_events]
        parts = [
            f"El expediente se reconstruye desde '{first.label}' hasta '{last.label}'.",
            f"Etapa procesal actual: {current_stage}.",
        ]
        if "competence_issue" in labels:
            parts.append("Se detecta una incidencia de competencia que altera la secuencia ordinaria.")
        if "right_forfeited" in labels:
            parts.append("Existe un hito de decaimiento o perdida del derecho de defensa.")
        if pending_actions:
            parts.append(f"Accion procesal pendiente principal: {pending_actions[0]}")
        return " ".join(parts)

    def _pick_first_text(self, event: dict[str, Any], fields: tuple[str, ...]) -> str:
        for field in fields:
            value = event.get(field)
            if value:
                return str(value).strip()
        return ""

    def _normalize_text(self, text: str) -> str:
        normalized = str(text or "").lower()
        normalized = normalized.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()
