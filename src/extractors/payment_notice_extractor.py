from __future__ import annotations

import re

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult
from src.utils.amount_utils import normalize_amount
from src.utils.date_utils import parse_date


class PaymentNoticeExtractor(BaseExtractor):
    """Extracts fields from payment notices."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract payment notice fields."""
        fields: dict[str, FieldEvidence] = {}
        all_text = self._get_all_text(ocr_results)

        # --- Client ---
        company_candidates = candidates.get("company", [])
        client_ev = self._extract_client(company_candidates, all_text)
        if client_ev:
            fields["detected_company"] = client_ev

        # --- Notice date ---
        date_candidates = candidates.get("date", [])
        notice_date_ev = self._extract_notice_date(date_candidates, all_text, filename)
        if notice_date_ev:
            fields["sign_date"] = notice_date_ev

        # --- Payment amount ---
        amount_candidates = candidates.get("amount", [])
        payment_ev = self._extract_payment_amount(amount_candidates, all_text)
        if payment_ev:
            fields["contract_total_amount"] = payment_ev

        # --- Currency ---
        currency_ev = self._extract_currency(all_text)
        if currency_ev:
            fields["currency"] = currency_ev

        return fields

    def _extract_client(
        self, company_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract client/recipient company name."""
        for c in company_candidates:
            ev_lower = c.evidence_text.lower()
            if any(kw in ev_lower for kw in ["致", "客户", "甲方", "dear", "to"]):
                return self._make_evidence(
                    value=c.normalized_value or c.value,
                    confidence=c.score,
                    page=c.page,
                    evidence_text=c.evidence_text,
                    source=c.source,
                )

        m = re.search(
            r"(?:致|客户|甲方)[：:\s]*([\u4e00-\u9fa5a-zA-Z0-9（）()]{4,40}(?:有限公司|集团))",
            text,
        )
        if m:
            return self._make_evidence(
                value=m.group(1).strip(),
                confidence=0.6,
                page=None,
                evidence_text=m.group(0),
                source=FieldSource.RULE,
            )

        if company_candidates:
            best = max(company_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score * 0.6,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        return None

    def _extract_notice_date(
        self,
        date_candidates: list[Candidate],
        text: str,
        filename: str,
    ) -> FieldEvidence | None:
        """Extract notice date."""
        if date_candidates:
            best = max(date_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        m = re.search(r"(20\d{2})[-._]?(\d{2})[-._]?(\d{2})", filename)
        if m:
            return self._make_evidence(
                value=f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                confidence=0.4,
                page=None,
                evidence_text=filename,
                source=FieldSource.RULE,
            )

        return None

    def _extract_payment_amount(
        self, amount_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract payment amount."""
        for label in ("contract_total_amount", "tax_included_amount", "amount_generic"):
            labeled = [c for c in amount_candidates if c.label == label]
            if labeled:
                best = max(labeled, key=lambda c: c.score)
                return self._make_evidence(
                    value=best.normalized_value or best.value,
                    confidence=best.score,
                    page=best.page,
                    evidence_text=best.evidence_text,
                    source=best.source,
                )

        # Fallback regex
        m = re.search(r"(?:应付|付款|金额)[：:\s]*[¥￥]?([\d,，.]+)\s*(?:元|人民币)?", text)
        if m:
            value = normalize_amount(m.group(1))
            if value:
                return self._make_evidence(
                    value=str(value),
                    confidence=0.6,
                    page=None,
                    evidence_text=m.group(0),
                    source=FieldSource.RULE,
                )

        return None

    def _extract_currency(self, text: str) -> FieldEvidence | None:
        """Detect currency."""
        if re.search(r"USD|美元|\$", text):
            return self._make_evidence("USD", 0.9, None, "", FieldSource.RULE)
        if re.search(r"EUR|欧元|€", text):
            return self._make_evidence("EUR", 0.9, None, "", FieldSource.RULE)
        return None
