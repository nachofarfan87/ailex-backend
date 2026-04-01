# c:\Users\nacho\Documents\APPS\AILEX\backend\app\api\legal_query.py
from __future__ import annotations

import logging
import time
from io import BytesIO
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.db.database import get_db
from app.db.user_models import User
from app.services import consulta_service
from app.services import learning_log_service, query_logging_service
from app.services import session_tracking_service
from app.services.beta_observability_helpers import derive_response_status
from app.services.beta_observability_service import (
    fail_beta_observability_context,
    finalize_beta_observability_context,
    start_beta_observability_context,
    update_beta_observability_context,
)
from app.services.chat_logger import build_chat_log_entry, log_chat_interaction
from app.services.clarification_flow_service import prepare_legal_query_turn
from app.services.learning_safety_service import (
    infer_fallback_type,
    record_safety_event,
    resolve_safety_outcome,
    should_exclude_from_learning,
)
from app.services.legal_export import build_legal_query_docx
from app.services.request_guardrail_service import evaluate_query_input
from app.services.safety_classifier import classify_severity, evaluate_protective_mode
from app.services.safety_response_service import build_safety_error_response
from app.services.usage_guardrail_service import evaluate_usage_guardrail
from legal_engine.query_orchestrator import PIPELINE_VERSION, QueryOrchestrator, QueryOrchestratorError

router = APIRouter(prefix="/api", tags=["legal"])

_orchestrator = QueryOrchestrator()
logger = logging.getLogger(__name__)


class LegalQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    jurisdiction: Optional[str] = None
    forum: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    document_mode: Optional[str] = None
    facts: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LegalQueryResponse(BaseModel):
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    pipeline_version: Optional[str] = None
    orchestrator_version: Optional[str] = None
    query: str
    jurisdiction: Optional[str] = None
    forum: Optional[str] = None
    case_domain: Optional[str] = None
    case_domains: list[str] = Field(default_factory=list)
    action_slug: Optional[str] = None
    source_mode: Optional[str] = None
    strategy_mode: Optional[str] = None
    dominant_factor: Optional[str] = None
    blocking_factor: Optional[str] = None
    execution_readiness: Optional[str] = None
    confidence_score: Optional[float] = None
    confidence_label: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    response_text: Optional[str] = None
    documents_considered: int = 0
    retrieval_bundle: dict = Field(default_factory=dict)
    orchestrator_decision: dict = Field(default_factory=dict)
    orchestrator_metadata: dict = Field(default_factory=dict)
    retrieved_items: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    classification: dict = Field(default_factory=dict)
    case_structure: dict = Field(default_factory=dict)
    reasoning: dict = Field(default_factory=dict)
    normative_reasoning: dict = Field(default_factory=dict)
    citation_validation: dict = Field(default_factory=dict)
    hallucination_guard: dict = Field(default_factory=dict)
    procedural_strategy: dict = Field(default_factory=dict)
    question_engine_result: dict = Field(default_factory=dict)
    case_theory: dict = Field(default_factory=dict)
    case_evaluation: dict = Field(default_factory=dict)
    conflict_evidence: dict = Field(default_factory=dict)
    evidence_reasoning_links: dict = Field(default_factory=dict)
    jurisprudence_analysis: dict = Field(default_factory=dict)
    case_profile: dict = Field(default_factory=dict)
    case_strategy: dict = Field(default_factory=dict)
    legal_strategy: dict = Field(default_factory=dict)
    output_modes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    conversational: dict[str, Any] = Field(default_factory=dict)
    conversational_response: dict[str, Any] = Field(default_factory=dict)
    conversation_state: dict[str, Any] = Field(default_factory=dict)
    dialogue_policy: dict[str, Any] = Field(default_factory=dict)
    generated_document: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    saved_consulta_id: Optional[str] = None
    saved_for_user: bool = False
    saved_at: Optional[str] = None
    persistence_warning: Optional[str] = None
    learning_log_id: Optional[str] = None
    safety_status: str = "normal"
    dominant_safety_reason: Optional[str] = None
    fallback_type: Optional[str] = None
    severity: str = "info"
    excluded_from_learning: bool = False
    protective_mode_active: bool = False
    safety_reasons: list[str] = Field(default_factory=list)
    input_guardrail: dict = Field(default_factory=dict)
    usage_guardrail: dict = Field(default_factory=dict)


