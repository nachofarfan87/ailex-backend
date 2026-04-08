"""
AILEX - Entry point de la aplicacion FastAPI.
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.adaptive_learning import router as adaptive_learning_router
from app.api.learning import router as learning_router
from app.api.learning_control import router as learning_control_router
from app.api.learning_observability import router as learning_observability_router
from app.api.legal_query import router as legal_query_router
from app.api.session_analytics import router as session_analytics_router
from app.api.auto_healing import router as auto_healing_router
from app.api.monitoring import router as monitoring_router
from app.api.safety import router as safety_router
from app.api.routes import (
    admin_legal_queries,
    analysis,
    audit,
    config,
    documents,
    generation,
    notifications,
    search,
    sources,
    strategy,
    workflow,
)
from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.consultas import router as consultas_router
from app.api.routes.expedientes import router as expedientes_router
from app.config import settings
from app.services import learning_runtime_config
from app.services.learning_runtime_config_store import load_latest_runtime_config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Valida configuracion y conectividad de la DB antes de aceptar requests."""
    import app.db.models  # noqa: F401
    import app.db.legal_query_log_models  # noqa: F401
    import app.models.learning_log  # noqa: F401
    import app.models.learning_action_log  # noqa: F401
    import app.models.learning_human_audit  # noqa: F401
    import app.models.learning_impact_log  # noqa: F401
    import app.models.learning_review  # noqa: F401
    import app.models.orchestrator_config_snapshot  # noqa: F401
    import app.models.orchestrator_tuning_event  # noqa: F401
    import app.models.system_safety_event  # noqa: F401
    import app.models.session_analytics  # noqa: F401
    import app.models.conversation_state_snapshot  # noqa: F401
    import app.models.case_state  # noqa: F401
    import app.services.learning_runtime_config_store  # noqa: F401
    import app.db.user_models  # noqa: F401
    from app.db.database import SessionLocal, init_db

    settings.validate_runtime_configuration()
    logger.info(
        "Iniciando AILEX backend.",
        extra={
            "env": settings.env,
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "database_backend": settings.database_backend,
            "database_url": settings.safe_database_url,
        },
    )
    init_db()
    db = SessionLocal()
    try:
        config = load_latest_runtime_config(db)
        if config:
            learning_runtime_config.apply_persisted_runtime_config(config)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI Juridica para practica judicial en Jujuy, Argentina. "
        "Sistema de apoyo profesional para abogados litigantes."
    ),
    lifespan=lifespan,
)

# El 400 de los preflight viene del CORSMiddleware, no del router.
# En desarrollo conviene permitir cualquier header/metodo y aceptar localhost/127.0.0.1
# con puertos variables para evitar rechazos previos al dispatch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.effective_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=86400,
)


@app.options("/{full_path:path}", include_in_schema=False)
async def cors_preflight_handler(full_path: str, request: Request) -> Response:
    """
    Fallback defensivo para cualquier preflight OPTIONS.

    Si el middleware no intercepta el request por alguna variacion de path,
    esta ruta evita un 404/405 posterior.
    """
    _ = full_path
    _ = request
    return Response(status_code=204)


app.include_router(notifications.router, prefix="/api/notifications", tags=["Notificaciones"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documentos"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analisis"])
app.include_router(generation.router, prefix="/api/generation", tags=["Generacion"])
app.include_router(audit.router, prefix="/api/audit", tags=["Auditoria"])
app.include_router(strategy.router, prefix="/api/strategy", tags=["Estrategia"])
app.include_router(workflow.router, prefix="/api/workflow", tags=["Workflow"])
app.include_router(sources.router, prefix="/api/sources", tags=["Fuentes"])
app.include_router(config.router, prefix="/api/config", tags=["Configuracion"])
app.include_router(search.router, prefix="/api/search", tags=["Busqueda"])
app.include_router(admin_legal_queries.router)
app.include_router(adaptive_learning_router)
app.include_router(learning_router)
app.include_router(learning_control_router)
app.include_router(learning_observability_router)
app.include_router(legal_query_router)
app.include_router(session_analytics_router)
app.include_router(monitoring_router)
app.include_router(auto_healing_router)
app.include_router(safety_router)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(expedientes_router)
app.include_router(consultas_router)


@app.get("/health", tags=["Sistema"])
async def health_check():
    """Verificacion de estado del sistema."""
    from app.db.database import get_database_info

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.env,
        "database": get_database_info(),
        "cors_origins": settings.cors_origin_list,
        "cors_origin_regex": settings.effective_cors_origin_regex,
    }
