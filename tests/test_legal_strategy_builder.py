from legal_engine.legal_strategy_builder import build_legal_strategy


def test_build_legal_strategy_for_alimentos_returns_structured_output():
    result = build_legal_strategy(
        query="El padre de mi hijo no paga alimentos desde hace 4 meses",
        facts={
            "tipo_accion": "alimentos",
            "variables_detectadas": {
                "ingresos_demandado": "empleado municipal",
                "edad_hijo": 10,
                "convivencia": "con la madre",
                "incumplimientos": "total",
                "urgencia": True,
            },
        },
        classification={"action_slug": "alimentos_hijos"},
    )

    assert result["tipo_accion"] == "alimentos"
    assert result["estrategia"]["urgencia"] is True
    assert "demanda de alimentos" in result["estrategia"]["pretension_principal"]
    assert result["parametros_clave"]["porcentaje"]
    assert result["parametros_clave"]["medidas"]
    assert result["fundamentos"]


def test_build_legal_strategy_for_divorcio_avoids_document_generation_logic():
    result = build_legal_strategy(
        query="Quiero iniciar divorcio unilateral en Jujuy",
        facts={"tipo_accion": "divorcio"},
        classification={"action_slug": "divorcio_unilateral"},
    )

    assert result["tipo_accion"] == "divorcio"
    assert "divorcio unilateral" in result["estrategia"]["pretension_principal"]
    assert result["parametros_clave"]["porcentaje"] == ""
    assert result["fundamentos"]
