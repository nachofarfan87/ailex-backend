from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_optional_user
from app.db.database import get_db
from app.db.user_models import User
from app.services import session_tracking_service


router = APIRouter(prefix="/api/analytics/sessions", tags=["session-analytics"])


class SessionAnalyticsEventRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    turn_index: int | None = None
    case_domain: str | None = None
    jurisdiction: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/event")
def track_session_event(
    payload: SessionAnalyticsEventRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> dict[str, Any]:
    event = session_tracking_service.record_event(
        db,
        session_id=session_tracking_service.ensure_session_id(payload.session_id),
        user_id=str(getattr(current_user, "id", "") or "") or None,
        event_type=payload.event_type,
        turn_index=payload.turn_index,
        case_domain=payload.case_domain,
        jurisdiction=payload.jurisdiction,
        payload=payload.payload,
    )
    return {"ok": True, "event": event.to_dict()}


@router.get("/summary")
def get_session_summary(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return session_tracking_service.build_summary(db)
