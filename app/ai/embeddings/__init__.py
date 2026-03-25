"""
AILEX — Proveedores de embeddings.
"""

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import create_provider, create_provider_from_settings

__all__ = ["EmbeddingProvider", "create_provider", "create_provider_from_settings"]
