"""
Tests for HallucinationGuard.

Run from backend/:
    python -m legal_engine.test_hallucination_guard
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.hallucination_guard import (
    GuardResult,
    HallucinationFlag,
    HallucinationGuard,
    Severity,
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

def _make_context(source_ids_articles: list[tuple[str, str]]) -> LegalContext:
    chunks = [
        LegalArticleChunk(
            source_id=sid, article=art, label=f"Articulo {art}",
            titulo="", texto=f"Texto del art {art}.", score=0.9,
            match_type="exact", jurisdiction="jujuy",
            norm_type="codigo", domain="procedural",
        )
        for sid, art in source_ids_articles
    ]
    return LegalContext(
        query="test", jurisdiction="jujuy", domain="procedural",
        applicable_norms=chunks, total_chars=200, truncated=False,
        source_ids_used=list(dict.fromkeys(s for s, _ in source_ids_articles)),
        context_text="...", formatted_sections={}, warnings=[],
    )


_CTX = _make_context([
    ("cpcc_jujuy", "34"),
    ("cpcc_jujuy", "163"),
    ("constitucion_nacional", "18"),
])

guard = HallucinationGuard()


# ---------------------------------------------------------------------------
# 1. Safe text -- no flags
# ---------------------------------------------------------------------------

_section("1. Safe text -- no flags expected")

safe_text = (
    "Conforme al Art. 34 del CPCC Jujuy, el juez debera resolver dentro del plazo "
    "establecido. En principio, podria corresponder la aplicacion de las normas "
    "procesales vigentes, sin perjuicio de las circunstancias del caso."
)
result_safe = guard.check(safe_text, context=_CTX, base_confidence=0.85)

_check("returns GuardResult",        isinstance(result_safe, GuardResult))
_check("is_safe == True",            result_safe.is_safe,
       detail=str([f.to_dict() for f in result_safe.flags]))
_check("no HIGH flags",              len(result_safe.high_flags()) == 0)
_check("confidence_adjustment 1.0",  result_safe.confidence_adjustment == 1.0)
_check("safe_mode_rewrite is None",  result_safe.safe_mode_rewrite is None)


# ---------------------------------------------------------------------------
# 2. Unsupported citation -- article not in context
# ---------------------------------------------------------------------------

_section("2. Unsupported citation detection")

text_unsp = "Segun el Art. 9999 del CPCC Jujuy, el plazo es de diez dias."
result_unsp = guard.check(text_unsp, context=_CTX, base_confidence=0.85)

high_flags = result_unsp.high_flags()
_check("unsupported_citation HIGH flag raised",
       any(f.flag_type == "unsupported_citation" for f in high_flags),
       detail=str([f.to_dict() for f in result_unsp.flags]))
_check("is_safe == False",           not result_unsp.is_safe)
_check("confidence_adjustment < 1",  result_unsp.confidence_adjustment < 1.0)
_check("safe_mode_rewrite produced", result_unsp.safe_mode_rewrite is not None)

# Article that IS in context should NOT be flagged
text_ok = "El Art. 34 del CPCC Jujuy establece el plazo."
result_ok = guard.check(text_ok, context=_CTX, base_confidence=0.85)
unsupported_ok = [f for f in result_ok.flags if f.flag_type == "unsupported_citation"]
_check("in-context article not flagged", len(unsupported_ok) == 0,
       detail=str([f.excerpt for f in unsupported_ok]))


# ---------------------------------------------------------------------------
# 3. Absolute language detection
# ---------------------------------------------------------------------------

_section("3. Absolute language detection")

text_abs = "Es claro que siempre corresponde el recurso de apelacion en este caso."
result_abs = guard.check(text_abs, context=_CTX, base_confidence=0.85)

abs_flags = [f for f in result_abs.flags if f.flag_type == "absolute_language"]
_check("absolute_language flag raised",  len(abs_flags) >= 1,
       detail=str([f.excerpt for f in result_abs.flags]))
_check("flag has suggestion",            bool(abs_flags[0].suggestion) if abs_flags else False)

# Text with caveats should be safe from absolute-language flag even if it sounds certain
text_with_caveat = "En principio corresponderia la notificacion, verificar circunstancias del caso."
result_cv = guard.check(text_with_caveat, context=None, base_confidence=0.85)
abs_cv = [f for f in result_cv.flags if f.flag_type == "absolute_language"]
_check("caveat text has no absolute_language flag", len(abs_cv) == 0)


# ---------------------------------------------------------------------------
# 4. Jurisdiction mixing
# ---------------------------------------------------------------------------

_section("4. Jurisdiction mixing detection")

text_mix = (
    "Conforme a la normativa nacional y a la normativa de Jujuy, el plazo es diferente "
    "en cada jurisdiccion."
)
result_mix = guard.check(text_mix, context=_CTX, base_confidence=0.85)
mix_flags = [f for f in result_mix.flags if f.flag_type == "jurisdiction_mixing"]
_check("jurisdiction_mixing flag raised",  len(mix_flags) >= 1,
       detail=str([f.to_dict() for f in result_mix.flags]))

# Text that mentions mixing BUT has explicit caveat should NOT be flagged
text_mix_ok = (
    "La normativa nacional sirve como referencia. Sin perjuicio de lo anterior, "
    "en Jujuy podria diferir."
)
result_mix_ok = guard.check(text_mix_ok, context=_CTX, base_confidence=0.85)
mix_ok_flags = [f for f in result_mix_ok.flags if f.flag_type == "jurisdiction_mixing"]
_check("mixing with caveat -> no flag",  len(mix_ok_flags) == 0)

# Single jurisdiction -- no flag
text_one_jur = "La normativa de Jujuy establece el procedimiento."
result_one = guard.check(text_one_jur, context=_CTX, base_confidence=0.85)
mix_one = [f for f in result_one.flags if f.flag_type == "jurisdiction_mixing"]
_check("single jurisdiction -> no mixing flag", len(mix_one) == 0)


# ---------------------------------------------------------------------------
# 5. Overconclusion detection
# ---------------------------------------------------------------------------

_section("5. Overconclusion detection")

text_over = "Por lo tanto corresponde la admision de la demanda en este caso concreto."
# Low confidence should trigger flag
result_over = guard.check(text_over, context=_CTX, base_confidence=0.40)
over_flags = [f for f in result_over.flags if f.flag_type == "overconclusion"]
_check("overconclusion HIGH flag (low confidence)",  len(over_flags) >= 1,
       detail=str([f.to_dict() for f in result_over.flags]))
_check("overconclusion flag is HIGH",                over_flags[0].severity == Severity.HIGH
       if over_flags else False)

# High confidence -> no overconclusion flag
result_high_conf = guard.check(text_over, context=_CTX, base_confidence=0.90)
over_high = [f for f in result_high_conf.flags if f.flag_type == "overconclusion"]
_check("overconclusion suppressed at high confidence", len(over_high) == 0)


# ---------------------------------------------------------------------------
# 6. Unknown source detection
# ---------------------------------------------------------------------------

_section("6. Unknown source detection")

text_unk = "Segun el Codigo Penal argentino, la conducta es ilicita."
result_unk = guard.check(text_unk, context=_CTX, base_confidence=0.85)
unk_flags = [f for f in result_unk.flags if f.flag_type == "unknown_source"]
_check("unknown source HIGH flag raised",  len(unk_flags) >= 1,
       detail=str([f.to_dict() for f in result_unk.flags]))
_check("is_safe == False",                 not result_unk.is_safe)


# ---------------------------------------------------------------------------
# 7. Empty text -- safe default
# ---------------------------------------------------------------------------

_section("7. Edge cases")

result_empty = guard.check("", context=_CTX, base_confidence=0.85)
_check("empty text -> is_safe True",      result_empty.is_safe)
_check("empty text -> warning",           len(result_empty.warnings) > 0)
_check("empty text -> 0 flags",           len(result_empty.flags) == 0)

result_none_ctx = guard.check("El Art. 34 es aplicable.", context=None, base_confidence=0.85)
_check("None context -> no crash",        isinstance(result_none_ctx, GuardResult))
# Without context, unsupported_citation rule cannot fire
unc_none = [f for f in result_none_ctx.flags if f.flag_type == "unsupported_citation"]
_check("no unsupported_citation without context", len(unc_none) == 0)


# ---------------------------------------------------------------------------
# 8. Confidence adjustment accumulation
# ---------------------------------------------------------------------------

_section("8. Confidence adjustment")

# A text with many problems should get a lower confidence adjustment
text_many = (
    "Es claro que siempre procede. Por lo tanto corresponde la nulidad absoluta. "
    "Segun el Codigo Penal y normativa nacional y de Jujuy, definitivamente procede."
)
result_many = guard.check(text_many, context=_CTX, base_confidence=0.40)
_check("multiple flags -> adj < 1.0",     result_many.confidence_adjustment < 1.0)
_check("confidence adj >= 0.05 (floor)",  result_many.confidence_adjustment >= 0.05)
_check("safe_mode_rewrite produced",      result_many.safe_mode_rewrite is not None)
_check("rewrite contains ADVERTENCIA",
       "ADVERTENCIA" in (result_many.safe_mode_rewrite or ""))


# ---------------------------------------------------------------------------
# 9. GuardResult helpers
# ---------------------------------------------------------------------------

_section("9. GuardResult helpers")

result_mixed = guard.check(
    "Definitivamente siempre corresponde segun el Art. 9999.",
    context=_CTX, base_confidence=0.40,
)
_check("high_flags() non-empty",          len(result_mixed.high_flags()) > 0)
_check("to_dict() has 'is_safe'",         "is_safe" in result_mixed.to_dict())
_check("to_dict() has 'flags'",           "flags" in result_mixed.to_dict())


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Results: {_passed} passed, {_failed} failed  (total {_passed + _failed})")
print(f"{'=' * 60}\n")

sys.exit(0 if _failed == 0 else 1)
