"""Tests for page classifier and document type detection."""
import pytest

from src.models.enums import PageType
from src.models.schema import OCRPageResult, OCRTextBlock
from src.pipeline.page_classifier import PageClassifier


def _make_ocr_result(page_no: int, text: str) -> OCRPageResult:
    """Helper to create a minimal OCRPageResult."""
    return OCRPageResult(
        page_no=page_no,
        width=1000,
        height=1400,
        text_blocks=[
            OCRTextBlock(text=text, bbox=[0, 0, 1000, 1400], confidence=0.9, page=page_no)
        ],
        raw_text=text,
        confidence_avg=0.9,
    )


class TestPageClassifier:
    """Tests for PageClassifier."""

    def setup_method(self):
        self.classifier = PageClassifier()

    def test_classify_title_page(self):
        """First page with contract keywords should be TITLE_PAGE."""
        text = "软件维护服务合同\n甲方：派克汉尼汾（中国）有限公司\n乙方：上海莱升信息科技有限公司"
        page_type = self.classifier.classify_page(text, page_no=0, total_pages=5)
        assert page_type == PageType.TITLE_PAGE

    def test_classify_signature_page(self):
        """Page with 签字/盖章 should be SIGNATURE_PAGE."""
        text = "甲方代表签字：___________\n乙方代表签字：___________\n日期：2021年3月15日\n盖章："
        page_type = self.classifier.classify_page(text, page_no=4, total_pages=5)
        assert page_type == PageType.SIGNATURE_PAGE

    def test_classify_amount_page(self):
        """Page with 总价/含税 should be AMOUNT_PAGE."""
        text = "年度维护费：33,750元\n含税金额：38,002.50元\n税率：13%"
        page_type = self.classifier.classify_page(text, page_no=2, total_pages=5)
        assert page_type == PageType.AMOUNT_PAGE

    def test_classify_terms_page(self):
        """Long text page without special markers should be TERMS_PAGE."""
        text = " ".join(["本合同条款如下"] * 120)  # ~120 words
        page_type = self.classifier.classify_page(text, page_no=1, total_pages=5)
        assert page_type == PageType.TERMS_PAGE

    def test_classify_acceptance_page(self):
        """Page with 验收 keyword should be ACCEPTANCE_PAGE."""
        text = "项目验收报告\n验收日期：2021年6月30日\n验收结果：合格"
        page_type = self.classifier.classify_page(text, page_no=3, total_pages=5)
        assert page_type == PageType.ACCEPTANCE_PAGE

    def test_classify_appendix_page(self):
        """Non-first page with 附件 should be APPENDIX_PAGE."""
        text = "附件一：价格明细表\n软件许可列表附录"
        page_type = self.classifier.classify_page(text, page_no=5, total_pages=8)
        assert page_type == PageType.APPENDIX_PAGE

    def test_classify_all_returns_dict(self):
        """classify_all should return dict keyed by page_no."""
        pages = [
            _make_ocr_result(0, "维护服务合同"),
            _make_ocr_result(1, "甲方代表签字 盖章"),
        ]
        result = self.classifier.classify_all(pages)
        assert isinstance(result, dict)
        assert 0 in result
        assert 1 in result

    def test_classify_all_signature_on_last_page(self):
        """Signature keywords should be detected on any page."""
        pages = [
            _make_ocr_result(0, "服务合同\n甲方：某公司"),
            _make_ocr_result(1, "第一条 服务内容\n本合同规定..."),
            _make_ocr_result(2, "甲方签字：____\n乙方盖章：____"),
        ]
        result = self.classifier.classify_all(pages)
        assert result[2] == PageType.SIGNATURE_PAGE


class TestDocTypeKeywordDetection:
    """Tests for document type keyword detection via normalizers."""

    def test_contract_keywords(self):
        from src.pipeline.normalizers import normalize_doc_type
        from src.models.enums import DocType

        assert normalize_doc_type("维护合同") == DocType.CONTRACT
        assert normalize_doc_type("服务协议") == DocType.CONTRACT
        assert normalize_doc_type("service agreement") == DocType.CONTRACT

    def test_purchase_order_keywords(self):
        from src.pipeline.normalizers import normalize_doc_type
        from src.models.enums import DocType

        assert normalize_doc_type("采购订单") == DocType.PURCHASE_ORDER
        assert normalize_doc_type("purchase order") == DocType.PURCHASE_ORDER
        assert normalize_doc_type("PO") == DocType.PURCHASE_ORDER

    def test_quote_keywords(self):
        from src.pipeline.normalizers import normalize_doc_type
        from src.models.enums import DocType

        assert normalize_doc_type("报价单") == DocType.QUOTE
        assert normalize_doc_type("quotation") == DocType.QUOTE

    def test_srf_keywords(self):
        from src.pipeline.normalizers import normalize_doc_type
        from src.models.enums import DocType

        assert normalize_doc_type("SRF") == DocType.SRF
        assert normalize_doc_type("服务需求表") == DocType.SRF

    def test_unknown(self):
        from src.pipeline.normalizers import normalize_doc_type
        from src.models.enums import DocType

        assert normalize_doc_type("") == DocType.UNKNOWN
        assert normalize_doc_type("随机文字") == DocType.UNKNOWN

    def test_attachment_keywords(self):
        from src.pipeline.normalizers import normalize_doc_type
        from src.models.enums import DocType

        assert normalize_doc_type("附件") == DocType.ATTACHMENT
        assert normalize_doc_type("attachment") == DocType.ATTACHMENT
