from __future__ import annotations

import re

from src.extractors.base import BaseExtractor
from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult


class AttachmentExtractor(BaseExtractor):
    """Extracts fields from attachment documents."""

    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract attachment-specific fields.

        Attachments are secondary documents, so is_primary_doc=False.
        """
        fields: dict[str, FieldEvidence] = {}
        all_text = self._get_all_text(ocr_results)

        # Mark as not primary doc
        fields["is_primary_doc"] = self._make_evidence(
            value="False",
            confidence=1.0,
            page=None,
            evidence_text="Classified as attachment",
            source=FieldSource.RULE,
        )

        # --- Attachment subtype ---
        subtype_ev = self._extract_attachment_subtype(all_text, filename)
        if subtype_ev:
            fields["attachment_subtype"] = subtype_ev

        # --- Related document number ---
        related_doc_ev = self._extract_related_doc_number(all_text, filename)
        if related_doc_ev:
            fields["related_doc_number"] = related_doc_ev

        # --- Company (best effort) ---
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

        return fields

    def _extract_attachment_subtype(self, text: str, filename: str) -> FieldEvidence | None:
        """Determine the type of attachment."""
        subtypes = {
            "技术规格": ["技术规格", "技术参数", "spec", "specification"],
            "价格清单": ["价格清单", "price list", "报价明细"],
            "人员简历": ["人员简历", "简历", "履历", "CV", "resume"],
            "资质证明": ["资质", "证书", "certification", "license"],
            "补充协议": ["补充协议", "supplement", "amendment"],
            "验收报告": ["验收报告", "acceptance report"],
            "技术方案": ["技术方案", "技术说明", "technical"],
        }

        text_lower = text.lower()[:2000]
        fn_lower = filename.lower()

        for subtype, keywords in subtypes.items():
            for kw in keywords:
                if kw.lower() in text_lower or kw.lower() in fn_lower:
                    return self._make_evidence(
                        value=subtype,
                        confidence=0.7,
                        page=None,
                        evidence_text=f"Detected keyword: {kw}",
                        source=FieldSource.RULE,
                    )

        return self._make_evidence(
            value="其他附件",
            confidence=0.4,
            page=None,
            evidence_text="No specific subtype detected",
            source=FieldSource.RULE,
        )

    def _extract_related_doc_number(self, text: str, filename: str) -> FieldEvidence | None:
        """Extract the reference number of the related primary document."""
        patterns = [
            re.compile(r"合同(?:编号|号)[：:\s]*([A-Za-z0-9\-_/]{4,30})"),
            re.compile(r"PO[-\s]*(?:No|Number)?[.：:\s]*([A-Za-z0-9\-_/]{4,30})", re.IGNORECASE),
            re.compile(r"附件.*?(?:合同|协议|PO)[：:\s]*([A-Za-z0-9\-_/]{4,30})", re.IGNORECASE),
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
