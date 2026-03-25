from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from scripts import benchmark_report


def test_build_report_data_includes_delta_confidence_and_failures_first():
    report = benchmark_report.build_report_data()
    cases = report["cases"]

    assert cases
    assert "delta_confidence" in cases[0]
    fail_section_ended = False
    for item in cases:
        if item["result"] == "FAIL":
            assert not fail_section_ended
        else:
            fail_section_ended = True


def test_fail_only_filters_visible_cases_only():
    report = benchmark_report.build_report_data(fail_only=True)
    assert report["summary"]["total"] >= len(report["visible_cases"])
    assert all(item["result"] == "FAIL" for item in report["visible_cases"])


def test_json_payload_is_serializable_and_contains_summary_fields():
    report = benchmark_report.build_report_data()
    payload = {
        **report["summary"],
        "cases": report["cases"],
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)

    assert "total" in decoded
    assert "passed" in decoded
    assert "failed" in decoded
    assert "average_confidence" in decoded
    assert "average_delta_confidence" in decoded
    assert "cases" in decoded


def test_main_exit_code_matches_failed_count():
    report = benchmark_report.build_report_data()
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = benchmark_report.main(["--json"])
    expected_exit_code = 0 if report["summary"]["failed"] == 0 else 1
    assert exit_code == expected_exit_code


def test_distribution_text_accepts_dict_counts():
    text = benchmark_report._distribution_text({"agresiva": 2, "cautelosa": 1})
    assert text == "agresiva: 2, cautelosa: 1"


def test_compare_includes_grouped_changes_and_summary_deltas(tmp_path):
    current = benchmark_report.build_report_data()
    previous_payload = {
        **current["summary"],
        "cases": [dict(item) for item in current["cases"]],
    }
    previous_payload["passed"] -= 2
    previous_payload["failed"] += 2
    previous_payload["average_confidence"] -= 0.05
    previous_payload["average_delta_confidence"] -= 0.02
    previous_payload["cases"][0]["result"] = "FAIL"
    previous_payload["cases"][0]["confidence_score"] -= 0.1
    previous_payload["cases"][0]["delta_confidence"] -= 0.1
    previous_payload["cases"][1]["real_strategic_posture"] = "conservadora"
    previous_payload["cases"][1]["confidence_score"] += 0.03
    previous_payload["cases"][1]["delta_confidence"] += 0.03

    compare_path = tmp_path / "previous_run.json"
    compare_path.write_text(json.dumps(previous_payload, ensure_ascii=False), encoding="utf-8")

    report = benchmark_report.build_report_data(compare_path=str(compare_path))
    comparison = report["comparison"]

    assert comparison["delta"]["passed"] == 2
    assert comparison["delta"]["failed"] == -2
    assert comparison["top_improvements"]
    assert comparison["other_changed_cases"]
    assert comparison["top_improvements"][0]["id"] == previous_payload["cases"][0]["id"]


def test_quiet_text_mode_reduces_output():
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        benchmark_report.main(["--quiet"])
    output = stdout.getvalue()

    assert "AILEX Legal Benchmark Report" not in output
    assert "Resumen" in output


def test_limit_reduces_visible_text_rows():
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        benchmark_report.main(["--limit", "2"])
    output = stdout.getvalue()

    assert "AILEX Legal Benchmark Report" in output
    assert "alimentos_urgente_fuerte" in output
    assert "alimentos_prueba_debil" in output
    assert "divorcio_base_normativa_buena" not in output
