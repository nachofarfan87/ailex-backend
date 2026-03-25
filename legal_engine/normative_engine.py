"""
AILEX — NormativeEngine

Loads the internal legal corpus from data/legal/ar/ and exposes
deterministic, hallucination-free article lookup and keyword search.

Design rules:
  - All article data comes exclusively from local JSON files.
  - The engine never synthesizes or augments legal text.
  - If a code or article does not exist the engine returns None / [].
  - Malformed JSON files are skipped with a logged warning; they never
    crash the engine or corrupt the index of valid files.

Supported JSON shapes (both are present in the corpus):

  Shape A — CPCC / constituciones:
    { "norma": "...", "articulos": [{"numero": 1, "titulo": "...", "texto": "..."}, ...] }

  Shape B — LCT:
    { "norma": "...", "ley": "...", "articulos": [{"numero": "10", "titulo": "", "texto": "...", ...}, ...] }

In both shapes the engine normalises "numero" to a string key for consistent
lookup regardless of whether the source file uses int or str.
"""

from __future__ import annotations

import json
import re
import unicodedata
import warnings
from pathlib import Path
from typing import Any


# Path from this file: legal_engine/ → backend/ → data/legal/ar/
_CORPUS_ROOT = Path(__file__).parent.parent / "data" / "legal" / "ar"


class NormativeEngine:
    """
    In-memory index of all legal articles in the AILEX corpus.

    Usage:
        engine = NormativeEngine()
        engine.load_corpus()                          # load once at startup
        article = engine.get_article("cpcc_jujuy", "34")
        results = engine.search_articles("traslado")
    """

    def __init__(self, corpus_root: Path | None = None) -> None:
        self._root: Path = corpus_root or _CORPUS_ROOT
        # { code_id: { "meta": {...}, "articles": { "34": {...} } } }
        self._index: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_corpus(self) -> dict[str, dict]:
        """
        Load every JSON file recursively from the corpus root.

        Returns a dict keyed by code_id (= file stem without extension),
        each value being the raw top-level JSON object.  The internal
        article index is also populated for fast lookup.

        Files that cannot be parsed are skipped with a warning; they do
        not affect the rest of the corpus.
        """
        self._index.clear()
        loaded: dict[str, dict] = {}

        if not self._root.exists():
            warnings.warn(
                f"NormativeEngine: corpus root not found: {self._root}",
                stacklevel=2,
            )
            return loaded

        for path in sorted(self._root.rglob("*.json")):
            code_id = path.stem
            raw = _load_json(path)
            if raw is None:
                continue

            articles = raw.get("articulos")
            if not isinstance(articles, list):
                warnings.warn(
                    f"NormativeEngine: '{path.name}' has no 'articulos' list — skipped.",
                    stacklevel=2,
                )
                continue

            meta = {
                "norma": raw.get("norma", code_id),
                "ley": raw.get("ley"),
                "jurisdiccion": raw.get("jurisdiccion"),
                "file": str(path.relative_to(self._root)),
            }
            article_index = _build_article_index(articles)
            self._index[code_id] = {"meta": meta, "articles": article_index}
            loaded[code_id] = raw

        return loaded

    def get_article(self, code_id: str, article_number: str | int) -> dict | None:
        """
        Return a single article by code and article number.

        Args:
            code_id:        File stem of the source (e.g. "cpcc_jujuy").
            article_number: Article number as string or int (e.g. "34" or 34).

        Returns:
            {
                "code":    "cpcc_jujuy",
                "norma":   "Código Procesal ...",
                "article": "34",
                "titulo":  "...",
                "texto":   "...",
            }
            or None if the code or article does not exist.
        """
        entry = self._index.get(code_id)
        if entry is None:
            return None

        key = str(article_number).strip()
        article = entry["articles"].get(key)
        if article is None:
            return None

        return {
            "code": code_id,
            "norma": entry["meta"]["norma"],
            "article": key,
            "titulo": article.get("titulo", ""),
            "texto": article.get("texto", ""),
        }

    def search_articles(self, keyword: str, max_results: int = 20) -> list[dict]:
        """
        Search through all loaded articles for a keyword.

        Matching is case-insensitive and accent-insensitive.
        Both the article text and the title are searched.

        Args:
            keyword:     The term to look for.
            max_results: Maximum number of results to return (default 20).

        Returns:
            List of dicts with the same shape as get_article() output,
            ordered by code_id then article number.
            Empty list if no matches or corpus not loaded.
        """
        if not keyword or not self._index:
            return []

        search_terms = _build_search_terms(keyword)
        if not search_terms:
            return []

        ranked: list[tuple[int, str, str, dict[str, str]]] = []

        for code_id, entry in sorted(self._index.items()):
            norma = entry["meta"]["norma"]
            for art_key, article in entry["articles"].items():
                haystack = _normalise_text(
                    f"{article.get('titulo', '')} {article.get('texto', '')}"
                )
                frequency = _match_frequency(haystack, search_terms)
                if frequency <= 0:
                    continue
                ranked.append(
                    (
                        frequency,
                        code_id,
                        art_key,
                        {
                            "code": code_id,
                            "norma": norma,
                            "article": art_key,
                            "titulo": article.get("titulo", ""),
                            "texto": article.get("texto", ""),
                        },
                    )
                )

        ranked.sort(key=lambda item: (-item[0], item[1], _article_sort_key(item[2])))
        return [item[3] for item in ranked[:max_results]]

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def list_codes(self) -> list[str]:
        """Return all loaded code_id values."""
        return sorted(self._index.keys())

    def article_count(self, code_id: str) -> int | None:
        """Return number of articles for a code, or None if not loaded."""
        entry = self._index.get(code_id)
        return len(entry["articles"]) if entry else None

    def is_loaded(self) -> bool:
        return bool(self._index)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict | None:
    """Load a JSON file safely; return None on any error."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            warnings.warn(
                f"NormativeEngine: '{path.name}' root is not a JSON object — skipped.",
                stacklevel=3,
            )
            return None
        return data
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        warnings.warn(
            f"NormativeEngine: could not load '{path.name}': {exc}",
            stacklevel=3,
        )
        return None


def _build_article_index(articles: list[Any]) -> dict[str, dict]:
    """
    Build a {normalised_number: article_dict} mapping.

    Skips entries that are not dicts or have no 'numero' field.
    """
    index: dict[str, dict] = {}
    for item in articles:
        if not isinstance(item, dict):
            continue
        numero = item.get("numero")
        if numero is None:
            continue
        key = str(numero).strip()
        if key:
            index[key] = item
    return index


def _normalise_text(text: str) -> str:
    """Lowercase + strip combining accents for locale-agnostic search."""
    nfkd = unicodedata.normalize("NFKD", text)
    normalized = "".join(c for c in nfkd if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _build_search_terms(keyword: str) -> list[str]:
    normalized = _normalise_text(keyword)
    if not normalized:
        return []
    terms: list[str] = []
    if " " in normalized:
        terms.append(normalized)
        terms.extend(token for token in re.findall(r"[a-z0-9]+", normalized) if token)
    else:
        terms.append(normalized)
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result


def _match_frequency(haystack: str, terms: list[str]) -> int:
    total = 0
    for term in terms:
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)")
        hits = len(pattern.findall(haystack))
        if " " in term:
            hits *= 2
        total += hits
    return total


def _article_sort_key(article: str) -> tuple[int, str]:
    digits = "".join(ch for ch in str(article) if ch.isdigit())
    return (int(digits) if digits else 10**9, str(article))
