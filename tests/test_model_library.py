import json

from legal_engine.model_library import ModelLibrary


def _write_index(tmp_path):
    payload = {
        "version": 1,
        "models": [
            {
                "model_id": "exact_model",
                "name": "Exacto",
                "source_type": "virtual",
                "priority": 3,
                "rating": 5,
                "applicability": {
                    "jurisdiction": "jujuy",
                    "forum": "familia",
                    "action_slug": "alimentos_hijos",
                    "document_kind": "formal",
                    "tags": ["estructura_base"],
                    "preferred_tags": ["cuota_provisoria"],
                    "excluded_tags": ["ascendientes"],
                },
                "style_profile": {
                    "tone": "technical_robust",
                    "structure": ["hechos_decisivos"],
                    "argument_density": "high",
                    "facts_style": "concrete",
                    "petitum_style": "progressive",
                    "opening_line": "Abrir con conflicto y soporte.",
                    "analysis_directive": "Analisis robusto.",
                    "facts_directive": "Hechos concretos.",
                    "petitum_directive": "Petitum gradual.",
                    "section_cues": ["Separar hechos y prueba."],
                },
                "argument_strategy": {
                    "focus": "urgency",
                    "risk_tolerance": "medium",
                    "proof_priority": ["documental", "informativa"],
                    "normative_anchor": "strong",
                },
            },
            {
                "model_id": "fallback_action_doc",
                "name": "Fallback accion",
                "source_type": "virtual",
                "priority": 2,
                "rating": 3,
                "applicability": {
                    "forum": "familia",
                    "action_slug": "alimentos_hijos",
                    "document_kind": "formal",
                    "tags": [],
                    "preferred_tags": [],
                    "excluded_tags": [],
                },
                "style_profile": {
                    "tone": "balanced_prudent",
                    "structure": [],
                    "argument_density": "standard",
                    "facts_style": "concrete",
                    "petitum_style": "prudent",
                },
            },
            {
                "model_id": "fallback_forum_doc",
                "name": "Fallback fuero documento",
                "source_type": "virtual",
                "priority": 1,
                "rating": 2,
                "applicability": {
                    "forum": "familia",
                    "document_kind": "formal",
                    "tags": [],
                    "preferred_tags": [],
                    "excluded_tags": [],
                },
                "style_profile": {
                    "tone": "balanced_prudent",
                    "structure": [],
                    "argument_density": "standard",
                    "facts_style": "concrete",
                    "petitum_style": "prudent",
                },
            },
        ],
    }
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    return index_path


def test_exact_selection(tmp_path):
    library = ModelLibrary(_write_index(tmp_path))

    result = library.select_model(
        jurisdiction="jujuy",
        forum="familia",
        action_slug="alimentos_hijos",
        document_kind="formal",
        detected_tags=["estructura_base"],
    )

    assert result["selected_model"]["model_id"] == "exact_model"
    assert result["match_type"] == "exact"
    assert result["style_directives"]["tone"] == "technical_robust"
    assert result["argument_strategy"]["focus"] == "urgency"


def test_fallback_by_forum_document_kind(tmp_path):
    library = ModelLibrary(_write_index(tmp_path))

    result = library.select_model(
        jurisdiction="jujuy",
        forum="familia",
        action_slug="divorcio",
        document_kind="formal",
        detected_tags=[],
    )

    assert result["selected_model"]["model_id"] == "fallback_forum_doc"
    assert result["match_type"] == "fallback_forum_document_kind"


def test_preferred_tags_increase_score(tmp_path):
    library = ModelLibrary(_write_index(tmp_path))

    result = library.select_model(
        jurisdiction="jujuy",
        forum="familia",
        action_slug="alimentos_hijos",
        document_kind="formal",
        detected_tags=["cuota_provisoria"],
    )

    assert result["selected_model"]["model_id"] == "exact_model"
    assert any("tags preferidos" in warning.lower() for warning in result["warnings"])


def test_returns_none_when_no_model_is_available(tmp_path):
    library = ModelLibrary(_write_index(tmp_path))

    result = library.select_model(
        jurisdiction="jujuy",
        forum="laboral",
        action_slug="despido",
        document_kind="formal",
        detected_tags=[],
    )

    assert result["selected_model"] is None
    assert result["match_type"] == "none"
    assert result["confidence"] == 0.0


