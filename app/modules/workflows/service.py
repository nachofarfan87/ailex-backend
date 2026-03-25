"""
AILEX — Servicio de workflows jurídicos integrados.
"""

from app.modules.workflows.notification_workflow import NotificationResponseWorkflow
from app.modules.workflows.schemas import (
    WorkflowNotificationRequest,
    WorkflowNotificationResponse,
)


class WorkflowService:
    """Punto de acceso a workflows integrados del sistema."""

    def __init__(self):
        self._notification_workflow = NotificationResponseWorkflow()

    async def notification_response(
        self,
        request: WorkflowNotificationRequest,
    ) -> WorkflowNotificationResponse:
        return await self._notification_workflow.run(request)
