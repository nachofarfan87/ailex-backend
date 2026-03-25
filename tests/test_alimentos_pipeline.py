# backend/tests/test_alimentos_pipeline.py
"""
Tests específicos para el pipeline de alimentos.

Valida:
  - Clasificación correcta de consultas de alimentos
  - Handler normativo correcto (no genérico)
  - Bloqueo de normas ajenas
  - Síntesis jurisprudencial limpia
  - Síntesis sucesoria sin residuos de resolutivo

Ejecutar:
    cd backend && python -m pytest tests/test_alimentos_pipeline.py -v
"""
from pathlib import Path

from legal_engine.action_classifier import ActionClassifier
from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.jurisprudence_engine import (
    JurisprudenceEngine,
    SOURCE_MODE_RETRIEVED,
)
from legal_engine.jurisprudence_index import JurisprudenceIndex
from legal_engine.jurisprudence_retriever import JurisprudenceRetriever
from legal_engine.normative_reasoner import NormativeReasoner, NormativeReasoningResult

SAMPLE_CORPUS_ROOT = Path(__file__).resolve().parent / "fixtures" / "jurisprudence"


# ---------------------------------------------------------------------------
# 1. Clasificación: consultas de alimentos deben clasificar como alimentos_hijos
# ---------------------------------------------------------------------------

class TestAlimentosClassification:
    """El clasificador debe detectar consultas de alimentos sin caer en genérico."""

    def setup_method(self):
        self.classifier = ActionClassifier()

    def test_classify_alimentos_simple(self):
        result = self.classifier.classify("alimentos")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_cuota_alimentaria(self):
        result = self.classifier.classify("cuota alimentaria")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_cuota_alimentaria_provisoria(self):
        result = self.classifier.classify("cuota alimentaria provisoria")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_alimentos_provisorios(self):
        result = self.classifier.classify("alimentos provisorios")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_alimentos_hijos(self):
        result = self.classifier.classify("alimentos hijos")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_aumento_de_cuota(self):
        result = self.classifier.classify("aumento de cuota alimentaria")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_reduccion_de_cuota(self):
        result = self.classifier.classify("reduccion de cuota alimentaria")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_padre_no_paga(self):
        result = self.classifier.classify("el padre de mi hijo no paga alimentos")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_classify_cuota_provisoria_hijo_menor(self):
        result = self.classifier.classify("cuota alimentaria provisoria para hijo menor")
        assert result is not None
        assert result.action_slug == "alimentos_hijos"

    def test_alimentos_not_confused_with_divorcio(self):
        """'alimentos' no debe clasificar como divorcio."""
        result = self.classifier.classify("alimentos")
        assert result is not None
        assert "divorcio" not in result.action_slug

    def test_alimentos_has_priority_articles(self):
        result = self.classifier.classify("cuota alimentaria provisoria")
        assert result is not None
        articles = {item["article"] for item in result.priority_articles}
        assert "658" in articles
        assert "659" in articles
        assert "662" in articles


# ---------------------------------------------------------------------------
# 2. NormativeReasoner: handler correcto para alimentos
# ---------------------------------------------------------------------------

