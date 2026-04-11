from __future__ import annotations

import re
from abc import ABC, abstractmethod

from src.models.enums import FieldSource, PageType
from src.models.schema import Candidate, FieldEvidence, OCRPageResult


class BaseExtractor(ABC):
    """Abstract base class for document field extractors."""

    @abstractmethod
    def extract(
        self,
        candidates: dict[str, list[Candidate]],
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        filename: str,
    ) -> dict[str, FieldEvidence]:
        """Extract fields from document candidates.

        Args:
            candidates: Dict of candidate lists keyed by field category.
            ocr_results: OCR results for each page.
            page_types: Classified page types.
            filename: Original filename for context.

        Returns:
            Dict mapping field names to FieldEvidence.
        """
        raise NotImplementedError

    def _pick_best(
        self,
        candidates: list[Candidate],
        field_name: str,
    ) -> FieldEvidence | None:
        """Pick the best candidate for a field based on score and label."""
        if not candidates:
            return None

        # Filter by label if possible
        labeled = [c for c in candidates if c.label == field_name]
        pool = labeled if labeled else candidates

        # Sort by score descending
        pool_sorted = sorted(pool, key=lambda c: c.score, reverse=True)

        if not pool_sorted:
            return None

        best = pool_sorted[0]
        return self._make_evidence(
            value=best.normalized_value or best.value,
            confidence=best.score,
            page=best.page,
            evidence_text=best.evidence_text,
            source=best.source,
            candidates=pool_sorted,
        )

    def _make_evidence(
        self,
        value: str,
        confidence: float,
        page: int | None,
        evidence_text: str,
        source: FieldSource,
        candidates: list[Candidate] | None = None,
    ) -> FieldEvidence:
        """Create a FieldEvidence instance."""
        return FieldEvidence(
            value=value,
            confidence=confidence,
            page=page,
            evidence_text=evidence_text,
            source=source,
            candidates=candidates or [],
        )

    def _get_text_for_page_types(
        self,
        ocr_results: list[OCRPageResult],
        page_types: dict[int, PageType],
        target_types: list[PageType],
    ) -> str:
        """Get combined text from pages matching target types."""
        texts: list[str] = []
        for result in ocr_results:
            if page_types.get(result.page_no) in target_types:
                texts.append(result.raw_text)
        return "\n".join(texts)

    def _get_all_text(self, ocr_results: list[OCRPageResult]) -> str:
        """Get all text from OCR results."""
        return "\n".join(r.raw_text for r in ocr_results)

    def _extract_software_version(self, text: str, filename: str) -> FieldEvidence | None:
        """Extract FormWare software version from contract text or filename."""
        text_patterns = [
            re.compile(r"版本[号]?[：:\s]*([Vv]?\d+\.\d+)", re.IGNORECASE),
            re.compile(r"[Vv]ersion[：:\s]*([Vv]?\d+\.\d+)", re.IGNORECASE),
            re.compile(r"[Ff]orm[Ww]are?\s*([Vv]?\d+\.\d+)", re.IGNORECASE),
        ]
        for pat in text_patterns:
            m = pat.search(text)
            if m:
                ver = m.group(1).upper().lstrip("V")
                return self._make_evidence(
                    value=f"V{ver}", confidence=0.9, page=None,
                    evidence_text=m.group(0), source=FieldSource.RULE,
                )
        fn_patterns = [
            re.compile(r"[Ff]orm[Ww]are?\s*([Vv]?\d+\.\d+)", re.IGNORECASE),
            re.compile(r"\bFW(\d{2})\b", re.IGNORECASE),
            re.compile(r"(\d+\.\d+)(?=升级|版本)"),
        ]
        for i, pat in enumerate(fn_patterns):
            m = pat.search(filename)
            if m:
                raw = m.group(1)
                if i == 1:
                    raw = f"{raw[0]}.{raw[1]}"
                ver = raw.upper().lstrip("V")
                return self._make_evidence(
                    value=f"V{ver}", confidence=0.7, page=None,
                    evidence_text=m.group(0), source=FieldSource.RULE,
                )
        return None
