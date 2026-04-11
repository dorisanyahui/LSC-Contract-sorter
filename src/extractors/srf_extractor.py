from __future__ import annotations

import re

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult
from src.utils.amount_utils import normalize_amount
from src.utils.date_utils import parse_date


class SRFExtractor(BaseExtractor):
    """Extracts fields from Service Request Forms (SRF)."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract SRF-specific fields."""
        fields: dict[str, FieldEvidence] = {}
        all_text = self._get_all_text(ocr_results)

        # --- Client (vendor-filtered) ---
        company_candidates = candidates.get("company", [])
        client_ev = self._extract_client(company_candidates, all_text)
        if client_ev:
            fields["detected_company"] = client_ev

        # --- SRF number ---
        srf_no_ev = self._extract_srf_number(all_text, filename)
        if srf_no_ev:
            fields["srf_number"] = srf_no_ev

        # --- Sign date: prefer last compact date in filename ---
        date_candidates = candidates.get("date", [])
        sign_ev = self._extract_sign_date(date_candidates, filename)
        if sign_ev:
            fields["sign_date"] = sign_ev

        # --- Service period ---
        start_ev, end_ev = self._extract_service_period(all_text, date_candidates)
        if start_ev:
            fields["service_period_start"] = start_ev
        if end_ev:
            fields["service_period_end"] = end_ev

        # --- Fee ---
        amount_candidates = candidates.get("amount", [])
        fee_ev = self._extract_fee(amount_candidates, all_text)
        if fee_ev:
            fields["annual_maintenance_fee"] = fee_ev

        # --- Tax rate ---
        tax_candidates = candidates.get("tax_rate", [])
        tax_ev = self._pick_best(tax_candidates, "tax_rate")
        if tax_ev:
            fields["tax_rate"] = tax_ev

        # --- Software version ---
        ver_ev = self._extract_software_version(all_text, filename)
        if ver_ev:
            fields["software_version"] = ver_ev

        return fields

    def _extract_client(
        self, company_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract client company name, excluding our own vendor names."""
        from src.config import get_settings
        try:
            vendor_names = get_settings().vendor_names
        except Exception:
            vendor_names = []

        def is_vendor(name: str) -> bool:
            return any(v.lower() in name.lower() for v in vendor_names)

        # Look for "Client:" label context first
        for c in company_candidates:
            ev_lower = c.evidence_text.lower()
            name = c.normalized_value or c.value
            if any(kw in ev_lower for kw in ["客户", "client", "用户", "甲方"]) and not is_vendor(name):
                return self._make_evidence(
                    value=name, confidence=c.score, page=c.page,
                    evidence_text=c.evidence_text, source=c.source,
                )

        # Regex: "Client: <name>"
        m = re.search(
            r"(?:客户|客[户户]名称|Client)[：:\s]*([\u4e00-\u9fa5a-zA-Z0-9（）()]{4,40}(?:有限公司|集团|Ltd\.?|Limited|Corp\.?))",
            text,
        )
        if m:
            name = m.group(1).strip()
            if not is_vendor(name):
                return self._make_evidence(
                    value=name, confidence=0.75, page=None,
                    evidence_text=m.group(0), source=FieldSource.RULE,
                )

        # Fallback: first non-vendor company candidate
        for c in sorted(company_candidates, key=lambda c: c.score, reverse=True):
            name = c.normalized_value or c.value
            if not is_vendor(name) and len(name) >= 4:
                return self._make_evidence(
                    value=name, confidence=c.score * 0.6, page=c.page,
                    evidence_text=c.evidence_text, source=c.source,
                )

        return None

    def _extract_sign_date(
        self, date_candidates: list[Candidate], filename: str
    ) -> FieldEvidence | None:
        """Extract sign date: prefer last compact date in filename."""
        fn_dates = re.findall(r"(20\d{2})(\d{2})(\d{2})", filename)
        if fn_dates:
            y, mo, d = fn_dates[-1]
            return self._make_evidence(
                value=f"{y}-{mo}-{d}", confidence=0.55, page=None,
                evidence_text=f"From filename: {filename}", source=FieldSource.RULE,
            )

        sign_candidates = [c for c in date_candidates if c.label == "sign_date"]
        if sign_candidates:
            best = max(sign_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value, confidence=best.score,
                page=best.page, evidence_text=best.evidence_text, source=best.source,
            )

        return None

    def _extract_service_period(
        self, text: str, date_candidates: list[Candidate]
    ) -> tuple[FieldEvidence | None, FieldEvidence | None]:
        """Extract service period from SRF (reuses contract period patterns)."""
        start_ev: FieldEvidence | None = None
        end_ev: FieldEvidence | None = None

        # Chinese numeric range
        period_pattern = re.compile(
            r"(?:维护|服务|合同)?期(?:间|限|限为)?\s*[：:from]?\s*"
            r"(\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?)"
            r"\s*(?:至|到|~|—|-)\s*"
            r"(\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?)"
        )
        m = period_pattern.search(text)
        if m:
            ps = parse_date(m.group(1))
            pe = parse_date(m.group(2))
            if ps:
                start_ev = self._make_evidence(
                    value=ps.isoformat(), confidence=0.7, page=None,
                    evidence_text=m.group(0), source=FieldSource.RULE,
                )
            if pe:
                end_ev = self._make_evidence(
                    value=pe.isoformat(), confidence=0.7, page=None,
                    evidence_text=m.group(0), source=FieldSource.RULE,
                )

        # English range: "from Dec. 26, 2012 to Dec. 25, 2017"
        if not start_ev or not end_ev:
            eng = re.compile(
                r"(?:take\s+effect\s+from|from|period\s+(?:of|is))\s+"
                r"([A-Za-z]+\.?\s*\d{1,2},?\s*\d{4})"
                r"\s+to\s+"
                r"([A-Za-z]+\.?\s*\d{1,2},?\s*\d{4})",
                re.IGNORECASE,
            )
            me = eng.search(text)
            if me:
                if not start_ev:
                    ps = parse_date(me.group(1).replace(".", ""))
                    if ps:
                        start_ev = self._make_evidence(
                            value=ps.isoformat(), confidence=0.7, page=None,
                            evidence_text=me.group(0), source=FieldSource.RULE,
                        )
                if not end_ev:
                    pe = parse_date(me.group(2).replace(".", ""))
                    if pe:
                        end_ev = self._make_evidence(
                            value=pe.isoformat(), confidence=0.7, page=None,
                            evidence_text=me.group(0), source=FieldSource.RULE,
                        )

        return start_ev, end_ev

    def _extract_srf_number(self, text: str, filename: str) -> FieldEvidence | None:
        """Extract SRF reference number."""
        patterns = [
            re.compile(r"SRF[-\s]*(?:No|Number|编号)?[.：:\s]*([A-Za-z0-9\-_/]{4,30})", re.IGNORECASE),
            re.compile(r"服务需求表?(?:编号|号)[：:\s]*([A-Za-z0-9\-_/]{4,30})"),
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

        m = re.search(r"SRF[-_]?(\w{4,20})", filename, re.IGNORECASE)
        if m:
            return self._make_evidence(
                value=m.group(1),
                confidence=0.5,
                page=None,
                evidence_text=f"From filename: {filename}",
                source=FieldSource.RULE,
            )

        return None

    def _extract_service_date(
        self, date_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract service date."""
        if date_candidates:
            best = max(date_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )
        return None

    def _extract_fee(
        self, amount_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract service fee."""
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

        # Chinese pattern
        m = re.search(
            r"(?:年度?(?:注册)?维护费(?:用)?|年度?(?:注册)?服务费(?:用)?|维护费(?:用)?|服务费(?:用)?|费用)"
            r"[^￥¥\d\n]{0,15}(?:[¥￥]|人民币)?\s*([\d,，.]+)\s*(?:元|人民币|CNY)?",
            text,
        )
        if m:
            value = normalize_amount(m.group(1))
            if value and value >= 500:
                return self._make_evidence(
                    value=str(value), confidence=0.65, page=None,
                    evidence_text=m.group(0), source=FieldSource.RULE,
                )

        # English fee patterns — ordered by confidence
        eng_patterns = [
            re.compile(
                r"annual\s+(?:software\s+)?maintenance\s+fee[^¥\d\n]{0,40}(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
            re.compile(
                r"annual\s+(?:software\s+)?service\s+fee[^¥\d\n]{0,40}(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
            re.compile(
                r"annual\s+(?:software\s+)?(?:maintenance\s+)?charge[^¥\d\n]{0,50}(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:maintenance|service)\s+fee\s+(?:of\s+|is\s+|:\s*)(?:RMB|USD|CNY|EUR)?\s*([\d,]+(?:[.,]\d+)?)",
                re.IGNORECASE,
            ),
            # Standalone "RMB X" as last resort (SRF header amount)
            re.compile(
                r"(?:RMB|CNY)\s*([\d,]+(?:[.,]\d+)?)\s*(?:元|yuan)?",
                re.IGNORECASE,
            ),
        ]
        for eng_pat in eng_patterns:
            m = eng_pat.search(text)
            if m:
                value = normalize_amount(m.group(1))
                if value and value >= 500:
                    return self._make_evidence(
                        value=str(value), confidence=0.65, page=None,
                        evidence_text=m.group(0), source=FieldSource.RULE,
                    )

        return None
