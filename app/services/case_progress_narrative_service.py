# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\case_progress_narrative_service.py
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


class CaseProgressNarrativeService:
    def build_case_progress_narrative(
        self,
        case_state_snapshot: dict[str, Any],
        api_payload: dict[str, Any],
        output_mode: str,
    ) -> dict[str, Any]:
        snapshot = dict(case_state_snapshot or {})
        case_state = dict(snapshot.get("case_state") or {})
        confirmed_facts = dict(snapshot.get("confirmed_facts") or {})
        contradictions = [
            dict(item)
            for item in list(snapshot.get("contradictions") or [])
            if isinstance(item, dict)
        ]
        open_needs = [
            dict(item)
            for item in list(snapshot.get("open_needs") or [])
            if isinstance(item, dict)
        ]
        case_stage = str(case_state.get("case_stage") or "").strip().lower()
        primary_goal = str(case_state.get("primary_goal") or "").strip()
        normalized_mode = str(output_mode or "").strip().lower()

        known_items = self._render_known_facts(confirmed_facts=confirmed_facts, primary_goal=primary_goal)[:2]
        need_items = self._render_open_needs(open_needs=open_needs, confirmed_facts=confirmed_facts)[:2]
        dominant_need = self._select_priority_need(open_needs, confirmed_facts)
        progress_block = self._render_progress_block(
            output_mode=normalized_mode,
            case_stage=case_stage,
            known_items=known_items,
            need_items=need_items,
            api_payload=api_payload,
        )
        priority_block = self._render_priority_block(
            dominant_need=dominant_need,
            output_mode=normalized_mode,
        )

        applies = self._narrative_applies(
            output_mode=normalized_mode,
            known_items=known_items,
            need_items=need_items,
            progress_block=progress_block,
            api_payload=api_payload,
        )
        if not applies:
            return self._empty_narrative()

        opening = self._render_opening(
            output_mode=normalized_mode,
            confirmed_fact_count=len(confirmed_facts),
            open_need_count=len(open_needs),
            primary_goal=primary_goal,
        )
        known_block = self._compose_known_block(known_items)
        contradiction_block = self._render_contradiction_block(
            contradictions=contradictions,
            output_mode=normalized_mode,
            api_payload=api_payload,
        )
        missing_block = self._compose_missing_block(need_items, normalized_mode=normalized_mode)
        priority_block = self._suppress_priority_block_if_redundant(
            priority_block=priority_block,
            dominant_need=dominant_need,
            api_payload=api_payload,
        )

        if normalized_mode == "estrategia" and not self._need_unlocks_strategy(dominant_need):
            missing_block = ""
        if normalized_mode == "ejecucion":
            opening = ""
            known_block = ""
            contradiction_block = ""
            missing_block = ""
            priority_block = ""

        if not any((opening, known_block, contradiction_block, missing_block, progress_block, priority_block)):
            return self._empty_narrative()

        return {
            "applies": True,
            "opening": opening,
            "known_block": known_block,
            "contradiction_block": contradiction_block,
            "missing_block": missing_block,
            "progress_block": progress_block,
            "priority_block": priority_block,
        }

    def _render_opening(
        self,
        *,
        output_mode: str,
        confirmed_fact_count: int,
        open_need_count: int,
        primary_goal: str,
    ) -> str:
        stable_index = (confirmed_fact_count * 11 + open_need_count * 7 + len(primary_goal.strip())) % 3
        if output_mode == "estructuracion":
            options = (
                "Con lo que ya sabemos hasta ahora...",
                "Con la informacion reunida hasta este punto...",
                "Hasta aca, el caso ya deja ver una base bastante clara...",
            )
            return options[stable_index]
        if output_mode == "estrategia":
            options = (
                "Con la informacion reunida hasta aca...",
                "Con la base que ya esta reunida...",
                "Con lo que ya esta definido en el caso...",
                "Con lo que ya quedo claro en el caso...",
            )
            return options[stable_index % len(options)]
        if output_mode == "orientacion_inicial":
            options = (
                "Con lo que ya sabemos hasta ahora...",
                "Con la informacion reunida hasta este punto...",
                "Con la base inicial que ya aparece en el caso...",
            )
            return options[stable_index]
        return ""

    def _render_known_facts(
        self,
        *,
        confirmed_facts: dict[str, Any],
        primary_goal: str,
    ) -> list[str]:
        items: list[str] = []
        if primary_goal:
            items.append(f"queres {self._normalize_goal(primary_goal)}")

        for key, value in confirmed_facts.items():
            rendered = self._humanize_fact_key(str(key or "").strip(), value)
            if rendered:
                items.append(rendered)
        return self._dedupe(items)

    def _render_open_needs(
        self,
        *,
        open_needs: list[dict[str, Any]],
        confirmed_facts: dict[str, Any],
    ) -> list[str]:
        items: list[str] = []
        for need in sorted(
            open_needs,
            key=lambda item: (
                -self._need_priority_rank(str(item.get("priority") or "")),
                -self._need_category_rank(str(item.get("category") or "")),
                str(item.get("need_key") or "").strip(),
            ),
        ):
            fact_key = self._derive_fact_key(need)
            if fact_key and fact_key in confirmed_facts:
                continue
            rendered = self._humanize_need_key(need)
            if rendered:
                items.append(rendered)
        return self._dedupe(items)

    def _render_progress_block(
        self,
        *,
        output_mode: str,
        case_stage: str,
        known_items: list[str],
        need_items: list[str],
        api_payload: dict[str, Any],
    ) -> str:
        if output_mode == "estructuracion" or case_stage == "recopilacion_hechos":
            if known_items:
                return "Con esto ya se puede ordenar mejor el caso."
            return ""
        if output_mode == "estrategia" or case_stage == "analisis_estrategico":
            if known_items:
                return "Ya hay una base suficiente para definir la via principal."
            return ""
        if output_mode == "ejecucion":
            execution_output = dict(api_payload.get("execution_output") or {})
            if self._has_clear_execution_steps(execution_output):
                return ""
            if known_items and not need_items:
                return "Con lo que ya esta definido, ya se puede avanzar de forma concreta."
        if output_mode == "orientacion_inicial" and known_items:
            return "Ya hay una base inicial clara para orientar el caso."
        return ""

    def _render_priority_block(
        self,
        *,
        dominant_need: dict[str, Any] | None,
        output_mode: str,
    ) -> str:
        if dominant_need is None:
            return ""
        label = self._humanize_need_key(dominant_need)
        if not label:
            return ""
        if output_mode == "estructuracion":
            return f"Lo siguiente mas util es definir {label}."
        if output_mode == "estrategia":
            return f"Lo que todavia falta para cerrar bien la estrategia es definir {label}."
        if output_mode == "orientacion_inicial":
            return f"Lo siguiente mas util es aclarar {label}."
        return ""

    def _render_contradiction_block(
        self,
        *,
        contradictions: list[dict[str, Any]],
        output_mode: str,
        api_payload: dict[str, Any],
    ) -> str:
        if not contradictions:
            return ""
        if output_mode == "ejecucion":
            return ""

        conversation_state = dict(api_payload.get("conversation_state") or {})
        progress_signals = dict(conversation_state.get("progress_signals") or {})
        blocking_missing = bool(progress_signals.get("blocking_missing"))

        if output_mode == "orientacion_inicial" and not blocking_missing:
            return ""

        contradiction_count = len(contradictions)
        if output_mode == "estructuracion":
            if contradiction_count > 1:
                return "Hay algunos puntos del caso que conviene aclarar porque la informacion no es consistente sobre aspectos relevantes."
            return "Hay un punto del caso que conviene aclarar porque hay informacion inconsistente sobre un aspecto clave."
        if output_mode == "estrategia":
            return "Antes de cerrar este encuadre, conviene aclarar un aspecto clave porque la informacion no es consistente."
        return ""

    def _compose_known_block(self, items: list[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return f"Ya esta claro que {items[0]}."
        return f"Ya esta claro que {items[0]} y que {items[1]}."

    def _compose_missing_block(self, items: list[str], *, normalized_mode: str) -> str:
        if not items:
            return ""
        if normalized_mode == "estrategia":
            if len(items) == 1:
                return f"Todavia falta definir {items[0]}."
            return f"Todavia falta definir {items[0]} y {items[1]}."
        if len(items) == 1:
            return f"Todavia falta precisar {items[0]}."
        return f"Todavia falta precisar {items[0]} y {items[1]}."

    def _narrative_applies(
        self,
        *,
        output_mode: str,
        known_items: list[str],
        need_items: list[str],
        progress_block: str,
        api_payload: dict[str, Any],
    ) -> bool:
        if output_mode == "ejecucion":
            execution_output = dict(api_payload.get("execution_output") or {})
            if not self._has_clear_execution_steps(execution_output):
                return False
            return bool(progress_block)
        return bool(known_items or need_items or progress_block)

    def _suppress_priority_block_if_redundant(
        self,
        *,
        priority_block: str,
        dominant_need: dict[str, Any] | None,
        api_payload: dict[str, Any],
    ) -> str:
        case_followup = dict(api_payload.get("case_followup") or {})
        if not priority_block or not case_followup or not bool(case_followup.get("should_ask")):
            return priority_block

        followup_need_key = str(case_followup.get("need_key") or "").strip()
        if dominant_need is not None:
            dominant_need_key = str(dominant_need.get("need_key") or "").strip()
            if followup_need_key and dominant_need_key and followup_need_key == dominant_need_key:
                return ""
            dominant_fact_key = self._derive_fact_key(dominant_need)
            followup_fact_key = self._derive_fact_key({"need_key": followup_need_key})
            if dominant_fact_key and followup_fact_key and dominant_fact_key == followup_fact_key:
                return ""

        followup_question = str(case_followup.get("question") or "").strip()
        if self._text_similarity(priority_block, followup_question) > 0.75:
            return ""
        return priority_block

    def _select_priority_need(
        self,
        open_needs: list[dict[str, Any]],
        confirmed_facts: dict[str, Any],
    ) -> dict[str, Any] | None:
        candidates = []
        for need in open_needs:
            fact_key = self._derive_fact_key(need)
            if fact_key and fact_key in confirmed_facts:
                continue
            candidates.append(need)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                -self._need_priority_rank(str(item.get("priority") or "")),
                -self._need_category_rank(str(item.get("category") or "")),
                str(item.get("need_key") or "").strip(),
            ),
        )[0]

    def _need_unlocks_strategy(self, need: dict[str, Any] | None) -> bool:
        if need is None:
            return False
        category = str(need.get("category") or "").strip().lower()
        need_key = str(need.get("need_key") or "").strip().lower()
        return category in {"procesal", "estrategia"} or "estrategia::" in need_key or "procesal::" in need_key

    def _humanize_fact_key(self, key: str, value: Any) -> str:
        normalized_key = self._canonical_key(key)
        if normalized_key == "hay_hijos" and bool(value):
            return "hay hijos involucrados"
        if normalized_key == "ingresos_otro_progenitor" and value not in (None, "", False):
            return "ya hay un dato sobre los ingresos del otro progenitor"
        if normalized_key == "hay_acuerdo":
            return "hay acuerdo entre las partes" if bool(value) else "no hay acuerdo entre las partes"
        if normalized_key == "domicilio_relevante" and value not in (None, "", False):
            return "ya hay un domicilio relevante identificado"
        if isinstance(value, bool):
            return self._humanize_label(normalized_key) if value else ""
        if value not in (None, "", [], {}):
            return f"ya hay un dato sobre {self._humanize_label(normalized_key)}"
        return ""

    def _humanize_need_key(self, need: dict[str, Any]) -> str:
        need_key = str(need.get("need_key") or "").strip().lower()
        fact_key = self._derive_fact_key(need)
        if "modalidad_divorcio" in {need_key, fact_key}:
            return "si el divorcio seria unilateral o de comun acuerdo"
        if fact_key == "ingresos_otro_progenitor":
            return "los ingresos del otro progenitor"
        if fact_key in {"jurisdiccion", "jurisdiction"}:
            return "la provincia o jurisdiccion"
        if fact_key == "domicilio_relevante":
            return "el domicilio relevante"
        return self._humanize_label(fact_key or need_key)

    @staticmethod
    def _normalize_goal(goal: str) -> str:
        value = str(goal or "").strip().rstrip(".")
        if value.startswith("avanzar con "):
            return value[len("avanzar con "):]
        return value

    @staticmethod
    def _humanize_label(value: str) -> str:
        text = str(value or "").strip()
        if "::" in text:
            text = text.rsplit("::", 1)[-1]
        text = text.replace("_", " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _canonical_key(value: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
        return normalized[:120]

    def _derive_fact_key(self, need: dict[str, Any]) -> str:
        resolved = self._canonical_key(need.get("resolved_by_fact_key"))
        if resolved:
            return resolved
        need_key = str(need.get("need_key") or "").strip()
        if "::" in need_key:
            return self._canonical_key(need_key.rsplit("::", 1)[-1])
        return self._canonical_key(need_key)

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

    @staticmethod
    def _has_clear_execution_steps(execution_output: dict[str, Any]) -> bool:
        execution_data = dict(execution_output.get("execution_output") or {})
        actions = [item for item in list(execution_data.get("what_to_do_now") or []) if str(item or "").strip()]
        where_to_go = [item for item in list(execution_data.get("where_to_go") or []) if str(item or "").strip()]
        documents = [item for item in list(execution_data.get("documents_needed") or []) if str(item or "").strip()]
        requests = [item for item in list(execution_data.get("what_to_request") or []) if str(item or "").strip()]
        return bool(actions) and (len(actions) >= 2 or bool(where_to_go or documents or requests or execution_output.get("applies")))

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            normalized = re.sub(r"\s+", " ", str(item or "").strip().casefold())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(str(item).strip())
        return result

    @staticmethod
    def _text_similarity(left: str, right: str) -> float:
        return SequenceMatcher(
            a=CaseProgressNarrativeService._normalize_similarity_text(left),
            b=CaseProgressNarrativeService._normalize_similarity_text(right),
        ).ratio()

    @staticmethod
    def _normalize_similarity_text(text: str) -> str:
        normalized = re.sub(r"[^\w\s]", "", str(text or "")).casefold()
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _empty_narrative() -> dict[str, Any]:
        return {
            "applies": False,
            "opening": "",
            "known_block": "",
            "contradiction_block": "",
            "missing_block": "",
            "progress_block": "",
            "priority_block": "",
        }


case_progress_narrative_service = CaseProgressNarrativeService()


def build_case_progress_narrative(
    case_state_snapshot: dict[str, Any],
    api_payload: dict[str, Any],
    output_mode: str,
) -> dict[str, Any]:
    return case_progress_narrative_service.build_case_progress_narrative(
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        output_mode=output_mode,
    )
