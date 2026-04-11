from __future__ import annotations

from src.models.enums import FieldSource
from src.models.schema import Candidate, OCRPageResult
from src.utils.amount_utils import extract_amount_candidates
from src.utils.date_utils import extract_date_candidates
from src.utils.text_utils import extract_company_names


class CandidateBuilder:
    """Builds candidate lists from OCR results and PDF text layers."""

    def build_company_candidates(
        self,
        ocr_results: list[OCRPageResult],
        text_by_page: dict[int, str],
    ) -> list[Candidate]:
        """Build company name candidates from all text sources."""
        candidates: list[Candidate] = []
        seen: set[str] = set()

        all_sources: list[tuple[str, int, FieldSource]] = []

        # From PDF text layer
        for page_no, text in text_by_page.items():
            all_sources.append((text, page_no, FieldSource.PDF_TEXT))

        # From OCR (only pages not well covered by text layer)
        for result in ocr_results:
            if result.raw_text.strip():
                all_sources.append((result.raw_text, result.page_no, FieldSource.OCR))

        for text, page_no, source in all_sources:
            names = extract_company_names(text)
            for name in names:
                if name not in seen:
                    seen.add(name)
                    candidates.append(
                        Candidate(
                            value=name,
                            normalized_value=name,
                            label="company",
                            page=page_no,
                            evidence_text=name,
                            score=0.6,
                            source=source,
                        )
                    )

        return candidates

    def build_date_candidates(
        self,
        ocr_results: list[OCRPageResult],
        text_by_page: dict[int, str],
    ) -> list[Candidate]:
        """Build date candidates from all text sources."""
        candidates: list[Candidate] = []

        for page_no, text in text_by_page.items():
            candidates.extend(extract_date_candidates(text, page_no))

        for result in ocr_results:
            if result.raw_text.strip():
                candidates.extend(extract_date_candidates(result.raw_text, result.page_no))

        return candidates

    def build_amount_candidates(
        self,
        ocr_results: list[OCRPageResult],
        text_by_page: dict[int, str],
    ) -> list[Candidate]:
        """Build monetary amount candidates from all text sources."""
        candidates: list[Candidate] = []

        for page_no, text in text_by_page.items():
            candidates.extend(extract_amount_candidates(text, page_no))

        for result in ocr_results:
            if result.raw_text.strip():
                candidates.extend(extract_amount_candidates(result.raw_text, result.page_no))

        return candidates

    def build_tax_candidates(
        self,
        ocr_results: list[OCRPageResult],
        text_by_page: dict[int, str],
    ) -> list[Candidate]:
        """Build tax rate candidates."""
        import re
        candidates: list[Candidate] = []

        # Match XX% followed optionally by 税/增值税/VAT, or preceded by 不含/含
        tax_pattern = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")
        # Trigger on explicit tax-rate labels (high confidence) or implicit tax mentions (lower)
        label_hi = re.compile(r"税率|增值税|VAT|tax\s*rate", re.IGNORECASE)
        label_lo = re.compile(r"税金|不含税|含税|税前|excluding\s*tax|including\s*tax", re.IGNORECASE)

        # Include both PDF text layer and OCR — complement each other
        all_texts: list[tuple[str, int, FieldSource]] = []
        for page_no, text in text_by_page.items():
            if text.strip():
                all_texts.append((text, page_no, FieldSource.PDF_TEXT))
        for result in ocr_results:
            if result.raw_text.strip():
                all_texts.append((result.raw_text, result.page_no, FieldSource.OCR))

        seen: set[str] = set()
        for text, page_no, source in all_texts:
            lines = text.splitlines()
            for line_idx, line in enumerate(lines):
                ctx_start = max(0, line_idx - 1)
                ctx_end = min(len(lines), line_idx + 2)
                context = "\n".join(lines[ctx_start:ctx_end])

                hi = label_hi.search(context)
                lo = label_lo.search(context)
                if not hi and not lo:
                    continue

                # Skip payment-schedule lines (e.g. "支付20%项目预付款", "首付30%")
                if re.search(r"预付款|首付|尾款|付款比|分期|款项|支付.*\d+%|advance\s*pay|installment", line, re.IGNORECASE):
                    continue

                # Known valid Chinese tax rates (营业税/增值税 historical and current)
                _VALID_CN_TAX_RATES = {3.0, 5.0, 6.0, 9.0, 10.0, 11.0, 13.0, 16.0, 17.0}

                for m in tax_pattern.finditer(line):
                    rate_val = float(m.group(1))
                    # Accept only known CN tax rates (reject payment percentages like 20%, 30%, 50%)
                    if rate_val not in _VALID_CN_TAX_RATES and not (rate_val != int(rate_val) and 3 <= rate_val <= 17):
                        continue
                    rate_str = m.group(1) + "%"
                    key = f"{page_no}:{rate_str}"
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        Candidate(
                            value=rate_str,
                            normalized_value=rate_str,
                            label="tax_rate",
                            page=page_no,
                            evidence_text=line.strip(),
                            score=0.85 if hi else 0.65,
                            source=source,
                        )
                    )

        return candidates

    def build_all(
        self,
        ocr_results: list[OCRPageResult],
        text_by_page: dict[int, str],
    ) -> dict[str, list[Candidate]]:
        """Build all candidate types and return as a dict."""
        return {
            "company": self.build_company_candidates(ocr_results, text_by_page),
            "date": self.build_date_candidates(ocr_results, text_by_page),
            "amount": self.build_amount_candidates(ocr_results, text_by_page),
            "tax_rate": self.build_tax_candidates(ocr_results, text_by_page),
        }
