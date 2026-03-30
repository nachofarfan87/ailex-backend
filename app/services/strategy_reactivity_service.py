from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.divorce_agreement_evaluation_service import build_divorce_agreement_enrichment


_STRUCTURAL_FACT_KEYS = (
    "hay_hijos",
    "divorcio_modalidad",
    "hay_acuerdo",
    "convenio_regulador",
    "cuota_alimentaria_porcentaje",
    "regimen_comunicacional",
    "jurisdiccion_relevante",
)


def apply_strategy_reactivity(
    strategy: dict[str, Any],
    *,
    case_domain: str,
    facts: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    query: str = "",
) -> dict[str, Any]:
    reactive_strategy = deepcopy(strategy or {})
    reactivity = analyze_strategy_reactivity(
        case_domain=case_domain,
        facts=facts or {},
        metadata=metadata or {},
        query=query,
    )
    reactive_strategy["strategy_reactivity"] = reactivity
    if not reactivity.get("stale"):
        return reactive_strategy

    additions = _build_strategy_reactivity_additions(
        case_domain=case_domain,
        facts=facts or {},
        changed_fields=list(reactivity.get("changed_fields") or []),
        query=query,
    )
    if not additions:
        return reactive_strategy

    visible_summary = str(additions.get("visible_summary") or "").strip()
    if visible_summary:
        reactive_strategy["reactive_summary"] = visible_summary
    transition_message = str(additions.get("transition_message") or "").strip()
    if transition_message:
        reactive_strategy["reactive_transition"] = transition_message

    narrative_additions = [item for item in additions.get("narrative_additions") or [] if str(item).strip()]
    if narrative_additions:
        existing_narrative = str(reactive_strategy.get("strategic_narrative") or "").strip()
        reactive_strategy["strategic_narrative"] = "\n\n".join(
            [*narrative_additions, *( [existing_narrative] if existing_narrative else [] )]
        )

    for field_name in ("recommended_actions", "risk_analysis", "procedural_focus"):
        incoming = [str(item).strip() for item in additions.get(field_name) or [] if str(item).strip()]
        if incoming:
            reactive_strategy[field_name] = [*incoming, *list(reactive_strategy.get(field_name) or [])]

    return reactive_strategy


def analyze_strategy_reactivity(
    *,
    case_domain: str,
    facts: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    query: str = "",
) -> dict[str, Any]:
    normalized_case_domain = str(case_domain or "").strip().casefold()
    normalized_facts = dict(facts or {})
    clarification_context = (
        dict((metadata or {}).get("clarification_context") or {})
        if isinstance((metadata or {}).get("clarification_context"), dict)
        else {}
    )
    previous_structural_facts = _structural_fact_view(
        clarification_context.get("previous_structural_facts")
        if isinstance(clarification_context.get("previous_structural_facts"), dict)
        else clarification_context.get("known_facts")
        if isinstance(clarification_context.get("known_facts"), dict)
        else {},
    )
    current_structural_facts = _structural_fact_view(
        clarification_context.get("current_structural_facts")
        if isinstance(clarification_context.get("current_structural_facts"), dict)
        else normalized_facts,
    )

    changed_fields = list(clarification_context.get("structural_fact_changes") or [])
    if not changed_fields:
        changed_fields = _diff_structural_facts(previous_structural_facts, current_structural_facts)

    stale = bool(changed_fields)
    return {
        "stale": stale,
        "case_domain": normalized_case_domain,
        "changed_fields": changed_fields,
        "previous_structural_facts": previous_structural_facts,
        "current_structural_facts": current_structural_facts,
        "reason": (
            f"Recalcular estrategia por cambio en facts estructurales: {', '.join(changed_fields)}."
            if stale else
            "Sin cambios estructurales relevantes; se conserva la estrategia base del turno."
        ),
        "query": str(query or "").strip(),
    }


