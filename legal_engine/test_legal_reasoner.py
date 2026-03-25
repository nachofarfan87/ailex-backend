"""
Tests for LegalReasoner.

Run from backend/:
    python -m legal_engine.test_legal_reasoner
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.legal_reasoner import (
    LegalReasoner,
    NormativeGrounding,
    ReasoningResult,
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

def _make_chunk(
    source_id: str, article: str, texto: str,
    domain: str = "procedural", match_type: str = "semantic", score: float = 0.8,
) -> LegalArticleChunk:
    return LegalArticleChunk(
        source_id=source_id, article=article,
        label=f"Articulo {article}", titulo="",
        texto=texto, score=score, match_type=match_type,
        jurisdiction="jujuy", norm_type="codigo", domain=domain,
    )


def _make_context(
    chunks: list[LegalArticleChunk],
    domain: str = "procedural",
    truncated: bool = False,
) -> LegalContext:
    return LegalContext(
        query="test", jurisdiction="jujuy", domain=domain,
        applicable_norms=chunks, total_chars=2000, truncated=truncated,
        source_ids_used=list(dict.fromkeys(c.source_id for c in chunks)),
        context_text="...", formatted_sections={}, warnings=[],
    )


# Rich procedural context
_PROC_CHUNKS = [
    _make_chunk("cpcc_jujuy", "34",  "El juez debera resolver dentro de los cinco dias de quedar la causa en estado de sentencia.", "procedural", "exact", 0.95),
    _make_chunk("cpcc_jujuy", "163", "El plazo para contestar la demanda es de quince dias habiles.", "procedural", "hybrid", 0.88),
    _make_chunk("cpcc_jujuy", "45",  "La notificacion se realizara por cedula dentro de los tres dias.", "procedural", "semantic", 0.72),
]
_PROC_CTX = _make_context(_PROC_CHUNKS)

# Civil context
_CIVIL_CHUNK = _make_chunk("codigo_civil_comercial", "961", "Los contratos deben celebrarse y ejecutarse de buena fe.", "civil", "semantic", 0.85)
_CIVIL_CTX   = _make_context([_CIVIL_CHUNK], domain="civil")

_FAMILY_CTX = _make_context(
    [
        _make_chunk(
            "codigo_civil_comercial",
            "437",
            "El divorcio se decreta judicialmente a peticion de ambos o de uno de los conyuges. La disolucion del matrimonio no requiere invocacion de causa.",
            "civil",
            "semantic",
            0.72,
        ),
        _make_chunk(
            "codigo_civil_comercial",
            "438",
            "Toda peticion de divorcio debe acompanar propuesta reguladora sobre los efectos derivados de la disolucion del vinculo matrimonial.",
            "civil",
            "hybrid",
            0.83,
        ),
    ],
    domain="civil",
)

reasoner = LegalReasoner()


# ---------------------------------------------------------------------------
# 1. Basic structure -- ReasoningResult well-formed
# ---------------------------------------------------------------------------

_section("1. ReasoningResult structure")

result = reasoner.reason(
    query="plazo para contestar demanda",
    context=_PROC_CTX,
    jurisdiction="jujuy",
)

_check("returns ReasoningResult",              isinstance(result, ReasoningResult))
_check("query preserved",                      result.query == "plazo para contestar demanda")
_check("jurisdiction preserved",               result.jurisdiction == "jujuy")
_check("normative_grounds non-empty",          len(result.normative_grounds) > 0)
_check("citations_used non-empty",             len(result.citations_used) > 0)
_check("short_answer non-empty",               len(result.short_answer) > 10)
_check("applied_analysis non-empty",           len(result.applied_analysis) > 20)
_check("confidence is valid label",            result.confidence in ("high", "medium", "low"))
_check("confidence_score 0--1",                0 <= result.confidence_score <= 1)
_check("evidence_sufficient is bool",          isinstance(result.evidence_sufficient, bool))
_check("to_dict() serialisable",               isinstance(result.to_dict(), dict))


# ---------------------------------------------------------------------------
# 2. Query type classification
# ---------------------------------------------------------------------------

_section("2. Query type classification")

_check("'plazo para contestar' -> deadline_query",
       reasoner._classify_query("plazo para contestar demanda") == "deadline_query")
_check("'es valido el recurso' -> validity_query",
       reasoner._classify_query("es valido el recurso de apelacion") == "validity_query")
_check("'requisitos para demandar' -> requirement_query",
       reasoner._classify_query("cuales son los requisitos para demandar") == "requirement_query")
_check("'que es la caducidad' -> definition_query",
       reasoner._classify_query("que es la caducidad de instancia") == "definition_query")
_check("unclassified -> procedure_query",
       reasoner._classify_query("notificacion por cedula") == "procedure_query")


# ---------------------------------------------------------------------------
# 3. Grounding cites only context articles
# ---------------------------------------------------------------------------

_section("3. Citations grounded in context only")

result_g = reasoner.reason(
    query="plazo cinco dias juez resolver",
    context=_PROC_CTX,
)
context_articles = {c.article for c in _PROC_CTX.applicable_norms}

for g in result_g.normative_grounds:
    art_in_ctx = g.article in context_articles
    _check(f"  Ground art.{g.article} exists in context", art_in_ctx,
           detail=f"context has {context_articles}")


# ---------------------------------------------------------------------------
# 4. Confidence degrades with fewer norms
# ---------------------------------------------------------------------------

_section("4. Confidence degradation with fewer norms")

# Single low-score norm -> low confidence
single_chunk = _make_chunk("cpcc_jujuy", "99", "Disposicion general sin especificidad.", score=0.3)
single_ctx   = _make_context([single_chunk])
result_single = reasoner.reason("plazo para contestar", single_ctx)

full_result   = reasoner.reason("plazo para contestar", _PROC_CTX)

_check("single norm has lower confidence than 3 norms",
       result_single.confidence_score <= full_result.confidence_score,
       detail=f"single={result_single.confidence_score}, full={full_result.confidence_score}")
_check("fewer norms may signal evidence_sufficient=False",
       not result_single.evidence_sufficient or result_single.confidence_score < full_result.confidence_score)


# ---------------------------------------------------------------------------
# 5. Empty context -> safe empty result
# ---------------------------------------------------------------------------

_section("5. Empty context -- safe fallback")

empty_ctx = _make_context([])
result_empty = reasoner.reason("plazo para contestar demanda", empty_ctx)

_check("empty context -> low confidence",         result_empty.confidence == "low")
_check("empty context -> evidence_sufficient F",  not result_empty.evidence_sufficient)
_check("empty context -> citations_used empty",   result_empty.citations_used == [])
_check("empty context -> has warning",            len(result_empty.warnings) > 0)
_check("short_answer is a string",                isinstance(result_empty.short_answer, str))

result_none = reasoner.reason("plazo", None)
_check("None context -> no crash",                isinstance(result_none, ReasoningResult))


# ---------------------------------------------------------------------------
# 6. Empty query -> safe result
# ---------------------------------------------------------------------------

_section("6. Empty query -- safe fallback")

result_noq = reasoner.reason("", _PROC_CTX)
_check("empty query -> warning issued",  len(result_noq.warnings) > 0)
_check("returns ReasoningResult",        isinstance(result_noq, ReasoningResult))


# ---------------------------------------------------------------------------
# 7. Truncated context -> limitation flagged
# ---------------------------------------------------------------------------

_section("7. Truncated context -> limitation listed")

trunc_ctx = _make_context(_PROC_CHUNKS, truncated=True)
result_trunc = reasoner.reason("plazo", trunc_ctx)
_check("truncated context -> limitation present",
       any("truncad" in l.lower() for l in result_trunc.limitations))


# ---------------------------------------------------------------------------
# 8. Civil query uses civil norms
# ---------------------------------------------------------------------------

_section("8. Domain-aware reasoning")

result_civil = reasoner.reason("buena fe contractual", _CIVIL_CTX, jurisdiction="jujuy")
_check("civil query -> at least 1 civil norm",
       any(g.source_id == "codigo_civil_comercial" for g in result_civil.normative_grounds),
       detail=str([g.source_id for g in result_civil.normative_grounds]))


# ---------------------------------------------------------------------------
# 9. NormativeGrounding helpers
# ---------------------------------------------------------------------------

_section("9. NormativeGrounding helpers")

g = NormativeGrounding(
    source_id="cpcc_jujuy", article="34",
    label="Articulo 34", texto="El juez resolvera.",
    relevance_note="Regula plazos.", score=0.9,
)
_check("citation() returns string",     isinstance(g.citation(), str))
_check("citation() includes article",   "34" in g.citation())
_check("citation() includes source",    "CPCC" in g.citation() or "cpcc" in g.citation().lower())
_check("to_dict() has 'citation' key",  "citation" in g.to_dict())


# ---------------------------------------------------------------------------
# 10. Analysis text cites norms
# ---------------------------------------------------------------------------

_section("10. Applied analysis content")

result_anal = reasoner.reason("plazo para contestar demanda", _PROC_CTX)
analysis    = result_anal.applied_analysis

_check("analysis is non-empty string",              len(analysis) > 50)
_check("analysis contains 'ANALISIS'",              "ANALISIS" in analysis)
# At least one ground's article should appear in the analysis
_check("analysis cites at least one article",
       any(g.article in analysis for g in result_anal.normative_grounds))


# ---------------------------------------------------------------------------
# 11. Synonym-aware semantic scoring
# ---------------------------------------------------------------------------

_section("11. Synonym-aware scoring")

result_syn = reasoner.reason("disolucion del matrimonio", _FAMILY_CTX)
articles_syn = [g.article for g in result_syn.normative_grounds]
_check("semantic synonym retrieves divorcio norms", "437" in articles_syn or "438" in articles_syn, detail=str(articles_syn))
_check("top grounding prioritises direct semantic equivalent", bool(articles_syn) and articles_syn[0] in {"437", "438"}, detail=str(articles_syn))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Results: {_passed} passed, {_failed} failed  (total {_passed + _failed})")
print(f"{'=' * 60}\n")

sys.exit(0 if _failed == 0 else 1)
