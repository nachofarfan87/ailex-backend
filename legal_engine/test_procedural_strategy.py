"""
Tests for ProceduralStrategy.

Run from backend/:
    python -m legal_engine.test_procedural_strategy
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.procedural_strategy import (
    ProceduralPlan,
    ProceduralStep,
    ProceduralStrategy,
    URGENCY_IMMEDIATE,
    URGENCY_SOON,
    URGENCY_NORMAL,
)
from legal_engine.legal_reasoner import (
    LegalReasoner,
    NormativeGrounding,
    ReasoningResult,
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

def _make_reasoning(
    query: str = "plazo contestar demanda",
    domain: str = "procedural",
    confidence: str = "medium",
    confidence_score: float = 0.65,
    citations: list[str] | None = None,
    evidence_sufficient: bool = True,
    limitations: list[str] | None = None,
) -> ReasoningResult:
    return ReasoningResult(
        query=               query,
        query_type=          "deadline_query",
        short_answer=        "Short answer.",
        normative_grounds=   [],
        applied_analysis=    "Analysis text.",
        limitations=         limitations or [],
        citations_used=      citations or ["Art. 163 CPCC Jujuy"],
        confidence=          confidence,
        confidence_score=    confidence_score,
        evidence_sufficient= evidence_sufficient,
        domain=              domain,
        jurisdiction=        "jujuy",
        warnings=            [],
    )


strategy = ProceduralStrategy(default_jurisdiction="jujuy")


# ---------------------------------------------------------------------------
# 1. KB matching -- contestacion de demanda
# ---------------------------------------------------------------------------

_section("1. KB match -- contestacion de demanda")

plan = strategy.generate("plazo para contestar demanda", reasoning_result=_make_reasoning())

_check("returns ProceduralPlan",        isinstance(plan, ProceduralPlan))
_check("query preserved",               plan.query == "plazo para contestar demanda")
_check("steps non-empty",               len(plan.steps) > 0)
_check("has immediate step",            plan.has_immediate_steps(),
       detail=str([s.urgency for s in plan.steps]))
_check("risks non-empty",               len(plan.risks) > 0)
_check("missing_info non-empty",        len(plan.missing_info) > 0)
_check("strategic_notes non-empty",     len(plan.strategic_notes) > 10)
_check("is_empty() False",              not plan.is_empty())
_check("to_dict() serialisable",        isinstance(plan.to_dict(), dict))


# ---------------------------------------------------------------------------
# 2. KB matching -- recurso de apelacion
# ---------------------------------------------------------------------------

_section("2. KB match -- recurso de apelacion")

plan_ap = strategy.generate("como apelar una sentencia", reasoning_result=None)

_check("steps non-empty",               len(plan_ap.steps) > 0)
_check("has immediate step",            plan_ap.has_immediate_steps(),
       detail=str([s.urgency for s in plan_ap.steps]))
_check("risks mention consentimiento",
       any("consentimiento" in r.lower() or "apelacion" in r.lower() or "plazo" in r.lower()
           for r in plan_ap.risks))


# ---------------------------------------------------------------------------
# 3. KB matching -- notificacion
# ---------------------------------------------------------------------------

_section("3. KB match -- notificacion")

plan_not = strategy.generate("notificacion por cedula")
_check("steps non-empty",      len(plan_not.steps) > 0)
_check("risks non-empty",      len(plan_not.risks) > 0)


# ---------------------------------------------------------------------------
# 4. KB matching -- caducidad de instancia
# ---------------------------------------------------------------------------

_section("4. KB match -- caducidad de instancia")

plan_cad = strategy.generate("caducidad de instancia en el proceso")
_check("steps non-empty",         len(plan_cad.steps) > 0)
_check("has immediate step",      plan_cad.has_immediate_steps())


# ---------------------------------------------------------------------------
# 5. KB matching -- medida cautelar
# ---------------------------------------------------------------------------

_section("5. KB match -- medida cautelar")

plan_mc = strategy.generate("solicitar embargo preventivo")
_check("steps non-empty",         len(plan_mc.steps) > 0)
_check("risks non-empty",         len(plan_mc.risks) > 0)


# ---------------------------------------------------------------------------
# 6. No KB match -- generic fallback
# ---------------------------------------------------------------------------

_section("6. Generic fallback for unmatched query")

plan_gen = strategy.generate("situacion juridica completamente generica xyz")
_check("generic plan has steps",       len(plan_gen.steps) > 0)
_check("generic plan has warning",
       any("generico" in w.lower() or "especifico" in w.lower() for w in plan_gen.warnings))


# ---------------------------------------------------------------------------
# 7. Step structure
# ---------------------------------------------------------------------------

_section("7. ProceduralStep structure")

plan_step = strategy.generate("plazo para contestar demanda")
first_step = plan_step.steps[0]

_check("step has order",               isinstance(first_step.order, int))
_check("step has action",              len(first_step.action) > 5)
_check("step has urgency",             first_step.urgency in (URGENCY_IMMEDIATE, URGENCY_SOON, URGENCY_NORMAL, "when_available"))
_check("step to_dict() works",         isinstance(first_step.to_dict(), dict))
_check("steps are ordered",
       all(plan_step.steps[i].order < plan_step.steps[i+1].order
           for i in range(len(plan_step.steps)-1)))


# ---------------------------------------------------------------------------
# 8. Citations from reasoning result
# ---------------------------------------------------------------------------

_section("8. Citations propagated from reasoning result")

citations_in = ["Art. 163 CPCC Jujuy", "Art. 34 CPCC Jujuy"]
plan_cit = strategy.generate(
    "plazo contestar demanda",
    reasoning_result=_make_reasoning(citations=citations_in),
)
_check("citations_used matches reasoning",
       all(c in plan_cit.citations_used for c in citations_in),
       detail=str(plan_cit.citations_used))


# ---------------------------------------------------------------------------
# 9. Low confidence / insufficient evidence enriches risks
# ---------------------------------------------------------------------------

_section("9. Insufficient evidence adds risks")

rr_low = _make_reasoning(
    confidence="low",
    confidence_score=0.30,
    evidence_sufficient=False,
    limitations=["Contexto truncado."],
)
plan_low = strategy.generate("plazo contestar demanda", reasoning_result=rr_low)
_check("insufficient evidence -> extra risk",
       len(plan_low.risks) >= 1)
_check("has warning about evidence",
       any("evidencia" in w.lower() for w in plan_low.warnings))


# ---------------------------------------------------------------------------
# 10. Empty query -- safe fallback
# ---------------------------------------------------------------------------

_section("10. Empty query -- safe fallback")

plan_empty = strategy.generate("")
_check("empty query -> is_empty()",    plan_empty.is_empty())
_check("empty query -> warning",       len(plan_empty.warnings) > 0)
_check("returns ProceduralPlan",       isinstance(plan_empty, ProceduralPlan))

plan_none = strategy.generate("plazo", reasoning_result=None)
_check("None reasoning -> no crash",   isinstance(plan_none, ProceduralPlan))


# ---------------------------------------------------------------------------
# 11. Non-jujuy jurisdiction warning
# ---------------------------------------------------------------------------

_section("11. Non-default jurisdiction")

plan_nac = strategy.generate("contestar demanda", jurisdiction="nacional")
_check("non-jujuy -> jurisdiccion warning",
       any("jurisdiccion" in w.lower() or "jujuy" in w.lower() for w in plan_nac.warnings))


# ---------------------------------------------------------------------------
# 12. to_dict serialisation
# ---------------------------------------------------------------------------

_section("12. to_dict serialisation")

d = strategy.generate("contestar demanda").to_dict()
_check("to_dict() has 'query'",         "query" in d)
_check("to_dict() has 'steps'",         "steps" in d)
_check("to_dict() has 'risks'",         "risks" in d)
_check("to_dict() has 'missing_info'",  "missing_info" in d)
_check("steps is a list",               isinstance(d["steps"], list))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Results: {_passed} passed, {_failed} failed  (total {_passed + _failed})")
print(f"{'=' * 60}\n")

sys.exit(0 if _failed == 0 else 1)