class LegalQueryExportRequest(BaseModel):
    response: Dict[str, Any] = Field(default_factory=dict)
    request_context: Dict[str, Any] = Field(default_factory=dict)


def _extract_session_id(metadata: Dict[str, Any]) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None
    for key in ("session_id", "sessionId", "chat_session_id", "chatSessionId"):
        value = metadata.get(key)
        if value is not None:
            normalized = str(value).strip()
            if normalized:
                return normalized
    return None


def _extract_conversation_id(metadata: Dict[str, Any]) -> Optional[str]:
    if not isinstance(metadata, dict):
        return None
    for key in ("conversation_id", "conversationId"):
        value = metadata.get(key)
        if value is not None:
            normalized = str(value).strip()
            if normalized:
                return normalized
    return None


def _extract_source_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return str(forwarded_for.split(",")[0]).strip() or None
    client = getattr(request, "client", None)
    if client is not None:
        return str(getattr(client, "host", "")).strip() or None
    return None


def _build_persistence_warning() -> str:
    return "La respuesta juridica fue generada, pero no se pudo guardar en el historial del usuario."


def _safe_rollback(db: Any) -> None:
    rollback = getattr(db, "rollback", None)
    if callable(rollback):
        rollback()


def _extract_response_summary(response_dict: Dict[str, Any]) -> Optional[str]:
    reasoning = response_dict.get("reasoning") or {}
    if isinstance(reasoning, dict):
        summary = reasoning.get("short_answer") or reasoning.get("case_analysis")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    summary = response_dict.get("query")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return None


