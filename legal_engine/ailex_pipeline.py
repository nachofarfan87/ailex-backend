# legal_engine/ailex_pipeline.py

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.services.beta_observability_helpers import (
    detect_interdomain_conflict,
    extract_citation_validation_status,
    extract_hallucination_guard_status,
    extract_secondary_domains,
    extract_selected_model_fields,
)
from app.services.beta_observability_service import update_beta_observability_context
from app.services import output_refinement_service
from app.services import output_mode_service
from legal_engine import (
    ActionClassifier,
    ArgumentGenerator,
    CaseTheoryEngine,
    CaseStructurer,
    CitationValidator,
    ContextBuilder,
    HallucinationGuard,
    LegalReasoner,
    LegalDecisionEngine,
    LegalRetrieverOrchestrator,
    NormativeReasoner,
    ProceduralCaseStateBuilder,
    ProceduralStrategy,
    ProceduralTimelineBuilder,
    QuestionEngine,
)
from legal_engine.case_evaluation_engine import CaseEvaluationEngine
from legal_engine.case_profile_builder import build_case_profile, align_classification_with_domain
from legal_engine.case_strategy_builder import build_case_strategy, sanitize_strategy_output, dedupe_domains
from legal_engine.conflict_evidence_engine import ConflictEvidenceEngine
from legal_engine.evidence_reasoning_linker import EvidenceReasoningLinker
from legal_engine.jurisprudence_engine import JurisprudenceEngine
from legal_engine.model_library import ModelLibrary
from legal_engine.tag_inference import collect_tag_signals, infer_model_tags
from legal_engine.style_blueprint import normalize_style_blueprint


@dataclass
class PipelineRequest:
    query: str
    jurisdiction: Optional[str] = None
    forum: Optional[str] = None
    top_k: int = 5
    document_mode: Optional[str] = None
    document_kind: Optional[str] = None
    facts: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    query: str
    jurisdiction: Optional[str]
    forum: Optional[str]
    case_domain: Optional[str] = None
    case_domains: List[str] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    retrieved_items: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    classification: Dict[str, Any] = field(default_factory=dict)
    case_structure: Dict[str, Any] = field(default_factory=dict)
    reasoning: Dict[str, Any] = field(default_factory=dict)
    normative_reasoning: Dict[str, Any] = field(default_factory=dict)
    citation_validation: Dict[str, Any] = field(default_factory=dict)
    hallucination_guard: Dict[str, Any] = field(default_factory=dict)
    procedural_strategy: Dict[str, Any] = field(default_factory=dict)
    question_engine_result: Dict[str, Any] = field(default_factory=dict)
    case_theory: Dict[str, Any] = field(default_factory=dict)
    case_evaluation: Dict[str, Any] = field(default_factory=dict)
    conflict_evidence: Dict[str, Any] = field(default_factory=dict)
    evidence_reasoning_links: Dict[str, Any] = field(default_factory=dict)
    jurisprudence_analysis: Dict[str, Any] = field(default_factory=dict)
    procedural_timeline: Dict[str, Any] = field(default_factory=dict)
    procedural_case_state: Dict[str, Any] = field(default_factory=dict)
    legal_decision: Dict[str, Any] = field(default_factory=dict)
    model_match: Dict[str, Any] = field(default_factory=dict)
    case_profile: Dict[str, Any] = field(default_factory=dict)
    case_strategy: Dict[str, Any] = field(default_factory=dict)
    legal_strategy: Dict[str, Any] = field(default_factory=dict)
    output_modes: Dict[str, Any] = field(default_factory=dict)
    conversational: Dict[str, Any] = field(default_factory=dict)
    conversational_response: Dict[str, Any] = field(default_factory=dict)
    generated_document: Optional[str] = None
    quick_start: Optional[str] = None

    warnings: List[str] = field(default_factory=list)
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(asdict(self))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=lambda item: str(item))]
    return value


