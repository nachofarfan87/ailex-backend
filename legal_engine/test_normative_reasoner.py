"""
Tests para NormativeReasoner.

Ejecutar:
    cd backend && python -m pytest legal_engine/test_normative_reasoner.py -v

O sin pytest:
    cd backend && python -m legal_engine.test_normative_reasoner
"""

from __future__ import annotations

import json
import unittest

from legal_engine.normative_reasoner import (
    AppliedRule,
    NormativeReasoner,
    NormativeReasoningResult,
)


class TestAppliedRuleToDict(unittest.TestCase):
    def test_to_dict(self):
        rule = AppliedRule(
            source="CCyC",
            article="435",
            title="Disolucion",
            relevance="aplica",
            effect="disuelve el vinculo",
        )
        d = rule.to_dict()
        self.assertEqual(d["source"], "CCyC")
        self.assertEqual(d["article"], "435")
        self.assertEqual(d["title"], "Disolucion")
        self.assertIn("relevance", d)
        self.assertIn("effect", d)

    def test_to_dict_none_title(self):
        rule = AppliedRule(
            source="src", article="1", title=None, relevance="r", effect="e",
        )
        d = rule.to_dict()
        self.assertIsNone(d["title"])


class TestNormativeReasoningResultToDict(unittest.TestCase):
    def test_serialization_roundtrip(self):
        result = NormativeReasoningResult(
            summary="Test summary",
            legal_basis=["Art. 1"],
            applied_rules=[
                AppliedRule("src", "1", "T", "rel", "eff"),
            ],
            inferences=["inf1"],
            requirements=["req1"],
            warnings=["w1"],
            unresolved_issues=["u1"],
            confidence_score=0.75,
        )
        d = result.to_dict()
        # Must be JSON-serializable
        json_str = json.dumps(d, ensure_ascii=False)
        self.assertIsInstance(json_str, str)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["summary"], "Test summary")
        self.assertEqual(len(parsed["applied_rules"]), 1)
        self.assertEqual(parsed["confidence_score"], 0.75)

    def test_defaults(self):
        result = NormativeReasoningResult(summary="s")
        d = result.to_dict()
        self.assertEqual(d["legal_basis"], [])
        self.assertEqual(d["applied_rules"], [])
        self.assertEqual(d["confidence_score"], 0.0)


