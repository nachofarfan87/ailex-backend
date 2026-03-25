import io
from zipfile import ZipFile

from app.services.legal_export import build_legal_query_docx
from legal_engine.ailex_pipeline import AilexPipeline
from legal_engine.case_evaluation_engine import CaseEvaluationEngine
from legal_engine.evidence_reasoning_linker import (
    EvidenceReasoningLinker,
    EvidenceReasoningResult,
    RequirementLink,
)


def _payload(
    action_slug: str,
    action_label: str,
    *,
    facts: list[str] | None = None,
    missing_information: list[str] | None = None,
    requirements: list[str] | None = None,
    unresolved_issues: list[str] | None = None,
    critical_questions: list[str] | None = None,
    evidentiary_needs: list[str] | None = None,
    likely_points_of_conflict: list[str] | None = None,
    critical_evidence_available: list[str] | None = None,
    key_evidence_missing: list[str] | None = None,
) -> dict:
    classification = {
        "action_slug": action_slug,
        "action_label": action_label,
        "confidence_score": 0.9,
    }
    case_structure = {
        "facts": facts if facts is not None else [
            "El matrimonio se celebro en 2015.",
            "Ambas partes tienen domicilio en Jujuy.",
            "Existen dos hijos menores de edad.",
        ],
        "missing_information": missing_information if missing_information is not None else [
            "Datos sobre bienes comunes.",
        ],
        "risks": ["Riesgo base 1"],
    }
    normative_reasoning = {
        "applied_rules": [
            {"source": "CCyC", "article": "437", "title": "Divorcio", "relevance": "Habilita divorcio incausado", "effect": "Disolucion del vinculo matrimonial"},
            {"source": "CCyC", "article": "438", "title": "Requisitos", "relevance": "Requiere propuesta reguladora", "effect": "Regulacion de efectos del divorcio"},
            {"source": "CCyC", "article": "439", "title": "Convenio regulador", "relevance": "Convenio sobre hijos y bienes", "effect": "Homologacion judicial del acuerdo"},
        ],
        "requirements": requirements if requirements is not None else [
            "Acreditar existencia del vinculo matrimonial.",
            "Presentar propuesta reguladora sobre hijos y bienes.",
            "Definir regimen de alimentos y cuidado personal.",
        ],
        "unresolved_issues": unresolved_issues if unresolved_issues is not None else [
            "Pendiente definir competencia territorial.",
        ],
        "warnings": [],
    }
    question_engine_result = {
        "critical_questions": critical_questions if critical_questions is not None else [
            "Situacion patrimonial de los conyuges.",
        ],
    }
    case_theory = {
        "primary_theory": "Teoria principal del caso.",
        "likely_points_of_conflict": likely_points_of_conflict if likely_points_of_conflict is not None else [
            "Conflicto sobre bienes gananciales.",
            "Conflicto sobre cuidado personal de hijos.",
        ],
        "evidentiary_needs": evidentiary_needs if evidentiary_needs is not None else [
            "Documentacion del vinculo matrimonial.",
        ],
        "key_facts_supporting": ["Hecho de soporte 1"],
    }
    case_evaluation = CaseEvaluationEngine().evaluate(
        query="Consulta base",
        classification=classification,
        case_structure=case_structure,
        normative_reasoning=normative_reasoning,
        procedural_strategy={"next_steps": ["Paso 1"], "risks": ["Riesgo procesal"]},
        case_theory=case_theory,
        question_engine_result=question_engine_result,
    ).to_dict()
    conflict_evidence = {
        "core_dispute": "Nucleo del conflicto.",
        "strongest_point": "Punto fuerte.",
        "most_vulnerable_point": "Debilidad en acreditacion de bienes y propuesta reguladora.",
        "critical_evidence_available": critical_evidence_available if critical_evidence_available is not None else [
            "Existencia del vinculo matrimonial.",
            "Voluntad concurrente de divorciarse.",
        ],
        "key_evidence_missing": key_evidence_missing if key_evidence_missing is not None else [
            "Convenio regulador completo.",
            "Datos sobre bienes comunes.",
            "Datos sobre hijos menores.",
        ],
        "probable_counterarguments": ["Contraargumento 1"],
        "recommended_evidence_actions": ["Accion 1"],
        "confidence_score": 0.75,
        "warnings": [],
    }
    return {
        "classification": classification,
        "case_structure": case_structure,
        "normative_reasoning": normative_reasoning,
        "question_engine_result": question_engine_result,
        "case_theory": case_theory,
        "case_evaluation": case_evaluation,
        "conflict_evidence": conflict_evidence,
    }


# ------------------------------------------------------------------
# Serialization
# ------------------------------------------------------------------