class AilexPipeline:
    """
    Orquesta el pipeline jurídico completo:

    query
      -> action_classifier
      -> case_structurer
      -> retriever
      -> context builder
      -> legal reasoner
      -> normative reasoner
      -> citation validator
      -> hallucination guard
      -> procedural strategy
      -> argument generator (opcional)
    """

    _ONLINE_NORMATIVE_CHUNK_LIMIT = 4000
    _NORMATIVE_HIERARCHY_ALIASES = {
        "normativa",
        "normativo",
        "normative",
        "norma",
    }

    def __init__(
        self,
        retriever: Optional[Any] = None,
        context_builder: Optional[Any] = None,
        legal_reasoner: Optional[Any] = None,
        citation_validator: Optional[Any] = None,
        hallucination_guard: Optional[Any] = None,
        procedural_strategy: Optional[Any] = None,
        question_engine: Optional[Any] = None,
        case_theory_engine: Optional[Any] = None,
        case_evaluation_engine: Optional[Any] = None,
        conflict_evidence_engine: Optional[Any] = None,
        evidence_reasoning_linker: Optional[Any] = None,
        jurisprudence_engine: Optional[Any] = None,
        legal_decision_engine: Optional[Any] = None,
        procedural_timeline_builder: Optional[Any] = None,
        procedural_case_state_builder: Optional[Any] = None,
        argument_generator: Optional[Any] = None,
        action_classifier: Optional[Any] = None,
        case_structurer: Optional[Any] = None,
        normative_reasoner: Optional[Any] = None,
        model_library: Optional[ModelLibrary] = None,
    ) -> None:
        self.retriever = retriever or LegalRetrieverOrchestrator()
        self.context_builder = context_builder or ContextBuilder()
        self.legal_reasoner = legal_reasoner or LegalReasoner()
        self.citation_validator = citation_validator or CitationValidator()
        self.hallucination_guard = hallucination_guard or HallucinationGuard()
        self.procedural_strategy = procedural_strategy or ProceduralStrategy()
        self.question_engine = question_engine or QuestionEngine()
        self.case_theory_engine = case_theory_engine or CaseTheoryEngine()
        self.case_evaluation_engine = case_evaluation_engine or CaseEvaluationEngine()
        self.conflict_evidence_engine = conflict_evidence_engine or ConflictEvidenceEngine()
        self.evidence_reasoning_linker = evidence_reasoning_linker or EvidenceReasoningLinker()
        self.jurisprudence_engine = jurisprudence_engine or JurisprudenceEngine()
        self.legal_decision_engine = legal_decision_engine or LegalDecisionEngine()
        self.procedural_timeline_builder = procedural_timeline_builder or ProceduralTimelineBuilder()
        self.procedural_case_state_builder = procedural_case_state_builder or ProceduralCaseStateBuilder()
        self.argument_generator = argument_generator or ArgumentGenerator()
        self.action_classifier = action_classifier or ActionClassifier()
        self.case_structurer = case_structurer or CaseStructurer()
        self.normative_reasoner = normative_reasoner or NormativeReasoner()
        default_model_index = Path(__file__).resolve().parent.parent / "data" / "model_library" / "index.json"
        self.model_library = model_library or ModelLibrary(default_model_index)
        self._logger = logging.getLogger(__name__)

    def run(
        self,
        query: str,
        jurisdiction: Optional[str] = None,
        forum: Optional[str] = None,
        top_k: int = 5,
        document_mode: Optional[str] = None,
        document_kind: Optional[str] = None,
        facts: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        db: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
        observability_context: Optional[Any] = None,
    ) -> PipelineResult:
        request = PipelineRequest(
            query=query,
            jurisdiction=jurisdiction,
            forum=forum,
            top_k=top_k,
            document_mode=document_mode,
            document_kind=document_kind,
            facts=facts or {},
            metadata=metadata or {},
        )
        return self.run_request(
            request,
            db=db,
            config=config,
            observability_context=observability_context,
        )

    def run_request(
        self,
        request: PipelineRequest,
        db: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
        observability_context: Optional[Any] = None,
    ) -> PipelineResult:
        warnings: List[str] = []
        pipeline_config = self._normalize_pipeline_config(config)

        # 1. Classification
        classification_started_at = time.perf_counter()
        classification = self._run_classification(request)
        self._record_observability_stage(observability_context, "pipeline_classification_ms", classification_started_at)
        self._update_observability(
            observability_context,
            query=request.query,
            normalized_query=request.query,
            jurisdiction=request.jurisdiction,
            forum=request.forum,
            original_action_slug=str(classification.get("action_slug") or "").strip() or None,
        )

        # 1b. Enrich classification with expediente context when available
        classification = self._enrich_classification_from_expediente(
            classification, request.metadata or {},
        )

        resolved_jurisdiction = request.jurisdiction or classification.get("jurisdiction") or "jujuy"
        # When classification identified an action, its forum is authoritative
        # (comes from taxonomy). Only fall back to request.forum if no action matched.
        resolved_forum = classification.get("forum") or request.forum

        # 2. Case structure
        case_structure = self._run_case_structurer(
            request=request,
            classification=classification,
            jurisdiction=resolved_jurisdiction,
            forum=resolved_forum,
        )

        # 3. Retrieval
        retrieved_items = self._run_retrieval(
            request,
            classification=classification,
            jurisdiction=resolved_jurisdiction,
            forum=resolved_forum,
            db=db,
            config=pipeline_config,
        )

        # 4. Context
        context = self._run_context_builder(
            request,
            retrieved_items,
            jurisdiction=resolved_jurisdiction,
            forum=resolved_forum,
        )

        # 5. Legal reasoner (existing)
        reasoning = self._run_reasoner(
            request,
            context,
            classification=classification,
            jurisdiction=resolved_jurisdiction,
            forum=resolved_forum,
        )

        # 6. Normative reasoner (new)
        normative_reasoning = self._run_normative_reasoner(
            request=request,
            classification=classification,
            case_structure=case_structure,
            retrieved_items=retrieved_items,
        )

        initial_case_profile_started_at = time.perf_counter()
        initial_case_profile = build_case_profile(
            query=request.query,
            classification=classification,
            case_theory={},
            conflict={},
            normative_reasoning=normative_reasoning,
            procedural_plan={},
            facts=request.facts or {},
        )
        initial_case_domain = str(initial_case_profile.get("case_domain") or "").strip() or None
        self._record_observability_stage(observability_context, "pipeline_initial_case_profile_ms", initial_case_profile_started_at)
        self._update_observability(
            observability_context,
            original_case_domain=initial_case_domain,
            top_level_domains_detected=[
                str(item).strip()
                for item in (initial_case_profile.get("case_domains") or [])
                if str(item).strip()
            ],
        )

        # 6b. Early slug alignment — ensures model selection (step 16) uses
        #     the corrected action_slug when explicit user intent forced a
        #     domain override (e.g. "quiero divorciarme" but classifier picked
        #     alimentos_hijos).  Must run BEFORE select_model().
        alignment_started_at = time.perf_counter()
        classification = align_classification_with_domain(
            classification=classification,
            case_domain=initial_case_domain,
            query=request.query,
        )
        self._record_observability_stage(observability_context, "pipeline_alignment_ms", alignment_started_at)
        self._update_observability(
            observability_context,
            final_action_slug=str(classification.get("action_slug") or "").strip() or None,
            slug_aligned_to_domain=bool(classification.get("_original_action_slug")),
        )

        # 7. Citation validation
        citation_validation = self._run_citation_validation(context, reasoning)
        self._update_observability(
            observability_context,
            citation_validation_status=extract_citation_validation_status(citation_validation),
        )

        # 8. Hallucination guard
        hallucination_guard = self._run_hallucination_guard(
            request=request,
            context=context,
            reasoning=reasoning,
            citation_validation=citation_validation,
            jurisdiction=resolved_jurisdiction,
            forum=resolved_forum,
        )
        hallucination_status, hallucination_flags = extract_hallucination_guard_status(hallucination_guard)
        self._update_observability(
            observability_context,
            hallucination_guard_status=hallucination_status,
            hallucination_flags=hallucination_flags,
        )

        # 9. Procedural strategy
        procedural_strategy = self._run_procedural_strategy(
            request=request,
            context=context,
            reasoning=reasoning,
            hallucination_guard=hallucination_guard,
            classification=classification,
            jurisdiction=resolved_jurisdiction,
            forum=resolved_forum,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            case_domain=initial_case_domain,
        )

        # 10. Question engine
        question_engine_result = self._run_question_engine(
            request=request,
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            case_domain=initial_case_domain,
        )

        # 11. Case theory engine
        case_theory = {}
        if not pipeline_config["light_mode"]:
            case_theory = self._run_case_theory_engine(
                request=request,
                classification=classification,
                case_structure=case_structure,
                normative_reasoning=normative_reasoning,
                procedural_strategy=procedural_strategy,
                question_engine_result=question_engine_result,
                case_domain=initial_case_domain,
            )

        # 12. Case evaluation engine
        case_evaluation = {}
        if not pipeline_config["light_mode"]:
            case_evaluation = self._run_case_evaluation_engine(
                request=request,
                classification=classification,
                case_structure=case_structure,
                normative_reasoning=normative_reasoning,
                procedural_strategy=procedural_strategy,
                case_theory=case_theory,
                question_engine_result=question_engine_result,
                case_domain=initial_case_domain,
            )

        # 13. Conflict & evidence engine
        conflict_evidence = {}
        if not pipeline_config["light_mode"]:
            conflict_evidence = self._run_conflict_evidence_engine(
                request=request,
                classification=classification,
                case_structure=case_structure,
                normative_reasoning=normative_reasoning,
                procedural_strategy=procedural_strategy,
                question_engine_result=question_engine_result,
                case_theory=case_theory,
                case_evaluation=case_evaluation,
                case_domain=initial_case_domain,
            )

        # 14. Evidence reasoning linker
        evidence_reasoning_links = self._run_evidence_reasoning_linker(
            request=request,
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            case_theory=case_theory,
            case_evaluation=case_evaluation,
            conflict_evidence=conflict_evidence,
            question_engine_result=question_engine_result,
        )

        # 15. Jurisprudence engine
        jurisprudence_analysis = {}
        if not pipeline_config["light_mode"] and not pipeline_config["skip_jurisprudence"]:
            jurisprudence_analysis = self._run_jurisprudence_engine(
                request=request,
                classification=classification,
                case_structure=case_structure,
                normative_reasoning=normative_reasoning,
                case_theory=case_theory,
                evidence_reasoning_links=evidence_reasoning_links,
            )
        integrate_jurisprudence = getattr(self.normative_reasoner, "integrate_jurisprudence", None)
        if jurisprudence_analysis and callable(integrate_jurisprudence):
            try:
                normative_reasoning = self._normalize_obj(
                    integrate_jurisprudence(
                        normative_reasoning=normative_reasoning,
                        jurisprudence_analysis=jurisprudence_analysis,
                    )
                )
            except TypeError:
                pass

        procedural_events = self._extract_procedural_events(request)
        procedural_timeline = self._run_procedural_timeline_builder(procedural_events=procedural_events)
        procedural_case_state = self._run_procedural_case_state_builder(procedural_timeline=procedural_timeline)

        legal_decision = self._run_legal_decision_engine(
            reasoning=reasoning,
            normative_reasoning=normative_reasoning,
            case_evaluation=case_evaluation,
            jurisprudence_analysis=jurisprudence_analysis,
            evidence_reasoning_links=evidence_reasoning_links,
            conflict_evidence=conflict_evidence,
            procedural_timeline=procedural_timeline,
            procedural_case_state=procedural_case_state,
        )

        # 16. Model selection
        resolved_document_kind = self._resolve_document_kind(
            request=request,
            classification=classification,
            case_structure=case_structure,
        )
        resolved_generation_mode = self._resolve_generation_mode(request)

        tag_signals = collect_tag_signals(
            request_query=request.query,
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=normative_reasoning,
            procedural_strategy=procedural_strategy,
            case_theory=case_theory,
            conflict_evidence=conflict_evidence,
        )
        detected_tags = infer_model_tags(tag_signals)

        model_selection_started_at = time.perf_counter()
        model_match = self.model_library.select_model(
            jurisdiction=resolved_jurisdiction,
            forum=resolved_forum,
            action_slug=classification.get("action_slug") or case_structure.get("action_slug"),
            document_kind=resolved_document_kind,
            detected_tags=detected_tags,
        )
        self._record_observability_stage(observability_context, "pipeline_model_selection_ms", model_selection_started_at)
        self._update_observability(
            observability_context,
            **extract_selected_model_fields(model_match),
        )

        # 16b. Style blueprint
        style_blueprint = normalize_style_blueprint(
            style_directives=model_match.get("style_directives"),
            generation_mode=resolved_generation_mode or "formal",
            detected_tags=detected_tags,
        )
        model_match["style_blueprint"] = style_blueprint.to_dict()

        # 17. Case profile + case strategy
        final_case_profile_started_at = time.perf_counter()
        case_profile = build_case_profile(
            query=request.query,
            classification=classification,
            case_theory=case_theory,
            conflict=conflict_evidence,
            normative_reasoning=normative_reasoning,
            procedural_plan=procedural_strategy,
            facts=request.facts or {},
        )
        case_profile["procedural_timeline"] = procedural_timeline
        case_profile["procedural_case_state"] = procedural_case_state
        case_domain = str(case_profile.get("case_domain") or "").strip() or None
        case_domains = dedupe_domains([str(item).strip() for item in (case_profile.get("case_domains") or []) if str(item).strip()])
        self._record_observability_stage(observability_context, "pipeline_final_case_profile_ms", final_case_profile_started_at)

        # 17b. Safety-net re-alignment: the primary alignment ran at step 6b
        # (before model selection), but if the *final* case_profile resolved a
        # different domain than the initial one, re-align here to keep
        # downstream consumers consistent.
        classification = align_classification_with_domain(
            classification=classification,
            case_domain=case_domain,
            query=request.query,
        )
        secondary_domains = extract_secondary_domains(case_domains, case_domain)
        self._update_observability(
            observability_context,
            final_case_domain=case_domain,
            final_action_slug=str(classification.get("action_slug") or "").strip() or None,
            domain_override_applied=bool(initial_case_domain and case_domain and initial_case_domain != case_domain),
            secondary_domains=secondary_domains,
            had_secondary_domains=bool(secondary_domains),
            had_interdomain_conflict=detect_interdomain_conflict(case_profile, conflict_evidence, legal_decision),
            top_level_domains_detected=case_domains,
        )

        normative_reasoning = self._sanitize_normative_reasoning(
            normative_reasoning=normative_reasoning,
            classification=classification,
            case_domain=case_domain,
        )
        case_strategy_started_at = time.perf_counter()
        case_strategy = sanitize_strategy_output(build_case_strategy(
            query=request.query,
            case_profile=case_profile,
            case_theory=case_theory,
            conflict=conflict_evidence,
            case_evaluation=case_evaluation,
            procedural_plan=procedural_strategy,
            jurisprudence_analysis=jurisprudence_analysis,
            reasoning_result=reasoning,
            legal_decision=legal_decision,
            procedural_case_state=procedural_case_state,
            metadata=request.metadata,
        ))
        self._record_observability_stage(observability_context, "pipeline_case_strategy_ms", case_strategy_started_at)
        strategy_mode_override = str(pipeline_config.get("strategy_mode") or "").strip()
        if strategy_mode_override:
            legal_decision["strategic_posture"] = strategy_mode_override
            case_strategy["strategy_mode"] = strategy_mode_override
        self._update_observability(
            observability_context,
            strategy_mode=str(case_strategy.get("strategy_mode") or legal_decision.get("strategic_posture") or "").strip() or None,
            dominant_factor=str(legal_decision.get("dominant_factor") or "").strip() or None,
        )
        legal_strategy = {
            "case_domain": case_domain,
            "case_domains": case_domains,
            "case_profile": case_profile,
            "procedural_timeline": procedural_timeline,
            "procedural_case_state": procedural_case_state,
            "legal_decision": legal_decision,
            "case_strategy": case_strategy,
        }

        # 18. Argument generation (conditional)
        generated_document = None
        if not pipeline_config["skip_argument_generation"]:
            generated_document = self._try_generate_document(
                request=request,
                reasoning=reasoning,
                procedural_strategy=procedural_strategy,
                citation_validation=citation_validation,
                hallucination_guard=hallucination_guard,
                classification=classification,
                jurisdiction=resolved_jurisdiction,
                forum=resolved_forum,
                case_structure=case_structure,
                normative_reasoning=normative_reasoning,
                question_engine_result=question_engine_result,
                case_theory=case_theory,
                case_evaluation=case_evaluation,
                conflict_evidence=conflict_evidence,
                evidence_reasoning_links=evidence_reasoning_links,
                jurisprudence_analysis=jurisprudence_analysis,
                model_match=model_match,
                context=context,
                retrieved_items=retrieved_items,
                warnings=warnings,
            )

        # Collect warnings
        warnings.extend(self._extract_warnings(classification))
        warnings.extend(self._extract_warnings(case_structure))
        warnings.extend(self._extract_warnings(reasoning))
        warnings.extend(self._extract_warnings(normative_reasoning))
        warnings.extend(self._extract_warnings(citation_validation))
        warnings.extend(self._extract_warnings(hallucination_guard))
        warnings.extend(self._extract_warnings(procedural_strategy))
        warnings.extend(self._extract_warnings(question_engine_result))
        warnings.extend(self._extract_warnings(case_theory))
        warnings.extend(self._extract_warnings(case_evaluation))
        warnings.extend(self._extract_warnings(conflict_evidence))
        warnings.extend(self._extract_warnings(evidence_reasoning_links))
        warnings.extend(self._extract_warnings(jurisprudence_analysis))
        warnings.extend(self._extract_warnings(procedural_timeline))
        warnings.extend(self._extract_warnings(procedural_case_state))
        warnings.extend(self._extract_warnings(legal_decision))
        warnings.extend(self._extract_warnings(model_match))
        warnings.extend(self._extract_warnings(case_profile))
        warnings.extend(self._extract_warnings(case_strategy))
        warnings.extend(self._extract_warnings(legal_strategy))

        confidence = self._resolve_confidence(
            reasoning=reasoning,
            hallucination_guard=hallucination_guard,
            legal_decision=legal_decision,
            case_domain=case_domain,
            case_strategy=case_strategy,
            case_profile=case_profile,
        )
        self._update_observability(
            observability_context,
            final_confidence=confidence,
            fallback_detected=bool(
                model_match.get("selected_model") is None
                or model_match.get("match_type") == "none"
                or model_match.get("fallback_used")
                or model_match.get("used_fallback")
                or model_match.get("selection_fallback")
            ),
            internal_warnings=self._dedupe_preserve_order(warnings),
        )

        response_payload = {
            "query": request.query,
            "jurisdiction": resolved_jurisdiction,
            "forum": resolved_forum,
            "case_domain": case_domain,
            "case_domains": case_domains,
            "facts": self._normalize_obj(request.facts or {}),
            "metadata": self._normalize_obj(request.metadata or {}),
            "retrieved_items": self._normalize_list_of_dicts(retrieved_items),
            "context": self._normalize_obj(context),
            "classification": self._normalize_obj(classification),
            "case_structure": self._normalize_obj(case_structure),
            "reasoning": self._normalize_obj(reasoning),
            "normative_reasoning": self._normalize_obj(normative_reasoning),
            "citation_validation": self._normalize_obj(citation_validation),
            "hallucination_guard": self._normalize_obj(hallucination_guard),
            "procedural_strategy": self._normalize_obj(procedural_strategy),
            "question_engine_result": self._normalize_obj(question_engine_result),
            "case_theory": self._normalize_obj(case_theory),
            "case_evaluation": self._normalize_obj(case_evaluation),
            "conflict_evidence": self._normalize_obj(conflict_evidence),
            "evidence_reasoning_links": self._normalize_obj(evidence_reasoning_links),
            "jurisprudence_analysis": self._normalize_obj(jurisprudence_analysis),
            "procedural_timeline": self._normalize_obj(procedural_timeline),
            "procedural_case_state": self._normalize_obj(procedural_case_state),
            "legal_decision": self._normalize_obj(legal_decision),
            "model_match": self._normalize_obj(model_match),
            "case_profile": self._normalize_obj(case_profile),
            "case_strategy": self._normalize_obj(case_strategy),
            "legal_strategy": self._normalize_obj(legal_strategy),
            "generated_document": generated_document,
            "warnings": self._filter_user_warnings(self._dedupe_preserve_order(warnings)),
            "confidence": confidence,
        }
        response_payload = output_refinement_service.refine(response_payload)
        response_payload = output_mode_service.build_dual_output(response_payload)

        return PipelineResult(
            query=response_payload.get("query", request.query),
            jurisdiction=response_payload.get("jurisdiction"),
            forum=response_payload.get("forum"),
            case_domain=response_payload.get("case_domain"),
            case_domains=list(response_payload.get("case_domains") or []),
            facts=self._normalize_obj(response_payload.get("facts")),
            metadata=self._normalize_obj(response_payload.get("metadata")),
            retrieved_items=self._normalize_list_of_dicts(response_payload.get("retrieved_items")),
            context=self._normalize_obj(response_payload.get("context")),
            classification=self._normalize_obj(response_payload.get("classification")),
            case_structure=self._normalize_obj(response_payload.get("case_structure")),
            reasoning=self._normalize_obj(response_payload.get("reasoning")),
            normative_reasoning=self._normalize_obj(response_payload.get("normative_reasoning")),
            citation_validation=self._normalize_obj(response_payload.get("citation_validation")),
            hallucination_guard=self._normalize_obj(response_payload.get("hallucination_guard")),
            procedural_strategy=self._normalize_obj(response_payload.get("procedural_strategy")),
            question_engine_result=self._normalize_obj(response_payload.get("question_engine_result")),
            case_theory=self._normalize_obj(response_payload.get("case_theory")),
            case_evaluation=self._normalize_obj(response_payload.get("case_evaluation")),
            conflict_evidence=self._normalize_obj(response_payload.get("conflict_evidence")),
            evidence_reasoning_links=self._normalize_obj(response_payload.get("evidence_reasoning_links")),
            jurisprudence_analysis=self._normalize_obj(response_payload.get("jurisprudence_analysis")),
            procedural_timeline=self._normalize_obj(response_payload.get("procedural_timeline")),
            procedural_case_state=self._normalize_obj(response_payload.get("procedural_case_state")),
            legal_decision=self._normalize_obj(response_payload.get("legal_decision")),
            model_match=self._normalize_obj(response_payload.get("model_match")),
            case_profile=self._normalize_obj(response_payload.get("case_profile")),
            case_strategy=self._normalize_obj(response_payload.get("case_strategy")),
            legal_strategy=self._normalize_obj(response_payload.get("legal_strategy")),
            output_modes=self._normalize_obj(response_payload.get("output_modes")),
            conversational=self._normalize_obj(response_payload.get("conversational")),
            conversational_response=self._normalize_obj(response_payload.get("conversational_response")),
            generated_document=response_payload.get("generated_document"),
            quick_start=response_payload.get("quick_start"),
            warnings=list(response_payload.get("warnings") or []),
            confidence=response_payload.get("confidence"),
        )

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    # Mapping from expediente materia/tipo_caso to retriever domain vocabulary
    _MATERIA_TO_DOMAIN: Dict[str, str] = {
        "civil": "civil",
        "laboral": "labor",
        "familia": "family",
        "penal": "penal",
        "comercial": "civil",
        "constitucional": "constitutional",
        "procesal": "procedural",
        "administrativo": "administrative",
        "tributario": "administrative",
    }

    def _enrich_classification_from_expediente(
        self,
        classification: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        When the classifier returned no domain (or empty classification)
        but we have expediente context in metadata, fill in domain hints
        so that the retriever can boost the right normative sources.
        """
        exp_ctx = metadata.get("expediente_context")
        if not exp_ctx or not isinstance(exp_ctx, dict):
            return classification

        # Only enrich when classification is empty or has no domain
        if classification.get("domain"):
            return classification

        classification = dict(classification)

        # Derive domain from tipo_caso or materia
        tipo_caso = (exp_ctx.get("tipo_caso") or "").strip().lower()
        materia = (exp_ctx.get("materia") or "").strip().lower()
        domain = self._MATERIA_TO_DOMAIN.get(tipo_caso) or self._MATERIA_TO_DOMAIN.get(materia)
        if domain:
            classification.setdefault("domain", domain)

        # Propagate expediente_context into classification metadata
        # so downstream engines (case_structurer, reasoner) can use it
        cls_meta = dict(classification.get("metadata") or {})
        cls_meta["expediente_context"] = exp_ctx
        classification["metadata"] = cls_meta

        return classification

    def _run_classification(self, request: PipelineRequest) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.action_classifier,
            method_names=["classify", "run"],
            kwargs={
                "query": request.query,
                "jurisdiction": request.jurisdiction,
                "forum": request.forum,
                "metadata": request.metadata or {},
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_case_structurer(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.case_structurer,
            method_names=["structure", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "jurisdiction": jurisdiction,
                "forum": forum,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_retrieval(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
        db: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        pipeline_config = self._normalize_pipeline_config(config)
        retrieval_mode = pipeline_config["retrieval_mode"]
        normative_items: List[Dict[str, Any]] = []
        online_items: List[Dict[str, Any]] = []
        offline_items: List[Dict[str, Any]] = []

        if retrieval_mode in {"online", "hybrid"} and db is not None:
            try:
                online_items = self._retrieve_normative_online(
                    request=request,
                    classification=classification,
                    jurisdiction=jurisdiction,
                    forum=forum,
                    db=db,
                )
            except Exception as exc:
                self._log_online_retrieval_error(exc)
                online_items = []

        if retrieval_mode in {"offline", "hybrid"} or (retrieval_mode == "online" and not online_items):
            candidates = self._call_first_available(
                target=self.retriever,
                method_names=["retrieve", "search", "run"],
                kwargs={
                    "query": request.query,
                    "top_k": request.top_k,
                    "jurisdiction": jurisdiction,
                    "forum": forum,
                    "classification": classification,
                },
                default=[],
            )
            offline_items = self._extract_normative_items(candidates)

        if retrieval_mode == "hybrid":
            normative_items = self._merge_retrieval_items(online_items, offline_items)
        elif retrieval_mode == "online":
            normative_items = online_items or offline_items
        else:
            normative_items = offline_items

        # 3b. Case document retrieval (expediente context)
        case_items = self._retrieve_case_documents(
            request, jurisdiction, classification, db=db,
        )
        if not case_items:
            return normative_items

        # 3c. Merge: case docs + normative, sorted by score
        from app.modules.search.retrieval import merge_normative_and_case_results
        return merge_normative_and_case_results(
            normative_items=normative_items,
            case_results=case_items,
            top_k=request.top_k * 2,
        )

    def _retrieve_case_documents(
        self,
        request: PipelineRequest,
        jurisdiction: Optional[str],
        classification: Dict[str, Any],
        db: Optional[Any] = None,
    ) -> list:
        """
        Retrieve chunks from documents linked to the expediente.

        Returns a list of SearchResult objects, or empty list if no
        expediente context is available or retrieval fails.
        """
        exp_ctx = (request.metadata or {}).get("expediente_context")
        if not exp_ctx or not isinstance(exp_ctx, dict):
            return []

        expediente_id = exp_ctx.get("expediente_id")
        if not expediente_id:
            return []

        try:
            from app.modules.search.retrieval import retrieve_case_chunks

            if db is not None:
                return retrieve_case_chunks(
                    db=db,
                    query=request.query,
                    expediente_id=expediente_id,
                    jurisdiction=jurisdiction or "Jujuy",
                    legal_area=exp_ctx.get("materia"),
                    top_k=request.top_k,
                    min_score=0.03,
                )

            from app.db.database import SessionLocal

            session = SessionLocal()
            try:
                return retrieve_case_chunks(
                    db=session,
                    query=request.query,
                    expediente_id=expediente_id,
                    jurisdiction=jurisdiction or "Jujuy",
                    legal_area=exp_ctx.get("materia"),
                    top_k=request.top_k,
                    min_score=0.03,
                )
            finally:
                session.close()
        except Exception:
            return []

    def _retrieve_normative_online(
        self,
        *,
        request: PipelineRequest,
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
        db: Any,
    ) -> List[Dict[str, Any]]:
        from app.modules.search.service import HybridSearchService, SearchFilters
        from app.services.document_service import DocumentService

        chunks = DocumentService().get_all_chunks(
            db,
            document_scope="corpus",
            limit=self._ONLINE_NORMATIVE_CHUNK_LIMIT,
        )
        if not chunks:
            return []

        filters = SearchFilters(
            jurisdiction=jurisdiction,
            legal_area=self._resolve_online_legal_area(
                classification=classification,
                metadata=request.metadata or {},
            ),
        )
        results = HybridSearchService().hybrid_search(
            query=request.query,
            chunks=chunks,
            filters=filters,
            top_k=max(request.top_k * 2, request.top_k),
            profile="general",
        )
        return self._normalize_online_retrieval_results(
            results=results,
            query=request.query,
            classification=classification,
            jurisdiction=jurisdiction,
            top_k=request.top_k,
        )

    def _normalize_online_retrieval_results(
        self,
        *,
        results: List[Any],
        query: str,
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        detected_article = None
        detected_source = None
        if hasattr(self.retriever, "detect_article_reference"):
            try:
                article_ref = self.retriever.detect_article_reference(query)
                detected_article = self._normalize_article_value(article_ref.get("article_number"))
                detected_source = article_ref.get("source_id")
            except Exception:
                detected_article = None
                detected_source = None

        priority_keys = {
            (
                str(item.get("source_id") or "").strip(),
                self._normalize_article_value(item.get("article")),
            )
            for item in (classification.get("priority_articles") or [])
            if isinstance(item, dict)
        }

        normalized: List[Dict[str, Any]] = []
        for raw in results or []:
            item = raw.to_dict() if hasattr(raw, "to_dict") and callable(raw.to_dict) else raw
            if not isinstance(item, dict):
                continue
            if not self._is_normative_hierarchy(item.get("source_hierarchy")):
                continue

            source_id = self._resolve_online_source_id(item)
            article = self._extract_online_article(item)
            article_key = self._normalize_article_value(article)
            match_type = "online_hybrid"
            score = self._normalize_online_score(
                item.get("scores", {}).get("final"),
                fallback=item.get("final_score"),
            )

            if detected_article and article_key == detected_article and (not detected_source or detected_source == source_id):
                score = max(score, 0.99)
                match_type = "exact"
            elif (source_id, article_key) in priority_keys:
                score = max(score, 0.92)
                match_type = "hybrid"

            titulo = str(item.get("document_title") or item.get("section") or "").strip()
            label = self._build_online_label(article=article, titulo=titulo, source_id=source_id)
            norm_type = self._resolve_online_norm_type(item, source_id)
            domain = self._resolve_online_domain(item, source_id, classification)

            normalized.append({
                "source_id": source_id,
                "article": article,
                "label": label,
                "titulo": titulo,
                "texto": str(item.get("text") or "").strip(),
                "score": round(score, 6),
                "match_type": match_type,
                "jurisdiction": str(item.get("jurisdiction") or jurisdiction or "").strip(),
                "norm_type": norm_type,
                "domain": domain,
                "source_hierarchy": str(item.get("source_hierarchy") or "").strip(),
                "chunk_id": str(item.get("chunk_id") or item.get("id") or "").strip(),
                "document_id": str(item.get("document_id") or "").strip(),
                "section": str(item.get("section") or "").strip(),
                "page_number": item.get("page_number"),
                "vigente": item.get("vigente", True),
                "retrieval_explanation": str(item.get("retrieval_explanation") or "").strip(),
            })

        if hasattr(self.retriever, "dedupe_results"):
            try:
                normalized = self.retriever.dedupe_results(normalized)
            except Exception:
                pass
        if hasattr(self.retriever, "boost_by_hierarchy"):
            try:
                normalized = self.retriever.boost_by_hierarchy(
                    normalized,
                    str(jurisdiction or "jujuy").strip().lower(),
                    str(classification.get("domain") or "unknown").strip().lower(),
                )
            except Exception:
                normalized.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        else:
            normalized.sort(key=lambda item: item.get("score", 0.0), reverse=True)

        return normalized[:top_k]

    def _extract_normative_items(self, payload: Any) -> List[Dict[str, Any]]:
        normalized = self._normalize_obj(payload)
        if isinstance(normalized, dict):
            results = normalized.get("results")
            if isinstance(results, list):
                return [item for item in results if isinstance(item, dict)]
            return [normalized]
        if isinstance(normalized, list):
            return [item for item in normalized if isinstance(item, dict)]
        return self._normalize_list_of_dicts(normalized)

    def _resolve_online_legal_area(
        self,
        *,
        classification: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        domain = str(classification.get("domain") or "").strip().lower()
        if domain:
            return {
                "procedural": "procesal",
                "constitutional": "constitucional",
                "civil": "civil",
                "family": "familia",
                "labor": "laboral",
            }.get(domain, domain)

        exp_ctx = metadata.get("expediente_context")
        if isinstance(exp_ctx, dict):
            materia = str(exp_ctx.get("materia") or "").strip().lower()
            if materia:
                return materia
        return None

    def _resolve_online_source_id(self, item: Dict[str, Any]) -> str:
        title = " ".join(
            str(part).strip()
            for part in (item.get("document_title"), item.get("section"), item.get("article_reference"))
            if str(part or "").strip()
        ).lower()
        jurisdiction = str(item.get("jurisdiction") or "").strip().lower()

        if "cpcc" in title or "codigo procesal" in title or "procesal civil" in title:
            return "cpcc_jujuy"
        if "constitucion nacional" in title:
            return "constitucion_nacional"
        if "constitucion" in title and "jujuy" in title:
            return "constitucion_jujuy"
        if "codigo civil y comercial" in title or "cccn" in title or "ccyc" in title:
            return "codigo_civil_comercial"
        if "contrato de trabajo" in title or "ley 20744" in title or "ley 20.744" in title or "lct" in title:
            return "lct_20744"
        if "constitucion" in title and jurisdiction == "nacional":
            return "constitucion_nacional"

        return str(item.get("document_id") or item.get("chunk_id") or "").strip()

    def _extract_online_article(self, item: Dict[str, Any]) -> str:
        for value in (item.get("article_reference"), item.get("section")):
            normalized = self._normalize_article_value(value)
            if normalized:
                return normalized
        return str(item.get("chunk_id") or "").strip()

    def _normalize_article_value(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        import re

        match = re.search(r"(\d+(?:\s*(?:bis|ter|quater))?)", text, re.IGNORECASE)
        if not match:
            return text
        return re.sub(r"\s+", "", match.group(1))

    def _build_online_label(
        self,
        *,
        article: str,
        titulo: str,
        source_id: str,
    ) -> str:
        if article and titulo:
            return f"Articulo {article} — {titulo}"
        if article:
            return f"Articulo {article}"
        if titulo:
            return titulo
        return source_id

    def _resolve_online_norm_type(self, item: Dict[str, Any], source_id: str) -> str:
        source_type = str(item.get("source_type") or "").strip().lower()
        if source_type:
            return source_type
        if source_id.startswith("constitucion"):
            return "constitucion"
        if source_id.startswith("cpcc") or source_id == "codigo_civil_comercial":
            return "codigo"
        if source_id == "lct_20744":
            return "ley"
        return "norma"

    def _resolve_online_domain(
        self,
        item: Dict[str, Any],
        source_id: str,
        classification: Dict[str, Any],
    ) -> str:
        if source_id == "cpcc_jujuy":
            return "procedural"
        if source_id in {"constitucion_nacional", "constitucion_jujuy"}:
            return "constitutional"
        if source_id == "codigo_civil_comercial":
            return "civil"
        if source_id == "lct_20744":
            return "labor"

        legal_area = str(item.get("legal_area") or "").strip().lower()
        if legal_area:
            return {
                "procesal": "procedural",
                "constitucional": "constitutional",
                "civil": "civil",
                "familia": "family",
                "laboral": "labor",
            }.get(legal_area, legal_area)
        return str(classification.get("domain") or "unknown").strip().lower()

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _normalize_online_score(
        self,
        value: Any,
        *,
        fallback: Any = None,
    ) -> float:
        score = self._safe_float(value, default=self._safe_float(fallback, default=0.0))
        if score <= 0.0:
            return 0.0
        if score <= 1.0:
            return score
        if score <= 100.0:
            return score / 100.0
        return 1.0

    def _is_normative_hierarchy(self, value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return normalized in self._NORMATIVE_HIERARCHY_ALIASES

    def _log_online_retrieval_error(self, exc: Exception) -> None:
        try:
            self._logger.warning(
                "Normative online retrieval failed; falling back to offline retriever: %s",
                exc,
            )
        except Exception:
            pass

    def _run_context_builder(
        self,
        request: PipelineRequest,
        retrieved_items: List[Dict[str, Any]],
        jurisdiction: Optional[str],
        forum: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.context_builder,
            method_names=["build", "build_context", "run"],
            kwargs={
                "query": request.query,
                "retrieved_items": retrieved_items,
                "jurisdiction": jurisdiction,
                "forum": forum,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_reasoner(
        self,
        request: PipelineRequest,
        context: Dict[str, Any],
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.legal_reasoner,
            method_names=["reason", "analyze", "run"],
            kwargs={
                "query": request.query,
                "context": context,
                "jurisdiction": jurisdiction,
                "forum": forum,
                "classification": classification,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_normative_reasoner(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
        retrieved_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.normative_reasoner,
            method_names=["reason", "analyze", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "case_structure": case_structure,
                "retrieved_chunks": retrieved_items,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_citation_validation(
        self,
        context: Dict[str, Any],
        reasoning: Dict[str, Any],
    ) -> Dict[str, Any]:
        citations_used = reasoning.get("citations_used", []) if isinstance(reasoning, dict) else []
        result = self._call_first_available(
            target=self.citation_validator,
            method_names=["validate", "validate_citations", "run"],
            kwargs={
                "citations": citations_used,
                "context": context,
                "reasoning": reasoning,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_hallucination_guard(
        self,
        request: PipelineRequest,
        context: Dict[str, Any],
        reasoning: Dict[str, Any],
        citation_validation: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.hallucination_guard,
            method_names=["review", "guard", "run"],
            kwargs={
                "query": request.query,
                "context": context,
                "reasoning": reasoning,
                "citation_validation": citation_validation,
                "jurisdiction": jurisdiction,
                "forum": forum,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_procedural_strategy(
        self,
        request: PipelineRequest,
        context: Dict[str, Any],
        reasoning: Dict[str, Any],
        hallucination_guard: Dict[str, Any],
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        case_domain: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.procedural_strategy,
            method_names=["build", "plan", "run"],
            kwargs={
                "query": request.query,
                "context": context,
                "reasoning": reasoning,
                "jurisdiction": jurisdiction,
                "forum": forum,
                "facts": request.facts or {},
                "hallucination_guard": hallucination_guard,
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "case_domain": case_domain,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_argument_generator(
        self,
        request: PipelineRequest,
        context: Dict[str, Any],
        reasoning: Dict[str, Any],
        procedural_strategy: Dict[str, Any],
        citation_validation: Dict[str, Any],
        hallucination_guard: Dict[str, Any],
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        question_engine_result: Dict[str, Any],
        case_theory: Dict[str, Any],
        case_evaluation: Dict[str, Any],
        conflict_evidence: Dict[str, Any],
        evidence_reasoning_links: Dict[str, Any],
        jurisprudence_analysis: Dict[str, Any],
        model_match: Dict[str, Any],
        effective_mode: Optional[str] = None,
    ) -> Optional[str]:
        mode = effective_mode or request.document_mode
        if not mode:
            return None

        generation_context = dict(context)
        generation_context["model_match"] = model_match

        result = self._call_first_available(
            target=self.argument_generator,
            method_names=["generate", "render", "run"],
            kwargs={
                "mode": mode,
                "query": request.query,
                "context": generation_context,
                "reasoning": reasoning,
                "strategy": procedural_strategy,
                "reasoning_result": reasoning,
                "procedural_plan": procedural_strategy,
                "citation_validation": citation_validation,
                "hallucination_guard": hallucination_guard,
                "jurisdiction": jurisdiction,
                "forum": forum,
                "facts": request.facts or {},
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "question_engine_result": question_engine_result,
                "case_theory": case_theory,
                "case_evaluation": case_evaluation,
                "conflict_evidence": conflict_evidence,
                "evidence_reasoning_links": evidence_reasoning_links,
                "jurisprudence_analysis": jurisprudence_analysis,
                "model_match": model_match,
            },
            default=None,
        )

        if result is None:
            return None
        if isinstance(result, str):
            return result

        normalized = self._normalize_obj(result)
        if isinstance(normalized, dict):
            return (
                normalized.get("full_text")
                or normalized.get("text")
                or normalized.get("document")
                or normalized.get("content")
            )
        return str(normalized)

    # ------------------------------------------------------------------
    # Document generation with activation policy
    # ------------------------------------------------------------------

    _AUTO_GENERATION_MODE = "base_argumental"
    _MIN_CONFIDENCE_FOR_GENERATION = 0.30

    def _try_generate_document(
        self,
        request: PipelineRequest,
        reasoning: Dict[str, Any],
        procedural_strategy: Dict[str, Any],
        citation_validation: Dict[str, Any],
        hallucination_guard: Dict[str, Any],
        classification: Dict[str, Any],
        jurisdiction: Optional[str],
        forum: Optional[str],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        question_engine_result: Dict[str, Any],
        case_theory: Dict[str, Any],
        case_evaluation: Dict[str, Any],
        conflict_evidence: Dict[str, Any],
        evidence_reasoning_links: Dict[str, Any],
        jurisprudence_analysis: Dict[str, Any],
        model_match: Dict[str, Any],
        context: Dict[str, Any],
        retrieved_items: List[Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[str]:
        """
        Conditionally generate a document using ArgumentGenerator.

        Activation policy:
        - If request.document_mode is set, use that mode (user intent).
        - Otherwise, auto-generate in 'base_argumental' mode only when:
          1. A meaningful action_slug was detected (not empty/generic).
          2. There is normative grounding (retrieved items or applied rules).
        - If generation fails, return None and append a filtered warning.
        """
        effective_mode = self._resolve_effective_generation_mode(
            request=request,
            classification=classification,
            normative_reasoning=normative_reasoning,
            retrieved_items=retrieved_items,
            reasoning=reasoning,
        )
        if effective_mode is None:
            return None

        try:
            result = self._run_argument_generator(
                request=request,
                context=context,
                reasoning=reasoning,
                procedural_strategy=procedural_strategy,
                citation_validation=citation_validation,
                hallucination_guard=hallucination_guard,
                classification=classification,
                jurisdiction=jurisdiction,
                forum=forum,
                case_structure=case_structure,
                normative_reasoning=normative_reasoning,
                question_engine_result=question_engine_result,
                case_theory=case_theory,
                case_evaluation=case_evaluation,
                conflict_evidence=conflict_evidence,
                evidence_reasoning_links=evidence_reasoning_links,
                jurisprudence_analysis=jurisprudence_analysis,
                model_match=model_match,
                effective_mode=effective_mode,
            )
            if result and isinstance(result, str) and result.strip():
                return result.strip()
            return None
        except Exception:
            warnings.append(
                "La generacion automatica de documento fallo; se entrega estrategia juridica estructurada."
            )
            return None

    def _resolve_effective_generation_mode(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        retrieved_items: List[Dict[str, Any]],
        reasoning: Dict[str, Any],
    ) -> Optional[str]:
        """
        Decide which generation mode to use, or None to skip generation.

        If the user explicitly requested a document_mode, honor it.
        Otherwise, apply activation policy for auto-generation:
        1. Meaningful action_slug (not empty/generic).
        2. Normative grounding (retrieved items or applied rules).
        3. Reasoning confidence >= _MIN_CONFIDENCE_FOR_GENERATION.
        """
        if request.document_mode:
            return request.document_mode

        # Auto-generation gate: require meaningful classification
        action_slug = str(classification.get("action_slug") or "").strip().lower()
        if not action_slug or action_slug == "generic":
            return None

        # Require normative grounding: at least 1 retrieved item or 1 applied rule
        has_retrieved = bool(retrieved_items)
        has_rules = bool(
            (normative_reasoning.get("applied_rules") or [])
            if isinstance(normative_reasoning, dict) else False
        )
        if not has_retrieved and not has_rules:
            return None

        # Require minimum confidence from reasoning layer
        confidence = None
        if isinstance(reasoning, dict):
            confidence = reasoning.get("confidence_score") or reasoning.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < self._MIN_CONFIDENCE_FOR_GENERATION:
            return None

        return self._AUTO_GENERATION_MODE

    def _run_question_engine(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        procedural_strategy: Dict[str, Any],
        case_domain: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.question_engine,
            method_names=["generate", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "procedural_strategy": procedural_strategy,
                "case_domain": case_domain,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_case_theory_engine(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        procedural_strategy: Dict[str, Any],
        question_engine_result: Dict[str, Any],
        case_domain: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.case_theory_engine,
            method_names=["build", "analyze", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "procedural_strategy": procedural_strategy,
                "question_engine_result": question_engine_result,
                "case_domain": case_domain,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_case_evaluation_engine(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        procedural_strategy: Dict[str, Any],
        case_theory: Dict[str, Any],
        question_engine_result: Dict[str, Any],
        case_domain: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.case_evaluation_engine,
            method_names=["evaluate", "analyze", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "procedural_strategy": procedural_strategy,
                "case_theory": case_theory,
                "question_engine_result": question_engine_result,
                "case_domain": case_domain,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_conflict_evidence_engine(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        procedural_strategy: Dict[str, Any],
        question_engine_result: Dict[str, Any],
        case_theory: Dict[str, Any],
        case_evaluation: Dict[str, Any],
        case_domain: Optional[str],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.conflict_evidence_engine,
            method_names=["analyze", "build", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "procedural_strategy": procedural_strategy,
                "question_engine_result": question_engine_result,
                "case_theory": case_theory,
                "case_evaluation": case_evaluation,
                "case_domain": case_domain,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_evidence_reasoning_linker(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        case_theory: Dict[str, Any],
        case_evaluation: Dict[str, Any],
        conflict_evidence: Dict[str, Any],
        question_engine_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.evidence_reasoning_linker,
            method_names=["analyze", "build", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "case_theory": case_theory,
                "case_evaluation": case_evaluation,
                "conflict_evidence": conflict_evidence,
                "question_engine_result": question_engine_result,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_jurisprudence_engine(
        self,
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        case_theory: Dict[str, Any],
        evidence_reasoning_links: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.jurisprudence_engine,
            method_names=["analyze", "build", "run"],
            kwargs={
                "query": request.query,
                "classification": classification,
                "case_structure": case_structure,
                "normative_reasoning": normative_reasoning,
                "case_theory": case_theory,
                "evidence_reasoning_links": evidence_reasoning_links,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _run_legal_decision_engine(
        self,
        *,
        reasoning: Dict[str, Any],
        normative_reasoning: Dict[str, Any],
        case_evaluation: Dict[str, Any],
        jurisprudence_analysis: Dict[str, Any],
        evidence_reasoning_links: Dict[str, Any],
        conflict_evidence: Dict[str, Any],
        procedural_timeline: Dict[str, Any],
        procedural_case_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = self._call_first_available(
            target=self.legal_decision_engine,
            method_names=["decide", "analyze", "build", "run"],
            kwargs={
                "reasoning": reasoning,
                "normative_reasoning": normative_reasoning,
                "case_evaluation": case_evaluation,
                "jurisprudence_analysis": jurisprudence_analysis,
                "evidence_reasoning_links": evidence_reasoning_links,
                "conflict_evidence": conflict_evidence,
                "procedural_timeline": procedural_timeline,
                "procedural_case_state": procedural_case_state,
            },
            default={},
        )
        return self._normalize_obj(result)

    def _extract_procedural_events(self, request: PipelineRequest) -> List[Dict[str, Any]]:
        metadata = request.metadata or {}
        facts = request.facts or {}
        for source in (metadata, facts):
            for key in ("procedural_events", "expediente_events", "timeline_events", "docket_events"):
                value = source.get(key)
                events = self._normalize_list_of_dicts(value)
                if events:
                    return events
        return []

    def _run_procedural_timeline_builder(
        self,
        *,
        procedural_events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not procedural_events:
            return {}
        result = self._call_first_available(
            target=self.procedural_timeline_builder,
            method_names=["build", "run"],
            kwargs={"events": procedural_events},
            default={},
        )
        return self._normalize_obj(result)

    def _run_procedural_case_state_builder(
        self,
        *,
        procedural_timeline: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not procedural_timeline:
            return {}
        result = self._call_first_available(
            target=self.procedural_case_state_builder,
            method_names=["build", "analyze", "run"],
            kwargs={"timeline": procedural_timeline},
            default={},
        )
        return self._normalize_obj(result)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_pipeline_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = dict(config or {})
        retrieval_mode = str(data.get("retrieval_mode") or "offline").strip().lower()
        if retrieval_mode not in {"online", "offline", "hybrid"}:
            retrieval_mode = "offline"
        return {
            "retrieval_mode": retrieval_mode,
            "strategy_mode": str(data.get("strategy_mode") or "").strip().lower(),
            "skip_jurisprudence": bool(data.get("skip_jurisprudence")),
            "skip_argument_generation": bool(data.get("skip_argument_generation")),
            "light_mode": bool(data.get("light_mode")),
        }

    def _merge_retrieval_items(self, *collections: Any) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for collection in collections:
            for item in self._normalize_list_of_dicts(collection):
                source = str(item.get("source_id") or item.get("source") or "").strip()
                article = str(item.get("article") or "").strip()
                title = str(item.get("title") or item.get("label") or "").strip()
                signature = (source.casefold(), article.casefold(), title.casefold())
                if signature in seen:
                    continue
                seen.add(signature)
                merged.append(item)
        return merged

    def _call_first_available(
        self,
        target: Any,
        method_names: List[str],
        kwargs: Dict[str, Any],
        default: Any = None,
    ) -> Any:
        for method_name in method_names:
            method = getattr(target, method_name, None)
            if callable(method):
                try:
                    return method(**self._filter_kwargs_for_callable(method, kwargs))
                except TypeError:
                    continue
        return default

    def _filter_kwargs_for_callable(
        self,
        fn: Callable[..., Any],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            import inspect

            signature = inspect.signature(fn)
            accepted = {}
            has_var_kw = False

            for param in signature.parameters.values():
                if param.kind == param.VAR_KEYWORD:
                    has_var_kw = True
                    break

            if has_var_kw:
                return kwargs

            for name in signature.parameters.keys():
                if name in kwargs:
                    accepted[name] = kwargs[name]
            return accepted
        except Exception:
            return kwargs

    def _normalize_obj(self, value: Any) -> Any:
        if value is None:
            return {}
        if hasattr(value, "to_dict") and callable(value.to_dict):
            try:
                return self._normalize_obj(value.to_dict())
            except Exception:
                return value
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {k: self._normalize_obj(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalize_obj(v) for v in value]
        if hasattr(value, "__dict__"):
            try:
                return {
                    k: self._normalize_obj(v)
                    for k, v in vars(value).items()
                    if not k.startswith("_")
                }
            except Exception:
                return value
        return value

    def _normalize_list_of_dicts(self, value: Any) -> List[Dict[str, Any]]:
        normalized = self._normalize_obj(value)
        if not normalized:
            return []
        if isinstance(normalized, list):
            result: List[Dict[str, Any]] = []
            for item in normalized:
                if isinstance(item, dict):
                    result.append(item)
                else:
                    result.append({"value": item})
            return result
        if isinstance(normalized, dict):
            return [normalized]
        return [{"value": normalized}]

    def _extract_warnings(self, payload: Any) -> List[str]:
        if not isinstance(payload, dict):
            return []

        warnings: List[str] = []

        for key in ("warnings", "alerts", "issues"):
            value = payload.get(key)
            if isinstance(value, list):
                warnings.extend(str(v) for v in value if v not in (None, ""))
            elif isinstance(value, str) and value.strip():
                warnings.append(value.strip())

        severity = payload.get("severity")
        if isinstance(severity, str) and severity.lower() in {"high", "critical"}:
            warnings.append(f"Severidad detectada: {severity}")

        return self._dedupe_preserve_order(warnings)

    def _update_observability(self, context: Any, **fields: Any) -> None:
        update_beta_observability_context(context, **fields)

    def _record_observability_stage(self, context: Any, stage_name: str, started_at: float) -> None:
        if context is None:
            return
        try:
            context.record_stage_duration(stage_name, started_at)
        except Exception:
            self._logger.debug("No se pudo registrar stage de beta observability.", exc_info=True)

    _WARNING_NOISE_PATTERNS: List[str] = [
        "fallback generico",
        "fallback",
        "generic",
        "no se encontro un patron",
        "no se encontro un modelo aplicable",
        "no existe handler",
        "modelo no aplicable",
        "se rechazaron",
        "no hay coincidencias en corpus",
        "internal_fallback",
        "razonamiento normativo generico",
    ]

    def _filter_user_warnings(self, warnings: List[str]) -> List[str]:
        result: List[str] = []
        for w in warnings:
            normalized = w.lower()
            if any(pat in normalized for pat in self._WARNING_NOISE_PATTERNS):
                continue
            result.append(w)
        return result

    def _sanitize_normative_reasoning(
        self,
        *,
        normative_reasoning: Dict[str, Any],
        classification: Dict[str, Any],
        case_domain: Optional[str],
    ) -> Dict[str, Any]:
        data = self._normalize_obj(normative_reasoning)
        if not isinstance(data, dict):
            return {}

        action_slug = str(classification.get("action_slug") or "").strip().lower()
        warnings_text = " ".join(str(item) for item in (data.get("warnings") or [])).lower()
        summary_text = str(data.get("summary") or "").lower()
        is_generic = action_slug in {"", "generic"} or "fallback generico" in warnings_text or "razonamiento normativo generico" in summary_text
        if not is_generic:
            return data

        if case_domain == "conflicto_patrimonial":
            filtered_rules = []
            for rule in (data.get("applied_rules") or []):
                if not isinstance(rule, dict):
                    continue
                source = str(rule.get("source") or rule.get("source_id") or "").lower()
                article = str(rule.get("article") or "").strip()
                if "constitucion" in source and article == "51":
                    continue
                filtered_rules.append(rule)

            cleaned = dict(data)
            cleaned["applied_rules"] = filtered_rules
            cleaned["warnings"] = self._dedupe_preserve_order([
                *[str(item).strip() for item in (data.get("warnings") or []) if str(item).strip()],
                "La estrategia patrimonial se prioriza aunque la base normativa especifica sea debil o generica.",
            ])
            if not filtered_rules:
                cleaned["summary"] = (
                    "La consulta se sostendra con estrategia juridica estructurada y preguntas criticas, "
                    "sin presentar normativa generica como respaldo fuerte."
                )
            return cleaned

        return data

    def _resolve_confidence(
        self,
        reasoning: Dict[str, Any],
        hallucination_guard: Dict[str, Any],
        *,
        legal_decision: Optional[Dict[str, Any]] = None,
        case_domain: Optional[str] = None,
        case_strategy: Optional[Dict[str, Any]] = None,
        case_profile: Optional[Dict[str, Any]] = None,
    ) -> Optional[float]:
        if isinstance(legal_decision, dict):
            decision_confidence = legal_decision.get("confidence_score")
            if decision_confidence is not None:
                try:
                    return round(float(decision_confidence), 4)
                except (TypeError, ValueError):
                    pass

        base_confidence = (
            reasoning.get("confidence_score") or reasoning.get("confidence")
            if isinstance(reasoning, dict) else None
        )
        adjusted_confidence = (
            hallucination_guard.get("confidence_adjustment")
            if isinstance(hallucination_guard, dict)
            else None
        )

        try:
            if base_confidence is None:
                confidence = 0.3
            else:
                confidence = float(base_confidence)

            if adjusted_confidence is not None:
                adjustment = float(adjusted_confidence)
                if 0.0 <= adjustment <= 1.0:
                    confidence *= adjustment
                else:
                    confidence = adjustment

            # --- Contextual calibration ---
            # Boost if a concrete case_domain was detected
            if case_domain and case_domain not in {"", "generic"}:
                confidence = max(confidence, 0.35)
                confidence += 0.05

            # Boost if strategy has structured content
            if isinstance(case_strategy, dict):
                narrative = case_strategy.get("strategic_narrative", "")
                actions = case_strategy.get("recommended_actions", [])
                if isinstance(narrative, str) and len(narrative) > 100:
                    confidence += 0.05
                if isinstance(actions, list) and len(actions) >= 2:
                    confidence += 0.05

            # Penalize if critical facts are missing
            if isinstance(case_profile, dict):
                missing = case_profile.get("missing_critical_facts") or case_profile.get("missing_info") or []
                if isinstance(missing, list) and len(missing) >= 3:
                    confidence -= 0.05

            return max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            return None

    def _dedupe_preserve_order(self, items: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    # ------------------------------------------------------------------
    # Document kind / generation mode resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_document_kind(
        request: PipelineRequest,
        classification: Dict[str, Any],
        case_structure: Dict[str, Any],
    ) -> Optional[str]:
        """Resolve the *document kind* (tipo de pieza procesal).

        Priority:
        1. Explicit ``request.document_kind`` (new field).
        2. Classification or case_structure hints.
        3. Fallback from ``request.document_mode`` for backward compat.
        """
        if request.document_kind:
            return request.document_kind
        # Infer from classification/case_structure if available
        for source in (classification, case_structure):
            kind = str(source.get("document_kind") or "").strip()
            if kind:
                return kind
        # Backward compat: document_mode used to serve double duty
        return request.document_mode

    @staticmethod
    def _resolve_generation_mode(request: PipelineRequest) -> Optional[str]:
        """Resolve the *generation mode* (strategy/format of output).

        For now this is ``document_mode``; the separation allows future
        callers to set generation_mode independently.
        """
        return request.document_mode
