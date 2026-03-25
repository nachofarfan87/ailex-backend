"""
AILEX — SemanticLegalIndex

Hybrid semantic retrieval over the internal legal corpus.

Core algorithm (always available — pure Python stdlib):
1. Each article is normalised into a LegalChunk and tokenised.
2. An inverted index stores log-normalised TF-IDF weights per term per doc.
3. Query scoring uses TF-IDF cosine similarity.
4. A small multiplicative boost layer rewards:
   - Matching legal domain   (procedural / constitutional / civil / labor)
   - Target jurisdiction     (optional; Jujuy preferred in that context)
   - Bigram phrase presence  (query phrases found verbatim in the document)

Enhanced mode (optional — requires numpy + sentence-transformers):
5. If precomputed embeddings exist (data/legal/embeddings/), they are loaded
   at build_index() time.
6. At query time the query is embedded with the same model and scored via
   cosine similarity against the precomputed corpus vectors.
7. Final score = 0.6 × embedding_cosine + 0.4 × tfidf_cosine, with the
   existing boost layer applied on top.
8. If embeddings or sentence-transformers are unavailable, the system falls
   back silently to pure TF-IDF.

Build once at startup:
    index = SemanticLegalIndex()
    index.build_index()

Then query freely:
    results = index.semantic_search("plazo para contestar demanda", top_k=5)

Precompute embeddings (one-time):
    python -m scripts.precompute_corpus_embeddings
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


_CORPUS_ROOT = Path(__file__).parent.parent / "data" / "legal" / "ar"

# ---------------------------------------------------------------------------
# Source metadata table
# ---------------------------------------------------------------------------

# source_id (JSON file stem) → (jurisdiction, norm_type, domain)
_SOURCE_META: dict[str, tuple[str, str, str]] = {
    "cpcc_jujuy":             ("jujuy",    "codigo",       "procedural"),
    "constitucion_jujuy":     ("jujuy",    "constitucion", "constitutional"),
    "constitucion_nacional":  ("nacional", "constitucion", "constitutional"),
    "codigo_civil_comercial": ("nacional", "codigo",       "civil"),
    "lct_20744":              ("nacional", "ley",          "labor"),
}

# ---------------------------------------------------------------------------
# Domain vocabulary for query-domain detection and boosting
# ---------------------------------------------------------------------------

_DOMAIN_TERMS: dict[str, frozenset[str]] = {
    "procedural": frozenset([
        "demanda", "contestacion", "plazo", "traslado", "notificacion",
        "rebeldia", "apelacion", "caducidad", "recurso", "sentencia",
        "proceso", "accion", "excepcion", "prueba", "audiencia",
        "demandado", "actor", "intimacion", "expediente", "tribunal",
        "juzgado", "camara", "instancia", "juicio", "competencia",
        "cedula", "notificacion", "emplazamiento", "interlocutoria",
    ]),
    "constitutional": frozenset([
        "defensa", "igualdad", "garantia", "derecho", "debido",
        "amparo", "constitucional", "libertad", "fundamental",
        "ciudadano", "estado", "provincia", "nacion", "derechos",
        "poder", "legislatura", "ejecutivo", "judicial", "publico",
        "soberania", "democracia", "republica", "federal",
    ]),
    "civil": frozenset([
        "contrato", "buena", "fe", "obligacion", "responsabilidad",
        "danos", "posesion", "propiedad", "bien", "cosa",
        "acreedor", "deudor", "credito", "compraventa", "locacion",
        "donacion", "herencia", "sucesion", "persona", "sociedad",
        "daños", "perjuicios", "incumplimiento", "mora",
    ]),
    "labor": frozenset([
        "despido", "salario", "jornada", "licencia", "trabajador",
        "empleador", "indemnizacion", "remuneracion", "vacaciones",
        "convenio", "sindical", "horas", "extras", "accidente",
        "enfermedad", "descanso", "preaviso", "estabilidad",
    ]),
}

# Domains that a source_id primarily covers (for scoring boost)
_DOMAIN_SOURCES: dict[str, frozenset[str]] = {
    "procedural":     frozenset(["cpcc_jujuy"]),
    "constitutional": frozenset(["constitucion_jujuy", "constitucion_nacional"]),
    "civil":          frozenset(["codigo_civil_comercial"]),
    "labor":          frozenset(["lct_20744"]),
}

_STOP_WORDS: frozenset[str] = frozenset([
    "de", "la", "el", "en", "que", "y", "a", "los", "se", "del",
    "las", "un", "una", "su", "con", "por", "para", "es", "al",
    "o", "no", "lo", "le", "si", "cuando", "como", "mas", "pero",
    "sus", "ser", "ha", "son", "fue", "esta", "han", "todo", "sobre",
    "ante", "sin", "ni", "e", "u", "ya", "muy", "bien", "donde",
    "hay", "cada", "sea", "sido", "puede", "caso", "dicho", "dicha",
    "mismo", "misma", "otro", "otra", "entre", "hasta", "desde",
    "aqui", "alli", "este", "esta", "aquella", "ese", "esa",
])


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LegalChunk:
    """A single normalised legal article ready for indexing."""

    source_id:    str
    jurisdiction: str
    norm_type:    str
    domain:       str
    book:         str | None
    title:        str | None
    chapter:      str | None
    article:      str
    label:        str
    text:         str
    search_text:  str   # pre-normalised, used for TF-IDF tokenisation


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SemanticLegalIndex:
    """
    TF-IDF semantic index over the AILEX legal corpus.

    Attributes
    ----------
    _chunks      : flat list of all loaded LegalChunk objects
    _index       : inverted index — token → [(chunk_idx, tfidf_weight)]
    _idf         : IDF value per token (computed at build time)
    _doc_norms   : L2 norm of each doc's TF-IDF weight vector
    """

    _EMBEDDING_WEIGHT = 0.6   # blend: alpha × embedding + (1-alpha) × tfidf
    _EMBEDDING_MIN_SIM = 0.05  # ignore embedding matches below this threshold

    def __init__(self, corpus_root: Path | None = None) -> None:
        self._root: Path = corpus_root or _CORPUS_ROOT
        self._chunks: list[LegalChunk] = []
        self._index: dict[str, list[tuple[int, float]]] = {}
        self._idf: dict[str, float] = {}
        self._doc_norms: list[float] = []
        self._built = False

        # Embedding support (populated during build_index if precomputed data exists)
        self._embeddings = None         # np.ndarray (N, dim) or None
        self._embedding_mask = None     # np.ndarray (N,) bool or None
        self._embedding_model: str | None = None
        self._query_embedder = None     # lazy SentenceTransformer or False (sentinel)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_documents(self) -> list[LegalChunk]:
        """
        Load and normalise all articles from the corpus root.

        Skips files that cannot be parsed; skips articles with no text.
        Returns the flat list of LegalChunk objects (also stored internally).
        """
        self._chunks = []

        if not self._root.exists():
            warnings.warn(
                f"SemanticLegalIndex: corpus root not found: {self._root}",
                stacklevel=2,
            )
            return []

        for path in sorted(self._root.rglob("*.json")):
            source_id = path.stem
            raw = _safe_load_json(path)
            if raw is None:
                continue

            articles = self.extract_articles_from_json(source_id, raw)
            juris, norm_type, domain = self.infer_source_metadata(source_id)
            norma_name = raw.get("norma") or source_id

            for art in articles:
                chunk = self._make_chunk(
                    art=art,
                    source_id=source_id,
                    jurisdiction=juris,
                    norm_type=norm_type,
                    domain=domain,
                    norma_name=norma_name,
                )
                if chunk is not None:
                    self._chunks.append(chunk)

        return self._chunks

    def normalize_text(self, text: str) -> str:
        """
        Lowercase, remove accents, collapse whitespace, strip punctuation.
        Returns a clean, tokenisable string.
        """
        nfkd = unicodedata.normalize("NFKD", text)
        no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
        lowered = no_accents.casefold()
        only_alnum = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return re.sub(r"\s+", " ", only_alnum).strip()

    def build_index(self) -> None:
        """
        Load the corpus (if not already loaded) and build the TF-IDF index.
        Must be called before ``semantic_search()``.
        """
        if not self._chunks:
            self.load_documents()

        if not self._chunks:
            warnings.warn(
                "SemanticLegalIndex: no documents loaded — index is empty.",
                stacklevel=2,
            )
            self._built = True
            return

        N = len(self._chunks)

        # Step 1: tokenise each doc, record term counts
        doc_term_counts: list[Counter] = []
        for chunk in self._chunks:
            tokens = _tokenise(chunk.search_text)
            counts = Counter(tokens)
            doc_term_counts.append(counts)

        # Step 2: document frequency (number of docs containing each term)
        df: Counter = Counter()
        for counts in doc_term_counts:
            df.update(counts.keys())

        # Step 3: smoothed IDF — stored for reuse in search
        self._idf = {
            term: math.log((N + 1) / (freq + 1)) + 1.0
            for term, freq in df.items()
        }

        # Step 4: build inverted index with log-normalised TF-IDF weights
        inverted: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self._doc_norms = []

        for doc_id, counts in enumerate(doc_term_counts):
            sq_norm = 0.0
            for term, count in counts.items():
                # Log-normalised TF on raw count: 1 + log(count).
                # Using raw count (not count/total) keeps the value positive for
                # all count >= 1 — log(1) = 0 gives weight = 1 * idf, log(2) > 0, etc.
                log_tf = 1.0 + math.log(count)
                weight = log_tf * self._idf.get(term, 1.0)
                if weight > 0.0:
                    inverted[term].append((doc_id, weight))
                    sq_norm += weight * weight
            self._doc_norms.append(math.sqrt(sq_norm) or 1.0)

        self._index = dict(inverted)
        self._built = True

        # Try to load precomputed embeddings (silent no-op if unavailable)
        self._try_load_embeddings()

    def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        jurisdiction_boost: str | None = None,
    ) -> list[dict]:
        """
        Retrieve the most relevant legal articles for a natural-language query.

        When precomputed embeddings are available, scores are a weighted blend
        of embedding cosine similarity and TF-IDF cosine similarity.  Otherwise
        falls back to pure TF-IDF (identical to the original behaviour).

        Args:
            query:              Free-text legal query in Spanish.
            top_k:              Maximum results to return (default 5).
            jurisdiction_boost: If provided, mildly boosts documents from this
                                jurisdiction (e.g. "jujuy" or "nacional").

        Returns:
            List of dicts ordered by descending relevance score::

                [{
                    "source_id":    "cpcc_jujuy",
                    "jurisdiction": "jujuy",
                    "norm_type":    "codigo",
                    "article":      "34",
                    "label":        "Artículo 34 — ...",
                    "text":         "...",
                    "score":        0.91,
                }]

        Raises:
            RuntimeError: if ``build_index()`` has not been called.
        """
        if not self._built:
            raise RuntimeError(
                "SemanticLegalIndex: call build_index() before semantic_search()."
            )

        query = (query or "").strip()
        if not query:
            return []

        norm_query = self.normalize_text(query)
        query_tokens = _tokenise(norm_query)
        if not query_tokens:
            return []

        query_domain = _detect_domain(query_tokens)
        juris_boost_norm = (jurisdiction_boost or "").casefold().strip()

        # ── Step 1: TF-IDF cosine scores ──────────────────────────────────
        tfidf_scores = self._compute_tfidf_scores(query_tokens)

        # ── Step 2: Embedding cosine scores (optional) ────────────────────
        emb_scores = self._compute_embedding_scores(query)

        # ── Step 3: Merge candidates ──────────────────────────────────────
        if emb_scores is not None and tfidf_scores:
            candidates = self._blend_scores(tfidf_scores, emb_scores)
        elif emb_scores is not None:
            candidates = emb_scores
        elif tfidf_scores:
            candidates = tfidf_scores
        else:
            return self._fallback_overlap(
                query_tokens, top_k, query_domain, juris_boost_norm,
            )

        # ── Step 4: Apply boost layer + rank ──────────────────────────────
        scored: list[tuple[float, int]] = []
        for doc_id, base_score in candidates.items():
            boost = _compute_boost(
                chunk=self._chunks[doc_id],
                query_domain=query_domain,
                norm_query=norm_query,
                juris_boost=juris_boost_norm,
            )
            scored.append((base_score * boost, doc_id))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            _format_result(self._chunks[doc_id], score)
            for score, doc_id in scored[:top_k]
        ]

    # ── Helper methods ────────────────────────────────────────────────────────

    @staticmethod
    def infer_source_metadata(source_id: str) -> tuple[str, str, str]:
        """
        Return ``(jurisdiction, norm_type, domain)`` for a known source_id.

        Falls back to ``("desconocida", "norma", "general")`` for unknown sources.
        """
        return _SOURCE_META.get(source_id, ("desconocida", "norma", "general"))

    @staticmethod
    def extract_articles_from_json(source_id: str, data: dict) -> list[dict]:
        """
        Defensively extract article-like dicts from a JSON source object.

        Tries, in order:
          1. ``data["articulos"]``  — primary structure for this corpus
          2. ``data["articles"]``   — English-key variant
          3. Top-level values       — if all values are dicts keyed by article nr

        Returns a flat list of raw article dicts (may be empty).
        """
        for key in ("articulos", "articles"):
            val = data.get(key)
            if isinstance(val, list):
                return [item for item in val if isinstance(item, dict)]

        # Last-resort: treat top-level dict values as articles
        candidates = [v for v in data.values() if isinstance(v, dict)]
        if len(candidates) == len(data):
            return candidates

        return []

    # ── Private — embedding support ───────────────────────────────────────────

    def _try_load_embeddings(self) -> None:
        """
        Load precomputed embeddings aligned to ``_chunks`` order.

        Expected files (relative to corpus root's parent):
            embeddings/corpus_vectors.npy   — (M, dim) float32
            embeddings/corpus_meta.json     — provenance + entry list

        Silent no-op if files are missing, numpy is absent, or data is
        inconsistent.  Sets ``_embeddings`` and ``_embedding_mask`` on success.
        """
        embeddings_dir = self._root.parent / "embeddings"
        meta_path = embeddings_dir / "corpus_meta.json"
        vectors_path = embeddings_dir / "corpus_vectors.npy"

        if not meta_path.exists() or not vectors_path.exists():
            return

        try:
            import numpy as np

            with meta_path.open(encoding="utf-8") as fh:
                meta = json.load(fh)

            vectors = np.load(str(vectors_path))

            entries = meta.get("entries") or []
            if vectors.shape[0] != len(entries):
                warnings.warn(
                    f"SemanticLegalIndex: embedding count mismatch "
                    f"({vectors.shape[0]} vectors vs {len(entries)} entries). "
                    f"Skipping embeddings.",
                    stacklevel=2,
                )
                return

            # Build key → row mapping from metadata
            entry_map: dict[tuple[str, str], int] = {}
            for i, entry in enumerate(entries):
                key = (str(entry.get("source_id", "")), str(entry.get("article", "")))
                entry_map[key] = i

            # Align vectors to self._chunks order
            dim = vectors.shape[1]
            aligned = np.zeros((len(self._chunks), dim), dtype=np.float32)
            mask = np.zeros(len(self._chunks), dtype=bool)

            matched = 0
            for chunk_idx, chunk in enumerate(self._chunks):
                row = entry_map.get((chunk.source_id, chunk.article))
                if row is not None:
                    aligned[chunk_idx] = vectors[row]
                    mask[chunk_idx] = True
                    matched += 1

            if matched == 0:
                return

            self._embeddings = aligned
            self._embedding_mask = mask
            self._embedding_model = meta.get("model")

        except Exception as exc:
            warnings.warn(
                f"SemanticLegalIndex: failed to load embeddings: {exc}",
                stacklevel=2,
            )
            self._embeddings = None
            self._embedding_mask = None

    def _embed_query(self, text: str):
        """
        Embed query text using the same model as the precomputed corpus.

        Returns a numpy float32 array or None on failure.
        Lazy-loads the SentenceTransformer model on first call.
        Uses a False sentinel to avoid retrying after a failed load.
        """
        if self._query_embedder is False:
            return None

        if self._query_embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                model_name = self._embedding_model or "paraphrase-multilingual-MiniLM-L12-v2"
                self._query_embedder = SentenceTransformer(model_name)
            except Exception:
                self._query_embedder = False
                return None

        try:
            import numpy as np
            vec = self._query_embedder.encode(text, normalize_embeddings=True)
            return np.array(vec, dtype=np.float32)
        except Exception:
            return None

    def _compute_tfidf_scores(self, query_tokens: list[str]) -> dict[int, float]:
        """
        Compute TF-IDF cosine similarity for all docs sharing tokens with the query.

        Returns a dict of doc_id → cosine score (may be empty).
        """
        q_counts = Counter(query_tokens)
        q_total = len(query_tokens)
        q_weights: dict[str, float] = {}

        for term, count in q_counts.items():
            if term not in self._index:
                continue
            tf = count / q_total
            log_tf = (1.0 + math.log(tf)) if tf > 0 else 0.0
            weight = log_tf * self._idf.get(term, 1.0)
            if weight > 0.0:
                q_weights[term] = weight

        if not q_weights:
            return {}

        q_norm = math.sqrt(sum(w * w for w in q_weights.values())) or 1.0

        dot_products: dict[int, float] = defaultdict(float)
        for term, q_w in q_weights.items():
            for doc_id, d_w in self._index.get(term, []):
                dot_products[doc_id] += q_w * d_w

        return {
            doc_id: dot / (q_norm * self._doc_norms[doc_id])
            for doc_id, dot in dot_products.items()
        }

    def _compute_embedding_scores(self, query_text: str) -> dict[int, float] | None:
        """
        Compute cosine similarity of query against all corpus embeddings.

        Returns dict of doc_id → similarity, or None if embeddings unavailable.
        Only includes docs above ``_EMBEDDING_MIN_SIM`` threshold.
        """
        if self._embeddings is None:
            return None

        q_vec = self._embed_query(query_text)
        if q_vec is None:
            return None

        try:
            import numpy as np
            # Both corpus vectors and query vector are L2-normalized,
            # so dot product = cosine similarity.
            similarities = self._embeddings @ q_vec  # shape (N,)

            scores: dict[int, float] = {}
            for i in range(len(self._chunks)):
                if self._embedding_mask[i] and similarities[i] > self._EMBEDDING_MIN_SIM:
                    scores[i] = float(similarities[i])

            return scores if scores else None
        except Exception:
            return None

    def _blend_scores(
        self,
        tfidf_scores: dict[int, float],
        emb_scores: dict[int, float],
    ) -> dict[int, float]:
        """
        Weighted blend of TF-IDF and embedding scores.

        final = alpha × embedding + (1 - alpha) × tfidf

        Candidates from either source are included; a missing score in one
        system contributes 0 to the blend for that document.
        """
        alpha = self._EMBEDDING_WEIGHT
        all_ids = set(tfidf_scores.keys()) | set(emb_scores.keys())

        blended: dict[int, float] = {}
        for doc_id in all_ids:
            t = tfidf_scores.get(doc_id, 0.0)
            e = emb_scores.get(doc_id, 0.0)
            blended[doc_id] = alpha * e + (1.0 - alpha) * t

        return blended

    # ── Private — corpus loading ──────────────────────────────────────────────

    def _make_chunk(
        self,
        art: dict,
        source_id: str,
        jurisdiction: str,
        norm_type: str,
        domain: str,
        norma_name: str,
    ) -> LegalChunk | None:
        """Build a LegalChunk from a raw article dict; return None if unusable."""
        text = (art.get("texto") or art.get("text") or "").strip()
        if not text:
            return None

        numero = str(art.get("numero") or art.get("number") or "").strip()
        if not numero:
            return None

        titulo = (art.get("titulo") or art.get("title") or "").strip()
        label = f"Artículo {numero}" + (f" — {titulo}" if titulo else "")

        estructura = art.get("estructura") or {}
        book = (
            estructura.get("titulo_nombre")
            or estructura.get("libro_nombre")
            or art.get("libro")
        )
        chapter = (
            estructura.get("capitulo_nombre")
            or art.get("capitulo")
        )

        # search_text: enriched field that gets indexed
        # Includes source name, metadata, and the full article text.
        parts = [
            source_id.replace("_", " "),
            jurisdiction,
            norm_type,
            norma_name,
            f"articulo {numero}",
            titulo,
            text,
        ]
        raw_search = " ".join(p for p in parts if p)
        # Normalise once here so tokenisation is consistent
        norm_search = _normalise_text_internal(raw_search)

        return LegalChunk(
            source_id=source_id,
            jurisdiction=jurisdiction,
            norm_type=norm_type,
            domain=domain,
            book=book or None,
            title=titulo or None,
            chapter=chapter or None,
            article=numero,
            label=label,
            text=text,
            search_text=norm_search,
        )

    def _fallback_overlap(
        self,
        query_tokens: list[str],
        top_k: int,
        query_domain: str | None,
        juris_boost: str,
    ) -> list[dict]:
        """Jaccard-like token overlap ranking when TF-IDF yields no candidate."""
        q_set = set(query_tokens)
        scored: list[tuple[float, int]] = []
        for doc_id, chunk in enumerate(self._chunks):
            doc_tokens = set(_tokenise(chunk.search_text))
            overlap = len(q_set & doc_tokens)
            if overlap == 0:
                continue
            score = overlap / max(len(q_set | doc_tokens), 1)
            boost = _compute_boost(
                chunk=chunk,
                query_domain=query_domain,
                norm_query=" ".join(query_tokens),
                juris_boost=juris_boost,
            )
            scored.append((score * boost, doc_id))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            _format_result(self._chunks[doc_id], score)
            for score, doc_id in scored[:top_k]
        ]


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------

def _normalise_text_internal(text: str) -> str:
    """Accent-free lowercase with collapsed whitespace."""
    nfkd = unicodedata.normalize("NFKD", text)
    no_acc = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = no_acc.casefold()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokenise(text: str) -> list[str]:
    """Split normalised text; filter stop words and very short tokens."""
    return [
        tok for tok in text.split()
        if len(tok) >= 2 and tok not in _STOP_WORDS
    ]


def _detect_domain(tokens: list[str]) -> str | None:
    """Return the legal domain most strongly signalled by the query tokens."""
    token_set = set(tokens)
    best_domain: str | None = None
    best_count = 0
    for domain, terms in _DOMAIN_TERMS.items():
        count = len(token_set & terms)
        if count > best_count:
            best_count = count
            best_domain = domain
    return best_domain if best_count > 0 else None


def _compute_boost(
    chunk: LegalChunk,
    query_domain: str | None,
    norm_query: str,
    juris_boost: str,
) -> float:
    """Multiplicative boost on top of cosine similarity."""
    boost = 1.0

    # Domain match: reward documents from the detected query domain
    if query_domain and chunk.domain == query_domain:
        boost *= 1.25

    # Jurisdiction: mild preference when explicitly requested
    if juris_boost and chunk.jurisdiction == juris_boost:
        boost *= 1.10

    # Bigram phrase presence in search_text
    if _any_bigram_present(norm_query, chunk.search_text):
        boost *= 1.15

    return boost


def _any_bigram_present(norm_query: str, search_text: str) -> bool:
    """True if any consecutive token-pair from the query appears in search_text."""
    tokens = norm_query.split()
    if len(tokens) < 2:
        return False
    for i in range(len(tokens) - 1):
        if f"{tokens[i]} {tokens[i + 1]}" in search_text:
            return True
    return False


def _format_result(chunk: LegalChunk, score: float) -> dict:
    return {
        "source_id":    chunk.source_id,
        "jurisdiction": chunk.jurisdiction,
        "norm_type":    chunk.norm_type,
        "article":      chunk.article,
        "label":        chunk.label,
        "text":         chunk.text,
        "score":        round(score, 6),
    }


def _safe_load_json(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        warnings.warn(
            f"SemanticLegalIndex: could not load '{path.name}': {exc}",
            stacklevel=3,
        )
        return None