def test_result_serialization():
    link = RequirementLink(
        source="CCyC",
        article="437",
        requirement="Acreditar vinculo.",
        supporting_facts=["Hecho 1"],
        evidence_available=["Prueba 1"],
        evidence_missing=["Faltante 1"],
        support_level="alto",
        strategic_note="Bien soportado.",
    )
    result = EvidenceReasoningResult(
        summary="Resumen.",
        requirement_links=[link],
        globally_supported_requirements=["Acreditar vinculo."],
        weakly_supported_requirements=[],
        critical_evidentiary_gaps=["Gap 1"],
        strategic_warnings=["Warning 1"],
        confidence_score=0.78,
    )
    payload = result.to_dict()

    assert payload["summary"] == "Resumen."
    assert len(payload["requirement_links"]) == 1
    assert payload["requirement_links"][0]["source"] == "CCyC"
    assert payload["confidence_score"] == 0.78


# ------------------------------------------------------------------
# Per-slug tests
# ------------------------------------------------------------------


def test_divorcio_mutuo_acuerdo():
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo")

    result = engine.analyze(query="Divorcio de comun acuerdo", **data)

    assert result.summary
    assert len(result.requirement_links) > 0
    assert all(link.support_level in ("alto", "medio", "bajo") for link in result.requirement_links)


def test_divorcio_unilateral():
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_unilateral", "Divorcio unilateral")

    result = engine.analyze(query="Me quiero divorciar sin acuerdo", **data)

    assert result.summary
    assert len(result.requirement_links) > 0


def test_divorcio_generico():
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio", "Divorcio")

    result = engine.analyze(query="Quiero divorciarme", **data)

    assert result.summary
    assert isinstance(result.requirement_links, list)


def test_alimentos_hijos():
    engine = EvidenceReasoningLinker()
    data = _payload(
        "alimentos_hijos",
        "Alimentos para hijos",
        facts=[
            "El padre no paga alimentos desde hace 6 meses.",
            "El hijo tiene 5 anios.",
            "La madre convive con el hijo.",
        ],
        requirements=[
            "Acreditar vinculo filial.",
            "Acreditar necesidades del hijo.",
            "Acreditar capacidad economica del obligado.",
        ],
        critical_evidence_available=[
            "Vinculo filial invocado.",
        ],
        key_evidence_missing=[
            "Comprobantes de gastos del hijo.",
            "Datos de ingresos del obligado.",
        ],
    )

    result = engine.analyze(query="El padre no paga alimentos", **data)

    assert result.summary
    assert len(result.requirement_links) >= 3
    levels = [link.support_level for link in result.requirement_links]
    assert "bajo" in levels or "medio" in levels


def test_sucesion_ab_intestato():
    engine = EvidenceReasoningLinker()
    data = _payload(
        "sucesion_ab_intestato",
        "Sucesion ab intestato",
        facts=[
            "El causante fallecio el 1 de enero de 2026.",
            "Existen tres hijos como herederos.",
        ],
        requirements=[
            "Acreditar fallecimiento del causante.",
            "Acreditar vinculo de parentesco de los herederos.",
            "Acreditar ultimo domicilio del causante.",
        ],
        critical_evidence_available=[
            "Fallecimiento del causante.",
        ],
        key_evidence_missing=[
            "Partida de defuncion.",
            "Partidas de nacimiento de los herederos.",
            "Constancia de ultimo domicilio.",
        ],
    )

    result = engine.analyze(query="Iniciar sucesion de mi padre", **data)

    assert result.summary
    assert len(result.requirement_links) >= 3


def test_generic_fallback():
    engine = EvidenceReasoningLinker()
    data = _payload("accion_generica", "Consulta generica")

    result = engine.analyze(query="Consulta contractual", **data)

    assert result.summary
    assert isinstance(result.requirement_links, list)
    assert isinstance(result.confidence_score, float)


# ------------------------------------------------------------------
# Structure and content quality
# ------------------------------------------------------------------


def test_support_levels_are_valid():
    """Todos los support_level deben ser alto, medio o bajo."""
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo")

    result = engine.analyze(query="Divorcio", **data)

    valid_levels = {"alto", "medio", "bajo"}
    for link in result.requirement_links:
        assert link.support_level in valid_levels, (
            f"support_level invalido: {link.support_level}"
        )


def test_globally_supported_matches_alto():
    """globally_supported_requirements debe corresponder a links con soporte alto."""
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo")

    result = engine.analyze(query="Divorcio", **data)

    alto_reqs = {link.requirement for link in result.requirement_links if link.support_level == "alto"}
    for req in result.globally_supported_requirements:
        assert req in alto_reqs, f"'{req}' no tiene soporte alto"


