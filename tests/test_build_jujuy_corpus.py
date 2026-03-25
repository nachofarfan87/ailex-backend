import json
from pathlib import Path

from scripts import build_jujuy_corpus


def test_build_corpus_always_writes_report(tmp_path, monkeypatch):
    input_dir = tmp_path / "raw"
    for folder in ("alimentos", "divorcio", "sucesiones"):
        target = input_dir / folder
        target.mkdir(parents=True)
        (target / f"{folder}.pdf").write_bytes(b"fake")

    target_dir = tmp_path / "jurisprudence"
    report_path = target_dir / "jujuy_build_report.json"

    monkeypatch.setattr(build_jujuy_corpus, "TARGET_CORPUS_DIR", target_dir)
    monkeypatch.setattr(build_jujuy_corpus, "BUILD_REPORT_PATH", report_path)
    monkeypatch.setattr(build_jujuy_corpus, "extract_text_from_pdf", lambda _: "")

    report = build_jujuy_corpus.build_corpus(input_dir)

    assert report_path.exists()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"
    assert persisted["totals"]["skipped_empty_text"] == 3


def test_build_case_dict_sanitizes_parser_output(tmp_path):
    pdf_file = tmp_path / "SUCESION - SALCEDO.pdf"
    pdf_file.write_bytes(b"fake")
    parser = build_jujuy_corpus.JurisprudenceParser()
    text = """
    PODER JUDICIAL DE LA PROVINCIA DE JUJUY
    JUZGADO DE PRIMERA INSTANCIA No 3 - SECRETARIA 5
    SAN SALVADOR DE JUJUY, 2 DE MARZO DE 2017
    AUTOS Y VISTOS:
    Los de estos Expte No B-228194/10 caratulado: "SUCESORIO: SALCEDO, NESTOR LIDORO"
    FUNDAMENTOS:
    Corresponde reconocer la posesion hereditaria en los terminos del art. 2337 y art. 2426 del CCyC.
    La nueva ley arancelaria establece en su art. 67 pautas de honorarios y los arts. 23, 37 y 15 de la ley 6358.
    PARTE DISPOSITIVA:
    I.- Declarar que por fallecimiento de SALCEDO, NESTOR LIDORO le suceden sus herederos.
    """
    parsed_case = parser.parse(text)

    case_dict = build_jujuy_corpus.build_case_dict(
        parsed_case=parsed_case,
        text=text,
        pdf_file=pdf_file,
        sub_dir_name="sucesiones",
        case_id="jujuy-sucesiones-salcedo",
    )

    assert case_dict["case_name"] == "SUCESORIO: SALCEDO, NESTOR LIDORO"
    assert case_dict["applied_articles"] == ["2337", "2426"]
    assert "poder judicial" not in case_dict["legal_issue"].lower()
    assert len(case_dict["legal_issue"]) <= 240
