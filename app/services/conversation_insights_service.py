from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.conversation_observability_service import CONVERSATION_LOG_PATH

ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CONVERSATION_LOG_PATH = ROOT_DIR / "logs" / "conversations.jsonl"
_TOP_N = 5
_MIN_DOMAIN_SAMPLE = 2
_HIGH_FRICTION_SCORE = 2.0
_SLOW_TURNS_TO_ADVICE = 3.0
_REPEATED_QUESTION_THRESHOLD = 2


def load_conversation_logs(
    *,
    log_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    resolved_path = Path(log_path) if log_path is not None else DEFAULT_CONVERSATION_LOG_PATH
    if not resolved_path.exists():
        return []

    turns: list[dict[str, Any]] = []
    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    turns.append(_normalize_turn(payload))
    except Exception:
        return []

    turns.sort(key=lambda item: (_clean_text(item.get("conversation_id")), int(item.get("turn_number") or 0)))
    return turns


def group_turns_by_conversation(turns: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for turn in turns or []:
        safe_turn = _normalize_turn(turn)
        conversation_id = _clean_text(safe_turn.get("conversation_id")) or "unknown"
        grouped[conversation_id].append(safe_turn)

    for conversation_id in list(grouped.keys()):
        grouped[conversation_id] = sorted(
            grouped[conversation_id],
            key=lambda item: int(item.get("turn_number") or 0),
        )
    return dict(grouped)


def calculate_metrics(
    turns: list[dict[str, Any]] | None,
    grouped_conversations: dict[str, list[dict[str, Any]]] | None = None,
    *,
    top_n: int = _TOP_N,
) -> dict[str, Any]:
    normalized_turns = [_normalize_turn(item) for item in (turns or [])]
    grouped = grouped_conversations or group_turns_by_conversation(normalized_turns)
    total_turns = len(normalized_turns)
    total_conversations = len(grouped)

    clarification_turns = sum(1 for turn in normalized_turns if _clean_text(turn.get("output_mode")) == "clarification")
    advice_turns = sum(1 for turn in normalized_turns if _clean_text(turn.get("output_mode")) == "advice")
    clarification_ratio = round(clarification_turns / max(total_turns, 1), 4)
    advice_ratio = round(advice_turns / max(total_turns, 1), 4)
    clarification_to_advice_ratio = round(clarification_turns / max(advice_turns, 1), 4) if clarification_turns else 0.0

    conversations_with_progress = 0
    conversations_without_progress = 0
    total_new_facts = 0
    repeated_questions = Counter()
    signal_counter = Counter()
    missing_counter = Counter()
    added_fact_counter = Counter()
    domain_missing_counter: dict[str, Counter[str]] = defaultdict(Counter)
    domain_repeated_questions: dict[str, Counter[str]] = defaultdict(Counter)
    domain_signal_counter: dict[str, Counter[str]] = defaultdict(Counter)
    domain_friction_scores = Counter()
    no_progress_conversations: list[dict[str, Any]] = []
    loop_conversations: list[dict[str, Any]] = []
    domain_transition_turns: dict[str, list[int]] = defaultdict(list)
    no_progress_after_turn_3 = 0

    domain_summary: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "conversation_count": 0,
        "turn_count": 0,
        "clarification_turns": 0,
        "advice_turns": 0,
        "loop_count": 0,
        "repeat_question_count": 0,
        "no_progress_count": 0,
        "unnecessary_clarification_count": 0,
        "domain_shift_count": 0,
        "turns_to_first_advice": [],
    })

    for conversation_id, conversation_turns in grouped.items():
        case_domain = _conversation_domain(conversation_turns)
        if case_domain:
            domain_summary[case_domain]["conversation_count"] += 1

        conversation_has_progress = False
        conversation_no_progress_count = 0
        conversation_loop_count = 0
        first_advice_turn = None

        for turn in conversation_turns:
            domain = _clean_text(turn.get("case_domain")) or case_domain
            signals = _as_dict(turn.get("signals"))
            progress = _as_dict(turn.get("progress"))
            question = _clean_text(turn.get("question_asked"))
            turn_number = _safe_int(turn.get("turn_number"))
            output_mode = _clean_text(turn.get("output_mode"))

            if domain:
                domain_summary[domain]["turn_count"] += 1

            if output_mode == "clarification":
                if domain:
                    domain_summary[domain]["clarification_turns"] += 1
            elif output_mode == "advice":
                if first_advice_turn is None:
                    first_advice_turn = turn_number
                if domain:
                    domain_summary[domain]["advice_turns"] += 1

            delta = _safe_int(progress.get("delta"))
            total_new_facts += delta
            if bool(progress.get("has_progress")):
                conversation_has_progress = True
            elif turn_number >= 3:
                no_progress_after_turn_3 += 1

            for fact_key in _as_str_list(progress.get("new_keys")):
                added_fact_counter[fact_key] += 1

            for missing_item in _as_str_list(turn.get("missing_information")):
                missing_counter[missing_item] += 1
                if domain:
                    domain_missing_counter[domain][missing_item] += 1

            for signal_name, active in signals.items():
                if not bool(active):
                    continue
                signal_counter[signal_name] += 1
                if domain:
                    domain_signal_counter[domain][signal_name] += 1

            if bool(signals.get("repeat_question")) and question:
                repeated_questions[question] += 1
                if domain:
                    domain_repeated_questions[domain][question] += 1
                    domain_summary[domain]["repeat_question_count"] += 1

            if bool(signals.get("no_progress")):
                conversation_no_progress_count += 1
                if domain:
                    domain_summary[domain]["no_progress_count"] += 1
                    domain_friction_scores[domain] += 1

            if bool(signals.get("loop_detected")):
                conversation_loop_count += 1
                if domain:
                    domain_summary[domain]["loop_count"] += 1
                    domain_friction_scores[domain] += 3

            if bool(signals.get("unnecessary_clarification")) and domain:
                domain_summary[domain]["unnecessary_clarification_count"] += 1
                domain_friction_scores[domain] += 1

            if bool(signals.get("domain_shift")) and domain:
                domain_summary[domain]["domain_shift_count"] += 1
                domain_friction_scores[domain] += 1

        if conversation_has_progress:
            conversations_with_progress += 1
        else:
            conversations_without_progress += 1

        if conversation_no_progress_count:
            no_progress_conversations.append({
                "conversation_id": conversation_id,
                "count": conversation_no_progress_count,
                "case_domain": case_domain,
                "turns": len(conversation_turns),
            })

        if conversation_loop_count:
            loop_conversations.append({
                "conversation_id": conversation_id,
                "loop_turns": conversation_loop_count,
                "case_domain": case_domain,
                "turns": len(conversation_turns),
            })

        if case_domain and first_advice_turn is not None:
            domain_transition_turns[case_domain].append(first_advice_turn)
            domain_summary[case_domain]["turns_to_first_advice"].append(first_advice_turn)

    domain_metrics = []
    for domain, values in domain_summary.items():
        avg_turns_to_first_advice = round(
            sum(values["turns_to_first_advice"]) / max(len(values["turns_to_first_advice"]), 1),
            2,
        ) if values["turns_to_first_advice"] else None
        friction_score = (
            values["repeat_question_count"]
            + values["no_progress_count"]
            + (values["loop_count"] * 2)
            + values["unnecessary_clarification_count"]
            + values["domain_shift_count"]
        )
        domain_metrics.append({
            "case_domain": domain,
            "conversation_count": values["conversation_count"],
            "turn_count": values["turn_count"],
            "clarification_turns": values["clarification_turns"],
            "advice_turns": values["advice_turns"],
            "avg_turns_to_first_advice": avg_turns_to_first_advice,
            "loop_count": values["loop_count"],
            "repeat_question_count": values["repeat_question_count"],
            "no_progress_count": values["no_progress_count"],
            "unnecessary_clarification_count": values["unnecessary_clarification_count"],
            "domain_shift_count": values["domain_shift_count"],
            "friction_score": friction_score,
            "top_missing_information": _counter_to_ranked_list(domain_missing_counter[domain], top_n=3),
        })

    domain_metrics.sort(key=lambda item: (-int(item["friction_score"]), item["case_domain"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "conversation_insights_service",
        "log_path": str(DEFAULT_CONVERSATION_LOG_PATH if grouped_conversations is not None else (Path(CONVERSATION_LOG_PATH) if CONVERSATION_LOG_PATH else DEFAULT_CONVERSATION_LOG_PATH)),
        "has_data": bool(total_turns),
        "volume": {
            "total_conversations": total_conversations,
            "total_turns": total_turns,
            "avg_turns_per_conversation": round(total_turns / max(total_conversations, 1), 2),
        },
        "output_modes": {
            "clarification_turns": clarification_turns,
            "advice_turns": advice_turns,
            "clarification_ratio": clarification_ratio,
            "advice_ratio": advice_ratio,
            "clarification_to_advice_ratio": clarification_to_advice_ratio,
        },
        "progress": {
            "conversations_with_progress": conversations_with_progress,
            "conversations_without_progress": conversations_without_progress,
            "avg_new_facts_per_turn": round(total_new_facts / max(total_turns, 1), 4),
            "top_no_progress_conversations": sorted(
                no_progress_conversations,
                key=lambda item: (-int(item["count"]), item["conversation_id"]),
            )[:top_n],
            "no_progress_after_turn_3_count": no_progress_after_turn_3,
        },
        "friction": {
            "most_repeated_questions": _counter_to_ranked_list(repeated_questions, top_n=top_n, key_name="question"),
            "loop_conversations": sorted(
                loop_conversations,
                key=lambda item: (-int(item["loop_turns"]), item["conversation_id"]),
            )[:top_n],
            "top_signals": _counter_to_ranked_list(signal_counter, top_n=top_n, key_name="signal"),
            "top_friction_domains": [
                {
                    "case_domain": item["case_domain"],
                    "friction_score": item["friction_score"],
                    "conversation_count": item["conversation_count"],
                    "repeat_question_count": item["repeat_question_count"],
                    "loop_count": item["loop_count"],
                    "no_progress_count": item["no_progress_count"],
                }
                for item in domain_metrics[:top_n]
            ],
            "domain_repeated_questions": {
                domain: _counter_to_ranked_list(counter, top_n=top_n, key_name="question")
                for domain, counter in domain_repeated_questions.items()
            },
        },
        "stability": {
            "domain_shift_count": int(signal_counter.get("domain_shift", 0)),
            "unnecessary_clarification_count": int(signal_counter.get("unnecessary_clarification", 0)),
        },
        "facts_and_missing": {
            "top_missing_information": _counter_to_ranked_list(missing_counter, top_n=top_n, key_name="item"),
            "top_added_facts": _counter_to_ranked_list(added_fact_counter, top_n=top_n, key_name="fact"),
            "missing_by_domain": {
                domain: _counter_to_ranked_list(counter, top_n=top_n, key_name="item")
                for domain, counter in domain_missing_counter.items()
            },
        },
        "domains": {
            "metrics": domain_metrics,
            "avg_turns_to_first_advice": {
                domain: round(sum(values) / max(len(values), 1), 2)
                for domain, values in domain_transition_turns.items()
            },
        },
    }


def generate_insights(metrics: dict[str, Any] | None) -> list[dict[str, Any]]:
    safe_metrics = dict(metrics or {})
    if not bool(safe_metrics.get("has_data")):
        return [
            _build_insight(
                code="no_conversation_data",
                severity="low",
                message="Todavia no hay telemetria conversacional suficiente para generar insights.",
                evidence={},
                recommendation="seguir registrando turnos antes de interpretar el flujo",
            )
        ]

    insights: list[dict[str, Any]] = []
    friction = _as_dict(safe_metrics.get("friction"))
    progress = _as_dict(safe_metrics.get("progress"))
    domains = _as_dict(safe_metrics.get("domains"))
    domain_metrics = domains.get("metrics") or []

    top_repeated = (friction.get("most_repeated_questions") or [{}])[0]
    repeated_question = _clean_text(_as_dict(top_repeated).get("question"))
    repeated_count = _safe_int(_as_dict(top_repeated).get("count"))
    if repeated_question and repeated_count >= _REPEATED_QUESTION_THRESHOLD:
        insights.append(_build_insight(
            code="repeated_question_hotspot",
            severity="high" if repeated_count >= 4 else "medium",
            message=f'Se repite demasiado la pregunta "{repeated_question}" ({repeated_count} veces).',
            evidence={"question": repeated_question, "count": repeated_count},
            recommendation="revisar esa pregunta, su redaccion o la condicion que la vuelve a disparar",
        ))

    no_progress_after_turn_3 = _safe_int(progress.get("no_progress_after_turn_3_count"))
    if no_progress_after_turn_3 > 0:
        insights.append(_build_insight(
            code="no_progress_after_turn_3",
            severity="high" if no_progress_after_turn_3 >= 3 else "medium",
            message=f"Hay {no_progress_after_turn_3} turnos sin progreso real despues del turno 3.",
            evidence={"no_progress_after_turn_3_count": no_progress_after_turn_3},
            recommendation="acortar clarification o cambiar la secuencia de preguntas cuando no entren facts nuevos",
        ))

    for domain_item in domain_metrics:
        safe_domain_item = _as_dict(domain_item)
        domain = _clean_text(safe_domain_item.get("case_domain"))
        conversation_count = _safe_int(safe_domain_item.get("conversation_count"))
        friction_score = _safe_float(safe_domain_item.get("friction_score"))
        avg_turns_to_first_advice = _safe_float(safe_domain_item.get("avg_turns_to_first_advice"))
        if not domain or conversation_count < _MIN_DOMAIN_SAMPLE:
            continue

        domain_questions = friction.get("domain_repeated_questions") or {}
        top_domain_question = _top_ranked_item(_as_dict(domain_questions).get(domain), key_name="question")
        if friction_score >= _HIGH_FRICTION_SCORE and top_domain_question:
            question = _clean_text(top_domain_question.get("question"))
            question_count = _safe_int(top_domain_question.get("count"))
            insights.append(_build_insight(
                code="domain_friction_question",
                severity="high" if friction_score >= 4 else "medium",
                message=f'El dominio {domain} muestra friccion alta en preguntas sobre "{question}" ({question_count} repeticiones).',
                evidence={
                    "case_domain": domain,
                    "friction_score": friction_score,
                    "question": question,
                    "count": question_count,
                },
                recommendation="revisar la logica de resolucion de esa pregunta o moverla antes/despues en el flujo",
            ))

        if domain == "divorcio" and top_domain_question:
            question = _clean_text(top_domain_question.get("question"))
            if re.search(r"\bhijos?\b", question, flags=re.IGNORECASE):
                insights.append(_build_insight(
                    code="divorcio_hijos_friction",
                    severity="high",
                    message="El dominio divorcio muestra alta friccion en preguntas sobre hijos.",
                    evidence={
                        "case_domain": domain,
                        "question": question,
                        "count": _safe_int(top_domain_question.get("count")),
                    },
                    recommendation="simplificar la deteccion de hijos y evitar repreguntar cuando el fact ya esta resuelto",
                ))

        if avg_turns_to_first_advice >= _SLOW_TURNS_TO_ADVICE:
            insights.append(_build_insight(
                code="slow_clarification_to_advice",
                severity="medium",
                message=f"La transicion clarification → advice tarda demasiado en {domain} (promedio {avg_turns_to_first_advice} turnos).",
                evidence={
                    "case_domain": domain,
                    "avg_turns_to_first_advice": avg_turns_to_first_advice,
                    "conversation_count": conversation_count,
                },
                recommendation="reducir la cantidad de aclaraciones previas antes de entregar orientacion util",
            ))

    top_missing_by_domain = _build_missing_by_domain_insights(safe_metrics)
    insights.extend(top_missing_by_domain)

    insights.sort(key=_insight_sort_key)
    deduped: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for item in insights:
        code = _clean_text(item.get("code"))
        if code in seen_codes:
            continue
        seen_codes.add(code)
        deduped.append(item)
    return deduped


def build_snapshot(
    *,
    log_path: str | Path | None = None,
    top_n: int = _TOP_N,
) -> dict[str, Any]:
    turns = load_conversation_logs(log_path=log_path)
    grouped = group_turns_by_conversation(turns)
    metrics = calculate_metrics(turns, grouped, top_n=top_n)
    insights = generate_insights(metrics)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "conversation_insights_service",
        "log_path": str(Path(log_path) if log_path is not None else DEFAULT_CONVERSATION_LOG_PATH),
        "has_data": bool(turns),
        "metrics": metrics,
        "insights": insights,
    }


def _build_missing_by_domain_insights(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    facts_and_missing = _as_dict(metrics.get("facts_and_missing"))
    missing_by_domain = _as_dict(facts_and_missing.get("missing_by_domain"))
    insights: list[dict[str, Any]] = []
    for domain, items in missing_by_domain.items():
        top_item = _top_ranked_item(items, key_name="item")
        if not top_item:
            continue
        count = _safe_int(top_item.get("count"))
        if count < 2:
            continue
        missing_item = _clean_text(top_item.get("item"))
        insights.append(_build_insight(
            code=f"missing_hotspot_{domain}",
            severity="medium",
            message=f'En {domain} falta con frecuencia "{missing_item}" ({count} apariciones).',
            evidence={"case_domain": domain, "item": missing_item, "count": count},
            recommendation="mejorar la captura temprana de ese dato o volverlo mas visible en la UX",
        ))
    return insights


def _normalize_turn(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload or {})
    safe["conversation_id"] = _clean_text(safe.get("conversation_id"))
    safe["turn_number"] = _safe_int(safe.get("turn_number"))
    safe["output_mode"] = _clean_text(safe.get("output_mode"))
    safe["question_asked"] = _clean_text(safe.get("question_asked"))
    safe["quick_start"] = _clean_text(safe.get("quick_start"))
    safe["case_domain"] = _clean_text(safe.get("case_domain"))
    safe["facts_detected"] = _as_dict(safe.get("facts_detected"))
    safe["missing_information"] = _as_str_list(safe.get("missing_information"))
    safe["progress"] = _as_dict(safe.get("progress"))
    safe["signals"] = _as_dict(safe.get("signals"))
    return safe


def _conversation_domain(turns: list[dict[str, Any]]) -> str:
    counter = Counter(
        _clean_text(turn.get("case_domain"))
        for turn in turns
        if _clean_text(turn.get("case_domain"))
    )
    return counter.most_common(1)[0][0] if counter else ""


def _counter_to_ranked_list(
    counter: Counter[str] | dict[str, int],
    *,
    top_n: int,
    key_name: str = "value",
) -> list[dict[str, Any]]:
    resolved = Counter(counter or {})
    return [
        {key_name: key, "count": int(count)}
        for key, count in resolved.most_common(top_n)
    ]


def _top_ranked_item(items: Any, *, key_name: str) -> dict[str, Any]:
    if not isinstance(items, list) or not items:
        return {}
    first = items[0]
    if not isinstance(first, dict):
        return {}
    if not _clean_text(first.get(key_name)):
        return {}
    return dict(first)


def _build_insight(
    *,
    code: str,
    severity: str,
    message: str,
    evidence: dict[str, Any],
    recommendation: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "type": "conversation_insight",
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _insight_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    order = {"high": 0, "medium": 1, "low": 2}
    return (order.get(_clean_text(item.get("severity")), 3), _clean_text(item.get("code")))


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
