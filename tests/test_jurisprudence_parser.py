from legal_engine.jurisprudence_parser import JurisprudenceParser


SAMPLE_DIVORCIO_TEXT = """
CAMARA DE APELACIONES DE FAMILIA DE JUJUY
San Salvador de Jujuy, 14 de agosto de 2024.

Divorcio: Collado Maria Cecilia c/ Lopez Marcos Manuel

AUTOS Y VISTOS

RESULTA:
Que la parte actora promovio demanda de divorcio y solicito se tengan presentes los efectos accesorios.
Refirio la existencia de hijos menores y la necesidad de ordenar la propuesta reguladora.

CONSIDERANDO:
Que el divorcio es incausado conforme al art. 437 del CCyC.
Que los arts. 438 y 439 del CCyC imponen considerar la propuesta reguladora.
La falta de acuerdo sobre efectos accesorios no impide la disolucion del vinculo.

RESUELVE:
I) Hacer lugar a la demanda de divorcio.
II) Disolver el vinculo matrimonial de las partes.
III) Diferir el tratamiento de los efectos accesorios para la etapa pertinente.
"""


SAMPLE_ALIMENTOS_TEXT = """
JUZGADO DE FAMILIA DE SAN SALVADOR DE JUJUY
12/04/2024

Alimentos: Felix c/ Amador

RESULTA:
La progenitora promovio accion de alimentos para su hijo menor.
Denuncio gastos de escolaridad y salud y requirio cuota provisoria.

FUNDAMENTOS:
El art. 658 del CCyC y el art. 659 del CCyC sustentan el deber alimentario.
La necesidad actual del hijo y la urgencia de la tutela justifican una decision inmediata.

RESUELVE:
1) Fijar cuota alimentaria provisoria.
2) Intimar al demandado al cumplimiento.
"""


SAMPLE_SUCCESSION_TEXT = """
PODER JUDICIAL DE LA PROVINCIA DE JUJUY
JUZGADO DE PRIMERA INSTANCIA No 3 - SECRETARIA 5
SAN SALVADOR DE JUJUY, 2 DE MARZO DE 2017

AUTOS Y VISTOS:
Los de estos Expte No B-228194/10 caratulado: "SUCESORIO: SALCEDO, NESTOR LIDORO"

RESULTA:
Que se solicito la declaratoria de herederos del causante.

FUNDAMENTOS:
Corresponde reconocer la posesion hereditaria en los terminos del art. 2337 y art. 2426 del CCyC.
Siguiendo este orden de ideas, la nueva ley arancelaria vigente en la Provincia de Jujuy No 6368 establece en su art. 67
que las disposiciones de la presente ley se aplicaran a todos los procesos en curso.
Conforme a lo expuesto corresponde regular honorarios conforme Ley No 6358, arts. 23, 37 cctes y art. 15.

PARTE DISPOSITIVA:
I.- Declarar que por fallecimiento de SALCEDO, NESTOR LIDORO le suceden sus herederos.
"""


def test_parser_extracts_divorce_case_name():
    parser = JurisprudenceParser()

    result = parser.parse(SAMPLE_DIVORCIO_TEXT)

    assert result.case_name == "Divorcio: Collado Maria Cecilia c/ Lopez Marcos Manuel"


def test_parser_extracts_succession_case_name():
    parser = JurisprudenceParser()

    result = parser.parse(SAMPLE_SUCCESSION_TEXT)

    assert result.case_name == "SUCESORIO: SALCEDO, NESTOR LIDORO"


def test_parser_detects_applied_articles_without_noise():
    parser = JurisprudenceParser()

    result = parser.parse(SAMPLE_SUCCESSION_TEXT)

    assert result.applied_articles == ["2337", "2426"]


def test_parser_builds_clean_legal_issue():
    parser = JurisprudenceParser()

    result = parser.parse(SAMPLE_DIVORCIO_TEXT)

    assert "san salvador de jujuy" not in result.legal_issue.lower()
    assert "poder judicial" not in result.legal_issue.lower()
    assert len(result.legal_issue) <= 240
    assert "divorcio" in result.legal_issue.lower()


def test_parser_detects_action_slug():
    parser = JurisprudenceParser()

    assert parser.parse(SAMPLE_DIVORCIO_TEXT).action_slug == "divorcio"
    assert parser.parse(SAMPLE_ALIMENTOS_TEXT).action_slug == "alimentos_hijos"
    assert parser.parse(SAMPLE_SUCCESSION_TEXT).action_slug == "sucesion_ab_intestato"


def test_parser_extracts_resolutive_section_and_outcome():
    parser = JurisprudenceParser()

    result = parser.parse(SAMPLE_ALIMENTOS_TEXT)

    assert "Fijar cuota alimentaria provisoria" in result.decision_summary
    assert "Fijar cuota alimentaria provisoria" in result.holding or "Fijar cuota alimentaria provisoria" in result.outcome


def test_parser_survives_missing_sections():
    parser = JurisprudenceParser()
    text = """
    JUZGADO CIVIL Y COMERCIAL DE JUJUY
    10/11/2023
    P. R. J. s/ sucesion ab intestato
    Se presenta solicitud de declaratoria de herederos. Se cita art. 2337 del CCyC.
    """

    result = parser.parse(text)

    assert result.case_name == "P. R. J. s/ sucesion ab intestato"
    assert result.action_slug == "sucesion_ab_intestato"
    assert "2337" in result.applied_articles
    assert result.full_text


def test_parser_to_corpus_dict_is_compatible():
    parser = JurisprudenceParser()
    result = parser.parse(SAMPLE_DIVORCIO_TEXT)

    payload = result.to_corpus_dict(
        case_id="parser-test-001",
        source="parser_fixture",
        source_url="fixture://parser-test-001",
        dataset_kind="fixture",
    )

    assert payload["case_id"] == "parser-test-001"
    assert payload["source"] == "parser_fixture"
    assert payload["action_slug"] == "divorcio"
    assert payload["document_type"] == "sentencia"
