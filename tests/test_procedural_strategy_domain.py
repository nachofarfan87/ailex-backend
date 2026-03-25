from legal_engine.procedural_strategy import ProceduralStrategy


def test_procedural_strategy_case_domain_overrides_generic_action_slug():
    strategy = ProceduralStrategy(default_jurisdiction="jujuy")

    plan = strategy.generate(
        query="como proceder para que mi ex renuncie a la cotitularidad de mi casa",
        classification={"action_slug": "generic", "action_label": "Consulta generica", "domain": "civil"},
        normative_reasoning={"warnings": ["No existe handler especifico; se uso fallback generico."]},
        case_structure={"risks": ["No esta claro si el bien es ganancial o propio."]},
        case_domain="conflicto_patrimonial",
    )

    rendered_steps = " ".join(step.action for step in plan.steps).lower()
    combined = " ".join([plan.strategic_notes, rendered_steps, *plan.risks, *plan.missing_info, *plan.warnings]).lower()

    assert plan.domain == "conflicto_patrimonial"
    assert "plan procesal generico" not in combined
    assert "generic" not in combined
    assert any(token in rendered_steps for token in ("adjudicacion", "liquidacion", "division"))
    assert "ganancial" in combined or "propio" in combined
