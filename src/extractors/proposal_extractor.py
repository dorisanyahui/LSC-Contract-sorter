from __future__ import annotations

import re

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult
from src.utils.date_utils import parse_date


class ProposalExtractor(BaseExtractor):
    """Extracts fields from project proposals."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract proposal-specific fields."""
        fields: dict[str, FieldEvidence] = {}
        all_text = self._get_all_text(ocr_results)

        # --- Client ---
        company_candidates = candidates.get("company", [])
        client_ev = self._extract_client(company_candidates, all_text)
        if client_ev:
            fields["detected_company"] = client_ev

        # --- Proposal date ---
        date_candidates = candidates.get("date", [])
        proposal_date_ev = self._extract_proposal_date(date_candidates, all_text, filename)
        if proposal_date_ev:
            fields["sign_date"] = proposal_date_ev

        # --- Project name ---
        project_ev = self._extract_project_name(all_text)
        if project_ev:
            fields["project_name"] = project_ev

        # --- Quote info ---
        amount_candidates = candidates.get("amount", [])
        quote_ev = self._extract_quote_info(amount_candidates, all_text)
        if quote_ev:
            fields["contract_total_amount"] = quote_ev

        # --- Acceptance date ---
        acceptance_ev = self._extract_acceptance_date(date_candidates, all_text)
        if acceptance_ev:
            fields["effective_date"] = acceptance_ev

        return fields

    def _extract_client(
        self, company_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract the client company from proposal."""
        for c in company_candidates:
            ev_lower = c.evidence_text.lower()
            if any(kw in ev_lower for kw in ["客户", "甲方", "致", "client"]):
                return self._make_evidence(
                    value=c.normalized_value or c.value,
                    confidence=c.score,
                    page=c.page,
                    evidence_text=c.evidence_text,
                    source=c.source,
                )

        m = re.search(
            r"(?:致|客户|甲方|尊敬的)[：:\s]*([\u4e00-\u9fa5a-zA-Z0-9（）()]{4,40}(?:有限公司|集团))",
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

    def _extract_proposal_date(
        self,
        date_candidates: list[Candidate],
        text: str,
        filename: str,
    ) -> FieldEvidence | None:
        """Extract proposal creation date."""
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

    def _extract_project_name(self, text: str) -> FieldEvidence | None:
        """Extract project name."""
        patterns = [
            re.compile(r"项目名称[：:\s]*([\u4e00-\u9fa5a-zA-Z0-9\s]{4,80})"),
            re.compile(r"关于([\u4e00-\u9fa5a-zA-Z0-9\s]{4,60})项目"),
        ]
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                return self._make_evidence(
                    value=m.group(1).strip(),
                    confidence=0.7,
                    page=None,
                    evidence_text=m.group(0),
                    source=FieldSource.RULE,
                )
        return None

    def _extract_quote_info(
        self, amount_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract quoted price information."""
        if amount_candidates:
            best = max(amount_candidates, key=lambda c: c.score)
            return self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )
        return None

    def _extract_acceptance_date(
        self, date_candidates: list[Candidate], text: str
    ) -> FieldEvidence | None:
        """Extract project acceptance date."""
        labeled = [c for c in date_candidates if c.label in ("service_period_end", "date_generic")]
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
            r"(?:验收|交付)[日期]?[：:\s]*(\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?)",
            text,
        )
        if m:
            parsed = parse_date(m.group(1))
            return self._make_evidence(
                value=parsed.isoformat() if parsed else m.group(1),
                confidence=0.6,
                page=None,
                evidence_text=m.group(0),
                source=FieldSource.RULE,
            )

        return None
