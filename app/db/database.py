"""
AILEX - Database bootstrap and session management.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


Base = declarative_base()


DATABASE_BACKEND = settings.database_backend
DATABASE_URL = settings.resolved_database_url
IS_POSTGRES = DATABASE_BACKEND == "postgres"

_SQLITE_ARGS = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={} if IS_POSTGRES else _SQLITE_ARGS,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """
    Validate DB configuration and connectivity.

    Ensure the mapped schema exists, then validate connectivity.

    Alembic remains the primary migration path. ``create_all`` is a safe
    bootstrap fallback for empty databases so startup does not crash before
    persisted runtime config can be read.
    """
    settings.validate_runtime_configuration()
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def get_database_info() -> dict:
    """Runtime DB info for health checks and logs."""
    return {
        "backend": DATABASE_BACKEND,
        "url": settings.safe_database_url,
        "is_postgres": IS_POSTGRES,
    }


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
