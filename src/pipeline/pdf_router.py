from __future__ import annotations

from pathlib import Path


class PDFRouter:
    """Analyzes PDF files to determine if they have a text layer or are scanned."""

    TEXT_LAYER_THRESHOLD = 50  # avg chars per page below this -> treat as scanned

    def analyze(self, pdf_path: Path) -> dict:
        """Analyze a PDF and return metadata about its content.

        Returns dict with:
            has_text_layer: bool
            page_count: int
            text_by_page: dict[int, str]
            text_total_chars: int
        """
        text_by_page = self.extract_text_layer(pdf_path)
        page_count = len(text_by_page)
        text_total_chars = sum(len(t) for t in text_by_page.values())

        if page_count > 0:
            avg_chars = text_total_chars / page_count
        else:
            avg_chars = 0

        has_text_layer = avg_chars >= self.TEXT_LAYER_THRESHOLD

        return {
            "has_text_layer": has_text_layer,
            "page_count": page_count,
            "text_by_page": text_by_page,
            "text_total_chars": text_total_chars,
        }

    def extract_text_layer(self, pdf_path: Path) -> dict[int, str]:
        """Extract text layer from PDF using PyMuPDF.

        Returns dict mapping page_no (0-indexed) to extracted text.
        """
        import fitz  # PyMuPDF

        text_by_page: dict[int, str] = {}
        try:
            doc = fitz.open(str(pdf_path))
            for page_no in range(len(doc)):
                page = doc[page_no]
                text = page.get_text("text")
                text_by_page[page_no] = text
            doc.close()
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to extract text layer from {pdf_path}: {e}")

        return text_by_page