def test_confidence_and_warnings_reflect_penalties(tmp_path):
    library = ModelLibrary(_write_index(tmp_path))

    result = library.select_model(
        jurisdiction="jujuy",
        forum="familia",
        action_slug="alimentos_hijos",
        document_kind="formal",
        detected_tags=["ascendientes"],
    )

    assert result["confidence"] > 0.0
    assert any("penalizo" in warning.lower() for warning in result["warnings"])


# ---------------------------------------------------------------------------
# Integrity validation tests
# ---------------------------------------------------------------------------

def _write_index_with_source_paths(tmp_path, models):
    payload = {"version": 1, "models": models}
    index_path = tmp_path / "data" / "model_library" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    return index_path


def test_virtual_model_passes_integrity(tmp_path):
    """source_type='virtual' should not require a file."""
    index_path = _write_index_with_source_paths(tmp_path, [
        {
            "model_id": "virtual_ok",
            "name": "Virtual",
            "source_type": "virtual",
            "priority": 1,
            "rating": 3,
            "applicability": {"forum": "familia", "document_kind": "formal", "tags": [], "preferred_tags": [], "excluded_tags": []},
            "style_profile": {"tone": "balanced_prudent"},
        },
    ])
    library = ModelLibrary(index_path)
    assert library.validate_integrity() is True
    report = library.get_integrity_report()
    assert report["valid"] is True
    assert report["total_records"] == 1
    assert report["active_records"] == 1
    assert report["excluded_model_ids"] == []


def test_missing_source_file_excludes_model(tmp_path):
    """A pdf model pointing to a non-existent file should be excluded."""
    index_path = _write_index_with_source_paths(tmp_path, [
        {
            "model_id": "missing_file",
            "name": "Missing",
            "source_path": "backend/data/writing_models/nonexistent.pdf",
            "source_type": "pdf",
            "priority": 5,
            "rating": 5,
            "applicability": {
                "jurisdiction": "jujuy",
                "forum": "familia",
                "action_slug": "alimentos_hijos",
                "document_kind": "formal",
                "tags": [],
                "preferred_tags": [],
                "excluded_tags": [],
            },
            "style_profile": {"tone": "balanced_prudent"},
        },
        {
            "model_id": "virtual_ok",
            "name": "Virtual",
            "source_type": "virtual",
            "priority": 1,
            "rating": 3,
            "applicability": {"forum": "familia", "document_kind": "formal", "tags": [], "preferred_tags": [], "excluded_tags": []},
            "style_profile": {"tone": "balanced_prudent"},
        },
    ])
    library = ModelLibrary(index_path)
    assert library.validate_integrity() is False
    report = library.get_integrity_report()
    assert "missing_file" in report["excluded_model_ids"]
    assert report["active_records"] == 1
    assert len(report["warnings"]) == 1

    # The excluded model should not be selectable
    result = library.select_model(
        jurisdiction="jujuy",
        forum="familia",
        action_slug="alimentos_hijos",
        document_kind="formal",
    )
    if result["selected_model"] is not None:
        assert result["selected_model"]["model_id"] != "missing_file"


def test_empty_source_path_with_pdf_type_excluded(tmp_path):
    """A pdf model with empty source_path should be excluded."""
    index_path = _write_index_with_source_paths(tmp_path, [
        {
            "model_id": "empty_path",
            "name": "Empty Path",
            "source_path": "",
            "source_type": "pdf",
            "priority": 5,
            "rating": 5,
            "applicability": {"forum": "familia", "document_kind": "formal", "tags": [], "preferred_tags": [], "excluded_tags": []},
            "style_profile": {"tone": "balanced_prudent"},
        },
    ])
    library = ModelLibrary(index_path)
    assert library.validate_integrity() is False
    assert "empty_path" in library.get_integrity_report()["excluded_model_ids"]
    assert len(library.records) == 0


def test_validate_false_disables_integrity_check(tmp_path):
    """validate=False should skip integrity checks."""
    index_path = _write_index_with_source_paths(tmp_path, [
        {
            "model_id": "no_check",
            "name": "No Check",
            "source_path": "nonexistent.pdf",
            "source_type": "pdf",
            "priority": 1,
            "rating": 1,
            "applicability": {"forum": "familia", "document_kind": "formal", "tags": [], "preferred_tags": [], "excluded_tags": []},
            "style_profile": {"tone": "balanced_prudent"},
        },
    ])
    library = ModelLibrary(index_path, validate=False)
    assert library.validate_integrity() is True
    assert len(library.records) == 1
