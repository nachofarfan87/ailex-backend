from __future__ import annotations

import re
from typing import Any

from app.services.conversation_integrity_service import build_integrity_state, canonicalize_slot

_GENERIC_QUESTION_PATTERNS = (
    "mas contexto",
    "queres contarme mas",
    "podrias ampliar",
    "puedes ampliar",
    "contarme mas",
)

_TECHNICAL_QUESTION_PATTERNS = (
    "tipo de proceso",
    "etapa procesal",
    "encuadre procesal",
    "competencia",
)

_EARLY_CASE_STAGES = {
    "",
    "recopilacion_hechos",
    "analisis_estrategico",
    "early",
}


class CaseFollowupService:
    def build_case_followup(
        self,
        case_state_snapshot: dict[str, Any],
        api_payload: dict[str, Any],
        output_mode: str,
    ) -> dict[str, Any]:
        snapshot = dict(case_state_snapshot or {})
        open_needs = [
            dict(item)
            for item in list(snapshot.get("open_needs") or [])
            if isinstance(item, dict)
        ]
        confirmed_facts = self._collect_resolved_facts(
            snapshot=snapshot,
            api_payload=api_payload,
        )
        integrity_state = build_integrity_state(
            conversation_state=dict(api_payload.get("conversation_state") or {}),
            case_memory=dict(api_payload.get("case_memory") or {}),
        )
        case_state = dict(snapshot.get("case_state") or {})
        case_stage = str(case_state.get("case_stage") or "").strip().lower()
        case_progress = dict(api_payload.get("case_progress") or {})
        clarification_behavior = self._extract_clarification_behavior(api_payload)

        if clarification_behavior["response_strategy"] == "advance_with_prudence":
            return self._empty_followup(
                clarification_behavior["reason"]
                or "La respuesta actual permite seguir orientando con prudencia sin insistir con otra pregunta."
            )

        progress_driven = self._build_progress_driven_followup(
            open_needs=open_needs,
            confirmed_facts=confirmed_facts,
            integrity_state=integrity_state,
            contradictions=[dict(item) for item in list(snapshot.get("contradictions") or []) if isinstance(item, dict)],
            case_progress=case_progress,
            api_payload=api_payload,
            case_stage=case_stage,
            output_mode=output_mode,
            clarification_behavior=clarification_behavior,
        )
        if progress_driven is not None:
            return progress_driven

        if not open_needs:
            return self._empty_followup("Hay suficiente información para avanzar sin follow-up.")

        candidate_need = self._select_candidate_need(
            open_needs=open_needs,
            confirmed_facts=confirmed_facts,
            case_progress=case_progress,
            integrity_state=integrity_state,
        )
        if candidate_need is None:
            return self._empty_followup("No hay una necesidad dominante pendiente que justifique una pregunta final.")

        if clarification_behavior["detected_loop"] or clarification_behavior["user_cannot_answer"]:
            return self._empty_followup(
                clarification_behavior["reason"]
                or "La respuesta actual no destraba mas el caso y no conviene insistir con la misma pregunta."
            )

        if not self._should_ask_followup(
            candidate_need=candidate_need,
            case_stage=case_stage,
            api_payload=api_payload,
            output_mode=output_mode,
        ):
            return self._empty_followup("Hay suficiente información para avanzar sin follow-up.")

        question = (
            clarification_behavior["reformulated_question"]
            if clarification_behavior["response_strategy"] == "reformulate_question"
            else self._build_question_from_need(
                candidate_need,
                api_payload=api_payload,
                case_stage=case_stage,
                output_mode=output_mode,
            )
        )
        if not self._is_valid_specific_question(question):
            return self._empty_followup("No se detectó una pregunta concreta y accionable para este momento.")

        return {
            "should_ask": True,
            "question": question,
            "reason": clarification_behavior["reason"] or self._build_reason(candidate_need, output_mode=output_mode, case_stage=case_stage),
            "source": str(candidate_need.get("source") or "case_need"),
            "priority": str(candidate_need.get("priority") or "").strip().lower(),
            "need_key": str(candidate_need.get("need_key") or "").strip(),
            "adaptive_question_type": (
                "reformulation"
                if clarification_behavior["response_strategy"] == "reformulate_question"
                else str(candidate_need.get("type") or "").strip().lower()
            ),
            "response_quality": clarification_behavior["response_quality"],
            "response_strategy": clarification_behavior["response_strategy"],
            "detected_loop": clarification_behavior["detected_loop"],
            "user_cannot_answer": clarification_behavior["user_cannot_answer"],
        }

    def _build_progress_driven_followup(
        self,
        *,
        open_needs: list[dict[str, Any]],
        confirmed_facts: dict[str, Any],
        integrity_state: dict[str, Any],
        contradictions: list[dict[str, Any]],
        case_progress: dict[str, Any],
        api_payload: dict[str, Any],
        case_stage: str,
        output_mode: str,
        clarification_behavior: dict[str, Any],
    ) -> dict[str, Any] | None:
        next_step_type = str(case_progress.get("next_step_type") or "").strip().lower()
        if next_step_type == "resolve_contradiction":
            need = self._select_contradiction_need(
                open_needs=open_needs,
                confirmed_facts=confirmed_facts,
                case_progress=case_progress,
                integrity_state=integrity_state,
                contradictions=contradictions,
            ) or self._build_synthetic_contradiction_need(case_progress, contradictions=contradictions)
            return self._materialize_followup(
                need=need,
                api_payload=api_payload,
                case_stage=case_stage,
                output_mode=output_mode,
                clarification_behavior=clarification_behavior,
            )

        if next_step_type == "ask":
            need = self._select_progress_driven_critical_need(
                open_needs=open_needs,
                confirmed_facts=confirmed_facts,
                case_progress=case_progress,
                integrity_state=integrity_state,
            )
            return self._materialize_followup(
                need=need,
                api_payload=api_payload,
                case_stage=case_stage,
                output_mode=output_mode,
                clarification_behavior=clarification_behavior,
            )
        return None

    def _materialize_followup(
        self,
        *,
        need: dict[str, Any] | None,
        api_payload: dict[str, Any],
        case_stage: str,
        output_mode: str,
        clarification_behavior: dict[str, Any],
    ) -> dict[str, Any] | None:
        if need is None:
            return None
        if clarification_behavior["detected_loop"] or clarification_behavior["user_cannot_answer"]:
            return None
        if not self._should_ask_followup(
            candidate_need=need,
            case_stage=case_stage,
            api_payload=api_payload,
            output_mode=output_mode,
        ):
            return None
        question = (
            clarification_behavior["reformulated_question"]
            if clarification_behavior["response_strategy"] == "reformulate_question"
            else self._build_question_from_need(
                need,
                api_payload=api_payload,
                case_stage=case_stage,
                output_mode=output_mode,
            )
        )
        if not self._is_valid_specific_question(question):
            return None
        return {
            "should_ask": True,
            "question": question,
            "reason": clarification_behavior["reason"] or self._build_reason(need, output_mode=output_mode, case_stage=case_stage),
            "source": str(need.get("source") or "case_progress"),
            "priority": str(need.get("priority") or "critical").strip().lower(),
            "need_key": str(need.get("need_key") or "").strip(),
            "adaptive_question_type": (
                "reformulation"
                if clarification_behavior["response_strategy"] == "reformulate_question"
                else str(need.get("type") or "").strip().lower()
            ),
            "response_quality": clarification_behavior["response_quality"],
            "response_strategy": clarification_behavior["response_strategy"],
            "detected_loop": clarification_behavior["detected_loop"],
            "user_cannot_answer": clarification_behavior["user_cannot_answer"],
        }

    def _select_candidate_need(
        self,
        *,
        open_needs: list[dict[str, Any]],
        confirmed_facts: dict[str, Any],
        case_progress: dict[str, Any] | None = None,
        integrity_state: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        progress = dict(case_progress or {})
        blocked_slots = set(dict(integrity_state or {}).get("blocked_slots") or [])
        priority_gap_keys = {
            self._canonical_key(item.get("key") or item.get("need_key"))
            for item in list(progress.get("critical_gaps") or [])
            if isinstance(item, dict)
        }
        candidates = [
            need
            for need in open_needs
            if not self._need_is_resolved_by_confirmed_fact(need, confirmed_facts)
            and not self._need_matches_blocked_slot(need, blocked_slots)
        ]
        if not candidates:
            return None

        return sorted(
            candidates,
            key=lambda need: (
                -int(self._derive_fact_key_from_need(need) in priority_gap_keys),
                -self._need_priority_rank(str(need.get("priority") or "")),
                -self._need_category_rank(str(need.get("category") or "")),
                -int(self._has_valid_suggested_question(str(need.get("suggested_question") or ""))),
                str(need.get("need_key") or "").strip(),
            ),
        )[0]

    def _should_ask_followup(
        self,
        *,
        candidate_need: dict[str, Any],
        case_stage: str,
        api_payload: dict[str, Any],
        output_mode: str,
    ) -> bool:
        conversation_state = dict(api_payload.get("conversation_state") or {})
        progress_signals = dict(conversation_state.get("progress_signals") or {})
        case_progress = dict(api_payload.get("case_progress") or {})
        blocking_missing = bool(progress_signals.get("blocking_missing"))
        completeness = str(progress_signals.get("case_completeness") or "low").strip().lower()
        execution_output = dict(api_payload.get("execution_output") or {})
        priority = str(candidate_need.get("priority") or "").strip().lower()
        stage = str(case_progress.get("stage") or "").strip().lower()
        next_step_type = str(case_progress.get("next_step_type") or "").strip().lower()
        progress_status = str(case_progress.get("progress_status") or "").strip().lower()
        readiness_label = str(case_progress.get("readiness_label") or "").strip().lower()
        critical_gap_count = len(list(case_progress.get("critical_gaps") or []))
        has_blockers = bool(list(case_progress.get("blocking_issues") or []))
        source = str(candidate_need.get("source") or "").strip().lower()
        category = str(candidate_need.get("category") or "").strip().lower()

        if next_step_type == "resolve_contradiction":
            return source == "case_progress" or str(candidate_need.get("type") or "").strip().lower() == "contradiction"
        if stage in {"decision", "ejecucion"} and critical_gap_count == 0:
            # Excepción controlada: en decision con faltante estratégico relevante,
            # permitir una única pregunta estratégica útil.
            # En ejecucion esta excepción no aplica: si no hay critical gaps, no se pregunta.
            allow_decision_followup = False
            if stage == "decision":
                from app.services.case_progress_service import resolve_progress_behavior_intent
                intent = resolve_progress_behavior_intent(case_progress)
                category = str(candidate_need.get("category") or "").strip().lower()
                allow_decision_followup = (
                    intent["should_allow_decision_followup"]
                    and category in {"procesal", "estrategia"}
                )
            if not allow_decision_followup:
                return False
            return True  # pregunta estratégica puntual en etapa de decisión
        if readiness_label == "high" and not has_blockers and critical_gap_count == 0:
            return False
        if progress_status == "blocked":
            if next_step_type not in {"ask", "resolve_contradiction"}:
                return False
            if priority != "critical" and category not in {"procesal", "estrategia"}:
                return False

        if output_mode == "ejecucion" and not blocking_missing:
            return False
        if case_stage == "ejecucion" and self._has_concrete_execution_steps(execution_output):
            return False
        if completeness in {"high", "very_high"} and priority != "critical":
            return False

        if priority == "critical":
            return True

        if blocking_missing and category in {"procesal", "estrategia", "hecho"}:
            return True
        if output_mode in {"analisis_estrategico", "estrategia"} and category in {"procesal", "estrategia"}:
            return True
        if case_stage in {"recopilacion_hechos", "analisis_estrategico"}:
            return True

        return False

    def _build_question_from_need(
        self,
        need: dict[str, Any],
        *,
        api_payload: dict[str, Any],
        case_stage: str,
        output_mode: str,
    ) -> str:
        suggested_question = str(need.get("suggested_question") or "").strip()
        if self._has_valid_suggested_question(suggested_question) and self._is_question_user_answerable(
            suggested_question,
            need=need,
            api_payload=api_payload,
            case_stage=case_stage,
            output_mode=output_mode,
        ):
            return self._normalize_question(suggested_question)

        fact_key = self._derive_fact_key_from_need(need)
        need_key = str(need.get("need_key") or "").strip().lower()
        category = str(need.get("category") or "").strip().lower()
        need_type = str(need.get("type") or "").strip().lower()

        if self._looks_like_divorce_context(
            api_payload=api_payload,
            need=need,
            question=suggested_question,
        ):
            if any(pattern in need_key for pattern in ("tipo_proceso", "etapa_procesal")) or any(
                pattern in suggested_question.casefold()
                for pattern in ("tipo de proceso", "etapa procesal")
            ):
                return "Â¿El divorcio serÃ­a de comÃºn acuerdo o no?"
            if fact_key in {"convivencia_actual", "separacion_actual"}:
                return "Â¿Ya estÃ¡n separados o todavÃ­a conviven?"
            if fact_key == "hijos":
                return "Â¿Tienen hijos en comÃºn?"

        if need_type == "contradiction":
            label = self._humanize_key(fact_key or need_key)
            if label:
                return f"¿Podés aclarar el dato correcto sobre {label}?"
            return "¿Podés aclarar cuál es el dato correcto en ese punto?"
        if "modalidad_divorcio" in {fact_key, need_key}:
            return "¿El divorcio sería unilateral o de común acuerdo?"
        if fact_key in {"jurisdiccion", "jurisdiction"} or "jurisdiccion" in need_key:
            return "¿En qué provincia o jurisdicción tramitarías esto?"
        if fact_key == "ingresos_otro_progenitor":
            return "¿Podés precisar los ingresos del otro progenitor?"
        if fact_key == "domicilio_relevante":
            return "¿Cuál es el domicilio relevante para este caso?"
        if category == "procesal" and "competencia" in need_key:
            return "¿En qué jurisdicción o tribunal debería tramitarse esto?"

        label = self._humanize_key(fact_key or need_key)
        if not label:
            return ""
        return f"¿Podés precisar {label}?"

    def _is_question_user_answerable(
        self,
        question: str,
        *,
        need: dict[str, Any],
        api_payload: dict[str, Any],
        case_stage: str,
        output_mode: str,
    ) -> bool:
        normalized = self._normalize_question(question).casefold()
        if not normalized:
            return False
        if case_stage not in _EARLY_CASE_STAGES and output_mode not in {"recopilacion_hechos", "orientacion_inicial"}:
            return True
        if not any(pattern in normalized for pattern in _TECHNICAL_QUESTION_PATTERNS):
            return True
        return False

    def _looks_like_divorce_context(
        self,
        *,
        api_payload: dict[str, Any],
        need: dict[str, Any],
        question: str,
    ) -> bool:
        values = [
            str(api_payload.get("query") or ""),
            str(api_payload.get("user_query") or ""),
            str(api_payload.get("quick_start") or ""),
            str(api_payload.get("response_text") or ""),
            str(api_payload.get("case_domain") or ""),
            str(need.get("need_key") or ""),
            str(question or ""),
        ]
        joined = " ".join(value.casefold() for value in values if value).strip()
        return any(token in joined for token in ("divorcio", "separ", "conyuge", "cÃ³nyuge"))

    @staticmethod
    def _need_priority_rank(priority: str) -> int:
        normalized = str(priority or "").strip().lower()
        if normalized == "critical":
            return 4
        if normalized == "high":
            return 3
        if normalized in {"normal", "medium"}:
            return 2
        if normalized == "low":
            return 1
        return 0

    @staticmethod
    def _need_category_rank(category: str) -> int:
        normalized = str(category or "").strip().lower()
        if normalized == "procesal":
            return 5
        if normalized == "estrategia":
            return 4
        if normalized == "hecho":
            return 3
        if normalized == "evidencia":
            return 2
        if normalized == "economico":
            return 1
        return 0

    def _need_is_resolved_by_confirmed_fact(
        self,
        need: dict[str, Any],
        confirmed_facts: dict[str, Any],
    ) -> bool:
        fact_key = self._derive_fact_key_from_need(need)
        if fact_key and self._fact_has_meaningful_value(confirmed_facts.get(fact_key)):
            return True
        normalized_need_key = str(need.get("need_key") or "").strip().lower()
        return bool(normalized_need_key and self._fact_has_meaningful_value(confirmed_facts.get(normalized_need_key)))

    def _collect_resolved_facts(
        self,
        *,
        snapshot: dict[str, Any],
        api_payload: dict[str, Any],
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}

        for source in (
            dict(snapshot.get("probable_facts") or {}),
            dict(snapshot.get("confirmed_facts") or {}),
        ):
            for key, value in source.items():
                canonical = self._canonical_key(key)
                if canonical and self._fact_has_meaningful_value(value):
                    resolved[canonical] = value

        case_memory = dict(api_payload.get("case_memory") or {})
        for key, item in dict(case_memory.get("facts") or {}).items():
            canonical = self._canonical_key(key)
            value = dict(item or {}).get("value") if isinstance(item, dict) else item
            if canonical and self._fact_has_meaningful_value(value):
                resolved[canonical] = value

        conversation_state = dict(api_payload.get("conversation_state") or {})
        known_facts_map = dict(conversation_state.get("known_facts_map") or {})
        for key, value in known_facts_map.items():
            canonical = self._canonical_key(key)
            if canonical and self._fact_has_meaningful_value(value):
                resolved[canonical] = value

        for item in list(conversation_state.get("known_facts") or []):
            if not isinstance(item, dict):
                continue
            canonical = self._canonical_key(item.get("key") or item.get("fact_key"))
            value = item.get("value")
            if canonical and self._fact_has_meaningful_value(value):
                resolved[canonical] = value

        return resolved

    def _derive_fact_key_from_need(self, need: dict[str, Any]) -> str:
        explicit = self._canonical_key(need.get("resolved_by_fact_key"))
        if explicit:
            return explicit
        need_key = str(need.get("need_key") or "").strip()
        if "::" in need_key:
            return self._canonical_key(need_key.rsplit("::", 1)[-1])
        return self._canonical_key(need_key)

    def _has_concrete_execution_steps(self, execution_output: dict[str, Any]) -> bool:
        execution_data = dict(execution_output.get("execution_output") or {})
        actions = [item for item in list(execution_data.get("what_to_do_now") or []) if str(item or "").strip()]
        where_to_go = [item for item in list(execution_data.get("where_to_go") or []) if str(item or "").strip()]
        documents = [item for item in list(execution_data.get("documents_needed") or []) if str(item or "").strip()]
        requests = [item for item in list(execution_data.get("what_to_request") or []) if str(item or "").strip()]
        return bool(actions) and (len(actions) >= 2 or bool(where_to_go or documents or requests or execution_output.get("applies")))

    def _build_reason(self, need: dict[str, Any], *, output_mode: str, case_stage: str) -> str:
        reason = str(need.get("reason") or "").strip()
        if reason:
            return reason

        category = str(need.get("category") or "").strip().lower()
        if str(need.get("type") or "").strip().lower() == "contradiction":
            return "Primero conviene aclarar la contradicción relevante antes de seguir avanzando."
        if output_mode == "ejecucion" or case_stage == "ejecucion":
            return "Falta el dato que habilita el siguiente paso concreto."
        if category == "procesal":
            return "Define el encuadre procesal inmediato."
        if category == "estrategia":
            return "Define la vía estratégica inmediata."
        if category == "hecho":
            return "Falta el dato más útil para consolidar el caso."
        return "Falta un dato relevante para avanzar con mayor precisión."

    def _has_valid_suggested_question(self, question: str) -> bool:
        normalized = self._normalize_question(question)
        if not normalized:
            return False
        lowered = normalized.casefold()
        return not any(pattern in lowered for pattern in _GENERIC_QUESTION_PATTERNS)

    def _is_valid_specific_question(self, question: str) -> bool:
        return self._has_valid_suggested_question(question)

    @staticmethod
    def _normalize_question(question: str) -> str:
        value = re.sub(r"\s+", " ", str(question or "").strip())
        if not value:
            return ""
        if not value.endswith("?"):
            value = f"{value}?"
        if not value.startswith("¿"):
            value = f"¿{value.lstrip('?')}"
        return value

    @staticmethod
    def _humanize_key(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if "::" in text:
            text = text.rsplit("::", 1)[-1]
        return text.replace("_", " ").strip()

    @staticmethod
    def _canonical_key(value: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
        return normalized[:120]

    @staticmethod
    def _fact_has_meaningful_value(value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str):
            normalized = re.sub(r"\s+", " ", value.strip().casefold())
            return normalized not in {"desconocido", "sin dato", "pendiente"}
        return True

    def _select_progress_driven_critical_need(
        self,
        *,
        open_needs: list[dict[str, Any]],
        confirmed_facts: dict[str, Any],
        case_progress: dict[str, Any],
        integrity_state: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        blocked_slots = set(dict(integrity_state or {}).get("blocked_slots") or [])
        critical_gap_keys = [
            self._canonical_key(item.get("key") or item.get("need_key"))
            for item in list(case_progress.get("critical_gaps") or [])
            if isinstance(item, dict)
        ]
        for gap_key in critical_gap_keys:
            for need in open_needs:
                if self._need_is_resolved_by_confirmed_fact(need, confirmed_facts):
                    continue
                if self._need_matches_blocked_slot(need, blocked_slots):
                    continue
                if self._derive_fact_key_from_need(need) == gap_key:
                    return need
        return None

    def _select_contradiction_need(
        self,
        *,
        open_needs: list[dict[str, Any]],
        confirmed_facts: dict[str, Any],
        case_progress: dict[str, Any],
        integrity_state: dict[str, Any] | None = None,
        contradictions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        blocked_slots = set(dict(integrity_state or {}).get("blocked_slots") or [])
        contradictions = list(case_progress.get("basis", {}).get("contradictions") or case_progress.get("contradictions") or contradictions)
        contradiction_keys = [
            self._canonical_key(dict(item or {}).get("key"))
            for item in contradictions
            if isinstance(item, dict)
        ]
        for contradiction_key in contradiction_keys:
            for need in open_needs:
                if self._need_is_resolved_by_confirmed_fact(need, confirmed_facts):
                    continue
                if self._need_matches_blocked_slot(need, blocked_slots):
                    continue
                if self._derive_fact_key_from_need(need) == contradiction_key:
                    return need
        return None

    def _need_matches_blocked_slot(
        self,
        need: dict[str, Any],
        blocked_slots: set[str],
    ) -> bool:
        if not blocked_slots:
            return False
        canonical_slot = canonicalize_slot(
            need_key=str(need.get("need_key") or ""),
            resolved_by_fact_key=str(need.get("resolved_by_fact_key") or ""),
            question=str(need.get("suggested_question") or ""),
        )
        return bool(canonical_slot and canonical_slot in blocked_slots)

    def _build_synthetic_contradiction_need(
        self,
        case_progress: dict[str, Any],
        *,
        contradictions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        contradictions = list(case_progress.get("basis", {}).get("contradictions") or case_progress.get("contradictions") or contradictions or [])
        if not contradictions:
            return None
        first = dict(contradictions[0] or {})
        key = self._canonical_key(first.get("key"))
        if not key:
            return None
        return {
            "type": "contradiction",
            "need_key": f"contradiction::{key}",
            "resolved_by_fact_key": key,
            "priority": "critical",
            "category": "hecho",
            "reason": "Primero conviene aclarar la contradicción relevante antes de seguir avanzando.",
            "source": "case_progress",
        }

    def _extract_clarification_behavior(self, api_payload: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(api_payload.get("metadata") or {})
        clarification_context = dict(metadata.get("clarification_context") or {})
        return {
            "response_quality": str(clarification_context.get("response_quality") or "").strip().lower(),
            "response_strategy": str(clarification_context.get("response_strategy") or "").strip().lower(),
            "reformulated_question": str(
                clarification_context.get("reformulated_question")
                or clarification_context.get("precision_prompt")
                or ""
            ).strip(),
            "reason": str(
                clarification_context.get("limit_explanation")
                or clarification_context.get("hybrid_guidance")
                or ""
            ).strip(),
            "detected_loop": bool(clarification_context.get("detected_loop")),
            "user_cannot_answer": bool(clarification_context.get("user_cannot_answer")),
        }

    @staticmethod
    def _empty_followup(reason: str) -> dict[str, Any]:
        return {
            "should_ask": False,
            "question": "",
            "reason": reason,
            "source": "none",
            "priority": "",
            "need_key": "",
        }


case_followup_service = CaseFollowupService()


def build_case_followup(
    case_state_snapshot: dict[str, Any],
    api_payload: dict[str, Any],
    output_mode: str,
) -> dict[str, Any]:
    return case_followup_service.build_case_followup(
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        output_mode=output_mode,
    )
