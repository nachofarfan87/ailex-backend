"""
Standalone test script for SemanticLegalIndex.

Run from backend/:
    python -m legal_engine.test_semantic_index

Exit 0 = all tests passed. Exit 1 = failures.
"""

from __future__ import annotations

import json
import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.semantic_index import LegalChunk, SemanticLegalIndex


# ---------------------------------------------------------------------------
# Minimal test harness
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def _check(description: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    status = "PASS" if condition else "FAIL"
    line = f"  [{status}] {description}"
    if not condition and detail:
        line += f"\n         Detail: {detail}"
    print(line)
    if condition:
        _passed += 1
    else:
        _failed += 1


def _section(title: str) -> None:
    print(f"\n{'-' * 62}")
    print(f"  {title}")
    print(f"{'-' * 62}")


# ---------------------------------------------------------------------------
# Shared index (built once to avoid repeated expensive load)
# ---------------------------------------------------------------------------

_shared_index: SemanticLegalIndex | None = None


def _get_index() -> SemanticLegalIndex:
    global _shared_index
    if _shared_index is None:
        _shared_index = SemanticLegalIndex()
        _shared_index.build_index()
    return _shared_index


# ---------------------------------------------------------------------------
# 1. Index construction
# ---------------------------------------------------------------------------

def test_index_builds_successfully() -> None:
    _section("1. Index builds successfully")

    idx = _get_index()
    _check("index is marked as built", idx._built)
    _check("chunks loaded (>0)", len(idx._chunks) > 0,
           f"got {len(idx._chunks)}")
    _check("at least 3000 chunks total", len(idx._chunks) >= 3000,
           f"got {len(idx._chunks)}")
    _check("inverted index non-empty", len(idx._index) > 0)
    _check("doc norms computed (one per chunk)",
           len(idx._doc_norms) == len(idx._chunks))
    _check("IDF table non-empty", len(idx._idf) > 0)

    # Distribution across sources
    sources = {c.source_id for c in idx._chunks}
    for expected in ("cpcc_jujuy", "constitucion_jujuy",
                     "constitucion_nacional", "codigo_civil_comercial", "lct_20744"):
        _check(f"source '{expected}' present", expected in sources)

    print(f"    Total chunks: {len(idx._chunks)}")
    from collections import Counter
    by_source = Counter(c.source_id for c in idx._chunks)
    for src, cnt in sorted(by_source.items()):
        print(f"    {src}: {cnt}")


# ---------------------------------------------------------------------------
# 2. Document normalisation
# ---------------------------------------------------------------------------

def test_documents_are_normalised() -> None:
    _section("2. Document normalisation")

    idx = _get_index()

    # All chunks must have non-empty mandatory fields
    empty_text = [c for c in idx._chunks if not c.text.strip()]
    _check("no chunk has empty text", len(empty_text) == 0,
           f"{len(empty_text)} empty-text chunks")

    empty_article = [c for c in idx._chunks if not c.article.strip()]
    _check("no chunk has empty article number", len(empty_article) == 0)

    # search_text must be lowercase-only (normalised)
    import re
    non_lower = [c for c in idx._chunks[:50]
                 if re.search(r"[A-Z]", c.search_text)]
    _check("search_text is lowercase", len(non_lower) == 0,
           f"{len(non_lower)} chunks with uppercase in search_text")

    # normalize_text API
    raw = "Artículo 34 — Buena Fe: Obligaciones."
    result = idx.normalize_text(raw)
    _check("normalize_text returns lowercase", result == result.lower())
    _check("normalize_text removes accents", "i" in result)  # "Artículo" → "articulo"
    _check("normalize_text removes punctuation", "." not in result and ":" not in result)
    _check("normalize_text collapses spaces", "  " not in result)


# ---------------------------------------------------------------------------
# 3. semantic_search returns results
# ---------------------------------------------------------------------------

def test_semantic_search_returns_results() -> None:
    _section("3. semantic_search returns results")

    idx = _get_index()
    results = idx.semantic_search("plazo para contestar demanda", top_k=5)

    _check("returns a list", isinstance(results, list))
    _check("returns up to top_k results", len(results) <= 5)
    _check("returns at least 1 result", len(results) >= 1)

    # Check result shape
    r = results[0]
    for field in ("source_id", "article", "label", "text", "score",
                  "jurisdiction", "norm_type"):
        _check(f"result has field '{field}'", field in r)

    _check("score is a float in (0, 2]",
           isinstance(r["score"], float) and 0 < r["score"] <= 2.0)

    # Results must be sorted descending by score
    scores = [r["score"] for r in results]
    _check("results ordered by score descending",
           scores == sorted(scores, reverse=True))


# ---------------------------------------------------------------------------
# 4. Procedural query → cpcc_jujuy
# ---------------------------------------------------------------------------

def test_procedural_query_retrieves_cpcc() -> None:
    _section("4. Procedural query retrieves cpcc_jujuy")

    idx = _get_index()
    results = idx.semantic_search("plazo para contestar demanda", top_k=10)
    sources = [r["source_id"] for r in results]

    _check("cpcc_jujuy appears in top-10 results", "cpcc_jujuy" in sources,
           f"got: {sources}")
    # Ideally in top-3
    top3 = sources[:3]
    _check("cpcc_jujuy in top-3 results", "cpcc_jujuy" in top3,
           f"top-3: {top3}")

    # Second procedural query
    results2 = idx.semantic_search("notificacion judicial traslado", top_k=5)
    sources2 = [r["source_id"] for r in results2]
    _check("'notificacion traslado' includes cpcc_jujuy",
           "cpcc_jujuy" in sources2, f"got: {sources2}")


# ---------------------------------------------------------------------------
# 5. Constitutional query → constituciones
# ---------------------------------------------------------------------------

def test_constitutional_query_retrieves_constitucion() -> None:
    _section("5. Constitutional query retrieves constituciones")

    idx = _get_index()
    constitutional_sources = {"constitucion_nacional", "constitucion_jujuy"}

    results = idx.semantic_search("garantia de defensa en juicio", top_k=10)
    sources = {r["source_id"] for r in results}
    _check("constitutional sources in top-10",
           bool(sources & constitutional_sources),
           f"got: {sorted(sources)}")

    # "poder judicial soberania provincial" is highly specific to constituciones
    results2 = idx.semantic_search("soberania popular poder constitucional provincia", top_k=10)
    sources2 = {r["source_id"] for r in results2}
    _check("constitutional sources in sovereignty/province query",
           bool(sources2 & constitutional_sources),
           f"got: {sorted(sources2)}")


# ---------------------------------------------------------------------------
# 6. Civil query → codigo_civil_comercial
# ---------------------------------------------------------------------------

def test_civil_query_retrieves_ccyc() -> None:
    _section("6. Civil query retrieves codigo_civil_comercial")

    idx = _get_index()
    results = idx.semantic_search("buena fe contractual obligaciones", top_k=10)
    sources = [r["source_id"] for r in results]
    _check("codigo_civil_comercial in results", "codigo_civil_comercial" in sources,
           f"got: {sources}")


# ---------------------------------------------------------------------------
# 7. Labor query → lct_20744
# ---------------------------------------------------------------------------

def test_labor_query_retrieves_lct() -> None:
    _section("7. Labor query retrieves lct_20744")

    idx = _get_index()
    results = idx.semantic_search("despido indemnizacion trabajador", top_k=10)
    sources = [r["source_id"] for r in results]
    _check("lct_20744 in results", "lct_20744" in sources,
           f"got: {sources}")


# ---------------------------------------------------------------------------
# 8. Edge cases — empty / short queries
# ---------------------------------------------------------------------------

def test_missing_or_empty_query_is_safe() -> None:
    _section("8. Edge cases — empty / short / None query")

    idx = _get_index()

    r_empty = idx.semantic_search("")
    _check("empty string returns empty list", r_empty == [])

    r_spaces = idx.semantic_search("   ")
    _check("whitespace-only returns empty list", r_spaces == [])

    r_stop = idx.semantic_search("de la el")
    _check("stop-words-only query returns empty list or falls back gracefully",
           isinstance(r_stop, list))

    # Call without building — separate instance
    idx2 = SemanticLegalIndex()
    try:
        idx2.semantic_search("test")
        _check("RuntimeError raised when not built", False)
    except RuntimeError:
        _check("RuntimeError raised when not built", True)


# ---------------------------------------------------------------------------
# 9. Malformed file / chunk does not crash indexing
# ---------------------------------------------------------------------------

def test_malformed_file_does_not_crash_indexing() -> None:
    _section("9. Malformed file / chunk does not crash indexing")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "ar" / "test"
        root.mkdir(parents=True)

        # Good file
        good = {
            "norma": "Test Code",
            "articulos": [
                {"numero": 1, "titulo": "Primero", "texto": "Texto del artículo uno sobre contratos."},
                {"numero": 2, "titulo": "Segundo", "texto": "Texto del artículo dos sobre obligaciones."},
                # Article with no text — should be silently skipped
                {"numero": 3, "titulo": "Vacio", "texto": ""},
                # Article with no number — should be silently skipped
                {"titulo": "Sin numero", "texto": "Texto sin numero de articulo."},
            ],
        }
        (root / "test_code.json").write_text(json.dumps(good), encoding="utf-8")

        # Malformed JSON — should not crash
        (root / "broken.json").write_text("{not valid json", encoding="utf-8")

        # JSON that is a list, not a dict — should be skipped
        (root / "wrong_root.json").write_text("[1, 2, 3]", encoding="utf-8")

        # JSON with no 'articulos' key
        (root / "no_articles.json").write_text('{"norma": "Empty", "other": []}', encoding="utf-8")

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            idx = SemanticLegalIndex(corpus_root=Path(tmpdir) / "ar")
            idx.build_index()

        _check("index built despite malformed files", idx._built)
        _check("only valid articles were loaded",
               len(idx._chunks) == 2,  # only articles 1 and 2
               f"got {len(idx._chunks)}")

        results = idx.semantic_search("contratos obligaciones", top_k=3)
        _check("search works on isolated test corpus", len(results) >= 1)


# ---------------------------------------------------------------------------
# 10. infer_source_metadata and extract_articles_from_json
# ---------------------------------------------------------------------------

def test_helper_methods() -> None:
    _section("10. Helper methods")

    idx = SemanticLegalIndex()

    juris, norm_type, domain = idx.infer_source_metadata("cpcc_jujuy")
    _check("cpcc_jujuy jurisdiction=jujuy", juris == "jujuy")
    _check("cpcc_jujuy norm_type=codigo", norm_type == "codigo")
    _check("cpcc_jujuy domain=procedural", domain == "procedural")

    juris2, norm_type2, domain2 = idx.infer_source_metadata("lct_20744")
    _check("lct_20744 domain=labor", domain2 == "labor")
    _check("lct_20744 norm_type=ley", norm_type2 == "ley")

    # Unknown source falls back gracefully
    juris3, _, domain3 = idx.infer_source_metadata("codigo_desconocido")
    _check("unknown source has fallback jurisdiction", juris3 == "desconocida")

    # extract_articles_from_json
    data_a = {"norma": "Test", "articulos": [{"numero": 1, "texto": "abc"}]}
    arts_a = idx.extract_articles_from_json("test", data_a)
    _check("extracts from 'articulos' key", len(arts_a) == 1)

    data_b = {"norma": "Test", "articles": [{"numero": 1, "texto": "abc"}]}
    arts_b = idx.extract_articles_from_json("test", data_b)
    _check("extracts from 'articles' key", len(arts_b) == 1)

    data_empty = {"norma": "Test", "other": "field"}
    arts_empty = idx.extract_articles_from_json("test", data_empty)
    _check("returns empty list when no article key found", arts_empty == [])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\nAILEX SemanticLegalIndex -- Test Suite")
    print("=" * 62)
    print("  Building index from corpus (this may take a few seconds)...")

    # Pre-build shared index so we see timing
    import time
    t0 = time.time()
    _get_index()
    elapsed = time.time() - t0
    print(f"  Index built in {elapsed:.2f}s")

    test_index_builds_successfully()
    test_documents_are_normalised()
    test_semantic_search_returns_results()
    test_procedural_query_retrieves_cpcc()
    test_constitutional_query_retrieves_constitucion()
    test_civil_query_retrieves_ccyc()
    test_labor_query_retrieves_lct()
    test_missing_or_empty_query_is_safe()
    test_malformed_file_does_not_crash_indexing()
    test_helper_methods()

    print(f"\n{'=' * 62}")
    print(f"  Results: {_passed} passed, {_failed} failed")
    print(f"{'=' * 62}\n")

    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
