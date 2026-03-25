"""
Regresiones de OCR fallback para PDFs escaneados.
"""

from app.api.routes import documents


NORMATIVE_OCR_TEXT = """
LEY DE PRUEBA

Articulo 1.- La presente ley regula el procedimiento de prueba documental.

Articulo 2.- Las notificaciones judiciales podran incorporarse en soporte digital.

Articulo 3.- El tribunal debera preservar la integridad del documento escaneado.
""".strip()


async def test_upload_pdf_uses_ocr_fallback_when_pdf_text_is_too_short(client, monkeypatch):
    documents.store.clear()

    def fake_extract(file_path: str) -> dict:
        return {"text": "  ", "pages": 3, "method": "pdfplumber"}

    def fake_ocr(file_path: str) -> dict:
        return {
            "text": NORMATIVE_OCR_TEXT,
            "pages_processed": 3,
            "total_pages": 3,
            "method": "ocr/pytesseract",
            "text_length": len(NORMATIVE_OCR_TEXT),
            "warning": "",
        }

    monkeypatch.setattr(documents.ingestion.extractor, "extract", fake_extract)
    monkeypatch.setattr(documents.ingestion.ocr_service, "extract_pdf", fake_ocr)

    try:
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("cedula-escaneada.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={
                "title": "Cedula escaneada",
                "source_type": "ley",
                "jurisdiction": "Nacional",
                "legal_area": "procesal",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["extraction_mode"] == "ocr"
        assert data["ocr_used"] is True
        assert data["chunk_count"] > 1

        detail = await client.get(f"/api/documents/{data['document_id']}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["source_hierarchy"] == "normativa"
        assert payload["extraction_mode"] == "ocr"
        assert payload["ocr_used"] is True
        assert payload["extracted_text_length"] == len(NORMATIVE_OCR_TEXT)
    finally:
        documents.store.clear()


async def test_upload_pdf_keeps_pdf_text_path_when_extraction_is_good(client, monkeypatch):
    documents.store.clear()
    ocr_called = False

    def fake_extract(file_path: str) -> dict:
        return {
            "text": (
                "Notificacion judicial con texto embebido suficiente para evitar OCR. "
                "Se corre traslado por cinco dias habiles y se intima a constituir domicilio."
            ),
            "pages": 1,
            "method": "pdfplumber",
        }

    def fake_ocr(file_path: str) -> dict:
        nonlocal ocr_called
        ocr_called = True
        raise AssertionError("OCR no deberia ejecutarse cuando PDF ya tiene texto")

    monkeypatch.setattr(documents.ingestion.extractor, "extract", fake_extract)
    monkeypatch.setattr(documents.ingestion.ocr_service, "extract_pdf", fake_ocr)

    try:
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("providencia.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={
                "title": "Providencia con texto",
                "source_type": "jurisprudencia",
                "jurisdiction": "Jujuy",
                "legal_area": "civil",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["extraction_mode"] == "pdf_text"
        assert data["ocr_used"] is False
        assert ocr_called is False
    finally:
        documents.store.clear()


async def test_upload_pdf_returns_clear_error_when_pdf_text_and_ocr_fail(client, monkeypatch):
    documents.store.clear()

    def fake_extract(file_path: str) -> dict:
        raise RuntimeError("pdfplumber no pudo leer el PDF")

    def fake_ocr(file_path: str) -> dict:
        raise RuntimeError("tesseract no disponible")

    monkeypatch.setattr(documents.ingestion.extractor, "extract", fake_extract)
    monkeypatch.setattr(documents.ingestion.ocr_service, "extract_pdf", fake_ocr)

    response = await client.post(
        "/api/documents/upload",
        files={"file": ("resolucion-escaneada.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={
            "title": "Resolucion escaneada",
            "source_type": "jurisprudencia",
            "jurisdiction": "Jujuy",
        },
    )

    assert response.status_code == 400
    assert "OCR fallback fallo" in response.json()["detail"]
