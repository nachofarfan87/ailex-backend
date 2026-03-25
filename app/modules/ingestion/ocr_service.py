"""
AILEX - OCR fallback para PDFs escaneados o basados en imagen.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class OCRService:
    """OCR local sobre PDFs usando pdf2image + pytesseract."""

    def __init__(self):
        self.language = settings.ocr_language
        self.max_pdf_pages = settings.ocr_max_pdf_pages
        self.dpi = settings.ocr_dpi
        self.timeout_seconds = settings.ocr_timeout_seconds
        self.poppler_path = settings.ocr_poppler_path
        self.tesseract_cmd = settings.ocr_tesseract_cmd

    def extract_pdf(self, file_path: str) -> dict:
        """
        Ejecutar OCR sobre un PDF.

        Retorna:
            {
                "text": str,
                "pages_processed": int,
                "total_pages": int,
                "method": "ocr/pytesseract",
                "text_length": int,
                "warning": str,
            }
        """
        try:
            from pdf2image import convert_from_path, pdfinfo_from_path
        except ImportError as exc:
            raise ImportError(
                "OCR PDF requiere pdf2image. Instalar con: pip install pdf2image"
            ) from exc

        try:
            import pytesseract
        except ImportError as exc:
            raise ImportError(
                "OCR PDF requiere pytesseract. Instalar con: pip install pytesseract"
            ) from exc

        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        try:
            info = pdfinfo_from_path(
                file_path,
                poppler_path=self.poppler_path or None,
            )
            total_pages = int(info.get("Pages", 0) or 0)
        except Exception as exc:
            raise RuntimeError(
                "No se pudo inspeccionar el PDF para OCR. "
                "Verificar Poppler y el archivo de entrada."
            ) from exc

        warning = ""
        last_page = None
        if self.max_pdf_pages and total_pages and total_pages > self.max_pdf_pages:
            last_page = self.max_pdf_pages
            warning = (
                f"OCR limitado a las primeras {self.max_pdf_pages} paginas "
                f"de un PDF de {total_pages} paginas."
            )

        try:
            images = convert_from_path(
                file_path,
                dpi=self.dpi,
                first_page=1,
                last_page=last_page,
                fmt="png",
                thread_count=1,
                poppler_path=self.poppler_path or None,
            )
        except Exception as exc:
            raise RuntimeError(
                "No se pudo rasterizar el PDF para OCR. "
                "Verificar Poppler y la integridad del archivo."
            ) from exc

        if not images:
            raise RuntimeError("OCR no pudo convertir ninguna pagina del PDF.")

        text_parts = []
        for page_index, image in enumerate(images, start=1):
            try:
                page_text = pytesseract.image_to_string(
                    image,
                    lang=self.language,
                    timeout=self.timeout_seconds,
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"OCR fallo en la pagina {page_index}: {exc}"
                ) from exc

            page_text = page_text.strip()
            if page_text:
                text_parts.append(page_text)

        text = "\n\n".join(text_parts).strip()
        logger.info(
            "OCR completado en %s: %s/%s paginas, %s caracteres",
            file_path,
            len(images),
            total_pages or len(images),
            len(text),
        )
        return {
            "text": text,
            "pages_processed": len(images),
            "total_pages": total_pages or len(images),
            "method": "ocr/pytesseract",
            "text_length": len(text),
            "warning": warning,
        }