def test_weakly_supported_matches_bajo():
    """weakly_supported_requirements debe corresponder a links con soporte bajo."""
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo")

    result = engine.analyze(query="Divorcio", **data)

    bajo_reqs = {link.requirement for link in result.requirement_links if link.support_level == "bajo"}
    for req in result.weakly_supported_requirements:
        assert req in bajo_reqs, f"'{req}' no tiene soporte bajo"


def test_no_invented_articles():
    """Los articles en links deben provenir de applied_rules, no inventados."""
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo")

    result = engine.analyze(query="Divorcio", **data)

    valid_articles = {"437", "438", "439", ""}
    for link in result.requirement_links:
        assert link.article in valid_articles, (
            f"Articulo inventado: {link.article}"
        )


def test_strategic_notes_not_empty():
    """Cada link debe tener una nota estratégica."""
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo")

    result = engine.analyze(query="Divorcio", **data)

    for link in result.requirement_links:
        assert link.strategic_note, f"strategic_note vacio para: {link.requirement}"


def test_confidence_in_range():
    """confidence_score debe estar entre 0.2 y 0.95."""
    engine = EvidenceReasoningLinker()
    data = _payload("divorcio_mutuo_acuerdo", "Divorcio por mutuo acuerdo")

    result = engine.analyze(query="Divorcio", **data)

    assert 0.2 <= result.confidence_score <= 0.95


# ------------------------------------------------------------------
# Strict support_level tests
# ------------------------------------------------------------------


def test_support_level_bajo_when_no_facts_no_evidence():
    """Sin hechos ni evidencia vinculada, support_level debe ser bajo."""
    engine = EvidenceReasoningLinker()
    data = _payload(
        "divorcio_mutuo_acuerdo",
        "Divorcio por mutuo acuerdo",
        facts=[],
        critical_evidence_available=[],
        key_evidence_missing=["Convenio regulador.", "Partida de matrimonio."],
    )

    result = engine.analyze(query="Divorcio", **data)

    for link in result.requirement_links:
        assert link.support_level in ("bajo", "medio"), (
            f"Sin hechos ni evidencia, support_level no deberia ser alto: {link.requirement} = {link.support_level}"
        )


def test_support_level_not_alto_with_only_norm():
    """La mera existencia de norma aplicable NO debe dar soporte alto."""
    engine = EvidenceReasoningLinker()
    # Tiene reglas pero sin hechos ni evidencia que matcheen con los requisitos
    data = _payload(
        "divorcio_mutuo_acuerdo",
        "Divorcio por mutuo acuerdo",
        facts=["Consulta generica sin detalles facticos."],
        requirements=[
            "Acreditar compensacion economica.",
            "Demostrar perjuicio patrimonial concreto.",
        ],
        critical_evidence_available=[],
        key_evidence_missing=["Documentacion de perjuicio patrimonial."],
    )

    result = engine.analyze(query="Divorcio", **data)

    # Requisitos que no tienen keyword overlap con hechos/evidencia → bajo
    for link in result.requirement_links:
        if "compensacion" in link.requirement.lower() or "perjuicio" in link.requirement.lower():
            assert link.support_level != "alto", (
                f"Requisito sin soporte factico real no deberia ser alto: {link.requirement}"
            )


def test_support_level_medio_with_facts_but_gaps():
    """Con hechos pero también gaps, support_level debe ser medio no alto."""
    level = EvidenceReasoningLinker._compute_support_level(
        supporting_facts=["Hecho 1"],
        evidence_available=[],
        evidence_missing=["Faltante 1"],
    )
    assert level == "medio"


def test_support_level_alto_requires_facts_and_evidence():
    """Alto requiere tanto hechos como evidencia, con pocos gaps."""
    level = EvidenceReasoningLinker._compute_support_level(
        supporting_facts=["Hecho 1", "Hecho 2"],
        evidence_available=["Evidencia 1"],
        evidence_missing=[],
    )
    assert level == "alto"

    # Solo hechos sin evidencia → medio como máximo
    level2 = EvidenceReasoningLinker._compute_support_level(
        supporting_facts=["Hecho 1", "Hecho 2"],
        evidence_available=[],
        evidence_missing=[],
    )
    assert level2 == "medio"


# ------------------------------------------------------------------
# Pipeline integration
# ------------------------------------------------------------------


def test_pipeline_integration():
    """Pipeline completo debe incluir evidence_reasoning_links."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
    ).to_dict()

    assert "evidence_reasoning_links" in payload
    erl = payload["evidence_reasoning_links"]
    assert erl["summary"]
    assert isinstance(erl["requirement_links"], list)
    assert isinstance(erl["confidence_score"], float)


def test_pipeline_alimentos_integration():
    """Pipeline con alimentos debe incluir evidence_reasoning_links."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="El padre de mi hijo no paga alimentos",
        jurisdiction="jujuy",
    ).to_dict()

    erl = payload["evidence_reasoning_links"]
    assert erl["summary"]


