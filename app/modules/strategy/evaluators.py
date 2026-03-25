"""
AILEX — Evaluación prudente de opciones estratégicas.
"""

from app.api.schemas.contracts import SourceHierarchy
from app.modules.strategy.schemas import (
    StrategyCharacter,
    StrategyContext,
    StrategyOption,
    StrategySolidity,
)


def evaluate_options(
    candidates: list[dict],
    context: StrategyContext,
) -> list[StrategyOption]:
    options = []
    source_titles = [_source_label(source) for source in context.fuentes_recuperadas]
    has_authoritative_support = any(
        _source_hierarchy(source) in (
            SourceHierarchy.NORMATIVA.value,
            SourceHierarchy.JURISPRUDENCIA.value,
        )
        for source in context.fuentes_recuperadas
    )
    has_only_internal_support = bool(source_titles) and not has_authoritative_support

    text = context.text_clean.casefold()
    explicit_actions = {
        (item.get("tipo") or "").casefold()
        for item in context.actuaciones_detectadas
    }
    deadline_actions = {
        (item.get("tipo_actuacion") or "").casefold()
        for item in context.plazos_detectados
    }

    for candidate in candidates:
        trigger = candidate["trigger"]
        name = candidate["nombre"]
        name_key = name.casefold()

        if name_key in text:
            character = StrategyCharacter.EXTRAIDO
        elif trigger == "explicit" or any(
            key in explicit_actions or key in deadline_actions
            for key in (
                "traslado",
                "intimacion",
                "vista",
                "plazo_para_contestar",
                "plazo_para_apelar",
                "plazo_para_subsanar",
            )
        ):
            character = StrategyCharacter.INFERIDO
        else:
            character = StrategyCharacter.SUGERENCIA

        strength_score = 0.35
        if trigger == "explicit":
            strength_score += 0.15
        if context.etapa_procesal:
            strength_score += 0.1
        if context.objetivo_abogado:
            strength_score += 0.1
        if has_authoritative_support:
            strength_score += 0.2
        elif has_only_internal_support:
            strength_score += 0.05
        else:
            strength_score -= 0.05
        if not context.text_clean.strip():
            strength_score -= 0.2

        if strength_score >= 0.75:
            solidity = StrategySolidity.ALTA
        elif strength_score >= 0.5:
            solidity = StrategySolidity.MEDIA
        else:
            solidity = StrategySolidity.BAJA

        support = source_titles[:3]
        if has_only_internal_support:
            support = [
                f"{label} (referencial, no autoritativo)"
                for label in support
            ]

        options.append(
            StrategyOption(
                nombre=name,
                caracter=character,
                justificacion_breve=candidate["justificacion"],
                requisitos=candidate["requisitos"],
                ventajas=candidate["ventajas"],
                riesgos=candidate["riesgos"],
                respaldo_disponible=support,
                nivel_solidez=solidity,
            )
        )

    return _sort_options(options)


def _sort_options(options: list[StrategyOption]) -> list[StrategyOption]:
    solidity_order = {
        StrategySolidity.ALTA: 0,
        StrategySolidity.MEDIA: 1,
        StrategySolidity.BAJA: 2,
    }
    return sorted(
        options,
        key=lambda item: (solidity_order[item.nivel_solidez], item.nombre.casefold()),
    )


def _source_hierarchy(source) -> str:
    if hasattr(source, "source_hierarchy"):
        hierarchy = source.source_hierarchy
        return hierarchy.value if hasattr(hierarchy, "value") else str(hierarchy)
    return str(source.get("source_hierarchy", ""))


def _source_label(source) -> str:
    if hasattr(source, "document_title"):
        return source.document_title
    return source.get("document_title", "Fuente sin título")
