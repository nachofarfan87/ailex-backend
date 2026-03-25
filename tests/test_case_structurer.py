"""Tests para CaseStructurer."""

import pytest

from legal_engine.case_structurer import ApplicableRule, CaseStructure, CaseStructurer
from legal_engine.action_classifier import ActionClassifier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def structurer():
    return CaseStructurer()


@pytest.fixture
def classifier():
    return ActionClassifier()


# ---------------------------------------------------------------------------
# divorcio_mutuo_acuerdo
# ---------------------------------------------------------------------------

class TestDivorcioMutuoAcuerdo:
    def test_structure_from_classification_object(self, structurer, classifier):
        cls = classifier.classify("Dos personas quieren divorciarse de comun acuerdo", jurisdiction="jujuy")
        assert cls is not None
        case = structurer.structure(query=cls.query, classification=cls)

        assert case.action_slug == "divorcio_mutuo_acuerdo"
        assert case.forum == "familia"
        assert case.process_type == "voluntario"
        assert case.jurisdiction == "jujuy"

    def test_structure_from_classification_dict(self, structurer):
        cls_dict = {
            "action_slug": "divorcio_mutuo_acuerdo",
            "action_label": "Divorcio por mutuo acuerdo",
            "forum": "familia",
            "process_type": "voluntario",
            "jurisdiction": "jujuy",
            "confidence_score": 0.85,
        }
        case = structurer.structure(
            query="queremos divorciarnos",
            classification=cls_dict,
        )
        assert case.action_slug == "divorcio_mutuo_acuerdo"
        assert case.forum == "familia"
        assert case.confidence_score == 0.85

    def test_applicable_rules_include_key_articles(self, structurer, classifier):
        cls = classifier.classify("Dos personas quieren divorciarse de comun acuerdo")
        case = structurer.structure(query=cls.query, classification=cls)

        article_numbers = {r.article for r in case.applicable_rules}
        assert "437" in article_numbers
        assert "438" in article_numbers
        assert "439" in article_numbers
        assert "717" in article_numbers

    def test_missing_information_not_empty(self, structurer, classifier):
        cls = classifier.classify("Dos personas quieren divorciarse de comun acuerdo")
        case = structurer.structure(query=cls.query, classification=cls)
        assert len(case.missing_information) >= 3

    def test_risks_not_empty(self, structurer, classifier):
        cls = classifier.classify("Dos personas quieren divorciarse de comun acuerdo")
        case = structurer.structure(query=cls.query, classification=cls)
        assert len(case.risks) >= 2

    def test_suggested_strategy_mentions_propuesta(self, structurer, classifier):
        cls = classifier.classify("Dos personas quieren divorciarse de comun acuerdo")
        case = structurer.structure(query=cls.query, classification=cls)
        assert "propuesta reguladora" in case.suggested_strategy.lower()

    def test_facts_mention_mutuo_acuerdo(self, structurer, classifier):
        cls = classifier.classify("Dos personas quieren divorciarse de comun acuerdo")
        assert cls is not None
        case = structurer.structure(query=cls.query, classification=cls)
        facts_text = " ".join(case.facts).lower()
        assert "conjunta" in facts_text or "mutuo acuerdo" in facts_text

    def test_to_dict_round_trip(self, structurer, classifier):
        cls = classifier.classify("Dos personas quieren divorciarse de comun acuerdo")
        case = structurer.structure(query=cls.query, classification=cls)
        d = case.to_dict()

        assert isinstance(d, dict)
        assert d["action_slug"] == "divorcio_mutuo_acuerdo"
        assert isinstance(d["applicable_rules"], list)
        assert all(isinstance(r, dict) for r in d["applicable_rules"])
        assert d["applicable_rules"][0]["source_id"] == "codigo_civil_comercial"

    def test_indirect_phrase_resolves_to_divorcio(self, structurer, classifier):
        cls = classifier.classify("Ambos conyuges decidieron terminar el matrimonio")
        assert cls is not None
        case = structurer.structure(query=cls.query, classification=cls)
        assert case.action_slug == "divorcio_mutuo_acuerdo"
        assert case.forum == "familia"


# ---------------------------------------------------------------------------
# divorcio generico
# ---------------------------------------------------------------------------

class TestDivorcioGenerico:
    def test_divorcio_unilateral(self, structurer):
        cls_dict = {
            "action_slug": "divorcio",
            "action_label": "Divorcio",
            "forum": "familia",
            "process_type": "contencioso_o_voluntario",
            "jurisdiction": "jujuy",
            "confidence_score": 0.7,
        }
        case = structurer.structure(query="quiero divorciarme", classification=cls_dict)
        assert case.action_slug == "divorcio"
        assert case.forum == "familia"
        article_numbers = {r.article for r in case.applicable_rules}
        assert "437" in article_numbers