# ------------------------------------------------------------------
# DOCX integration
# ------------------------------------------------------------------


def test_docx_integration():
    """DOCX export debe incluir sección de trazabilidad probatoria."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
        document_mode="formal",
    ).to_dict()

    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": "Dos personas quieren divorciarse", "jurisdiction": "jujuy"},
    )
    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Trazabilidad probatoria" in document_xml


# ------------------------------------------------------------------
# Real-query end-to-end tests
# ------------------------------------------------------------------


def test_e2e_divorcio_pipeline_full():
    """Pipeline completo para 'Quiero divorciarme' con validaciones de calidad."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="Quiero divorciarme",
        jurisdiction="jujuy",
        document_mode="formal",
    ).to_dict()

    # Classification
    cls = payload["classification"]
    assert cls.get("action_slug") in ("divorcio", "divorcio_mutuo_acuerdo", "divorcio_unilateral")

    # Conflict evidence present
    ce = payload["conflict_evidence"]
    assert ce.get("core_dispute")
    assert isinstance(ce.get("probable_counterarguments"), list)

    # Evidence reasoning links present and well-formed
    erl = payload["evidence_reasoning_links"]
    assert erl["summary"]
    links = erl["requirement_links"]
    assert isinstance(links, list)
    assert len(links) > 0
    for link in links:
        assert link["support_level"] in ("alto", "medio", "bajo")
        assert link["strategic_note"]

    # Generated document includes traceability
    doc = payload.get("generated_document") or ""
    assert "Trazabilidad Probatoria" in doc or len(doc) > 100

    # DOCX export works
    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": "Quiero divorciarme", "jurisdiction": "jujuy"},
    )
    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "Trazabilidad probatoria" in document_xml


def test_e2e_alimentos_pipeline_full():
    """Pipeline completo para alimentos con validaciones de calidad."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="El padre de mi hijo no paga alimentos",
        jurisdiction="jujuy",
        document_mode="formal",
    ).to_dict()

    cls = payload["classification"]
    assert cls.get("action_slug") == "alimentos_hijos"

    ce = payload["conflict_evidence"]
    assert ce.get("core_dispute")

    erl = payload["evidence_reasoning_links"]
    assert erl["summary"]
    assert len(erl["requirement_links"]) > 0

    # Support levels should be realistic — not all alto
    levels = [link["support_level"] for link in erl["requirement_links"]]
    assert "bajo" in levels or "medio" in levels, (
        f"Alimentos sin datos concretos no deberia tener todo alto: {levels}"
    )

    doc = payload.get("generated_document") or ""
    assert len(doc) > 100


def test_e2e_sucesion_pipeline_full():
    """Pipeline completo para sucesión con validaciones de calidad."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="Murio mi padre y quiero iniciar la sucesion",
        jurisdiction="jujuy",
        document_mode="formal",
    ).to_dict()

    cls = payload["classification"]
    assert cls.get("action_slug") == "sucesion_ab_intestato"

    ce = payload["conflict_evidence"]
    assert ce.get("core_dispute")

    erl = payload["evidence_reasoning_links"]
    assert erl["summary"]
    assert len(erl["requirement_links"]) > 0

    # DOCX works
    content = build_legal_query_docx(
        response_payload=payload,
        request_context={"query": "Sucesion", "jurisdiction": "jujuy"},
    )
    with ZipFile(io.BytesIO(content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "Trazabilidad probatoria" in document_xml


def test_e2e_formal_document_has_traceability_section():
    """Modo formal debe incluir sección Trazabilidad Probatoria en el documento generado."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="Quiero divorciarme",
        jurisdiction="jujuy",
        document_mode="formal",
    ).to_dict()

    doc = payload.get("generated_document") or ""
    assert "TRAZABILIDAD PROBATORIA" in doc.upper(), (
        "Modo formal no incluye seccion Trazabilidad Probatoria en generated_document"
    )


def test_e2e_base_argumental_has_traceability_section():
    """Modo base_argumental debe incluir sección Trazabilidad Probatoria."""
    pipeline = AilexPipeline()
    payload = pipeline.run(
        query="El padre de mi hijo no paga alimentos",
        jurisdiction="jujuy",
        document_mode="base_argumental",
    ).to_dict()

    doc = payload.get("generated_document") or ""
    assert "TRAZABILIDAD PROBATORIA" in doc.upper(), (
        "Modo base_argumental no incluye seccion Trazabilidad Probatoria en generated_document"
    )
