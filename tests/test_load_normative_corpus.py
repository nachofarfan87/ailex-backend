from app.modules.legal import load_normative_corpus as legal_module_loader
from legal_sources.load_norms import load_normative_corpus


def test_load_normative_corpus_returns_expected_files():
    corpus = load_normative_corpus()

    assert set(corpus) == {
        "constitucion_nacional",
        "codigo_civil_comercial",
        "constitucion_jujuy",
        "cpcc_jujuy",
        "lct_20744",
    }

    for document in corpus.values():
        assert isinstance(document, dict)
        assert "articulos" in document


def test_legal_modules_can_access_normative_corpus_loader():
    assert legal_module_loader is load_normative_corpus
    assert legal_module_loader() is load_normative_corpus()
