from __future__ import annotations

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult


class UnknownExtractor(BaseExtractor):
    """Best-effort extractor for documents of unknown type."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract whatever fields are findable."""
        fields: dict[str, FieldEvidence] = {}
        all_text = self._get_all_text(ocr_results)

        # Best-effort company extraction
        company_candidates = candidates.get("company", [])
        if company_candidates:
            best = max(company_candidates, key=lambda c: c.score)
            fields["detected_company"] = self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score * 0.5,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        # Best-effort date extraction
        date_candidates = candidates.get("date", [])
        if date_candidates:
            best = max(date_candidates, key=lambda c: c.score)
            fields["sign_date"] = self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score * 0.5,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        # Best-effort amount extraction
        amount_candidates = candidates.get("amount", [])
        if amount_candidates:
            best = max(amount_candidates, key=lambda c: c.score)
            fields["contract_total_amount"] = self._make_evidence(
                value=best.normalized_value or best.value,
                confidence=best.score * 0.4,
                page=best.page,
                evidence_text=best.evidence_text,
                source=best.source,
            )

        # Add a flag for unknown type
        fields["_flag_unknown_type"] = self._make_evidence(
            value="UNKNOWN_DOC_TYPE",
            confidence=1.0,
            page=None,
            evidence_text="Document type could not be determined",
            source=FieldSource.RULE,
        )

        return fields
