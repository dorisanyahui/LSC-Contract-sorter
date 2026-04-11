from __future__ import annotations

import re

from src.models.enums import PageType
from src.models.schema import OCRPageResult


class PageClassifier:
    """Classifies PDF pages by their functional role."""

    SIGNATURE_KEYWORDS = [
        "签字", "盖章", "授权代表", "authorized", "signature",
        "甲方代表", "乙方代表", "签署", "Authorized Signature",
        "legal representative", "法定代表人",
    ]

    AMOUNT_KEYWORDS = [
        "总价", "合计", "金额", "含税", "不含税", "年度维护费",
        "维护费", "合同总金额", "报价金额", "服务费",
    ]

    TABLE_KEYWORDS = [
        "序号", "名称", "型号", "数量", "单价", "单位",
        "product", "quantity", "unit price",
    ]

    TITLE_KEYWORDS = [
        "合同", "协议", "agreement", "contract", "服务合同",
        "维护合同", "采购合同", "技术服务合同", "报价单", "purchase order",
    ]

    ACCEPTANCE_KEYWORDS = [
        "验收", "acceptance", "交付", "交接", "项目完成",
    ]

    APPENDIX_KEYWORDS = [
        "附件", "appendix", "attachment", "附录", "补充协议",
    ]

    def classify_page(self, text: str, page_no: int, total_pages: int) -> PageType:
        """Classify a single page based on its text content."""
        text_lower = text.lower()

        def has_any(keywords: list[str]) -> bool:
            for kw in keywords:
                if kw.lower() in text_lower:
                    return True
            return False

        # Title pages are typically early pages with contract type keywords and short text
        if page_no == 0 and has_any(self.TITLE_KEYWORDS):
            return PageType.TITLE_PAGE

        if has_any(self.SIGNATURE_KEYWORDS):
            return PageType.SIGNATURE_PAGE

        if has_any(self.ACCEPTANCE_KEYWORDS):
            return PageType.ACCEPTANCE_PAGE

        if has_any(self.APPENDIX_KEYWORDS) and page_no > 0:
            return PageType.APPENDIX_PAGE

        if has_any(self.AMOUNT_KEYWORDS):
            return PageType.AMOUNT_PAGE

        # Table page: has grid-like structure with sequence numbers and unit prices
        if has_any(self.TABLE_KEYWORDS):
            return PageType.TABLE_PAGE

        if page_no == 0 and has_any(self.TITLE_KEYWORDS):
            return PageType.TITLE_PAGE

        # Terms pages: long text without special markers
        word_count = len(text.split())
        if word_count > 100:
            return PageType.TERMS_PAGE

        return PageType.UNKNOWN

    def classify_all(self, ocr_results: list[OCRPageResult]) -> dict[int, PageType]:
        """Classify all pages in a document."""
        total_pages = len(ocr_results)
        classifications: dict[int, PageType] = {}

        for result in ocr_results:
            page_type = self.classify_page(result.raw_text, result.page_no, total_pages)
            classifications[result.page_no] = page_type

        return classifications
