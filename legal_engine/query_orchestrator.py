from __future__ import annotations

import re
import time
from typing import Any
from uuid import uuid4

from app.services.orchestrator_config_service import load_orchestrator_config
from legal_engine.ailex_pipeline import AilexPipeline, PipelineRequest
from legal_engine.orchestrator_config import OrchestratorAdaptiveConfig
from legal_engine.orchestrator_schema import (
    NormalizedOrchestratorInput,
    OrchestratorClassification,
    OrchestratorDecision,
    OrchestratorResult,
    OrchestratorTimings,
    RetrievalBundle,
    StrategyBundle,
)
from legal_engine.response_postprocessor import ResponsePostprocessor


PIPELINE_VERSION = "beta-orchestrator-v1"

_ACTION_VERBS = (
    "demanda",
    "demandar",
    "iniciar",
    "presentar",
    "reclamar",
    "promover",
    "ejecutar",
    "interponer",
)
_BLOCKING_PHRASES = (
    "no me notificaron",
    "no puedo avanzar",
    "esta frenado",
    "está frenado",
    "bloqueado",
    "paralizado",
)
_INFORMATIONAL_PHRASES = (
    "que es",
    "qué es",
    "como funciona",
    "cómo funciona",
    "informacion",
    "información",
    "explicame",
    "explícame",
    "significa",
    "puedo",
)
_PROCEDURAL_KEYWORDS = (
    "demanda",
    "iniciar",
    "presentar",
    "reclamar",
    "notific",
    "expediente",
    "traslado",
    "plazo",
    "audiencia",
    "apel",
    "medida cautelar",
    "ejecutar",
    "incidente",
    "divorcio",
    "alimentos",
)
_LEGAL_ENTITY_PATTERNS = (
    re.compile(r"\bccyc\b", re.IGNORECASE),
    re.compile(r"\bcpcc\b", re.IGNORECASE),
    re.compile(r"\bley\b", re.IGNORECASE),
    re.compile(r"\bc[óo]digo\b", re.IGNORECASE),
    re.compile(r"\bart(?:[íi]culo)?s?\.?\s*\d+[a-z]?\b", re.IGNORECASE),
)
_ARTICLE_REFERENCE_PATTERNS = (
    re.compile(r"\bart(?:[íi]culo)?s?\.?\s*\d+[a-z]?\b", re.IGNORECASE),
    re.compile(r"\barts?\.?\s*\d+[a-z]?\b", re.IGNORECASE),
    re.compile(r"\bley\s+\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\bccyc\b", re.IGNORECASE),
    re.compile(r"\bcpcc\b", re.IGNORECASE),
)
_CONJUNCTION_PATTERNS = (
    re.compile(r"\by\b", re.IGNORECASE),
    re.compile(r"\bo\b", re.IGNORECASE),
    re.compile(r"\bpero\b", re.IGNORECASE),
)
_AMBIGUOUS_BRANCH_PATTERNS = (
    re.compile(r"\bo\b", re.IGNORECASE),
    re.compile(r"\bpero\b", re.IGNORECASE),
)
_SAFE_LIGHT_MODE_PLACEHOLDERS = {
    "case_theory": {"status": "skipped_light_mode"},
    "case_evaluation": {"status": "skipped_light_mode"},
    "conflict_evidence": {"status": "skipped_light_mode"},
}
_DOMAIN_KEYWORDS = {
    "alimentos": ("alimentos", "cuota alimentaria"),
    "divorcio": ("divorcio",),
    "familia": ("filiacion", "cuidado personal", "regimen de comunicacion", "régimen de comunicación"),
}


class QueryOrchestratorError(RuntimeError):
    def __init__(self, request_id: str, message: str) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.message = message


