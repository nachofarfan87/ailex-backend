"""
AILEX — API Routes: Workflows jurídicos integrados.
"""

from fastapi import APIRouter

from app.modules.workflows.schemas import (
    WorkflowNotificationRequest,
    WorkflowNotificationResponse,
)
from app.modules.workflows.service import WorkflowService

router = APIRouter()
_service = WorkflowService()


@router.post("/notification-response", response_model=WorkflowNotificationResponse)
async def workflow_notification_response(request: WorkflowNotificationRequest):
    """Ejecutar el flujo integrado desde notificación hasta borrador revisado."""
    return await _service.notification_response(request)
