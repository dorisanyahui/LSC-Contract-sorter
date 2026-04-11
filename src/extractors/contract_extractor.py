from __future__ import annotations

import re

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult
from src.utils.amount_utils import normalize_amount
from src.utils.date_utils import extract_date_candidates, parse_date


class ContractExtractor(BaseExtractor):
    """Extracts fields from service/maintenance contracts."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract contract-specific fields."""
        fields: dict[str, FieldEvidence] = {}

        all_text = self._get_all_text(ocr_results)
        sig_text = self._get_text_for_page_types(
            ocr_results, page_types, [PageType.SIGNATURE_PAGE]
        )
        amount_text = self._get_text_for_page_types(
            ocr_results, page_types, [PageType.AMOUNT_PAGE, PageType.TABLE_PAGE]
        )
        title_text = self._get_text_for_page_types(
            ocr_results, page_types, [PageType.TITLE_PAGE]
        )

        # --- Company (甲方 / detected_company) ---
        company_candidates = candidates.get("company", [])
        company_ev = self._extract_counterparty(company_candidates, all_text)
        if company_ev:
            fields["detected_company"] = company_ev

        # --- Sign date ---
        date_candidates = candidates.get("date", [])
        sign_ev = self._extract_sign_date(date_candidates, sig_text or all_text, filename)
        if sign_ev:
            fields["sign_date"] = sign_ev

        # --- Service period ---
        service_start, service_end = self._extract_service_period(all_text, date_candidates)
        if service_start:
            fields["service_period_start"] = service_start
        if service_end:
            fields["service_period_end"] = service_end

        # --- Annual maintenance fee ---
        amount_candidates = candidates.get("amount", [])
        # Pass both amount_text and all_text so regex fallbacks can search everywhere
        fee_ev = self._extract_maintenance_fee(amount_candidates, amount_text or all_text, all_text)
        if fee_ev:
            fields["annual_maintenance_fee"] = fee_ev

        # --- Tax rate ---
        tax_candidates = candidates.get("tax_rate", [])
        tax_ev = self._pick_best(tax_candidates, "tax_rate")
        if tax_ev:
            fields["tax_rate"] = tax_ev

        # --- Tax-included amount ---
        tax_inc = self._extract_labeled_amount(amount_candidates, ["tax_included_amount"])
        if tax_inc:
            fields["tax_included_amount"] = tax_inc

        # --- Tax-excluded amount ---
        tax_exc = self._extract_labeled_amount(amount_candidates, ["tax_excluded_amount"])
        if tax_exc:
            fields["tax_excluded_amount"] = tax_exc

        # --- Contract total ---
        total = self._extract_labeled_amount(
            amount_candidates, ["contract_total_amount"]
        )
        if total:
            fields["contract_total_amount"] = total

        # --- Contract number ---
        contract_no = self._extract_contract_number(all_text, title_text)
        if contract_no:
            fields["contract_number"] = contract_no

        # --- Software version ---
        version_ev = self._extract_software_version(all_text, filename)
        if version_ev:
            fields["software_version"] = version_ev

        # --- Doc type from filename ---
        doc_type_ev = self._extract_doc_type_from_filename(filename)
        if doc_type_ev:
            fields["doc_type_hint"] = doc_type_ev

        return fields

    def _extract_counterparty(
        self,
        company_candidates: list[Candidate],
        text: str,
    ) -> FieldEvidence | None:
        """Extract the client (甲方) company name, excluding our own vendor names."""
        from src.config import get_settings
        try:
            vendor_names = get_settings().vendor_names
        except Exception:
            vendor_names = []

        def is_vendor(name: str) -> bool:
            name_l = name.lower()
            return any(v.lower() in name_l for v in vendor_names)

        # 1. Regex first: "甲方：<company>" is highly reliable
        m = re.search(
            r"甲\s*方[：:]\s*([\u4e00-\u9fa5a-zA-Z0-9（）()]{4,40}(?:有限公司|集团|股份有限公司|有限责任公司))",
            text,
        )
        if m:
            name = m.group(1).strip()
            if not is_vendor(name):
                return self._make_evidence(
                    value=name, confidence=0.85,
                    page=None, evidence_text=m.group(0), source=FieldSource.RULE,
                )

        # 2. Candidates labeled near 甲方/client
        jia_fang_candidates = [
            c for c in company_candidates
            if ("甲方" in c.evidence_text or "client" in c.evidence_text.lower()
                or "buyer" in c.evidence_text.lower())
            and not is_vendor(c.normalized_value or c.value)
        ]

        # 3. Fall back to all non-vendor candidates
        non_vendor = [
            c for c in company_candidates
            if not is_vendor(c.normalized_value or c.value)
        ]

        pool = jia_fang_candidates if jia_fang_candidates else non_vendor
        if pool:
            best = max(pool, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
                candidates=pool,
            )

        return None

    def _extract_sign_date(
        self,
        date_candidates: list[Candidate],
        text: str,
        filename: str,
    ) -> FieldEvidence | None:
        """Extract signature date, prioritizing signature page dates."""
        sign_candidates = [c for c in date_candidates if c.label == "sign_date"]
        if sign_candidates:
            best = max(sign_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        # Filename date: prefer last occurrence (sign date is usually at end of filename)
        # Try compact form first (e.g. "20110217"), then dotted/hyphenated (e.g. "2015.11.11")
        fn_dates = re.findall(r"(20\d{2})(\d{2})(\d{2})", filename)
        fn_dates_sep = re.findall(r"(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})(?=[^0-9]|$)", filename)
        all_fn_dates = fn_dates + fn_dates_sep
        if all_fn_dates:
            y, mo, d = all_fn_dates[-1]  # last date = sign date
            date_str = f"{int(y)}-{int(mo):02d}-{int(d):02d}"
            return self._make_evidence(
                value=date_str,
                confidence=0.65,
                page=None,
                evidence_text=f"From filename: {filename}",
                source=FieldSource.RULE,
            )

        # Fallback: any date candidate (low confidence since context is unclear)
        if date_candidates:
            best = max(date_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score * 0.5,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        return None

    def _extract_service_period(
        self,
        text: str,
        date_candidates: list[Candidate],
    ) -> tuple[FieldEvidence | None, FieldEvidence | None]:
        """Extract service period start and end dates."""
        start_candidates = [c for c in date_candidates if c.label == "service_period_start"]
        end_candidates = [c for c in date_candidates if c.label == "service_period_end"]

        start_ev: FieldEvidence | None = None
        end_ev: FieldEvidence | None = None

        if start_candidates:
            best = max(start_candidates, key=lambda c: c.score)
            start_ev = self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        if end_candidates:
            best = max(end_candidates, key=lambda c: c.score)
            end_ev = self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        # Try to extract from "维护期间/合同有效期限 YYYY-MM-DD 至 YYYY-MM-DD" pattern
        if not start_ev or not end_ev:
            period_pattern = re.compile(
                r"(?:维护|服务|合同)?期(?:间|限|限为)?\s*[：:from]?\s*"
                r"(\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?)"
                r"\s*(?:至|到|~|—|-)\s*"
                r"(\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?)"
            )
            m = period_pattern.search(text)
            if m:
                if not start_ev:
                    parsed = parse_date(m.group(1))
                    start_ev = self._make_evidence(
                        value=parsed.isoformat() if parsed else m.group(1),
                        confidence=0.7,
                        page=None,
                        evidence_text=m.group(0),
                        source=FieldSource.RULE,
                    )
                if not end_ev:
                    parsed = parse_date(m.group(2))
                    end_ev = self._make_evidence(
                        value=parsed.isoformat() if parsed else m.group(2),
                        confidence=0.7,
                        page=None,
                        evidence_text=m.group(0),
                        source=FieldSource.RULE,
                    )

        # English pattern: "take effect from March. 01, 2011 to February.28, 2012"
        if not start_ev or not end_ev:
            from src.utils.date_utils import parse_date as _pd
            eng_pattern = re.compile(
                r"(?:take\s+effect\s+from|from|effective)\s+"
                r"([A-Za-z]+\.?\s*\d{1,2},?\s*\d{4})"
                r"\s+to\s+"
                r"([A-Za-z]+\.?\s*\d{1,2},?\s*\d{4})",
                re.IGNORECASE,
            )
            me = eng_pattern.search(text)
            if me:
                if not start_ev:
                    ps = _pd(me.group(1).replace(".", ""))
                    if ps:
                        start_ev = self._make_evidence(
                            value=ps.isoformat(), confidence=0.7,
                            page=None, evidence_text=me.group(0), source=FieldSource.RULE,
                        )
                if not end_ev:
                    pe = _pd(me.group(2).replace(".", ""))
                    if pe:
                        end_ev = self._make_evidence(
                            value=pe.isoformat(), confidence=0.7,
                            page=None, evidence_text=me.group(0), source=FieldSource.RULE,
                        )

        return start_ev, end_ev

    def _extract_maintenance_fee(
        self,
        amount_candidates: list[Candidate],
        text: str,
        full_text: str = "",
    ) -> FieldEvidence | None:
        """Extract annual maintenance fee."""
        # Try labeled candidates in priority order
        for label in ("annual_maintenance_fee", "maintenance_fee"):
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

        # Regex fallback: handles "年维护费", "年度维护费用", "维护费用", "年服务费" variants
        pattern = re.compile(
            r"(?:年度?(?:注册)?维护费(?:用)?|年度?(?:注册)?服务费(?:用)?|维护费(?:用)?)"
            r"[^￥¥\d\n]{0,15}(?:[¥￥]|人民币)?\s*([\d,，.]+)\s*(?:元|人民币|CNY)?",
        )
        m = pattern.search(text)
        if m:
            value = normalize_amount(m.group(1))
            if value:
                return self._make_evidence(
                    value=str(value),
                    confidence=0.65,
                    page=None,
                    evidence_text=m.group(0),
                    source=FieldSource.RULE,
                )

        # Broader pattern: "费用为人民币X元" or "费用…X元"
        pattern2 = re.compile(
            r"费用[为是]?[^￥¥\d\n]{0,10}(?:[¥￥]|人民币)?\s*([\d,，.]+)\s*(?:元|人民币|CNY)?",
        )
        m = pattern2.search(text)
        if m:
            value = normalize_amount(m.group(1))
            if value and value >= 500:
                return self._make_evidence(
                    value=str(value),
                    confidence=0.55,
                    page=None,
                    evidence_text=m.group(0),
                    source=FieldSource.RULE,
                )

        # English fee patterns — ordered by confidence
        eng_patterns = [
            # "annual (software) maintenance fee (of|is|for...) RMB X"
            re.compile(
                r"annual\s+(?:software\s+)?maintenance\s+fee[^¥\d\n]{0,40}(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
            # "annual service fee ... RMB X"
            re.compile(
                r"annual\s+(?:software\s+)?service\s+fee[^¥\d\n]{0,40}(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
            # "annual charge of ... RMB X"
            re.compile(
                r"annual\s+(?:software\s+)?(?:maintenance\s+)?charge[^¥\d\n]{0,50}(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
            # "(maintenance|service) fee is RMB X" (without annual)
            re.compile(
                r"(?:maintenance|service)\s+fee\s+(?:of\s+|is\s+|:\s*)(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
        ]
        search_texts = [t for t in [text, full_text if full_text else None] if t]
        for eng_pat in eng_patterns:
            for search_text in search_texts:
                m = eng_pat.search(search_text)
                if m:
                    value = normalize_amount(m.group(1))
                    if value and value >= 100:
                        return self._make_evidence(
                            value=str(value),
                            confidence=0.75,
                            page=None,
                            evidence_text=m.group(0),
                            source=FieldSource.RULE,
                        )

        return None

    def _extract_labeled_amount(
        self,
        amount_candidates: list[Candidate],
        labels: list[str],
    ) -> FieldEvidence | None:
        """Extract amount with one of the given labels, passing all candidates for fallback."""
        for label in labels:
            labeled = sorted(
                [c for c in amount_candidates if c.label == label],
                # Primary: higher score first; secondary: larger value first (breaks ties
                # so total > unit price when both score equally, e.g. PO tables)
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
        return None

    def _extract_contract_number(self, all_text: str, title_text: str) -> FieldEvidence | None:
        """Extract contract number."""
        pattern = re.compile(
            r"合同(?:编号|号)[：:\s]*([A-Za-z0-9\-_/\\（）()]{4,30})"
        )
        for text in [title_text, all_text]:
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

    def _extract_doc_type_from_filename(self, filename: str) -> FieldEvidence | None:
        """Extract document type hint from filename."""
        fn_lower = filename.lower()
        type_hints = {
            "维护合同": ["维护合同", "维保合同"],
            "服务合同": ["服务合同"],
            "采购合同": ["采购合同"],
            "项目合同": ["项目合同"],
            "报价单": ["报价单", "报价"],
            "SRF": ["srf"],
        }
        for label, keywords in type_hints.items():
            for kw in keywords:
                if kw.lower() in fn_lower:
                    return self._make_evidence(
                        value=label,
                        confidence=0.9,
                        page=None,
                        evidence_text=f"From filename: {filename}",
                        source=FieldSource.RULE,
                    )
        return None

    # _extract_software_version is inherited from BaseExtractor
