"""
Tests for ArgumentGenerator.

Run from backend/:
    python -m legal_engine.test_argument_generator
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from legal_engine.argument_generator import (
    ALL_MODES,
    MODE_BASE_ARGUMENTAL,
    MODE_BREVE,
    MODE_CONTESTACION,
    MODE_FORMAL,
    MODE_INCIDENTE,
    MODE_MEMORIAL,
    ArgumentGenerator,
    ArgumentSection,
    GeneratedArgument,
    _PLACEHOLDER,
)
from legal_engine.legal_reasoner import (
    NormativeGrounding,
    ReasoningResult,
)
from legal_engine.procedural_strategy import (
    ProceduralPlan,
    ProceduralStep,
    URGENCY_IMMEDIATE,
    URGENCY_SOON,
    URGENCY_NORMAL,
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

def _make_ng(source_id: str = "cpcc_jujuy", article: str = "163",
             texto: str = "El plazo para contestar demanda es de quince dias habiles.",
             relevance_note: str = "Plazo de contestacion.") -> NormativeGrounding:
    return NormativeGrounding(
        source_id=source_id,
        article=article,
        label=f"Articulo {article}",
        texto=texto,
        relevance_note=relevance_note,
        score=0.85,
    )


def _make_reasoning(
    query: str = "plazo para contestar demanda",
    confidence: str = "medium",
    confidence_score: float = 0.65,
    citations: list[str] | None = None,
    limitations: list[str] | None = None,
    evidence_sufficient: bool = True,
    norms: list[NormativeGrounding] | None = None,
    short_answer: str = "El plazo para contestar es de 15 dias habiles.",
) -> ReasoningResult:
    return ReasoningResult(
        query=query,
        query_type="deadline_query",
        short_answer=short_answer,
        normative_grounds=norms if norms is not None else [_make_ng()],
        applied_analysis="Segun el Art. 163 CPCC Jujuy, el plazo es de 15 dias.",
        limitations=limitations or [],
        citations_used=citations or ["Art. 163 CPCC Jujuy"],
        confidence=confidence,
        confidence_score=confidence_score,
        evidence_sufficient=evidence_sufficient,
        domain="procedural",
        jurisdiction="jujuy",
        warnings=[],
    )


def _make_plan(
    steps: list[ProceduralStep] | None = None,
    risks: list[str] | None = None,
    missing_info: list[str] | None = None,
    strategic_notes: str = "Presentar escritos con antelacion.",
    warnings: list[str] | None = None,
) -> ProceduralPlan:
    if steps is None:
        steps = [
            ProceduralStep(order=1, action="Verificar fecha de notificacion", deadline_hint="15 dias", urgency=URGENCY_IMMEDIATE, notes=""),
            ProceduralStep(order=2, action="Redactar escrito de contestacion", deadline_hint=None, urgency=URGENCY_SOON, notes=""),
            ProceduralStep(order=3, action="Ofrecer prueba documental", deadline_hint=None, urgency=URGENCY_NORMAL, notes=""),
        ]
    return ProceduralPlan(
        query="plazo para contestar demanda",
        domain="procedural",
        jurisdiction="jujuy",
        steps=steps,
        risks=risks or ["Riesgo de caducidad si no se contesta en plazo."],
        missing_info=missing_info or ["Fecha exacta de notificacion."],
        strategic_notes=strategic_notes,
        citations_used=["Art. 163 CPCC Jujuy"],
        warnings=warnings or [],
    )


gen = ArgumentGenerator()


# ---------------------------------------------------------------------------
# 1. Output type and common fields
# ---------------------------------------------------------------------------

_section("1. Output type and common fields")

arg = gen.generate("plazo para contestar demanda", mode=MODE_BREVE)

_check("returns GeneratedArgument",    isinstance(arg, GeneratedArgument))
_check("mode preserved",               arg.mode == MODE_BREVE)
_check("query preserved",              arg.query == "plazo para contestar demanda")
_check("title non-empty",              len(arg.title) > 0)
_check("sections non-empty",           len(arg.sections) > 0)
_check("full_text non-empty",          len(arg.full_text) > 0)
_check("to_dict() serialisable",       isinstance(arg.to_dict(), dict))
_check("is_empty() False",             not arg.is_empty())


# ---------------------------------------------------------------------------
# 2. Empty query guard
# ---------------------------------------------------------------------------

_section("2. Empty query guard")

arg_empty = gen.generate("", mode=MODE_BREVE)
_check("empty -> is_empty()",          arg_empty.is_empty())
_check("empty -> warning",             len(arg_empty.warnings) > 0)
_check("empty -> returns GeneratedArgument", isinstance(arg_empty, GeneratedArgument))


# ---------------------------------------------------------------------------
# 3. Unknown mode guard
# ---------------------------------------------------------------------------

_section("3. Unknown mode guard")

arg_unk = gen.generate("consulta juridica", mode="xyz_mode_that_does_not_exist")
_check("unknown mode -> returns GeneratedArgument", isinstance(arg_unk, GeneratedArgument))
_check("unknown mode -> warning",      len(arg_unk.warnings) > 0)
_check("unknown mode -> warning mentions valid modes",
       any("validos" in w.lower() or "valido" in w.lower() for w in arg_unk.warnings))


# ---------------------------------------------------------------------------
# 4. MODE_BREVE
# ---------------------------------------------------------------------------

_section("4. MODE_BREVE")

rr = _make_reasoning()
arg_breve = gen.generate(
    "plazo para contestar demanda",
    mode=MODE_BREVE,
    reasoning_result=rr,
)
_check("breve has >= 3 sections",              len(arg_breve.sections) >= 3)
_check("breve has 'Analisis' section",
       any(s.title == "Analisis" for s in arg_breve.sections))
_check("breve has 'Conclusion' section",
       any(s.title == "Conclusion" for s in arg_breve.sections))
_check("breve cites article in section",
       any("163" in s.content or "163" in " ".join(s.cites)
           for s in arg_breve.sections))
_check("breve full_text contains title",
       arg_breve.title.upper()[:10] in arg_breve.full_text.upper())


# ---------------------------------------------------------------------------
# 5. MODE_FORMAL
# ---------------------------------------------------------------------------

_section("5. MODE_FORMAL")

rr_formal = _make_reasoning(limitations=["El contexto no incluye jurisprudencia."])
arg_formal = gen.generate(
    "contestar demanda por incumplimiento",
    mode=MODE_FORMAL,
    reasoning_result=rr_formal,
    facts={"actor": "Juan Perez", "expediente": "123/2025"},
)
_check("formal has 'Encabezado' section",
       any(s.title == "Encabezado" for s in arg_formal.sections))
_check("formal has 'Marco Normativo' section",
       any(s.title == "Marco Normativo" for s in arg_formal.sections))
_check("formal has 'Conclusion' section",
       any(s.title == "Conclusion" for s in arg_formal.sections))
_check("formal encabezado contains actor",
       any("Juan Perez" in s.content for s in arg_formal.sections))
_check("formal Limitaciones section present",
       any(s.title == "Limitaciones" for s in arg_formal.sections))

# Without required facts -> missing_fields
arg_formal_miss = gen.generate("contestar demanda", mode=MODE_FORMAL)
_check("formal missing actor -> missing_fields",
       "actor" in arg_formal_miss.missing_fields)
_check("formal missing expediente -> missing_fields",
       "expediente" in arg_formal_miss.missing_fields)
_check("formal missing -> DATO_FALTANTE in full_text",
       _PLACEHOLDER in arg_formal_miss.full_text)


# ---------------------------------------------------------------------------
# 6. MODE_CONTESTACION
# ---------------------------------------------------------------------------

_section("6. MODE_CONTESTACION")

arg_cont = gen.generate(
    "contestar demanda laboral",
    mode=MODE_CONTESTACION,
    reasoning_result=_make_reasoning(),
    facts={
        "demandado":  "Empresa SA",
        "demandante": "Juan Lopez",
        "expediente": "456/2025",
        "juzgado":    "Juzgado Civil N.o 3",
        "hechos":     "El actor no tenia relacion de dependencia.",
        "prueba":     "Documental y testimonial.",
        "domicilio_procesal": "Belgrano 123, Jujuy",
    },
)
_check("contestacion has 'Encabezado'",
       any(s.title == "Encabezado" for s in arg_cont.sections))
_check("contestacion has 'I. Personeria'",
       any("Personeria" in s.title for s in arg_cont.sections))
_check("contestacion has 'VI. Petitorio'",
       any("Petitorio" in s.title for s in arg_cont.sections))
_check("contestacion no missing_fields when all facts provided",
       len(arg_cont.missing_fields) == 0,
       detail=str(arg_cont.missing_fields))
_check("contestacion Encabezado contains demandado",
       any("Empresa SA" in s.content for s in arg_cont.sections))
_check("contestacion IV. Derecho has citations",
       any("IV. Derecho" in s.title and s.cites for s in arg_cont.sections))

# Without required facts -> placeholders
arg_cont_miss = gen.generate("contestar demanda", mode=MODE_CONTESTACION)
_check("contestacion missing facts -> missing_fields non-empty",
       len(arg_cont_miss.missing_fields) > 0)


# ---------------------------------------------------------------------------
# 7. MODE_INCIDENTE
# ---------------------------------------------------------------------------

_section("7. MODE_INCIDENTE")

plan_mc = _make_plan(
    steps=[ProceduralStep(order=1, action="Presentar solicitud de embargo", deadline_hint=None, urgency=URGENCY_IMMEDIATE, notes="")],
)
arg_inc = gen.generate(
    "solicitar embargo preventivo",
    mode=MODE_INCIDENTE,
    reasoning_result=_make_reasoning(query="embargo preventivo"),
    procedural_plan=plan_mc,
    facts={
        "requirente":  "Ana Gomez",
        "expediente":  "789/2025",
        "juzgado":     "Juzgado Civil N.o 1",
    },
)
_check("incidente has 'Encabezado'",
       any(s.title == "Encabezado" for s in arg_inc.sections))
_check("incidente has 'IV. Petitorio'",
       any("Petitorio" in s.title for s in arg_inc.sections))
_check("incidente no missing_fields when all facts provided",
       len(arg_inc.missing_fields) == 0,
       detail=str(arg_inc.missing_fields))
_check("incidente infers medida cautelar from query",
       "cautelar" in arg_inc.title.lower() or "embargo" in arg_inc.title.lower())

# Nulidad query
arg_nul = gen.generate("incidente de nulidad de notificacion", mode=MODE_INCIDENTE)
_check("nulidad incident inferred",
       "nulidad" in arg_nul.title.lower())


# ---------------------------------------------------------------------------
# 8. MODE_MEMORIAL
# ---------------------------------------------------------------------------

_section("8. MODE_MEMORIAL")

rr_mem = _make_reasoning(
    norms=[
        _make_ng("cpcc_jujuy", "163", "Plazo 15 dias."),
        _make_ng("cpcc_jujuy", "34", "Deberes del juez.", "Fundamento de autoridad."),
    ],
    citations=["Art. 163 CPCC Jujuy", "Art. 34 CPCC Jujuy"],
)
arg_mem = gen.generate(
    "fundamentos del recurso de apelacion",
    mode=MODE_MEMORIAL,
    reasoning_result=rr_mem,
    facts={
        "requirente": "Pedro Ruiz",
        "expediente": "101/2025",
        "juzgado":    "Camara Civil de Jujuy",
        "hechos":     "La sentencia de primera instancia omitio tratar la prueba documental.",
    },
)
_check("memorial has 'Introduccion'",
       any(s.title == "Introduccion" for s in arg_mem.sections))
_check("memorial has 'Hechos Relevantes' when provided",
       any(s.title == "Hechos Relevantes" for s in arg_mem.sections))
_check("memorial has 'Conclusion'",
       any(s.title == "Conclusion" for s in arg_mem.sections))
_check("memorial has multiple Fundamento sections",
       sum(1 for s in arg_mem.sections if "Fundamento" in s.title) >= 2)
_check("memorial no missing_fields when all facts provided",
       len(arg_mem.missing_fields) == 0,
       detail=str(arg_mem.missing_fields))


# ---------------------------------------------------------------------------
# 9. MODE_BASE_ARGUMENTAL
# ---------------------------------------------------------------------------

_section("9. MODE_BASE_ARGUMENTAL")

rr_ba = _make_reasoning(
    short_answer="El plazo para contestar es de 15 dias habiles.",
    norms=[_make_ng(), _make_ng("constitucion_jujuy", "18", "Defensa en juicio.", "Garantia constitucional.")],
    citations=["Art. 163 CPCC Jujuy", "Art. 18 Constitucion Jujuy"],
)
plan_ba = _make_plan()
arg_ba = gen.generate(
    "plazo para contestar demanda",
    mode=MODE_BASE_ARGUMENTAL,
    reasoning_result=rr_ba,
    procedural_plan=plan_ba,
)
_check("base_argumental has 'Tesis Principal'",
       any(s.title == "Tesis Principal" for s in arg_ba.sections))
_check("base_argumental has 'Argumentos Normativos'",
       any(s.title == "Argumentos Normativos" for s in arg_ba.sections))
_check("base_argumental has 'Riesgos'",
       any("Riesgo" in s.title for s in arg_ba.sections))
_check("base_argumental has 'Informacion Faltante'",
       any("Faltante" in s.title for s in arg_ba.sections))
_check("base_argumental has 'Proximos Pasos'",
       any("Pasos" in s.title for s in arg_ba.sections))
_check("base_argumental Tesis contains short_answer",
       any(
           "15 dias" in s.content or "plazo" in s.content.lower()
           for s in arg_ba.sections if s.title == "Tesis Principal"
       ))
_check("base_argumental Argumentos cites articles",
       any(s.cites for s in arg_ba.sections if s.title == "Argumentos Normativos"))


# ---------------------------------------------------------------------------
# 10. Citations propagated from ReasoningResult
# ---------------------------------------------------------------------------

_section("10. Citations propagated from reasoning result")

citations_in = ["Art. 163 CPCC Jujuy", "Art. 34 CPCC Jujuy"]
rr_cit = _make_reasoning(citations=citations_in)
arg_cit = gen.generate(
    "contestar demanda",
    mode=MODE_BREVE,
    reasoning_result=rr_cit,
)
_check("citations_used matches reasoning",
       all(c in arg_cit.citations_used for c in citations_in),
       detail=str(arg_cit.citations_used))
_check("no duplicate citations",
       len(arg_cit.citations_used) == len(set(arg_cit.citations_used)))


# ---------------------------------------------------------------------------
# 11. No ReasoningResult -- graceful fallback
# ---------------------------------------------------------------------------

_section("11. No reasoning result -- graceful fallback")

for mode in sorted(ALL_MODES):
    arg_no_rr = gen.generate("contestar demanda", mode=mode)
    _check(f"{mode}: no crash without reasoning_result",
           isinstance(arg_no_rr, GeneratedArgument))
    _check(f"{mode}: still has sections",
           len(arg_no_rr.sections) > 0 or mode in (MODE_BREVE,))

# verify breve fallback specifically
arg_fallback = gen.generate("plazo apelacion", mode=MODE_BREVE)
_check("breve fallback: 'Conclusion' section present",
       any(s.title == "Conclusion" for s in arg_fallback.sections))


# ---------------------------------------------------------------------------
# 12. No ProceduralPlan -- graceful fallback
# ---------------------------------------------------------------------------

_section("12. No procedural plan -- graceful fallback")

arg_no_plan = gen.generate(
    "contestar demanda",
    mode=MODE_BASE_ARGUMENTAL,
    reasoning_result=_make_reasoning(),
    procedural_plan=None,
)
_check("base_argumental without plan: no crash",    isinstance(arg_no_plan, GeneratedArgument))
_check("base_argumental without plan: has Tesis",
       any(s.title == "Tesis Principal" for s in arg_no_plan.sections))


# ---------------------------------------------------------------------------
# 13. Jurisdiction warning for non-jujuy
# ---------------------------------------------------------------------------

_section("13. Jurisdiction warning for non-jujuy")

arg_nac = gen.generate(
    "contestar demanda",
    mode=MODE_BREVE,
    jurisdiction="nacional",
)
_check("non-jujuy -> jurisdiction warning",
       any("jurisdiccion" in w.lower() or "nacional" in w.lower() for w in arg_nac.warnings))


# ---------------------------------------------------------------------------
# 14. Warnings propagated from upstream pipeline
# ---------------------------------------------------------------------------

_section("14. Warnings propagated from upstream pipeline")

rr_warn = _make_reasoning()
rr_warn.warnings = ["Contexto insuficiente."]
plan_warn = _make_plan(warnings=["Plazo critico detectado."])
arg_warn = gen.generate(
    "contestar demanda",
    mode=MODE_BREVE,
    reasoning_result=rr_warn,
    procedural_plan=plan_warn,
)
_check("reasoning warnings propagated",
       any("Contexto insuficiente" in w for w in arg_warn.warnings))
_check("plan warnings propagated",
       any("critico" in w.lower() for w in arg_warn.warnings))


# ---------------------------------------------------------------------------
# 15. ArgumentSection helpers
# ---------------------------------------------------------------------------

_section("15. ArgumentSection helpers")

sec = ArgumentSection(title="Analisis", content="Texto de prueba.", cites=["Art. 1"])
_check("section to_dict() has 'title'",   "title"   in sec.to_dict())
_check("section to_dict() has 'content'", "content" in sec.to_dict())
_check("section to_dict() has 'cites'",   "cites"   in sec.to_dict())
_check("section cites is list",           isinstance(sec.to_dict()["cites"], list))


# ---------------------------------------------------------------------------
# 16. GeneratedArgument.to_dict() structure
# ---------------------------------------------------------------------------

_section("16. GeneratedArgument.to_dict() structure")

d = gen.generate("plazo contestar", mode=MODE_FORMAL).to_dict()
for key in ("mode", "query", "title", "sections", "citations_used",
            "warnings", "missing_fields", "full_text"):
    _check(f"to_dict() has '{key}'", key in d)
_check("to_dict()['sections'] is list", isinstance(d["sections"], list))


# ---------------------------------------------------------------------------
# 17. full_text structure
# ---------------------------------------------------------------------------

_section("17. full_text structure")

arg_ft = gen.generate(
    "contestar demanda",
    mode=MODE_BREVE,
    reasoning_result=_make_reasoning(),
)
_check("full_text is non-empty string", isinstance(arg_ft.full_text, str) and len(arg_ft.full_text) > 10)
_check("full_text contains section titles uppercased",
       any(s.title.upper() in arg_ft.full_text for s in arg_ft.sections))


# ---------------------------------------------------------------------------
# 18. Missing fields warning
# ---------------------------------------------------------------------------

_section("18. Missing fields warning")

arg_miss = gen.generate("contestar demanda", mode=MODE_CONTESTACION)
_check("missing fields -> warning in warnings",
       any("DATO_FALTANTE" in w or "campos" in w.lower() for w in arg_miss.warnings))
_check("full_text contains placeholder for missing fields",
       _PLACEHOLDER in arg_miss.full_text)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Results: {_passed} passed, {_failed} failed  (total {_passed + _failed})")
print(f"{'=' * 60}\n")

sys.exit(0 if _failed == 0 else 1)
