from __future__ import annotations

import re
import unicodedata
from typing import Any

PROGRESSION_TO_CASE_STAGE = {
    "structuring_case": "analisis_estructurado",
    "strategy": "analisis_estrategico",
    "execution": "ejecucion",
}


class CaseStateExtractorService:
    def extract_from_pipeline_payload(self, pipeline_payload: dict[str, Any] | None) -> dict[str, Any]:
        payload = _as_dict(pipeline_payload)
        classification = _as_dict(payload.get("classification"))
        case_profile = _as_dict(payload.get("case_profile"))
        legal_reasoning = _as_dict(payload.get("legal_reasoning"))
        user_message = _clean_text(
            payload.get("user_message")
            or payload.get("query")
            or payload.get("user_query")
        )

        case_type = self._resolve_case_type(payload, classification, case_profile)
        domain = _clean_text(
            payload.get("legal_domain")
            or payload.get("domain")
            or case_profile.get("case_domain")
            or classification.get("case_domain")
            or payload.get("case_domain")
        )
        facts = self._extract_facts(payload, domain=domain)
        needs = self._extract_needs(payload)
        case_stage = self._resolve_case_stage(payload, facts=facts, needs=needs)
        primary_goal = self._resolve_primary_goal(
            payload=payload,
            user_message=user_message,
            case_type=case_type,
            legal_reasoning=legal_reasoning,
        )
        summary_text = self._resolve_summary_text(payload, legal_reasoning, user_message)
        events = self._extract_events(
            payload=payload,
            case_stage=case_stage,
            facts=facts,
            needs=needs,
        )

        return {
            "case_type": case_type,
            "primary_goal": primary_goal,
            "case_stage": case_stage,
            "facts": facts,
            "needs": needs,
            "events": events,
            "summary_text": summary_text,
            "jurisdiction": _clean_text(payload.get("jurisdiction") or case_profile.get("jurisdiction")),
            "confidence_score": _safe_float(payload.get("confidence_score") or payload.get("confidence")),
            "status": "active",
            "secondary_goals_json": [],
        }

    def _resolve_case_type(
        self,
        payload: dict[str, Any],
        classification: dict[str, Any],
        case_profile: dict[str, Any],
    ) -> str:
        for candidate in (
            classification.get("action_slug"),
            _as_dict(payload.get("case_structure")).get("action_slug"),
            case_profile.get("case_type"),
            payload.get("legal_domain"),
            payload.get("domain"),
            case_profile.get("case_domain"),
            classification.get("case_domain"),
            payload.get("case_domain"),
        ):
            normalized = _clean_text(candidate)
            if normalized and normalized.casefold() not in {"generic", "unknown", "general"}:
                return normalized
        return ""

    def _resolve_primary_goal(
        self,
        *,
        payload: dict[str, Any],
        user_message: str,
        case_type: str,
        legal_reasoning: dict[str, Any],
    ) -> str:
        recommended_strategy = _clean_text(legal_reasoning.get("recommended_strategy"))
        if recommended_strategy:
            return recommended_strategy

        quick_start = _strip_known_prefix(_clean_text(payload.get("quick_start")), "Primer paso recomendado:")
        if quick_start:
            return quick_start

        normalized = _normalize_text(user_message)
        heuristics = (
            (("divorci",), "iniciar divorcio"),
            (("alimento", "cuota alimentaria", "manutencion"), "reclamar cuota alimentaria"),
            (("cuidado personal", "tenencia"), "definir cuidado personal"),
            (("regimen de comunicacion", "visitas"), "definir regimen de comunicacion"),
            (("sucesion", "herencia"), "iniciar sucesion"),
        )
        for patterns, label in heuristics:
            if any(pattern in normalized for pattern in patterns):
                return label

        if case_type:
            return f"avanzar con {case_type.replace('_', ' ')}"
        return "obtener orientacion juridica"

    def _resolve_case_stage(
        self,
        payload: dict[str, Any],
        *,
        facts: list[dict[str, Any]],
        needs: list[dict[str, Any]],
    ) -> str:
        output_mode = _clean_text(payload.get("output_mode")).casefold()
        if output_mode == "ejecucion":
            return "ejecucion"
        if output_mode == "estrategia":
            return "analisis_estrategico"

        if not facts:
            return "consulta_inicial"

        critical_missing = {
            _canonical_key(item)
            for item in (
                list(payload.get("critical_missing") or [])
                + list(_as_dict(payload.get("question_engine_result")).get("critical_missing") or [])
            )
        }
        if critical_missing:
            return "recopilacion_hechos"

        if needs:
            return "recopilacion_hechos"

        return "analisis_estrategico"

    def _resolve_summary_text(
        self,
        payload: dict[str, Any],
        legal_reasoning: dict[str, Any],
        user_message: str,
    ) -> str:
        output_modes = _as_dict(payload.get("output_modes"))
        user_output = _as_dict(output_modes.get("user"))
        for candidate in (
            legal_reasoning.get("case_summary"),
            _as_dict(payload.get("reasoning")).get("short_answer"),
            user_output.get("summary"),
            payload.get("summary_text"),
        ):
            normalized = _clean_text(candidate)
            if normalized:
                return normalized
        if user_message:
            return user_message[:400]
        return ""

    def _extract_facts(self, payload: dict[str, Any], *, domain: str) -> list[dict[str, Any]]:
        facts: dict[str, dict[str, Any]] = {}

        pipeline_facts = _as_dict(payload.get("facts"))
        for raw_key, raw_value in pipeline_facts.items():
            if raw_value in (None, "", [], {}):
                continue
            self._store_fact(
                facts,
                {
                    "fact_key": _canonical_key(raw_key),
                    "fact_value": raw_value,
                    "value_type": _infer_value_type(raw_value),
                    "domain": domain,
                    "source_type": "user_explicit",
                    "confidence": 0.92,
                    "status": "confirmed",
                    "evidence_excerpt": _clean_text(payload.get("user_message") or payload.get("query")),
                },
            )

        for item in _as_list(payload.get("detected_facts")):
            normalized = self._normalize_fact_item(item, domain=domain)
            if normalized:
                self._store_fact(facts, normalized)

        return list(facts.values())

    def _normalize_fact_item(self, item: Any, *, domain: str) -> dict[str, Any]:
        if isinstance(item, dict):
            raw_key = item.get("fact_key") or item.get("key") or item.get("name") or item.get("label")
            raw_value = item.get("fact_value") if "fact_value" in item else item.get("value")
            if raw_value in (None, "", [], {}):
                return {}
            source_hint = _normalize_text(item.get("source_type") or item.get("source") or "")
            source_type = "user_explicit" if any(token in source_hint for token in ("user", "query", "turn", "explicit")) else "pipeline_inferred"
            status = _clean_text(item.get("status")) or ("confirmed" if source_type == "user_explicit" else "probable")
            confidence = _safe_float(item.get("confidence"))
            return {
                "fact_key": _canonical_key(raw_key),
                "fact_value": raw_value,
                "value_type": _clean_text(item.get("value_type")) or _infer_value_type(raw_value),
                "domain": _clean_text(item.get("domain")) or domain,
                "source_type": source_type,
                "confidence": confidence if confidence is not None else (0.9 if source_type == "user_explicit" else 0.65),
                "status": status,
                "evidence_excerpt": _clean_text(item.get("evidence_excerpt") or item.get("excerpt")),
            }
        if isinstance(item, str):
            key = _canonical_key(item)
            if not key:
                return {}
            return {
                "fact_key": key,
                "fact_value": True,
                "value_type": "boolean",
                "domain": domain,
                "source_type": "pipeline_inferred",
                "confidence": 0.6,
                "status": "probable",
                "evidence_excerpt": "",
            }
        return {}

    def _extract_needs(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        needs: dict[str, dict[str, Any]] = {}
        critical_keys = {
            _canonical_key(item)
            for item in (
                list(payload.get("critical_missing") or [])
                + list(_as_dict(payload.get("question_engine_result")).get("critical_missing") or [])
            )
        }
        missing_candidates = (
            list(payload.get("missing_facts") or [])
            + list(_as_dict(payload.get("question_engine_result")).get("missing_facts") or [])
        )
        for item in missing_candidates:
            normalized = self._normalize_need_item(item, critical_keys=critical_keys)
            if normalized:
                needs[normalized["need_key"]] = normalized
        return list(needs.values())

    def _normalize_need_item(self, item: Any, *, critical_keys: set[str]) -> dict[str, Any]:
        if isinstance(item, dict):
            raw_key = item.get("need_key") or item.get("fact_key") or item.get("key") or item.get("name") or item.get("label")
            fact_key = _canonical_key(raw_key)
            key = _normalize_need_key(raw_key)
            if not key:
                return {}
            category = _clean_text(item.get("category")) or self._infer_need_category(raw_key)
            priority = _clean_text(item.get("priority")).lower() or ("critical" if fact_key in critical_keys else "normal")
            return {
                "need_key": key,
                "category": category,
                "priority": priority,
                "status": _clean_text(item.get("status")) or "open",
                "reason": _clean_text(item.get("reason") or item.get("label") or raw_key),
                "suggested_question": _clean_text(item.get("suggested_question")) or _fact_to_question(raw_key),
                "resolved_by_fact_key": _canonical_key(item.get("resolved_by_fact_key")),
            }
        if isinstance(item, str):
            fact_key = _canonical_key(item)
            key = _normalize_need_key(item)
            if not key:
                return {}
            return {
                "need_key": key,
                "category": self._infer_need_category(item),
                "priority": "critical" if fact_key in critical_keys else "normal",
                "status": "open",
                "reason": _clean_text(item),
                "suggested_question": _fact_to_question(item),
                "resolved_by_fact_key": "",
            }
        return {}

    def _extract_events(
        self,
        *,
        payload: dict[str, Any],
        case_stage: str,
        facts: list[dict[str, Any]],
        needs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not (facts or needs or _clean_text(payload.get("output_mode")) or _clean_text(payload.get("query"))):
            return []
        return [
            {
                "event_type": "pipeline_case_state_extracted",
                "payload": {
                    "output_mode": _clean_text(payload.get("output_mode")),
                    "case_stage": case_stage,
                    "facts_detected": len(facts),
                    "needs_detected": len(needs),
                },
            }
        ]

    def _store_fact(self, facts: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
        fact_key = _canonical_key(item.get("fact_key"))
        if not fact_key:
            return
        previous = facts.get(fact_key)
        if previous is None:
            facts[fact_key] = item
            return
        if _source_strength(item.get("source_type")) >= _source_strength(previous.get("source_type")):
            facts[fact_key] = item

    def _infer_need_category(self, raw_value: Any) -> str:
        normalized = _normalize_text(raw_value)
        if any(token in normalized for token in ("ingres", "monto", "cuota", "gasto")):
            return "economico"
        if any(token in normalized for token in ("domicilio", "jurisdic", "juzgado", "competen")):
            return "procesal"
        if any(token in normalized for token in ("prueba", "comprobante", "mensaje", "document")):
            return "evidencia"
        return "hecho"


case_state_extractor_service = CaseStateExtractorService()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", _clean_text(value))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.casefold()


def _canonical_key(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", _normalize_text(value)).strip("_")
    return normalized[:120]


def _normalize_need_key(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if "::" in text:
        namespace, raw_key = text.split("::", 1)
        normalized_namespace = _canonical_key(namespace)
        normalized_key = _canonical_key(raw_key)
        if normalized_namespace and normalized_key:
            return f"{normalized_namespace}::{normalized_key}"
        return normalized_key
    normalized_key = _canonical_key(text)
    if not normalized_key:
        return ""
    return f"hecho::{normalized_key}"


def _infer_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (list, dict)):
        return "json"
    return "string"


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _strip_known_prefix(text: str, prefix: str) -> str:
    if text.casefold().startswith(prefix.casefold()):
        return text[len(prefix):].strip()
    return text


def _fact_to_question(fact: Any) -> str:
    text = _clean_text(fact)
    if not text:
        return ""
    if text.endswith("?"):
        return text
    lowered = text.replace("_", " ").strip()
    return f"¿Podés precisar {lowered}?"


def _source_strength(source_type: Any) -> int:
    normalized = _normalize_text(source_type)
    if "user_explicit" in normalized:
        return 4
    if "explicit" in normalized:
        return 3
    if "pipeline" in normalized:
        return 2
    return 1