class TestDivorcioMutuoAcuerdo(unittest.TestCase):
    """Tests del handler especializado para divorcio_mutuo_acuerdo."""

    def setUp(self):
        self.reasoner = NormativeReasoner()
        self.classification = {
            "action_slug": "divorcio_mutuo_acuerdo",
            "action_label": "Divorcio por mutuo acuerdo",
            "forum": "familia",
            "jurisdiction": "jujuy",
            "process_type": "voluntario",
            "confidence_score": 0.88,
        }
        self.case_structure = {
            "action_slug": "divorcio_mutuo_acuerdo",
            "facts": [
                "Ambos conyuges manifiestan voluntad de divorciarse.",
                "La peticion es conjunta (mutuo acuerdo).",
            ],
            "applicable_rules": [],
            "missing_information": [
                "Fecha y lugar de celebracion del matrimonio.",
                "Ultimo domicilio conyugal.",
                "Existencia de hijos menores o con capacidad restringida.",
            ],
            "risks": [],
        }

    def test_query_directa(self):
        """'Dos personas quieren divorciarse de comun acuerdo'"""
        result = self.reasoner.reason(
            query="Dos personas quieren divorciarse de comun acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        self.assertIsInstance(result, NormativeReasoningResult)

        # Debe mencionar que no requiere causa
        inferences_text = " ".join(result.inferences).lower()
        self.assertIn("incausado", inferences_text)

        # Debe mencionar presentacion conjunta
        self.assertTrue(
            any("conjunta" in inf.lower() for inf in result.inferences),
            "Debe inferir que puede tramitarse por presentacion conjunta.",
        )

        # Debe mencionar propuesta reguladora
        self.assertTrue(
            any("propuesta reguladora" in inf.lower() for inf in result.inferences),
            "Debe inferir la relevancia de la propuesta reguladora.",
        )

        # Confidence razonable
        self.assertGreater(result.confidence_score, 0.50)

    def test_detecta_faltantes_hijos(self):
        """Detecta que faltan datos sobre hijos si no se mencionan."""
        result = self.reasoner.reason(
            query="Queremos divorciarnos de mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        unresolved_text = " ".join(result.unresolved_issues).lower()
        self.assertTrue(
            "hijos" in unresolved_text,
            "Debe advertir sobre falta de informacion de hijos.",
        )

    def test_detecta_faltantes_bienes(self):
        """Detecta que faltan datos sobre bienes."""
        result = self.reasoner.reason(
            query="Nos queremos divorciar",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        unresolved_text = " ".join(result.unresolved_issues).lower()
        self.assertTrue(
            "bienes" in unresolved_text or "patrimonio" in unresolved_text,
            "Debe advertir sobre falta de informacion patrimonial.",
        )

    def test_detecta_faltantes_alimentos(self):
        """Detecta que faltan datos sobre alimentos."""
        result = self.reasoner.reason(
            query="Divorcio de mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        unresolved_text = " ".join(result.unresolved_issues).lower()
        self.assertTrue(
            "alimentos" in unresolved_text,
            "Debe advertir sobre falta de informacion de alimentos.",
        )

    def test_applied_rules_contienen_articulos_clave(self):
        """Debe incluir arts. 435, 437, 438, 439."""
        result = self.reasoner.reason(
            query="Divorcio mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        articles = {r.article for r in result.applied_rules}
        for art in ("435", "437", "438", "439"):
            self.assertIn(art, articles, f"Debe incluir art. {art}")

    def test_applied_rules_tienen_efecto(self):
        """Cada AppliedRule debe tener efecto no vacio."""
        result = self.reasoner.reason(
            query="Divorcio mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        for rule in result.applied_rules:
            self.assertTrue(
                rule.effect.strip(),
                f"Art. {rule.article} debe tener efecto explicito.",
            )

    def test_legal_basis_no_vacia(self):
        """Debe tener al menos una entrada en legal_basis."""
        result = self.reasoner.reason(
            query="Divorcio mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        self.assertGreater(len(result.legal_basis), 0)

    def test_requirements_no_vacios(self):
        """Debe listar requisitos."""
        result = self.reasoner.reason(
            query="Divorcio mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        self.assertGreater(len(result.requirements), 0)

    def test_serialization(self):
        """to_dict debe ser JSON-serializable."""
        result = self.reasoner.reason(
            query="Divorcio de mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
        )
        d = result.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        parsed = json.loads(json_str)
        self.assertIn("summary", parsed)
        self.assertIn("applied_rules", parsed)
        self.assertIsInstance(parsed["applied_rules"], list)
        self.assertIsInstance(parsed["confidence_score"], float)

    def test_with_retrieved_chunks(self):
        """Chunks recuperados deben enriquecer las applied_rules."""
        chunks = [
            {
                "source_id": "codigo_civil_comercial",
                "article": "721",
                "norma": "Codigo Civil y Comercial",
                "titulo": "Medidas provisionales",
                "texto": "Durante el proceso de divorcio...",
                "score": 0.7,
            },
        ]
        result = self.reasoner.reason(
            query="Divorcio mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
            retrieved_chunks=chunks,
        )
        articles = {r.article for r in result.applied_rules}
        self.assertIn("721", articles, "Chunk recuperado con art. 721 debe sumarse.")

    def test_no_duplica_chunks_ya_incluidos(self):
        """Si el chunk tiene un articulo ya presente, no debe duplicarse."""
        chunks = [
            {
                "source_id": "Codigo Civil y Comercial de la Nacion",
                "article": "435",
                "texto": "...",
                "score": 0.9,
            },
        ]
        result = self.reasoner.reason(
            query="Divorcio mutuo acuerdo",
            classification=self.classification,
            case_structure=self.case_structure,
            retrieved_chunks=chunks,
        )
        count_435 = sum(1 for r in result.applied_rules if r.article == "435")
        self.assertEqual(count_435, 1, "Art. 435 no debe duplicarse.")


class TestFallbackGenerico(unittest.TestCase):
    """Tests del razonamiento generico (action_slug sin handler)."""

    def setUp(self):
        self.reasoner = NormativeReasoner()

    def test_sin_clasificacion(self):
        """Funciona sin clasificacion ni case_structure."""
        result = self.reasoner.reason(query="Quiero iniciar un amparo")
        self.assertIsInstance(result, NormativeReasoningResult)
        self.assertGreater(len(result.warnings), 0)
        self.assertIn("generico", result.warnings[0].lower())

    def test_con_clasificacion_desconocida(self):
        """action_slug desconocido cae en generico."""
        result = self.reasoner.reason(
            query="Quiero iniciar un amparo",
            classification={"action_slug": "amparo", "action_label": "Amparo"},
        )
        self.assertIsInstance(result, NormativeReasoningResult)
        self.assertIn("amparo", result.summary.lower())

    def test_generico_con_case_structure(self):
        """Generico incorpora applicable_rules del case_structure."""
        result = self.reasoner.reason(
            query="Demanda laboral",
            classification={"action_slug": "demanda_laboral", "action_label": "Demanda laboral"},
            case_structure={
                "applicable_rules": [
                    {"source_id": "lct_20744", "article": "245", "description": "Indemnizacion por despido."},
                ],
                "missing_information": ["Fecha de ingreso", "Ultimo salario"],
            },
        )
        articles = {r.article for r in result.applied_rules}
        self.assertIn("245", articles)
        self.assertGreater(len(result.unresolved_issues), 0)

    def test_generico_con_chunks(self):
        """Generico incorpora retrieved_chunks."""
        result = self.reasoner.reason(
            query="Recurso de apelacion",
            classification={"action_slug": "recurso_apelacion", "action_label": "Recurso de apelacion"},
            retrieved_chunks=[
                {
                    "source_id": "cpcc_jujuy",
                    "article": "229",
                    "texto": "El recurso de apelacion procedera...",
                    "score": 0.8,
                },
            ],
        )
        articles = {r.article for r in result.applied_rules}
        self.assertIn("229", articles)

    def test_generico_confidence_limitada(self):
        """Confidence del generico no debe superar 0.70."""
        result = self.reasoner.reason(
            query="Consulta generica",
            classification={"action_slug": "unknown"},
        )
        self.assertLessEqual(result.confidence_score, 0.70)

    def test_generico_serializable(self):
        """Generico to_dict es JSON-serializable."""
        result = self.reasoner.reason(query="Cualquier consulta")
        d = result.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        self.assertIsInstance(json.loads(json_str), dict)


class TestCoercion(unittest.TestCase):
    """Tests de coercion de inputs."""

    def setUp(self):
        self.reasoner = NormativeReasoner()

    def test_accepts_none_inputs(self):
        """Todos los inputs opcionales pueden ser None."""
        result = self.reasoner.reason(
            query="test",
            classification=None,
            case_structure=None,
            retrieved_chunks=None,
        )
        self.assertIsInstance(result, NormativeReasoningResult)

    def test_accepts_dataclass_with_to_dict(self):
        """Acepta objetos con metodo to_dict()."""

        class FakeClassification:
            def to_dict(self):
                return {
                    "action_slug": "divorcio_mutuo_acuerdo",
                    "action_label": "Divorcio por mutuo acuerdo",
                }

        result = self.reasoner.reason(
            query="Divorcio mutuo",
            classification=FakeClassification(),
        )
        self.assertIsInstance(result, NormativeReasoningResult)
        # Should have used the specialized handler
        self.assertIn("incausado", " ".join(result.inferences).lower())

    def test_accepts_object_with_dict(self):
        """Acepta objetos simples con __dict__."""

        class SimpleObj:
            def __init__(self):
                self.action_slug = "generic"
                self.action_label = "Test"

        result = self.reasoner.reason(
            query="test",
            classification=SimpleObj(),
        )
        self.assertIsInstance(result, NormativeReasoningResult)


class TestAlimentosPriorityFiltering(unittest.TestCase):
    def setUp(self):
        self.reasoner = NormativeReasoner()
        self.classification = {
            "action_slug": "alimentos_hijos",
            "action_label": "Alimentos para hijos",
            "priority_articles": [
                {"source_id": "codigo_civil_comercial", "article": "658"},
                {"source_id": "codigo_civil_comercial", "article": "659"},
                {"source_id": "codigo_civil_comercial", "article": "660"},
                {"source_id": "codigo_civil_comercial", "article": "661"},
                {"source_id": "codigo_civil_comercial", "article": "662"},
                {"source_id": "codigo_civil_comercial", "article": "663"},
                {"source_id": "codigo_civil_comercial", "article": "664"},
                {"source_id": "codigo_civil_comercial", "article": "669"},
            ],
        }

    def test_alimentos_ignora_normas_ajenas_recuperadas(self):
        result = self.reasoner.reason(
            query="Cuota alimentaria provisoria para hijo menor",
            classification=self.classification,
            case_structure={"applicable_rules": [], "missing_information": []},
            retrieved_chunks=[
                {"source_id": "codigo_civil_comercial", "article": "658", "texto": "Obligacion alimentaria."},
                {"source_id": "cpcc_jujuy", "article": "287", "texto": "Embargo."},
                {"source_id": "constitucion_jujuy", "article": "123", "texto": "Norma constitucional."},
                {"source_id": "cpcc_jujuy", "article": "628", "texto": "Inventario sucesorio."},
            ],
        )

        articles = {(rule.source, rule.article) for rule in result.applied_rules}
        self.assertIn(("CCyC", "658"), articles)
        self.assertNotIn(("CPCC Jujuy", "287"), articles)
        self.assertNotIn(("Const. Jujuy", "123"), articles)
        self.assertNotIn(("CPCC Jujuy", "628"), articles)


if __name__ == "__main__":
    unittest.main()