class TestAlimentosNormativeReasoner:
    """El reasoner debe usar el handler de alimentos_hijos, no el genérico."""

    def setup_method(self):
        self.reasoner = NormativeReasoner()

    def _alimentos_classification(self):
        return {
            "action_slug": "alimentos_hijos",
            "action_label": "Alimentos para hijos",
            "forum": "familia",
            "jurisdiction": "jujuy",
            "confidence_score": 0.88,
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

    def test_handler_alimentos_not_generic(self):
        """Debe usar handler especializado, no genérico."""
        result = self.reasoner.reason(
            query="cuota alimentaria provisoria",
            classification=self._alimentos_classification(),
        )
        assert "generico" not in result.summary.lower()
        assert "alimentos" in result.summary.lower()

    def test_handler_alimentos_articles_clave(self):
        """Debe incluir arts. 658, 659, 662."""
        result = self.reasoner.reason(
            query="cuota alimentaria provisoria",
            classification=self._alimentos_classification(),
        )
        articles = {r.article for r in result.applied_rules}
        for art in ("658", "659", "662"):
            assert art in articles, f"Debe incluir art. {art}"

    def test_handler_alimentos_inferences(self):
        """Inferencias deben mencionar legitimación y cuantificación."""
        result = self.reasoner.reason(
            query="alimentos para mi hijo",
            classification=self._alimentos_classification(),
        )
        inferences_text = " ".join(result.inferences).lower()
        assert "legitimacion" in inferences_text
        assert "cuantificacion" in inferences_text or "cuota" in inferences_text

    def test_handler_alimentos_blocks_foreign_norms(self):
        """Chunks de normas ajenas deben ser bloqueados."""
        result = self.reasoner.reason(
            query="cuota alimentaria provisoria para hijo menor",
            classification=self._alimentos_classification(),
            case_structure={"applicable_rules": [], "missing_information": []},
            retrieved_chunks=[
                {"source_id": "codigo_civil_comercial", "article": "658", "texto": "Obligacion alimentaria."},
                {"source_id": "cpcc_jujuy", "article": "287", "texto": "Embargo."},
                {"source_id": "constitucion_jujuy", "article": "50", "texto": "Derechos sociales."},
                {"source_id": "cpcc_jujuy", "article": "628", "texto": "Inventario sucesorio."},
            ],
        )
        articles = {(r.source, r.article) for r in result.applied_rules}
        assert ("CCyC", "658") in articles
        assert ("CPCC Jujuy", "287") not in articles
        assert ("Const. Jujuy", "50") not in articles
        assert ("CPCC Jujuy", "628") not in articles

    def test_safety_net_generic_slug_redirects_to_alimentos(self):
        """Si el slug es genérico pero la query dice 'alimentos', debe redirigir."""
        result = self.reasoner.reason(
            query="quiero pedir alimentos para mi hijo",
            classification={"action_slug": "generic"},
        )
        assert "generico" not in result.summary.lower()
        assert "alimentos" in result.summary.lower()

    def test_safety_net_cuota_alimentaria_provisoria(self):
        """Safety net para 'cuota alimentaria provisoria' sin clasificación."""
        result = self.reasoner.reason(
            query="cuota alimentaria provisoria",
            classification=None,
        )
        assert "alimentos" in result.summary.lower()
        articles = {r.article for r in result.applied_rules}
        assert "658" in articles

    def test_safety_net_reduccion_de_cuota(self):
        """Safety net para 'reduccion de cuota'."""
        result = self.reasoner.reason(
            query="reduccion de cuota alimentaria",
            classification={"action_slug": "generic"},
        )
        assert "alimentos" in result.summary.lower()

    def test_confidence_above_threshold(self):
        result = self.reasoner.reason(
            query="cuota alimentaria provisoria",
            classification=self._alimentos_classification(),
        )
        assert result.confidence_score > 0.50


# ---------------------------------------------------------------------------
# 3. JurisprudenceIndex: normalización de slugs
# ---------------------------------------------------------------------------

class TestAlimentosSlugNormalization:
    def test_normalize_alimentos(self):
        assert JurisprudenceIndex.normalize_action_slug("alimentos") == "alimentos_hijos"

    def test_normalize_cuota_alimentaria(self):
        assert JurisprudenceIndex.normalize_action_slug("cuota_alimentaria") == "alimentos_hijos"

    def test_normalize_cuota_alimentaria_provisoria(self):
        assert JurisprudenceIndex.normalize_action_slug("cuota_alimentaria_provisoria") == "alimentos_hijos"

    def test_normalize_alimentos_provisorios(self):
        assert JurisprudenceIndex.normalize_action_slug("alimentos_provisorios") == "alimentos_hijos"

    def test_normalize_aumento_de_cuota(self):
        assert JurisprudenceIndex.normalize_action_slug("aumento_de_cuota") == "alimentos_hijos"

    def test_normalize_reduccion_de_cuota(self):
        assert JurisprudenceIndex.normalize_action_slug("reduccion_de_cuota") == "alimentos_hijos"


# ---------------------------------------------------------------------------
# 4. JurisprudenceEngine: síntesis limpia para alimentos
# ---------------------------------------------------------------------------

class TestAlimentosJurisprudenceSynthesis:
    """Criterion y strategic_use no deben contener texto crudo de resolutivo."""

    def setup_method(self):
        self.engine = JurisprudenceEngine(
            jurisprudence_retriever=JurisprudenceRetriever(corpus_root=SAMPLE_CORPUS_ROOT)
        )

    def _payload(self):
        return dict(
            classification={
                "action_slug": "alimentos_hijos",
                "action_label": "Alimentos para hijos",
                "confidence_score": 0.9,
                "jurisdiction": "jujuy",
                "forum": "familia",
            },
            case_structure={
                "facts": ["El padre no paga alimentos.", "La madre convive con el hijo."],
                "missing_information": ["Ingresos del obligado."],
                "risks": [],
            },
            normative_reasoning={
                "applied_rules": [
                    {"source": "CCyC", "article": "658", "relevance": "Obligacion alimentaria", "effect": "Deber del progenitor"},
                ],
                "requirements": ["Acreditar gastos del hijo."],
                "unresolved_issues": [],
            },
        )

    def test_alimentos_criterion_no_dni(self):
        payload = self.engine.analyze(
            query="Cuota alimentaria provisoria para hijo menor",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            assert "dni" not in first["criterion"].lower()

    def test_alimentos_criterion_no_hacer_lugar(self):
        payload = self.engine.analyze(
            query="Cuota alimentaria provisoria",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            assert "hacer lugar" not in first["criterion"].lower()

    def test_alimentos_criterion_has_legal_content(self):
        payload = self.engine.analyze(
            query="alimentos para hijo menor",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            lowered = first["criterion"].lower()
            assert any(kw in lowered for kw in ("cuota", "aliment", "necesidad", "provisori", "obligacion"))

    def test_alimentos_criterion_word_count(self):
        """criterion debe tener entre 12 y 40 palabras."""
        payload = self.engine.analyze(
            query="Cuota alimentaria provisoria para hijo menor",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            criterion = payload["jurisprudence_highlights"][0]["criterion"]
            word_count = len(criterion.split())
            assert 12 <= word_count <= 40, (
                f"criterion tiene {word_count} palabras (debe ser 12-40): {criterion!r}"
            )

    def test_alimentos_criterion_no_resolutivo_markers(self):
        """criterion no debe contener marcadores de resolutivo."""
        payload = self.engine.analyze(
            query="Cuota alimentaria provisoria",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            criterion = payload["jurisprudence_highlights"][0]["criterion"].lower()
            for marker in ("resuelvo", "fallo", "1º)", "1°)", "registrese",
                           "notifiquese", "hagase saber", "archivese"):
                assert marker not in criterion, (
                    f"criterion contiene marcador de resolutivo: '{marker}'"
                )

    def test_alimentos_criterion_no_party_names(self):
        """criterion no debe contener nombres propios de partes."""
        payload = self.engine.analyze(
            query="alimentos para hijo menor",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            criterion = payload["jurisprudence_highlights"][0]["criterion"]
            # No uppercase multi-word names (party names)
            import re
            party_pattern = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{2,}\s+[A-ZÁÉÍÓÚÑ]{2,}\b")
            assert not party_pattern.search(criterion), (
                f"criterion contiene posible nombre de parte: {criterion!r}"
            )

    def test_alimentos_criterion_no_expte(self):
        """criterion no debe contener referencias a expedientes."""
        payload = self.engine.analyze(
            query="cuota alimentaria provisoria",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            criterion = payload["jurisprudence_highlights"][0]["criterion"].lower()
            for marker in ("expte", "expediente", "legajo"):
                assert marker not in criterion, (
                    f"criterion contiene referencia a expediente: '{marker}'"
                )

    def test_alimentos_strategic_use_no_raw_text(self):
        payload = self.engine.analyze(
            query="Cuota alimentaria provisoria",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            lowered = first["strategic_use"].lower()
            for bad in ("registrese", "notifiquese", "hagase saber", "archivese", "poder judicial"):
                assert bad not in lowered, f"strategic_use contiene texto crudo: '{bad}'"

    def test_alimentos_strategic_use_not_empty(self):
        payload = self.engine.analyze(
            query="alimentos",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            assert first["strategic_use"].strip(), "strategic_use no debe estar vacío"


# ---------------------------------------------------------------------------
# 5. JurisprudenceEngine: síntesis limpia para sucesiones
# ---------------------------------------------------------------------------

class TestSucesionJurisprudenceSynthesis:
    """Sucesiones: criterion no debe contener fragmentos de resolutivo."""

    def setup_method(self):
        self.engine = JurisprudenceEngine(
            jurisprudence_retriever=JurisprudenceRetriever(corpus_root=SAMPLE_CORPUS_ROOT)
        )

    def _payload(self):
        return dict(
            classification={
                "action_slug": "sucesion_ab_intestato",
                "action_label": "Sucesion ab intestato",
                "confidence_score": 0.9,
                "jurisdiction": "jujuy",
                "forum": "civil",
            },
            case_structure={
                "facts": ["Fallecio el padre.", "Los hijos quieren iniciar la sucesion."],
                "missing_information": ["Ultimo domicilio del causante."],
                "risks": [],
            },
            normative_reasoning={
                "applied_rules": [
                    {"source": "CCyC", "article": "2336", "relevance": "Competencia", "effect": "Ultimo domicilio"},
                ],
                "requirements": ["Partida de defuncion."],
                "unresolved_issues": [],
            },
        )

    def test_sucesion_criterion_no_registrese(self):
        payload = self.engine.analyze(
            query="Posesion hereditaria en sucesion ab intestato",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            for bad in ("registrese", "notifiquese", "hagase saber", "archivese", "poder judicial", "en la ciudad de"):
                assert bad not in first["criterion"].lower(), f"criterion contiene residuo: '{bad}'"

    def test_sucesion_criterion_no_dni(self):
        payload = self.engine.analyze(
            query="sucesion ab intestato",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            assert "dni" not in first["criterion"].lower()

    def test_sucesion_criterion_has_legal_content(self):
        payload = self.engine.analyze(
            query="sucesion ab intestato declaratoria de herederos",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            lowered = first["criterion"].lower()
            assert any(kw in lowered for kw in ("declaratoria", "hereder", "sucesion", "sucesorio", "fallecimiento", "competencia"))

    def test_sucesion_criterion_word_count(self):
        """criterion debe tener entre 12 y 40 palabras."""
        payload = self.engine.analyze(
            query="sucesion ab intestato declaratoria de herederos",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            criterion = payload["jurisprudence_highlights"][0]["criterion"]
            word_count = len(criterion.split())
            assert 12 <= word_count <= 40, (
                f"criterion tiene {word_count} palabras (debe ser 12-40): {criterion!r}"
            )

    def test_sucesion_criterion_no_resolutivo_markers(self):
        """criterion no debe contener marcadores de resolutivo."""
        payload = self.engine.analyze(
            query="sucesion ab intestato",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            criterion = payload["jurisprudence_highlights"][0]["criterion"].lower()
            for marker in ("resuelvo", "fallo", "1º)", "1°)", "registrese",
                           "notifiquese", "hagase saber", "archivese", "expte"):
                assert marker not in criterion, (
                    f"criterion contiene marcador de resolutivo: '{marker}'"
                )

    def test_sucesion_criterion_no_party_names(self):
        """criterion no debe contener nombres propios de partes."""
        payload = self.engine.analyze(
            query="sucesion ab intestato",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            criterion = payload["jurisprudence_highlights"][0]["criterion"]
            import re
            party_pattern = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{2,}\s+[A-ZÁÉÍÓÚÑ]{2,}\b")
            assert not party_pattern.search(criterion), (
                f"criterion contiene posible nombre de parte: {criterion!r}"
            )

    def test_sucesion_strategic_use_no_raw_text(self):
        payload = self.engine.analyze(
            query="sucesion ab intestato",
            **self._payload(),
        ).to_dict()
        if payload["jurisprudence_highlights"]:
            first = payload["jurisprudence_highlights"][0]
            lowered = first["strategic_use"].lower()
            for bad in ("registrese", "notifiquese", "hagase saber", "san salvador de jujuy"):
                assert bad not in lowered


# ---------------------------------------------------------------------------
# 6. _clean_case_text: tests directos del sanitizador
# ---------------------------------------------------------------------------

class TestCleanCaseText:
    """Verifica que _clean_case_text elimina fragmentos problemáticos."""

    def test_removes_dni(self):
        result = JurisprudenceEngine._clean_case_text("El alimentante DNI 23.456.789 debe pagar cuota")
        assert "23.456.789" not in result
        assert "DNI" not in result

    def test_removes_registrese(self):
        result = JurisprudenceEngine._clean_case_text("Registrese y notifiquese.")
        assert result == ""

    def test_removes_hacer_lugar(self):
        result = JurisprudenceEngine._clean_case_text("Hacer lugar a la demanda de alimentos provisorios")
        assert "hacer lugar" not in result.lower()

    def test_removes_costas(self):
        result = JurisprudenceEngine._clean_case_text("Se fija cuota alimentaria con costas al vencido en un 80%")
        assert "costas" not in result.lower()

    def test_removes_en_la_ciudad_de(self):
        result = JurisprudenceEngine._clean_case_text("En la ciudad de San Salvador de Jujuy, a los 10 dias...")
        assert result == ""

    def test_removes_expediente(self):
        result = JurisprudenceEngine._clean_case_text("Expte. N° 12345/2023 - cuota alimentaria provisoria")
        assert "12345" not in result

    def test_removes_money_amounts(self):
        result = JurisprudenceEngine._clean_case_text("Fija cuota en $15.000 mensuales")
        assert "15.000" not in result

    def test_removes_percentages(self):
        result = JurisprudenceEngine._clean_case_text("cuota del 15% de los ingresos")
        assert "15%" not in result

    def test_preserves_substantive_legal_text(self):
        text = "La obligacion alimentaria del progenitor subsiste mientras las necesidades del hijo lo requieran"
        result = JurisprudenceEngine._clean_case_text(text)
        assert "obligacion alimentaria" in result.lower()
        assert "necesidades" in result.lower()

    def test_discards_very_short_result(self):
        result = JurisprudenceEngine._clean_case_text("OK.")
        assert result == ""

    def test_removes_hagase_saber(self):
        result = JurisprudenceEngine._clean_case_text("Hagase saber y cumplase")
        assert result == ""

    def test_removes_dates(self):
        result = JurisprudenceEngine._clean_case_text("Resuelto el 15/03/2024 por la Sala I")
        assert "15/03/2024" not in result


class TestAlimentosGeneratedDocument:
    def test_formal_document_for_non_payment_pushes_provisional_quota(self):
        payload = AilexPipeline().run(
            query="El padre de mi hijo no paga alimentos y necesito cuota provisoria",
            jurisdiction="jujuy",
            document_mode="formal",
        ).to_dict()

        document = (payload.get("generated_document") or "").lower()
        assert document
        assert "cuota provisoria" in document
        assert "incumplimiento" in document or "no paga" in document