def _safe_track_session_cycle(
    db: Session,
    *,
    session_id: str | None,
    user_id: str | None,
    query: str,
    jurisdiction: str | None,
    case_domain: str | None,
    conversational: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> None:
    if not session_id:
        return
    try:
        session_tracking_service.track_legal_query_cycle(
            db,
            session_id=session_id,
            user_id=user_id,
            query=query,
            jurisdiction=jurisdiction,
            case_domain=case_domain,
            conversational=conversational,
            metadata=metadata,
        )
    except Exception:
        _safe_rollback(db)
        logger.exception("No se pudo registrar analytics de sesion.", extra={"session_id": session_id})


def _safe_track_error(
    db: Session,
    *,
    session_id: str | None,
    user_id: str | None,
    error_type: str,
    message: str,
    jurisdiction: str | None = None,
) -> None:
    if not session_id:
        return
    try:
        session_tracking_service.track_backend_error(
            db,
            session_id=session_id,
            user_id=user_id,
            error_type=error_type,
            message=message,
            jurisdiction=jurisdiction,
        )
    except Exception:
        _safe_rollback(db)
        logger.exception("No se pudo registrar error analytics de sesion.", extra={"session_id": session_id})


@router.post("/legal-query", response_model=LegalQueryResponse)
def legal_query(
    payload: LegalQueryRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
) -> LegalQueryResponse | JSONResponse:
    start_time = time.perf_counter()
    metadata = dict(payload.metadata or {})
    request_id = str(metadata.get("request_id") or metadata.get("requestId") or uuid4())
    metadata["request_id"] = request_id
    source_ip = _extract_source_ip(request)
    processing_log_id: Optional[str] = None
    session_id = session_tracking_service.ensure_session_id(_extract_session_id(metadata))
    metadata["session_id"] = session_id

    pm_status = evaluate_protective_mode()
    pm_active = pm_status["protective_mode_active"]
    observability_context = start_beta_observability_context(
        request_id=request_id,
        trace_id=request_id,
        query=payload.query,
        jurisdiction=payload.jurisdiction,
        forum=payload.forum,
        user_id=str(getattr(current_user, "id", "") or "") or None,
        session_id=session_id,
        protective_mode_active=pm_active,
        metadata={"route_path": str(request.url.path)},
    )

    input_guardrail = evaluate_query_input(payload.query)
    update_beta_observability_context(
        observability_context,
        normalized_query=input_guardrail.get("normalized_query"),
        safety_status=input_guardrail.get("safety_status"),
    )
    if input_guardrail["decision"] == "rejected":
        safety_outcome = resolve_safety_outcome(input_guardrail)
        sev = classify_severity(
            event_type="input_rejected",
            safety_status=safety_outcome["safety_status"],
            fallback_type=safety_outcome["fallback_type"],
        )
        record_safety_event(
            db,
            event_type="input_rejected",
            safety_status=safety_outcome["safety_status"],
            dominant_safety_reason=safety_outcome["dominant_safety_reason"],
            fallback_type=safety_outcome["fallback_type"],
            request_id=request_id,
            user_id=getattr(current_user, "id", None),
            source_ip=source_ip,
            route_path=str(request.url.path),
            reason=safety_outcome["dominant_safety_reason"] or "input_rejected",
            reason_category="input_guardrail",
            excluded_from_learning=True,
            detail={"input_guardrail": input_guardrail},
            severity=sev,
            protective_mode_active=pm_active,
        )
        fail_beta_observability_context(
            observability_context,
            error_message="input_rejected",
            response_status="blocked",
            total_duration_ms=int((time.perf_counter() - start_time) * 1000),
        )
        _safe_track_error(
            db,
            session_id=session_id,
            user_id=str(getattr(current_user, "id", "") or "") or None,
            error_type="error_validation",
            message="input_rejected",
            jurisdiction=payload.jurisdiction,
        )
        return build_safety_error_response(
            status_code=422,
            request_id=request_id,
            safety_status=safety_outcome["safety_status"],
            dominant_safety_reason=safety_outcome["dominant_safety_reason"],
            fallback_type=safety_outcome["fallback_type"],
            message="La consulta no pudo procesarse por formato invalido.",
            reasons=safety_outcome["safety_reasons"],
            excluded_from_learning=True,
            details={"input_guardrail": input_guardrail},
            severity=sev,
            protective_mode_active=pm_active,
        )

    usage_guardrail = evaluate_usage_guardrail(
        user_id=getattr(current_user, "id", None),
        source_ip=source_ip,
        route_path=str(request.url.path),
        bucket="heavy_query",
    )
    if not usage_guardrail["allowed"]:
        safety_outcome = resolve_safety_outcome(input_guardrail, usage_guardrail)
        sev = classify_severity(
            event_type="rate_limited",
            safety_status=safety_outcome["safety_status"],
            fallback_type=safety_outcome["fallback_type"],
        )
        record_safety_event(
            db,
            event_type="rate_limited",
            safety_status=safety_outcome["safety_status"],
            dominant_safety_reason=safety_outcome["dominant_safety_reason"],
            fallback_type=safety_outcome["fallback_type"],
            request_id=request_id,
            user_id=getattr(current_user, "id", None),
            source_ip=source_ip,
            route_path=str(request.url.path),
            reason=safety_outcome["dominant_safety_reason"] or "rate_limited",
            reason_category="usage_guardrail",
            excluded_from_learning=True,
            detail={"usage_guardrail": usage_guardrail},
            severity=sev,
            protective_mode_active=pm_active,
        )
        update_beta_observability_context(
            observability_context,
            safety_status=safety_outcome["safety_status"],
        )
        fail_beta_observability_context(
            observability_context,
            error_message="rate_limited",
            response_status="blocked",
            total_duration_ms=int((time.perf_counter() - start_time) * 1000),
        )
        _safe_track_error(
            db,
            session_id=session_id,
            user_id=str(getattr(current_user, "id", "") or "") or None,
            error_type="error_validation",
            message="rate_limited",
            jurisdiction=payload.jurisdiction,
        )
        return build_safety_error_response(
            status_code=429,
            request_id=request_id,
            safety_status=safety_outcome["safety_status"],
            dominant_safety_reason=safety_outcome["dominant_safety_reason"],
            fallback_type=safety_outcome["fallback_type"],
            message="Se alcanzo temporalmente el limite de uso para esta ruta.",
            reasons=safety_outcome["safety_reasons"],
            excluded_from_learning=True,
            retry_after_seconds=usage_guardrail["retry_after_seconds"],
            details={"usage_guardrail": usage_guardrail},
            severity=sev,
            protective_mode_active=pm_active,
        )

    effective_query = input_guardrail["normalized_query"]

    # Protective mode: reduce max query length when active
    if pm_active and len(effective_query) > pm_status["effective_max_query_length"]:
        effective_query = effective_query[:pm_status["effective_max_query_length"]].rstrip()
    clarification_turn = prepare_legal_query_turn(
        query=effective_query,
        facts=payload.facts,
        metadata=metadata,
    )
    effective_query = clarification_turn.effective_query
    effective_facts = clarification_turn.merged_facts
    metadata = clarification_turn.metadata
    update_beta_observability_context(
        observability_context,
        normalized_query=effective_query,
    )

    try:
        processing_log = query_logging_service.create_processing_log(
            db,
            request_id=request_id,
            pipeline_version=PIPELINE_VERSION,
            user_query_original=payload.query,
            user_query_normalized=effective_query,
            jurisdiction_requested=payload.jurisdiction,
            forum_requested=payload.forum,
            facts=effective_facts,
            metadata=metadata,
        )
        processing_log_id = processing_log.id
    except Exception:
        _safe_rollback(db)
        logger.exception("No se pudo crear el log inicial de la consulta juridica.", extra={"request_id": request_id})

    try:
        result = _orchestrator.run(
            query=effective_query,
            jurisdiction=payload.jurisdiction,
            forum=payload.forum,
            top_k=payload.top_k,
            document_mode=payload.document_mode,
            facts=effective_facts,
            metadata=metadata,
            db=db,
            observability_context=observability_context,
        )
    except QueryOrchestratorError as exc:
        try:
            query_logging_service.fail_log(
                db,
                log_id=processing_log_id,
                request_id=exc.request_id,
                pipeline_version=PIPELINE_VERSION,
                user_query_original=payload.query,
                user_query_normalized=effective_query,
                jurisdiction_requested=payload.jurisdiction,
                forum_requested=payload.forum,
                facts=effective_facts,
                metadata=metadata,
                error_message=exc.message,
            )
        except Exception:
            _safe_rollback(db)
            logger.exception("No se pudo marcar como failed el log de la consulta juridica.", extra={"request_id": request_id})

        error_sev = classify_severity(
            event_type="fallback_triggered",
            safety_status="degraded",
            fallback_type="internal_error",
        )
        record_safety_event(
            db,
            event_type="fallback_triggered",
            safety_status="degraded",
            dominant_safety_reason="controlled_orchestrator_error",
            fallback_type="internal_error",
            request_id=exc.request_id,
            user_id=getattr(current_user, "id", None),
            source_ip=source_ip,
            route_path=str(request.url.path),
            reason="controlled_orchestrator_error",
            reason_category="processing_error",
            excluded_from_learning=True,
            detail={"message": exc.message},
            severity=error_sev,
            protective_mode_active=pm_active,
        )
        update_beta_observability_context(
            observability_context,
            safety_status="degraded",
        )
        fail_beta_observability_context(
            observability_context,
            error_message=exc.message,
            response_status="blocked",
            total_duration_ms=int((time.perf_counter() - start_time) * 1000),
        )
        _safe_track_error(
            db,
            session_id=session_id,
            user_id=str(getattr(current_user, "id", "") or "") or None,
            error_type="error_backend",
            message=exc.message,
            jurisdiction=payload.jurisdiction,
        )
        return build_safety_error_response(
            status_code=500,
            request_id=exc.request_id,
            safety_status="degraded",
            dominant_safety_reason="controlled_orchestrator_error",
            fallback_type="internal_error",
            message="La consulta no pudo procesarse normalmente en este momento.",
            reasons=["controlled_orchestrator_error"],
            excluded_from_learning=True,
            details={"message": exc.message},
            severity=error_sev,
            protective_mode_active=pm_active,
        )

    try:
        query_logging_service.complete_log(
            db,
            log_id=processing_log_id,
            request_id=request_id,
            result=result,
        )
    except Exception:
        _safe_rollback(db)
        logger.exception("No se pudo completar el log estructurado de la consulta juridica.", extra={"request_id": request_id})

    response_dict = dict(result.final_output.api_payload)
    response_dict.setdefault("warnings", [])
    response_dict.setdefault("request_id", request_id)
    response_dict.setdefault("session_id", session_id)
    response_dict.setdefault("pipeline_version", PIPELINE_VERSION)
    response_dict.setdefault("orchestrator_version", PIPELINE_VERSION)
    response_dict.setdefault("safety_status", input_guardrail["safety_status"])
    response_dict.setdefault("dominant_safety_reason", input_guardrail.get("dominant_safety_reason"))
    response_dict.setdefault("fallback_type", input_guardrail.get("fallback_type"))
    response_dict.setdefault("safety_reasons", list(input_guardrail["reasons"]))
    response_dict.setdefault("input_guardrail", dict(input_guardrail))
    response_dict.setdefault("usage_guardrail", dict(usage_guardrail))

    effective_jurisdiction = payload.jurisdiction or response_dict.get("jurisdiction") or "jujuy"
    effective_forum = payload.forum or response_dict.get("forum") or ""
    effective_document_mode = payload.document_mode or ""

    excluded_from_learning = should_exclude_from_learning(
        input_guardrail=input_guardrail,
        rate_limit_guardrail=usage_guardrail,
        response_payload=response_dict,
    )
    if input_guardrail["decision"] == "degraded":
        record_safety_event(
            db,
            event_type="request_degraded",
            safety_status="degraded",
            dominant_safety_reason=input_guardrail.get("dominant_safety_reason"),
            fallback_type=input_guardrail.get("fallback_type") or "degraded_mode",
            request_id=request_id,
            user_id=getattr(current_user, "id", None),
            source_ip=source_ip,
            route_path=str(request.url.path),
            reason=input_guardrail["reasons"][0] if input_guardrail["reasons"] else "input_truncated_for_safety",
            reason_category="input_guardrail",
            excluded_from_learning=True,
            detail={"input_guardrail": input_guardrail},
        )

    if response_dict.get("fallback_used", False):
        fallback_type = infer_fallback_type(
            fallback_reason=str(response_dict.get("fallback_reason") or ""),
            safety_status="degraded",
        ) or "degraded_mode"
        record_safety_event(
            db,
            event_type="fallback_triggered",
            safety_status="degraded",
            dominant_safety_reason=str(response_dict.get("fallback_reason") or "pipeline_fallback_used"),
            fallback_type=fallback_type,
            request_id=request_id,
            user_id=getattr(current_user, "id", None),
            source_ip=source_ip,
            route_path=str(request.url.path),
            reason=str(response_dict.get("fallback_reason") or "pipeline_fallback_used"),
            reason_category="pipeline_fallback",
            excluded_from_learning=True,
            detail={
                "fallback_reason": response_dict.get("fallback_reason"),
                "warnings": response_dict.get("warnings"),
            },
        )
        response_dict["fallback_type"] = fallback_type

    safety_outcome = resolve_safety_outcome(
        input_guardrail,
        usage_guardrail,
        {
            "safety_status": "degraded" if response_dict.get("fallback_used", False) else response_dict.get("safety_status", "normal"),
            "reasons": (
                [str(response_dict.get("fallback_reason") or "pipeline_fallback_used")]
                if response_dict.get("fallback_used", False)
                else []
            ),
            "dominant_safety_reason": (
                str(response_dict.get("fallback_reason") or "pipeline_fallback_used")
                if response_dict.get("fallback_used", False)
                else response_dict.get("dominant_safety_reason")
            ),
            "fallback_type": (
                response_dict.get("fallback_type")
                or infer_fallback_type(
                    fallback_reason=str(response_dict.get("fallback_reason") or ""),
                    safety_status=response_dict.get("safety_status"),
                )
            ),
        },
    )
    response_dict["safety_status"] = safety_outcome["safety_status"]
    response_dict["dominant_safety_reason"] = safety_outcome["dominant_safety_reason"]
    response_dict["fallback_type"] = safety_outcome["fallback_type"]
    response_dict["safety_reasons"] = safety_outcome["safety_reasons"]
    response_dict["severity"] = classify_severity(
        event_type="request_degraded" if response_dict.get("fallback_used") else "normal",
        safety_status=safety_outcome["safety_status"],
        fallback_type=safety_outcome["fallback_type"],
    )
    response_dict["protective_mode_active"] = pm_active

    saved_consulta_id: Optional[str] = None
    saved_at: Optional[str] = None
    persistence_warning: Optional[str] = None
    db_persisted = False
    conversation_id = _extract_conversation_id(payload.metadata)

    if current_user is not None:
        try:
            consulta = consulta_service.save_consulta(
                db=db,
                user_id=current_user.id,
                query=payload.query,
                resultado=response_dict,
                jurisdiction=effective_jurisdiction,
                forum=effective_forum,
                document_mode=effective_document_mode,
                facts=effective_facts,
                conversation_id=conversation_id,
            )
            saved_consulta_id = consulta.id
            saved_at = consulta.created_at.isoformat() if consulta.created_at else None
            db_persisted = True
        except Exception:
            _safe_rollback(db)
            persistence_warning = _build_persistence_warning()

    response_time_ms = int((time.perf_counter() - start_time) * 1000)
    response_summary = _extract_response_summary(response_dict)
    learning_log_id: Optional[str] = None

    if not excluded_from_learning and current_user is not None:
        try:
            learning_log = learning_log_service.save_learning_log(
                db,
                user_id=str(getattr(current_user, "id", "") or "") or None,
                session_id=session_id,
                conversation_id=conversation_id,
                payload=payload,
                orchestrator_result=result,
                response_time_ms=response_time_ms,
                orchestrator_version=PIPELINE_VERSION,
            )
            db.commit()
            learning_log_id = learning_log.id
        except Exception:
            _safe_rollback(db)
            logger.warning(
                "No se pudo persistir el learning log de la consulta juridica.",
                extra={"request_id": request_id},
                exc_info=True,
            )
    else:
        record_safety_event(
            db,
            event_type="excluded_from_learning",
            safety_status=response_dict.get("safety_status", "degraded"),
            dominant_safety_reason=response_dict.get("dominant_safety_reason"),
            fallback_type=response_dict.get("fallback_type"),
            request_id=request_id,
            user_id=getattr(current_user, "id", None),
            source_ip=source_ip,
            route_path=str(request.url.path),
            reason=response_dict.get("dominant_safety_reason") or response_dict.get("fallback_reason") or (input_guardrail["reasons"][0] if input_guardrail["reasons"] else "excluded_from_learning"),
            reason_category="learning_safety",
            excluded_from_learning=True,
            detail={
                "input_guardrail": input_guardrail,
                "fallback_used": response_dict.get("fallback_used", False),
            },
        )

    log_entry = build_chat_log_entry(
        user=current_user,
        session_id=session_id,
        query=payload.query,
        response_payload=response_dict,
        response_summary=response_summary,
        facts=payload.facts,
        metadata=metadata,
        document_mode=effective_document_mode,
        jurisdiction=effective_jurisdiction,
        forum=effective_forum,
        case_domain=response_dict.get("case_domain"),
        case_domains=response_dict.get("case_domains"),
        confidence=response_dict.get("confidence_score", response_dict.get("confidence")),
        warnings=response_dict.get("warnings"),
        response_time_ms=response_time_ms,
        has_generated_document=bool(response_dict.get("generated_document")),
        saved_consulta_id=saved_consulta_id,
        saved_for_user=db_persisted,
        saved_at=saved_at,
        persistence_warning=persistence_warning,
        db_persisted=db_persisted,
    )
    log_chat_interaction(log_entry)

    response_dict["saved_consulta_id"] = saved_consulta_id
    response_dict["saved_for_user"] = db_persisted
    response_dict["saved_at"] = saved_at
    response_dict["persistence_warning"] = persistence_warning
    response_dict["learning_log_id"] = learning_log_id
    response_dict["request_id"] = response_dict.get("request_id") or request_id
    response_dict["session_id"] = response_dict.get("session_id") or session_id
    response_dict["orchestrator_version"] = PIPELINE_VERSION
    response_dict["excluded_from_learning"] = excluded_from_learning
    _safe_track_session_cycle(
        db,
        session_id=session_id,
        user_id=str(getattr(current_user, "id", "") or "") or None,
        query=payload.query,
        jurisdiction=effective_jurisdiction,
        case_domain=response_dict.get("case_domain"),
        conversational=response_dict.get("conversational"),
        metadata=metadata,
    )
    update_beta_observability_context(
        observability_context,
        jurisdiction=effective_jurisdiction,
        user_id=str(getattr(current_user, "id", "") or "") or None,
        session_id=session_id,
        final_confidence=response_dict.get("confidence_score", response_dict.get("confidence")),
        fallback_detected=bool(response_dict.get("fallback_used")),
        sanitized_output=bool(getattr(result.final_output, "sanitized_output", False)),
        protective_mode_active=pm_active,
        safety_status=response_dict.get("safety_status"),
        internal_warnings=[str(item).strip() for item in (result.final_output.warnings or []) if str(item).strip()],
        top_level_domains_detected=[str(item).strip() for item in (response_dict.get("case_domains") or []) if str(item).strip()],
        final_case_domain=response_dict.get("case_domain"),
        final_action_slug=response_dict.get("action_slug"),
        strategy_mode=response_dict.get("strategy_mode"),
        dominant_factor=response_dict.get("dominant_factor"),
        citation_validation_status=response_dict.get("citation_validation", {}).get("status"),
        stage_durations_ms={
            "normalization_ms": int(getattr(result.timings, "normalization_ms", 0) or 0),
            "orchestrator_pipeline_ms": int(getattr(result.timings, "pipeline_ms", 0) or 0),
            "orchestrator_classification_ms": int(getattr(result.timings, "classification_ms", 0) or 0),
            "orchestrator_retrieval_ms": int(getattr(result.timings, "retrieval_ms", 0) or 0),
            "orchestrator_strategy_ms": int(getattr(result.timings, "strategy_ms", 0) or 0),
            "postprocess_ms": int(getattr(result.timings, "postprocess_ms", 0) or 0),
            "final_assembly_ms": int(getattr(result.timings, "final_assembly_ms", 0) or 0),
        },
    )
    finalize_beta_observability_context(
        observability_context,
        response_status=derive_response_status(
            fallback_detected=bool(response_dict.get("fallback_used")),
            safety_status=response_dict.get("safety_status"),
        ),
        total_duration_ms=response_time_ms,
    )

    return LegalQueryResponse(**response_dict)


@router.post("/legal-query/export/docx")
def export_legal_query_docx(payload: LegalQueryExportRequest) -> StreamingResponse:
    query = str(
        payload.response.get("query")
        or payload.request_context.get("query")
        or "resultado_juridico"
    ).strip()
    safe_name = "_".join(query.lower().split())[:48] or "resultado_juridico"

    content = build_legal_query_docx(
        response_payload=payload.response,
        request_context=payload.request_context,
    )

    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.docx"',
        },
    )
