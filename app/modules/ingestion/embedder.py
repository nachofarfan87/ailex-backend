"""
AILEX — Generador de embeddings (adaptador de compatibilidad).

Mantiene la API pública original para que IngestionService
y el código existente funcionen sin cambios.

Internamente delega a app.ai.embeddings (capa provider-agnostic).
Para nuevo código, usar directamente:

    from app.ai.embeddings.factory import create_provider_from_settings
    provider = create_provider_from_settings()
"""

from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.factory import create_provider
from typing import Optional


class EmbeddingGenerator:
    """
    Adaptador de compatibilidad sobre EmbeddingProvider.

    Expone la API original (generate, generate_batch, cosine_similarity,
    to_json, from_json) delegando al proveedor subyacente.

    El proveedor se selecciona según los parámetros del constructor:
    - use_placeholder=True  → StubEmbeddingProvider (hash-based)
    - use_placeholder=False → proveedor según settings
    """

    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM = 384

    def __init__(self, model_name: str = None, use_placeholder: bool = False):
        self.use_placeholder = use_placeholder
        self._model_name = model_name or self.DEFAULT_MODEL

        if use_placeholder:
            self._provider: EmbeddingProvider = create_provider(
                provider="stub",
                dimension=self.EMBEDDING_DIM,
            )
        else:
            self._provider = create_provider(
                provider="sentence_transformers",
                model=self._model_name,
                dimension=self.EMBEDDING_DIM,
            )

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def generate(self, text: str) -> list[float]:
        """Generar embedding para un texto."""
        return self._provider.embed_text(text)

    def generate_batch(self, texts: list[str]) -> list[list[float]]:
        """Generar embeddings para múltiples textos (más eficiente)."""
        return self._provider.embed_batch(texts)

    def to_json(self, embedding: list[float]) -> str:
        """Serializar embedding a JSON para almacenar en DB."""
        return self._provider.to_json(embedding)

    def from_json(self, json_str: str) -> Optional[list[float]]:
        """Deserializar embedding desde JSON."""
        return self._provider.from_json(json_str)

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calcular similitud coseno entre dos vectores."""
        return self._provider.cosine_similarity(a, b)
