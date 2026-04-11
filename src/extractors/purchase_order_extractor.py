from __future__ import annotations

import re

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult
from src.utils.amount_utils import normalize_amount
from src.utils.date_utils import parse_date


class PurchaseOrderExtractor(BaseExtractor):
    """Extracts fields from purchase orders."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract purchase order specific fields."""
        fields: dict[str, FieldEvidence] = {}
        all_text = self._get_all_text(ocr_results)

        # --- Buyer ---
        company_candidates = candidates.get("company", [])
        buyer_ev = self._extract_role_company(company_candidates, all_text, "buyer")
        if buyer_ev:
            fields["detected_company"] = buyer_ev

        # --- Vendor ---
        vendor_ev = self._extract_role_company(company_candidates, all_text, "seller")
        if vendor_ev:
            fields["detected_counterparty"] = vendor_ev

        # --- PO Number ---
        po_ev = self._extract_po_number(all_text, filename)
        if po_ev:
            fields["po_number"] = po_ev

        # --- Issue date ---
        date_candidates = candidates.get("date", [])
        issue_ev = self._extract_issue_date(date_candidates, all_text)
        if issue_ev:
            fields["sign_date"] = issue_ev

        # --- Delivery date ---
        delivery_ev = self._extract_delivery_date(date_candidates, all_text)
        if delivery_ev:
            fields["service_period_end"] = delivery_ev

        # --- Currency ---
        currency_ev = self._extract_currency(all_text)
        if currency_ev:
            fields["currency"] = currency_ev

        # --- Total price ---
        amount_candidates = candidates.get("amount", [])
        total_ev = self._extract_total_amount(amount_candidates, all_text)
        if total_ev:
            fields["contract_total_amount"] = total_ev

        # --- Line items summary ---
        summary_ev = self._extract_line_items_summary(all_text)
        if summary_ev:
            fields["line_items_summary"] = summary_ev

        return fields

    def _extract_role_company(
        self,
        company_candidates: list[Candidate],
        text: str,
        role: str,
    ) -> FieldEvidence | None:
        """Extract buyer or seller company."""
        from src.config import get_settings
        from src.pipeline.normalizers import normalize_company_name

        if role == "buyer":
            keywords = ["买方", "采购方", "甲方", "buyer", "purchaser"]
        else:
            keywords = ["卖方", "供应商", "乙方", "seller", "vendor", "supplier"]

        for c in company_candidates:
            ev_lower = c.evidence_text.lower()
            if any(kw.lower() in ev_lower for kw in keywords):
                return self._make_evidence(
                    value=c.normalized_value or c.value,
                    confidence=c.score,
                    page=c.page,
                    evidence_text=c.evidence_text,
                    source=c.source,
                )

        # Regex fallback
        for kw in keywords:
            pattern = re.compile(
                rf"{re.escape(kw)}[：:\s]*([\u4e00-\u9fa5a-zA-Z0-9（）(){{}}]{4,40}(?:有限公司|集团|有限责任公司|股份有限公司))"
            )
            m = pattern.search(text)
            if m:
                return self._make_evidence(
                    value=m.group(1).strip(),
                    confidence=0.6,
                    page=None,
                    evidence_text=m.group(0),
                    source=FieldSource.RULE,
                )

        # For buyer role: fall back to first non-vendor company candidate
        # (English POs often don't have explicit "Buyer:" labels)
        if role == "buyer":
            try:
                settings = get_settings()
                vendor_names = settings.vendor_names
            except Exception:
                vendor_names = []

            for c in company_candidates:
                name = c.normalized_value or c.value
                name_lower = name.lower()
                is_vendor = any(v.lower() in name_lower for v in vendor_names)
                if not is_vendor and len(name) >= 4:
                    return self._make_evidence(
                        value=name,
                        confidence=0.5,
                        page=c.page,
                        evidence_text=c.evidence_text,
                        source=c.source,
                    )

        return None

    def _extract_po_number(self, text: str, filename: str) -> FieldEvidence | None:
        """Extract purchase order number."""
        patterns = [
            re.compile(r"(?:PO|采购订单|订单号|Purchase\s*Order)[：:\s#]*([A-Za-z0-9\-_/]{4,30})", re.IGNORECASE),
            re.compile(r"No[.：:\s]*([A-Za-z0-9\-_/]{4,30})", re.IGNORECASE),
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

        # Try from filename
        m = re.search(r"PO[-_]?(\w{4,20})", filename, re.IGNORECASE)
        if m:
            return self._make_evidence(
                value=m.group(1),
                confidence=0.5,
                page=None,
                evidence_text=f"From filename: {filename}",
                source=FieldSource.RULE,
            )

        return None

    def _extract_issue_date(
        self, date_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract PO issue/order date."""
        labeled = [
            c for c in date_candidates
            if c.label in ("sign_date", "date_generic", "effective_date")
        ]
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

    def _extract_delivery_date(
        self, date_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract expected delivery date."""
        labeled = [c for c in date_candidates if c.label == "service_period_end"]
        if labeled:
            best = max(labeled, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        m = re.search(
            r"(?:交货|交付|delivery)[期日]?[：:\s]*(\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?)",
            text,
            re.IGNORECASE,
        )
        if m:
            parsed = parse_date(m.group(1))
            return self._make_evidence(
                value=parsed.isoformat() if parsed else m.group(1),
                confidence=0.7,
                page=None,
                evidence_text=m.group(0),
                source=FieldSource.RULE,
            )

        return None

    def _extract_currency(self, text: str) -> FieldEvidence | None:
        """Extract currency from text. CNY/RMB takes priority over generic $ mentions."""
        # Check explicit CNY/RMB first (highest priority)
        if re.search(r"\bCNY\b|人民币|RMB|¥", text):
            return self._make_evidence(
                value="CNY", confidence=0.95, page=None, evidence_text="", source=FieldSource.RULE
            )
        # USD: require explicit "USD" or "美元"; bare "$" alone may be in T&C boilerplate
        if re.search(r"\bUSD\b|美元", text):
            return self._make_evidence(
                value="USD", confidence=0.9, page=None, evidence_text="", source=FieldSource.RULE
            )
        if re.search(r"EUR|欧元|€", text):
            return self._make_evidence(
                value="EUR", confidence=0.9, page=None, evidence_text="", source=FieldSource.RULE
            )
        return None

    def _extract_total_amount(
        self, amount_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract total order amount."""
        from src.utils.amount_utils import normalize_amount

        # First try labeled candidates — pass all so ingest can try next if top fails
        for label in ("contract_total_amount", "tax_included_amount"):
            labeled = sorted(
                [c for c in amount_candidates if c.label == label],
                key=lambda c: (-c.score, -float(c.normalized_value or c.value or 0)),
            )
            if labeled:
                best = labeled[0]
                return self._make_evidence(
                    value=best.normalized_value or best.value,
                    confidence=best.score,
                    page=best.page,
                    evidence_text=best.evidence_text,
                    source=best.source,
                    candidates=labeled,
                )

        # For generic amounts: look for "Total" context in text, pick the largest
        # plausible amount (avoids phone numbers, zip codes, etc.)
        total_pattern = re.compile(
            r"(?:total|合计|总价|总金额)[^\d\n]*?([\d,，]+(?:\.\d+)?)",
            re.IGNORECASE,
        )
        m = total_pattern.search(text)
        if m:
            val = normalize_amount(m.group(1))
            if val and val >= 100:
                return self._make_evidence(
                    value=str(val),
                    confidence=0.75,
                    page=None,
                    evidence_text=m.group(0),
                    source=FieldSource.RULE,
                )

        # Fallback: pick the most-repeated amount on page 0 in plausible range
        # (PO totals typically appear twice: in line items and grand total row)
        from collections import Counter
        generic = [c for c in amount_candidates if c.label == "amount_generic"]
        page0 = [c for c in generic if c.page == 0] or generic  # prefer page 0
        val_map: dict[float, list] = {}
        for c in page0:
            val = normalize_amount(c.value)
            if val is not None and 100 <= val <= 10_000_000:
                val_map.setdefault(val, []).append(c)

        if val_map:
            # Pick the value that appears most often (grand total is repeated)
            best_val = max(val_map, key=lambda v: len(val_map[v]))
            best = val_map[best_val][0]
            return self._make_evidence(
                value=str(best_val),
                confidence=0.5,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        return None

    def _extract_line_items_summary(self, text: str) -> FieldEvidence | None:
        """Generate a brief line items summary from table content."""
        # Count product lines
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        item_lines = [l for l in lines if re.match(r"^\d+[\.\s]", l)]
        if item_lines:
            summary = f"{len(item_lines)} line item(s): " + "; ".join(item_lines[:3])
            if len(item_lines) > 3:
                summary += f" ... (+{len(item_lines) - 3} more)"
            return self._make_evidence(
                value=summary[:300],
                confidence=0.5,
                page=None,
                evidence_text="",
                source=FieldSource.RULE,
            )
        return None
