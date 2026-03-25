from legal_engine.action_classifier import ActionClassifier


def test_action_classifier_detects_divorcio_mutuo_acuerdo():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Dos personas quieren divorciarse de comun acuerdo",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio_mutuo_acuerdo"
    assert result.forum == "familia"
    assert result.jurisdiction == "jujuy"
    assert result.process_type == "voluntario"
    assert any(item["article"] == "437" for item in result.priority_articles)


def test_action_classifier_scores_indirect_phrase_ambos_conyuges():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Ambos conyuges decidieron terminar el matrimonio",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio_mutuo_acuerdo"
    assert result.confidence_score >= 0.7


def test_action_classifier_scores_indirect_phrase_esposos_separarse():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Los esposos quieren separarse",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio_mutuo_acuerdo"


def test_action_classifier_scores_indirect_phrase_disolver_vinculo():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Ambas partes quieren disolver el vinculo matrimonial",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio_mutuo_acuerdo"


def test_action_classifier_avoids_false_positive_for_non_divorce_phrase():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Los esposos quieren vender el auto familiar",
        jurisdiction="jujuy",
    )

    assert result is None


def test_action_classifier_detects_divorcio_unilateral():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Mi esposa no quiere divorciarse pero yo si",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio_unilateral"
    assert result.forum == "familia"
    assert result.process_type == "contencioso_inicial"


def test_action_classifier_detects_alimentos_hijos():
    classifier = ActionClassifier()

    result = classifier.classify(
        "El padre de mi hijo no paga alimentos",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "alimentos_hijos"
    assert result.forum == "familia"
    assert any(item["article"] == "658" for item in result.priority_articles)


def test_action_classifier_detects_sucesion_ab_intestato():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Murio mi padre y queremos iniciar la sucesion",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "sucesion_ab_intestato"
    assert result.forum == "civil"
    assert result.process_type == "voluntario_sucesorio"


def test_action_classifier_detects_basic_divorcio_query():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Quiero divorciarme",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio"
    assert result.forum == "familia"
    assert result.process_type == "contencioso_o_voluntario"


def test_action_classifier_detects_quiero_el_divorcio():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Quiero el divorcio",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio"
    assert result.forum == "familia"


def test_action_classifier_detects_me_quiero_divorciar():
    classifier = ActionClassifier()

    result = classifier.classify(
        "Me quiero divorciar",
        jurisdiction="jujuy",
    )

    assert result is not None
    assert result.action_slug == "divorcio"
    assert result.forum == "familia"
