from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from app.services import conversation_observability_service
from legal_engine.orchestrator_schema import FinalOutput, RetrievalBundle, StrategyBundle


_QUICK_START_PREFIX = "Primer paso recomendado:"
_QUICK_START_SIMILARITY_THRESHOLD = 0.75

_NOISE_PATTERNS = (
    "fallback generico",
    "fallback",
    "generic",
    "missing handler",
    "modelo no aplicable",
    "internal_fallback",
    "no se encontro un patron",
    "razonamiento normativo generico",
)


class ResponsePostprocessor:
    def postprocess(
        self,
        *,
        request_id: str,
        normalized_input: dict[str, Any],
        pipeline_payload: dict[str, Any],
        retrieval: RetrievalBundle,
        strategy: StrategyBundle,
    ) -> FinalOutput:
        raw_response_text = self._build_response_text(pipeline_payload)
        response_text = self._sanitize_text(raw_response_text)
        response_text = self._prepend_quick_start(
            response_text, pipeline_payload.get("quick_start"),
        )
        response_text = self._apply_prudence(
            response_text=response_text,
            pipeline_payload=pipeline_payload,
            retrieval=retrieval,
            strategy=strategy,
        )

        api_payload = self._build_api_payload(
            request_id=request_id,
            response_text=response_text,
            pipeline_payload=pipeline_payload,
            retrieval=retrieval,
            strategy=strategy,
        )
        try:
            conversational = pipeline_payload.get("conversational") or {}
            conversation_memory = conversational.get("conversation_memory") or {}
            conversation_observability_service.record_observation(
                turn_input=normalized_input,
                response=api_payload,
                memory=conversation_memory if isinstance(conversation_memory, dict) else None,
            )
        except Exception:
            pass

        return FinalOutput(
            request_id=request_id,
            response_text=response_text,
            pipeline_version=self._safe_pipeline_version(api_payload.get("pipeline_version")),
            case_domain=str(api_payload.get("case_domain") or ""),
            action_slug=str(api_payload.get("action_slug") or ""),
            source_mode=str(api_payload.get("source_mode") or "unknown"),
            documents_considered=self._safe_int(api_payload.get("documents_considered")),
            strategy_mode=str(api_payload.get("strategy_mode") or ""),
            dominant_factor=str(api_payload.get("dominant_factor") or ""),
            blocking_factor=str(api_payload.get("blocking_factor") or ""),
            execution_readiness=str(api_payload.get("execution_readiness") or ""),
            confidence_score=api_payload.get("confidence_score"),
            confidence_label=str(api_payload.get("confidence_label") or "low"),
            fallback_used=bool(api_payload.get("fallback_used")),
            fallback_reason=str(api_payload.get("fallback_reason") or ""),
            sanitized_output=response_text != raw_response_text,
            warnings=list(api_payload.get("warnings") or []),
            api_payload=api_payload,
        )

    def _build_api_payload(
        self,
        *,
        request_id: str,
        response_text: str,
        pipeline_payload: dict[str, Any],
        retrieval: RetrievalBundle,
        strategy: StrategyBundle,
    ) -> dict[str, Any]:
        payload = dict(pipeline_payload)
        warnings = self._sanitize_warnings(
            [
                *list(payload.get("warnings") or []),
                *list(retrieval.warnings or []),
            ]
        )

        payload["request_id"] = request_id
        payload["response_text"] = response_text
        payload["pipeline_version"] = self._safe_pipeline_version(payload.get("pipeline_version"))
        payload["retrieval_bundle"] = retrieval.to_dict()
        payload["source_mode"] = retrieval.source_mode
        payload["documents_considered"] = retrieval.documents_considered
        payload["action_slug"] = self._canonical_action_slug(payload)
        payload["case_domain"] = self._canonical_case_domain(payload)
        payload["strategy_mode"] = self._canonical_strategy_mode(payload)
        payload["dominant_factor"] = self._canonical_dominant_factor(payload)
        payload["blocking_factor"] = self._canonical_blocking_factor(payload)
        payload["execution_readiness"] = self._canonical_execution_readiness(payload)
        payload["confidence_score"] = self._canonical_confidence_score(payload)
        payload["confidence_label"] = self._confidence_label(payload["confidence_score"])
        payload["confidence"] = payload["confidence_score"]
        payload["fallback_used"] = strategy.fallback_used
        payload["fallback_reason"] = strategy.fallback_reason
        payload["warnings"] = warnings
        return payload

    def _build_response_text(self, payload: dict[str, Any]) -> str:
        conversational = payload.get("conversational") or {}
        if conversational.get("should_ask_first"):
            guided_response = str(conversational.get("guided_response") or "").strip()
            if guided_response:
                return guided_response

        generated_document = str(payload.get("generated_document") or "").strip()
        if generated_document:
            return generated_document

        reasoning = payload.get("reasoning") or {}
        short_answer = str(reasoning.get("short_answer") or "").strip()
        applied_analysis = str(reasoning.get("applied_analysis") or "").strip()
        strategy = payload.get("case_strategy") or {}
        reactive_transition = str(strategy.get("reactive_transition") or "").strip()
        strategic_narrative = str(strategy.get("strategic_narrative") or "").strip()

        parts = [part for part in (reactive_transition, short_answer, applied_analysis, strategic_narrative) if part]
        return "\n\n".join(self._dedupe_lines(parts))

    def _prepend_quick_start(self, response_text: str, quick_start: str | None) -> str:
        """Insert quick_start at the beginning of response_text if not already present."""
        qs = str(quick_start or "").strip()
        if not qs:
            return response_text

        # Normalize: strip any repeated prefix occurrences, then add exactly one
        qs_body = self._normalize_quick_start_prefix(qs)
        qs = f"{_QUICK_START_PREFIX} {qs_body}".strip()
        # Ensure trailing period
        if qs and qs[-1] not in ".!?":
            qs += "."

        if not response_text.strip():
            return qs

        # Already present: starts with the prefix
        first_line = response_text.split("\n")[0].strip()
        if first_line.lower().startswith(_QUICK_START_PREFIX.lower()):
            return response_text

        # Semantic near-duplicate: first line is very similar to quick_start body
        norm_first = re.sub(r"\s+", " ", first_line.lower())
        norm_qs = re.sub(r"\s+", " ", qs_body.lower())
        if norm_qs and SequenceMatcher(a=norm_first, b=norm_qs).ratio() >= _QUICK_START_SIMILARITY_THRESHOLD:
            return response_text

        return f"{qs}\n\n{response_text}"

    @staticmethod
    def _normalize_quick_start_prefix(text: str) -> str:
        body = str(text or "").strip()
        prefix_pattern = re.compile(rf"^(?:{re.escape(_QUICK_START_PREFIX)}\s*)+", re.IGNORECASE)
        while True:
            normalized = prefix_pattern.sub("", body, count=1).strip()
            if normalized == body:
                break
            body = normalized
        return body

    def _apply_prudence(
        self,
        *,
        response_text: str,
        pipeline_payload: dict[str, Any],
        retrieval: RetrievalBundle,
        strategy: StrategyBundle,
    ) -> str:
        text = response_text
        evidence = pipeline_payload.get("evidence_reasoning_links") or {}
        confidence_score = float(evidence.get("confidence_score") or 0.0)

        if retrieval.source_mode in {"fallback", "legacy"} or strategy.fallback_used:
            text = self._append_once(
                text,
                "La orientacion recuperada tiene valor interno y prudente; no debe tratarse como cita verificable consolidada.",
            )
        if confidence_score and confidence_score < 0.45:
            text = self._append_once(
                text,
                "La evidencia disponible todavia es debil y conviene evitar afirmaciones concluyentes sin mayor soporte.",
            )
        if strategy.blocking_factor and strategy.blocking_factor != "none":
            text = self._append_once(
                text,
                f"Bloqueo procesal detectado: {strategy.blocking_factor}.",
            )
        return self._sanitize_text(text)

    def _sanitize_text(self, text: str) -> str:
        parts = [self._normalize_whitespace(part) for part in re.split(r"\n{2,}", str(text or "")) if str(part).strip()]
        clean = [part for part in self._dedupe_lines(parts) if not self._is_noise(part)]
        return "\n\n".join(clean).strip()

    def _sanitize_warnings(self, warnings: list[Any]) -> list[str]:
        clean: list[str] = []
        for item in warnings:
            text = self._normalize_whitespace(str(item or ""))
            if not text or self._is_noise(text):
                continue
            clean.append(text)
        return self._dedupe_lines(clean)

    def _canonical_case_domain(self, payload: dict[str, Any]) -> str:
        case_profile = payload.get("case_profile") or {}
        return str(case_profile.get("case_domain") or payload.get("case_domain") or "").strip()

    def _canonical_action_slug(self, payload: dict[str, Any]) -> str:
        classification = payload.get("classification") or {}
        case_structure = payload.get("case_structure") or {}
        return str(classification.get("action_slug") or case_structure.get("action_slug") or "").strip()

    def _canonical_strategy_mode(self, payload: dict[str, Any]) -> str:
        case_strategy = payload.get("case_strategy") or {}
        legal_decision = payload.get("legal_decision") or {}
        return str(case_strategy.get("strategy_mode") or legal_decision.get("strategic_posture") or "").strip()

    def _canonical_dominant_factor(self, payload: dict[str, Any]) -> str:
        legal_decision = payload.get("legal_decision") or {}
        return str(legal_decision.get("dominant_factor") or "").strip()

    def _canonical_blocking_factor(self, payload: dict[str, Any]) -> str:
        procedural_case_state = payload.get("procedural_case_state") or {}
        return str(procedural_case_state.get("blocking_factor") or "none").strip()

    def _canonical_execution_readiness(self, payload: dict[str, Any]) -> str:
        legal_decision = payload.get("legal_decision") or {}
        return str(legal_decision.get("execution_readiness") or "").strip()

    def _canonical_confidence_score(self, payload: dict[str, Any]) -> float | None:
        legal_decision = payload.get("legal_decision") or {}
        raw = legal_decision.get("confidence_score", payload.get("confidence"))
        try:
            return round(float(raw), 4)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_pipeline_version(value: Any) -> str:
        text = str(value or "").strip()
        return text or "unknown"

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _confidence_label(confidence_score: float | None) -> str:
        if confidence_score is None:
            return "low"
        if confidence_score >= 0.75:
            return "high"
        if confidence_score >= 0.5:
            return "medium"
        return "low"

    @staticmethod
    def _append_once(text: str, line: str) -> str:
        normalized_text = text.casefold()
        if line.casefold() in normalized_text:
            return text
        return f"{text}\n\n{line}".strip() if text else line

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _dedupe_lines(lines: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for line in lines:
            normalized = line.casefold().strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(line.strip())
        return result

    def _is_noise(self, text: str) -> bool:
        normalized = text.casefold()
        return any(pattern in normalized for pattern in _NOISE_PATTERNS)
