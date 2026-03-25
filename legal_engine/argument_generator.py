from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from legal_engine.case_profile_builder import build_case_profile
from legal_engine.case_strategy_builder import build_case_strategy
from legal_engine.legal_reasoner import NormativeGrounding, ReasoningResult
from legal_engine.procedural_strategy import ProceduralPlan, ProceduralStep, URGENCY_NORMAL
from legal_engine.style_blueprint import StyleBlueprint, normalize_style_blueprint


MODE_BREVE = "breve"
MODE_FORMAL = "formal"
MODE_CONTESTACION = "contestacion"
MODE_INCIDENTE = "incidente"
MODE_MEMORIAL = "memorial"
MODE_BASE_ARGUMENTAL = "base_argumental"

ALL_MODES = frozenset([
    MODE_BREVE,
    MODE_FORMAL,
    MODE_CONTESTACION,
    MODE_INCIDENTE,
    MODE_MEMORIAL,
    MODE_BASE_ARGUMENTAL,
])

_PLACEHOLDER = "[DATO_FALTANTE]"
_SOFTENER_PRINCIPIO = "en principio"
_SOFTENER_PODRIA = "podria"
_SOFTENER_VERIFICAR = "verificar"
_SOFTENER_SP = "sin perjuicio de las particularidades del caso"


@dataclass
class ArgumentSection:
    title: str
    content: str
    cites: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "content": self.content, "cites": list(self.cites)}


@dataclass
class GeneratedArgument:
    mode: str
    query: str
    title: str
    sections: list[ArgumentSection] = field(default_factory=list)
    citations_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    full_text: str = ""

    def is_empty(self) -> bool:
        return len(self.sections) == 0 and not self.full_text.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "query": self.query,
            "title": self.title,
            "sections": [s.to_dict() for s in self.sections],
            "citations_used": list(self.citations_used),
            "warnings": list(self.warnings),
            "missing_fields": list(self.missing_fields),
            "full_text": self.full_text,
        }


