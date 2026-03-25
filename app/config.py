"""
AILEX - Configuracion del sistema.
Carga variables de entorno y define settings globales.
"""

import logging
from urllib.parse import urlsplit, urlunsplit
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

DEFAULT_DEV_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
DEFAULT_PROD_CORS_ORIGINS = (
    "https://ailex.com.ar",
    "https://www.ailex.com.ar",
)
DEFAULT_DEV_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?$"
DEFAULT_SECRET_KEY = "cambia_esto_en_produccion_genera_con_openssl_rand_hex_32"
DEFAULT_SQLITE_URL = "sqlite:///./ailex_local.db"

logger = logging.getLogger(__name__)


def _parse_cors_origins(raw_value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, (list, tuple)):
        candidates = [str(item) for item in raw_value]
    else:
        normalized = str(raw_value).strip()
        if not normalized:
            candidates = []
        elif normalized.startswith("[") and normalized.endswith("]"):
            stripped = normalized[1:-1]
            candidates = stripped.split(",")
        else:
            candidates = normalized.split(",")

    parsed: list[str] = []
    for candidate in candidates:
        origin = str(candidate).strip().strip('"').strip("'").rstrip("/")
        if origin and origin not in parsed:
            parsed.append(origin)

    return parsed


def _normalize_database_url(raw_value: str | None) -> str:
    normalized = str(raw_value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("postgres://"):
        return "postgresql://" + normalized[len("postgres://") :]
    return normalized


class Settings(BaseSettings):
    """Configuracion centralizada de AILEX."""

    # App
    env: str = "development"
    app_name: str = "AILEX"
    app_version: str = "0.1.0"
    debug: bool = True
    port: int = 8000

    # Base de datos
    database_url: str = "postgresql://ailex_user:password@localhost:5432/ailex_db"
    rag_store_backend: str = "memory"  # memory | sqlite | postgres
    pgvector_dimension: int = 384

    # RAG - Embeddings
    embedding_provider: str = "stub"  # stub | sentence_transformers | openai
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384
    use_placeholder_embeddings: bool = True  # Compat con codigo anterior (maps to stub)
    rag_default_jurisdiction: str = "Jujuy"

    # RAG - Busqueda
    enable_vector_search: bool = True
    default_top_k: int = 10
    default_search_profile: str = "general"  # general | notifications | generation | audit | strategy

    # OCR
    ocr_language: str = "spa"
    ocr_min_text_chars: int = 80
    ocr_max_pdf_pages: int = 40
    ocr_max_file_size_mb: int = 25
    ocr_dpi: int = 200
    ocr_timeout_seconds: int = 30
    ocr_poppler_path: Optional[str] = None
    ocr_tesseract_cmd: Optional[str] = None

    # RAG - Ranking juridico
    boost_jurisdiccion_local: float = 0.20  # Bonus por jurisdiccion local (Jujuy)
    boost_fuente_primaria: float = 0.15  # Bonus por fuente vinculante (codigo/ley)
    penalize_no_vigente: float = 0.30  # Penalizacion por fuente no vigente

    # CORS
    frontend_url: Optional[str] = None
    cors_origins: str = ""
    cors_origin_regex: str = DEFAULT_DEV_CORS_ORIGIN_REGEX

    # AI Provider (futuro)
    ai_provider: str = "none"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_ai_api_key: Optional[str] = None

    # Confianza
    default_confidence_threshold: float = 0.7
    min_sources_for_assertion: int = 2

    # Auth JWT
    # IMPORTANTE: cambiar en produccion. Generar con: openssl rand -hex 32
    secret_key: str = DEFAULT_SECRET_KEY
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 dias

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug_value(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value

    @field_validator("env", mode="before")
    @classmethod
    def _parse_env_value(cls, value):
        normalized = str(value or "").strip().lower()
        if normalized in {"", "dev", "development", "local"}:
            return "development"
        if normalized in {"prod", "production", "railway"}:
            return "production"
        if normalized in {"staging", "stage"}:
            return "staging"
        return normalized

    @field_validator("port", mode="before")
    @classmethod
    def _parse_port_value(cls, value):
        if value in {None, ""}:
            return 8000
        return int(value)

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url_value(cls, value):
        normalized = _normalize_database_url(value)
        return normalized or DEFAULT_SQLITE_URL

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        configured_origins = _parse_cors_origins(self.cors_origins)
        frontend_origins = _parse_cors_origins(self.frontend_url)

        merged_origins: list[str] = []
        default_origins = DEFAULT_PROD_CORS_ORIGINS if self.is_production else DEFAULT_DEV_CORS_ORIGINS
        for origin in (*default_origins, *configured_origins, *frontend_origins):
            if origin not in merged_origins:
                merged_origins.append(origin)

        if not self.is_production:
            for origin in DEFAULT_DEV_CORS_ORIGINS:
                if origin not in merged_origins:
                    merged_origins.append(origin)

        return merged_origins

    @property
    def effective_cors_origin_regex(self) -> Optional[str]:
        if self.is_production:
            return None
        normalized = str(self.cors_origin_regex or "").strip()
        return normalized or DEFAULT_DEV_CORS_ORIGIN_REGEX

    @property
    def database_backend(self) -> str:
        raw_backend = (self.rag_store_backend or "").strip().lower()
        if raw_backend in {"memory", "sqlite"}:
            return "sqlite"
        if raw_backend == "postgres":
            return "postgres"
        raise ValueError(
            "rag_store_backend invalido. Usar uno de: memory, sqlite, postgres."
        )

    @property
    def resolved_database_url(self) -> str:
        if self.database_backend == "postgres":
            return _normalize_database_url(self.database_url)

        configured_url = (self.database_url or "").strip()
        if configured_url.startswith("sqlite"):
            return configured_url
        return DEFAULT_SQLITE_URL

    @property
    def safe_database_url(self) -> str:
        parsed = urlsplit(self.resolved_database_url)
        if not parsed.password:
            return self.resolved_database_url

        username = parsed.username or ""
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        masked_netloc = f"{username}:***@{host}{port}"
        return urlunsplit((parsed.scheme, masked_netloc, parsed.path, parsed.query, parsed.fragment))

    def validate_runtime_configuration(self) -> None:
        raw_backend = (self.rag_store_backend or "").strip().lower()
        if raw_backend not in {"memory", "sqlite", "postgres"}:
            raise ValueError(
                "rag_store_backend invalido. Usar uno de: memory, sqlite, postgres."
            )

        if not self.debug and self.secret_key == DEFAULT_SECRET_KEY:
            logger.error(
                "Configuracion invalida para produccion: debug=False con secret_key default.",
                extra={"env": self.env, "app_name": self.app_name},
            )
            raise ValueError(
                "Configuracion insegura: debug=False requiere una secret_key distinta de la default."
            )

        if not self.debug and raw_backend == "memory":
            logger.error(
                "Configuracion invalida para produccion: rag_store_backend=memory.",
                extra={"env": self.env, "rag_store_backend": raw_backend},
            )
            raise ValueError(
                "Configuracion ambigua: en produccion usar rag_store_backend=sqlite o rag_store_backend=postgres."
            )

        if self.database_backend == "postgres" and not self.database_url.startswith("postgresql"):
            logger.error(
                "Configuracion inconsistente: rag_store_backend=postgres sin DATABASE_URL PostgreSQL valida.",
                extra={"env": self.env, "database_url": self.safe_database_url},
            )
            raise ValueError(
                "Configuracion inconsistente: rag_store_backend=postgres requiere database_url PostgreSQL."
            )

        if raw_backend == "sqlite" and self.database_url and not (
            self.database_url.startswith("sqlite") or self.database_url.startswith("postgresql")
        ):
            raise ValueError(
                "Configuracion inconsistente: database_url debe ser sqlite:// o postgresql://."
            )

        if self.is_production:
            allowed_prod_origins = set(self.cors_origin_list)
            if not {"https://ailex.com.ar", "https://www.ailex.com.ar"} & allowed_prod_origins:
                logger.error(
                    "Configuracion insegura: produccion sin ailex.com.ar en CORS.",
                    extra={"env": self.env, "cors_origins": sorted(allowed_prod_origins)},
                )
                raise ValueError(
                    "Configuracion insegura: en produccion CORS debe incluir ailex.com.ar."
                )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
