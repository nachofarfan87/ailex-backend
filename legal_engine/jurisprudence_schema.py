"""
AILEX -- canonical jurisprudence schema.

Strict mode is intended for curated real precedents.
Legacy mode is a compatibility path for fixtures and older imported datasets.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


STRICT_MODE = "strict"
LEGACY_MODE = "legacy"
ALLOWED_MODES = {STRICT_MODE, LEGACY_MODE}

TOPIC_ALIASES = {
    "divorcio": "divorcio",
    "divorcios": "divorcio",
    "alimentos": "alimentos",
    "cuidado personal": "cuidado_personal",
    "cuidado_personal": "cuidado_personal",
    "sucesion": "sucesiones",
    "sucesiones": "sucesiones",
    "sucesorio": "sucesiones",
}
SUBTOPIC_ALIASES = {
    "divorcio": {
        "divorcio_unilateral": "divorcio_unilateral",
        "divorcio_unilateral_con_efectos_parcialmente_acordados": "divorcio_unilateral_con_efectos_parcialmente_acordados",
        "divorcio_unilateral_sin_respuesta_a_propuesta_reguladora": "divorcio_unilateral_sin_respuesta_a_propuesta_reguladora",
        "divorcio incausado": "divorcio_incausado",
        "divorcio_incausado": "divorcio_incausado",
        "divorcio_mutuo_acuerdo": "divorcio_mutuo_acuerdo",
        "acuerdo_regulador": "acuerdo_regulador",
        "efectos_accesorios": "efectos_accesorios",
    },
    "alimentos": {
        "cuota_provisoria": "cuota_provisoria",
        "hijo_mayor_estudiante_universitario": "hijo_mayor_estudiante_universitario",
        "progenitor_afin_obligacion_subsidiaria": "progenitor_afin_obligacion_subsidiaria",
        "aumento_de_cuota": "aumento_de_cuota",
    },
    "cuidado_personal": {
        "modalidad_compartida_indistinta": "modalidad_compartida_indistinta",
        "centro_de_vida_con_progenitor_paterno": "centro_de_vida_con_progenitor_paterno",
        "modalidad_alternada": "modalidad_alternada",
    },
    "sucesiones": {
        "declaratoria_de_herederos": "declaratoria_de_herederos",
        "competencia_territorial": "competencia_territorial",
    },
}
GENERIC_STRATEGIC_USE_MARKERS = (
    "sirve para orientar estrategicamente",
    "sirve como apoyo orientativo",
    "sirve para orientar la pretension",
    "regla util sobre la cuestion juridica",
)
ADMINISTRATIVE_MARKERS = (
    "registrese",
    "notifiquese",
    "hagase saber",
    "archivese",
    "para dictar sentencia",
    "poder judicial",
    "en la ciudad de",
)
BANNED_CASE_MARKERS_RE = re.compile(
    r"\b(?:expte?\.?|expediente|legajo|causa|dni|cuil|cuit)\b",
    re.IGNORECASE,
)
BANNED_PARTY_NAME_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,3}\b"
)
BANNED_CASE_CAPTION_RE = re.compile(r"\bc/\b|\bs/\b", re.IGNORECASE)
ARTICLE_SOURCE_ALIASES = {
    "ccyc": "CCyC",
    "codigo civil y comercial": "CCyC",
    "codigo civil y comercial de la nacion": "CCyC",
    "constitucion nacional": "CN",
    "cn": "CN",
    "constitucion de jujuy": "Const. Jujuy",
    "const jujuy": "Const. Jujuy",
    "ley procesal de familia": "LPF Jujuy",
    "lpf jujuy": "LPF Jujuy",
    "cpcc jujuy": "CPCC Jujuy",
}


def normalize_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9\s/_-]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.strip().split())
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def coerce_year(year_value: Any, date_value: Any = None) -> int | None:
    if isinstance(year_value, int):
        return year_value
    if isinstance(year_value, str) and year_value.strip().isdigit():
        return int(year_value.strip())
    date_text = clean_text(date_value)
    if len(date_text) >= 4 and date_text[:4].isdigit():
        return int(date_text[:4])
    return None


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
    return items


def normalize_topic(value: Any) -> str:
    normalized = normalize_text(value).replace("_", " ")
    if not normalized:
        return ""
    return TOPIC_ALIASES.get(normalized, normalized.replace(" ", "_"))


def normalize_subtopic(topic: str, value: Any) -> str | None:
    normalized = normalize_text(value).replace(" ", "_")
    if not normalized:
        return None
    mapping = SUBTOPIC_ALIASES.get(topic, {})
    return mapping.get(normalized, normalized)


def normalize_applied_article(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(r"(?P<source>[A-Za-zÁÉÍÓÚÑáéíóúñ.\s]+)?\s*(?P<article>\d+[A-Za-z]?)", text)
    if not match:
        return text
    source = normalize_text(match.group("source") or "")
    article = match.group("article")
    label = ARTICLE_SOURCE_ALIASES.get(source, clean_text(match.group("source") or ""))
    label = label or "Art."
    if label == "Art.":
        return f"Art. {article}"
    return f"{label} {article}"


def normalize_applied_articles(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif value is None:
        raw_items = []
    else:
        raw_items = [value]
    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, dict):
            source = clean_text(item.get("source") or item.get("source_id"))
            article = clean_text(item.get("article"))
            item = f"{source} {article}".strip()
        text = normalize_applied_article(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_items.append(text)
    return normalized_items


def coerce_confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _legacy_fallback_topic(raw: dict[str, Any]) -> str:
    topic = normalize_topic(raw.get("topic"))
    if topic:
        return topic
    topics = coerce_list(raw.get("topics"))
    if topics:
        return normalize_topic(topics[0])
    action_slug = clean_text(raw.get("action_slug")).replace("_", " ")
    return normalize_topic(action_slug or raw.get("forum"))


def _legacy_fallback_subtopic(topic: str, raw: dict[str, Any]) -> str | None:
    subtopic = normalize_subtopic(topic, raw.get("subtopic"))
    if subtopic:
        return subtopic
    action_slug = clean_text(raw.get("action_slug"))
    action_subtopic = normalize_subtopic(topic, action_slug)
    if action_subtopic and action_subtopic != topic:
        return action_subtopic
    topics = coerce_list(raw.get("topics"))
    if len(topics) >= 2:
        candidate = normalize_subtopic(topic, topics[1])
        if candidate in SUBTOPIC_ALIASES.get(topic, {}).values():
            return candidate
    return None


def _legacy_fallback_legal_issue(raw: dict[str, Any]) -> str:
    return clean_text(raw.get("legal_issue") or raw.get("decision_summary") or raw.get("summary") or raw.get("holding"))


def _legacy_fallback_criterion(raw: dict[str, Any]) -> str:
    for candidate in (
        raw.get("criterion"),
        raw.get("holding"),
        raw.get("key_reasoning"),
        raw.get("decision_summary"),
        raw.get("summary"),
    ):
        text = clean_text(candidate)
        if text:
            return text
    return ""


def _legacy_fallback_strategic_use(raw: dict[str, Any]) -> str:
    return clean_text(raw.get("strategic_use") or raw.get("strategic_value"))


def _legacy_fallback_full_text(raw: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            clean_text(raw.get("full_text")),
            clean_text(raw.get("facts_summary")),
            clean_text(raw.get("decision_summary") or raw.get("summary")),
            clean_text(raw.get("holding")),
            clean_text(raw.get("key_reasoning")),
            clean_text(raw.get("outcome")),
        )
        if part
    )


def _has_banned_markers(text: str) -> bool:
    lowered = normalize_text(text)
    if any(marker in lowered for marker in ADMINISTRATIVE_MARKERS):
        return True
    if BANNED_CASE_MARKERS_RE.search(text):
        return True
    if BANNED_CASE_CAPTION_RE.search(text):
        return True
    if BANNED_PARTY_NAME_RE.search(text):
        return True
    return False


def _minimum_quality(text: str, *, min_words: int) -> bool:
    return len(clean_text(text).split()) >= min_words


@dataclass(slots=True)
class JurisprudenceValidationError:
    field_name: str
    message: str


@dataclass(slots=True)
class JurisprudencePrecedent:
    id: str
    topic: str
    subtopic: str | None
    jurisdiction: str
    forum: str
    court: str
    year: int | None
    case_name: str
    source_type: str
    legal_issue: str
    applied_articles: list[str] = field(default_factory=list)
    criterion: str = ""
    strategic_use: str = ""
    full_text: str = ""
    keywords: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source_url: str = ""
    source_name: str = ""
    chamber: str = ""
    date: str = ""
    action_slug: str = ""
    facts_summary: str = ""
    decision_summary: str = ""
    key_reasoning: str = ""
    holding: str = ""
    outcome: str = ""
    document_type: str = ""
    procedural_stage: str = ""
    territorial_priority: str = ""
    local_practice_value: str = ""
    court_level: str = ""
    redundancy_group: str = ""
    practical_frequency: str = ""
    local_topic_cluster: str = ""
    dataset_kind: str = "real"
    ingest_mode: str = LEGACY_MODE
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        return self.id

    @property
    def source(self) -> str:
        return self.source_name or self.source_type

    @property
    def summary(self) -> str:
        return self.decision_summary or self.criterion or self.legal_issue

    @property
    def cited_rules(self) -> list[str]:
        return list(self.applied_articles)

    @property
    def topics(self) -> list[str]:
        items = [self.topic]
        if self.subtopic:
            items.append(self.subtopic)
        return coerce_list(items)

    @classmethod
    def from_record(cls, raw: dict[str, Any], *, mode: str = LEGACY_MODE) -> "JurisprudencePrecedent":
        resolved_mode = mode if mode in ALLOWED_MODES else LEGACY_MODE
        if resolved_mode == STRICT_MODE:
            topic = normalize_topic(raw.get("topic"))
            subtopic = normalize_subtopic(topic, raw.get("subtopic"))
            legal_issue = clean_text(raw.get("legal_issue"))
            criterion = clean_text(raw.get("criterion"))
            strategic_use = clean_text(raw.get("strategic_use"))
            full_text = clean_text(raw.get("full_text"))
            derived_fields: list[str] = []
        else:
            topic = _legacy_fallback_topic(raw)
            subtopic = _legacy_fallback_subtopic(topic, raw)
            legal_issue = _legacy_fallback_legal_issue(raw)
            criterion = _legacy_fallback_criterion(raw)
            strategic_use = _legacy_fallback_strategic_use(raw)
            full_text = _legacy_fallback_full_text(raw)
            derived_fields = [
                field_name
                for field_name, value in (
                    ("topic", raw.get("topic")),
                    ("subtopic", raw.get("subtopic")),
                    ("legal_issue", raw.get("legal_issue")),
                    ("criterion", raw.get("criterion")),
                    ("strategic_use", raw.get("strategic_use")),
                    ("full_text", raw.get("full_text")),
                )
                if not clean_text(value)
            ]

        metadata = dict(raw.get("metadata") or {})
        metadata["_derived_fields"] = derived_fields
        metadata["_explicit_criterion"] = clean_text(raw.get("criterion"))
        metadata["_explicit_legal_issue"] = clean_text(raw.get("legal_issue"))
        metadata["_explicit_strategic_use"] = clean_text(raw.get("strategic_use"))

        return cls(
            id=clean_text(raw.get("id") or raw.get("case_id") or raw.get("source_id")),
            topic=topic,
            subtopic=subtopic,
            jurisdiction=clean_text(raw.get("jurisdiction")),
            forum=clean_text(raw.get("forum")),
            court=clean_text(raw.get("court")),
            year=coerce_year(raw.get("year"), raw.get("date")),
            case_name=clean_text(raw.get("case_name")),
            source_type=clean_text(raw.get("source_type") or raw.get("source") or "jurisprudencia"),
            legal_issue=legal_issue,
            applied_articles=normalize_applied_articles(raw.get("applied_articles") or raw.get("cited_rules")),
            criterion=criterion,
            strategic_use=strategic_use or clean_text(raw.get("strategic_value")),
            full_text=full_text,
            keywords=coerce_list(raw.get("keywords")),
            confidence=coerce_confidence(raw.get("confidence")),
            source_url=clean_text(raw.get("source_url") or raw.get("origin_reference")),
            source_name=clean_text(raw.get("source") or raw.get("source_name")),
            chamber=clean_text(raw.get("chamber")),
            date=clean_text(raw.get("date")),
            action_slug=clean_text(raw.get("action_slug")).lower(),
            facts_summary=clean_text(raw.get("facts_summary")),
            decision_summary=clean_text(raw.get("decision_summary") or raw.get("summary")),
            key_reasoning=clean_text(raw.get("key_reasoning")),
            holding=clean_text(raw.get("holding")),
            outcome=clean_text(raw.get("outcome")),
            document_type=clean_text(raw.get("document_type")),
            procedural_stage=clean_text(raw.get("procedural_stage")),
            territorial_priority=clean_text(raw.get("territorial_priority")),
            local_practice_value=clean_text(raw.get("local_practice_value")),
            court_level=clean_text(raw.get("court_level")),
            redundancy_group=clean_text(raw.get("redundancy_group")),
            practical_frequency=clean_text(raw.get("practical_frequency")),
            local_topic_cluster=clean_text(raw.get("local_topic_cluster")),
            dataset_kind=clean_text(raw.get("dataset_kind") or "real") or "real",
            ingest_mode=resolved_mode,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.id,
            "topic": self.topic,
            "subtopic": self.subtopic,
            "jurisdiction": self.jurisdiction,
            "forum": self.forum,
            "court": self.court,
            "year": self.year,
            "case_name": self.case_name,
            "source_type": self.source_type,
            "source": self.source,
            "legal_issue": self.legal_issue,
            "applied_articles": list(self.applied_articles),
            "criterion": self.criterion,
            "strategic_use": self.strategic_use,
            "full_text": self.full_text,
            "keywords": list(self.keywords),
            "confidence": self.confidence,
            "source_url": self.source_url,
            "chamber": self.chamber,
            "date": self.date,
            "action_slug": self.action_slug,
            "facts_summary": self.facts_summary,
            "decision_summary": self.decision_summary,
            "key_reasoning": self.key_reasoning,
            "holding": self.holding,
            "outcome": self.outcome,
            "document_type": self.document_type,
            "procedural_stage": self.procedural_stage,
            "territorial_priority": self.territorial_priority,
            "local_practice_value": self.local_practice_value,
            "court_level": self.court_level,
            "redundancy_group": self.redundancy_group,
            "practical_frequency": self.practical_frequency,
            "local_topic_cluster": self.local_topic_cluster,
            "dataset_kind": self.dataset_kind,
            "ingest_mode": self.ingest_mode,
            "metadata": dict(self.metadata),
        }


def validate_precedent(precedent: JurisprudencePrecedent, *, mode: str | None = None) -> list[JurisprudenceValidationError]:
    resolved_mode = mode if mode in ALLOWED_MODES else precedent.ingest_mode
    errors: list[JurisprudenceValidationError] = []

    required_fields = ("id", "topic", "jurisdiction", "forum", "court", "case_name", "source_type")
    for field_name in required_fields:
        if not clean_text(getattr(precedent, field_name)):
            errors.append(JurisprudenceValidationError(field_name, f"Missing required field '{field_name}'."))  # noqa: PERF401

    if precedent.year is None:
        errors.append(JurisprudenceValidationError("year", "Missing or invalid 'year'."))  # noqa: PERF401

    if precedent.topic not in SUBTOPIC_ALIASES:
        errors.append(JurisprudenceValidationError("topic", "topic is outside the controlled vocabulary."))  # noqa: PERF401

    if resolved_mode == STRICT_MODE and precedent.subtopic:
        allowed_subtopics = SUBTOPIC_ALIASES.get(precedent.topic, {})
        if precedent.subtopic not in allowed_subtopics.values():
            errors.append(JurisprudenceValidationError("subtopic", "subtopic is outside the controlled vocabulary."))  # noqa: PERF401

    if resolved_mode == STRICT_MODE:
        for field_name in ("legal_issue", "criterion", "strategic_use", "full_text"):
            if not clean_text(getattr(precedent, field_name)):
                errors.append(JurisprudenceValidationError(field_name, f"Missing required strict field '{field_name}'."))  # noqa: PERF401

    legal_issue_min_words = 7 if resolved_mode == STRICT_MODE else 4
    if precedent.legal_issue and (not _minimum_quality(precedent.legal_issue, min_words=legal_issue_min_words) or _has_banned_markers(precedent.legal_issue)):
        errors.append(JurisprudenceValidationError("legal_issue", "legal_issue has insufficient quality or contains procedural noise."))  # noqa: PERF401

    if precedent.criterion:
        criterion_words = len(precedent.criterion.split())
        if criterion_words < (12 if resolved_mode == STRICT_MODE else 8) or criterion_words > 40:
            errors.append(JurisprudenceValidationError("criterion", "criterion must contain between 12 and 40 words."))  # noqa: PERF401
        if _has_banned_markers(precedent.criterion):
            errors.append(JurisprudenceValidationError("criterion", "criterion contains resolutives, procedural identifiers or party markers."))  # noqa: PERF401

    if precedent.strategic_use:
        if not _minimum_quality(precedent.strategic_use, min_words=8 if resolved_mode == STRICT_MODE else 5):
            errors.append(JurisprudenceValidationError("strategic_use", "strategic_use is too short for litigation use."))  # noqa: PERF401
        strategic_normalized = normalize_text(precedent.strategic_use)
        if resolved_mode == STRICT_MODE and any(marker in strategic_normalized for marker in GENERIC_STRATEGIC_USE_MARKERS):
            errors.append(JurisprudenceValidationError("strategic_use", "strategic_use is too generic for a real precedent."))  # noqa: PERF401
        if _has_banned_markers(precedent.strategic_use):
            errors.append(JurisprudenceValidationError("strategic_use", "strategic_use contains procedural noise."))  # noqa: PERF401

    if resolved_mode == STRICT_MODE and not precedent.applied_articles:
        errors.append(JurisprudenceValidationError("applied_articles", "Strict precedents must provide at least one applied article."))  # noqa: PERF401

    if resolved_mode == STRICT_MODE and precedent.metadata.get("_derived_fields"):
        errors.append(JurisprudenceValidationError("metadata", "Strict precedents cannot rely on derived fallback fields."))  # noqa: PERF401

    return errors
