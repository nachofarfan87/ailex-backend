"""Tests for the multi-domain case_profile_builder."""
from __future__ import annotations

import pytest

from legal_engine.case_profile_builder import build_case_profile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_inputs(**overrides):
    defaults = dict(
        query="",
        classification={},
        case_theory={},
        conflict={},
        normative_reasoning={},
        procedural_plan=None,
        facts={},
    )
    defaults.update(overrides)
    return defaults


def _profile(**kw):
    return build_case_profile(**_base_inputs(**kw))


# ---------------------------------------------------------------------------
# Empty / no domain
# ---------------------------------------------------------------------------

class TestEmptyProfile:
    def test_no_activation(self):
        p = _profile(query="hola, quiero consultar algo")
        assert p["case_domain"] is None
        assert p["case_domains"] == []
        assert p["is_alimentos"] is False
        assert p["scenarios"] == set()
        assert p["urgency_level"] == "low"

    def test_empty_inputs(self):
        p = _profile()
        assert p["case_domain"] is None
        assert p["case_domains"] == []


# ---------------------------------------------------------------------------
# Alimentos — backward compatibility
# ---------------------------------------------------------------------------

class TestAlimentos:
    def test_slug_activation(self):
        p = _profile(classification={"action_slug": "alimentos_hijos"})
        assert p["case_domain"] == "alimentos"
        assert p["is_alimentos"] is True
        assert "alimentos" in p["case_domains"]

    def test_keyword_activation(self):
        p = _profile(query="reclamo cuota alimentaria para mi hijo de 10 años")
        assert p["is_alimentos"] is True
        assert p["case_domain"] == "alimentos"

    def test_incumplimiento_scenario(self):
        p = _profile(
            query="el padre no paga alimentos de mi hijo de 8 años",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert "incumplimiento" in p["scenarios"]
        assert "acreditar incumplimiento alimentario" in p["strategic_focus"]

    def test_cuota_provisoria(self):
        p = _profile(
            query="necesito cuota provisoria de alimentos",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert "cuota_provisoria" in p["scenarios"]
        assert p["urgency_level"] == "high"

    def test_ascendientes(self):
        p = _profile(
            query="alimentos subsidiarios contra el abuelo",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert "ascendientes" in p["scenarios"]

    def test_hijo_mayor_estudiante(self):
        p = _profile(
            query="mi hijo de 23 años estudia en la universidad, reclamo alimentos",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert "hijo_mayor" in p["scenarios"]
        assert "hijo_mayor_estudiante" in p["scenarios"]

    def test_vulnerability(self):
        p = _profile(
            query="soy madre vulnerable, sin recursos, pido alimentos",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert p["vulnerability"] is True
        assert p["needs_proof_strengthening"] is True

    def test_vivienda_scenario(self):
        p = _profile(
            query="necesito alimentos y vivienda para mis hijos",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert "vivienda" in p["scenarios"]

    def test_mixto_conyuge(self):
        p = _profile(
            query="alimentos para mis hijos y para mi como conyuge",
            classification={"action_slug": "alimentos_hijos"},
        )
        assert "mixto_conyuge" in p["scenarios"]


# ---------------------------------------------------------------------------
# Conflicto patrimonial
# ---------------------------------------------------------------------------

class TestConflictoPatrimonial:
    def test_slug_activation(self):
        p = _profile(classification={"action_slug": "conflicto_patrimonial"})
        assert p["case_domain"] == "conflicto_patrimonial"
        assert p["is_alimentos"] is False

    def test_keyword_activation(self):
        p = _profile(query="quiero dividir un bien ganancial")
        assert p["case_domain"] == "conflicto_patrimonial"

    def test_cotitularidad(self):
        p = _profile(query="inmueble en cotitularidad con mi ex, bien ganancial")
        assert "cotitularidad" in p["scenarios"]
        assert "bien_ganancial" in p["scenarios"]

    def test_bien_propio(self):
        p = _profile(query="el bien propio es de mi propiedad, conflicto patrimonial")
        assert "bien_propio" in p["scenarios"]

    def test_bien_heredado(self):
        p = _profile(query="conflicto por bien heredado de la sucesion de mi padre")
        assert "bien_heredado" in p["scenarios"]

    def test_conflicto_vs_acuerdo(self):
        p = _profile(query="no hay acuerdo sobre la division de bienes gananciales")
        assert "conflicto" in p["scenarios"]

    def test_acuerdo(self):
        p = _profile(query="convenio de particion de bienes gananciales de comun acuerdo")
        assert "acuerdo" in p["scenarios"]

    def test_liquidacion(self):
        p = _profile(query="liquidacion de la sociedad conyugal")
        assert "liquidacion" in p["scenarios"]

    def test_urgency_embargo(self):
        p = _profile(query="conflicto patrimonial, venta inminente del bien ganancial")
        assert p["urgency_level"] == "high"

    def test_inmueble(self):
        p = _profile(query="conflicto patrimonial por un departamento ganancial")
        assert "inmueble" in p["scenarios"]

    def test_strategic_focus_ganancial(self):
        p = _profile(query="division de bienes gananciales en conflicto")
        assert any("ganancial" in f for f in p["strategic_focus"])


# ---------------------------------------------------------------------------
# Divorcio
# ---------------------------------------------------------------------------

class TestDivorcio:
    def test_slug_activation(self):
        p = _profile(classification={"action_slug": "divorcio"})
        assert p["case_domain"] == "divorcio"
        assert p["is_alimentos"] is False

    def test_keyword_activation(self):
        p = _profile(query="quiero iniciar un divorcio")
        assert p["case_domain"] == "divorcio"

    def test_default_unilateral(self):
        p = _profile(query="quiero divorciarme")
        assert "unilateral" in p["scenarios"]

    def test_conjunto(self):
        p = _profile(query="divorcio de comun acuerdo con mi esposa")
        assert "conjunto" in p["scenarios"]

    def test_unilateral_explicit(self):
        p = _profile(query="divorcio unilateral")
        assert "unilateral" in p["scenarios"]

    def test_bienes(self):
        p = _profile(query="divorcio, tenemos bienes gananciales")
        assert "bienes" in p["scenarios"]

    def test_hijos(self):
        p = _profile(query="divorcio, tenemos hijos menores")
        assert "hijos" in p["scenarios"]

    def test_convenio_regulador(self):
        p = _profile(query="divorcio con convenio regulador")
        assert "convenio_regulador" in p["scenarios"]

    def test_violencia_urgency(self):
        p = _profile(query="divorcio por violencia domestica")
        assert "violencia" in p["scenarios"]
        assert p["urgency_level"] == "high"

    def test_strategic_focus_unilateral(self):
        p = _profile(query="divorcio unilateral")
        assert any("unilateral" in f for f in p["strategic_focus"])

    def test_strategic_focus_hijos(self):
        p = _profile(query="divorcio, tenemos hijos menores")
        assert any("hijos" in f for f in p["strategic_focus"])


# ---------------------------------------------------------------------------
# Régimen comunicacional
# ---------------------------------------------------------------------------

class TestRegimenComunicacional:
    def test_slug_activation(self):
        p = _profile(classification={"action_slug": "regimen_comunicacional"})
        assert p["case_domain"] == "regimen_comunicacional"

    def test_keyword_activation(self):
        p = _profile(query="necesito fijar un regimen de comunicacion con mi hijo")
        assert p["case_domain"] == "regimen_comunicacional"

    def test_impedimento_contacto(self):
        p = _profile(query="la madre no deja ver al nino, impedimento de contacto")
        assert "impedimento_contacto" in p["scenarios"]
        assert p["urgency_level"] == "high"

    def test_revinculacion(self):
        p = _profile(query="hace tiempo sin ver a mi hijo, necesito revinculacion, regimen comunicacional")
        assert "revinculacion" in p["scenarios"]

    def test_modificacion(self):
        p = _profile(query="quiero ampliar el regimen comunicacional")
        assert "modificacion" in p["scenarios"]

    def test_fijacion(self):
        p = _profile(query="sin regimen comunicacional, quiero fijar regimen")
        assert "fijacion" in p["scenarios"]

    def test_pernocte(self):
        p = _profile(query="regimen comunicacional con pernocte")
        assert "pernocte" in p["scenarios"]

    def test_vacaciones(self):
        p = _profile(query="regimen comunicacional, distribucion de vacaciones")
        assert "vacaciones" in p["scenarios"]

    def test_urgency_impedimento(self):
        p = _profile(query="me impide el contacto con mi hijo, regimen comunicacional urgente")
        assert p["urgency_level"] == "high"
        assert any("audiencia inmediata" in f or "medida cautelar" in f for f in p["strategic_focus"])

    def test_proof_impedimento(self):
        p = _profile(query="obstruccion del contacto, regimen comunicacional")
        assert p["needs_proof_strengthening"] is True


# ---------------------------------------------------------------------------
# Cuidado personal
# ---------------------------------------------------------------------------

class TestCuidadoPersonal:
    def test_slug_activation(self):
        p = _profile(classification={"action_slug": "cuidado_personal"})
        assert p["case_domain"] == "cuidado_personal"

    def test_keyword_activation(self):
        p = _profile(query="solicito cuidado personal de mi hijo")
        assert p["case_domain"] == "cuidado_personal"

    def test_tenencia_slug(self):
        p = _profile(classification={"action_slug": "tenencia"})
        assert p["case_domain"] == "cuidado_personal"

    def test_centro_de_vida(self):
        p = _profile(query="el centro de vida del nino es con la madre, cuidado personal")
        assert "centro_de_vida" in p["scenarios"]

    def test_convivencia_actual(self):
        p = _profile(query="el nino convive con la madre, cuidado personal")
        assert "convivencia_actual" in p["scenarios"]

    def test_cuidado_compartido(self):
        p = _profile(query="solicito cuidado personal compartido")
        assert "cuidado_compartido" in p["scenarios"]

    def test_cuidado_unipersonal(self):
        p = _profile(query="solicito cuidado personal unipersonal, tenencia exclusiva")
        assert "cuidado_unipersonal" in p["scenarios"]
        assert p["needs_proof_strengthening"] is True

    def test_interes_superior(self):
        p = _profile(query="el interes superior del nino exige cuidado personal")
        assert "interes_superior" in p["scenarios"]

    def test_cambio_cuidado(self):
        p = _profile(query="solicito cambio de cuidado personal, mudanza de la madre")
        assert "cambio_cuidado" in p["scenarios"]

    def test_riesgo_urgencia(self):
        p = _profile(query="cuidado personal, el nino esta en riesgo, maltrato")
        assert "riesgo" in p["scenarios"]
        assert p["urgency_level"] == "high"

    def test_strategic_focus_centro_de_vida(self):
        p = _profile(query="cuidado personal, centro de vida del nino")
        assert any("centro de vida" in f for f in p["strategic_focus"])


# ---------------------------------------------------------------------------
# Cross-domain: case_domain field always present
# ---------------------------------------------------------------------------

class TestProfileStructure:
    @pytest.mark.parametrize("query,expected_domain", [
        ("alimentos para mi hijo", "alimentos"),
        ("divorcio unilateral", "divorcio"),
        ("conflicto por bien ganancial", "conflicto_patrimonial"),
        ("regimen de comunicacion con mi hija", "regimen_comunicacional"),
        ("cuidado personal del nino", "cuidado_personal"),
    ])
    def test_case_domain_field(self, query, expected_domain):
        p = _profile(query=query)
        assert p["case_domain"] == expected_domain
        assert "case_domains" in p
        assert isinstance(p["case_domains"], list)
        assert expected_domain in p["case_domains"]
        assert "scenarios" in p
        assert "urgency_level" in p
        assert "vulnerability" in p
        assert "needs_proof_strengthening" in p
        assert "strategic_focus" in p

    def test_only_alimentos_has_is_alimentos_true(self):
        for q, domain in [
            ("divorcio unilateral", "divorcio"),
            ("conflicto por bien ganancial", "conflicto_patrimonial"),
            ("regimen de comunicacion", "regimen_comunicacional"),
            ("cuidado personal del nino", "cuidado_personal"),
        ]:
            p = _profile(query=q)
            assert p["is_alimentos"] is False, f"{domain} should not be is_alimentos"


# ---------------------------------------------------------------------------
# Vulnerability shared across domains
# ---------------------------------------------------------------------------

class TestVulnerabilityAcrossDomains:
    @pytest.mark.parametrize("query", [
        "alimentos, madre en situacion de violencia",
        "divorcio, mujer vulnerable sin recursos",
        "conflicto patrimonial, bajos recursos",
        "regimen de comunicacion, violencia domestica",
        "cuidado personal, madre vulnerable",
    ])
    def test_vulnerability_detected(self, query):
        p = _profile(query=query)
        assert p["vulnerability"] is True
        assert any("proteccion" in f for f in p["strategic_focus"])


# ---------------------------------------------------------------------------
# Multi-domain detection and priority
# ---------------------------------------------------------------------------

class TestMultiDomain:

    def test_divorcio_plus_patrimonial(self):
        """Divorcio con bienes gananciales activa ambos dominios."""
        p = _profile(query="divorcio y division de bienes gananciales en cotitularidad")
        assert p["case_domain"] == "divorcio"
        assert "divorcio" in p["case_domains"]
        assert "conflicto_patrimonial" in p["case_domains"]
        assert len(p["case_domains"]) == 2
        # cross-domain focus present
        assert any("divorcio" in f and "patrimonial" in f for f in p["strategic_focus"])

    def test_alimentos_plus_cuidado_personal(self):
        """Alimentos + cuidado personal: alimentos es primary por prioridad."""
        p = _profile(query="reclamo alimentos y cuidado personal del hijo de 5 años")
        assert p["case_domain"] == "alimentos"
        assert p["is_alimentos"] is True
        assert "alimentos" in p["case_domains"]
        assert "cuidado_personal" in p["case_domains"]
        # cross-domain focus
        assert any("alimentos" in f and "cuidado personal" in f for f in p["strategic_focus"])

    def test_alimentos_plus_divorcio(self):
        """Divorcio con alimentos: alimentos gana por prioridad."""
        p = _profile(query="divorcio y alimentos para los hijos menores")
        assert p["case_domain"] == "alimentos"
        assert "alimentos" in p["case_domains"]
        assert "divorcio" in p["case_domains"]

    def test_cuidado_personal_plus_regimen(self):
        """Cuidado personal + regimen comunicacional: cuidado gana."""
        p = _profile(
            query="solicito cuidado personal y fijar regimen de comunicacion"
        )
        assert p["case_domain"] == "cuidado_personal"
        assert "cuidado_personal" in p["case_domains"]
        assert "regimen_comunicacional" in p["case_domains"]
        assert any("cuidado personal" in f and "regimen comunicacional" in f
                    for f in p["strategic_focus"])

    def test_three_domains_divorcio_alimentos_patrimonial(self):
        """Triple domain: alimentos is primary."""
        p = _profile(
            query="divorcio con alimentos para los hijos y division de bienes gananciales"
        )
        assert p["case_domain"] == "alimentos"
        assert len(p["case_domains"]) >= 3
        assert "alimentos" in p["case_domains"]
        assert "divorcio" in p["case_domains"]
        assert "conflicto_patrimonial" in p["case_domains"]

    def test_scenarios_come_from_primary_domain(self):
        """Scenarios are built by the primary domain builder only."""
        p = _profile(query="reclamo alimentos y cuidado personal del hijo de 5 años")
        # alimentos is primary, so scenarios should be alimentos-specific
        assert p["case_domain"] == "alimentos"
        # should NOT have cuidado_personal scenarios like centro_de_vida
        assert "centro_de_vida" not in p["scenarios"]
        # but should have alimentos scenario (hijo_menor from age 5)
        assert "hijo_menor" in p["scenarios"]

    def test_single_domain_case_domains_is_singleton(self):
        """Single domain: case_domains has exactly one entry."""
        p = _profile(classification={"action_slug": "alimentos_hijos"})
        assert p["case_domains"] == ["alimentos"]

    def test_no_cross_focus_for_single_domain(self):
        """Single domain should not have cross-domain focus."""
        p = _profile(query="reclamo cuota alimentaria para mi hijo")
        focus_text = " ".join(p["strategic_focus"])
        assert "coordinar estrategia entre" not in focus_text

    def test_priority_order_is_respected(self):
        """case_domains list follows the priority order."""
        p = _profile(
            query="divorcio con alimentos para los hijos y cuidado personal"
        )
        domains = p["case_domains"]
        # alimentos < cuidado_personal < divorcio in priority
        assert domains.index("alimentos") < domains.index("cuidado_personal")
        assert domains.index("cuidado_personal") < domains.index("divorcio")

    def test_divorcio_plus_patrimonial_no_scenario_leak(self):
        """Divorcio primary should not leak patrimonial scenarios."""
        p = _profile(query="divorcio y division de bienes gananciales en cotitularidad")
        assert p["case_domain"] == "divorcio"
        # cotitularidad is a conflicto_patrimonial scenario, not divorcio
        assert "cotitularidad" not in p["scenarios"]
        # but divorcio should detect bienes
        assert "bienes" in p["scenarios"]
