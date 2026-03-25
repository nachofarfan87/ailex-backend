"""
AILEX — Proveedor de embeddings con sentence-transformers.

Modelo recomendado para español jurídico:
  paraphrase-multilingual-MiniLM-L12-v2 (384 dims)

Instalación:
  pip install sentence-transformers

El modelo se carga de manera lazy en el primer uso.
Soporta GPU si está disponible (torch con CUDA).
"""

from app.ai.embeddings.base import EmbeddingProvider


class SentenceTransformersProvider(EmbeddingProvider):
    """
    Embeddings reales con sentence-transformers.

    Produce vectores semánticamente significativos que permiten
    búsqueda por similitud real de contenido, no solo por palabras clave.

    El modelo paraphrase-multilingual-MiniLM-L12-v2 está entrenado
    en 50+ idiomas y funciona bien para español jurídico.
    """

    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None
        self._dimension = 384  # se actualiza tras cargar el modelo

    def _load_model(self):
        """Carga lazy del modelo (solo al primer uso)."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
        except ImportError:
            raise RuntimeError(
                "sentence-transformers no instalado. "
                "Instalar con: pip install sentence-transformers"
            )

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> list[float]:
        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        )
        return [e.tolist() for e in embeddings]
