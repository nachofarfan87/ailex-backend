from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.beta_observability_helpers import (
    extract_secondary_domains,
    extract_selected_model_fields,
    load_recent_snapshots,
)
from app.services.beta_observability_service import (
    fail_beta_observability_context,
    finalize_beta_observability_context,
    start_beta_observability_context,
    summarize_beta_observability,
    update_beta_observability_context,
)
from legal_engine.case_profile_builder import align_classification_with_domain, build_case_profile
from legal_engine.model_library import ModelLibrary


def _build_index(tmp_path: Path) -> Path:
    payload = {
        "version": 1,
        "models": [
            {
                "model_id": "divorcio_template",
                "name": "Divorcio unilateral base",
                "source_type": "virtual",
                "priority": 3,
                "rating": 5,
                "applicability": {
                    "jurisdiction": "nacional",
                    "forum": "familia",
                    "action_slug": "divorcio_unilateral",
                    "document_kind": "formal",
                },
                "style_profile": {
                    "tone": "technical_robust",
                    "structure": [],
                    "argument_density": "high",
                    "facts_style": "concrete",
                    "petitum_style": "progressive",
                },
            },
            {
                "model_id": "alimentos_template",
                "name": "Alimentos hijos base",
                "source_type": "virtual",
                "priority": 3,
                "rating": 5,
                "applicability": {
                    "jurisdiction": "nacional",
                    "forum": "familia",
                    "action_slug": "alimentos_hijos",
                    "document_kind": "formal",
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


def _build_profile(query: str, classification: dict[str, str]) -> dict:
    return build_case_profile(
        query=query,
        classification=classification,
        case_theory={},
        conflict={},
        normative_reasoning={},
        procedural_plan={},
        facts={},
    )


def _new_context(tmp_path: Path):
    return start_beta_observability_context(
        request_id="req-beta",
        trace_id="trace-beta",
        query="consulta",
        storage_dir=tmp_path,
    )


def test_observability_snapshot_captures_slug_alignment(tmp_path):
    context = _new_context(tmp_path)
    raw_classification = {"action_slug": "alimentos_hijos"}
    profile = _build_profile("Quiero divorciarme", raw_classification)
    aligned = align_classification_with_domain(raw_classification, profile["case_domain"], "Quiero divorciarme")

    update_beta_observability_context(
        context,
        original_action_slug="alimentos_hijos",
        final_action_slug=aligned["action_slug"],
        final_case_domain=profile["case_domain"],
        slug_aligned_to_domain=bool(aligned.get("_original_action_slug")),
    )
    payload = finalize_beta_observability_context(context, emit=False)

    assert payload["original_action_slug"] == "alimentos_hijos"
    assert payload["final_action_slug"] == "divorcio_unilateral"
    assert payload["slug_aligned_to_domain"] is True


def test_observability_snapshot_records_domain_override(tmp_path):
    context = _new_context(tmp_path)
    update_beta_observability_context(
        context,
        original_case_domain="alimentos",
        final_case_domain="divorcio",
        domain_override_applied=True,
    )
    payload = finalize_beta_observability_context(context, emit=False)

    assert payload["original_case_domain"] == "alimentos"
    assert payload["final_case_domain"] == "divorcio"
    assert payload["domain_override_applied"] is True


def test_observability_snapshot_records_selected_model(tmp_path):
    context = _new_context(tmp_path)
    library = ModelLibrary(_build_index(tmp_path))
    selected = library.select_model(
        jurisdiction="nacional",
        forum="familia",
        action_slug="divorcio_unilateral",
        document_kind="formal",
    )

    update_beta_observability_context(context, **extract_selected_model_fields(selected))
    payload = finalize_beta_observability_context(context, emit=False)

    assert payload["selected_model"] == "divorcio_template"
    assert payload["selected_template"] == "Divorcio unilateral base"


def test_observability_snapshot_handles_no_alignment_case(tmp_path):
    context = _new_context(tmp_path)
    raw_classification = {"action_slug": "alimentos_hijos"}
    profile = _build_profile("El padre no paga alimentos", raw_classification)
    aligned = align_classification_with_domain(raw_classification, profile["case_domain"], "El padre no paga alimentos")

    update_beta_observability_context(
        context,
        original_action_slug="alimentos_hijos",
        final_action_slug=aligned["action_slug"],
        slug_aligned_to_domain=bool(aligned.get("_original_action_slug")),
    )
    payload = finalize_beta_observability_context(context, emit=False)

    assert payload["original_action_slug"] == payload["final_action_slug"]
    assert payload["slug_aligned_to_domain"] is False


def test_observability_snapshot_records_response_status_success(tmp_path):
    context = _new_context(tmp_path)
    update_beta_observability_context(context, fallback_detected=False, safety_status="normal")
    payload = finalize_beta_observability_context(context, emit=False)

    assert payload["response_status"] == "success"


def test_observability_snapshot_records_error_status_on_exception(tmp_path):
    context = _new_context(tmp_path)
    payload = fail_beta_observability_context(
        context,
        error_message="controlled_orchestrator_error",
        response_status="blocked",
        emit=False,
    )

    assert payload["response_status"] == "blocked"
    assert payload["error_message"] == "controlled_orchestrator_error"


def test_observability_logging_is_json_friendly(tmp_path):
    context = _new_context(tmp_path)
    update_beta_observability_context(
        context,
        final_case_domain="divorcio",
        final_action_slug="divorcio_unilateral",
        stage_durations_ms={"pipeline_model_selection_ms": 12},
    )
    payload = finalize_beta_observability_context(context, emit=True)

    rendered = json.dumps(payload, ensure_ascii=False)
    assert rendered
    stored = load_recent_snapshots(storage_dir=tmp_path, limit=1, days=1)[0]
    assert stored["final_action_slug"] == "divorcio_unilateral"


def test_observability_snapshot_records_secondary_domains(tmp_path):
    context = _new_context(tmp_path)
    secondary_domains = extract_secondary_domains(["divorcio", "alimentos", "vivienda"], "divorcio")
    update_beta_observability_context(
        context,
        final_case_domain="divorcio",
        secondary_domains=secondary_domains,
        had_secondary_domains=bool(secondary_domains),
    )
    payload = finalize_beta_observability_context(context, emit=False)

    assert payload["secondary_domains"] == ["alimentos", "vivienda"]
    assert payload["had_secondary_domains"] is True


def test_observability_total_duration_is_recorded(tmp_path):
    context = _new_context(tmp_path)
    payload = finalize_beta_observability_context(context, total_duration_ms=184, emit=False)

    assert payload["total_duration_ms"] == 184


def test_observability_summary_helper_returns_operational_view(tmp_path):
    context = _new_context(tmp_path)
    update_beta_observability_context(
        context,
        final_case_domain="divorcio",
        final_action_slug="divorcio_unilateral",
        fallback_detected=True,
        response_status="degraded",
    )
    finalize_beta_observability_context(context, emit=True)

    summary = summarize_beta_observability(storage_dir=tmp_path, limit=10, days=1)

    assert summary["total_snapshots"] == 1
    assert summary["fallback_count"] == 1
    assert summary["recent_items"][0]["final_case_domain"] == "divorcio"