class TestPhase2SpecificActions:
    def test_divorcio_unilateral_specific_structure(self, structurer, classifier):
        cls = classifier.classify("Mi esposa no quiere divorciarse pero yo si", jurisdiction="jujuy")
        assert cls is not None

        case = structurer.structure(query=cls.query, classification=cls)

        assert case.action_slug == "divorcio_unilateral"
        assert case.forum == "familia"
        assert case.process_type == "contencioso_inicial"
        assert any(rule.article == "721" for rule in case.applicable_rules)
        assert any("propuesta reguladora" in item.lower() for item in case.missing_information)

    def test_alimentos_hijos_specific_structure(self, structurer, classifier):
        cls = classifier.classify("El padre de mi hijo no paga alimentos", jurisdiction="jujuy")
        assert cls is not None

        case = structurer.structure(query=cls.query, classification=cls)

        assert case.action_slug == "alimentos_hijos"
        assert case.forum == "familia"
        assert any(rule.article == "669" for rule in case.applicable_rules)
        assert any("gastos" in item.lower() for item in case.missing_information)
        assert "cuota" in case.main_claim.lower() or "alimentos" in case.main_claim.lower()

    def test_sucesion_ab_intestato_specific_structure(self, structurer, classifier):
        cls = classifier.classify("Murio mi padre y queremos iniciar la sucesion", jurisdiction="jujuy")
        assert cls is not None

        case = structurer.structure(query=cls.query, classification=cls)

        assert case.action_slug == "sucesion_ab_intestato"
        assert case.forum == "civil"
        assert any(rule.article == "2336" for rule in case.applicable_rules)
        assert any("domicilio" in item.lower() for item in case.missing_information)
        assert "declaratoria" in case.main_claim.lower() or "sucesion" in case.main_claim.lower()


# ---------------------------------------------------------------------------
# Fallback generico
# ---------------------------------------------------------------------------

class TestGenericFallback:
    def test_unknown_action_slug_uses_fallback(self, structurer):
        cls_dict = {
            "action_slug": "reclamo_laboral",
            "action_label": "Reclamo laboral",
            "forum": "laboral",
            "process_type": "ordinario",
            "jurisdiction": "jujuy",
            "confidence_score": 0.5,
            "priority_articles": [
                {"source_id": "lct", "article": "245"},
            ],
        }
        case = structurer.structure(query="me despidieron sin causa", classification=cls_dict)

        assert case.action_slug == "reclamo_laboral"
        assert case.forum == "laboral"
        assert len(case.warnings) >= 1
        assert any("generica" in w.lower() for w in case.warnings)
        assert len(case.applicable_rules) == 1
        assert case.applicable_rules[0].article == "245"

    def test_none_classification_produces_generic(self, structurer):
        case = structurer.structure(query="tengo un problema legal", classification=None)
        assert case.action_slug == "generic"
        assert len(case.warnings) >= 1

    def test_empty_dict_classification(self, structurer):
        case = structurer.structure(query="consulta general", classification={})
        assert case.action_slug == "generic"


# ---------------------------------------------------------------------------
# Parametros override
# ---------------------------------------------------------------------------

class TestParameterOverrides:
    def test_jurisdiction_override(self, structurer):
        cls_dict = {
            "action_slug": "divorcio_mutuo_acuerdo",
            "action_label": "Divorcio por mutuo acuerdo",
            "forum": "familia",
            "process_type": "voluntario",
            "jurisdiction": "buenos_aires",
            "confidence_score": 0.9,
        }
        case = structurer.structure(
            query="divorcio",
            classification=cls_dict,
            jurisdiction="cordoba",
        )
        assert case.jurisdiction == "cordoba"

    def test_forum_override(self, structurer):
        cls_dict = {
            "action_slug": "divorcio_mutuo_acuerdo",
            "action_label": "Divorcio por mutuo acuerdo",
            "forum": "familia",
            "process_type": "voluntario",
            "confidence_score": 0.9,
        }
        case = structurer.structure(
            query="divorcio",
            classification=cls_dict,
            forum="civil_y_comercial",
        )
        assert case.forum == "civil_y_comercial"


# ---------------------------------------------------------------------------
# ApplicableRule
# ---------------------------------------------------------------------------

class TestApplicableRule:
    def test_to_dict(self):
        rule = ApplicableRule(
            source_id="codigo_civil_comercial",
            article="437",
            description="Legitimacion para peticionar divorcio.",
        )
        d = rule.to_dict()
        assert d == {
            "source_id": "codigo_civil_comercial",
            "article": "437",
            "description": "Legitimacion para peticionar divorcio.",
        }
