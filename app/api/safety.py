from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.db.user_models import User
from app.services.learning_safety_service import get_safety_snapshot


router = APIRouter(prefix="/api/safety", tags=["Safety"])


@router.get("/summary")
def get_safety_summary(
    last_hours: int = Query(default=24, ge=1, le=168),
    recent_limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return get_safety_snapshot(db, last_hours=last_hours, recent_limit=recent_limit)
