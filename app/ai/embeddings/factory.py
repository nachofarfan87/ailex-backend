"""
AILEX — Factory de proveedores de embeddings.

Crea el proveedor correcto según la configuración.
Toda la lógica de selección está aquí — el resto del código
no necesita conocer los detalles de cada proveedor.

Providers disponibles:
  stub               — hash-based, para desarrollo (sin dependencias)
  sentence_transformers — embeddings reales, requiere instalación
  openai             — placeholder, a implementar en etapa futura
"""

from app.ai.embeddings.base import EmbeddingProvider


def create_provider(
    provider: str = "stub",
    model: str = None,
    dimension: int = 384,
) -> EmbeddingProvider:
    """
    Crear proveedor de embeddings.

    Args:
        provider: "stub" | "sentence_transformers" | "openai"
        model: nombre del modelo (para sentence_transformers)
        dimension: dimensión del vector (para stub)

    Returns:
        EmbeddingProvider listo para usar.
        Si el provider no está disponible, hace fallback a stub.
    """
    if provider == "sentence_transformers":
        try:
            from app.ai.embeddings.sentence_transformers_provider import (
                SentenceTransformersProvider,
            )
            return SentenceTransformersProvider(model)
        except Exception as e:
            print(
                f"AVISO: sentence-transformers no disponible ({e}). "
                "Usando stub (sin semántica real)."
            )

    if provider == "openai":
        # Placeholder — implementar cuando se integre OpenAI
        print(
            "AVISO: OpenAI embedding provider no implementado. "
            "Usando stub."
        )

    from app.ai.embeddings.stub import StubEmbeddingProvider
    return StubEmbeddingProvider(dimension)


def create_provider_from_settings() -> EmbeddingProvider:
    """
    Crear proveedor usando la configuración de settings.

    Lee embedding_provider, embedding_model y embedding_dimension.
    Si use_placeholder_embeddings=True, fuerza stub independientemente.
    """
    from app.config import settings

    # Compat: use_placeholder_embeddings fuerza stub
    if settings.use_placeholder_embeddings:
        provider = "stub"
    else:
        provider = settings.embedding_provider

    return create_provider(
        provider=provider,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )


# Instancia singleton para reutilizar en toda la app
_default_provider: EmbeddingProvider = None


def get_default_provider() -> EmbeddingProvider:
    """Obtener/crear el proveedor por defecto (singleton)."""
    global _default_provider
    if _default_provider is None:
        _default_provider = create_provider_from_settings()
    return _default_provider
