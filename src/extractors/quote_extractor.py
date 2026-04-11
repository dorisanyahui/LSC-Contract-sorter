from __future__ import annotations

import re

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult
from src.utils.amount_utils import normalize_amount
from src.utils.date_utils import parse_date


class QuoteExtractor(BaseExtractor):
    """Extracts fields from quotations."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract quotation-specific fields."""
        fields: dict[str, FieldEvidence] = {}
        all_text = self._get_all_text(ocr_results)

        # --- Client ---
        company_candidates = candidates.get("company", [])
        client_ev = self._extract_client(company_candidates, all_text)
        if client_ev:
            fields["detected_company"] = client_ev

        # --- Quote date ---
        date_candidates = candidates.get("date", [])
        quote_date_ev = self._extract_quote_date(date_candidates, all_text, filename)
        if quote_date_ev:
            fields["sign_date"] = quote_date_ev

        # --- Currency ---
        currency_ev = self._extract_currency(all_text)
        if currency_ev:
            fields["currency"] = currency_ev

        # --- Tax rate ---
        tax_candidates = candidates.get("tax_rate", [])
        tax_ev = self._pick_best(tax_candidates, "tax_rate")
        if tax_ev:
            fields["tax_rate"] = tax_ev

        # --- Total amount ---
        amount_candidates = candidates.get("amount", [])
        total_ev = self._extract_total(amount_candidates, all_text)
        if total_ev:
            fields["contract_total_amount"] = total_ev

        # --- Maintenance fee ---
        fee_ev = self._extract_maintenance_fee(amount_candidates, all_text)
        if fee_ev:
            fields["annual_maintenance_fee"] = fee_ev

        # --- Validity period ---
        validity_ev = self._extract_validity_period(all_text)
        if validity_ev:
            fields["validity_period"] = validity_ev

        # --- Quote number ---
        quote_no_ev = self._extract_quote_number(all_text, filename)
        if quote_no_ev:
            fields["quote_number"] = quote_no_ev

        return fields

    def _extract_client(
        self, company_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract client name."""
        for c in company_candidates:
            ev_lower = c.evidence_text.lower()
            if any(kw in ev_lower for kw in ["客户", "甲方", "client", "to", "致"]):
                return self._make_evidence(
                    value=c.normalized_value or c.value,
                    confidence=c.score,
                    page=c.page,
                    evidence_text=c.evidence_text,
                    source=c.source,
                )

        m = re.search(r"(?:致|客户|甲方)[：:\s]*([\u4e00-\u9fa5a-zA-Z0-9（）()]{4,40}(?:有限公司|集团))", text)
        if m:
            return self._make_evidence(
                value=m.group(1).strip(),
                confidence=0.6,
                page=None,
                evidence_text=m.group(0),
                source=FieldSource.RULE,
            )

        # English: "Company: <Name>" label on quote header
        m = re.search(
            r"Company[（(公司）)]*[：:\s]+([A-Z][A-Za-z0-9 \-&',\.()]{4,60}"
            r"(?:Co\.,?\s*Ltd\.?|Ltd\.?|Corporation|Corp\.?|Inc\.?|Limited|GmbH|PLC|LLC))",
            text,
        )
        if m:
            from src.config import get_settings
            try:
                vendor_names = get_settings().vendor_names
            except Exception:
                vendor_names = []
            name = m.group(1).strip()
            if not any(v.lower() in name.lower() for v in vendor_names):
                return self._make_evidence(
                    value=name, confidence=0.7, page=None,
                    evidence_text=m.group(0), source=FieldSource.RULE,
                )

        if company_candidates:
            best = max(company_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score * 0.7,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        return None

    def _extract_quote_date(
        self,
        date_candidates: list[Candidate],
        text: str,
        filename: str,
    ) -> FieldEvidence | None:
        """Extract quotation date."""
        fn_m = re.search(r"(20\d{2})[-._]?(\d{2})[-._]?(\d{2})", filename)
        if date_candidates:
            best = max(date_candidates, key=lambda c: c.score)
            # If the filename has a year that is earlier than all OCR date candidates,
            # the OCR dates are likely service period dates (future), not issue dates.
            # Prefer the filename date in that case (it's the quote issue date).
            if fn_m:
                fn_year = int(fn_m.group(1))
                try:
                    best_year = int((best.normalized_value or best.value or "")[:4])
                except (ValueError, TypeError):
                    best_year = 9999
                if fn_year < best_year:
                    return self._make_evidence(
                        value=f"{fn_m.group(1)}-{fn_m.group(2)}-{fn_m.group(3)}",
                        confidence=0.65,
                        page=None,
                        evidence_text=filename,
                        source=FieldSource.RULE,
                    )
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )
        # Filename date fallback
        if fn_m:
            return self._make_evidence(
                value=f"{fn_m.group(1)}-{fn_m.group(2)}-{fn_m.group(3)}",
                confidence=0.4,
                page=None,
                evidence_text=filename,
                source=FieldSource.RULE,
            )
        return None

    def _extract_currency(self, text: str) -> FieldEvidence | None:
        """Detect currency type."""
        if re.search(r"USD|美元|\$", text):
            return self._make_evidence("USD", 0.9, None, "", FieldSource.RULE)
        if re.search(r"EUR|欧元|€", text):
            return self._make_evidence("EUR", 0.9, None, "", FieldSource.RULE)
        return None

    def _extract_total(
        self, amount_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract total quoted amount."""
        for label in ("tax_included_amount", "contract_total_amount", "amount_generic"):
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
        return None

    def _extract_maintenance_fee(
        self, amount_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract maintenance fee from quote."""
        # Check maintenance_fee first (explicit RMB statement, high confidence),
        # then annual_maintenance_fee (table row label, lower confidence)
        for label in ("maintenance_fee", "annual_maintenance_fee"):
            labeled = [c for c in amount_candidates if c.label == label]
            if labeled:
                best = max(labeled, key=lambda c: (c.score, float(c.normalized_value or c.value or 0)))
                return self._make_evidence(
                    value=best.normalized_value or best.value,
                    confidence=best.score,
                    page=best.page,
                    evidence_text=best.evidence_text,
                    source=best.source,
                )
        return None

    def _extract_validity_period(self, text: str) -> FieldEvidence | None:
        """Extract quote validity period."""
        m = re.search(r"有效期[：:\s]*(\d+)\s*(?:天|日|个月|月|年)", text)
        if m:
            return self._make_evidence(
                value=m.group(0).strip(),
                confidence=0.7,
                page=None,
                evidence_text=m.group(0),
                source=FieldSource.RULE,
            )
        return None

    def _extract_quote_number(self, text: str, filename: str) -> FieldEvidence | None:
        """Extract quotation number."""
        patterns = [
            re.compile(r"报价(?:单|书)?(?:编号|号)[：:\s]*([A-Za-z0-9\-_/]{4,30})", re.IGNORECASE),
            re.compile(r"Quote\s*(?:No|Number)[.：:\s]*([A-Za-z0-9\-_/]{4,30})", re.IGNORECASE),
        ]
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                return self._make_evidence(
                    value=m.group(1).strip(),
                    confidence=0.8,
                    page=None,
                    evidence_text=m.group(0),
                    source=FieldSource.RULE,
                )
        return None
