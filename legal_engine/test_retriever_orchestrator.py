"""
Standalone test script for LegalRetrieverOrchestrator.

Run from the backend/ directory:
    python -m legal_engine.test_retriever_orchestrator

Or directly:
    python legal_engine/test_retriever_orchestrator.py

Exit code 0 = all tests passed.
Exit code 1 = one or more tests failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from backend/ or from legal_engine/
sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.retriever_orchestrator import LegalRetrieverOrchestrator


# ---------------------------------------------------------------------------
# Minimal test harness (matches project convention — no external deps)
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
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


# ---------------------------------------------------------------------------
# Shared orchestrator instance — built once for the whole test run
# ---------------------------------------------------------------------------

print("\nInitialising LegalRetrieverOrchestrator (loading corpus + building index)…")
retriever = LegalRetrieverOrchestrator()
print("Ready.\n")


# ---------------------------------------------------------------------------
# 1. detect_article_reference
# ---------------------------------------------------------------------------

_section("1. detect_article_reference")

ref = retriever.detect_article_reference("art 34 cpcc jujuy")
_check("'art 34 cpcc jujuy' -> article_number='34'",
       ref.get("article_number") == "34",
       detail=str(ref))
_check("'art 34 cpcc jujuy' -> source_id='cpcc_jujuy'",
       ref.get("source_id") == "cpcc_jujuy",
       detail=str(ref))

ref2 = retriever.detect_article_reference("art. 34")
_check("'art. 34' -> article_number='34'",
       ref2.get("article_number") == "34",
       detail=str(ref2))

ref3 = retriever.detect_article_reference("artículo 163")
_check("'artículo 163' -> article_number='163'",
       ref3.get("article_number") == "163",
       detail=str(ref3))

ref4 = retriever.detect_article_reference("articulo 163")
_check("'articulo 163' (no accent) -> article_number='163'",
       ref4.get("article_number") == "163",
       detail=str(ref4))

ref5 = retriever.detect_article_reference("34 cpcc")
_check("'34 cpcc' (suffix pattern) -> article_number='34'",
       ref5.get("article_number") == "34",
       detail=str(ref5))
_check("'34 cpcc' -> source_id='cpcc_jujuy'",
       ref5.get("source_id") == "cpcc_jujuy",
       detail=str(ref5))

ref6 = retriever.detect_article_reference("plazo para contestar demanda")
_check("conceptual query -> no article reference (empty dict)",
       ref6 == {},
       detail=str(ref6))


# ---------------------------------------------------------------------------
# 2. infer_source_from_query
# ---------------------------------------------------------------------------

_section("2. infer_source_from_query")

_check("'cpcc jujuy' -> cpcc_jujuy",
       retriever.infer_source_from_query("cpcc jujuy") == "cpcc_jujuy")
_check("'procesal civil' -> cpcc_jujuy",
       retriever.infer_source_from_query("procesal civil") == "cpcc_jujuy")
_check("'constitucion nacional' -> constitucion_nacional",
       retriever.infer_source_from_query("constitucion nacional") == "constitucion_nacional")
_check("'constitucion jujuy' -> constitucion_jujuy",
       retriever.infer_source_from_query("constitucion jujuy") == "constitucion_jujuy")
_check("'codigo civil' -> codigo_civil_comercial",
       retriever.infer_source_from_query("codigo civil") == "codigo_civil_comercial")
_check("'cccn' -> codigo_civil_comercial",
       retriever.infer_source_from_query("cccn") == "codigo_civil_comercial")
_check("'lct' -> lct_20744",
       retriever.infer_source_from_query("lct") == "lct_20744")
_check("'contrato de trabajo' -> lct_20744",
       retriever.infer_source_from_query("contrato de trabajo") == "lct_20744")
_check("unrelated query -> None",
       retriever.infer_source_from_query("plazo para contestar") is None)


# ---------------------------------------------------------------------------
# 3. classify_query_strategy
# ---------------------------------------------------------------------------

_section("3. classify_query_strategy")

_check("'art 34 cpcc jujuy' -> exact_article",
       retriever.classify_query_strategy("art 34 cpcc jujuy") == "exact_article")
_check("'artículo 163' -> exact_article",
       retriever.classify_query_strategy("artículo 163") == "exact_article")
_check("'34 cpcc' -> exact_article",
       retriever.classify_query_strategy("34 cpcc") == "exact_article")

_check("'plazo para contestar demanda' -> hybrid or semantic",
       retriever.classify_query_strategy("plazo para contestar demanda")
       in ("hybrid", "semantic"))

_check(
    "long conceptual query -> semantic",
    retriever.classify_query_strategy(
        "cuales son los requisitos para interponer recurso de apelacion en proceso civil"
    ) == "semantic",
)

_check("empty string -> hybrid (safe default)",
       retriever.classify_query_strategy("") == "hybrid")


# ---------------------------------------------------------------------------
# 4. detect_domain
# ---------------------------------------------------------------------------

_section("4. detect_domain")

_check("'plazo para contestar demanda' -> procedural",
       retriever.detect_domain("plazo para contestar demanda") == "procedural")
_check("'garantia de defensa en juicio' -> constitutional",
       retriever.detect_domain("garantia de defensa en juicio") == "constitutional")
_check("'buena fe contractual' -> civil",
       retriever.detect_domain("buena fe contractual") == "civil")
_check("'indemnizacion por despido' -> labor",
       retriever.detect_domain("indemnizacion por despido") == "labor")
_check("'xyz123' -> unknown",
       retriever.detect_domain("xyz123") == "unknown")


# ---------------------------------------------------------------------------
# 5. Exact article retrieval — known article
# ---------------------------------------------------------------------------

_section("5. retrieve — exact article 'art 34 cpcc jujuy'")

resp = retriever.retrieve("art 34 cpcc jujuy", top_k=3)

_check("strategy == 'exact_article'",
       resp["strategy"] == "exact_article",
       detail=f"strategy={resp['strategy']}")
_check("at least one result",
       len(resp["results"]) >= 1,
       detail=f"results={len(resp['results'])}")
_check("first result source_id == 'cpcc_jujuy'",
       resp["results"][0]["source_id"] == "cpcc_jujuy" if resp["results"] else False,
       detail=str(resp["results"][:1]))
_check("first result article == '34'",
       resp["results"][0]["article"] == "34" if resp["results"] else False,
       detail=str(resp["results"][:1]))
_check("first result match_type == 'exact'",
       resp["results"][0].get("match_type") == "exact" if resp["results"] else False)
_check("score > 0.9 (exact match should be near 1.0)",
       resp["results"][0]["score"] > 0.9 if resp["results"] else False,
       detail=str(resp["results"][0]["score"] if resp["results"] else "no results"))
_check("result has 'texto' key",
       "texto" in resp["results"][0] if resp["results"] else False)


# ---------------------------------------------------------------------------
# 6. Exact article without explicit source
# ---------------------------------------------------------------------------

_section("6. retrieve — exact article without explicit source")

resp_ns = retriever.retrieve("artículo 34", top_k=3, jurisdiction="jujuy")

_check("strategy == 'exact_article'",
       resp_ns["strategy"] == "exact_article",
       detail=f"strategy={resp_ns['strategy']}")
_check("at least one result returned (fallback to candidate sources)",
       len(resp_ns["results"]) >= 1,
       detail=f"results={len(resp_ns['results'])}, warnings={resp_ns['warnings']}")


# ---------------------------------------------------------------------------
# 7. Missing article fails safely
# ---------------------------------------------------------------------------

_section("7. Missing article fails safely")

resp_miss = retriever.retrieve("art 99999 cpcc jujuy", top_k=3)

_check("strategy == 'exact_article' or 'hybrid' (fallback)",
       resp_miss["strategy"] in ("exact_article", "hybrid"),
       detail=f"strategy={resp_miss['strategy']}")
_check("warnings list is non-empty",
       len(resp_miss["warnings"]) > 0,
       detail=str(resp_miss["warnings"]))
# Should not crash; may return 0 results or fallback results
_check("call does not raise (results is a list)",
       isinstance(resp_miss["results"], list))


# ---------------------------------------------------------------------------
# 8. Procedural conceptual query -> cpcc_jujuy in results
# ---------------------------------------------------------------------------

_section("8. retrieve — procedural query")

resp_proc = retriever.retrieve("plazo para contestar demanda", top_k=5)

_check("strategy is 'semantic', 'hybrid', or 'lexical'",
       resp_proc["strategy"] in ("semantic", "hybrid", "lexical"),
       detail=f"strategy={resp_proc['strategy']}")
_check("at least one result",
       len(resp_proc["results"]) >= 1,
       detail=f"results={len(resp_proc['results'])}")
_check("cpcc_jujuy appears in top results",
       any(r["source_id"] == "cpcc_jujuy" for r in resp_proc["results"]),
       detail=str([r["source_id"] for r in resp_proc["results"]]))


# ---------------------------------------------------------------------------
# 9. Constitutional query -> constitucion_* in results
# ---------------------------------------------------------------------------

_section("9. retrieve — constitutional query")

resp_const = retriever.retrieve("garantia de defensa en juicio", top_k=5)

_check("at least one result",
       len(resp_const["results"]) >= 1,
       detail=f"results={len(resp_const['results'])}")
_check("constitutional source in results",
       any(
           r["source_id"] in ("constitucion_nacional", "constitucion_jujuy")
           for r in resp_const["results"]
       ),
       detail=str([r["source_id"] for r in resp_const["results"]]))


# ---------------------------------------------------------------------------
# 10. Civil query -> codigo_civil_comercial in results
# ---------------------------------------------------------------------------

_section("10. retrieve — civil query")

resp_civil = retriever.retrieve("buena fe contractual", top_k=5)

_check("at least one result",
       len(resp_civil["results"]) >= 1,
       detail=f"results={len(resp_civil['results'])}")
_check("codigo_civil_comercial appears in top results",
       any(r["source_id"] == "codigo_civil_comercial" for r in resp_civil["results"]),
       detail=str([r["source_id"] for r in resp_civil["results"]]))


# ---------------------------------------------------------------------------
# 11. Labor query -> lct_20744 in results
# ---------------------------------------------------------------------------

_section("11. retrieve — labor query")

resp_labor = retriever.retrieve("indemnizacion por despido trabajador", top_k=5)

_check("at least one result",
       len(resp_labor["results"]) >= 1,
       detail=f"results={len(resp_labor['results'])}")
_check("lct_20744 appears in top results",
       any(r["source_id"] == "lct_20744" for r in resp_labor["results"]),
       detail=str([r["source_id"] for r in resp_labor["results"]]))


# ---------------------------------------------------------------------------
# 12. Short source-specific query — can use lexical
# ---------------------------------------------------------------------------

_section("12. retrieve — short source-specific query (lexical)")

resp_lex = retriever.retrieve("traslado cpcc", top_k=5)

_check("strategy is 'lexical', 'exact_article', or 'hybrid'",
       resp_lex["strategy"] in ("lexical", "exact_article", "hybrid"),
       detail=f"strategy={resp_lex['strategy']}")
_check("at least one result",
       len(resp_lex["results"]) >= 1,
       detail=f"results={len(resp_lex['results'])}")


# ---------------------------------------------------------------------------
# 13. Ambiguous query uses hybrid
# ---------------------------------------------------------------------------

_section("13. classify_query_strategy — ambiguous query")

ambiguous = "notificacion demanda"
strat = retriever.classify_query_strategy(ambiguous)
_check("ambiguous query classifies as 'hybrid' or 'semantic'",
       strat in ("hybrid", "semantic"),
       detail=f"strategy={strat}")


# ---------------------------------------------------------------------------
# 14. Deduplication
# ---------------------------------------------------------------------------

_section("14. dedupe_results")

dupes = [
    {"source_id": "cpcc_jujuy", "article": "34", "score": 0.8, "match_type": "lexical"},
    {"source_id": "cpcc_jujuy", "article": "34", "score": 0.9, "match_type": "semantic"},
    {"source_id": "cpcc_jujuy", "article": "45", "score": 0.7, "match_type": "lexical"},
]
deduped = retriever.dedupe_results(dupes)

_check("de-duplicated to 2 unique results",
       len(deduped) == 2,
       detail=f"got {len(deduped)} results: {[(r['source_id'], r['article']) for r in deduped]}")
_check("higher-scored duplicate kept (score=0.9 for art 34)",
       any(r["article"] == "34" and r["score"] == 0.9 for r in deduped),
       detail=str(deduped))


# ---------------------------------------------------------------------------
# 15. merge_results
# ---------------------------------------------------------------------------

_section("15. merge_results")

lex = [
    {"source_id": "cpcc_jujuy", "article": "34", "score": 0.6, "match_type": "lexical"},
    {"source_id": "cpcc_jujuy", "article": "45", "score": 0.5, "match_type": "lexical"},
]
sem = [
    {"source_id": "cpcc_jujuy", "article": "34", "score": 0.8, "match_type": "semantic"},
    {"source_id": "lct_20744",  "article": "10", "score": 0.7, "match_type": "semantic"},
]
merged = retriever.merge_results(lex, sem)

# article 34 should appear once as hybrid
hybrid_34 = [r for r in merged if r["article"] == "34" and r["source_id"] == "cpcc_jujuy"]
_check("article 34 appears exactly once after merge",
       len(hybrid_34) == 1,
       detail=str(hybrid_34))
_check("merged article 34 has match_type='hybrid'",
       hybrid_34[0]["match_type"] == "hybrid" if hybrid_34 else False,
       detail=str(hybrid_34))
_check("merged article 34 score == max(0.6, 0.8) * 1.1 = 0.88",
       abs(hybrid_34[0]["score"] - 0.88) < 0.001 if hybrid_34 else False,
       detail=str(hybrid_34[0]["score"] if hybrid_34 else "no result"))
_check("article 45 (lexical only) present",
       any(r["article"] == "45" for r in merged))
_check("article 10/lct (semantic only) present",
       any(r["article"] == "10" and r["source_id"] == "lct_20744" for r in merged))


# ---------------------------------------------------------------------------
# 16. Empty query — safe response
# ---------------------------------------------------------------------------

_section("16. retrieve — empty query")

resp_empty = retriever.retrieve("")

_check("strategy == 'none'",
       resp_empty["strategy"] == "none",
       detail=str(resp_empty))
_check("results is empty list",
       resp_empty["results"] == [],
       detail=str(resp_empty["results"]))
_check("warnings non-empty",
       len(resp_empty["warnings"]) > 0,
       detail=str(resp_empty["warnings"]))

resp_blank = retriever.retrieve("   ")

_check("whitespace-only query also returns empty response",
       resp_blank["results"] == [],
       detail=str(resp_blank["results"]))


# ---------------------------------------------------------------------------
# 17. Result schema — all required keys present
# ---------------------------------------------------------------------------

_section("17. Result schema completeness")

_REQUIRED_KEYS = {
    "source_id", "article", "label", "titulo", "texto",
    "score", "match_type", "jurisdiction", "norm_type", "domain",
}

resp_schema = retriever.retrieve("plazo contestar demanda", top_k=3)
if resp_schema["results"]:
    first = resp_schema["results"][0]
    missing = _REQUIRED_KEYS - set(first.keys())
    _check("all required schema keys present in result",
           len(missing) == 0,
           detail=f"missing keys: {missing}")
    _check("score is a float",
           isinstance(first["score"], float),
           detail=str(type(first["score"])))
    _check("score is non-negative",
           first["score"] >= 0,
           detail=str(first["score"]))
else:
    _check("query returned results to validate schema", False,
           detail="no results returned")


# ---------------------------------------------------------------------------
# 18. Hierarchy boost preserves order
# ---------------------------------------------------------------------------

_section("18. boost_by_hierarchy")

# Use equal base scores so that the hierarchy position is the deciding factor.
# constitucion_nacional is at position 0; lct_20744 at position 4 in jujuy hierarchy.
unordered = [
    {"source_id": "lct_20744",            "article": "1", "score": 0.7,
     "match_type": "semantic", "jurisdiction": "nacional", "norm_type": "ley",   "domain": "labor"},
    {"source_id": "constitucion_nacional", "article": "1", "score": 0.7,
     "match_type": "semantic", "jurisdiction": "nacional", "norm_type": "const", "domain": "constitutional"},
]
boosted = retriever.boost_by_hierarchy(unordered, jurisdiction="jujuy", domain="procedural")

_check("constitucion_nacional is ranked first after hierarchy boost",
       boosted[0]["source_id"] == "constitucion_nacional" if boosted else False,
       detail=str([(r["source_id"], r["score"]) for r in boosted]))
_check("constitucion_nacional has higher boosted score than lct_20744",
       (boosted[0]["score"] > boosted[1]["score"]) if len(boosted) >= 2 else False,
       detail=str([(r["source_id"], r["score"]) for r in boosted]))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Results: {_passed} passed, {_failed} failed  "
      f"(total {_passed + _failed})")
print(f"{'=' * 60}\n")

sys.exit(0 if _failed == 0 else 1)
