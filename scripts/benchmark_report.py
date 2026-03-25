# backend/scripts/benchmark_report.py
# Uso:
#   Desde `backend/`: python -m scripts.benchmark_report
#   Desde la raiz del repo: python -m backend.scripts.benchmark_report

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tests.fixtures.legal_benchmark_cases import LEGAL_BENCHMARK_CASES
from tests.legal_benchmark_support import evaluate_benchmark_case


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke benchmark report para AILEX.")
    parser.add_argument("--fail-only", action="store_true", help="Muestra solo casos fallidos en la tabla principal.")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emite el reporte estructurado en JSON.")
    parser.add_argument("--quiet", action="store_true", help="Reduce la salida textual al minimo util.")
    parser.add_argument("--compare", type=str, help="Ruta a un JSON previo generado con --json para comparar corridas.")
    parser.add_argument("--limit", type=int, default=None, help="Limita la cantidad de filas o cambios mostrados en modo texto.")
    return parser.parse_args(argv)


def _truncate(text: Any, width: int) -> str:
    value = str(text)
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def _format_float(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "-"


def _ordered_evaluations(evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        case_index = int(item.get("case_index", 0))
        if not item["passed"]:
            return (0, -len(item["failures"]), -abs(float(item["delta_confidence"])), item["case"].get("id", ""))
        return (1, case_index, item["case"].get("id", ""))

    return sorted(evaluations, key=sort_key)


def _build_case_result(evaluation: dict[str, Any]) -> dict[str, Any]:
    case = evaluation["case"]
    decision = evaluation["payload"]["legal_decision"]
    expected = case["expected"]
    return {
        "id": case["id"],
        "title": case["title"],
        "expected_case_strength_label": expected["case_strength_label"],
        "real_case_strength_label": decision.get("case_strength_label"),
        "expected_strategic_posture": expected["strategic_posture"],
        "real_strategic_posture": decision.get("strategic_posture"),
        "confidence_score": float(decision.get("confidence_score", 0.0)),
        "dominant_factor": decision.get("dominant_factor"),
        "caution_level": decision.get("caution_level"),
        "result": "OK" if evaluation["passed"] else "FAIL",
        "failures": list(evaluation["failures"]),
        "delta_confidence": float(evaluation["delta_confidence"]),
        "case_index": int(evaluation.get("case_index", 0)),
    }


def _build_row(case_result: dict[str, Any]) -> dict[str, str]:
    return {
        "id": case_result["id"],
        "title": case_result["title"],
        "exp_strength": str(case_result["expected_case_strength_label"] or "-"),
        "real_strength": str(case_result["real_case_strength_label"] or "-"),
        "exp_posture": str(case_result["expected_strategic_posture"] or "-"),
        "real_posture": str(case_result["real_strategic_posture"] or "-"),
        "confidence": _format_float(case_result["confidence_score"]),
        "delta_conf": _format_float(case_result["delta_confidence"]),
        "factor": str(case_result["dominant_factor"] or "-"),
        "caution": str(case_result["caution_level"] or "-"),
        "result": str(case_result["result"] or "-"),
    }


def _column_widths(rows: list[dict[str, str]], headers: dict[str, str]) -> dict[str, int]:
    widths: dict[str, int] = {key: len(label) for key, label in headers.items()}
    for row in rows:
        for key, value in row.items():
            widths[key] = max(widths.get(key, 0), len(value))
    return widths


def _render_table(rows: list[dict[str, str]]) -> str:
    headers = {
        "id": "id",
        "title": "title",
        "exp_strength": "exp_strength",
        "real_strength": "real_strength",
        "exp_posture": "exp_posture",
        "real_posture": "real_posture",
        "confidence": "confidence",
        "delta_conf": "delta_conf",
        "factor": "factor",
        "caution": "caution",
        "result": "result",
    }
    clipped_rows: list[dict[str, str]] = []
    for row in rows:
        clipped_rows.append(
            {
                "id": _truncate(row["id"], 34),
                "title": _truncate(row["title"], 42),
                "exp_strength": _truncate(row["exp_strength"], 12),
                "real_strength": _truncate(row["real_strength"], 13),
                "exp_posture": _truncate(row["exp_posture"], 13),
                "real_posture": _truncate(row["real_posture"], 13),
                "confidence": _truncate(row["confidence"], 10),
                "delta_conf": _truncate(row["delta_conf"], 10),
                "factor": _truncate(row["factor"], 15),
                "caution": _truncate(row["caution"], 10),
                "result": _truncate(row["result"], 6),
            }
        )

    widths = _column_widths(clipped_rows, headers)
    ordered_keys = list(headers)
    separator = "-+-".join("-" * widths[key] for key in ordered_keys)
    lines = [
        " | ".join(headers[key].ljust(widths[key]) for key in ordered_keys),
        separator,
    ]
    for row in clipped_rows:
        lines.append(" | ".join(row[key].ljust(widths[key]) for key in ordered_keys))
    return "\n".join(lines)


def _distribution_text(data: Mapping[str, int] | Counter[str]) -> str:
    if not data:
        return "-"
    return ", ".join(f"{key}: {int(data[key])}" for key in sorted(data))


def _limit_items(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None or limit < 0:
        return items
    return items[:limit]


def _build_summary(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_results)
    passed = sum(1 for item in case_results if item["result"] == "OK")
    failed = total - passed
    average_confidence = (
        sum(float(item["confidence_score"]) for item in case_results) / total if total else 0.0
    )
    average_delta_confidence = (
        sum(float(item["delta_confidence"]) for item in case_results) / total if total else 0.0
    )
    strategic_posture_distribution = Counter(str(item["real_strategic_posture"] or "-") for item in case_results)
    case_strength_label_distribution = Counter(str(item["real_case_strength_label"] or "-") for item in case_results)
    failed_case_ids = [item["id"] for item in case_results if item["result"] == "FAIL"]
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "average_confidence": average_confidence,
        "average_delta_confidence": average_delta_confidence,
        "strategic_posture_distribution": dict(sorted(strategic_posture_distribution.items())),
        "case_strength_label_distribution": dict(sorted(case_strength_label_distribution.items())),
        "failed_case_ids": failed_case_ids,
    }


def _load_comparison_file(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _changed_case_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    change_priority = {"regressed": 0, "improved": 1, "changed": 2, "new": 3}
    fail_transition_priority = 0 if item.get("previous_result") == "OK" and item.get("current_result") == "FAIL" else 1
    return (
        change_priority.get(str(item.get("change_type")), 9),
        fail_transition_priority,
        -abs(float(item.get("delta_confidence_change", 0.0))),
        item["id"],
    )


def _split_changed_cases(changed_cases: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "regressed": [],
        "improved": [],
        "changed": [],
        "new": [],
    }
    for item in changed_cases:
        groups.setdefault(str(item.get("change_type")), []).append(item)
    for key in groups:
        groups[key] = sorted(groups[key], key=_changed_case_sort_key)
    return groups


def _build_comparison(current_cases: list[dict[str, Any]], current_summary: dict[str, Any], previous_run: dict[str, Any]) -> dict[str, Any]:
    previous_cases = {str(item.get("id")): item for item in previous_run.get("cases", [])}
    previous_summary = {
        "total": int(previous_run.get("total", 0)),
        "passed": int(previous_run.get("passed", 0)),
        "failed": int(previous_run.get("failed", 0)),
        "average_confidence": float(previous_run.get("average_confidence", 0.0)),
        "average_delta_confidence": float(previous_run.get("average_delta_confidence", 0.0)),
    }
    changed_cases: list[dict[str, Any]] = []
    improved = 0
    regressed = 0

    for case in current_cases:
        previous = previous_cases.get(case["id"])
        if previous is None:
            changed_cases.append(
                {
                    "id": case["id"],
                    "change_type": "new",
                    "current_result": case["result"],
                    "current_confidence_score": float(case["confidence_score"]),
                    "current_delta_confidence": float(case["delta_confidence"]),
                    "delta_confidence_change": float(case["delta_confidence"]),
                    "confidence_drift": abs(float(case["delta_confidence"])) >= 0.10,
                }
            )
            continue

        result_changed = str(previous.get("result")) != case["result"]
        posture_changed = previous.get("real_strategic_posture") != case["real_strategic_posture"]
        strength_changed = previous.get("real_case_strength_label") != case["real_case_strength_label"]
        confidence_change = float(case["confidence_score"]) - float(previous.get("confidence_score", 0.0))
        delta_confidence_change = float(case["delta_confidence"]) - float(previous.get("delta_confidence", 0.0))

        if not any((result_changed, posture_changed, strength_changed, abs(confidence_change) > 1e-12, abs(delta_confidence_change) > 1e-12)):
            continue

        if previous.get("result") == "FAIL" and case["result"] == "OK":
            change_type = "improved"
            improved += 1
        elif previous.get("result") == "OK" and case["result"] == "FAIL":
            change_type = "regressed"
            regressed += 1
        else:
            change_type = "changed"

        confidence_drift = abs(delta_confidence_change) >= 0.10

        changed_cases.append(
            {
                "id": case["id"],
                "change_type": change_type,
                "previous_result": previous.get("result"),
                "current_result": case["result"],
                "previous_confidence_score": float(previous.get("confidence_score", 0.0)),
                "current_confidence_score": float(case["confidence_score"]),
                "confidence_change": confidence_change,
                "previous_delta_confidence": float(previous.get("delta_confidence", 0.0)),
                "current_delta_confidence": float(case["delta_confidence"]),
                "delta_confidence_change": delta_confidence_change,
                "confidence_drift": confidence_drift,
                "previous_strategic_posture": previous.get("real_strategic_posture"),
                "current_strategic_posture": case["real_strategic_posture"],
                "previous_case_strength_label": previous.get("real_case_strength_label"),
                "current_case_strength_label": case["real_case_strength_label"],
            }
        )

    changed_cases = sorted(changed_cases, key=_changed_case_sort_key)
    drift_cases = sum(1 for item in changed_cases if item.get("confidence_drift"))
    groups = _split_changed_cases(changed_cases)

    return {
        "previous": previous_summary,
        "current": {
            "total": current_summary["total"],
            "passed": current_summary["passed"],
            "failed": current_summary["failed"],
            "average_confidence": current_summary["average_confidence"],
            "average_delta_confidence": current_summary["average_delta_confidence"],
        },
        "delta": {
            "passed": current_summary["passed"] - previous_summary["passed"],
            "failed": current_summary["failed"] - previous_summary["failed"],
            "average_confidence": current_summary["average_confidence"] - previous_summary["average_confidence"],
            "average_delta_confidence": current_summary["average_delta_confidence"] - previous_summary["average_delta_confidence"],
        },
        "improved_cases": improved,
        "regressed_cases": regressed,
        "drift_cases": drift_cases,
        "changed_cases": changed_cases,
        "top_regressions": groups["regressed"],
        "top_improvements": groups["improved"],
        "other_changed_cases": groups["changed"] + groups["new"],
    }


def build_report_data(fail_only: bool = False, compare_path: str | None = None) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    for index, case in enumerate(LEGAL_BENCHMARK_CASES):
        evaluation = evaluate_benchmark_case(case)
        evaluation["case_index"] = index
        evaluations.append(evaluation)

    evaluations = _ordered_evaluations(evaluations)
    case_results = [_build_case_result(item) for item in evaluations]
    summary = _build_summary(case_results)
    visible_case_results = [item for item in case_results if item["result"] == "FAIL"] if fail_only else case_results

    report = {
        "summary": summary,
        "cases": case_results,
        "visible_cases": visible_case_results,
        "fail_only": fail_only,
    }
    if compare_path:
        report["comparison"] = _build_comparison(case_results, summary, _load_comparison_file(compare_path))
    return report


def _print_summary(summary: dict[str, Any]) -> None:
    print("Resumen")
    print("-------")
    print(f"total cases: {summary['total']}")
    print(f"passed: {summary['passed']}")
    print(f"failed: {summary['failed']}")
    print(f"average confidence: {summary['average_confidence']:.3f}")
    print(f"average delta confidence: {summary['average_delta_confidence']:.3f}")
    print(f"strategic_posture distribution: {_distribution_text(summary['strategic_posture_distribution'])}")
    print(f"case_strength_label distribution: {_distribution_text(summary['case_strength_label_distribution'])}")
    print(f"failed cases: {', '.join(summary['failed_case_ids']) if summary['failed_case_ids'] else '-'}")


def _print_change_group(title: str, items: list[dict[str, Any]], limit: int | None) -> None:
    if not items:
        return
    print(title)
    for item in _limit_items(items, limit):
        drift_tag = " | DRIFT" if item.get("confidence_drift") else ""
        print(
            f"- {item['id']} | {item['change_type']} | "
            f"result {item.get('previous_result', '-')} -> {item.get('current_result', '-')}"
            f" | delta_conf_change={_format_float(item.get('delta_confidence_change'))}"
            f"{drift_tag}"
        )


def _print_comparison(comparison: dict[str, Any], quiet: bool = False, limit: int | None = None) -> None:
    print("\nComparación")
    print("-----------")
    print(
        "passed delta:"
        f" {comparison['delta']['passed']:+d} | failed delta: {comparison['delta']['failed']:+d}"
    )
    print(
        "average confidence delta:"
        f" {_format_float(comparison['delta']['average_confidence'])}"
        f" | average delta confidence delta: {_format_float(comparison['delta']['average_delta_confidence'])}"
    )
    drift_count = sum(1 for item in comparison["changed_cases"] if item.get("confidence_drift"))
    print(
        "changed cases:"
        f" {len(comparison['changed_cases'])}"
        f" | improved: {comparison['improved_cases']}"
        f" | regressed: {comparison['regressed_cases']}"
        f" | confidence_drift: {comparison.get('drift_cases', 0)}"
    )
    if quiet:
        return

    if comparison["top_regressions"]:
        print()
        _print_change_group("Top regressions", comparison["top_regressions"], limit)
    if comparison["top_improvements"]:
        print()
        _print_change_group("Top improvements", comparison["top_improvements"], limit)
    if comparison["other_changed_cases"]:
        print()
        _print_change_group("Other changed cases", comparison["other_changed_cases"], limit)


def _print_text_report(report: dict[str, Any], quiet: bool = False, limit: int | None = None) -> None:
    summary = report["summary"]
    visible_case_results = report["visible_cases"]
    rows = [_build_row(item) for item in _limit_items(visible_case_results, limit)]

    if not quiet:
        print("AILEX Legal Benchmark Report")
        print("============================")
        if rows:
            print(_render_table(rows))
        elif report["fail_only"]:
            print("No failed cases")
        else:
            print("No cases to display")

        print()

    _print_summary(summary)

    if "comparison" in report:
        _print_comparison(report["comparison"], quiet=quiet, limit=limit)

    if quiet or summary["failed"] == 0:
        return

    print("\nCasos fallidos")
    print("--------------")
    for item in _limit_items([case for case in report["cases"] if case["result"] == "FAIL"], limit):
        print(f"- {item['id']} | {item['title']}")
        print(
            "  Esperado:"
            f" strength={item['expected_case_strength_label']},"
            f" posture={item['expected_strategic_posture']}"
        )
        print(
            "  Real:"
            f" strength={item['real_case_strength_label']},"
            f" posture={item['real_strategic_posture']},"
            f" factor={item['dominant_factor']},"
            f" confidence={_format_float(item['confidence_score'])},"
            f" delta_conf={_format_float(item['delta_confidence'])},"
            f" caution={item['caution_level']}"
        )
        for failure in item["failures"]:
            print(f"  - {failure}")


def _emit_json_report(report: dict[str, Any]) -> None:
    payload = {
        **report["summary"],
        "cases": report["cases"],
    }
    if "comparison" in report:
        payload["comparison"] = report["comparison"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report_data(fail_only=args.fail_only, compare_path=args.compare)
    if args.json_output:
        _emit_json_report(report)
    else:
        _print_text_report(report, quiet=args.quiet, limit=args.limit)
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
