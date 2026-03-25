"""
AILEX — Comparación prudente entre opciones estratégicas.
"""

from app.modules.strategy.schemas import StrategyComparison, StrategyOption


def build_option_comparisons(
    options: list[StrategyOption],
    has_missing_data: bool,
) -> list[StrategyComparison]:
    available = {option.nombre: option for option in options}

    conservative = _pick_names(
        available,
        [
            "esperar constancia o documentación antes de actuar",
            "subsanar presentación",
            "contestar traslado",
            "reservar planteo",
        ],
    )
    standard = _pick_names(
        available,
        [
            "contestar traslado",
            "subsanar presentación",
            "solicitar pronto despacho",
            "intimar previamente",
        ],
    )
    assertive = _pick_names(
        available,
        [
            "promover medida cautelar",
            "apelar",
            "ampliar prueba",
            "intimar previamente",
        ],
    )
    defer = _pick_names(
        available,
        [
            "esperar constancia o documentación antes de actuar",
            "reservar planteo",
            "subsanar presentación",
        ],
    )

    return [
        StrategyComparison(
            perfil="conservadora",
            opciones_priorizadas=conservative,
            tradeoffs=[
                "Reduce exposición inmediata, pero puede resignar velocidad o presión táctica.",
                "Es más razonable cuando faltan constancias, fechas o pieza completa.",
            ],
            nota_prudencia=(
                "No presupone renunciar a otras vías; su valor depende de cuánto falte para cerrar el cuadro de hechos."
            ),
        ),
        StrategyComparison(
            perfil="estándar",
            opciones_priorizadas=standard,
            tradeoffs=[
                "Busca mover el expediente sin asumir el mayor riesgo disponible.",
                "Puede equilibrar tiempo, preservación de defensas y necesidad de respuesta inmediata.",
            ],
            nota_prudencia=(
                "Conviene revisar si la documentación disponible sostiene el paso elegido antes de ejecutarlo."
            ),
        ),
        StrategyComparison(
            perfil="ofensiva prudente",
            opciones_priorizadas=assertive,
            tradeoffs=[
                "Puede generar mayor tracción procesal, pero exige mejor base fáctica y documental.",
                "Aumenta el costo de error si la vía elegida no era admisible o estaba inmadura.",
            ],
            nota_prudencia=(
                "No equivale a recomendar agresividad por defecto; solo muestra opciones que podrían evaluarse si la base mejora."
            ),
        ),
        StrategyComparison(
            perfil="diferir_decision_por_falta_de_datos",
            opciones_priorizadas=defer,
            tradeoffs=[
                "Protege contra decisiones irreversibles apoyadas en información incompleta.",
                "Puede postergar una reacción útil si el expediente sí exige respuesta inmediata.",
            ],
            nota_prudencia=(
                "Este perfil gana peso cuando faltan datos críticos."
                if has_missing_data
                else "Aun con información razonable, puede ser útil como control de prudencia."
            ),
        ),
    ]


def _pick_names(
    options: dict[str, StrategyOption],
    preferred_names: list[str],
) -> list[str]:
    selected = [name for name in preferred_names if name in options]
    if selected:
        return selected[:3]
    return list(options.keys())[:3]