def _build_strategy_reactivity_additions(
    *,
    case_domain: str,
    facts: dict[str, Any],
    changed_fields: list[str],
    query: str,
) -> dict[str, Any]:
    if case_domain != "divorcio" or not changed_fields:
        return {}

    visible_summary_parts: list[str] = []
    narrative_additions: list[str] = []
    recommended_actions: list[str] = []
    risk_analysis: list[str] = []
    procedural_focus: list[str] = []
    transition_bits: list[str] = []

    if "hay_hijos" in changed_fields and facts.get("hay_hijos") is True:
        transition_bits.append("Ahora el caso ya no es un divorcio sin definiciones parentales: hay hijos en juego.")
        visible_summary_parts.append(
            "Con hijos ya definidos, la estrategia deja de ser un divorcio basico y pasa a exigir una propuesta concreta sobre alimentos, cuidado y comunicacion."
        )
        narrative_additions.append(
            "Cambio estrategico visible: la definicion de hijos modifica el encuadre practico del divorcio. Ya no alcanza con abrir el tramite; ahora importa ordenar de manera expresa alimentos, cuidado y comunicacion porque esos efectos pasan a ser parte central de la presentacion."
        )
        recommended_actions.append(
            "Reordenar la estrategia del divorcio para incluir propuesta concreta sobre alimentos, cuidado personal y comunicacion."
        )
        risk_analysis.append(
            "Si los hijos ya aparecen en el caso, dejar esos efectos para despues debilita la utilidad practica de la presentacion inicial."
        )
        procedural_focus.append(
            "Priorizar la parte del divorcio vinculada a hijos antes de cerrar detalles accesorios o patrimoniales."
        )

    if "divorcio_modalidad" in changed_fields or "hay_acuerdo" in changed_fields:
        modalidad = str(facts.get("divorcio_modalidad") or "").strip().casefold()
        hay_acuerdo = facts.get("hay_acuerdo")
        if modalidad == "unilateral" or hay_acuerdo is False:
            transition_bits.append("El escenario tambien cambio porque ya no se trata de un acuerdo conjunto sino de una via unilateral.")
            visible_summary_parts.append(
                "Al quedar definido que el divorcio es unilateral, cambian los pasos: corresponde preparar la presentacion propia y no hablar del caso como si fuera un acuerdo cerrado."
            )
            narrative_additions.append(
                "Cambio estrategico visible: la modalidad unilateral recalcula la estrategia. El foco ya no es cerrar una presentacion conjunta sino sostener una propuesta reguladora propia, con hechos suficientes y un encuadre procesal consistente."
            )
            recommended_actions.append(
                "Preparar presentacion unilateral con propuesta reguladora propia y hechos suficientes para sostenerla."
            )
            risk_analysis.append(
                "Tratar como acuerdo un divorcio que ya aparece unilateral puede desalinear la presentacion y generar objeciones tempranas."
            )
            procedural_focus.append(
                "Alinear el escrito, los pedidos y la narrativa con una via unilateral, sin depender de un acuerdo no existente."
            )
        elif modalidad == "conjunto" or hay_acuerdo is True:
            transition_bits.append("El escenario se ordena distinto porque ahora hay acuerdo y eso permite trabajar como presentacion conjunta.")
            visible_summary_parts.append(
                "Al quedar definido que hay acuerdo, la estrategia se desplaza a cerrar una presentacion conjunta y un convenio suficientemente preciso."
            )
            narrative_additions.append(
                "Cambio estrategico visible: la existencia de acuerdo cambia el eje. Conviene concentrar energia en la completitud del convenio y no en construir un conflicto que ya no domina el caso."
            )
            recommended_actions.append(
                "Cerrar presentacion conjunta con convenio regulador completo y listo para homologacion."
            )
            risk_analysis.append(
                "Aunque exista acuerdo, una redaccion imprecisa del convenio puede frustrar la homologacion o abrir discusiones posteriores."
            )
            procedural_focus.append(
                "Ordenar la documentacion y la propuesta reguladora como presentacion conjunta ejecutable."
            )

    if "jurisdiccion_relevante" in changed_fields:
        transition_bits.append("Tambien cambia el escenario procesal porque la jurisdiccion relevante ya quedo mejor definida.")
        visible_summary_parts.append(
            "Al cambiar la jurisdiccion relevante, tambien cambia la estrategia porque hay que revisar competencia y vias concretas del tramite."
        )
        recommended_actions.append(
            "Revisar competencia y encuadre procesal a la luz de la jurisdiccion relevante informada."
        )
        risk_analysis.append(
            "Una jurisdiccion mal tomada puede volver esteril una estrategia que en abstracto parecia correcta."
        )
        procedural_focus.append(
            "Controlar competencia territorial y tribunal util antes de seguir ampliando la estrategia."
        )

    convenio_additions = build_divorce_agreement_enrichment({
        "case_domain": case_domain,
        "case_domains": [case_domain],
        "facts": facts,
        "query": query,
    }) if any(
        field in changed_fields
        for field in ("convenio_regulador", "cuota_alimentaria_porcentaje", "regimen_comunicacional")
    ) else {}
    if convenio_additions:
        transition_bits.append("El convenio informado agrega un plano nuevo de analisis y ya no alcanza una orientacion generica de divorcio.")
        visible_summary_parts.append(str(convenio_additions.get("summary") or "").strip())
        narrative_additions.append(str(convenio_additions.get("strategic_narrative") or "").strip())
        recommended_actions.extend(list(convenio_additions.get("recommended_actions") or []))
        risk_analysis.extend(list(convenio_additions.get("risk_analysis") or []))
        procedural_focus.extend(list(convenio_additions.get("procedural_focus") or []))

    visible_summary = " ".join(part for part in visible_summary_parts if part).strip()
    if not visible_summary:
        return {}
    transition_message = _build_transition_message(changed_fields, transition_bits)
    return {
        "transition_message": transition_message,
        "visible_summary": visible_summary,
        "narrative_additions": narrative_additions,
        "recommended_actions": recommended_actions,
        "risk_analysis": risk_analysis,
        "procedural_focus": procedural_focus,
    }


def _structural_fact_view(facts: dict[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {}
    for key in _STRUCTURAL_FACT_KEYS:
        if key in facts and facts.get(key) not in (None, "", [], {}):
            view[key] = facts.get(key)
    return view


def _diff_structural_facts(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for key in _STRUCTURAL_FACT_KEYS:
        if previous.get(key) != current.get(key):
            if previous.get(key) in (None, "", [], {}) and current.get(key) in (None, "", [], {}):
                continue
            changed.append(key)
    return changed


def _build_transition_message(changed_fields: list[str], transition_bits: list[str]) -> str:
    if transition_bits:
        return " ".join(bit.strip() for bit in transition_bits if bit.strip())
    if not changed_fields:
        return ""
    if len(changed_fields) == 1:
        return f"Con este dato nuevo cambia el escenario juridico del caso: {changed_fields[0]}."
    return (
        "Con estos datos nuevos cambia el escenario juridico del caso: "
        + ", ".join(changed_fields)
        + "."
    )
