from __future__ import annotations

from collections import defaultdict
from typing import Any


class AdaptiveLearningEngine:
    def __init__(self, *, min_evidence_count: int = 3) -> None:
        self.min_evidence_count = max(3, int(min_evidence_count or 3))

    def analyze(self, *, summary: dict, recent_logs: list[dict]) -> list[dict]:
        recommendations: list[dict] = []
        recommendations.extend(self._analyze_negative_feedback_clusters(recent_logs))
        recommendations.extend(self._analyze_domain_mismatch_patterns(recent_logs))
        recommendations.extend(self._analyze_strategy_mismatch_patterns(recent_logs))
        recommendations.extend(self._analyze_feedback_backed_version_alerts(recent_logs))
        recommendations.extend(self._analyze_high_fallback_domains(recent_logs))
        recommendations.extend(self._analyze_high_severity_versions(summary))
        recommendations.extend(self._analyze_ambiguous_domains(recent_logs))
        recommendations.extend(self._analyze_low_confidence(summary, recent_logs))
        recommendations.extend(self._analyze_low_feedback_domains(recent_logs))
        recommendations.extend(self._analyze_strategy_corrections(recent_logs))
        recommendations.extend(self._analyze_domain_corrections(recent_logs))
        recommendations.extend(self._analyze_feedback_version_alerts(recent_logs))
        return recommendations

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _feedback_logs(self, recent_logs: list[dict]) -> list[dict]:
        result: list[dict] = []
        for log in recent_logs:
            review_feedback = dict((log.get("quality_flags_json") or {}).get("review_feedback") or {})
            if (
                log.get("feedback_submitted_at")
                or log.get("reviewed_by_user")
                or log.get("reviewed_by_admin")
                or log.get("user_feedback_score") is not None
                or log.get("is_user_feedback_positive") is not None
                or log.get("corrected_domain")
                or log.get("corrected_strategy_mode")
                or log.get("feedback_comment")
                or review_feedback
            ):
                result.append(log)
        return result

    def _review_feedback(self, log: dict[str, Any]) -> dict[str, Any]:
        return dict((log.get("quality_flags_json") or {}).get("review_feedback") or {})

    def _is_positive_confirmation(self, log: dict[str, Any]) -> bool:
        review_feedback = self._review_feedback(log)
        return bool(review_feedback.get("feedback_is_positive_confirmation"))

    def _is_negative_feedback(self, log: dict[str, Any]) -> bool:
        review_feedback = self._review_feedback(log)
        return bool(review_feedback.get("feedback_is_negative"))

    def _has_domain_correction(self, log: dict[str, Any]) -> bool:
        review_feedback = self._review_feedback(log)
        return bool(review_feedback.get("feedback_has_domain_correction"))

    def _has_strategy_correction(self, log: dict[str, Any]) -> bool:
        review_feedback = self._review_feedback(log)
        return bool(review_feedback.get("feedback_has_strategy_correction"))

    def _impact_scope(self, *, affected_queries: int, total_queries: int) -> dict[str, Any]:
        percentage = 0.0
        if total_queries > 0:
            percentage = affected_queries / total_queries
        return {
            "affected_queries": int(affected_queries),
            "affected_percentage": round(percentage, 4),
        }

    def _score_recommendation_confidence(
        self,
        *,
        sample_size: int,
        issue_rate: float,
        delta: float = 0.0,
        sample_reference: int | None = None,
        delta_scale: float = 1.0,
    ) -> float:
        reference = max(sample_reference or (self.min_evidence_count * 4), 1)
        sample_factor = self._clamp(sample_size / reference, 0.0, 1.0)
        rate_factor = self._clamp(issue_rate, 0.0, 1.0)
        delta_factor = self._clamp(abs(delta) / max(delta_scale, 0.0001), 0.0, 1.0)
        confidence = 0.18 + (0.34 * sample_factor) + (0.30 * rate_factor) + (0.16 * delta_factor)
        return round(self._clamp(confidence, 0.0, 0.98), 4)

    def _score_recommendation_priority(
        self,
        *,
        confidence_score: float,
        affected_percentage: float,
        issue_rate: float = 0.0,
        delta: float = 0.0,
        delta_scale: float = 1.0,
    ) -> float:
        delta_factor = self._clamp(abs(delta) / max(delta_scale, 0.0001), 0.0, 1.0)
        issue_factor = self._clamp(max(issue_rate, delta_factor), 0.0, 1.0)
        priority = (0.45 * confidence_score) + (0.35 * affected_percentage) + (0.20 * issue_factor)
        return round(self._clamp(priority, 0.0, 1.0), 4)

    def _recommendation(
        self,
        *,
        event_type: str,
        title: str,
        description: str,
        evidence: dict[str, Any],
        proposed_changes: dict[str, Any],
        sample_size: int,
        issue_rate: float,
        delta: float = 0.0,
        delta_scale: float = 1.0,
    ) -> dict[str, Any]:
        confidence_score = self._score_recommendation_confidence(
            sample_size=sample_size,
            issue_rate=issue_rate,
            delta=delta,
            delta_scale=delta_scale,
        )
        priority = self._score_recommendation_priority(
            confidence_score=confidence_score,
            affected_percentage=float(evidence.get("affected_percentage") or 0.0),
            issue_rate=issue_rate,
            delta=delta,
            delta_scale=delta_scale,
        )
        return {
            "event_type": event_type,
            "title": title,
            "description": description,
            "confidence_score": confidence_score,
            "priority": priority,
            "evidence": evidence,
            "proposed_changes": proposed_changes,
        }

    def _analyze_negative_feedback_clusters(self, recent_logs: list[dict]) -> list[dict]:
        feedback_logs = self._feedback_logs(recent_logs)
        total_feedback = len(feedback_logs)
        domain_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "feedback_count": 0,
                "negative_count": 0,
                "positive_confirmation_count": 0,
                "strong_signal_count": 0,
            }
        )
        for log in feedback_logs:
            domain = str(log.get("case_domain") or "").strip().lower()
            if not domain:
                continue
            review_feedback = self._review_feedback(log)
            domain_stats[domain]["feedback_count"] += 1
            if self._is_negative_feedback(log):
                domain_stats[domain]["negative_count"] += 1
            if self._is_positive_confirmation(log):
                domain_stats[domain]["positive_confirmation_count"] += 1
            if bool(review_feedback.get("feedback_is_strong_signal")):
                domain_stats[domain]["strong_signal_count"] += 1

        recommendations: list[dict] = []
        for domain, stats in domain_stats.items():
            if stats["feedback_count"] < self.min_evidence_count:
                continue
            negative_feedback_rate = stats["negative_count"] / stats["feedback_count"]
            positive_confirmation_rate = stats["positive_confirmation_count"] / stats["feedback_count"]
            strong_signal_rate = stats["strong_signal_count"] / stats["feedback_count"]
            if negative_feedback_rate < 0.6 or strong_signal_rate < 0.6 or positive_confirmation_rate > 0.2:
                continue
            impact = self._impact_scope(affected_queries=stats["feedback_count"], total_queries=total_feedback)
            evidence = {
                "domain": domain,
                "feedback_count": stats["feedback_count"],
                "negative_feedback_count": stats["negative_count"],
                "negative_feedback_rate": round(negative_feedback_rate, 4),
                "positive_confirmation_count": stats["positive_confirmation_count"],
                "positive_confirmation_rate": round(positive_confirmation_rate, 4),
                "strong_signal_count": stats["strong_signal_count"],
                "strong_signal_rate": round(strong_signal_rate, 4),
                **impact,
            }
            recommendations.append(
                self._recommendation(
                    event_type="domain_review",
                    title=f"Revisar desempeno del dominio {domain}",
                    description=f"El dominio {domain} acumula feedback humano negativo y consistente.",
                    evidence=evidence,
                    proposed_changes={
                        "domain_review": {
                            "domain": domain,
                            "reason": "negative_feedback_cluster",
                        }
                    },
                    sample_size=stats["feedback_count"],
                    issue_rate=negative_feedback_rate,
                    delta=negative_feedback_rate - positive_confirmation_rate,
                    delta_scale=1.0,
                )
            )
        return recommendations

    def _analyze_domain_mismatch_patterns(self, recent_logs: list[dict]) -> list[dict]:
        feedback_logs = self._feedback_logs(recent_logs)
        total_feedback = len(feedback_logs)
        corrections: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"count": 0, "feedback_count": 0})
        domain_feedback_totals: dict[str, int] = defaultdict(int)
        for log in feedback_logs:
            original = str(log.get("case_domain") or "").strip().lower()
            corrected = str(log.get("corrected_domain") or "").strip().lower()
            review_feedback = self._review_feedback(log)
            if original:
                domain_feedback_totals[original] += 1
            if not original or not corrected or corrected == original:
                continue
            if not self._has_domain_correction(log):
                continue
            corrections[(original, corrected)]["count"] += 1

        recommendations: list[dict] = []
        for (original, corrected), stats in corrections.items():
            feedback_count = domain_feedback_totals.get(original, 0)
            if stats["count"] < self.min_evidence_count or feedback_count < self.min_evidence_count:
                continue
            correction_rate = stats["count"] / feedback_count
            if correction_rate < 0.6:
                continue
            impact = self._impact_scope(affected_queries=stats["count"], total_queries=total_feedback)
            evidence = {
                "original_case_domain": original,
                "corrected_domain": corrected,
                "correction_count": int(stats["count"]),
                "feedback_count": int(feedback_count),
                "correction_rate": round(correction_rate, 4),
                **impact,
            }
            recommendations.append(
                self._recommendation(
                    event_type="classification_review",
                    title=f"Revisar clasificacion de {original} hacia {corrected}",
                    description="El feedback humano corrige repetidamente el dominio clasificado por el orquestador.",
                    evidence=evidence,
                    proposed_changes={
                        "classification_review": {
                            "from_domain": original,
                            "to_domain": corrected,
                            "reason": "human_feedback_mismatch",
                        }
                    },
                    sample_size=feedback_count,
                    issue_rate=correction_rate,
                    delta=correction_rate - 0.6,
                    delta_scale=0.4,
                )
            )
        return recommendations

    def _analyze_strategy_mismatch_patterns(self, recent_logs: list[dict]) -> list[dict]:
        feedback_logs = self._feedback_logs(recent_logs)
        total_feedback = len(feedback_logs)
        corrections: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"count": 0})
        strategy_feedback_totals: dict[str, int] = defaultdict(int)
        for log in feedback_logs:
            original = str(log.get("strategy_mode") or "").strip().lower()
            corrected = str(log.get("corrected_strategy_mode") or "").strip().lower()
            review_feedback = self._review_feedback(log)
            if original:
                strategy_feedback_totals[original] += 1
            if not original or not corrected or corrected == original:
                continue
            if not self._has_strategy_correction(log):
                continue
            corrections[(original, corrected)]["count"] += 1

        recommendations: list[dict] = []
        for (original, corrected), stats in corrections.items():
            feedback_count = strategy_feedback_totals.get(original, 0)
            if stats["count"] < self.min_evidence_count or feedback_count < self.min_evidence_count:
                continue
            correction_rate = stats["count"] / feedback_count
            if correction_rate < 0.6:
                continue
            impact = self._impact_scope(affected_queries=stats["count"], total_queries=total_feedback)
            evidence = {
                "original_strategy_mode": original,
                "corrected_strategy_mode": corrected,
                "correction_count": int(stats["count"]),
                "feedback_count": int(feedback_count),
                "correction_rate": round(correction_rate, 4),
                **impact,
            }
            recommendations.append(
                self._recommendation(
                    event_type="strategy_recalibration",
                    title=f"Recalibrar estrategia {original} hacia {corrected}",
                    description="El feedback humano corrige repetidamente la estrategia sugerida hacia otra modalidad.",
                    evidence=evidence,
                    proposed_changes={
                        "strategy_review": {
                            "from_strategy_mode": original,
                            "to_strategy_mode": corrected,
                            "reason": "human_feedback_mismatch",
                        }
                    },
                    sample_size=feedback_count,
                    issue_rate=correction_rate,
                    delta=correction_rate - 0.6,
                    delta_scale=0.4,
                )
            )
        return recommendations

    def _analyze_feedback_backed_version_alerts(self, recent_logs: list[dict]) -> list[dict]:
        feedback_logs = self._feedback_logs(recent_logs)
        version_stats: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "count": 0,
                "negative_count": 0,
                "positive_confirmation_count": 0,
                "score_total": 0.0,
                "score_count": 0,
            }
        )
        for log in feedback_logs:
            version = str(log.get("orchestrator_version") or "").strip()
            score = log.get("user_feedback_score")
            if not version:
                continue
            version_stats[version]["count"] += 1
            if self._is_negative_feedback(log):
                version_stats[version]["negative_count"] += 1
            if self._is_positive_confirmation(log):
                version_stats[version]["positive_confirmation_count"] += 1
            if score is not None:
                version_stats[version]["score_total"] += float(score)
                version_stats[version]["score_count"] += 1

        ranking = sorted(
            [
                {
                    "version": version,
                    "count": int(stats["count"]),
                    "negative_feedback_rate": round(stats["negative_count"] / stats["count"], 4),
                    "positive_confirmation_rate": round(stats["positive_confirmation_count"] / stats["count"], 4),
                    "average_feedback_score": round(stats["score_total"] / stats["score_count"], 4)
                    if stats["score_count"] > 0 else 0.0,
                }
                for version, stats in version_stats.items()
                if int(stats["count"]) >= self.min_evidence_count
            ],
            key=lambda item: (
                -item["negative_feedback_rate"],
                item["positive_confirmation_rate"],
                item["average_feedback_score"],
                -item["count"],
                item["version"],
            ),
        )
        total_feedback = sum(int(item["count"]) for item in ranking)
        if len(ranking) < 2:
            return []

        worst = ranking[0]
        best = ranking[-1]
        negative_delta = worst["negative_feedback_rate"] - best["negative_feedback_rate"]
        positive_confirmation_delta = best["positive_confirmation_rate"] - worst["positive_confirmation_rate"]
        if negative_delta < 0.25 and positive_confirmation_delta < 0.25:
            return []

        impact = self._impact_scope(
            affected_queries=int(worst["count"]),
            total_queries=total_feedback,
        )
        evidence = {
            "current_version": worst["version"],
            "current_negative_feedback_rate": worst["negative_feedback_rate"],
            "current_positive_confirmation_rate": worst["positive_confirmation_rate"],
            "current_average_feedback_score": worst["average_feedback_score"],
            "current_feedback_count": worst["count"],
            "baseline_version": best["version"],
            "baseline_negative_feedback_rate": best["negative_feedback_rate"],
            "baseline_positive_confirmation_rate": best["positive_confirmation_rate"],
            "baseline_average_feedback_score": best["average_feedback_score"],
            "baseline_feedback_count": best["count"],
            "negative_feedback_delta": round(negative_delta, 4),
            "positive_confirmation_delta": round(positive_confirmation_delta, 4),
            **impact,
        }
        return [
            self._recommendation(
                event_type="version_alert",
                title=f"Feedback real bajo en {worst['version']}",
                description="Una version del orquestador concentra feedback humano peor y mas negativo que la linea base reciente.",
                evidence=evidence,
                proposed_changes={
                    "version_alert": {
                        "source_version": worst["version"],
                        "baseline_version": best["version"],
                        "reason": "negative_feedback_cluster",
                    }
                },
                sample_size=int(worst["count"]) + int(best["count"]),
                issue_rate=max(worst["negative_feedback_rate"], positive_confirmation_delta),
                delta=max(negative_delta, positive_confirmation_delta),
                delta_scale=1.0,
            )
        ]

    def _analyze_high_fallback_domains(self, recent_logs: list[dict]) -> list[dict]:
        domain_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "fallbacks": 0})
        total_logs = len(recent_logs)
        for log in recent_logs:
            domain = str(log.get("case_domain") or "").strip().lower()
            if not domain:
                continue
            domain_stats[domain]["count"] += 1
            if bool(log.get("fallback_used")):
                domain_stats[domain]["fallbacks"] += 1

        recommendations: list[dict] = []
        for domain, stats in domain_stats.items():
            if stats["count"] < self.min_evidence_count:
                continue
            fallback_rate = stats["fallbacks"] / stats["count"]
            if fallback_rate <= 0.30:
                continue
            impact = self._impact_scope(affected_queries=stats["count"], total_queries=total_logs)
            evidence = {
                "domain": domain,
                "sample_count": stats["count"],
                "fallback_count": stats["fallbacks"],
                "fallback_rate": round(fallback_rate, 4),
                **impact,
            }
            recommendations.append(
                self._recommendation(
                    event_type="domain_override",
                    title=f"Preferir retrieval hibrido en {domain}",
                    description=f"El dominio {domain} muestra una tasa de fallback alta y consistente.",
                    evidence=evidence,
                    proposed_changes={"prefer_hybrid_domains_add": [domain]},
                    sample_size=stats["count"],
                    issue_rate=fallback_rate,
                    delta=fallback_rate - 0.30,
                    delta_scale=0.70,
                )
            )
        return recommendations

    def _analyze_high_severity_versions(self, summary: dict) -> list[dict]:
        version_summary = dict(summary.get("orchestrator_version_summary") or {})
        ranking = list(version_summary.get("severity_ranking") or [])
        total_version_sample = sum(int(item.get("count") or 0) for item in ranking)
        if len(ranking) < 2:
            return []

        top = ranking[0]
        baseline = ranking[1]
        if min(int(top.get("count") or 0), int(baseline.get("count") or 0)) < self.min_evidence_count:
            return []

        top_avg = float(top.get("average_severity") or 0.0)
        baseline_avg = float(baseline.get("average_severity") or 0.0)
        delta = top_avg - baseline_avg
        if delta < 0.10:
            return []

        impact = self._impact_scope(
            affected_queries=int(top.get("count") or 0),
            total_queries=total_version_sample,
        )
        evidence = {
            "current_version": top.get("version"),
            "current_average_severity": round(top_avg, 4),
            "current_count": int(top.get("count") or 0),
            "baseline_version": baseline.get("version"),
            "baseline_average_severity": round(baseline_avg, 4),
            "baseline_count": int(baseline.get("count") or 0),
            "severity_delta": round(delta, 4),
            **impact,
        }
        return [
            self._recommendation(
                event_type="version_alert",
                title=f"Severidad elevada en {top.get('version')}",
                description="Una version del orquestador presenta una severidad promedio materialmente superior a la linea base reciente.",
                evidence=evidence,
                proposed_changes={
                    "version_alert": {
                        "source_version": top.get("version"),
                        "baseline_version": baseline.get("version"),
                    }
                },
                sample_size=int(top.get("count") or 0) + int(baseline.get("count") or 0),
                issue_rate=self._clamp(delta, 0.0, 1.0),
                delta=delta,
                delta_scale=0.6,
            )
        ]

    def _analyze_ambiguous_domains(self, recent_logs: list[dict]) -> list[dict]:
        domain_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "ambiguous": 0})
        total_logs = len(recent_logs)
        for log in recent_logs:
            domain = str(log.get("case_domain") or "").strip().lower()
            if not domain:
                continue
            flags = dict(log.get("quality_flags_json") or {})
            domain_stats[domain]["count"] += 1
            if bool(flags.get("ambiguous_query")):
                domain_stats[domain]["ambiguous"] += 1

        recommendations: list[dict] = []
        for domain, stats in domain_stats.items():
            if stats["count"] < self.min_evidence_count:
                continue
            ambiguous_rate = stats["ambiguous"] / stats["count"]
            if ambiguous_rate < 0.35:
                continue
            impact = self._impact_scope(affected_queries=stats["count"], total_queries=total_logs)
            evidence = {
                "domain": domain,
                "sample_count": stats["count"],
                "ambiguous_count": stats["ambiguous"],
                "ambiguous_rate": round(ambiguous_rate, 4),
                **impact,
            }
            recommendations.append(
                self._recommendation(
                    event_type="domain_override",
                    title=f"Forzar pipeline completo en {domain}",
                    description=f"El dominio {domain} acumula consultas ambiguas con frecuencia superior al umbral seguro.",
                    evidence=evidence,
                    proposed_changes={"force_full_pipeline_domains_add": [domain]},
                    sample_size=stats["count"],
                    issue_rate=ambiguous_rate,
                    delta=ambiguous_rate - 0.35,
                    delta_scale=0.65,
                )
            )
        return recommendations

    def _analyze_low_confidence(self, summary: dict, recent_logs: list[dict]) -> list[dict]:
        total = int(summary.get("total_queries") or 0)
        low_confidence_rate = float(summary.get("low_confidence_rate") or 0.0)
        if total < self.min_evidence_count or low_confidence_rate < 0.25:
            return []

        recent_low_confidence = sum(
            1
            for log in recent_logs
            if bool((log.get("quality_flags_json") or {}).get("low_confidence"))
        )
        if recent_low_confidence < self.min_evidence_count:
            return []

        impact = self._impact_scope(affected_queries=recent_low_confidence, total_queries=max(len(recent_logs), total))
        evidence = {
            "total_queries": total,
            "low_confidence_rate": round(low_confidence_rate, 4),
            "recent_low_confidence_count": recent_low_confidence,
            **impact,
        }
        return [
            self._recommendation(
                event_type="threshold_adjustment",
                title="Revisar thresholds de confianza",
                description="Se detecta una proporcion sostenida de respuestas con baja confianza que amerita recalibracion conservadora.",
                evidence=evidence,
                proposed_changes={
                    "threshold_review": {
                        "low_confidence_threshold": 0.55,
                        "low_decision_confidence_threshold": 0.55,
                    }
                },
                sample_size=recent_low_confidence,
                issue_rate=low_confidence_rate,
                delta=low_confidence_rate - 0.25,
                delta_scale=0.75,
            )
        ]

    def _analyze_low_feedback_domains(self, recent_logs: list[dict]) -> list[dict]:
        feedback_logs = self._feedback_logs(recent_logs)
        domain_scores: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "score_total": 0.0})
        total_feedback = len(feedback_logs)
        for log in feedback_logs:
            score = log.get("user_feedback_score")
            domain = str(log.get("case_domain") or "").strip().lower()
            if score is None or not domain:
                continue
            domain_scores[domain]["count"] += 1
            domain_scores[domain]["score_total"] += float(score)

        recommendations: list[dict] = []
        for domain, stats in domain_scores.items():
            if int(stats["count"]) < self.min_evidence_count:
                continue
            average_score = stats["score_total"] / stats["count"]
            if average_score > 2.5:
                continue
            impact = self._impact_scope(affected_queries=int(stats["count"]), total_queries=total_feedback)
            evidence = {
                "domain": domain,
                "feedback_count": int(stats["count"]),
                "average_feedback_score": round(average_score, 4),
                **impact,
            }
            recommendations.append(
                self._recommendation(
                    event_type="domain_review",
                    title=f"Revisar desempeno del dominio {domain}",
                    description=f"El dominio {domain} acumula feedback real bajo con volumen suficiente.",
                    evidence=evidence,
                    proposed_changes={
                        "domain_review": {
                            "domain": domain,
                            "reason": "low_user_feedback",
                        }
                    },
                    sample_size=int(stats["count"]),
                    issue_rate=self._clamp((5.0 - average_score) / 5.0, 0.0, 1.0),
                    delta=3.0 - average_score,
                    delta_scale=3.0,
                )
            )
        return recommendations

    def _analyze_strategy_corrections(self, recent_logs: list[dict]) -> list[dict]:
        return self._analyze_strategy_mismatch_patterns(recent_logs)

    def _analyze_domain_corrections(self, recent_logs: list[dict]) -> list[dict]:
        return self._analyze_domain_mismatch_patterns(recent_logs)

    def _analyze_feedback_version_alerts(self, recent_logs: list[dict]) -> list[dict]:
        return self._analyze_feedback_backed_version_alerts(recent_logs)
