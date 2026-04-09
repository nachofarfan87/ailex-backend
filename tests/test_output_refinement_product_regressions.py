from __future__ import annotations

from app.services.output_refinement_service import extract_quick_start, prioritize_actions, simplify_strategy_text


def test_question_like_candidates_do_not_survive_as_actions_or_quick_start():
    actions = [
        "Existen hijos menores o con capacidad restringida que haya que contemplar",
        "Acreditar vinculo, ordenar cuidado personal y preparar una presentacion util.",
        "¿Hay hijos en comun?",
    ]

    prioritized = prioritize_actions(actions, case_domain="divorcio", facts={"hay_hijos": True})
    quick_start = extract_quick_start(actions, case_domain="divorcio", facts={"hay_hijos": True})

    assert prioritized == ["Acreditar vinculo, ordenar cuidado personal y preparar una presentacion util."]
    assert "existen hijos" not in quick_start.lower()
    assert "hay hijos" not in quick_start.lower()


def test_divorce_with_children_prioritizes_parental_axis_over_housing():
    prioritized = prioritize_actions(
        [
            "Inventariar bienes y revisar vivienda familiar.",
            "Ordenar primero cuidado personal, regimen comunicacional y alimentos de los hijos dentro de la propuesta reguladora.",
        ],
        case_domain="divorcio",
        facts={"hay_hijos": True},
    )

    assert "cuidado personal" in prioritized[0].lower()


def test_simplify_strategy_text_keeps_caution_signal_when_it_appears_later():
    text = (
        "La narrativa base debe ordenar el planteo inicial. "
        "Hay conflicto actual sobre alimentos. "
        "La prueba disponible todavia es parcial. "
        "El caso requiere prudencia y saneamiento previo antes de ampliar la pretension. "
        "Conviene consolidar soporte probatorio."
    )

    simplified = simplify_strategy_text(text)

    assert "prudencia" in simplified.lower() or "saneamiento" in simplified.lower()
