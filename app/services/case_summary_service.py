# c:\Users\nacho\Documents\APPS\AILEX\backend\app\services\case_summary_service.py
from __future__ import annotations

import re
from typing import Any


class CaseSummaryService:
    def build_case_summary(
        self,
        case_state_snapshot: dict[str, Any],
        api_payload: dict[str, Any],
        output_mode: str,
    ) -> dict[str, Any]:
        snapshot = dict(case_state_snapshot or {})
        case_state = dict(snapshot.get("case_state") or {})
        confirmed_facts = dict(snapshot.get("confirmed_facts") or {})
        open_needs = [
            dict(item)
            for item in list(snapshot.get("open_needs") or [])
            if isinstance(item, dict)
        ]

        primary_goal = str(case_state.get("primary_goal") or "").strip()
        case_type = str(case_state.get("case_type") or "").strip()
        case_stage = str(case_state.get("case_stage") or "").strip().lower()
        normalized_mode = str(output_mode or "").strip().lower()

        goal_fragment = self._render_goal_fragment(primary_goal=primary_goal, case_type=case_type)
        known_fragment = self._render_known_fragment(confirmed_facts=confirmed_facts, output_mode=normalized_mode)
        pending_fragment = self._render_pending_fragment(
            dominant_need=self._select_dominant_need(open_needs),
            output_mode=normalized_mode,
        )
        stage_fragment = self._render_stage_fragment(
            output_mode=normalized_mode,
            case_stage=case_stage,
            has_known=bool(known_fragment),
            has_pending=bool(pending_fragment),
            api_payload=api_payload,
        )

        fragments = [fragment for fragment in (goal_fragment, known_fragment, stage_fragment, pending_fragment) if fragment]
        deduped_fragments = self._dedupe_fragments(fragments)
        if not deduped_fragments:
            return self._empty_summary()

        summary_text = self._trim_summary(" ".join(deduped_fragments))
        if not summary_text or len(summary_text) < 12:
            return self._empty_summary()

        return {
            "applies": True,
            "summary_text": summary_text,
            "summary_version": "v1",
        }

    def _render_goal_fragment(self, *, primary_goal: str, case_type: str) -> str:
        normalized_goal = str(primary_goal or "").strip().rstrip(".")
        normalized_case_type = self._canonical_key(case_type)

        if "reclamar cuota alimentaria" in normalized_goal.lower():
            return "Reclamo de alimentos."
        if "divorcio" in normalized_goal.lower() or "divorcio" in normalized_case_type:
            return "Divorcio."
        if normalized_goal:
            goal_text = normalized_goal[:1].upper() + normalized_goal[1:]
            return f"{goal_text}."
        if normalized_case_type == "alimentos_hijos":
            return "Reclamo de alimentos."
        if normalized_case_type.startswith("divorcio"):
            return "Divorcio."
        return ""

    def _render_known_fragment(self, *, confirmed_facts: dict[str, Any], output_mode: str) -> str:
        facts = self._select_summary_facts(confirmed_facts)
        if not facts:
            if output_mode == "ejecucion":
                return "El caso ya tiene base suficiente para avanzar."
            return ""
        if len(facts) == 1:
            options = (
                f"Hay {facts[0]}.",
                f"Se confirma que {facts[0]}.",
                f"Ya esta claro que {facts[0]}.",
            )
            stable_index = (len(facts[0]) + len(output_mode or "")) % len(options)
            return options[stable_index]
        return f"Ya esta claro que {facts[0]} y que {facts[1]}."

    def _render_pending_fragment(self, *, dominant_need: dict[str, Any] | None, output_mode: str) -> str:
        if dominant_need is None:
            return ""
        label = self._humanize_need(dominant_need)
        if not label:
            return ""
        if output_mode == "estrategia":
            return f"Falta definir {label} para cerrar la estrategia."
        if output_mode == "ejecucion":
            return f"Queda pendiente {label} para ajustar el siguiente paso."
        return f"Falta precisar {label}."

    def _render_stage_fragment(
        self,
        *,
        output_mode: str,
        case_stage: str,
        has_known: bool,
        has_pending: bool,
        api_payload: dict[str, Any],
    ) -> str:
        if output_mode == "ejecucion":
            execution_output = dict(api_payload.get("execution_output") or {})
            execution_data = dict(execution_output.get("execution_output") or {})
            actions = [item for item in list(execution_data.get("what_to_do_now") or []) if str(item or "").strip()]
            if actions:
                return "El caso ya tiene base suficiente para avanzar."
            return ""
        if output_mode == "estrategia" or case_stage == "analisis_estrategico":
            return "Ya hay una base suficiente para definir la via principal." if not has_known else ""
        if output_mode == "estructuracion" or case_stage == "recopilacion_hechos":
            return "Ya hay una base inicial del caso." if not has_known and has_pending else ""
        return ""

    def _select_summary_facts(self, confirmed_facts: dict[str, Any]) -> list[str]:
        ranked: list[str] = []
        for key, value in confirmed_facts.items():
            rendered = self._humanize_fact(key, value)
            if rendered:
                ranked.append(rendered)
        deduped = self._dedupe_fragments(ranked)
        return deduped[:2]

    def _select_dominant_need(self, open_needs: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not open_needs:
            return None
        return sorted(
            open_needs,
            key=lambda item: (
                -self._need_priority_rank(str(item.get("priority") or "")),
                -self._need_category_rank(str(item.get("category") or "")),
                str(item.get("need_key") or "").strip(),
            ),
        )[0]

    def _humanize_fact(self, key: str, value: Any) -> str:
        normalized_key = self._canonical_key(key)
        if normalized_key == "hay_hijos" and bool(value):
            return "hay hijos involucrados"
        if normalized_key == "hay_acuerdo":
            return "hay acuerdo entre las partes" if bool(value) else "no hay acuerdo entre las partes"
        if normalized_key == "ingresos_otro_progenitor" and value not in (None, "", False):
            return "ya hay un dato sobre los ingresos del otro progenitor"
        if normalized_key == "domicilio_relevante" and value not in (None, "", False):
            return "ya hay un domicilio relevante identificado"
        return ""

    def _humanize_need(self, need: dict[str, Any]) -> str:
        need_key = str(need.get("need_key") or "").strip().lower()
        resolved_by_fact_key = self._canonical_key(need.get("resolved_by_fact_key"))
        fact_key = resolved_by_fact_key or self._canonical_key(need_key.rsplit("::", 1)[-1] if "::" in need_key else need_key)

        if "modalidad_divorcio" in {need_key, fact_key}:
            return "si seria unilateral o de comun acuerdo"
        if fact_key == "ingresos_otro_progenitor":
            return "los ingresos del otro progenitor"
        if fact_key in {"jurisdiccion", "jurisdiction"}:
            return "la provincia o jurisdiccion"
        if fact_key == "domicilio_relevante":
            return "el domicilio relevante"

        label = self._humanize_label(fact_key or need_key)
        return label

    def _trim_summary(self, text: str, max_chars: int = 280) -> str:
        compacted = re.sub(r"\s+", " ", str(text or "").strip())
        if len(compacted) <= max_chars:
            return compacted

        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", compacted) if part.strip()]
        selected: list[str] = []
        current_length = 0
        for sentence in sentences:
            projected = current_length + len(sentence) + (1 if selected else 0)
            if projected > max_chars:
                break
            selected.append(sentence)
            current_length = projected
        if selected:
            return " ".join(selected).strip()

        truncated = compacted[: max_chars + 1]
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        return truncated.rstrip(" ,.;:") + "..."

    @staticmethod
    def _dedupe_fragments(items: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = re.sub(r"[^\w\s]", "", str(item or "")).casefold()
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(str(item).strip())
        return result

    @staticmethod
    def _canonical_key(value: Any) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
        return normalized[:120]

    @staticmethod
    def _humanize_label(value: str) -> str:
        text = str(value or "").strip()
        if "::" in text:
            text = text.rsplit("::", 1)[-1]
        return re.sub(r"\s+", " ", text.replace("_", " ").strip())

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
    def _empty_summary() -> dict[str, Any]:
        return {
            "applies": False,
            "summary_text": "",
            "summary_version": "v1",
        }


case_summary_service = CaseSummaryService()


def build_case_summary(
    case_state_snapshot: dict[str, Any],
    api_payload: dict[str, Any],
    output_mode: str,
) -> dict[str, Any]:
    return case_summary_service.build_case_summary(
        case_state_snapshot=case_state_snapshot,
        api_payload=api_payload,
        output_mode=output_mode,
    )
