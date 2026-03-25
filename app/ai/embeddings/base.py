"""
AILEX — Interfaz abstracta para proveedores de embeddings.

Permite cambiar entre stub, sentence-transformers, OpenAI u otros
sin modificar el código de consumo.

Todos los proveedores deben implementar:
- embed_text(text) -> list[float]
- embed_batch(texts) -> list[list[float]]

Helpers comunes están implementados aquí (cosine_similarity, to_json, from_json).
"""

import json
from abc import ABC, abstractmethod
from typing import Optional


class EmbeddingProvider(ABC):
    """
    Interfaz abstracta para proveedores de embeddings vectoriales.

    Uso:
        provider = create_provider_from_settings()
        vector = provider.embed_text("plazo de contestación de demanda")
        vectors = provider.embed_batch(["texto 1", "texto 2"])
        sim = provider.cosine_similarity(vector_a, vector_b)
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensión del vector de embedding."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nombre del modelo/proveedor."""
        ...

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """
        Generar embedding para un texto.

        Returns:
            Vector normalizado como lista de floats.
        """
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generar embeddings para múltiples textos.

        Más eficiente que llamar embed_text() individualmente.

        Returns:
            Lista de vectores normalizados.
        """
        ...

    # ─── Helpers implementados en la base ───────────────

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calcular similitud coseno entre dos vectores (0-1)."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def to_json(self, embedding: list[float]) -> str:
        """Serializar embedding a JSON para almacenar en DB."""
        return json.dumps(embedding)

    def from_json(self, json_str: str) -> Optional[list[float]]:
        """Deserializar embedding desde JSON."""
        if not json_str:
            return None
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None
