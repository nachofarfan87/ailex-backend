"""
AILEX — Extracción de texto desde archivos.

Soporta PDF, DOCX y TXT.
Extrae texto preservando estructura cuando es posible.
"""

import os
import re


class TextExtractor:
    """Extracción de texto crudo desde diferentes formatos."""

    SUPPORTED = {"pdf", "docx", "txt"}

    def extract(self, file_path: str) -> dict:
        """
        Extraer texto de un archivo.
        Retorna: {"text": str, "pages": int, "method": str}
        """
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")

        if ext not in self.SUPPORTED:
            raise ValueError(f"Formato no soportado: {ext}")

        if ext == "pdf":
            return self._extract_pdf(file_path)
        elif ext == "docx":
            return self._extract_docx(file_path)
        elif ext == "txt":
            return self._extract_txt(file_path)

    def extract_from_bytes(self, content: bytes, file_type: str) -> dict:
        """Extraer texto desde bytes en memoria."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            suffix=f".{file_type}", delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            return self.extract(tmp_path)
        finally:
            os.unlink(tmp_path)

    def _extract_pdf(self, file_path: str) -> dict:
        """Extraer texto de PDF usando pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber requerido para PDFs. "
                "Instalar con: pip install pdfplumber"
            )

        text_parts = []
        page_count = 0

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)

        return {
            "text": "\n\n".join(text_parts),
            "pages": page_count,
            "method": "pdfplumber",
        }

    def _extract_docx(self, file_path: str) -> dict:
        """Extraer texto de DOCX usando python-docx."""
        try:
            from docx import Document
        except ImportError:
            raise ImportError(
                "python-docx requerido para DOCX. "
                "Instalar con: pip install python-docx"
            )

        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

        return {
            "text": "\n\n".join(paragraphs),
            "pages": max(1, len(paragraphs) // 30),  # estimación
            "method": "python-docx",
        }

    def _extract_txt(self, file_path: str) -> dict:
        """Extraer texto de archivo plano."""
        encodings = ["utf-8", "latin-1", "cp1252"]

        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    text = f.read()
                return {
                    "text": text,
                    "pages": 1,
                    "method": f"txt/{enc}",
                }
            except (UnicodeDecodeError, UnicodeError):
                continue

        raise ValueError(f"No se pudo decodificar {file_path}")