class QueryOrchestrator:
    def __init__(
        self,
        *,
        pipeline: Any | None = None,
        postprocessor: ResponsePostprocessor | None = None,
    ) -> None:
        self.pipeline = pipeline or AilexPipeline()
        self.postprocessor = postprocessor or ResponsePostprocessor()

    def run(
        self,
        query: str,
        jurisdiction: str | None = None,
        forum: str | None = None,
        top_k: int = 5,
        document_mode: str | None = None,
        document_kind: str | None = None,
        facts: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        db: Any | None = None,
    ) -> OrchestratorResult:
        total_start = time.perf_counter()
        timings = OrchestratorTimings()

        normalized_start = time.perf_counter()
        normalized = self._normalize_input(
            query=query,
            jurisdiction=jurisdiction,
            forum=forum,
            top_k=top_k,
            document_mode=document_mode,
            document_kind=document_kind,
            facts=facts,
            metadata=metadata,
        )
        timings.normalization_ms = self._elapsed_ms(normalized_start)

        decision = self._decide(normalized=normalized, db=db)
        pipeline_config = self._build_pipeline_config(decision)

        pipeline_start = time.perf_counter()
        try:
            pipeline_result = self._run_pipeline(
                normalized=normalized,
                db=db,
                config=pipeline_config,
            )
        except Exception as exc:
            raise QueryOrchestratorError(normalized.request_id, "Fallo controlado durante la orquestacion juridica.") from exc
        timings.pipeline_ms = self._elapsed_ms(pipeline_start)

        base_payload = pipeline_result.to_dict() if hasattr(pipeline_result, "to_dict") else dict(pipeline_result or {})
        self._apply_safe_light_mode(base_payload, decision)
        orchestration_metadata = self._build_result_metadata(
            decision=decision,
            normalized=normalized,
            pipeline_config=pipeline_config,
            db=db,
        )
        payload = {
            **base_payload,
            "pipeline_version": PIPELINE_VERSION,
            "orchestrator_decision": decision.to_dict(),
            "orchestrator_metadata": orchestration_metadata,
        }
        payload.setdefault("case_strategy", {})
        payload.setdefault("legal_decision", {})
        payload["case_strategy"].setdefault("strategy_mode", decision.strategy_mode)
        payload["legal_decision"].setdefault("strategic_posture", decision.strategy_mode)

        classification_start = time.perf_counter()
        classification = self._build_classification(payload, normalized)
        timings.classification_ms = self._elapsed_ms(classification_start)

        retrieval_start = time.perf_counter()
        retrieval = self._build_retrieval_bundle(payload, decision)
        timings.retrieval_ms = self._elapsed_ms(retrieval_start)

        strategy_start = time.perf_counter()
        strategy = self._build_strategy_bundle(payload, retrieval, decision)
        timings.strategy_ms = self._elapsed_ms(strategy_start)

        postprocess_start = time.perf_counter()
        final_output = self.postprocessor.postprocess(
            request_id=normalized.request_id,
            normalized_input=normalized.to_dict(),
            pipeline_payload=payload,
            retrieval=retrieval,
            strategy=strategy,
        )
        timings.postprocess_ms = self._elapsed_ms(postprocess_start)

        final_output.api_payload.setdefault("orchestrator_decision", decision.to_dict())
        final_output.api_payload.setdefault("orchestrator_metadata", orchestration_metadata)

        final_assembly_start = time.perf_counter()
        result = OrchestratorResult(
            pipeline_version=PIPELINE_VERSION,
            normalized_input=normalized,
            decision=decision,
            classification=classification,
            retrieval=retrieval,
            strategy=strategy,
            final_output=final_output,
            timings=timings,
            pipeline_payload=payload,
            metadata=orchestration_metadata,
        )
        timings.final_assembly_ms = self._elapsed_ms(final_assembly_start)
        timings.total_ms = self._elapsed_ms(total_start)
        return result

    def _normalize_input(
        self,
        *,
        query: str,
        jurisdiction: str | None,
        forum: str | None,
        top_k: int,
        document_mode: str | None,
        document_kind: str | None,
        facts: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> NormalizedOrchestratorInput:
        normalized_query = " ".join(str(query or "").split()).strip() or "consulta juridica"
        normalized_metadata = dict(metadata or {})
        request_id = str(normalized_metadata.get("request_id") or normalized_metadata.get("requestId") or uuid4())
        normalized_metadata["request_id"] = request_id
        return NormalizedOrchestratorInput(
            request_id=request_id,
            query=normalized_query,
            jurisdiction=self._normalize_optional_text(jurisdiction),
            forum=self._normalize_optional_text(forum),
            top_k=max(1, min(int(top_k or 5), 20)),
            document_mode=self._normalize_optional_text(document_mode),
            document_kind=self._normalize_optional_text(document_kind),
            facts=dict(facts or {}),
            metadata=normalized_metadata,
        )

    def _decide(
        self,
        *,
        normalized: NormalizedOrchestratorInput,
        db: Any | None,
    ) -> OrchestratorDecision:
        adaptive_config = self._load_adaptive_config()
        query_text = normalized.query.casefold()
        has_article_reference = self._has_article_reference(normalized.query)
        complexity = self._estimate_complexity(query_text, has_article_reference=has_article_reference)
        is_procedural = self._is_procedural_query(query_text)
        has_action_signal = self._has_action_signal(query_text)
        inferred_domain = self._infer_query_domain(query_text)
        strategy_scores = self._score_strategy(query_text, adaptive_config=adaptive_config)
        strategy_mode = max(strategy_scores, key=strategy_scores.get)
        is_ambiguous = self._detect_ambiguity(
            strategy_scores,
            query_text=query_text,
            ambiguity_threshold=adaptive_config.ambiguity_threshold,
        )
        is_informational = self._is_informational_query(
            query_text,
            is_procedural=is_procedural,
            has_action_signal=has_action_signal,
        )

        if has_article_reference:
            retrieval_mode = "hybrid"
        elif inferred_domain and inferred_domain in adaptive_config.prefer_hybrid_domains and db is not None:
            retrieval_mode = "hybrid"
        elif db is not None:
            retrieval_mode = "online"
        else:
            retrieval_mode = "offline"

        pipeline_mode = "full"
        if is_informational and not is_procedural and complexity == "low" and not is_ambiguous:
            pipeline_mode = "light"
        if inferred_domain and inferred_domain in adaptive_config.force_full_pipeline_domains:
            pipeline_mode = "full"

        use_jurisprudence = bool(is_procedural or complexity == "high" or has_action_signal)
        use_argument_generation = pipeline_mode != "light"
        decision_confidence = self._score_decision_confidence(
            is_procedural=is_procedural,
            has_action_signal=has_action_signal,
            has_article_reference=has_article_reference,
            complexity=complexity,
            strategy_scores=strategy_scores,
            is_ambiguous=is_ambiguous,
        )

        return OrchestratorDecision(
            retrieval_mode=retrieval_mode,
            strategy_mode=strategy_mode,
            pipeline_mode=pipeline_mode,
            use_jurisprudence=use_jurisprudence,
            use_argument_generation=use_argument_generation,
            decision_confidence=decision_confidence,
        )

    def _score_strategy(
        self,
        query_text: str,
        *,
        adaptive_config: OrchestratorAdaptiveConfig | None = None,
    ) -> dict[str, float]:
        scores = {
            "aggressive": 0.1,
            "cautious": 0.1,
            "conservative": 0.1,
        }

        action_hits = sum(1 for token in _ACTION_VERBS if token in query_text)
        blocking_hits = sum(1 for token in _BLOCKING_PHRASES if token in query_text)
        informational_hits = sum(1 for token in _INFORMATIONAL_PHRASES if token in query_text)

        if "puedo" in query_text and action_hits > 0:
            informational_hits = max(0, informational_hits - 1)

        scores["aggressive"] += action_hits * 0.4
        scores["cautious"] += blocking_hits * 0.5
        scores["conservative"] += informational_hits * 0.3

        if "?" in query_text:
            scores["conservative"] += 0.1
        if blocking_hits and action_hits:
            scores["cautious"] += 0.2
        if action_hits and not informational_hits:
            scores["aggressive"] += 0.1

        strategy_weights = dict((adaptive_config or OrchestratorAdaptiveConfig.default_config()).strategy_weights)
        for key in scores:
            scores[key] *= float(strategy_weights.get(key, 1.0) or 1.0)

        total = sum(scores.values()) or 1.0
        return {
            key: round(value / total, 4)
            for key, value in scores.items()
        }

    def _build_pipeline_config(self, decision: OrchestratorDecision) -> dict[str, Any]:
        return {
            "retrieval_mode": decision.retrieval_mode,
            "strategy_mode": decision.strategy_mode,
            "skip_jurisprudence": not decision.use_jurisprudence,
            "skip_argument_generation": not decision.use_argument_generation,
            "light_mode": decision.pipeline_mode == "light",
        }

    def _run_pipeline(
        self,
        *,
        normalized: NormalizedOrchestratorInput,
        db: Any | None,
        config: dict[str, Any],
    ) -> Any:
        if hasattr(self.pipeline, "run_request") and callable(self.pipeline.run_request):
            request = PipelineRequest(
                query=normalized.query,
                jurisdiction=normalized.jurisdiction,
                forum=normalized.forum,
                top_k=normalized.top_k,
                document_mode=normalized.document_mode,
                document_kind=normalized.document_kind,
                facts=normalized.facts,
                metadata=normalized.metadata,
            )
            return self.pipeline.run_request(request, db=db, config=config)

        return self.pipeline.run(
            query=normalized.query,
            jurisdiction=normalized.jurisdiction,
            forum=normalized.forum,
            top_k=normalized.top_k,
            document_mode=normalized.document_mode,
            document_kind=normalized.document_kind,
            facts=normalized.facts,
            metadata=normalized.metadata,
            db=db,
            config=config,
        )

    def _apply_safe_light_mode(self, payload: dict[str, Any], decision: OrchestratorDecision) -> None:
        if decision.pipeline_mode != "light":
            return
        for key, placeholder in _SAFE_LIGHT_MODE_PLACEHOLDERS.items():
            value = payload.get(key)
            if not isinstance(value, dict) or not value:
                payload[key] = dict(placeholder)

    def _build_classification(
        self,
        payload: dict[str, Any],
        normalized: NormalizedOrchestratorInput,
    ) -> OrchestratorClassification:
        raw = dict(payload.get("classification") or {})
        case_profile = payload.get("case_profile") or {}
        return OrchestratorClassification(
            action_slug=str(raw.get("action_slug") or payload.get("action_slug") or "").strip(),
            action_label=str(raw.get("action_label") or "").strip(),
            case_domain=str(case_profile.get("case_domain") or payload.get("case_domain") or "").strip(),
            jurisdiction=str(raw.get("jurisdiction") or payload.get("jurisdiction") or normalized.jurisdiction or "").strip() or None,
            forum=str(raw.get("forum") or payload.get("forum") or normalized.forum or "").strip() or None,
            raw=raw,
        )

    def _build_retrieval_bundle(
        self,
        payload: dict[str, Any],
        decision: OrchestratorDecision,
    ) -> RetrievalBundle:
        retrieved_items = list(payload.get("retrieved_items") or [])
        context = payload.get("context") or {}
        normative_reasoning = payload.get("normative_reasoning") or {}
        jurisprudence_analysis = payload.get("jurisprudence_analysis") or {}

        normative_references = self._dedupe_dicts(
            [
                *[
                    {
                        "source": item.get("source_id") or item.get("source"),
                        "article": item.get("article"),
                        "score": item.get("score"),
                    }
                    for item in (context.get("applicable_norms") or [])
                    if isinstance(item, dict)
                ],
                *[
                    {
                        "source": item.get("source") or item.get("source_id"),
                        "article": item.get("article"),
                    }
                    for item in (normative_reasoning.get("applied_rules") or [])
                    if isinstance(item, dict)
                ],
            ]
        )
        jurisprudence_references = self._dedupe_dicts(
            [
                item
                for item in (jurisprudence_analysis.get("jurisprudence_highlights") or [])
                if isinstance(item, dict)
            ]
        )
        top_scores = [
            float(item.get("score") or 0.0)
            for item in retrieved_items
            if isinstance(item, dict) and item.get("score") is not None
        ]
        sources_used = self._dedupe_strings(
            [
                *[
                    str(item.get("source_id") or item.get("source") or "").strip()
                    for item in retrieved_items
                    if isinstance(item, dict)
                ],
                *[str(item).strip() for item in (context.get("source_ids_used") or []) if str(item).strip()],
            ]
        )
        warnings = self._dedupe_strings(
            [
                *[str(item).strip() for item in (context.get("warnings") or []) if str(item).strip()],
                *[str(item).strip() for item in (jurisprudence_analysis.get("warnings") or []) if str(item).strip()],
            ]
        )

        return RetrievalBundle(
            source_mode=decision.retrieval_mode,
            sources_used=sources_used,
            normative_references=normative_references,
            jurisprudence_references=jurisprudence_references,
            documents_considered=len([item for item in retrieved_items if isinstance(item, dict)]),
            top_retrieval_scores=top_scores[:5],
            warnings=warnings,
        )

    def _build_strategy_bundle(
        self,
        payload: dict[str, Any],
        retrieval: RetrievalBundle,
        decision: OrchestratorDecision,
    ) -> StrategyBundle:
        legal_decision = payload.get("legal_decision") or {}
        procedural_case_state = payload.get("procedural_case_state") or {}
        confidence_score = self._safe_float(legal_decision.get("confidence_score", payload.get("confidence")))
        fallback_used, fallback_reason = self._resolve_fallback(payload, retrieval)
        return StrategyBundle(
            strategy_mode=decision.strategy_mode,
            dominant_factor=str(legal_decision.get("dominant_factor") or "").strip(),
            blocking_factor=str(procedural_case_state.get("blocking_factor") or "none").strip(),
            execution_readiness=str(legal_decision.get("execution_readiness") or "").strip(),
            confidence_score=confidence_score,
            confidence_label=self._confidence_label(confidence_score),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            raw={
                "legal_decision": legal_decision,
                "procedural_case_state": procedural_case_state,
                "orchestrator_decision": decision.to_dict(),
            },
        )

    def _build_result_metadata(
        self,
        *,
        decision: OrchestratorDecision,
        normalized: NormalizedOrchestratorInput,
        pipeline_config: dict[str, Any],
        db: Any | None,
    ) -> dict[str, Any]:
        return {
            "request_id": normalized.request_id,
            "pipeline_version": PIPELINE_VERSION,
            "query_length": len(normalized.query),
            "has_db": db is not None,
            "pipeline_config": dict(pipeline_config),
            "decision": decision.to_dict(),
        }

    def _resolve_fallback(self, payload: dict[str, Any], retrieval: RetrievalBundle) -> tuple[bool, str]:
        jurisprudence_analysis = payload.get("jurisprudence_analysis") or {}
        model_match = payload.get("model_match") or {}
        classification = payload.get("classification") or {}
        action_slug = str(classification.get("action_slug") or "").strip().lower()
        source_quality = str(jurisprudence_analysis.get("source_quality") or "").strip().lower()
        model_status = str(model_match.get("status") or model_match.get("selection_status") or "").strip().lower()
        warnings = " ".join(str(item).lower() for item in (payload.get("warnings") or []))
        model_match_warnings = " ".join(str(item).lower() for item in (model_match.get("warnings") or []))

        if retrieval.source_mode == "fallback":
            return True, "Se recurrió a orientación interna por falta de soporte jurisprudencial verificable."
        if jurisprudence_analysis.get("used_internal_fallback") or jurisprudence_analysis.get("fallback_used"):
            return True, "Se recurrió a orientación interna por falta de soporte jurisprudencial verificable."
        if source_quality == "fallback":
            return True, "Se recurrió a orientación interna por falta de soporte jurisprudencial verificable."
        if model_match.get("fallback_used") or model_match.get("used_fallback") or model_match.get("selection_fallback"):
            return True, "Se aplicó fallback de selección de modelo."
        if model_status in {"fallback", "not_found", "unmatched", "no_match"}:
            return True, "Se aplicó fallback de selección de modelo."
        if model_match.get("selected") is False or model_match.get("matched") is False:
            return True, "Se aplicó fallback de selección de modelo."
        if action_slug in {"", "generic"}:
            return True, "La acción no quedó clasificada con precisión suficiente."
        if "no se encontro un modelo aplicable" in warnings or "no se encontro un modelo aplicable" in model_match_warnings:
            return True, "Se aplicó fallback de selección de modelo."
        return False, ""

    def _estimate_complexity(self, query_text: str, *, has_article_reference: bool) -> str:
        token_count = len([token for token in re.split(r"\W+", query_text) if token])
        procedural_hits = sum(1 for token in _PROCEDURAL_KEYWORDS if token in query_text)
        article_hits = 1 if has_article_reference else 0
        legal_entity_hits = sum(1 for pattern in _LEGAL_ENTITY_PATTERNS if pattern.search(query_text))
        conjunction_hits = sum(1 for pattern in _CONJUNCTION_PATTERNS if pattern.search(query_text))

        if procedural_hits >= 2:
            return "high"
        if article_hits >= 1 and procedural_hits >= 1:
            return "high"
        if legal_entity_hits >= 2 and conjunction_hits >= 1:
            return "high"
        if procedural_hits == 1 or token_count >= 8:
            return "medium"
        return "low"

    def _detect_ambiguity(
        self,
        strategy_scores: dict[str, float],
        *,
        query_text: str = "",
        ambiguity_threshold: float = 0.12,
    ) -> bool:
        action_hits = sum(1 for token in _ACTION_VERBS if token in query_text)
        token_count = len([token for token in re.split(r"\W+", query_text) if token])

        if action_hits >= 2:
            return True

        ordered_scores = sorted(strategy_scores.values(), reverse=True)
        if len(ordered_scores) >= 2:
            margin = ordered_scores[0] - ordered_scores[1]
            if margin < float(ambiguity_threshold or 0.12) and token_count > 5:
                return True

        has_disjunctive_branch = any(
            pattern.search(query_text)
            for pattern in _AMBIGUOUS_BRANCH_PATTERNS
        )
        return has_disjunctive_branch and token_count > 5

    def _score_decision_confidence(
        self,
        *,
        is_procedural: bool,
        has_action_signal: bool,
        has_article_reference: bool,
        complexity: str,
        strategy_scores: dict[str, float],
        is_ambiguous: bool,
    ) -> float:
        ordered_scores = sorted(strategy_scores.values(), reverse=True)
        lead_margin = ordered_scores[0] - ordered_scores[1]

        if is_procedural and has_action_signal:
            confidence = 0.86
        elif lead_margin >= 0.2 or has_article_reference or complexity == "high":
            confidence = 0.64
        else:
            confidence = 0.34

        if is_ambiguous:
            confidence -= 0.05 if (is_procedural and has_action_signal) else 0.2
        if complexity == "high" and confidence < 0.8:
            confidence += 0.05
        return round(max(0.0, min(confidence, 0.95)), 4)

    def _has_article_reference(self, query: str) -> bool:
        return any(pattern.search(query or "") for pattern in _ARTICLE_REFERENCE_PATTERNS)

    def _is_procedural_query(self, query_text: str) -> bool:
        return any(token in query_text for token in _PROCEDURAL_KEYWORDS)

    def _has_action_signal(self, query_text: str) -> bool:
        return any(token in query_text for token in _ACTION_VERBS)

    def _is_informational_query(
        self,
        query_text: str,
        *,
        is_procedural: bool,
        has_action_signal: bool,
    ) -> bool:
        if is_procedural or has_action_signal:
            return False
        return any(token in query_text for token in _INFORMATIONAL_PHRASES)

    def _load_adaptive_config(self) -> OrchestratorAdaptiveConfig:
        try:
            return load_orchestrator_config()
        except Exception:
            return OrchestratorAdaptiveConfig.default_config()

    def _infer_query_domain(self, query_text: str) -> str | None:
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            if any(keyword in query_text for keyword in keywords):
                return domain
        return None

    @staticmethod
    def _normalize_optional_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _dedupe_strings(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            normalized = item.casefold()
            if not item or normalized in seen:
                continue
            seen.add(normalized)
            result.append(item)
        return result

    @staticmethod
    def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[tuple[str, str], ...]] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            cleaned = {str(key): value for key, value in item.items() if value not in (None, "", [], {})}
            signature = tuple(sorted((key, str(value)) for key, value in cleaned.items()))
            if not cleaned or signature in seen:
                continue
            seen.add(signature)
            result.append(cleaned)
        return result

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.perf_counter() - start) * 1000)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return round(float(value), 4)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _confidence_label(confidence_score: float | None) -> str:
        if confidence_score is None:
            return "low"
        if confidence_score >= 0.75:
            return "high"
        if confidence_score >= 0.5:
            return "medium"
        return "low"
