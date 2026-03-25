"""AILEX -- Legal Engine: corpus retrieval and post-retrieval reasoning pipeline."""

from legal_engine.action_classifier import ActionClassification, ActionClassifier
from legal_engine.action_taxonomy import ACTION_TAXONOMY, TAXONOMY_BY_ACTION, ActionTaxonomyEntry
from legal_engine.normative_engine import NormativeEngine
from legal_engine.retriever_orchestrator import LegalRetrieverOrchestrator
from legal_engine.jurisprudence_corpus import JurisprudenceCorpus
from legal_engine.jurisprudence_loader import JurisprudenceLoader
from legal_engine.jurisprudence_schema import (
    LEGACY_MODE,
    STRICT_MODE,
    JurisprudencePrecedent,
    JurisprudenceValidationError,
)
from legal_engine.jurisprudence_curation import (
    CuratedCaseValidationIssue,
    CuratedCaseValidationResult,
    CuratedDatasetValidationReport,
    build_curated_case_template,
    validate_curated_case,
    validate_curated_corpus_root,
    validate_curated_dataset_file,
)
from legal_engine.jurisprudence_index import JurisprudenceIndex
from legal_engine.jurisprudence_parser import ParsedJurisprudenceCase, JurisprudenceParser
from legal_engine.jurisprudence_retriever import JurisprudenceRetriever

# Post-retrieval reasoning pipeline
from legal_engine.context_builder import (
    LegalArticleChunk,
    LegalContext,
    LegalContextBuilder,
)
from legal_engine.citation_validator import (
    CitationStatus,
    CitationValidator,
    ValidatedCitation,
    ValidationReport,
)
from legal_engine.hallucination_guard import (
    GuardResult,
    HallucinationFlag,
    HallucinationGuard,
    Severity,
)
from legal_engine.legal_reasoner import (
    LegalReasoner,
    NormativeGrounding,
    ReasoningResult,
)
from legal_engine.normative_reasoner import (
    AppliedRule as NormativeAppliedRule,
    NormativeReasoner,
    NormativeReasoningResult,
)
from legal_engine.procedural_strategy import (
    ProceduralPlan,
    ProceduralStep,
    ProceduralStrategy,
)
from legal_engine.procedural_timeline_builder import (
    ProceduralTimelineBuilder,
    ProceduralTimelineEvent,
    ProceduralTimelineResult,
)
from legal_engine.procedural_case_state import (
    ProceduralCaseState,
    ProceduralCaseStateBuilder,
)
from legal_engine.question_engine import (
    QuestionEngine,
    QuestionEngineResult,
    QuestionItem,
)
from legal_engine.case_theory_engine import (
    CaseTheoryEngine,
    CaseTheoryResult,
)
from legal_engine.argument_generator import (
    ArgumentGenerator,
    ArgumentSection,
    GeneratedArgument,
)
from legal_engine.legal_decision_engine import (
    LegalDecisionEngine,
    LegalDecisionResult,
)
from legal_engine.model_library import (
    ApplicabilityRules,
    ModelLibrary,
    ModelRecord,
    StyleProfile,
)
from legal_engine.evidence_reasoning_linker import (
    EvidenceReasoningLinker,
    EvidenceReasoningResult,
    RequirementLink,
)
from legal_engine.legal_strategy_builder import build_legal_strategy
from legal_engine.case_structurer import (
    ApplicableRule,
    CaseStructure,
    CaseStructurer,
)

# Alias consumed by ailex_pipeline
ContextBuilder = LegalContextBuilder

# Pipeline -- imported last to avoid circular-import issues
# (ailex_pipeline.py imports from this package; placing it last guarantees all
# names above are already bound before Python re-enters this module)
from legal_engine.ailex_pipeline import AilexPipeline, PipelineRequest, PipelineResult  # noqa: E402

__all__ = [
    # Retrieval
    "NormativeEngine",
    "LegalRetrieverOrchestrator",
    "JurisprudenceCorpus",
    "JurisprudenceLoader",
    "STRICT_MODE",
    "LEGACY_MODE",
    "JurisprudencePrecedent",
    "JurisprudenceValidationError",
    "CuratedCaseValidationIssue",
    "CuratedCaseValidationResult",
    "CuratedDatasetValidationReport",
    "build_curated_case_template",
    "validate_curated_case",
    "validate_curated_corpus_root",
    "validate_curated_dataset_file",
    "JurisprudenceIndex",
    "ParsedJurisprudenceCase",
    "JurisprudenceParser",
    "JurisprudenceRetriever",
    "ActionClassification",
    "ActionClassifier",
    "ActionTaxonomyEntry",
    "ACTION_TAXONOMY",
    "TAXONOMY_BY_ACTION",
    # Context
    "LegalArticleChunk",
    "LegalContext",
    "LegalContextBuilder",
    "ContextBuilder",
    # Citation validation
    "CitationStatus",
    "CitationValidator",
    "ValidatedCitation",
    "ValidationReport",
    # Hallucination guard
    "GuardResult",
    "HallucinationFlag",
    "HallucinationGuard",
    "Severity",
    # Reasoning
    "LegalReasoner",
    "NormativeGrounding",
    "ReasoningResult",
    # Normative reasoner
    "NormativeAppliedRule",
    "NormativeReasoner",
    "NormativeReasoningResult",
    # Procedural strategy
    "ProceduralPlan",
    "ProceduralStep",
    "ProceduralStrategy",
    "ProceduralTimelineBuilder",
    "ProceduralTimelineEvent",
    "ProceduralTimelineResult",
    "ProceduralCaseState",
    "ProceduralCaseStateBuilder",
    # Question engine
    "QuestionEngine",
    "QuestionEngineResult",
    "QuestionItem",
    # Case theory
    "CaseTheoryEngine",
    "CaseTheoryResult",
    # Argument generation
    "ArgumentGenerator",
    "ArgumentSection",
    "GeneratedArgument",
    "LegalDecisionEngine",
    "LegalDecisionResult",
    "ModelLibrary",
    "ModelRecord",
    "StyleProfile",
    "ApplicabilityRules",
    # Case structurer
    "ApplicableRule",
    "CaseStructure",
    "CaseStructurer",
    # Evidence reasoning linker
    "EvidenceReasoningLinker",
    "EvidenceReasoningResult",
    "RequirementLink",
    "build_legal_strategy",
    # Full pipeline
    "AilexPipeline",
    "PipelineRequest",
    "PipelineResult",
]
