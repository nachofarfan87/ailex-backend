from legal_engine.strategy_engine import StrategyEngine


def test_strategy_engine_routes_patrimonial_conflict_without_generic_fallback():
    engine = StrategyEngine()

    result = engine.analyze("como tendria que proceder para que mi ex esposo renuncie a la cotitularidad de mi casa")

    assert result["tipo_accion"] == "conflicto_patrimonial"
    strategy = result["estrategia"]
    assert strategy["pretension_principal"] == "definicion_patrimonial_sobre_inmueble"
    joined_questions = " ".join(strategy["preguntas_criticas"]).lower()
    assert "ganancial" in joined_questions or "antes o durante el matrimonio" in joined_questions
    assert "fallback generico" in " ".join(strategy["validation_notes"]).lower()


def test_strategy_engine_routes_higher_education_case_as_student_subscenario():
    engine = StrategyEngine()

    result = engine.analyze("se puede subir la cuota alimentaria si esta en nivel universitario")

    assert result["tipo_accion"] == "alimentos"
    strategy = result["estrategia"]
    assert strategy["pretension_principal"] == "cuota_alimentaria"
    assert "que edad tiene el hijo o hija" in strategy["preguntas_criticas"]


def test_strategy_engine_blocks_student_strategy_when_query_says_22_and_not_studying():
    engine = StrategyEngine()

    result = engine.analyze("hasta que edad mi ex esposo puede pasar cuota alimentaria si mi hija tiene 22 y no estudia")

    variables = result["variables"]
    strategy = result["estrategia"]
    assert variables["categoria_hijo"] == "mayor_21_no_estudia"
    assert strategy["pretension_principal"] == "analisis_cese_o_limite_cuota_hijo_mayor"
    assert "certificado_alumno_regular" not in strategy["prueba_sugerida"]
    assert "art_663_ccyc" in strategy["estrategias_bloqueadas"]


def test_strategy_engine_multiple_ages_do_not_collapse_into_single_relevant_age():
    engine = StrategyEngine()

    result = engine.analyze("tengo dos hijos de 13 y 21 anos y quiero saber la cuota alimentaria")

    variables = result["variables"]
    assert variables["edades_hijos"] == [13, 21]
    assert variables["hay_multiples_edades"] is True
    assert "edad_relevante" not in variables
    assert set(variables["categorias_etarias_detectadas"]) == {"menor_18", "entre_18_y_21"}
    assert "que edad tiene el hijo o hija" in result["estrategia"]["preguntas_criticas"]


def test_strategy_engine_treats_22_and_not_working_different_from_22_and_studying():
    engine = StrategyEngine()

    not_working = engine.analyze("mi hija tiene 22 anos y no trabaja, hasta cuando corresponde cuota alimentaria")
    studying = engine.analyze("mi hija tiene 22 anos y estudia en la universidad, se puede subir la cuota alimentaria")

    assert not_working["variables"]["categoria_hijo"] == "mayor_21_indeterminado"
    assert not_working["variables"]["no_trabaja"] is True
    assert not_working["estrategia"]["parametros"]["autosustento_actual"]
    assert studying["variables"]["categoria_hijo"] == "mayor_21_estudia"
    assert "certificado_alumno_regular" in studying["estrategia"]["prueba_sugerida"]
