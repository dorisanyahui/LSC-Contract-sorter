from __future__ import annotations

import re

from src.models.enums import DocType, PageType, PacketType
from src.models.schema import OCRPageResult, PacketResult


_DOC_TYPE_HEADER_PATTERNS = [
    (re.compile(r"采购合同|purchase\s+order|采购订单", re.IGNORECASE), DocType.PURCHASE_ORDER),
    (re.compile(r"报价单|quotation|quote", re.IGNORECASE), DocType.QUOTE),
    (re.compile(r"项目建议书|proposal|建议书", re.IGNORECASE), DocType.PROPOSAL),
    (re.compile(r"srf|服务需求表|service\s+request\s+form", re.IGNORECASE), DocType.SRF),
    (re.compile(r"付款通知|payment\s+notice|催款", re.IGNORECASE), DocType.PAYMENT_NOTICE),
    (re.compile(r"附件|attachment|附录|appendix", re.IGNORECASE), DocType.ATTACHMENT),
    (re.compile(r"合同|协议|agreement|contract", re.IGNORECASE), DocType.CONTRACT),
]


def _detect_doc_type_from_text(text: str) -> DocType:
    """Detect document type from text using header patterns."""
    for pattern, doc_type in _DOC_TYPE_HEADER_PATTERNS:
        if pattern.search(text):
            return doc_type
    return DocType.UNKNOWN


def _is_new_packet_boundary(page_type: PageType, prev_page_type: PageType | None, text: str) -> bool:
    """Determine if a page starts a new packet."""
    # A title page that comes after non-title content signals a new packet
    if page_type == PageType.TITLE_PAGE and prev_page_type not in (None, PageType.TITLE_PAGE):
        return True

    # An appendix page can be a separate packet
    if page_type == PageType.APPENDIX_PAGE and prev_page_type not in (None, PageType.APPENDIX_PAGE, PageType.TITLE_PAGE):
        return True

    return False


class Packetizer:
    """Splits a document into logical packets (sub-documents)."""

    def split(
        self,
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
    ) -> list[PacketResult]:
        """Split OCR results into packets based on page type transitions."""
        if not ocr_results:
            return []

        packets: list[PacketResult] = []
        current_start = 0
        prev_page_type: PageType | None = None

        for i, result in enumerate(ocr_results):
            page_no = result.page_no
            page_type = page_types.get(page_no, PageType.UNKNOWN)

            is_boundary = (
                i > 0 and _is_new_packet_boundary(page_type, prev_page_type, result.raw_text)
            )

            if is_boundary and i > current_start:
                # Finalize current packet
                packet = self._make_packet(
                    ocr_results[current_start:i],
                    page_types,
                    len(packets),
                )
                packets.append(packet)
                current_start = i

            prev_page_type = page_type

        # Finalize last packet
        if current_start < len(ocr_results):
            packet = self._make_packet(
                ocr_results[current_start:],
                page_types,
                len(packets),
            )
            packets.append(packet)

        # Ensure at least one packet
        if not packets:
            packet = self._make_packet(ocr_results, page_types, 0)
            packets.append(packet)

        return packets

    def _make_packet(
        self,
        pages: list[OCRPageResult],
        page_types: dict[int, PageType],
        idx: int,
    ) -> PacketResult:
        """Create a PacketResult from a slice of OCR pages."""
        start_page = pages[0].page_no if pages else 0
        end_page = pages[-1].page_no if pages else 0

        # Determine packet type from the first page's type
        first_page_type = page_types.get(start_page, PageType.UNKNOWN)
        packet_type = first_page_type.value

        # Collect all text to detect doc type
        all_text = "\n".join(p.raw_text for p in pages)
        doc_type = _detect_doc_type_from_text(all_text[:2000])

        # Extract title hint from first page
        title_hint = ""
        if pages:
            first_lines = pages[0].raw_text.strip().splitlines()[:5]
            title_hint = " ".join(line.strip() for line in first_lines if line.strip())[:200]

        return PacketResult(
            packet_id=f"packet_{idx:03d}",
            start_page=start_page,
            end_page=end_page,
            packet_type=packet_type,
            title_hint=title_hint,
            doc_type=doc_type,
            fields={},
        )