class ArgumentGenerator:
    def __init__(self) -> None:
        self._last_section_warnings: list[str] = []
        self._dispatch = {
            MODE_BREVE: self._build_breve,
            MODE_FORMAL: self._build_formal,
            MODE_CONTESTACION: self._build_contestacion,
            MODE_INCIDENTE: self._build_incidente,
            MODE_MEMORIAL: self._build_memorial,
            MODE_BASE_ARGUMENTAL: self._build_base_argumental,
        }

    def generate(
        self,
        query: str,
        mode: str = MODE_BREVE,
        reasoning_result: ReasoningResult | dict[str, Any] | None = None,
        procedural_plan: ProceduralPlan | dict[str, Any] | None = None,
        facts: dict[str, str] | None = None,
        jurisdiction: str | None = None,
        reasoning: dict[str, Any] | None = None,
        strategy: dict[str, Any] | None = None,
        case_structure: dict[str, Any] | None = None,
        normative_reasoning: dict[str, Any] | None = None,
        **extra: Any,
    ) -> GeneratedArgument:
        query = (query or "").strip()
        if not query:
            return GeneratedArgument(mode=mode, query=query, title="", warnings=["La consulta esta vacia; no se puede generar argumento."], missing_fields=["query"])
        if mode not in ALL_MODES:
            return GeneratedArgument(mode=mode, query=query, title="Modo desconocido", warnings=[f"Modo '{mode}' no reconocido."])
        self._last_section_warnings = []

        facts = facts or {}
        rr = self._coerce_reasoning_result(reasoning_result or reasoning, query)
        plan = self._coerce_procedural_plan(procedural_plan or strategy, query, jurisdiction)
        jur = jurisdiction or (rr.jurisdiction if rr else "jujuy")
        citations = self._collect_citations(rr)
        missing: list[str] = []
        jurisprudence_analysis = extra.get("jurisprudence_analysis") if isinstance(extra.get("jurisprudence_analysis"), dict) else {}
        jurisprudence_guard = self._build_jurisprudence_guard(jurisprudence_analysis)
        model_match = extra.get("model_match") if isinstance(extra.get("model_match"), dict) else {}
        style_directives = self._coerce_style_directives(model_match.get("style_directives"))
        style_blueprint = self._coerce_style_blueprint(model_match, mode)
        argument_strategy = self._coerce_argument_strategy(model_match.get("argument_strategy"))

        sections, title = self._dispatch[mode](
            query=query,
            reasoning_result=rr,
            procedural_plan=plan,
            facts=facts,
            jurisdiction=jur,
            citations=citations,
            missing=missing,
            normative_reasoning=normative_reasoning if isinstance(normative_reasoning, dict) else {},
            case_structure=case_structure if isinstance(case_structure, dict) else {},
            jurisprudence_analysis=jurisprudence_analysis,
            jurisprudence_guard=jurisprudence_guard,
            classification=extra.get("classification") if isinstance(extra.get("classification"), dict) else {},
            case_theory=extra.get("case_theory") if isinstance(extra.get("case_theory"), dict) else {},
            case_evaluation=extra.get("case_evaluation") if isinstance(extra.get("case_evaluation"), dict) else {},
            conflict_evidence=extra.get("conflict_evidence") if isinstance(extra.get("conflict_evidence"), dict) else {},
            evidence_reasoning_links=extra.get("evidence_reasoning_links") if isinstance(extra.get("evidence_reasoning_links"), dict) else {},
            style_directives=style_directives,
            style_blueprint=style_blueprint,
            argument_strategy=argument_strategy,
        )

        warnings = self._collect_warnings(rr, plan) + jurisprudence_guard["warnings"]
        warnings.extend(str(item).strip() for item in (model_match.get("warnings") or []) if str(item).strip())
        warnings.extend(str(item).strip() for item in getattr(style_blueprint, "warnings", []) if str(item).strip())
        warnings.extend(str(item).strip() for item in self._last_section_warnings if str(item).strip())
        if jur.lower() not in ("jujuy", ""):
            warnings.append(f"El documento fue generado para la jurisdiccion '{jur}'. Verificar aplicabilidad de las normas citadas.")
        if missing:
            warnings.append("El documento contiene campos sin datos: " + ", ".join(missing) + ". Reemplazar [DATO_FALTANTE] antes de presentar.")
        return GeneratedArgument(
            mode=mode,
            query=query,
            title=title,
            sections=sections,
            citations_used=citations,
            warnings=self._dedupe(warnings),
            missing_fields=missing,
            full_text=self._render_full_text(title, sections),
        )

    def _build_breve(self, *, query: str, reasoning_result: ReasoningResult | None, procedural_plan: ProceduralPlan | None, facts: dict[str, str], jurisdiction: str, citations: list[str], missing: list[str], **kwargs: Any) -> tuple[list[ArgumentSection], str]:
        _ = procedural_plan, facts
        blueprint = kwargs.get("style_blueprint")
        profile = self._build_writing_profile(kwargs.get("jurisprudence_guard") or {}, kwargs.get("style_directives"), blueprint, kwargs.get("argument_strategy"))
        title = f"Nota Legal Breve: {self._capitalise(query)}"
        context = self._build_generation_context(
            title=title,
            query=query,
            mode=MODE_BREVE,
            reasoning_result=reasoning_result,
            procedural_plan=procedural_plan,
            facts=facts,
            jurisdiction=jurisdiction,
            citations=citations,
            missing=missing,
            profile=profile,
            blueprint=blueprint,
            argument_strategy=kwargs.get("argument_strategy") or {},
            classification=kwargs.get("classification") or {},
            case_structure=kwargs.get("case_structure") or {},
            normative_reasoning=kwargs.get("normative_reasoning") or {},
            jurisprudence_analysis=kwargs.get("jurisprudence_analysis") or {},
            jurisprudence_guard=kwargs.get("jurisprudence_guard") or {},
            case_profile={},
            case_strategy={},
            case_theory=kwargs.get("case_theory") or {},
            conflict_evidence=kwargs.get("conflict_evidence") or {},
            evidence_reasoning_links=kwargs.get("evidence_reasoning_links") or {},
        )
        return self._build_sections_from_blueprint(blueprint, context), title

    def _build_formal(self, *, query: str, reasoning_result: ReasoningResult | None, procedural_plan: ProceduralPlan | None, facts: dict[str, str], jurisdiction: str, citations: list[str], missing: list[str], **kwargs: Any) -> tuple[list[ArgumentSection], str]:
        classification = kwargs.get("classification") or {}
        case_structure = kwargs.get("case_structure") or {}
        case_theory = kwargs.get("case_theory") or {}
        case_evaluation = kwargs.get("case_evaluation") or {}
        conflict = kwargs.get("conflict_evidence") or {}
        links = kwargs.get("evidence_reasoning_links") or {}
        nr = kwargs.get("normative_reasoning") or {}
        jurisprudence = kwargs.get("jurisprudence_analysis") or {}
        guard = kwargs.get("jurisprudence_guard") or {}
        blueprint = kwargs.get("style_blueprint")
        profile = self._build_writing_profile(guard, kwargs.get("style_directives"), blueprint, kwargs.get("argument_strategy"))
        case_profile = build_case_profile(query, classification, case_theory, conflict, nr, procedural_plan, facts)
        case_strategy = build_case_strategy(query, case_profile, case_theory, conflict, case_evaluation, procedural_plan, jurisprudence, reasoning_result)

        actor = facts.get("actor", _PLACEHOLDER)
        expediente = facts.get("expediente", _PLACEHOLDER)
        if actor == _PLACEHOLDER:
            missing.append("actor")
        if expediente == _PLACEHOLDER:
            missing.append("expediente")

        title = "Dictamen Juridico"
        context = self._build_generation_context(
            title="Dictamen Juridico",
            query=query,
            mode=MODE_FORMAL,
            reasoning_result=reasoning_result,
            procedural_plan=procedural_plan,
            facts=facts,
            jurisdiction=jurisdiction,
            citations=citations,
            missing=missing,
            profile=profile,
            blueprint=blueprint,
            argument_strategy=kwargs.get("argument_strategy") or {},
            classification=classification,
            case_structure=case_structure,
            normative_reasoning=nr,
            jurisprudence_analysis=jurisprudence,
            jurisprudence_guard=guard,
            case_profile=case_profile,
            case_strategy=case_strategy,
            case_theory=case_theory,
            conflict_evidence=conflict,
            evidence_reasoning_links=links,
        )
        return self._build_sections_from_blueprint(blueprint, context), "Dictamen Juridico"

    def _build_contestacion(self, *, query: str, reasoning_result: ReasoningResult | None, procedural_plan: ProceduralPlan | None, facts: dict[str, str], jurisdiction: str, citations: list[str], missing: list[str], **kwargs: Any) -> tuple[list[ArgumentSection], str]:
        _ = query, jurisdiction
        blueprint = kwargs.get("style_blueprint")
        profile = self._build_writing_profile(kwargs.get("jurisprudence_guard") or {}, kwargs.get("style_directives"), blueprint, kwargs.get("argument_strategy"))
        demandado = facts.get("demandado", _PLACEHOLDER)
        demandante = facts.get("demandante", _PLACEHOLDER)
        expediente = facts.get("expediente", _PLACEHOLDER)
        juzgado = facts.get("juzgado", _PLACEHOLDER)
        for field_name, value in [("demandado", demandado), ("demandante", demandante), ("expediente", expediente), ("juzgado", juzgado)]:
            if value == _PLACEHOLDER:
                missing.append(field_name)
        hechos = facts.get("hechos", _PLACEHOLDER)
        prueba = facts.get("prueba", _PLACEHOLDER)
        if hechos == _PLACEHOLDER:
            missing.append("hechos")
        if prueba == _PLACEHOLDER:
            missing.append("prueba")
        case_strategy = {
            "recommended_actions": [step.action for step in (procedural_plan.steps if procedural_plan else [])],
            "procedural_focus": [step.notes for step in (procedural_plan.steps if procedural_plan else []) if step.notes],
            "risk_analysis": list(procedural_plan.risks if procedural_plan else []),
            "conflict_summary": [hechos] if hechos != _PLACEHOLDER else [],
        }
        context = self._build_generation_context(
            title="Contestacion de Demanda",
            query=query,
            mode=MODE_CONTESTACION,
            reasoning_result=reasoning_result,
            procedural_plan=procedural_plan,
            facts=facts,
            jurisdiction=jurisdiction,
            citations=citations,
            missing=missing,
            profile=profile,
            blueprint=blueprint,
            argument_strategy=kwargs.get("argument_strategy") or {},
            classification=kwargs.get("classification") or {},
            case_structure=kwargs.get("case_structure") or {},
            normative_reasoning=kwargs.get("normative_reasoning") or {},
            jurisprudence_analysis=kwargs.get("jurisprudence_analysis") or {},
            jurisprudence_guard=kwargs.get("jurisprudence_guard") or {},
            case_profile={},
            case_strategy=case_strategy,
            case_theory=kwargs.get("case_theory") or {},
            conflict_evidence=kwargs.get("conflict_evidence") or {},
            evidence_reasoning_links=kwargs.get("evidence_reasoning_links") or {},
        )
        return self._build_sections_from_blueprint(blueprint, context), "Contestacion de Demanda"

    def _build_incidente(self, *, query: str, reasoning_result: ReasoningResult | None, procedural_plan: ProceduralPlan | None, facts: dict[str, str], jurisdiction: str, citations: list[str], missing: list[str], **kwargs: Any) -> tuple[list[ArgumentSection], str]:
        _ = jurisdiction
        guard = kwargs.get("jurisprudence_guard") or {}
        blueprint = kwargs.get("style_blueprint")
        profile = self._build_writing_profile(guard, kwargs.get("style_directives"), blueprint, kwargs.get("argument_strategy"))
        tipo = facts.get("tipo_incidente", self._infer_incident_type(query))
        requirente = facts.get("requirente", _PLACEHOLDER)
        expediente = facts.get("expediente", _PLACEHOLDER)
        juzgado = facts.get("juzgado", _PLACEHOLDER)
        for field_name, value in [("requirente", requirente), ("expediente", expediente), ("juzgado", juzgado)]:
            if value == _PLACEHOLDER:
                missing.append(field_name)
        context = self._build_generation_context(
            title=f"Incidente: {self._capitalise(tipo or query)}",
            query=query,
            mode=MODE_INCIDENTE,
            reasoning_result=reasoning_result,
            procedural_plan=procedural_plan,
            facts=facts,
            jurisdiction=jurisdiction,
            citations=citations,
            missing=missing,
            profile=profile,
            blueprint=blueprint,
            argument_strategy=kwargs.get("argument_strategy") or {},
            classification=kwargs.get("classification") or {},
            case_structure=kwargs.get("case_structure") or {},
            normative_reasoning=kwargs.get("normative_reasoning") or {},
            jurisprudence_analysis=kwargs.get("jurisprudence_analysis") or {},
            jurisprudence_guard=guard,
            case_profile={},
            case_strategy={},
            case_theory=kwargs.get("case_theory") or {},
            conflict_evidence=kwargs.get("conflict_evidence") or {},
            evidence_reasoning_links=kwargs.get("evidence_reasoning_links") or {},
            incident_type=tipo,
        )
        return self._build_sections_from_blueprint(blueprint, context), f"Incidente: {self._capitalise(tipo or query)}"

    def _build_memorial(self, *, query: str, reasoning_result: ReasoningResult | None, procedural_plan: ProceduralPlan | None, facts: dict[str, str], jurisdiction: str, citations: list[str], missing: list[str], **kwargs: Any) -> tuple[list[ArgumentSection], str]:
        guard = kwargs.get("jurisprudence_guard") or {}
        jurisprudence = kwargs.get("jurisprudence_analysis") or {}
        case_theory = kwargs.get("case_theory") or {}
        case_evaluation = kwargs.get("case_evaluation") or {}
        conflict = kwargs.get("conflict_evidence") or {}
        links = kwargs.get("evidence_reasoning_links") or {}
        blueprint = kwargs.get("style_blueprint")
        profile = self._build_writing_profile(guard, kwargs.get("style_directives"), blueprint, kwargs.get("argument_strategy"))
        case_profile = build_case_profile(query, kwargs.get("classification") or {}, case_theory, conflict, kwargs.get("normative_reasoning") or {}, procedural_plan, facts)
        case_strategy = build_case_strategy(query, case_profile, case_theory, conflict, case_evaluation, procedural_plan, jurisprudence, reasoning_result)
        requirente = facts.get("requirente", _PLACEHOLDER)
        expediente = facts.get("expediente", _PLACEHOLDER)
        juzgado = facts.get("juzgado", _PLACEHOLDER)
        for field_name, value in [("requirente", requirente), ("expediente", expediente), ("juzgado", juzgado)]:
            if value == _PLACEHOLDER:
                missing.append(field_name)
        context = self._build_generation_context(
            title=f"Memorial: {self._capitalise(query)}",
            query=query,
            mode=MODE_MEMORIAL,
            reasoning_result=reasoning_result,
            procedural_plan=procedural_plan,
            facts=facts,
            jurisdiction=jurisdiction,
            citations=citations,
            missing=missing,
            profile=profile,
            blueprint=blueprint,
            argument_strategy=kwargs.get("argument_strategy") or {},
            classification=kwargs.get("classification") or {},
            case_structure=kwargs.get("case_structure") or {},
            normative_reasoning=kwargs.get("normative_reasoning") or {},
            jurisprudence_analysis=jurisprudence,
            jurisprudence_guard=guard,
            case_profile=case_profile,
            case_strategy=case_strategy,
            case_theory=case_theory,
            conflict_evidence=conflict,
            evidence_reasoning_links=links,
        )
        return self._build_sections_from_blueprint(blueprint, context), f"Memorial: {self._capitalise(query)}"

    def _build_base_argumental(self, *, query: str, reasoning_result: ReasoningResult | None, procedural_plan: ProceduralPlan | None, facts: dict[str, str], jurisdiction: str, citations: list[str], missing: list[str], **kwargs: Any) -> tuple[list[ArgumentSection], str]:
        _ = facts, jurisdiction, missing
        guard = kwargs.get("jurisprudence_guard") or {}
        jurisprudence = kwargs.get("jurisprudence_analysis") or {}
        case_theory = kwargs.get("case_theory") or {}
        case_evaluation = kwargs.get("case_evaluation") or {}
        conflict = kwargs.get("conflict_evidence") or {}
        links = kwargs.get("evidence_reasoning_links") or {}
        nr = kwargs.get("normative_reasoning") or {}
        blueprint = kwargs.get("style_blueprint")
        profile = self._build_writing_profile(guard, kwargs.get("style_directives"), blueprint, kwargs.get("argument_strategy"))
        case_profile = build_case_profile(query, kwargs.get("classification") or {}, case_theory, conflict, nr, procedural_plan, facts)
        case_strategy = build_case_strategy(query, case_profile, case_theory, conflict, case_evaluation, procedural_plan, jurisprudence, reasoning_result)
        context = self._build_generation_context(
            title=f"Base Argumental: {self._capitalise(query)}",
            query=query,
            mode=MODE_BASE_ARGUMENTAL,
            reasoning_result=reasoning_result,
            procedural_plan=procedural_plan,
            facts=facts,
            jurisdiction=jurisdiction,
            citations=citations,
            missing=missing,
            profile=profile,
            blueprint=blueprint,
            argument_strategy=kwargs.get("argument_strategy") or {},
            classification=kwargs.get("classification") or {},
            case_structure=kwargs.get("case_structure") or {},
            normative_reasoning=nr,
            jurisprudence_analysis=jurisprudence,
            jurisprudence_guard=guard,
            case_profile=case_profile,
            case_strategy=case_strategy,
            case_theory=case_theory,
            conflict_evidence=conflict,
            evidence_reasoning_links=links,
        )
        return self._build_sections_from_blueprint(blueprint, context), f"Base Argumental: {self._capitalise(query)}"

    def _build_generation_context(self, **kwargs: Any) -> dict[str, Any]:
        context = dict(kwargs)
        context.setdefault("section_warnings", [])
        return context

    def _build_sections_from_blueprint(self, blueprint: StyleBlueprint, context: dict[str, Any]) -> list[ArgumentSection]:
        registry = self._section_registry()
        sections: list[ArgumentSection] = []
        seen_keys: set[str] = set()

        for section_key in blueprint.section_order:
            template = dict(blueprint.section_templates.get(section_key, {}))
            behavior = self._resolve_section_behavior(template, context["profile"], context.get("argument_strategy") or {})
            builder = registry.get(section_key)
            if builder is None:
                if behavior["required"]:
                    context["section_warnings"].append(f"Section warning: no existe builder para la seccion requerida '{section_key}'.")
                continue
            section = builder(context, behavior)
            if section is None:
                if behavior["required"] or behavior["include_if_empty"]:
                    fallback = self._build_missing_required_section(section_key, context)
                    if fallback is not None:
                        sections.append(fallback)
                        seen_keys.add(section_key)
                        context["section_warnings"].append(f"Section warning: se aplico fallback para la seccion requerida '{section_key}'.")
                    else:
                        context["section_warnings"].append(f"Section warning: no pudo construirse la seccion requerida '{section_key}'.")
                continue
            sections.append(self._apply_section_template(section, behavior))
            seen_keys.add(section_key)

        for section_key in blueprint.required_sections:
            if section_key in seen_keys:
                continue
            builder = registry.get(section_key)
            if builder is None:
                context["section_warnings"].append(f"Section warning: falta builder para la seccion requerida '{section_key}'.")
                continue
            behavior = self._resolve_section_behavior(dict(blueprint.section_templates.get(section_key, {})), context["profile"], context.get("argument_strategy") or {})
            section = builder(context, behavior)
            if section is not None:
                sections.append(self._apply_section_template(section, behavior))
            else:
                fallback = self._build_missing_required_section(section_key, context)
                if fallback is not None:
                    sections.append(fallback)
                context["section_warnings"].append(f"Section warning: se resolvio tardio el requerimiento de '{section_key}' con fallback prudente.")

        self._last_section_warnings = list(context.get("section_warnings") or [])
        return sections

    def _resolve_section_behavior(self, template: dict[str, Any], profile: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
        behavior = {
            "required": bool(template.get("required", False)),
            "include_if_empty": bool(template.get("include_if_empty", False)),
            "max_paragraphs": int(template.get("max_paragraphs", 3) or 3),
            "density": str(template.get("density") or profile.get("content_rules", {}).get("normative_density") or "standard").strip(),
            "urgency": str(template.get("urgency") or profile.get("urgency_emphasis") or "conditional").strip(),
            "style": str(template.get("style") or profile.get("facts_style") or "default").strip(),
            "proof_priority": list(template.get("proof_priority") or strategy.get("proof_priority") or profile.get("proof_priority") or []),
            "risk_tolerance": str(template.get("risk_tolerance") or strategy.get("risk_tolerance") or profile.get("risk_tolerance") or "medium").strip(),
            "focus": str(template.get("focus") or strategy.get("focus") or profile.get("strategy_focus") or "").strip(),
            "argument_style": str(template.get("argument_style") or profile.get("content_rules", {}).get("argument_style") or "prudential").strip(),
            "include_jurisprudence": str(template.get("include_jurisprudence") or profile.get("content_rules", {}).get("include_jurisprudence") or "auto").strip(),
            "normative_anchor": str(template.get("normative_anchor") or strategy.get("normative_anchor") or profile.get("normative_anchor") or "").strip(),
        }
        if behavior["focus"] == "urgency" and behavior["urgency"] == "conditional":
            behavior["urgency"] = "high"
        if behavior["normative_anchor"] == "strong" and behavior["density"] == "standard":
            behavior["density"] = "high"
        if behavior["normative_anchor"] == "light" and behavior["density"] == "high":
            behavior["density"] = "standard"
        return behavior

    def _section_registry(self) -> dict[str, Any]:
        return {
            "consulta": self._section_consulta,
            "analisis": self._section_analisis,
            "conclusion": self._section_conclusion,
            "encabezado": self._section_encabezado,
            "objeto": self._section_objeto,
            "hechos_decisivos": self._section_hechos_decisivos,
            "marco_normativo": self._section_marco_normativo,
            "cautela_jurisprudencial": self._section_cautela_jurisprudencial,
            "inferencias_juridicas": self._section_inferencias_juridicas,
            "reglas_aplicadas": self._section_reglas_aplicadas,
            "requisitos_soporte": self._section_requisitos_soporte,
            "analisis_juridico": self._section_analisis_juridico,
            "requisitos": self._section_requisitos,
            "conflicto_prueba": self._section_conflicto_prueba,
            "trazabilidad_probatoria": self._section_trazabilidad_probatoria,
            "jurisprudencia": self._section_jurisprudencia,
            "riesgo_procesal": self._section_riesgo_procesal,
            "pasos_procesales": self._section_pasos_procesales,
            "limitaciones": self._section_limitaciones,
            "introduccion": self._section_introduccion,
            "punto_en_debate": self._section_punto_en_debate,
            "fundamentos_derecho": self._section_fundamentos_derecho,
            "hechos_relevantes": self._section_hechos_relevantes,
            "desarrollo_estrategico": self._section_desarrollo_estrategico,
            "personeria": self._section_personeria,
            "relacion_hechos": self._section_relacion_hechos,
            "derecho": self._section_derecho,
            "ofrecimiento_prueba": self._section_ofrecimiento_prueba,
            "linea_defensa": self._section_linea_defensa,
            "fundamentos": self._section_fundamentos,
            "medidas_urgentes": self._section_medidas_urgentes,
            "petitorio": self._section_petitorio,
            "tesis_principal": self._section_tesis_principal,
            "hecho_decisivo": self._section_hecho_decisivo,
            "argumentos_normativos": self._section_argumentos_normativos,
            "riesgos_contraargumentos": self._section_riesgos_contraargumentos,
            "informacion_faltante": self._section_informacion_faltante,
            "proximos_pasos": self._section_proximos_pasos,
            "notas_estrategicas": self._section_notas_estrategicas,
            "linea_accion_inmediata": self._section_linea_accion_inmediata,
            "cierre_estrategico": self._section_cierre_estrategico,
        }

    def _apply_section_template(self, section: ArgumentSection, template: dict[str, Any]) -> ArgumentSection:
        max_paragraphs = int(template.get("max_paragraphs", 0) or 0)
        if max_paragraphs <= 0:
            return section
        paragraphs = [part.strip() for part in section.content.split("\n\n") if part.strip()]
        if len(paragraphs) <= max_paragraphs:
            return section
        return ArgumentSection(
            title=section.title,
            content="\n\n".join(paragraphs[:max_paragraphs]),
            cites=section.cites,
        )

    def _build_missing_required_section(self, section_key: str, context: dict[str, Any]) -> ArgumentSection | None:
        labels = {
            "conclusion": "Conclusion",
            "petitorio": "Petitorio",
            "objeto": "Objeto",
            "jurisprudencia": "Jurisprudencia relevante",
            "cautela_jurisprudencial": "Cautela Jurisprudencial",
        }
        label = labels.get(section_key)
        if label is None:
            return None
        return ArgumentSection(label, "Seccion requerida sin contenido suficiente en el contexto disponible.")

    def _section_consulta(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        return ArgumentSection("Consulta", f"En relacion a la consulta sobre '{context['query']}', {_SOFTENER_PRINCIPIO} corresponde analizar la normativa aplicable en la jurisdiccion de {context['jurisdiction']}.")

    def _section_analisis(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        rr = context.get("reasoning_result")
        max_items = self._normative_items_from_template(context, template, default=3)
        content = " ".join(self._format_normative_grounds(rr, max_items)) or "No se encontraron normas de aplicacion directa en el contexto disponible."
        if template.get("argument_style") == "assertive":
            content = "El analisis disponible permite sostener una linea inicial con apoyo identificable. " + content
        elif template.get("argument_style") == "exploratory":
            content = "El analisis debe leerse como exploratorio y sujeto a contraste con mas hechos y prueba. " + content
        return ArgumentSection("Analisis", content, list(context.get("citations") or []))

    def _section_conclusion(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        rr = context.get("reasoning_result")
        guard = context.get("jurisprudence_guard") or {}
        conflict = context.get("conflict_evidence") or {}
        case_theory = context.get("case_theory") or {}
        case_profile = context.get("case_profile") or {}
        text = self._build_conclusion_text(context["mode"], rr.confidence if rr else "desconocida", guard, conflict, context.get("procedural_plan"), case_theory, case_profile, context["profile"])
        title = "Cierre Estrategico" if context["mode"] == MODE_BASE_ARGUMENTAL else "Conclusion"
        return ArgumentSection(title, text)

    def _section_encabezado(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        mode = context["mode"]
        facts = context.get("facts") or {}
        if mode == MODE_FORMAL:
            classification = context.get("classification") or {}
            case_structure = context.get("case_structure") or {}
            rr = context.get("reasoning_result")
            actor = facts.get("actor", _PLACEHOLDER)
            expediente = facts.get("expediente", _PLACEHOLDER)
            return ArgumentSection("Encabezado", "DICTAMEN JURIDICO\n" + f"Consulta: {self._resolve_formal_subject(context['query'], classification, case_structure)}\n" + f"Fuero: {self._resolve_formal_forum(classification, case_structure, rr)}\n" + f"Jurisdiccion: {self._format_header_value(context['jurisdiction'])}\n" + f"Referencia: {self._capitalise(context['query'])}\n" + f"Parte requirente: {actor}\n" + f"Expediente N.o: {expediente}")
        if mode == MODE_MEMORIAL:
            return ArgumentSection("Encabezado", f"EXCMO. {facts.get('juzgado', _PLACEHOLDER)}:\n\n{facts.get('requirente', _PLACEHOLDER)}, en autos '{facts.get('expediente', _PLACEHOLDER)}', presenta memorial y dice:")
        if mode == MODE_CONTESTACION:
            return ArgumentSection("Encabezado", f"EXCMO. {facts.get('juzgado', _PLACEHOLDER)}:\n\n{facts.get('demandado', _PLACEHOLDER)}, parte demandada en autos '{facts.get('expediente', _PLACEHOLDER)}', iniciados por {facts.get('demandante', _PLACEHOLDER)}, a V.S. respetuosamente dice:")
        if mode == MODE_INCIDENTE:
            return ArgumentSection("Encabezado", f"EXCMO. {facts.get('juzgado', _PLACEHOLDER)}:\n\n{facts.get('requirente', _PLACEHOLDER)}, en autos '{facts.get('expediente', _PLACEHOLDER)}', a V.S. respetuosamente dice:")
        return ArgumentSection("Encabezado", context["title"])

    def _section_objeto(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        mode = context["mode"]
        style_prefix = self._analysis_style_prefix(template)
        if mode == MODE_FORMAL:
            return ArgumentSection("Objeto", f"El presente dictamen tiene por objeto analizar la cuestion relativa a '{context['query']}' a fin de brindar orientacion juridica fundada en las normas vigentes de la jurisdiccion de {context['jurisdiction']}. {style_prefix}{context['profile']['opening_line']} {context['profile']['analysis_directive']}".strip())
        if mode == MODE_CONTESTACION:
            facts = context.get("facts") or {}
            return ArgumentSection("II. Objeto", f"Que por el presente escrito la parte demandada contesta la demanda interpuesta por {facts.get('demandante', _PLACEHOLDER)} en relacion a: {facts.get('objeto', context['query'])}.")
        if mode == MODE_INCIDENTE:
            return ArgumentSection("I. Objeto", f"Que por el presente escrito se promueve incidente de {context.get('incident_type', self._infer_incident_type(context['query']))}, {_SOFTENER_SP}.")
        return ArgumentSection("Objeto", context['profile']['opening_line'])

    def _section_hechos_decisivos(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_strategic_case_section("Punto de Conflicto y Hechos Decisivos", context.get("case_strategy") or {}, context["profile"])

    def _section_marco_normativo(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        rr = context.get("reasoning_result")
        content = "\n".join(self._format_normative_grounds(rr, self._normative_items_from_template(context, template, default=5))) or "Sin normas de referencia en contexto."
        return ArgumentSection("Marco Normativo", content, list(context.get("citations") or []))

    def _section_cautela_jurisprudencial(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        if not self._should_include_jurisprudence(context, template, allow_never=True):
            return None
        return self._build_jurisprudence_caution_section(context.get("jurisprudence_guard") or {})

    def _section_inferencias_juridicas(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        items = [f"- {x}" for x in (context.get("normative_reasoning") or {}).get("inferences", []) if str(x).strip()]
        return ArgumentSection("Inferencias Juridicas", "\n".join(items)) if items else None

    def _section_reglas_aplicadas(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        lines: list[str] = []
        for rule in (context.get("normative_reasoning") or {}).get("applied_rules", []):
            if isinstance(rule, dict) and str(rule.get("article") or "").strip() and str(rule.get("effect") or "").strip():
                lines.append(f"- Art. {rule.get('article')} ({str(rule.get('source') or '').strip()}): {rule.get('effect')}")
        return ArgumentSection("Reglas Aplicadas y Efectos", "\n".join(lines), list(context.get("citations") or [])) if lines else None

    def _section_requisitos_soporte(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_requirements_support_section(context.get("normative_reasoning") or {}, context.get("evidence_reasoning_links") or {}, context.get("case_profile") or {}, context["profile"], behavior=template)

    def _section_analisis_juridico(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        case_strategy = context.get("case_strategy") or {}
        content = str(case_strategy.get("strategic_narrative") or "Analisis juridico pendiente de desarrollo con el contexto disponible.")
        if template.get("focus") == "damage":
            content = "El eje debe pasar por el perjuicio concreto, su acreditacion y su cobertura probatoria. " + content
        elif template.get("focus") == "formalism":
            content = "El eje debe pasar por el encuadre normativo, los requisitos y la consistencia tecnica del planteo. " + content
        return ArgumentSection("Analisis Juridico", f"{self._analysis_style_prefix(template)}{content}".strip())

    def _section_requisitos(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        items = [f"- {x}" for x in (context.get("normative_reasoning") or {}).get("requirements", []) if str(x).strip()]
        return ArgumentSection("Requisitos", "\n".join(items)) if items else None

    def _section_conflicto_prueba(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        title = "Hecho Decisivo y Punto de Conflicto" if context["mode"] == MODE_BASE_ARGUMENTAL else "Conflicto y Prueba"
        if context["mode"] == MODE_BASE_ARGUMENTAL:
            return self._build_strategic_case_section(title, context.get("case_strategy") or {}, context["profile"])
        return self._build_strategy_list_section(title, (context.get("case_strategy") or {}).get("conflict_summary") or [])

    def _section_trazabilidad_probatoria(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        section = self._format_evidence_traceability(context.get("evidence_reasoning_links") or {})
        if section is None:
            return None
        priorities = template.get("proof_priority") or []
        if priorities:
            content = f"Prioridad probatoria del modelo: {', '.join(priorities)}.\n\n{section.content}"
            return ArgumentSection(section.title, content, section.cites)
        return section

    def _section_jurisprudencia(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        if not self._should_include_jurisprudence(context, template):
            return None
        section = self._format_jurisprudential_orientation(context.get("jurisprudence_analysis") or {})
        if section is not None:
            return section
        if template.get("include_jurisprudence") == "always":
            context["section_warnings"].append("Section warning: include_jurisprudence='always' no pudo cumplirse por falta de base suficiente.")
            return ArgumentSection("Jurisprudencia relevante", "No hay base jurisprudencial suficiente para incluir una seccion sustantiva; corresponde sostener el planteo con norma, hechos y prueba.")
        return None

    def _section_riesgo_procesal(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_strategy_list_section("Riesgo Procesal y Cobertura Probatoria", (context.get("case_strategy") or {}).get("risk_analysis") or [])

    def _section_pasos_procesales(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_action_section("Pasos Procesales Recomendados", context.get("case_strategy") or {}, context["profile"], behavior=template)

    def _section_limitaciones(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        rr = context.get("reasoning_result")
        if rr and rr.limitations:
            return ArgumentSection("Limitaciones", "\n".join(f"- {x}" for x in rr.limitations if str(x).strip()))
        return None

    def _section_introduccion(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        return ArgumentSection("Introduccion", f"El presente memorial tiene por objeto desarrollar los fundamentos de derecho relacionados con: '{context['query']}', en el marco del proceso tramitado ante este honorable juzgado de {context['jurisdiction']}. {context['profile']['opening_line']}")

    def _section_punto_en_debate(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_strategic_case_section("Punto en Debate", context.get("case_strategy") or {}, context["profile"])

    def _section_fundamentos_derecho(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        sections = self._build_legal_argument_sections(context.get("reasoning_result"), list(context.get("citations") or []), self._normative_items_from_template(context, template, default=6))
        if not sections:
            return None
        merged = "\n\n".join(f"{section.title}\n{section.content}" for section in sections)
        cites: list[str] = []
        for section in sections:
            cites.extend(section.cites)
        return ArgumentSection("Fundamentos de Derecho", merged, self._dedupe(cites))

    def _section_hechos_relevantes(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        hechos = str((context.get("facts") or {}).get("hechos") or "").strip()
        if not hechos:
            return None
        return ArgumentSection("Hechos Relevantes", f"{context['profile']['facts_directive']} {hechos}".strip())

    def _section_desarrollo_estrategico(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        return ArgumentSection("Desarrollo Estrategico", str((context.get("case_strategy") or {}).get("strategic_narrative") or ""))

    def _section_personeria(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        facts = context.get("facts") or {}
        return ArgumentSection("I. Personeria", f"Que el suscripto se presenta en caracter de parte demandada en los presentes autos, con domicilio procesal en {facts.get('domicilio_procesal', _PLACEHOLDER)}.")

    def _section_relacion_hechos(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        facts = context.get("facts") or {}
        hechos = facts.get("hechos", _PLACEHOLDER)
        return ArgumentSection("III. Relacion de Hechos", f"{context['profile']['facts_directive']} En orden a los hechos invocados en la demanda, la parte demandada manifiesta: {hechos}.\n\nSe niegan expresamente todos los hechos no reconocidos.".strip())

    def _section_derecho(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        rr = context.get("reasoning_result")
        content = "\n".join(self._format_normative_grounds(rr, self._normative_items_from_template(context, template, default=5))) or "Las normas aplicables seran indicadas en el correspondiente informe de ley."
        return ArgumentSection("IV. Derecho", content, list(context.get("citations") or []))

    def _section_ofrecimiento_prueba(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        facts = context.get("facts") or {}
        proof_priority = template.get("proof_priority") or []
        suffix = f" Prioridad sugerida: {', '.join(proof_priority)}." if proof_priority else ""
        return ArgumentSection("V. Ofrecimiento de Prueba", f"La parte demandada ofrece la siguiente prueba: {facts.get('prueba', _PLACEHOLDER)}.{suffix}".strip())

    def _section_linea_defensa(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        plan = context.get("procedural_plan")
        if plan and not plan.is_empty():
            return ArgumentSection("VI. Linea de Defensa Inmediata", self._format_steps(plan.steps[:3]))
        return None

    def _section_fundamentos(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        rr = context.get("reasoning_result")
        content = "\n".join(self._format_normative_grounds(rr, self._normative_items_from_template(context, template, default=4))) or "Los fundamentos normativos seran desarrollados en el cuerpo del incidente."
        if context["profile"]["analysis_directive"]:
            content = f"{context['profile']['analysis_directive']}\n\n{content}"
        if (context.get("jurisprudence_guard") or {}).get("avoid_assertions"):
            content += "\n\nLa orientacion jurisprudencial disponible no debe presentarse como linea consolidada; corresponde enfatizar hechos, urgencia, presupuesto legal y respaldo probatorio."
        return ArgumentSection("II. Fundamentos", content, list(context.get("citations") or []))

    def _section_medidas_urgentes(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        plan = context.get("procedural_plan")
        if plan and not plan.is_empty():
            immediate = [step for step in plan.steps if step.urgency == "immediate"]
            if immediate:
                return ArgumentSection("III. Medidas Urgentes", self._format_steps(immediate))
        return None

    def _section_petitorio(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        mode = context["mode"]
        if mode == MODE_CONTESTACION:
            lines = [
                "Por todo lo expuesto, a V.S. solicita:",
                "1. Se tenga por contestada la presente demanda.",
                "2. Oportunamente, se dicte sentencia rechazando la demanda.",
                "3. Con costas.",
                "",
                "Proveer de conformidad, sera justicia.",
            ]
            return ArgumentSection("VI. Petitorio", self._compose_petitum(context["profile"], lines))
        if mode == MODE_INCIDENTE:
            lines = [
                "Por lo expuesto, se solicita:",
                f"1. Se haga lugar al presente incidente de {context.get('incident_type', self._infer_incident_type(context['query']))}.",
                "2. Con costas.",
                "",
                "Proveer de conformidad, sera justicia.",
            ]
            return ArgumentSection("IV. Petitorio", self._compose_petitum(context["profile"], lines))
        text = self._build_conclusion_text(mode, context.get("reasoning_result").confidence if context.get("reasoning_result") else "desconocida", context.get("jurisprudence_guard") or {}, context.get("conflict_evidence") or {}, context.get("procedural_plan"), context.get("case_theory") or {}, context.get("case_profile") or {}, context["profile"])
        return ArgumentSection("Petitorio", self._compose_petitum(context["profile"], [text], behavior=template))

    def _section_tesis_principal(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        rr = context.get("reasoning_result")
        thesis = (rr.short_answer if rr else "") or f"Posicion juridica pendiente de definicion para: {context['query']}."
        if context["profile"]["supports_jurisprudential_density"]:
            thesis += " La linea se apoya en precedentes reales recuperados del corpus que operan como eje del planteo y deben conectarse con los hechos decisivos y la prueba disponible."
        elif context["profile"]["uses_secondary_jurisprudence"]:
            thesis += " La jurisprudencia disponible cumple un rol de apoyo secundario; la solidez de la tesis depende sobre todo de la norma positiva y de la acreditacion de los hechos."
        elif (context.get("jurisprudence_guard") or {}).get("avoid_assertions"):
            thesis = f"Posicion juridica inicial y revisable para: {context['query']}. La tesis debe sostenerse sin respaldo jurisprudencial consolidado y requiere mejor base factica y probatoria."
        focus = template.get("focus") or context["profile"].get("strategy_focus") or ""
        if focus == "urgency":
            thesis += " La estrategia prioriza tutela inmediata y cobertura de dano actual."
        elif focus == "formalism":
            thesis += " La estrategia exige cierre normativo y procesal antes de expandir el pedido."
        elif focus == "damage":
            thesis += " La estrategia prioriza mostrar el impacto material y la necesidad de cobertura concreta."
        return ArgumentSection("Tesis Principal", thesis)

    def _section_hecho_decisivo(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_strategic_case_section("Hecho Decisivo y Punto de Conflicto", context.get("case_strategy") or {}, context["profile"])

    def _section_argumentos_normativos(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        rr = context.get("reasoning_result")
        nr = context.get("normative_reasoning") or {}
        arguments: list[str] = []
        if rr and rr.normative_grounds:
            for index, ng in enumerate(rr.normative_grounds[:self._normative_items_from_template(context, template, default=6)], 1):
                arguments.append(f"{index}. {ng.citation()}\n   \"{ng.texto[:250].rstrip()}...\"" + (f"\n   Relevancia: {ng.relevance_note}" if ng.relevance_note else ""))
        for rule in nr.get("applied_rules") or []:
            if isinstance(rule, dict) and str(rule.get("article") or "").strip() and str(rule.get("effect") or "").strip():
                arguments.append(f"- Art. {rule.get('article')} ({str(rule.get('source') or '').strip()}): {rule.get('effect')}")
        normative_anchor = template.get("normative_anchor") or context["profile"].get("normative_anchor") or ""
        if normative_anchor == "strong":
            arguments.insert(0, "La estrategia del modelo exige anclaje normativo fuerte antes de escalar la pretension.")
        return ArgumentSection("Argumentos Normativos", "\n".join(arguments) or "- Sin normas de sustento encontradas en el contexto.", list(context.get("citations") or []))

    def _section_riesgos_contraargumentos(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_strategy_list_section("Riesgos y Contra-argumentos", (context.get("case_strategy") or {}).get("risk_analysis") or [])

    def _section_informacion_faltante(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        items = self._collect_missing_information(context.get("procedural_plan"), context.get("case_theory") or {})
        return ArgumentSection("Informacion Faltante", "\n".join(f"- {x}" for x in items)) if items else None

    def _section_proximos_pasos(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_action_section("Proximos Pasos Procesales", context.get("case_strategy") or {}, context["profile"], behavior=template)

    def _section_notas_estrategicas(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        plan = context.get("procedural_plan")
        if plan and plan.strategic_notes:
            return ArgumentSection("Notas Estrategicas", plan.strategic_notes)
        return None

    def _section_linea_accion_inmediata(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection | None:
        return self._build_action_section("Linea de Accion Inmediata", context.get("case_strategy") or {}, context["profile"], limit=2, behavior=template)

    def _section_cierre_estrategico(self, context: dict[str, Any], template: dict[str, Any]) -> ArgumentSection:
        return self._section_conclusion(context, template)

    def _should_include_jurisprudence(self, context: dict[str, Any], template: dict[str, Any], allow_never: bool = False) -> bool:
        # Priority: template (from behavior) > profile content_rules > default "auto"
        template_rule = str(template.get("include_jurisprudence") or "").strip()
        profile_rule = str((context["profile"].get("content_rules") or {}).get("include_jurisprudence") or "").strip()
        rule = template_rule or profile_rule or "auto"
        if rule == "always":
            has_material = bool(context.get("jurisprudence_analysis"))
            if not has_material and allow_never:
                context["section_warnings"].append("Section warning: se requirio jurisprudencia pero no hay base suficiente.")
            return True
        if rule == "never":
            return False
        return bool(context.get("jurisprudence_analysis"))

    def _normative_items_from_template(self, context: dict[str, Any], template: dict[str, Any], default: int) -> int:
        density = str(template.get("density") or (context["profile"].get("content_rules") or {}).get("normative_density") or "").strip()
        if density == "high":
            return default + 2
        if density == "low":
            return max(2, default - 2)
        if str(context["profile"].get("normative_anchor") or "").strip() == "light":
            return max(2, default - 1)
        return self._resolve_normative_limit(context["profile"], default)

    @staticmethod
    def _analysis_style_prefix(template: dict[str, Any]) -> str:
        style = str(template.get("argument_style") or "prudential").strip()
        if style == "assertive":
            return "Con mayor firmeza argumental, "
        if style == "exploratory":
            return "De forma exploratoria y revisable, "
        return ""

    def _build_writing_profile(self, jurisprudence_guard: dict[str, Any], style_directives: dict[str, Any] | None = None, style_blueprint: StyleBlueprint | None = None, argument_strategy: dict[str, Any] | None = None) -> dict[str, Any]:
        source_quality = str(jurisprudence_guard.get("source_quality") or "none").strip()
        strength = str(jurisprudence_guard.get("strength") or "none").strip()
        style = style_directives or {}
        bp = style_blueprint
        strategy = argument_strategy or {}
        profile = {
            "source_quality": source_quality,
            "strength": strength,
            "supports_jurisprudential_density": source_quality == "real" and strength == "strong",
            "uses_secondary_jurisprudence": source_quality == "legacy",
            "tone": (bp.tone if bp else "") or str(style.get("tone") or "balanced_prudent").strip(),
            "argument_density": (bp.argument_density if bp else "") or str(style.get("argument_density") or "standard").strip(),
            "facts_style": (bp.facts_style if bp else "") or str(style.get("facts_style") or "concrete").strip(),
            "petitum_style": (bp.petition_style if bp else "") or str(style.get("petitum_style") or "prudent").strip(),
            "structure": (bp.structure_cues if bp else []) or [str(item).strip() for item in (style.get("structure") or []) if str(item).strip()],
            "analysis_directive": (bp.analysis_directive if bp else "") or str(style.get("analysis_directive") or "").strip(),
            "facts_directive": (bp.facts_directive if bp else "") or str(style.get("facts_directive") or "").strip(),
            "petitum_directive": (bp.petitum_directive if bp else "") or str(style.get("petitum_directive") or "").strip(),
            "section_cues": (bp.section_cues if bp else []) or [str(item).strip() for item in (style.get("section_cues") or []) if str(item).strip()],
            "opening_line": "La pieza debe jerarquizar el conflicto, el hecho decisivo, la cobertura probatoria y el riesgo procesal.",
            # Blueprint structural fields
            "section_order": bp.section_order if bp else [],
            "required_sections": bp.required_sections if bp else [],
            "urgency_emphasis": (bp.urgency_emphasis if bp else "none"),
            "normative_quote_density": (bp.normative_quote_density if bp else "standard"),
            "opening_style": (bp.opening_style if bp else ""),
            "section_templates": bp.section_templates if bp else {},
            "content_rules": bp.content_rules if bp else {},
            "strategy_focus": str(strategy.get("focus") or "").strip(),
            "risk_tolerance": str(strategy.get("risk_tolerance") or "medium").strip(),
            "proof_priority": [str(item).strip() for item in (strategy.get("proof_priority") or []) if str(item).strip()],
            "normative_anchor": str(strategy.get("normative_anchor") or "").strip(),
        }
        if profile["supports_jurisprudential_density"]:
            profile["opening_line"] = "La pieza debe articular los precedentes reales como columna del planteo, conectandolos directamente con el conflicto y la prueba del caso."
        elif profile["uses_secondary_jurisprudence"]:
            profile["opening_line"] = "La pieza debe usar la jurisprudencia disponible como apoyo secundario y sostener el eje en norma positiva, hechos y prueba."
        elif source_quality in {"fallback", "none"}:
            profile["opening_line"] = "La pieza no debe apoyarse en jurisprudencia como respaldo consolidado y tiene que concentrarse en requisitos legales, hechos decisivos, prueba faltante y pasos inmediatos."
        opening_override = (bp.opening_line if bp else "") or str(style.get("opening_line") or "").strip()
        if opening_override:
            profile["opening_line"] = opening_override
        if not profile["analysis_directive"]:
            profile["analysis_directive"] = "El analisis debe preservar un tono prudente y sostener cada conclusion en hechos y norma."
        if not profile["facts_directive"]:
            profile["facts_directive"] = "Los hechos deben narrarse de modo concreto, sin agregar inferencias no acreditadas."
        if not profile["petitum_directive"]:
            profile["petitum_directive"] = "El cierre debe mantener prudencia y correspondencia con el soporte disponible."
        if profile["strategy_focus"] == "urgency" and profile["urgency_emphasis"] == "none":
            profile["urgency_emphasis"] = "medium"
        if profile["normative_anchor"] == "strong" and profile["normative_quote_density"] == "standard":
            profile["normative_quote_density"] = "high"
        if profile["risk_tolerance"] == "low":
            profile["petitum_directive"] = profile["petitum_directive"] + " Evitar pedidos expansivos no cubiertos por la prueba."
        elif profile["risk_tolerance"] == "high":
            profile["petitum_directive"] = profile["petitum_directive"] + " Puede escalar medidas siempre que el soporte ya este explicitado."
        return profile

    @staticmethod
    def _alimentos_proof_lines(cp: dict[str, Any]) -> list[str]:
        scenarios = cp.get("scenarios", set())
        lines: list[str] = []
        lines.append("Base de cuantificacion a ordenar: necesidades concretas del alimentado y situacion economica, aunque sea indiciaria, del alimentante.")
        if "cuota_provisoria" in scenarios or "incumplimiento" in scenarios:
            lines.append("Si se impulsa cuota provisoria, conviene llegar con comprobantes concretos de gastos, modalidad de cuidado e indicios utiles sobre ingresos o capacidad contributiva.")
        if cp.get("vulnerability"):
            lines.append("Si el caso realmente lo muestra, conviene documentar bajos recursos, justicia gratuita y referencias operativas como SMVM, ANSES, AUH o CBU sin invocarlos en abstracto.")
        if "ascendientes" in scenarios:
            lines.append("Debe acreditarse la imposibilidad o insuficiencia del obligado principal antes de desplazar el reclamo hacia ascendientes; la pretension puede incluir litisexpensas si el caso lo permite.")
        if "hijo_mayor_estudiante" in scenarios:
            lines.append("Debe acreditarse regularidad academica, continuidad de asistencia y relacion entre estudio y necesidad alimentaria bajo el art. 663 CCyC.")
        if "hijo_mayor_no_estudia" in scenarios:
            lines.append("Si la consulta indica que no estudia, no corresponde sugerir certificado de alumno regular y la prueba debe orientarse a edad, convivencia, ingresos propios y necesidad actual.")
        if "hijo_18_21" in scenarios:
            lines.append("Entre 18 y 21 anos la prueba debe ordenar edad exacta, convivencia, gastos actuales e ingresos propios, sin mezclar el caso con hijo mayor estudiante.")
        return lines

    def _build_strategic_case_section(self, title: str, case_strategy: dict[str, Any], style_profile: dict[str, Any] | None = None) -> ArgumentSection | None:
        profile = style_profile or {}
        lines: list[str] = []
        if profile.get("facts_directive"):
            lines.append(str(profile.get("facts_directive")).strip())
        for cue in (profile.get("section_cues") or [])[:2]:
            lines.append(f"Criterio de redaccion: {cue}")
        conflict_lines = [str(item).strip() for item in (case_strategy.get("conflict_summary") or []) if str(item).strip()]
        procedural_focus = [str(item).strip() for item in (case_strategy.get("procedural_focus") or []) if str(item).strip()]
        lines.extend(conflict_lines[:4])
        for item in procedural_focus[:2]:
            lines.append(f"Foco procesal inmediato: {item}")
        return ArgumentSection(title, "\n".join(lines)) if lines else None

    def _build_requirements_support_section(self, normative_reasoning: dict[str, Any], evidence_links: dict[str, Any], case_profile: dict[str, Any] | None = None, style_profile: dict[str, Any] | None = None, behavior: dict[str, Any] | None = None) -> ArgumentSection | None:
        cp = case_profile or {}
        profile = style_profile or {}
        beh = behavior or {}
        lines: list[str] = []
        if profile.get("analysis_directive"):
            lines.append(str(profile.get("analysis_directive")).strip())
        proof_priority = beh.get("proof_priority") or profile.get("proof_priority") or []
        if proof_priority:
            lines.append("Prioridad probatoria del modelo: " + ", ".join(proof_priority))
        for item in (normative_reasoning.get("requirements") or [])[:4]:
            if str(item).strip():
                lines.append(f"Requisito legal a cubrir: {str(item).strip()}")
        for link in (evidence_links.get("requirement_links") or [])[:3]:
            if not isinstance(link, dict):
                continue
            requirement = str(link.get("requirement") or "").strip()
            support_level = str(link.get("support_level") or "").strip()
            missing_evidence = [str(x).strip() for x in (link.get("evidence_missing") or []) if str(x).strip()]
            note = str(link.get("strategic_note") or "").strip()
            if requirement and support_level:
                lines.append(f"Cobertura actual del requisito '{requirement}': {support_level}.")
            if missing_evidence:
                lines.append("Prueba faltante vinculada: " + "; ".join(missing_evidence[:2]))
            if note:
                lines.append(f"Observacion de uso forense: {note}")
        if cp.get("is_alimentos"):
            lines.extend(self._alimentos_proof_lines(cp))
        return ArgumentSection("Requisitos Criticos y Soporte", "\n".join(lines)) if lines else None

    def _build_strategy_list_section(self, title: str, items: list[str]) -> ArgumentSection | None:
        lines = [str(item).strip() for item in items if str(item).strip()]
        if not lines:
            return None
        formatted = [line if line.startswith("- ") or line[:2].isdigit() else f"- {line}" for line in lines]
        return ArgumentSection(title, "\n".join(formatted))

    def _build_action_section(self, title: str, case_strategy: dict[str, Any], style_profile: dict[str, Any] | None = None, limit: int | None = None, behavior: dict[str, Any] | None = None) -> ArgumentSection | None:
        profile = style_profile or {}
        beh = behavior or {}
        actions = [str(item).strip() for item in (case_strategy.get("recommended_actions") or []) if str(item).strip()]
        focus_items = [str(item).strip() for item in (case_strategy.get("procedural_focus") or []) if str(item).strip()]
        if limit is not None:
            actions = actions[:limit]
            focus_items = focus_items[:limit]
        if not actions and not focus_items:
            return None
        lines: list[str] = []
        if profile.get("petitum_directive"):
            lines.append(str(profile.get("petitum_directive")).strip())
        urgency = beh.get("urgency") or profile.get("urgency_emphasis") or "none"
        if urgency == "high":
            lines.append("Prioridad: despacho urgente y tramite inmediato.")
        risk = beh.get("risk_tolerance") or profile.get("risk_tolerance") or "medium"
        if risk == "low" and not any("prudente" in l.lower() or "proporcionada" in l.lower() for l in lines):
            lines.append("El alcance se mantiene deliberadamente prudente respecto del soporte disponible.")
        lines.extend(f"- {item}" for item in actions)
        if focus_items:
            if lines:
                lines.append("Foco procesal:")
            lines.extend(f"- {item}" for item in focus_items)
        return ArgumentSection(title, "\n".join(lines).strip()) if lines else None

    def _collect_missing_information(self, procedural_plan: ProceduralPlan | None, case_theory: dict[str, Any]) -> list[str]:
        items = [str(x).strip() for x in (procedural_plan.missing_info if procedural_plan else []) if str(x).strip()]
        items.extend(str(x).strip() for x in (case_theory.get("missing_facts") or []) if str(x).strip())
        items.extend(f"Soporte a reunir: {str(x).strip()}" for x in (case_theory.get("evidentiary_needs") or [])[:3] if str(x).strip())
        return self._dedupe(items)

    def _build_conclusion_text(self, mode: str, confidence_label: str, guard: dict[str, Any], conflict: dict[str, Any], procedural_plan: ProceduralPlan | None, case_theory: dict[str, Any], case_profile: dict[str, Any] | None = None, style_profile: dict[str, Any] | None = None) -> str:
        cp = case_profile or {}
        profile = style_profile or {}
        scenarios = cp.get("scenarios", set())
        source_quality = str(guard.get("source_quality") or "none").strip()
        argument_style = str((profile.get("content_rules") or {}).get("argument_style") or "prudential").strip()
        risk_tolerance = str(profile.get("risk_tolerance") or "medium").strip()
        vulnerable = str(conflict.get("most_vulnerable_point") or "").strip()
        next_action = ""
        if procedural_plan and procedural_plan.steps:
            next_action = str(procedural_plan.steps[0].action).strip()
        elif case_theory.get("recommended_line_of_action"):
            next_action = str((case_theory.get("recommended_line_of_action") or [""])[0]).strip()
        if mode == MODE_MEMORIAL:
            if source_quality in {"fallback", "none"}:
                return self._prepend_conclusion_directive(
                    "Por lo expuesto, la parte deja delineada una base juridica util para resolver el planteo, sin presentar la orientacion disponible como jurisprudencia consolidada. " + f"Corresponde reforzar en forma inmediata {vulnerable or 'la cobertura probatoria del punto controvertido'}" + (f" y avanzar en {next_action}." if next_action else ".") + " Proveer de conformidad, sera justicia.",
                    profile,
                )
            return self._prepend_conclusion_directive(
                f"Por lo expuesto, se solicita a V.S. tenga por desarrollados los fundamentos de derecho y valore la linea propuesta junto con la prueba y el conflicto efectivamente acreditados. Nivel de confianza de la base analitica: {confidence_label}. Proveer de conformidad, sera justicia.",
                profile,
            )
        if mode == MODE_BASE_ARGUMENTAL:
            if source_quality == "real" and str(guard.get("strength") or "").strip() == "strong":
                return self._finalize_argument_style(
                    f"La base argumental se sostiene con precedentes reales que operan como eje del planteo. El siguiente paso es {next_action or 'ordenar la presentacion y ejecutar la estrategia probatoria'}. Esta linea tiene fuerza litigante directa.",
                    profile,
                    argument_style,
                    risk_tolerance,
                )
            if source_quality == "real":
                return self._finalize_argument_style(
                    f"La base argumental puede sostenerse con mayor densidad porque existe apoyo jurisprudencial util y el siguiente paso debe ser {next_action or 'ordenar la presentacion y la prueba'}.",
                    profile,
                    argument_style,
                    risk_tolerance,
                )
            if source_quality == "legacy":
                return self._finalize_argument_style(
                    f"La base argumental es util para litigar, pero la jurisprudencia disponible solo cumple una funcion secundaria; conviene priorizar {next_action or 'la cobertura de hechos y prueba'}.",
                    profile,
                    argument_style,
                    risk_tolerance,
                )
            return self._finalize_argument_style(
                f"La base argumental es inicial y prudente: no debe sobredimensionarse la jurisprudencia disponible y conviene concentrar el trabajo inmediato en {next_action or 'cerrar hechos, requisitos y prueba'}.",
                profile,
                argument_style,
                risk_tolerance,
            )
        if source_quality in {"fallback", "none"}:
            return self._finalize_argument_style(
                f"Con base en el analisis expuesto, la posicion juridica puede trabajarse de manera inicial, pero no corresponde presentar la jurisprudencia disponible como respaldo consolidado. Nivel de confianza del analisis: {confidence_label}. Conviene reforzar {vulnerable or 'hechos, prueba y adecuacion normativa'}" + (f" y ejecutar sin demora {next_action}." if next_action else "."),
                profile,
                argument_style,
                risk_tolerance,
            )
        if source_quality == "legacy":
            return self._finalize_argument_style(
                f"Con base en el analisis expuesto, la posicion puede sostenerse de forma razonable, utilizando la jurisprudencia importada solo como apoyo secundario. Nivel de confianza del analisis: {confidence_label}. Resulta aconsejable avanzar en {next_action or 'la consolidacion del soporte factico y probatorio'}.",
                profile,
                argument_style,
                risk_tolerance,
            )
        strength = str(guard.get("strength") or "").strip()
        if source_quality == "real" and strength == "strong":
            return self._finalize_argument_style(
                f"Con base en el analisis expuesto, la posicion juridica tiene respaldo directo en precedentes reales recuperados del corpus y esta en condiciones de sostenerse con fuerza litigante. Nivel de confianza del analisis: {confidence_label}. Corresponde ejecutar {next_action or 'la presentacion estrategica del planteo'} sin dilacion.",
                profile,
                argument_style,
                risk_tolerance,
            )
        if cp.get("is_alimentos"):
            cierre = "Con base en el analisis expuesto, el planteo alimentario debe quedar armado sobre incumplimiento, necesidades concretas, capacidad contributiva y prueba inmediata."
            if "hijo_mayor_no_estudia" in scenarios:
                cierre = "Con base en el analisis expuesto, el planteo debe tratarse como supuesto de mayor de 21 anos que no estudia, bloqueando estrategias apoyadas en art. 663 CCyC o regularidad academica."
            elif "hijo_mayor_estudiante" in scenarios:
                cierre = "Con base en el analisis expuesto, el planteo debe sostenerse como alimentos de hijo mayor estudiante, acreditando art. 663 CCyC, regularidad academica y continuidad de asistencia."
            elif "ascendientes" in scenarios:
                cierre = "Con base en el analisis expuesto, el planteo debe explicar con claridad la subsidiariedad del reclamo contra ascendientes y la insuficiencia del obligado principal."
            if "cuota_provisoria" in scenarios or "incumplimiento" in scenarios:
                cierre += " Conviene empujar cuota provisoria y una agenda de prueba inmediata."
            if cp.get("vulnerability"):
                cierre += " La vulnerabilidad del caso debe reflejarse en el tono, la proteccion reforzada y la justificacion de acceso a justicia."
            cierre += f" Corresponde avanzar en {next_action or 'la presentacion estrategica del reclamo'}."
            return self._finalize_argument_style(cierre, profile, argument_style, risk_tolerance)
        return self._finalize_argument_style(
            f"Con base en el analisis expuesto, la posicion juridica cuenta con una linea argumental util para litigacion y puede apoyarse en los criterios recuperados siempre que se los vincule con el conflicto y la prueba del caso. Nivel de confianza del analisis: {confidence_label}. Corresponde avanzar en {next_action or 'la presentacion estrategica del planteo'}.",
            profile,
            argument_style,
            risk_tolerance,
        )

    def _finalize_argument_style(
        self,
        text: str,
        profile: dict[str, Any],
        argument_style: str,
        risk_tolerance: str,
    ) -> str:
        if argument_style == "assertive":
            text = "La linea argumental puede sostenerse con mayor definicion. " + text
        elif argument_style == "exploratory":
            text = "La linea debe tomarse como exploratoria y sujeta a contraste adicional. " + text
        if risk_tolerance == "low":
            text += " El cierre mantiene un alcance deliberadamente prudente."
        elif risk_tolerance == "high":
            text += " El cierre admite mayor intensidad si el soporte ya quedo explicitado."
        return self._prepend_conclusion_directive(text, profile)

    @staticmethod
    def _format_evidence_traceability(evidence_links: dict[str, Any]) -> ArgumentSection | None:
        links = evidence_links.get("requirement_links") or []
        if not links:
            return None
        lines: list[str] = []
        if str(evidence_links.get("summary") or "").strip():
            lines.append(str(evidence_links.get("summary")).strip())
            lines.append("")
        labels = {"alto": "ALTO", "medio": "MEDIO", "bajo": "BAJO"}
        for link in links:
            if not isinstance(link, dict) or not str(link.get("requirement") or "").strip():
                continue
            source = str(link.get("source") or "").strip()
            article = str(link.get("article") or "").strip()
            header = f"Art. {article} ({source})" if source and article else (f"Art. {article}" if article else "")
            level = labels.get(str(link.get("support_level") or "bajo").strip(), "BAJO")
            lines.append(f"[{level}] {header + ' - ' if header else ''}{str(link.get('requirement')).strip()}")
            for item in (link.get("supporting_facts") or [])[:2]:
                if str(item).strip():
                    lines.append(f"  Hecho de apoyo: {str(item).strip()}")
            for item in (link.get("evidence_available") or [])[:2]:
                if str(item).strip():
                    lines.append(f"  Evidencia disponible: {str(item).strip()}")
            for item in (link.get("evidence_missing") or [])[:2]:
                if str(item).strip():
                    lines.append(f"  Evidencia faltante: {str(item).strip()}")
            if str(link.get("strategic_note") or "").strip():
                lines.append(f"  Nota: {str(link.get('strategic_note')).strip()}")
            lines.append("")
        for item in (evidence_links.get("strategic_warnings") or [])[:3]:
            if str(item).strip():
                lines.append(f"Advertencia: {str(item).strip()}")
        return ArgumentSection("Trazabilidad Probatoria", "\n".join(lines).strip()) if lines else None

    def _format_jurisprudential_orientation(self, jurisprudence_analysis: dict[str, Any]) -> ArgumentSection | None:
        if not isinstance(jurisprudence_analysis, dict) or not jurisprudence_analysis:
            return None
        lines: list[str] = []
        source_quality = str(jurisprudence_analysis.get("source_quality") or "").strip()
        strength = str(jurisprudence_analysis.get("jurisprudence_strength") or "").strip()
        if source_quality == "real" and strength == "strong":
            lines.append("Uso forense: la linea puede apoyarse con mayor densidad en precedentes reales recuperados del corpus.")
        elif source_quality == "legacy":
            lines.append("Uso forense: la jurisprudencia disponible funciona solo como apoyo secundario y no reemplaza el peso de la norma, los hechos y la prueba.")
        elif source_quality in {"fallback", "none"}:
            lines.append("Uso forense: no corresponde presentar esta base como jurisprudencia consolidada; solo sirve para orientar el planteo con prudencia.")
        mapping = {"real": "precedentes reales del corpus", "legacy": "precedentes legacy importados", "fallback": "fallback interno", "none": "sin base suficiente"}
        if source_quality:
            lines.append(f"Calidad de fuente: {mapping.get(source_quality, source_quality)}")
        if strength:
            lines.append(f"Fuerza orientativa: {strength}")
        for key, label in [("usable_real_precedents", "Precedentes reales utilizables"), ("usable_legacy_precedents", "Precedentes legacy utilizables")]:
            value = jurisprudence_analysis.get(key)
            if isinstance(value, int):
                lines.append(f"{label}: {value}")
        highlights = jurisprudence_analysis.get("jurisprudence_highlights") or []
        if highlights:
            for item in highlights[:3]:
                if not isinstance(item, dict):
                    continue
                if str(item.get("case_name") or "").strip():
                    lines.append(f"Caso: {str(item.get('case_name')).strip()}")
                if str(item.get("court") or "").strip() and str(item.get("source_mode") or "").strip() != "internal_fallback_profile":
                    lines.append(f"Tribunal: {str(item.get('court')).strip()}")
                if str(item.get("year") or "").strip() and str(item.get("year")).strip() != "0":
                    lines.append(f"Anio: {str(item.get('year')).strip()}")
                if str(item.get("criterion") or "").strip():
                    lines.append(f"Criterio: {str(item.get('criterion')).strip()}")
                if str(item.get("strategic_use") or "").strip():
                    lines.append(f"Utilidad estrategica: {str(item.get('strategic_use')).strip()}")
                if str(item.get("source_mode") or "").strip() == "internal_fallback_profile":
                    lines.append("Nota: perfil interno orientativo, no precedente real recuperado del corpus.")
                lines.append("")
        else:
            for label, key in [("Criterio dominante", "dominant_criteria"), ("Escenario posible", "possible_outcomes"), ("Implicancia estrategica", "strategic_implications")]:
                for item in (jurisprudence_analysis.get(key) or [])[:3]:
                    if str(item).strip():
                        lines.append(f"{label}: {str(item).strip()}")
        if str(jurisprudence_analysis.get("source_mode_summary") or "").strip():
            lines.append(f"Fuente jurisprudencial: {str(jurisprudence_analysis.get('source_mode_summary')).strip()}")
        for item in (jurisprudence_analysis.get("warnings") or [])[:3]:
            if str(item).strip():
                lines.append(f"Advertencia: {str(item).strip()}")
        return ArgumentSection("Jurisprudencia relevante", "\n".join(lines).strip()) if lines else None

    def _build_jurisprudence_guard(self, jurisprudence_analysis: dict[str, Any]) -> dict[str, Any]:
        source_quality = str(jurisprudence_analysis.get("source_quality") or "none").strip()
        strength = str(jurisprudence_analysis.get("jurisprudence_strength") or "none").strip()
        limit_claims = bool(jurisprudence_analysis.get("should_limit_claims", True))
        avoid_assertions = bool(jurisprudence_analysis.get("should_avoid_jurisprudential_assertions", True))
        if source_quality == "real" and strength == "strong":
            limit_claims = False
            avoid_assertions = False
        elif source_quality == "legacy":
            limit_claims = True
            avoid_assertions = False
        elif source_quality in {"fallback", "none"}:
            limit_claims = True
            avoid_assertions = True
        return {
            "source_quality": source_quality,
            "strength": strength,
            "limit_claims": limit_claims,
            "avoid_assertions": avoid_assertions,
            "warnings": list(jurisprudence_analysis.get("warnings") or []),
        }

    def _build_jurisprudence_caution_section(self, jurisprudence_guard: dict[str, Any]) -> ArgumentSection | None:
        source_quality = jurisprudence_guard.get("source_quality")
        if source_quality == "real" and not jurisprudence_guard.get("limit_claims"):
            return None
        if source_quality == "legacy":
            return ArgumentSection("Cautela Jurisprudencial", "La orientacion jurisprudencial disponible proviene de precedentes legacy importados. Puede servir para encuadrar lineas de trabajo, pero conviene evitar afirmaciones concluyentes y reforzar el planteo con norma, hechos y prueba.")
        if source_quality == "fallback":
            return ArgumentSection("Cautela Jurisprudencial", "No se recuperaron precedentes reales suficientes del corpus. El apoyo disponible es solo un perfil interno orientativo y no debe presentarse como jurisprudencia verificable.")
        if source_quality == "none":
            return ArgumentSection("Cautela Jurisprudencial", "No hay base jurisprudencial suficiente para sostener una orientacion confiable. La construccion del caso debe apoyarse principalmente en la norma positiva, la delimitacion del conflicto y la estrategia probatoria.")
        return None

    @staticmethod
    def _collect_citations(rr: ReasoningResult | None) -> list[str]:
        if rr is None:
            return []
        seen: dict[str, None] = {}
        for item in rr.citations_used or []:
            if isinstance(item, dict):
                source_id = str(item.get("source_id") or item.get("source") or "").strip()
                article = str(item.get("article") or item.get("articulo") or "").strip()
                if source_id and article:
                    seen[f"{source_id}:{article}"] = None
            elif str(item).strip():
                seen[str(item).strip()] = None
        return list(seen)

    @staticmethod
    def _collect_warnings(rr: ReasoningResult | None, plan: ProceduralPlan | None) -> list[str]:
        warnings: list[str] = []
        if rr and rr.warnings:
            warnings.extend(rr.warnings)
        if plan and plan.warnings:
            warnings.extend(plan.warnings)
        return warnings

    @staticmethod
    def _format_normative_grounds(rr: ReasoningResult | None, max_items: int = 5) -> list[str]:
        if not rr or not rr.normative_grounds:
            return []
        return [f"- {ng.citation()}: {ng.texto[:200].rstrip()}..." for ng in rr.normative_grounds[:max_items]]

    @staticmethod
    def _coerce_reasoning_result(value: ReasoningResult | dict[str, Any] | None, query: str) -> ReasoningResult | None:
        if value is None:
            return None
        if isinstance(value, ReasoningResult):
            return value
        if not isinstance(value, dict):
            return None
        grounds: list[NormativeGrounding] = []
        for item in (value.get("normative_grounds") or value.get("normative_foundations") or []):
            if isinstance(item, NormativeGrounding):
                grounds.append(item)
            elif isinstance(item, dict):
                grounds.append(NormativeGrounding(
                    source_id=str(item.get("source_id") or item.get("source") or ""),
                    article=str(item.get("article") or item.get("articulo") or ""),
                    label=str(item.get("label") or item.get("title") or item.get("titulo") or ""),
                    texto=str(item.get("texto") or item.get("text") or item.get("summary") or ""),
                    relevance_note=str(item.get("relevance_note") or item.get("description") or ""),
                    score=float(item.get("score", 0.0)),
                ))
        citations: list[str] = []
        for item in value.get("citations_used") or []:
            if isinstance(item, str):
                citations.append(item)
            elif isinstance(item, dict):
                source_id = str(item.get("source_id") or item.get("source") or "").strip()
                article = str(item.get("article") or item.get("articulo") or "").strip()
                if source_id and article:
                    citations.append(f"{source_id}:{article}")
        confidence_raw = value.get("confidence")
        if isinstance(confidence_raw, (int, float)):
            confidence_score = float(confidence_raw)
            confidence_label = "high" if confidence_score >= 0.75 else "medium" if confidence_score >= 0.45 else "low"
        else:
            confidence_label = str(confidence_raw or "low")
            confidence_score = float(value.get("confidence_score", 0.0) or 0.0)
        return ReasoningResult(
            query=str(value.get("query", query)),
            query_type=str(value.get("query_type", "procedure_query")),
            short_answer=str(value.get("short_answer", "")),
            normative_grounds=grounds,
            applied_analysis=str(value.get("applied_analysis") or value.get("case_analysis") or ""),
            limitations=list(value.get("limitations") or []),
            citations_used=citations,
            confidence=confidence_label,
            confidence_score=confidence_score,
            evidence_sufficient=bool(value.get("evidence_sufficient", bool(grounds))),
            domain=str(value.get("domain", "procedural")),
            jurisdiction=str(value.get("jurisdiction", "jujuy")),
            warnings=list(value.get("warnings") or []),
        )

    @staticmethod
    def _coerce_procedural_plan(value: ProceduralPlan | dict[str, Any] | None, query: str, jurisdiction: str | None) -> ProceduralPlan | None:
        if value is None:
            return None
        if isinstance(value, ProceduralPlan):
            return value
        if not isinstance(value, dict):
            return None
        raw_steps = value.get("steps") or []
        if not raw_steps and value.get("next_steps"):
            raw_steps = [{"action": str(item)} for item in value.get("next_steps") or []]
        steps: list[ProceduralStep] = []
        for index, item in enumerate(raw_steps, 1):
            if isinstance(item, ProceduralStep):
                steps.append(item)
            elif isinstance(item, dict):
                steps.append(ProceduralStep(
                    order=int(item.get("order", index)),
                    action=str(item.get("action") or item.get("label") or item.get("title") or ""),
                    deadline_hint=str(item.get("deadline_hint") or "") or None,
                    urgency=str(item.get("urgency") or URGENCY_NORMAL),
                    notes=str(item.get("notes") or ""),
                ))
            elif isinstance(item, str):
                steps.append(ProceduralStep(order=index, action=item, deadline_hint=None, urgency=URGENCY_NORMAL, notes=""))
        return ProceduralPlan(
            query=str(value.get("query", query)),
            domain=str(value.get("domain", "procedural")),
            jurisdiction=str(value.get("jurisdiction", jurisdiction or "jujuy")),
            steps=steps,
            risks=list(value.get("risks") or []),
            missing_info=list(value.get("missing_info") or value.get("missing_information") or []),
            strategic_notes=str(value.get("strategic_notes", "")),
            citations_used=list(value.get("citations_used") or []),
            warnings=list(value.get("warnings") or []),
        )

    @staticmethod
    def _format_steps(steps: list[ProceduralStep]) -> str:
        parts: list[str] = []
        for step in steps:
            deadline = f" [{step.deadline_hint}]" if step.deadline_hint else ""
            urgency = f" ({step.urgency})" if step.urgency else ""
            parts.append(f"{step.order}. {step.action}{deadline}{urgency}")
            if step.notes:
                parts.append(f"   Nota: {step.notes}")
        return "\n".join(parts)

    def _build_legal_argument_sections(self, rr: ReasoningResult | None, citations: list[str], max_norms: int = 6) -> list[ArgumentSection]:
        if not rr or not rr.normative_grounds:
            return [ArgumentSection("Fundamentos de Derecho", "Sin normas de referencia en contexto disponible.")]
        sections: list[ArgumentSection] = []
        for index, ng in enumerate(rr.normative_grounds[:max_norms], 1):
            content = f"Conforme al {ng.citation()}:\n\"{ng.texto[:300].rstrip()}...\"\n"
            if ng.relevance_note:
                content += f"\nAplicacion: {ng.relevance_note}"
            sections.append(ArgumentSection(f"Fundamento {index}: {ng.citation()}", content, [ng.citation()]))
        if not sections and citations:
            sections.append(ArgumentSection("Fundamentos de Derecho", "\n".join(citations), list(citations)))
        return sections

    @staticmethod
    def _resolve_normative_limit(style_profile: dict[str, Any], default: int) -> int:
        density = str(style_profile.get("argument_density") or "standard").strip()
        quote_density = str(style_profile.get("normative_quote_density") or "").strip()
        if quote_density == "high" or density == "high":
            return default + 1
        if quote_density == "focused" or density in {"focused", "concise"}:
            return max(2, default - 2)
        return default

    @staticmethod
    def _compose_petitum(style_profile: dict[str, Any], lines: list[str], behavior: dict[str, Any] | None = None) -> str:
        template = behavior or {}
        profile_line = str(style_profile.get("petitum_directive") or "").strip()
        parts = [profile_line] if profile_line else []
        urgency = str(template.get("urgency") or style_profile.get("urgency_emphasis") or "none").strip()
        if urgency == "high":
            parts.append("Atento a la urgencia acreditada en autos, se solicita despacho preferente y tramite inmediato.")
        risk = str(template.get("risk_tolerance") or style_profile.get("risk_tolerance") or "medium").strip()
        if risk == "low":
            parts.append("Los pedidos se formulan de manera estrictamente proporcionada al soporte actualmente disponible.")
        elif risk == "high":
            parts.append("Si el soporte ya fue explicitado, el modelo admite escalar medidas con mayor intensidad litigiosa.")
        parts.extend(lines)
        return "\n".join(part for part in parts if part != "")

    @staticmethod
    def _prepend_conclusion_directive(text: str, style_profile: dict[str, Any]) -> str:
        directive = str(style_profile.get("petitum_directive") or "").strip()
        if not directive:
            return text
        return f"{directive} {text}".strip()

    @staticmethod
    def _coerce_style_directives(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {
            "tone": str(value.get("tone") or "").strip(),
            "structure": [str(item).strip() for item in (value.get("structure") or []) if str(item).strip()],
            "argument_density": str(value.get("argument_density") or "").strip(),
            "facts_style": str(value.get("facts_style") or "").strip(),
            "petitum_style": str(value.get("petitum_style") or "").strip(),
            "opening_line": str(value.get("opening_line") or "").strip(),
            "analysis_directive": str(value.get("analysis_directive") or "").strip(),
            "facts_directive": str(value.get("facts_directive") or "").strip(),
            "petitum_directive": str(value.get("petitum_directive") or "").strip(),
            "section_cues": [str(item).strip() for item in (value.get("section_cues") or []) if str(item).strip()],
        }

    @staticmethod
    def _coerce_style_blueprint(model_match: dict[str, Any], mode: str) -> StyleBlueprint:
        """Extract or build a StyleBlueprint from model_match."""
        raw_bp = model_match.get("style_blueprint")
        if isinstance(raw_bp, dict) and raw_bp:
            # Already normalised by the pipeline — reconstruct dataclass
            return StyleBlueprint(
                section_order=raw_bp.get("section_order", []),
                required_sections=raw_bp.get("required_sections", []),
                optional_sections=raw_bp.get("optional_sections", []),
                section_templates=raw_bp.get("section_templates", {}),
                content_rules=raw_bp.get("content_rules", {}),
                tone=raw_bp.get("tone", "balanced_prudent"),
                opening_style=raw_bp.get("opening_style", ""),
                facts_style=raw_bp.get("facts_style", "concrete"),
                legal_analysis_style=raw_bp.get("legal_analysis_style", ""),
                petition_style=raw_bp.get("petition_style", "prudent"),
                urgency_emphasis=raw_bp.get("urgency_emphasis", "none"),
                argument_density=raw_bp.get("argument_density", "standard"),
                normative_quote_density=raw_bp.get("normative_quote_density", "standard"),
                opening_line=raw_bp.get("opening_line", ""),
                analysis_directive=raw_bp.get("analysis_directive", ""),
                facts_directive=raw_bp.get("facts_directive", ""),
                petitum_directive=raw_bp.get("petitum_directive", ""),
                section_cues=raw_bp.get("section_cues", []),
                structure_cues=raw_bp.get("structure_cues", []),
                warnings=raw_bp.get("warnings", []),
            )
        # Fallback: build from style_directives
        sd = model_match.get("style_directives")
        tags = model_match.get("detected_tags", [])
        return normalize_style_blueprint(sd if isinstance(sd, dict) else None, mode, tags)

    @staticmethod
    def _coerce_argument_strategy(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {
            "focus": str(value.get("focus") or "").strip(),
            "risk_tolerance": str(value.get("risk_tolerance") or "medium").strip(),
            "proof_priority": [str(item).strip() for item in (value.get("proof_priority") or []) if str(item).strip()],
            "normative_anchor": str(value.get("normative_anchor") or "").strip(),
        }

    @staticmethod
    def _infer_incident_type(query: str) -> str:
        q = _normalise(query)
        if "cautelar" in q or "embargo" in q or "inhibicion" in q:
            return "medida cautelar"
        if "nulidad" in q:
            return "nulidad"
        if "caducidad" in q:
            return "caducidad de instancia"
        if "apelacion" in q or "apelar" in q:
            return "recurso de apelacion"
        return "incidente procesal"

    @staticmethod
    def _render_full_text(title: str, sections: list[ArgumentSection]) -> str:
        parts: list[str] = []
        if title:
            parts.extend([title.upper(), "=" * min(len(title), 72), ""])
        for sec in sections:
            parts.extend([sec.title.upper(), "-" * min(len(sec.title), 60), sec.content, ""])
        return "\n".join(parts)

    @staticmethod
    def _capitalise(text: str) -> str:
        return text[:1].upper() + text[1:] if text else text

    def _resolve_formal_subject(self, query: str, classification: dict[str, Any], case_structure: dict[str, Any]) -> str:
        if str(classification.get("action_label") or "").strip():
            return self._capitalise(str(classification.get("action_label")).strip())
        if str(case_structure.get("main_claim") or "").strip():
            return self._capitalise(str(case_structure.get("main_claim")).replace("Peticion conjunta de ", "").strip())
        return self._capitalise(query)

    def _resolve_formal_forum(self, classification: dict[str, Any], case_structure: dict[str, Any], reasoning_result: ReasoningResult | None) -> str:
        value = classification.get("forum") or case_structure.get("forum") or (reasoning_result.domain if reasoning_result else "") or "No especificado"
        return self._format_header_value(str(value))

    @staticmethod
    def _format_header_value(value: str) -> str:
        cleaned = " ".join(str(value or "").replace("_", " ").split())
        return (cleaned[:1].upper() + cleaned[1:]) if cleaned else "No especificado"

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result


def _normalise(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in nfkd if not unicodedata.combining(char))


def _SOFTENER_principio() -> str:  # noqa: N802
    return _SOFTENER_PRINCIPIO
