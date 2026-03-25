"""
Tests for LegalContextBuilder and its shared data structures.

Run from backend/:
    python -m legal_engine.test_context_builder

Exit 0 = all passed.  Exit 1 = failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.context_builder import (
    LegalArticleChunk,
    LegalContext,
    LegalContextBuilder,
    _infer_domain,
    _is_near_dup,
    _trigrams,
)

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def _check(description: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    status = "PASS" if condition else "FAIL"
    line   = f"  [{status}] {description}"
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
# Fixtures
# ---------------------------------------------------------------------------

def _make_chunk(
    source_id: str    = "cpcc_jujuy",
    article:   str    = "34",
    texto:     str    = "El juez debe resolver en el plazo de cinco dias.",
    score:     float  = 0.8,
    domain:    str    = "procedural",
    match_type: str   = "semantic",
    jurisdiction: str = "jujuy",
) -> dict:
    return {
        "source_id":    source_id,
        "article":      article,
        "label":        f"Articulo {article}",
        "titulo":       "",
        "texto":        texto,
        "score":        score,
        "match_type":   match_type,
        "jurisdiction": jurisdiction,
        "norm_type":    "codigo",
        "domain":       domain,
    }


def _chunk_list() -> list[dict]:
    return [
        _make_chunk("cpcc_jujuy",             "34",  "Plazo para resolver.", 0.9, "procedural"),
        _make_chunk("constitucion_nacional",  "18",  "Nadie puede ser penado sin juicio previo.", 0.7, "constitutional", jurisdiction="nacional"),
        _make_chunk("codigo_civil_comercial", "961", "Los contratos deben celebrarse de buena fe.", 0.6, "civil", jurisdiction="nacional"),
        _make_chunk("lct_20744",              "245", "En caso de despido sin causa...", 0.8, "labor", jurisdiction="nacional"),
    ]


builder = LegalContextBuilder(max_chars=8_000, max_results=10, default_jurisdiction="jujuy")


# ---------------------------------------------------------------------------
# 1. LegalArticleChunk
# ---------------------------------------------------------------------------

_section("1. LegalArticleChunk.from_dict")

d = _make_chunk()
chunk = LegalArticleChunk.from_dict(d)
_check("source_id parsed correctly",    chunk.source_id == "cpcc_jujuy")
_check("article parsed correctly",      chunk.article   == "34")
_check("texto parsed correctly",        "plazo" in chunk.texto.lower())
_check("score parsed as float",         isinstance(chunk.score, float))
_check("char_count > 0",                chunk.char_count() > 0)
_check("citation_key returns tuple",    chunk.citation_key() == ("cpcc_jujuy", "34"))
_check("source_label returns string",   isinstance(chunk.source_label(), str))
_check("to_dict roundtrip",             chunk.to_dict()["source_id"] == "cpcc_jujuy")

# tolerates 'text' key (SemanticLegalIndex output)
d_text = {**d, "texto": None, "text": "texto via text key"}
chunk_t = LegalArticleChunk.from_dict(d_text)
_check("tolerates 'text' key alias",   chunk_t.texto == "texto via text key")


# ---------------------------------------------------------------------------
# 2. build_context -- happy path
# ---------------------------------------------------------------------------

_section("2. build_context -- happy path")

results = _chunk_list()
ctx = builder.build_context(
    query="plazo para contestar demanda",
    retriever_results=results,
    jurisdiction="jujuy",
)

_check("returns LegalContext",          isinstance(ctx, LegalContext))
_check("query preserved",               ctx.query == "plazo para contestar demanda")
_check("jurisdiction preserved",        ctx.jurisdiction == "jujuy")
_check("applicable_norms non-empty",    len(ctx.applicable_norms) > 0)
_check("total_chars > 0",              ctx.total_chars > 0)
_check("context_text non-empty",        len(ctx.context_text) > 10)
_check("is_empty() == False",           not ctx.is_empty())
_check("source_ids_used non-empty",     len(ctx.source_ids_used) > 0)
_check("to_dict() serialisable",        isinstance(ctx.to_dict(), dict))


# ---------------------------------------------------------------------------
# 3. build_context -- empty input
# ---------------------------------------------------------------------------

_section("3. build_context -- empty / invalid input")

ctx_empty = builder.build_context(query="test", retriever_results=[])
_check("empty results -> is_empty()",   ctx_empty.is_empty())
_check("empty results -> warning",      len(ctx_empty.warnings) > 0)
_check("context_text safe string",      isinstance(ctx_empty.context_text, str))

ctx_none = builder.build_context(query="test", retriever_results=None)
_check("None results -> is_empty()",    ctx_none.is_empty())

ctx_noquery = builder.build_context(query="", retriever_results=results)
_check("empty query -> warning issued", any("empty" in w.lower() for w in ctx_noquery.warnings))

ctx_bad = builder.build_context(query="test", retriever_results=[{"foo": "bar"}])
_check("no-text result skipped",        ctx_bad.is_empty() or len(ctx_bad.warnings) > 0)


# ---------------------------------------------------------------------------
# 4. Deduplication
# ---------------------------------------------------------------------------

_section("4. Deduplication")

# Two identical chunks (same source_id + article) -- only highest score kept
dup_results = [
    _make_chunk("cpcc_jujuy", "34", "Texto A.", 0.6),
    _make_chunk("cpcc_jujuy", "34", "Texto A.", 0.9),   # higher score
    _make_chunk("cpcc_jujuy", "45", "Otro articulo completamente diferente.", 0.7),
]
ctx_dup = builder.build_context(query="test", retriever_results=dup_results)
art34 = [c for c in ctx_dup.applicable_norms if c.article == "34"]
_check("exact dup removed -> one art.34",       len(art34) == 1)
_check("higher-scored dup kept",                art34[0].score == 0.9 if art34 else False)
_check("dedup warning issued",                  any("dup" in w.lower() or "duplicad" in w.lower()
                                                    for w in ctx_dup.warnings))


# ---------------------------------------------------------------------------
# 5. Near-duplicate detection helpers
# ---------------------------------------------------------------------------

_section("5. Near-duplicate helpers")

long_text = "a" * 60
tgrams = _trigrams(long_text)
_check("trigrams returns frozenset",        isinstance(tgrams, frozenset))
_check("trigrams of short text is empty",   _trigrams("ab") == frozenset())
_check("trigrams of 3-char text has 1",     len(_trigrams("abc")) == 1)

c1 = LegalArticleChunk.from_dict(_make_chunk(texto="El plazo es de cinco dias habiles."))
c2 = LegalArticleChunk.from_dict(_make_chunk(texto="El plazo es de cinco dias habiles."))
c3 = LegalArticleChunk.from_dict(_make_chunk(texto="La parte actora debera presentar prueba."))

_check("identical texto -> near-dup",         _is_near_dup(c2, [c1]))
_check("different texto -> not near-dup",     not _is_near_dup(c3, [c1]))
_check("empty existing -> not near-dup",      not _is_near_dup(c1, []))


# ---------------------------------------------------------------------------
# 6. Sorting -- jurisdiction and domain boost
# ---------------------------------------------------------------------------

_section("6. Sorting -- jurisdiction and domain alignment")

mixed = [
    _make_chunk("lct_20744",              "1",  "Norma laboral.", 0.9, "labor",         "nacional"),
    _make_chunk("cpcc_jujuy",             "1",  "Norma procesal jujuy.", 0.5, "procedural", "jujuy"),
    _make_chunk("codigo_civil_comercial", "1",  "Norma civil.", 0.5, "civil",          "nacional"),
]
ctx_sort = builder.build_context(
    query="plazo procesal",
    retriever_results=mixed,
    jurisdiction="jujuy",
    domain="procedural",
)
norms = ctx_sort.applicable_norms
# cpcc_jujuy has lower base score but jurisdiction+domain boost should push it up
cpcc_pos = next((i for i, c in enumerate(norms) if c.source_id == "cpcc_jujuy"), None)
_check("cpcc_jujuy boosted to top 2",  cpcc_pos is not None and cpcc_pos <= 1,
       detail=str([c.source_id for c in norms]))


# ---------------------------------------------------------------------------
# 7. Budget truncation
# ---------------------------------------------------------------------------

_section("7. Budget truncation -- direct _truncate tests")

# Test max_results cap directly (bypasses near-dup which needs diverse texts).
cap_builder = LegalContextBuilder(max_chars=500_000, max_results=3, default_jurisdiction="jujuy")

# Build 10 chunks with unique texts so near-dup does not fire.
import string
unique_chunks = [
    LegalArticleChunk.from_dict(
        _make_chunk(
            article=str(i),
            texto=(
                string.ascii_uppercase[i % 26] * 12
                + f" art{i} contenido especifico de esta norma con alcance limitado a supuestos {i}."
            ),
        )
    )
    for i in range(10)
]
_warn: list[str] = []
kept_caps, trunc_caps = cap_builder._truncate(unique_chunks, _warn)
_check("truncated by max_results",          trunc_caps)
_check("exactly max_results kept",          len(kept_caps) == 3)
_check("truncation warning in _warn list",  any("truncad" in w.lower() for w in _warn))

# Test character budget cap.
char_builder = LegalContextBuilder(max_chars=300, max_results=100, default_jurisdiction="jujuy")
# Each chunk costs roughly: len(label)+len(titulo)+len(texto)+80
# With texto="x"*5 and label="Articulo 0": 10 + 0 + 5 + 80 = 95 chars each.
# Budget=300: first chunk fits (95<=300), second (95+95=190<=300), third (285<=300),
# fourth would exceed (380>300), so truncated after 3.
tiny_chunks = [
    LegalArticleChunk.from_dict(_make_chunk(article=str(i), texto="x" * 5))
    for i in range(10)
]
_warn2: list[str] = []
kept_char, trunc_char = char_builder._truncate(tiny_chunks, _warn2)
_check("truncated by char budget",          trunc_char)
_check("char-budget kept count >= 1",       len(kept_char) >= 1)
_check("char-budget kept count < total",    len(kept_char) < len(tiny_chunks))


# ---------------------------------------------------------------------------
# 8. Sections
# ---------------------------------------------------------------------------

_section("8. formatted_sections grouping")

ctx_sec = builder.build_context(query="test", retriever_results=_chunk_list())
sections = ctx_sec.formatted_sections

_check("procedural_norms section present",      "procedural_norms" in sections)
_check("constitutional_norms section present",  "constitutional_norms" in sections)
_check("civil_norms section present",           "civil_norms" in sections)
_check("labor_norms section present",           "labor_norms" in sections)

cpcc_in_section = any(
    c.source_id == "cpcc_jujuy"
    for c in sections.get("procedural_norms", [])
)
_check("cpcc_jujuy in procedural_norms",        cpcc_in_section)


# ---------------------------------------------------------------------------
# 9. Accessors
# ---------------------------------------------------------------------------

_section("9. LegalContext accessors")

ctx_acc = builder.build_context(query="test", retriever_results=_chunk_list())

by_source = ctx_acc.get_by_source("cpcc_jujuy")
_check("get_by_source('cpcc_jujuy') non-empty",    len(by_source) >= 1)
_check("all results have correct source_id",        all(c.source_id == "cpcc_jujuy" for c in by_source))

by_domain = ctx_acc.get_by_domain("procedural")
_check("get_by_domain('procedural') non-empty",    len(by_domain) >= 1)

keys = ctx_acc.citation_keys()
_check("citation_keys() returns set of tuples",    isinstance(keys, set))
_check("citation_keys() non-empty",                len(keys) > 0)


# ---------------------------------------------------------------------------
# 10. format_for_llm
# ---------------------------------------------------------------------------

_section("10. format_for_llm")

ctx_llm = builder.build_context(query="garantia constitucional", retriever_results=_chunk_list())
llm_text = builder.format_for_llm(ctx_llm, include_header=True)
_check("format_for_llm includes header",         "CONTEXTO" in llm_text or "consulta" in llm_text.lower())
_check("format_for_llm includes norms",          any(c.label in llm_text for c in ctx_llm.applicable_norms))

llm_no_header = builder.format_for_llm(ctx_llm, include_header=False)
_check("no-header version == context_text",      llm_no_header == ctx_llm.context_text)


# ---------------------------------------------------------------------------
# 11. Domain inference
# ---------------------------------------------------------------------------

_section("11. Domain inference")

proc_chunks   = [LegalArticleChunk.from_dict(_make_chunk(domain="procedural")) for _ in range(3)]
civil_chunks  = [LegalArticleChunk.from_dict(_make_chunk(domain="civil"))      for _ in range(1)]
unknown_chunk = [LegalArticleChunk.from_dict(_make_chunk(domain="unknown"))]

_check("majority domain inferred", _infer_domain(proc_chunks + civil_chunks) == "procedural")
_check("empty list -> unknown",    _infer_domain([]) == "unknown")
_check("all-unknown -> unknown",   _infer_domain(unknown_chunk) == "unknown")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Results: {_passed} passed, {_failed} failed  (total {_passed + _failed})")
print(f"{'=' * 60}\n")

sys.exit(0 if _failed == 0 else 1)
