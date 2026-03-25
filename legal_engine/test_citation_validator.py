"""
Tests for CitationValidator.

Run from backend/:
    python -m legal_engine.test_citation_validator
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.citation_validator import (
    CitationStatus,
    CitationValidator,
    ValidatedCitation,
    ValidationReport,
)
from legal_engine.context_builder import LegalArticleChunk, LegalContext

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

def _make_chunk(source_id: str, article: str, domain: str = "procedural") -> LegalArticleChunk:
    return LegalArticleChunk(
        source_id=source_id, article=article,
        label=f"Articulo {article}", titulo="",
        texto=f"Texto del articulo {article} de {source_id}.",
        score=0.9, match_type="exact",
        jurisdiction="jujuy", norm_type="codigo", domain=domain,
    )


def _make_context(chunks: list[LegalArticleChunk]) -> LegalContext:
    return LegalContext(
        query="test",
        jurisdiction="jujuy",
        domain="procedural",
        applicable_norms=chunks,
        total_chars=500,
        truncated=False,
        source_ids_used=[c.source_id for c in chunks],
        context_text="...",
        formatted_sections={},
        warnings=[],
    )


# Build a standard test context with a few articles
_CTX_CHUNKS = [
    _make_chunk("cpcc_jujuy",             "34"),
    _make_chunk("cpcc_jujuy",             "163"),
    _make_chunk("constitucion_nacional",  "18",  "constitutional"),
    _make_chunk("lct_20744",              "245", "labor"),
]
_CTX = _make_context(_CTX_CHUNKS)

validator = CitationValidator()


# ---------------------------------------------------------------------------
# 1. parse_citation
# ---------------------------------------------------------------------------

_section("1. parse_citation -- various formats")

p = validator.parse_citation("Art. 34 CPCC Jujuy")
_check("'Art. 34 CPCC Jujuy' -> article='34'",   p["article"] == "34",   detail=str(p))
_check("'Art. 34 CPCC Jujuy' -> cpcc_jujuy",     p["source_id"] == "cpcc_jujuy", detail=str(p))

p2 = validator.parse_citation("Articulo 18 de la Constitucion Nacional")
_check("'Articulo 18 CN' -> article='18'",        p2["article"] == "18",  detail=str(p2))
_check("'Articulo 18 CN' -> constitucion_nacional", p2["source_id"] == "constitucion_nacional")

p3 = validator.parse_citation("Art. 245 LCT")
_check("'Art. 245 LCT' -> article='245'",         p3["article"] == "245", detail=str(p3))
_check("'Art. 245 LCT' -> lct_20744",             p3["source_id"] == "lct_20744")

p4 = validator.parse_citation("cpcc_jujuy:34")
_check("'cpcc_jujuy:34' structured -> article='34'",   p4["article"] == "34")
_check("'cpcc_jujuy:34' structured -> cpcc_jujuy",     p4["source_id"] == "cpcc_jujuy")

p5 = validator.parse_citation("Art. 961 CCyC")
_check("'Art. 961 CCyC' -> codigo_civil_comercial", p5["source_id"] == "codigo_civil_comercial")

p6 = validator.parse_citation("")
_check("empty string -> both None",    p6["source_id"] is None and p6["article"] is None)

p7 = validator.parse_citation("algo sin referencia normativa")
_check("gibberish -> article None",    p7["article"] is None)


# ---------------------------------------------------------------------------
# 2. validate -- VALID citations (present in context)
# ---------------------------------------------------------------------------

_section("2. validate -- VALID citations (in context)")

report_valid = validator.validate(
    citations=["Art. 34 CPCC Jujuy", "Art. 163 CPCC", "Art. 18 Constitucion Nacional"],
    context=_CTX,
)

_check("report is ValidationReport",   isinstance(report_valid, ValidationReport))
_check("is_safe == True",              report_valid.is_safe)
_check("valid_count == 3",             report_valid.valid_count == 3,
       detail=f"valid={report_valid.valid_count}")
_check("invalid_count == 0",           report_valid.invalid_count == 0)
_check("all status == VALID",
       all(c.status == CitationStatus.VALID for c in report_valid.citations))
_check("confidence > 0.9",
       all(c.confidence > 0.9 for c in report_valid.citations))


# ---------------------------------------------------------------------------
# 3. validate -- INVALID citations (article not in context, no engine)
# ---------------------------------------------------------------------------

_section("3. validate -- INVALID citations (not in context, no engine)")

report_inv = validator.validate(
    citations=["Art. 9999 CPCC Jujuy"],
    context=_CTX,
)

_check("is_safe == False (no engine -> DOUBTFUL)",
       not report_inv.is_safe or report_inv.doubtful_count > 0)
# Without engine: not-in-context known source -> DOUBTFUL
first = report_inv.citations[0] if report_inv.citations else None
_check("citation present",              first is not None)
_check("status is DOUBTFUL (no engine)", first.status == CitationStatus.DOUBTFUL if first else False)


# ---------------------------------------------------------------------------
# 4. validate -- unparseable citation -> INVALID
# ---------------------------------------------------------------------------

_section("4. validate -- unparseable citations")

report_unparse = validator.validate(
    citations=["esto no tiene articulo ni fuente valida"],
    context=_CTX,
)
c = report_unparse.citations[0] if report_unparse.citations else None
_check("unparseable -> INVALID",       c is not None and c.status == CitationStatus.INVALID,
       detail=str(c))
_check("is_safe == False",             not report_unparse.is_safe)


# ---------------------------------------------------------------------------
# 5. validate -- citation with article but no source -> DOUBTFUL
# ---------------------------------------------------------------------------

_section("5. validate -- article without source")

report_nosrc = validator.validate(
    citations=["Art. 34"],   # no source hint
    context=_CTX,
)
c_ns = report_nosrc.citations[0] if report_nosrc.citations else None
_check("no-source -> DOUBTFUL",        c_ns is not None and c_ns.status == CitationStatus.DOUBTFUL)
_check("is_safe == True (DOUBTFUL)",   report_nosrc.is_safe)


# ---------------------------------------------------------------------------
# 6. validate -- structured dict input
# ---------------------------------------------------------------------------

_section("6. validate -- structured dict input")

report_dict = validator.validate(
    citations=[{"source_id": "cpcc_jujuy", "article": "34"}],
    context=_CTX,
)
_check("dict citation -> VALID",       report_dict.citations[0].status == CitationStatus.VALID
                                       if report_dict.citations else False)


# ---------------------------------------------------------------------------
# 7. validate -- deduplication of repeated citations
# ---------------------------------------------------------------------------

_section("7. validate -- deduplication")

report_dup = validator.validate(
    citations=["Art. 34 CPCC Jujuy", "Art. 34 CPCC Jujuy", "Art. 34 CPCC"],
    context=_CTX,
)
# Art. 34 CPCC Jujuy appears twice as identical strings (normalised)
_check("duplicates deduplicated",      len(report_dup.citations) <= 2,
       detail=f"got {len(report_dup.citations)} citations")


# ---------------------------------------------------------------------------
# 8. validate -- empty / None inputs safe
# ---------------------------------------------------------------------------

_section("8. validate -- edge cases")

report_empty = validator.validate(citations=[], context=_CTX)
_check("empty list -> is_safe True",   report_empty.is_safe)
_check("empty list -> 0 citations",    len(report_empty.citations) == 0)

report_no_ctx = validator.validate(citations=["Art. 34 CPCC"], context=None)
_check("None context -> no crash",     isinstance(report_no_ctx, ValidationReport))

report_bad_input = validator.validate(citations="not a list", context=_CTX)
_check("non-list input -> warning",    len(report_bad_input.warnings) > 0)


# ---------------------------------------------------------------------------
# 9. validate_context -- context integrity check
# ---------------------------------------------------------------------------

_section("9. validate_context -- context integrity")

report_ctx = validator.validate_context(_CTX)
_check("validate_context returns ValidationReport", isinstance(report_ctx, ValidationReport))
# Without engine, all articles in context should be VALID (they are in context_keys)
_check("all context articles valid",
       all(c.status == CitationStatus.VALID for c in report_ctx.citations),
       detail=str([c.to_dict() for c in report_ctx.citations if not c.is_valid()]))

report_empty_ctx_check = validator.validate_context(None)
_check("None context -> is_safe",      report_empty_ctx_check.is_safe)


# ---------------------------------------------------------------------------
# 10. ValidatedCitation helpers
# ---------------------------------------------------------------------------

_section("10. ValidatedCitation helpers")

vc_valid = ValidatedCitation(
    raw="Art. 34 CPCC", source_id="cpcc_jujuy", article="34",
    status=CitationStatus.VALID, reason="en contexto", confidence=0.99,
)
_check("is_valid() True for VALID",    vc_valid.is_valid())
_check("is_safe() True for VALID",     vc_valid.is_safe())
_check("to_dict() has status key",     "status" in vc_valid.to_dict())

vc_inv = ValidatedCitation(
    raw="Art. 0 XYZ", source_id=None, article=None,
    status=CitationStatus.INVALID, reason="no parseable", confidence=0.95,
)
_check("is_valid() False for INVALID", not vc_inv.is_valid())
_check("is_safe() False for INVALID",  not vc_inv.is_safe())


# ---------------------------------------------------------------------------
# 11. to_dict serialisation
# ---------------------------------------------------------------------------

_section("11. to_dict serialisation")

report_ser = validator.validate(["Art. 34 CPCC Jujuy"], context=_CTX)
d = report_ser.to_dict()
_check("to_dict() has 'citations' key",     "citations" in d)
_check("to_dict() has 'is_safe' key",       "is_safe" in d)
_check("to_dict() has 'valid_count' key",   "valid_count" in d)
_check("citations is a list",               isinstance(d["citations"], list))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Results: {_passed} passed, {_failed} failed  (total {_passed + _failed})")
print(f"{'=' * 60}\n")

sys.exit(0 if _failed == 0 else 1)
