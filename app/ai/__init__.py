"""
AILEX — Capa de IA.

Abstracciones provider-agnostic para:
- Embeddings (stub | sentence_transformers | openai)
- LLM (futuro)
"""

from app.ai.embeddings.factory import create_provider, create_provider_from_settings

__all__ = ["create_provider", "create_provider_from_settings"]
