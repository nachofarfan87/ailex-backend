"""
AILEX — Precompute corpus embeddings for semantic search.

Generates dense vector embeddings for every article in the legal corpus
using sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2).

Output:
    data/legal/embeddings/corpus_vectors.npy   — (N, 384) float32 matrix
    data/legal/embeddings/corpus_meta.json     — mapping + provenance metadata

Usage:
    cd backend
    python -m scripts.precompute_corpus_embeddings

Requires:
    pip install sentence-transformers numpy

This script is idempotent — re-running it overwrites the previous embeddings.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend/ is importable
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from legal_engine.semantic_index import SemanticLegalIndex

_CORPUS_ROOT = _BACKEND / "data" / "legal" / "ar"
_OUTPUT_DIR = _BACKEND / "data" / "legal" / "embeddings"
_VECTORS_FILE = "corpus_vectors.npy"
_META_FILE = "corpus_meta.json"

_DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
_BATCH_SIZE = 64


def _build_embed_text(chunk) -> str:
    """Build natural-language text for embedding (not the normalized search_text)."""
    return f"{chunk.label}. {chunk.text}"


def main() -> None:
    print(f"[1/4] Loading corpus from {_CORPUS_ROOT} ...")
    index = SemanticLegalIndex(corpus_root=_CORPUS_ROOT)
    chunks = index.load_documents()

    if not chunks:
        print("ERROR: No articles loaded from corpus. Aborting.")
        sys.exit(1)

    print(f"       Loaded {len(chunks)} articles.")

    print(f"[2/4] Loading sentence-transformers model: {_DEFAULT_MODEL} ...")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "ERROR: sentence-transformers not installed.\n"
            "       pip install sentence-transformers"
        )
        sys.exit(1)

    model = SentenceTransformer(_DEFAULT_MODEL)
    dimension = model.get_sentence_embedding_dimension()
    print(f"       Model loaded. Dimension: {dimension}")

    print(f"[3/4] Encoding {len(chunks)} articles (batch_size={_BATCH_SIZE}) ...")
    texts = [_build_embed_text(c) for c in chunks]

    t0 = time.perf_counter()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=_BATCH_SIZE,
        show_progress_bar=True,
    )
    elapsed = time.perf_counter() - t0
    print(f"       Encoding done in {elapsed:.1f}s — shape {vectors.shape}")

    print(f"[4/4] Saving to {_OUTPUT_DIR} ...")
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import numpy as np

    np.save(_OUTPUT_DIR / _VECTORS_FILE, vectors.astype(np.float32))

    meta = {
        "model": _DEFAULT_MODEL,
        "dimension": int(dimension),
        "count": len(chunks),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_root": str(_CORPUS_ROOT),
        "entries": [
            {"source_id": c.source_id, "article": c.article}
            for c in chunks
        ],
    }

    with (_OUTPUT_DIR / _META_FILE).open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    vectors_size_mb = (vectors.shape[0] * vectors.shape[1] * 4) / (1024 * 1024)
    print(f"\n  Done.")
    print(f"  {_OUTPUT_DIR / _VECTORS_FILE}  ({vectors_size_mb:.1f} MB)")
    print(f"  {_OUTPUT_DIR / _META_FILE}")
    print(f"  {meta['count']} articles × {meta['dimension']} dims")


if __name__ == "__main__":
    main()
