"""
Standalone test script for NormativeEngine.

Run from the backend/ directory:
    python -m legal_engine.test_normative_engine

Or directly:
    python legal_engine/test_normative_engine.py

Exit code 0 = all tests passed.
Exit code 1 = one or more tests failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from backend/ or from legal_engine/
sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.normative_engine import NormativeEngine


# ---------------------------------------------------------------------------
# Tiny test harness (no external deps)
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def _check(description: str, condition: bool) -> None:
    global _passed, _failed
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {description}")
    if condition:
        _passed += 1
    else:
        _failed += 1


def _section(title: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_load_corpus(engine: NormativeEngine) -> None:
    _section("1. load_corpus()")

    corpus = engine.load_corpus()

    _check("Returns a non-empty dict", bool(corpus))
    _check("cpcc_jujuy is loaded", "cpcc_jujuy" in corpus)
    _check("constitucion_jujuy is loaded", "constitucion_jujuy" in corpus)
    _check("constitucion_nacional is loaded", "constitucion_nacional" in corpus)
    _check("codigo_civil_comercial is loaded", "codigo_civil_comercial" in corpus)
    _check("lct_20744 is loaded", "lct_20744" in corpus)
    _check("engine.is_loaded() returns True", engine.is_loaded())
    _check("list_codes() contains expected codes", "cpcc_jujuy" in engine.list_codes())

    count = engine.article_count("cpcc_jujuy")
    _check("cpcc_jujuy has at least one article", count is not None and count > 0)
    print(f"    cpcc_jujuy: {count} articles indexed")

    count_lct = engine.article_count("lct_20744")
    _check("lct_20744 has at least one article", count_lct is not None and count_lct > 0)
    print(f"    lct_20744:  {count_lct} articles indexed")


def test_get_article_existing(engine: NormativeEngine) -> None:
    _section("2. get_article() — existing article")

    # cpcc_jujuy art. 1 is "TUTELA JUDICIAL EFECTIVA"
    result = engine.get_article("cpcc_jujuy", "1")
    _check("Returns a dict (not None)", result is not None)
    _check("Has 'code' field = 'cpcc_jujuy'", (result or {}).get("code") == "cpcc_jujuy")
    _check("Has 'article' field = '1'", (result or {}).get("article") == "1")
    _check("Has non-empty 'texto'", bool((result or {}).get("texto")))
    _check("Has 'norma' field", bool((result or {}).get("norma")))

    # Accept int as article_number
    result_int = engine.get_article("cpcc_jujuy", 1)
    _check("Accepts int article number", result_int is not None)
    _check("Int and str return same article", (result or {}).get("texto") == (result_int or {}).get("texto"))

    # lct_20744 articles start at "10" in the corpus
    result_lct = engine.get_article("lct_20744", "10")
    _check("lct_20744 art. 10 found", result_lct is not None)
    _check("lct_20744 art. 10 has texto", bool((result_lct or {}).get("texto")))


def test_get_article_missing(engine: NormativeEngine) -> None:
    _section("3. get_article() — missing article / missing code")

    result_no_art = engine.get_article("cpcc_jujuy", "99999")
    _check("Returns None for non-existent article number", result_no_art is None)

    result_no_code = engine.get_article("codigo_que_no_existe", "1")
    _check("Returns None for non-existent code_id", result_no_code is None)

    result_empty_art = engine.get_article("cpcc_jujuy", "")
    _check("Returns None for empty article number", result_empty_art is None)


def test_search_articles(engine: NormativeEngine) -> None:
    _section("4. search_articles() — keyword search")

    # "traslado" appears in cpcc_jujuy
    results = engine.search_articles("traslado")
    _check("'traslado' search returns results", len(results) > 0)
    _check("Each result has 'code', 'article', 'texto'",
           all("code" in r and "article" in r and "texto" in r for r in results))

    # Accent-insensitive: "tutela" vs "tutela" (no accent issue here but let's test)
    results_tutela = engine.search_articles("tutela judicial")
    _check("'tutela judicial' search finds cpcc_jujuy art. 1",
           any(r["code"] == "cpcc_jujuy" and r["article"] == "1" for r in results_tutela))

    # Case-insensitive
    results_upper = engine.search_articles("TRASLADO")
    _check("Search is case-insensitive", len(results_upper) > 0)

    # Non-existent keyword
    results_none = engine.search_articles("xyzzy_no_existe_12345")
    _check("Non-existent keyword returns empty list", results_none == [])

    # Empty keyword
    results_empty = engine.search_articles("")
    _check("Empty keyword returns empty list", results_empty == [])

    # max_results cap
    results_cap = engine.search_articles("el", max_results=3)
    _check("max_results is respected", len(results_cap) <= 3)

    # LCT keyword
    results_lct = engine.search_articles("contrato de trabajo")
    _check("'contrato de trabajo' finds results in lct_20744",
           any(r["code"] == "lct_20744" for r in results_lct))

    # Word boundary: "pago" no debe matchear solo por "pagador"
    engine._index = {
        "test_code": {
            "meta": {"norma": "Norma Test"},
            "articles": {
                "1": {"titulo": "Pago", "texto": "El pago debe realizarse en termino."},
                "2": {"titulo": "Pagador", "texto": "La figura del pagador se define aparte."},
                "3": {"titulo": "Pago reiterado", "texto": "Pago. El pago parcial y el pago total deben distinguirse."},
            },
        }
    }
    boundary_results = engine.search_articles("pago", max_results=10)
    _check("word boundary excludes pagador-only article",
           all(r["article"] != "2" for r in boundary_results))
    _check("frequency ranking prioritises repeated term article",
           boundary_results and boundary_results[0]["article"] == "3")
    phrase_results = engine.search_articles("pago parcial", max_results=10)
    _check("multi-word phrase search finds exact phrase article",
           phrase_results and phrase_results[0]["article"] == "3")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\nAILEX NormativeEngine — Test Suite")
    print("=" * 60)

    engine = NormativeEngine()

    test_load_corpus(engine)
    test_get_article_existing(engine)
    test_get_article_missing(engine)
    test_search_articles(engine)

    print(f"\n{'=' * 60}")
    print(f"  Results: {_passed} passed, {_failed} failed")
    print(f"{'=' * 60}\n")

    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
