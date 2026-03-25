from legal_engine.jurisprudence_schema import (
    LEGACY_MODE,
    STRICT_MODE,
    JurisprudencePrecedent,
    normalize_applied_articles,
    validate_precedent,
)


def test_strict_mode_requires_explicit_core_fields():
    precedent = JurisprudencePrecedent.from_record(
        {
            "id": "strict-bad-001",
            "topic": "divorcio",
            "subtopic": "divorcio_unilateral",
            "jurisdiction": "jujuy",
            "forum": "familia",
            "court": "Tribunal de Familia",
            "year": 2025,
            "case_name": "S. c/ M. s/ divorcio",
            "source_type": "sentencia_judicial",
            "applied_articles": ["ccyc 437"],
        },
        mode=STRICT_MODE,
    )

    errors = validate_precedent(precedent, mode=STRICT_MODE)

    assert any(error.field_name == "legal_issue" for error in errors)
    assert any(error.field_name == "criterion" for error in errors)
    assert any(error.field_name == "strategic_use" for error in errors)


def test_strict_mode_rejects_resolutivo_and_procedural_noise():
    precedent = JurisprudencePrecedent.from_record(
        {
            "id": "strict-bad-002",
            "topic": "alimentos",
            "subtopic": "cuota_provisoria",
            "jurisdiction": "jujuy",
            "forum": "familia",
            "court": "Juzgado de Familia",
            "year": 2024,
            "case_name": "A. c/ B. s/ alimentos",
            "source_type": "sentencia_judicial",
            "legal_issue": "Cuota provisoria con prueba de gastos del hijo y capacidad economica del obligado.",
            "criterion": "Resuelvo fijar cuota alimentaria provisoria en Expte. 123/24 a favor del actor DNI 20111222.",
            "strategic_use": "Sirve para fundar una cuota provisoria con prueba documental de gastos del hijo y urgencia alimentaria.",
            "full_text": "Texto suficiente para el precedente de prueba.",
            "applied_articles": ["CCyC 658"],
        },
        mode=STRICT_MODE,
    )

    errors = validate_precedent(precedent, mode=STRICT_MODE)

    assert any(error.field_name == "criterion" for error in errors)


def test_legacy_mode_can_import_old_fixture_without_explicit_criterion():
    precedent = JurisprudencePrecedent.from_record(
        {
            "case_id": "legacy-001",
            "court": "Camara de Familia",
            "jurisdiction": "jujuy",
            "forum": "familia",
            "year": 2024,
            "case_name": "Caso legacy",
            "source": "fixture",
            "legal_issue": "Alimentos provisorios para hijo menor.",
            "holding": "La existencia de gastos regulares del hijo justifica una cuota provisoria aun con informacion economica incompleta.",
            "strategic_value": "Util para sostener una cuota provisoria cuando ya hay comprobantes de gastos.",
            "topics": ["alimentos", "cuota provisoria"],
            "applied_articles": ["CCyC 658"],
            "document_type": "sentencia",
            "facts_summary": "Hechos relevantes.",
            "decision_summary": "Decision relevante.",
        },
        mode=LEGACY_MODE,
    )

    errors = validate_precedent(precedent, mode=LEGACY_MODE)

    assert errors == []
    assert precedent.topic == "alimentos"
    assert precedent.subtopic == "cuota_provisoria"
    assert precedent.criterion


def test_applied_articles_are_normalized_consistently():
    articles = normalize_applied_articles(["ccyc 437", {"source": "codigo civil y comercial", "article": "438"}])

    assert articles == ["CCyC 437", "CCyC 438"]
