"""Production-oriented notification analysis workflow."""

from app.api.schemas.contracts import SourceCitationSchema
from app.modules.legal.detect_risks import detect_risks
from app.modules.legal.extract_procedural_elements import extract_procedural_elements
from app.modules.legal.infer_deadlines import infer_deadlines
from app.modules.legal.normative_citations import resolve_normative_references
from app.modules.search.retrieval import retrieve_sources


async def analyze_notification(
    text: str,
    jurisdiction: str = "Jujuy",
    legal_area: str | None = None,
    top_k: int = 5,
) -> dict:
    """Analyze a judicial notice and return a structured legal memo."""
    elements = extract_procedural_elements(text)
    deadline_info = infer_deadlines(elements, jurisdiction=jurisdiction)
    risk_info = detect_risks(elements, deadline_info)
    sources = await _retrieve_relevant_sources(
        elements=elements,
        jurisdiction=jurisdiction,
        legal_area=legal_area,
        top_k=top_k,
    )
    normative = resolve_normative_references(
        action_slug=elements.get("procedural_action_slug"),
        jurisdiction=jurisdiction,
        forum=legal_area,
    )
    confidence = _compute_confidence(elements, deadline_info, sources)

    memo = {
        "document_detected": elements["document_detected"],
        "court": elements["court"],
        "case_number": elements["case_number"],
        "notification_date": deadline_info["notification_date"],
        "procedural_action": elements["procedural_action"],
        "deadline": deadline_info["deadline"],
        "critical_date": deadline_info["critical_date"],
        "procedural_risks": risk_info["procedural_risks"],
        "recommended_next_step": risk_info["recommended_next_step"],
        "observations": risk_info["observations"],
        "relevant_sources": sources,
        "confidence": confidence,
        "normalized_text": elements["normalized_text"],
        "deadline_detections": deadline_info["detections"],
        # V1 deadline calculation fields
        "estimated_due_date": deadline_info.get("estimated_due_date", ""),
        "deadline_type": deadline_info.get("deadline_type", ""),
        "deadline_basis": deadline_info.get("deadline_basis", ""),
        "deadline_warning": deadline_info.get("deadline_warning", ""),
        # Normative citation fields
        "normative_references": normative["normative_references"],
        "normative_confidence": normative["normative_confidence"],
        "normative_warning": normative["normative_warning"],
        "normative_summary": normative["normative_summary"],
    }
    return memo


async def _retrieve_relevant_sources(
    elements: dict,
    jurisdiction: str,
    legal_area: str | None,
    top_k: int,
) -> list[SourceCitationSchema]:
    query_parts = [
        elements.get("procedural_action") or "",
        elements.get("document_detected") or "",
        "codigo procesal",
        jurisdiction,
    ]
    if legal_area:
        query_parts.append(legal_area)

    query = " ".join(part for part in query_parts if part).strip()
    return await retrieve_sources(
        query=query,
        module="notifications",
        jurisdiction=jurisdiction,
        legal_area=legal_area,
        top_k=top_k,
    )


def _compute_confidence(
    elements: dict,
    deadline_info: dict,
    sources: list[SourceCitationSchema],
) -> str:
    score = 0
    if elements.get("procedural_action") and elements.get("procedural_action") != "actuacion no determinada":
        score += 1
    if elements.get("court"):
        score += 1
    if elements.get("case_number"):
        score += 1
    if deadline_info.get("deadline"):
        score += 1
    if sources:
        score += 1

    if score >= 4 and (deadline_info.get("deadline") or deadline_info.get("critical_date")):
        return "high"
    if score >= 2:
        return "medium"
    return "low"
