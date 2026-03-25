"""
AILEX — Proveedor de embeddings stub (hash-based).

Para desarrollo sin dependencias externas.

Características:
- Determinístico: mismo texto → mismo vector siempre
- Sin valor semántico real (no puede hacer búsqueda semántica verdadera)
- No requiere instalación de librerías externas
- Rápido, sin I/O de red ni disco

Uso:
    provider = StubEmbeddingProvider(dimension=384)
    vec = provider.embed_text("contestación de demanda")
"""

import hashlib
from app.ai.embeddings.base import EmbeddingProvider


class StubEmbeddingProvider(EmbeddingProvider):
    """
    Embedding placeholder basado en hash SHA-256.

    ADVERTENCIA: Solo para desarrollo. No tiene valor semántico.
    La búsqueda vectorial con este proveedor no refleja similitud real.
    Cambiar a SentenceTransformersProvider para búsqueda semántica real.
    """

    def __init__(self, dimension: int = 384):
        self._dimension = dimension
        self._model_name = f"stub-hash-{dimension}d"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> list[float]:
        """Generar embedding determinístico basado en hash del texto."""
        hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        values = []
        for i in range(self._dimension):
            byte_idx = i % len(hash_bytes)
            values.append((hash_bytes[byte_idx] - 128) / 128.0)
        return values

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]
