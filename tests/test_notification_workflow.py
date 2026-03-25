"""Focused tests for the production notification workflow."""

from app.api.routes import documents
from app.db.store import DocumentStore
from app.modules.legal.analyze_notification import analyze_notification


PROCEDURAL_CORPUS_TEXT = """
CODIGO PROCESAL CIVIL DE JUJUY

Articulo 1.- El traslado de la demanda debe contestarse dentro del plazo procesal aplicable.
Articulo 2.- Las intimaciones deben cumplirse dentro del termino fijado por el tribunal, bajo apercibimiento.
Articulo 3.- La integracion del tribunal debe notificarse a las partes.
""".strip()


def _clear_store():
    DocumentStore().clear()


async def _seed_corpus(client):
    response = await client.post(
        "/api/documents/upload/text",
        data={
            "text": PROCEDURAL_CORPUS_TEXT,
            "title": "Codigo procesal base",
            "source_type": "codigo",
            "jurisdiction": "Jujuy",
            "legal_area": "civil",
            "scope": "corpus",
        },
    )
    assert response.status_code == 200


async def test_analyze_notification_detects_traslado_with_deadline_and_sources(client):
    _clear_store()
    await _seed_corpus(client)

    memo = await analyze_notification(
        text=(
            "JUZGADO CIVIL Y COMERCIAL N 3 DE JUJUY\n"
            "Expte. 12345/2026\n"
            "Cedula. Corrase traslado de la demanda por 5 dias. Notifiquese."
        ),
        jurisdiction="Jujuy",
        legal_area="civil",
    )

    assert memo["document_detected"] == "cedula judicial"
    assert memo["court"]
    assert memo["case_number"] == "12345/2026"
    assert "traslado" in memo["procedural_action"]
    assert "5 dias" in memo["deadline"]
    assert memo["recommended_next_step"]
    assert memo["relevant_sources"]
    assert memo["confidence"] in {"high", "medium"}


async def test_workflow_handles_integration_notice_without_inventing_deadline(client):
    _clear_store()
    await _seed_corpus(client)

    response = await client.post(
        "/api/workflow/notification-response",
        json={
            "texto": (
                "Camara de Apelaciones en lo Civil de Jujuy\n"
                "Expte. 555/2026\n"
                "Notifiquese la integracion del tribunal para el conocimiento de las partes."
            ),
            "fuero": "civil",
            "generar_borrador": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["procedural_action"] == "integracion del tribunal"
    assert payload["deadline"] == ""
    assert "No se informa un plazo expreso" in payload["observations"]
    assert payload["confidence"] in {"medium", "low"}


async def test_workflow_detects_intimacion_and_procedural_risk(client):
    _clear_store()
    await _seed_corpus(client)

    response = await client.post(
        "/api/workflow/notification-response",
        json={
            "texto": (
                "Juzgado Civil N 2\n"
                "Intimese a la parte actora a acompanar la documental ofrecida en el plazo de 3 dias, "
                "bajo apercibimiento de ley."
            ),
            "fuero": "civil",
            "generar_borrador": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["procedural_action"] == "intimacion"
    assert "3 dias" in payload["deadline"]
    assert any("apercibimiento" in risk.lower() or "intimacion" in risk.lower() for risk in payload["procedural_risks"])


async def test_analyze_notification_marks_ambiguous_short_text_as_low_confidence():
    _clear_store()
    memo = await analyze_notification(
        text="Se agrega escrito.",
        jurisdiction="Jujuy",
    )

    assert memo["procedural_action"] == "actuacion no determinada"
    assert memo["deadline"] == ""
    assert memo["confidence"] == "low"
    assert "plazo no surge" in memo["observations"].lower()


async def test_case_upload_with_ocr_can_feed_notification_workflow(client, monkeypatch):
    _clear_store()
    await _seed_corpus(client)

    ocr_text = (
        "CEDULA\n"
        "JUZGADO CIVIL N 4\n"
        "Expte. 999/2026\n"
        "Corrase traslado de la demanda por 5 dias."
    )

    def fake_extract(file_path: str) -> dict:
        return {"text": " ", "pages": 1, "method": "pdfplumber"}

    def fake_ocr(file_path: str) -> dict:
        return {
            "text": ocr_text,
            "pages_processed": 1,
            "total_pages": 1,
            "method": "ocr/pytesseract",
            "text_length": len(ocr_text),
            "warning": "",
        }

    monkeypatch.setattr(documents.ingestion.extractor, "extract", fake_extract)
    monkeypatch.setattr(documents.ingestion.ocr_service, "extract_pdf", fake_ocr)

    upload = await client.post(
        "/api/documents/upload",
        files={"file": ("cedula-ocr.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={
            "title": "Cedula OCR",
            "source_type": "escrito",
            "scope": "case",
        },
    )

    assert upload.status_code == 200
    upload_payload = upload.json()
    assert upload_payload["document_scope"] == "case"
    assert upload_payload["ocr_used"] is True
    assert upload_payload["analysis_text"]

    workflow = await client.post(
        "/api/workflow/notification-response",
        json={
            "texto": upload_payload["analysis_text"],
            "fuero": "civil",
            "generar_borrador": False,
        },
    )

    assert workflow.status_code == 200
    workflow_payload = workflow.json()
    assert "traslado" in workflow_payload["procedural_action"]
    assert "5 dias" in workflow_payload["deadline"]
