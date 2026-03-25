"""Style blueprint normalization.

Transforms raw style_directives (from model selection) into a structured
blueprint that the argument generator can use to make *architectural*
decisions — section ordering, required/optional sections, argument
intensity, petitum shape, urgency emphasis — not just tonal adjustments.

The generator consumes the blueprint without knowing anything about the
model library or PDF sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Default section orders per generation mode
# ---------------------------------------------------------------------------

_DEFAULT_SECTION_ORDER: dict[str, list[str]] = {
    "formal": [
        "encabezado",
        "objeto",
        "hechos_decisivos",
        "marco_normativo",
        "cautela_jurisprudencial",
        "inferencias_juridicas",
        "reglas_aplicadas",
        "requisitos_soporte",
        "analisis_juridico",
        "requisitos",
        "conflicto_prueba",
        "trazabilidad_probatoria",
        "jurisprudencia",
        "riesgo_procesal",
        "pasos_procesales",
        "limitaciones",
        "conclusion",
    ],
    "memorial": [
        "encabezado",
        "introduccion",
        "punto_en_debate",
        "fundamentos_derecho",
        "cautela_jurisprudencial",
        "hechos_relevantes",
        "desarrollo_estrategico",
        "trazabilidad_probatoria",
        "jurisprudencia",
        "conclusion",
    ],
    "incidente": [
        "encabezado",
        "objeto",
        "fundamentos",
        "medidas_urgentes",
        "petitorio",
    ],
    "contestacion": [
        "encabezado",
        "personeria",
        "objeto",
        "relacion_hechos",
        "derecho",
        "ofrecimiento_prueba",
        "linea_defensa",
        "petitorio",
    ],
    "base_argumental": [
        "tesis_principal",
        "hecho_decisivo",
        "argumentos_normativos",
        "cautela_jurisprudencial",
        "inferencias_juridicas",
        "requisitos",
        "requisitos_soporte",
        "riesgos_contraargumentos",
        "informacion_faltante",
        "proximos_pasos",
        "notas_estrategicas",
        "conflicto_prueba",
        "trazabilidad_probatoria",
        "jurisprudencia",
        "linea_accion_inmediata",
        "cierre_estrategico",
    ],
    "breve": [
        "consulta",
        "analisis",
        "cautela_jurisprudencial",
        "conclusion",
    ],
}


# ---------------------------------------------------------------------------
# Blueprint dataclass
# ---------------------------------------------------------------------------

@dataclass
class StyleBlueprint:
    """Normalized blueprint consumed by the argument generator.

    Fields are divided into *structural* (affect document architecture)
    and *tonal* (affect prose style within sections).
    """

    # --- Structural ---
    section_order: list[str] = field(default_factory=list)
    required_sections: list[str] = field(default_factory=list)
    optional_sections: list[str] = field(default_factory=list)
    section_templates: dict[str, dict[str, Any]] = field(default_factory=dict)
    content_rules: dict[str, str] = field(default_factory=dict)

    # --- Tonal / intensity ---
    tone: str = "balanced_prudent"
    opening_style: str = ""
    facts_style: str = "concrete"
    legal_analysis_style: str = ""
    petition_style: str = "prudent"
    urgency_emphasis: str = "none"
    argument_density: str = "standard"
    normative_quote_density: str = "standard"

    # --- Directives (carried forward from style_directives) ---
    opening_line: str = ""
    analysis_directive: str = ""
    facts_directive: str = ""
    petitum_directive: str = ""
    section_cues: list[str] = field(default_factory=list)
    structure_cues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # --- Backward compatibility ---
    raw_style_directives: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_order": list(self.section_order),
            "required_sections": list(self.required_sections),
            "optional_sections": list(self.optional_sections),
            "section_templates": {
                key: dict(value) for key, value in self.section_templates.items()
            },
            "content_rules": dict(self.content_rules),
            "tone": self.tone,
            "opening_style": self.opening_style,
            "facts_style": self.facts_style,
            "legal_analysis_style": self.legal_analysis_style,
            "petition_style": self.petition_style,
            "urgency_emphasis": self.urgency_emphasis,
            "argument_density": self.argument_density,
            "normative_quote_density": self.normative_quote_density,
            "opening_line": self.opening_line,
            "analysis_directive": self.analysis_directive,
            "facts_directive": self.facts_directive,
            "petitum_directive": self.petitum_directive,
            "section_cues": list(self.section_cues),
            "structure_cues": list(self.structure_cues),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_style_blueprint(
    style_directives: dict[str, Any] | None,
    generation_mode: str = "formal",
    detected_tags: list[str] | None = None,
) -> StyleBlueprint:
    """Produce a StyleBlueprint from raw style_directives + context.

    - If style_directives has a ``structure`` list, use it to reorder
      sections (promoting matching sections to the front).
    - Infer urgency_emphasis and normative_quote_density from tags and
      argument_density.
    - Always fills in sensible defaults for missing fields.
    - Full backward compat: everything the old ``_build_writing_profile``
      consumed is still available.
    """
    sd = style_directives or {}
    tags = set(detected_tags or [])
    warnings: list[str] = []

    # --- Tone & intensity ---
    tone = _str(sd.get("tone"), "balanced_prudent")
    argument_density = _str(sd.get("argument_density"), "standard")
    facts_style = _str(sd.get("facts_style"), "concrete")
    petitum_style = _str(sd.get("petitum_style"), "prudent")

    # --- Urgency ---
    urgency_emphasis = "none"
    if "urgencia" in tags or tone in ("urgent_prudent",):
        urgency_emphasis = "high"
    elif "medidas_fuertes" in tags:
        urgency_emphasis = "medium"

    # --- Normative density ---
    normative_quote_density = "standard"
    if argument_density == "high":
        normative_quote_density = "high"
    elif argument_density in ("focused", "concise"):
        normative_quote_density = "focused"

    # --- Section ordering ---
    default_order = list(_DEFAULT_SECTION_ORDER.get(generation_mode, []))
    structure_cues = [_str(s) for s in (sd.get("structure") or []) if _str(s)]
    section_order, order_warnings = _resolve_section_order(
        explicit_section_order=sd.get("section_order"),
        default_order=default_order,
        structure_cues=structure_cues,
    )
    warnings.extend(order_warnings)

    # --- Required / optional sections ---
    required_sections = list(default_order[:2]) if default_order else []
    # Always require conclusion/cierre
    for section in default_order:
        if section in ("conclusion", "cierre_estrategico", "petitorio"):
            if section not in required_sections:
                required_sections.append(section)
    optional_sections = [s for s in section_order if s not in required_sections]

    section_templates = _build_section_templates(
        section_order=section_order,
        required_sections=required_sections,
        style_directives=sd,
        generation_mode=generation_mode,
        argument_density=argument_density,
        facts_style=facts_style,
        petitum_style=petitum_style,
        urgency_emphasis=urgency_emphasis,
    )
    content_rules = _build_content_rules(
        style_directives=sd,
        argument_density=argument_density,
        tone=tone,
    )

    # --- Directives ---
    opening_line = _str(sd.get("opening_line"))
    analysis_directive = _str(sd.get("analysis_directive"))
    facts_directive = _str(sd.get("facts_directive"))
    petitum_directive = _str(sd.get("petitum_directive"))
    section_cues_list = [_str(s) for s in (sd.get("section_cues") or []) if _str(s)]

    # --- Opening style ---
    opening_style = ""
    if tone in ("urgent_prudent",):
        opening_style = "urgent"
    elif tone in ("institutional_protective",):
        opening_style = "protective"
    elif tone in ("technical_focused", "technical_robust", "technical_ordered"):
        opening_style = "technical"
    elif tone in ("litigation_clear",):
        opening_style = "litigation"

    # --- Legal analysis style ---
    legal_analysis_style = ""
    if analysis_directive:
        legal_analysis_style = "directed"
    elif argument_density == "high":
        legal_analysis_style = "dense"

    return StyleBlueprint(
        section_order=section_order,
        required_sections=required_sections,
        optional_sections=optional_sections,
        section_templates=section_templates,
        content_rules=content_rules,
        tone=tone,
        opening_style=opening_style,
        facts_style=facts_style,
        legal_analysis_style=legal_analysis_style,
        petition_style=petitum_style,
        urgency_emphasis=urgency_emphasis,
        argument_density=argument_density,
        normative_quote_density=normative_quote_density,
        opening_line=opening_line,
        analysis_directive=analysis_directive,
        facts_directive=facts_directive,
        petitum_directive=petitum_directive,
        section_cues=section_cues_list,
        structure_cues=structure_cues,
        warnings=warnings,
        raw_style_directives=dict(sd),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(value: Any, default: str = "") -> str:
    return str(value or "").strip() or default


def _apply_structure_cues(base_order: list[str], cues: list[str]) -> list[str]:
    """Reorder ``base_order`` by promoting sections that match cues.

    Cues are free-text hints from the model's style_profile.structure.
    We do a fuzzy match: if any cue substring appears in a section name
    or vice-versa, that section gets promoted.
    """
    if not cues or not base_order:
        return list(base_order)

    promoted: list[str] = []
    remaining: list[str] = []

    for section in base_order:
        matched = False
        for cue in cues:
            cue_norm = cue.lower().replace(" ", "_")
            section_norm = section.lower()
            if cue_norm in section_norm or section_norm in cue_norm:
                matched = True
                break
        if matched:
            promoted.append(section)
        else:
            remaining.append(section)

    # Keep required anchors (first and last) in place
    if remaining and base_order:
        first = base_order[0]
        last = base_order[-1]
        # Ensure first section stays first
        if first in remaining:
            remaining.remove(first)
            remaining.insert(0, first)
        elif first in promoted:
            promoted.remove(first)
            promoted.insert(0, first)
        # Ensure last section stays last
        if last in remaining:
            remaining.remove(last)
        elif last in promoted:
            promoted.remove(last)
        # Promoted sections go after anchored first, before remaining
        result = []
        if promoted and promoted[0] == first:
            result.append(promoted.pop(0))
        elif remaining and remaining[0] == first:
            result.append(remaining.pop(0))
        result.extend(promoted)
        result.extend(remaining)
        result.append(last)
        return result

    return promoted + remaining


def _resolve_section_order(
    explicit_section_order: Any,
    default_order: list[str],
    structure_cues: list[str],
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []

    if isinstance(explicit_section_order, list):
        cleaned = [_str(item) for item in explicit_section_order if _str(item)]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in cleaned:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        if deduped:
            return deduped, warnings
        warnings.append("Blueprint warning: 'section_order' explicito invalido o vacio; se uso fallback estructural.")
    elif explicit_section_order is not None:
        warnings.append("Blueprint warning: 'section_order' explicito invalido; se uso fallback estructural.")

    return _apply_structure_cues(default_order, structure_cues), warnings


def _build_section_templates(
    section_order: list[str],
    required_sections: list[str],
    style_directives: dict[str, Any],
    generation_mode: str,
    argument_density: str,
    facts_style: str,
    petitum_style: str,
    urgency_emphasis: str,
) -> dict[str, dict[str, Any]]:
    custom = style_directives.get("section_templates")
    custom_templates = custom if isinstance(custom, dict) else {}
    templates: dict[str, dict[str, Any]] = {}

    for section in section_order:
        template = {
            "required": section in required_sections,
            "style": "default",
            "max_paragraphs": 3,
            "density": argument_density,
            "urgency": "conditional",
        }
        if "hecho" in section or "consulta" in section:
            template["style"] = facts_style
            template["max_paragraphs"] = 3
        elif "normativ" in section or "reglas" in section or "fundamentos" in section:
            template["style"] = "normative"
            template["density"] = "high" if argument_density == "high" else "standard"
            template["max_paragraphs"] = 4 if argument_density == "high" else 3
        elif section in {"petitorio", "pasos_procesales", "proximos_pasos", "linea_accion_inmediata", "medidas_urgentes"}:
            template["style"] = petitum_style
            template["urgency"] = "high" if urgency_emphasis == "high" else "conditional"
            template["max_paragraphs"] = 2
        elif "jurisprud" in section or "cautela" in section:
            template["style"] = "prudential"
            template["max_paragraphs"] = 2

        if generation_mode == "breve":
            template["max_paragraphs"] = min(template["max_paragraphs"], 2)
        elif generation_mode == "base_argumental" and section in {"argumentos_normativos", "analisis_juridico"}:
            template["max_paragraphs"] = max(template["max_paragraphs"], 4)

        override = custom_templates.get(section)
        if isinstance(override, dict):
            template.update(override)
        templates[section] = template

    return templates


def _build_content_rules(
    style_directives: dict[str, Any],
    argument_density: str,
    tone: str,
) -> dict[str, str]:
    custom = style_directives.get("content_rules")
    if isinstance(custom, dict):
        include_jurisprudence = _str(custom.get("include_jurisprudence"), "auto")
        normative_density = _str(custom.get("normative_density"), "standard")
        argument_style = _str(custom.get("argument_style"), "prudential")
    else:
        include_jurisprudence = "auto"
        normative_density = "high" if argument_density == "high" else "low" if argument_density in {"focused", "concise"} else "standard"
        if tone in {"technical_robust", "litigation_clear"}:
            argument_style = "assertive"
        elif tone in {"balanced_prudent", "institutional_protective", "urgent_prudent"}:
            argument_style = "prudential"
        else:
            argument_style = "exploratory"

    return {
        "include_jurisprudence": include_jurisprudence,
        "normative_density": normative_density,
        "argument_style": argument_style,
    }
