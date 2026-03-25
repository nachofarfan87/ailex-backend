"""Integration tests: case_profile_builder + case_strategy_builder end-to-end.

Each test simulates a realistic mixed case, builds the profile, feeds it into
the strategy builder, and verifies the *output* is jurídicamente coherent:
  - correct primary_domain
  - complete case_domains
  - domain-specific narrative (not generic)
  - cross-domain focus when applicable
  - secondary_domain_notes for non-primary pretensiones
  - no scenario leaks between domains
  - no contradictory or vacuous language
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from legal_engine.case_profile_builder import build_case_profile
from legal_engine.case_strategy_builder import build_case_strategy


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _reasoning():
    return SimpleNamespace(
        short_answer="Existe una base inicial para estructurar el planteo.",
        applied_analysis="La estrategia debe conectar conflicto, requisitos y prueba utilizable.",
    )


_NO_JURIS = {"source_quality": "none", "jurisprudence_strength": "none"}


def _run(
    query: str,
    *,
    classification: dict | None = None,
    case_theory: dict | None = None,
    conflict: dict | None = None,
    normative_reasoning: dict | None = None,
    case_evaluation: dict | None = None,
    facts: dict | None = None,
):
    cls = classification or {}
    ct = case_theory or {}
    conf = conflict or {}
    nr = normative_reasoning or {"requirements": [], "applied_rules": []}
    facts = facts or {}

    profile = build_case_profile(query, cls, ct, conf, nr, None, facts)
    strategy = build_case_strategy(
        query=query,
        case_profile=profile,
        case_theory=ct,
        conflict=conf,
        case_evaluation=case_evaluation or {},
        procedural_plan=None,
        jurisprudence_analysis=_NO_JURIS,
        reasoning_result=_reasoning(),
    )
    return profile, strategy


def _all_strategy_text(strategy: dict) -> str:
    parts = [
        strategy.get("strategic_narrative", ""),
        " ".join(strategy.get("conflict_summary", [])),
        " ".join(strategy.get("risk_analysis", [])),
        " ".join(strategy.get("recommended_actions", [])),
        " ".join(strategy.get("procedural_focus", [])),
        " ".join(strategy.get("secondary_domain_notes", [])),
    ]
    return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# 1. Divorcio + bienes + hijos
# ---------------------------------------------------------------------------

class TestDivorcioBienesHijos:
    @pytest.fixture()
    def result(self):
        return _run(
            "quiero divorciarme, tenemos hijos menores y un bien ganancial en cotitularidad",
            case_theory={
                "primary_theory": "Divorcio unilateral con hijos menores y bienes gananciales a liquidar.",
                "objective": "Obtener sentencia de divorcio y resolver bienes e hijos.",
            },
            conflict={
                "core_dispute": "Divorcio con efectos patrimoniales y personales pendientes.",
                "most_vulnerable_point": "Falta definir regimen de bienes y situacion de hijos.",
            },
        )

    def test_primary_domain_is_divorcio(self, result):
        profile, _ = result
        assert profile["case_domain"] == "divorcio"

    def test_case_domains_includes_patrimonial(self, result):
        profile, _ = result
        assert "conflicto_patrimonial" in profile["case_domains"]

    def test_narrative_mentions_propuesta_reguladora(self, result):
        _, strategy = result
        assert "propuesta reguladora" in strategy["strategic_narrative"].lower()

    def test_narrative_mentions_hijos(self, result):
        _, strategy = result
        assert "hijos" in strategy["strategic_narrative"].lower()

    def test_narrative_mentions_bienes(self, result):
        _, strategy = result
        text = _all_strategy_text(strategy)
        assert "bienes" in text or "patrimonial" in text

    def test_recommended_actions_not_empty(self, result):
        _, strategy = result
        assert len(strategy["recommended_actions"]) >= 2

    def test_secondary_domain_notes_patrimonial(self, result):
        _, strategy = result
        notes = strategy.get("secondary_domain_notes", [])
        assert any("patrimonial" in n.lower() for n in notes)

    def test_no_alimentos_language(self, result):
        _, strategy = result
        narrative = strategy["strategic_narrative"].lower()
        assert "cuota alimentaria" not in narrative
        assert "incumplimiento alimentario" not in narrative


# ---------------------------------------------------------------------------
# 2. Alimentos + cuidado personal
# ---------------------------------------------------------------------------

class TestAlimentosCuidadoPersonal:
    @pytest.fixture()
    def result(self):
        return _run(
            "reclamo alimentos y cuidado personal de mi hijo de 5 años que vive conmigo",
            classification={"action_slug": "alimentos_hijos"},
            case_theory={
                "primary_theory": "Alimentos para hijo menor con cuidado personal a cargo de la madre.",
                "objective": "Obtener cuota alimentaria y resolver cuidado personal.",
            },
            conflict={
                "core_dispute": "Alimentos e incumplimiento del progenitor no conviviente.",
                "most_vulnerable_point": "Falta acreditar gastos y capacidad contributiva.",
            },
        )

    def test_primary_is_alimentos(self, result):
        profile, _ = result
        assert profile["case_domain"] == "alimentos"
        assert profile["is_alimentos"] is True

    def test_cuidado_personal_is_secondary(self, result):
        profile, _ = result
        assert "cuidado_personal" in profile["case_domains"]

    def test_scenarios_are_alimentos_only(self, result):
        profile, _ = result
        assert "hijo_menor" in profile["scenarios"]
        # cuidado_personal scenarios should not leak
        assert "centro_de_vida" not in profile["scenarios"]
        assert "cuidado_compartido" not in profile["scenarios"]

    def test_narrative_is_alimentos_specific(self, result):
        _, strategy = result
        narrative = strategy["strategic_narrative"].lower()
        assert "alimentos" in narrative
        assert "necesidades concretas" in narrative or "incumplimiento" in narrative

    def test_cross_domain_focus(self, result):
        profile, _ = result
        focus = " ".join(profile.get("strategic_focus", [])).lower()
        assert "alimentos" in focus and "cuidado personal" in focus

    def test_secondary_notes_cuidado(self, result):
        _, strategy = result
        notes = strategy.get("secondary_domain_notes", [])
        assert any("cuidado personal" in n.lower() for n in notes)

    def test_secondary_notes_mention_centro_de_vida(self, result):
        _, strategy = result
        notes_text = " ".join(strategy.get("secondary_domain_notes", [])).lower()
        assert "centro de vida" in notes_text or "convive" in notes_text


# ---------------------------------------------------------------------------
# 3. Régimen comunicacional + cuidado personal
# ---------------------------------------------------------------------------

class TestRegimenCuidado:
    @pytest.fixture()
    def result(self):
        return _run(
            "la madre impide el contacto con mi hijo, solicito cuidado personal y regimen de comunicacion",
            case_theory={
                "primary_theory": "Impedimento de contacto con pedido de cuidado personal.",
                "objective": "Restablecer contacto y resolver cuidado personal.",
            },
            conflict={
                "core_dispute": "Obstruccion del contacto paterno-filial.",
                "most_vulnerable_point": "Falta prueba autonoma del impedimento.",
            },
        )

    def test_primary_is_cuidado_personal(self, result):
        profile, _ = result
        # cuidado_personal has higher priority than regimen_comunicacional
        assert profile["case_domain"] == "cuidado_personal"

    def test_regimen_is_secondary(self, result):
        profile, _ = result
        assert "regimen_comunicacional" in profile["case_domains"]

    def test_narrative_mentions_cuidado(self, result):
        _, strategy = result
        narrative = strategy["strategic_narrative"].lower()
        assert "cuidado" in narrative or "centro de vida" in narrative or "interes superior" in narrative

    def test_secondary_notes_regimen(self, result):
        _, strategy = result
        notes = strategy.get("secondary_domain_notes", [])
        assert any("regimen comunicacional" in n.lower() for n in notes)

    def test_secondary_notes_mention_contacto(self, result):
        _, strategy = result
        notes_text = " ".join(strategy.get("secondary_domain_notes", [])).lower()
        assert "contacto" in notes_text or "dias" in notes_text


# ---------------------------------------------------------------------------
# 4. Divorcio + conflicto patrimonial (bienes gananciales en cotitularidad)
# ---------------------------------------------------------------------------

class TestDivorcioPatrimonial:
    @pytest.fixture()
    def result(self):
        return _run(
            "divorcio y quiero resolver la cotitularidad del departamento ganancial",
            case_theory={
                "primary_theory": "Divorcio con conflicto patrimonial por inmueble ganancial en cotitularidad.",
                "objective": "Obtener divorcio y adjudicacion del inmueble.",
                "likely_points_of_conflict": ["Cotitularidad del inmueble con el ex conyuge."],
            },
            conflict={
                "core_dispute": "Resolver divorcio y cotitularidad del departamento ganancial.",
                "most_vulnerable_point": "No esta claro si el bien es ganancial o propio.",
            },
        )

    def test_primary_is_divorcio(self, result):
        profile, _ = result
        assert profile["case_domain"] == "divorcio"

    def test_patrimonial_is_secondary(self, result):
        profile, _ = result
        assert "conflicto_patrimonial" in profile["case_domains"]

    def test_narrative_covers_divorcio(self, result):
        _, strategy = result
        narrative = strategy["strategic_narrative"].lower()
        assert "propuesta reguladora" in narrative or "divorcio" in narrative

    def test_conflict_summary_not_empty(self, result):
        _, strategy = result
        assert len(strategy["conflict_summary"]) >= 2

    def test_secondary_notes_patrimonial(self, result):
        _, strategy = result
        notes = strategy.get("secondary_domain_notes", [])
        assert any("patrimonial" in n.lower() for n in notes)

    def test_cross_domain_focus_bienes(self, result):
        profile, _ = result
        focus = " ".join(profile.get("strategic_focus", [])).lower()
        assert "divorcio" in focus and "patrimonial" in focus


# ---------------------------------------------------------------------------
# 5. Alimentos hijo mayor + no estudia (single domain, edge case)
# ---------------------------------------------------------------------------

class TestAlimentosHijoMayorNoEstudia:
    @pytest.fixture()
    def result(self):
        return _run(
            "mi hija tiene 22 años y no estudia, hasta cuando corresponde cuota alimentaria",
            classification={"action_slug": "alimentos_hijos"},
            case_theory={
                "primary_theory": "La hija tiene 22 anos y no estudia; se consulta continuidad de cuota.",
                "objective": "Determinar si corresponde sostener o revisar la cuota.",
            },
            conflict={
                "core_dispute": "Alcance de cuota para hija mayor de 21 que no estudia.",
                "most_vulnerable_point": "Falta precisar si trabaja o tiene ingresos propios.",
            },
        )

    def test_single_domain(self, result):
        profile, _ = result
        assert profile["case_domains"] == ["alimentos"]
        assert profile["is_alimentos"] is True

    def test_hijo_mayor_no_estudia_scenario(self, result):
        profile, _ = result
        assert "hijo_mayor_no_estudia" in profile["scenarios"]

    def test_narrative_blocks_academic_strategy(self, result):
        _, strategy = result
        narrative = strategy["strategic_narrative"].lower()
        assert "no debe tratarse como hijo mayor estudiante" in narrative

    def test_no_regularidad_academica_in_actions(self, result):
        _, strategy = result
        actions = " ".join(strategy["recommended_actions"]).lower()
        assert "regularidad academica" not in actions
        assert "alumno regular" not in actions

    def test_risk_mentions_no_estudia(self, result):
        _, strategy = result
        risks = " ".join(strategy["risk_analysis"]).lower()
        assert "no estudia" in risks

    def test_no_secondary_domain_notes(self, result):
        _, strategy = result
        assert strategy.get("secondary_domain_notes") == []


# ---------------------------------------------------------------------------
# 6. Single-domain strategies produce domain-specific output (not generic)
# ---------------------------------------------------------------------------

class TestSingleDomainNarrativeQuality:

    def test_divorcio_unilateral_narrative(self):
        _, strategy = _run(
            "quiero divorciarme",
            case_theory={"primary_theory": "Divorcio unilateral.", "objective": "Obtener sentencia de divorcio."},
            conflict={"core_dispute": "Disolucion del vinculo matrimonial."},
        )
        narrative = strategy["strategic_narrative"].lower()
        assert "propuesta reguladora" in narrative or "art. 438" in narrative

    def test_cuidado_personal_narrative(self):
        _, strategy = _run(
            "solicito cuidado personal de mi hijo, centro de vida conmigo",
            case_theory={"primary_theory": "Cuidado personal.", "objective": "Resolver cuidado."},
            conflict={"core_dispute": "Definir cuidado personal del nino."},
        )
        narrative = strategy["strategic_narrative"].lower()
        assert "centro de vida" in narrative or "interes superior" in narrative or "convivencia" in narrative

    def test_regimen_comunicacional_impedimento_narrative(self):
        _, strategy = _run(
            "impedimento de contacto con mi hijo, solicito regimen de comunicacion",
            case_theory={"primary_theory": "Impedimento de contacto.", "objective": "Restablecer contacto."},
            conflict={"core_dispute": "Obstruccion del vinculo paterno-filial."},
        )
        narrative = strategy["strategic_narrative"].lower()
        assert "impedimento" in narrative or "medida" in narrative or "cautelar" in narrative

    def test_conflicto_patrimonial_narrative(self):
        _, strategy = _run(
            "conflicto patrimonial por bien ganancial en cotitularidad",
            case_theory={"primary_theory": "Conflicto por bien ganancial.", "objective": "Liquidar bien ganancial."},
            conflict={"core_dispute": "Resolver cotitularidad de inmueble ganancial."},
        )
        narrative = strategy["strategic_narrative"].lower()
        assert "titularidad" in narrative or "ganancial" in narrative
        # the narrative says "evitar formulas genericas" which is domain-specific guidance
        assert "concentrarse en titularidad" in narrative or "regimen aplicable" in narrative

    def test_conflicto_patrimonial_recommended_actions(self):
        _, strategy = _run(
            "conflicto patrimonial por bien ganancial en cotitularidad",
            classification={"action_slug": "conflicto_patrimonial"},
            case_theory={"primary_theory": "Conflicto por bien ganancial.", "objective": "Liquidar bien ganancial."},
            conflict={"core_dispute": "Resolver cotitularidad de inmueble ganancial."},
        )
        actions = " ".join(strategy["recommended_actions"]).lower()
        assert "cotitularidad" in actions or "ganancial" in actions

    def test_regimen_comunicacional_recommended_actions(self):
        _, strategy = _run(
            "impedimento de contacto con mi hijo, regimen de comunicacion",
            classification={"action_slug": "regimen_comunicacional"},
            case_theory={"primary_theory": "Impedimento de contacto.", "objective": "Restablecer contacto."},
            conflict={"core_dispute": "Obstruccion del contacto."},
        )
        actions = " ".join(strategy["recommended_actions"]).lower()
        assert "audiencia inmediata" in actions or "medida cautelar" in actions

    def test_cuidado_personal_recommended_actions_riesgo(self):
        _, strategy = _run(
            "cuidado personal, el nino esta en riesgo por maltrato",
            classification={"action_slug": "cuidado_personal"},
            case_theory={"primary_theory": "Riesgo para el nino.", "objective": "Proteccion urgente."},
            conflict={"core_dispute": "Situacion de riesgo."},
        )
        actions = " ".join(strategy["recommended_actions"]).lower()
        assert "proteccion" in actions or "riesgo" in actions

    def test_divorcio_recommended_actions_bienes(self):
        _, strategy = _run(
            "divorcio con bienes gananciales",
            classification={"action_slug": "divorcio"},
            case_theory={"primary_theory": "Divorcio con bienes.", "objective": "Divorcio y liquidacion."},
            conflict={"core_dispute": "Divorcio con efectos patrimoniales."},
        )
        actions = " ".join(strategy["recommended_actions"]).lower()
        assert "bienes" in actions or "inventariar" in actions or "ganancial" in actions


# ---------------------------------------------------------------------------
# 7. Risk analysis is domain-aware
# ---------------------------------------------------------------------------

class TestRiskAnalysisDomainAware:

    def test_divorcio_bienes_risk(self):
        _, strategy = _run(
            "divorcio con bienes gananciales y hijos menores",
            classification={"action_slug": "divorcio"},
            case_theory={"primary_theory": "Divorcio.", "objective": "Divorcio."},
            conflict={"core_dispute": "Divorcio."},
        )
        risks = " ".join(strategy["risk_analysis"]).lower()
        assert "bienes" in risks or "regimen" in risks

    def test_cuidado_cambio_risk(self):
        _, strategy = _run(
            "solicito cambio de cuidado personal por mudanza",
            case_theory={"primary_theory": "Cambio de cuidado.", "objective": "Modificar cuidado."},
            conflict={"core_dispute": "Cambio de cuidado.", "most_vulnerable_point": "Falta prueba de cambio."},
        )
        risks = " ".join(strategy["risk_analysis"]).lower()
        assert "cambio" in risks or "circunstancias" in risks

    def test_regimen_impedimento_risk(self):
        _, strategy = _run(
            "impedimento de contacto con mi hijo, regimen de comunicacion",
            case_theory={"primary_theory": "Impedimento.", "objective": "Contacto."},
            conflict={"core_dispute": "Obstruccion.", "most_vulnerable_point": "Falta prueba."},
        )
        risks = " ".join(strategy["risk_analysis"]).lower()
        assert "impedimento" in risks or "prueba" in risks

    def test_conflicto_patrimonial_risk(self):
        profile, strategy = _run(
            "conflicto patrimonial por bien ganancial en cotitularidad",
            classification={"action_slug": "conflicto_patrimonial"},
            case_theory={"primary_theory": "Conflicto patrimonial.", "objective": "Liquidar."},
            conflict={"core_dispute": "Cotitularidad.", "most_vulnerable_point": "Caracter del bien incierto."},
        )
        risks = " ".join(strategy["risk_analysis"]).lower()
        if profile.get("needs_proof_strengthening"):
            assert "titularidad" in risks or "patrimonial" in risks or "bien" in risks


# ---------------------------------------------------------------------------
# 8. secondary_domain_notes structure
# ---------------------------------------------------------------------------

class TestSecondaryDomainNotesStructure:

    def test_empty_for_single_domain(self):
        _, strategy = _run("alimentos para mi hijo", classification={"action_slug": "alimentos_hijos"})
        assert strategy["secondary_domain_notes"] == []

    def test_present_for_multi_domain(self):
        _, strategy = _run("divorcio con alimentos para los hijos y bienes gananciales")
        notes = strategy["secondary_domain_notes"]
        assert len(notes) >= 1

    def test_notes_are_actionable(self):
        """Each note should mention a pretension and what to do about it."""
        _, strategy = _run("divorcio con alimentos para los hijos y cuidado personal")
        for note in strategy["secondary_domain_notes"]:
            lower = note.lower()
            assert "pretension secundaria" in lower
            # should contain some action guidance
            assert any(word in lower for word in ("verificar", "incluir", "definir", "identificar"))


# ---------------------------------------------------------------------------
# 9. Conflict summary is domain-specific
# ---------------------------------------------------------------------------

class TestConflictSummaryDomainSpecific:

    def test_divorcio_conflict_summary_bienes(self):
        _, strategy = _run(
            "divorcio con bienes gananciales",
            classification={"action_slug": "divorcio"},
            case_theory={"primary_theory": "Divorcio.", "objective": "Divorcio."},
            conflict={"core_dispute": "Divorcio con bienes."},
        )
        summary = " ".join(strategy["conflict_summary"]).lower()
        assert "bienes" in summary or "propuesta reguladora" in summary

    def test_cuidado_personal_conflict_summary_centro_vida(self):
        _, strategy = _run(
            "cuidado personal, centro de vida del nino conmigo",
            case_theory={"primary_theory": "Cuidado personal.", "objective": "Cuidado."},
            conflict={"core_dispute": "Cuidado personal."},
        )
        summary = " ".join(strategy["conflict_summary"]).lower()
        assert "centro de vida" in summary or "arraigo" in summary

    def test_regimen_impedimento_conflict_summary(self):
        _, strategy = _run(
            "impedimento de contacto, regimen de comunicacion",
            case_theory={"primary_theory": "Impedimento.", "objective": "Contacto."},
            conflict={"core_dispute": "Obstruccion."},
        )
        summary = " ".join(strategy["conflict_summary"]).lower()
        assert "impedimento" in summary or "contacto" in summary

    def test_patrimonial_conflict_summary_ganancial(self):
        _, strategy = _run(
            "conflicto patrimonial por bien ganancial",
            classification={"action_slug": "conflicto_patrimonial"},
            case_theory={"primary_theory": "Conflicto patrimonial.", "objective": "Liquidar."},
            conflict={"core_dispute": "Bien ganancial."},
        )
        summary = " ".join(strategy["conflict_summary"]).lower()
        assert "ganancial" in summary
