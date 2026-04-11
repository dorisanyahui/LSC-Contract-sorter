from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from src.config import Settings, get_settings
from src.mapping.company_mapper import CompanyMapper
from src.models.enums import Currency, DocType, FieldSource
from src.models.schema import DocumentResult, FieldEvidence
from src.pipeline.candidate_builder import CandidateBuilder
from src.pipeline.ocr_pipeline import OCRPipeline
from src.pipeline.packetizer import Packetizer
from src.pipeline.page_classifier import PageClassifier
from src.pipeline.pdf_router import PDFRouter
from src.pipeline.summarizer import Summarizer
from src.pipeline.validators import validate_company, validate_date, is_clean_company_name
from src.utils.date_utils import determine_report_year
from src.utils.hash_utils import md5_file


def _detect_doc_type(
    candidates: dict,
    ocr_results: list,
    text_by_page: dict,
    filename: str,
    settings: Settings,
) -> DocType:
    """Detect document type from content (primary) and filename (fallback).

    Per spec: filename is a weak hint only. Content takes priority.
    """
    import re as _re
    from src.pipeline.normalizers import normalize_doc_type
    from src.utils.text_utils import contains_keywords

    def _kw_matches(kw: str, text: str) -> bool:
        """Match keyword in text; use word boundaries for short uppercase tokens like 'PO'."""
        kw_l = kw.lower()
        if len(kw) <= 3 and kw == kw.upper() and kw.isalpha():
            return bool(_re.search(r"\b" + _re.escape(kw_l) + r"\b", text.lower()))
        return kw_l in text.lower()

    filename_lower = filename.lower()
    # Use first 3 pages for type detection (titles are usually on early pages)
    early_pages = ocr_results[:3] if ocr_results else []
    all_text = "\n".join(r.raw_text for r in early_pages)

    doc_type_keywords = settings.rules.doc_type_keywords if settings.rules else {}

    # 0. Title-line check: first 15 lines of page 0 carry the document type reliably
    #    (e.g. "Services Request Form", "服务需求表", "Purchase Order", "报价单", "Quotation")
    title_lines = "\n".join(
        (early_pages[0].raw_text if early_pages else "").splitlines()[:15]
    )
    for type_name, keywords in doc_type_keywords.items():
        if any(_kw_matches(kw, title_lines) for kw in keywords):
            result = normalize_doc_type(type_name)
            if result != DocType.UNKNOWN:
                return result

    # 1. Content takes priority (spec: filename is weak hint)
    # Score each type by keyword matches in content
    content_scores: dict[str, int] = {}
    for type_name, keywords in doc_type_keywords.items():
        score = sum(1 for kw in keywords if _kw_matches(kw, all_text))
        if score > 0:
            content_scores[type_name] = score

    if content_scores:
        best_type = max(content_scores, key=lambda t: content_scores[t])
        result = normalize_doc_type(best_type)
        if result != DocType.UNKNOWN:
            return result

    # 2. Fall back to filename when content is unclear (poor scan / no text)
    for type_name, keywords in doc_type_keywords.items():
        if contains_keywords(filename_lower, keywords):
            result = normalize_doc_type(type_name)
            if result != DocType.UNKNOWN:
                return result

    return DocType.UNKNOWN


def _route_extractor(doc_type: DocType) -> Any:
    """Return the appropriate extractor for the document type."""
    from src.extractors.attachment_extractor import AttachmentExtractor
    from src.extractors.contract_extractor import ContractExtractor
    from src.extractors.payment_notice_extractor import PaymentNoticeExtractor
    from src.extractors.proposal_extractor import ProposalExtractor
    from src.extractors.purchase_order_extractor import PurchaseOrderExtractor
    from src.extractors.quote_extractor import QuoteExtractor
    from src.extractors.srf_extractor import SRFExtractor
    from src.extractors.unknown_extractor import UnknownExtractor

    mapping = {
        DocType.CONTRACT: ContractExtractor,
        DocType.PURCHASE_ORDER: PurchaseOrderExtractor,
        DocType.QUOTE: QuoteExtractor,
        DocType.PROPOSAL: ProposalExtractor,
        DocType.SRF: SRFExtractor,
        DocType.PAYMENT_NOTICE: PaymentNoticeExtractor,
        DocType.ATTACHMENT: AttachmentExtractor,
    }

    extractor_class = mapping.get(doc_type, UnknownExtractor)
    return extractor_class()


def _populate_result_from_fields(
    result: DocumentResult,
    fields: dict[str, FieldEvidence],
    settings: Settings,
) -> None:
    """Populate DocumentResult fields from extracted FieldEvidence dict."""
    from src.utils.amount_utils import normalize_amount
    from src.utils.date_utils import parse_date
    from src.pipeline.normalizers import normalize_date_str, normalize_tax_rate
    from src.pipeline.validators import validate_amount

    def get_val(key: str) -> str:
        ev = fields.get(key)
        return ev.value if ev else ""

    # Company fields
    if "detected_company" in fields:
        result.detected_company = get_val("detected_company")

    if "detected_counterparty" in fields:
        result.detected_counterparty = get_val("detected_counterparty")

    # Dates
    for field_name, result_attr in [
        ("sign_date", "sign_date"),
        ("effective_date", "effective_date"),
        ("service_period_start", "service_period_start"),
        ("service_period_end", "service_period_end"),
    ]:
        val = get_val(field_name)
        if val:
            parsed = parse_date(val)
            if parsed:
                setattr(result, result_attr, normalize_date_str(parsed))

    # Tax rate
    tax_rate = get_val("tax_rate")
    if tax_rate:
        result.tax_rate = normalize_tax_rate(tax_rate)

    # Amounts
    amount_ranges = settings.rules.amount_ranges if settings.rules else {}
    for field_name, result_attr in [
        ("annual_maintenance_fee", "annual_maintenance_fee"),
        ("tax_included_amount", "tax_included_amount"),
        ("tax_excluded_amount", "tax_excluded_amount"),
        ("contract_total_amount", "contract_total_amount"),
    ]:
        val = get_val(field_name)
        if val:
            amount = normalize_amount(val)
            if amount is not None:
                is_valid, reason = validate_amount(amount, field_name, amount_ranges)
                if is_valid:
                    setattr(result, result_attr, amount)
                else:
                    result.flags.append(f"amount_invalid:{field_name}:{reason}")
                    # Try next candidates stored in the FieldEvidence
                    ev = fields.get(field_name)
                    if ev and ev.candidates:
                        from src.utils.amount_utils import normalize_amount as _na
                        for alt in ev.candidates[1:]:  # skip first (already tried)
                            alt_val = _na(alt.normalized_value or alt.value)
                            if alt_val is not None:
                                alt_valid, _ = validate_amount(alt_val, field_name, amount_ranges)
                                if alt_valid:
                                    setattr(result, result_attr, alt_val)
                                    break

    # PO number / quote number
    po = get_val("po_number")
    if po:
        result.po_number = po

    quote_no = get_val("quote_number")
    if quote_no:
        result.quote_number = quote_no

    sw_ver = get_val("software_version")
    if sw_ver:
        result.software_version = sw_ver

    # Currency
    currency_val = get_val("currency")
    if currency_val:
        try:
            result.currency = Currency(currency_val.upper())
        except ValueError:
            pass

    # is_primary_doc
    is_primary = get_val("is_primary_doc")
    if is_primary == "False":
        result.is_primary_doc = False

    # doc_subtype
    subtype = get_val("attachment_subtype") or get_val("doc_subtype_hint")
    if subtype:
        result.doc_subtype = subtype

    # Store all extracted fields
    result.fields.update(fields)


class DocumentProcessor:
    """Full pipeline for processing individual PDF documents."""

    def __init__(
        self,
        settings: Settings | None = None,
        company_mapper: CompanyMapper | None = None,
        ai_resolver: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._pdf_router = PDFRouter()
        self._ocr_pipeline = OCRPipeline(self._settings)
        self._page_classifier = PageClassifier()
        self._packetizer = Packetizer()
        self._candidate_builder = CandidateBuilder()
        self._summarizer = Summarizer()
        self._company_mapper = company_mapper or self._load_mapper()
        self._ai_resolver = ai_resolver

    def _load_mapper(self) -> CompanyMapper:
        """Initialize and load company mapper."""
        mapper = CompanyMapper()
        mapping_file = self._settings.mapping_file
        if mapping_file.exists():
            mapper.load(mapping_file)
        else:
            logger.warning(f"Mapping file not found: {mapping_file}")
        return mapper

    def process_file(self, pdf_path: Path) -> DocumentResult:
        """Process a single PDF file through the full pipeline."""
        result = DocumentResult(
            file_path=str(pdf_path),
            file_name=pdf_path.name,
        )

        try:
            # Step 1: MD5
            result.file_md5 = md5_file(pdf_path)

            # Step 2: PDF router analysis
            router_info = self._pdf_router.analyze(pdf_path)
            result.page_count = router_info["page_count"]
            result.has_text_layer = router_info["has_text_layer"]
            text_by_page: dict[int, str] = router_info["text_by_page"]

            # Step 3: OCR — skip if PDF has a usable text layer
            if result.has_text_layer:
                # Build OCRPageResult directly from PDF text layer, no PaddleOCR needed
                from src.models.schema import OCRPageResult as _OCRPage
                ocr_results = [
                    _OCRPage(page_no=page_no, raw_text=text, blocks=[])
                    for page_no, text in sorted(text_by_page.items())
                ]
            else:
                ocr_results = self._ocr_pipeline.process(
                    pdf_path, result.file_md5, force=False
                )

            # Step 4: Page classification
            page_types = self._page_classifier.classify_all(ocr_results)

            # Step 5: Packetize
            packets = self._packetizer.split(ocr_results, page_types)
            result.packets = packets
            result.packet_count = len(packets)

            # Step 6: Build candidates
            candidates = self._candidate_builder.build_all(ocr_results, text_by_page)

            # Step 7: Detect doc type
            doc_type = _detect_doc_type(
                candidates, ocr_results, text_by_page,
                pdf_path.name, self._settings,
            )
            result.doc_type = doc_type

            # Use AI for doc type if still unknown and AI enabled
            if doc_type == DocType.UNKNOWN and self._ai_resolver:
                all_text = "\n".join(r.raw_text for r in ocr_results)
                from src.models.enums import DocType as DT
                all_types = [dt.value for dt in DT if dt != DT.UNKNOWN]
                ai_type_str = self._ai_resolver.classify_doc_type(
                    text_snippet=all_text,
                    filename=pdf_path.name,
                    candidates=all_types,
                )
                if ai_type_str and ai_type_str != "UNKNOWN":
                    try:
                        result.doc_type = DocType(ai_type_str)
                        doc_type = result.doc_type
                    except ValueError:
                        pass

            # Step 8: Route to extractor
            extractor = _route_extractor(doc_type)
            extracted_fields = extractor.extract(
                candidates, ocr_results, page_types, pdf_path.name
            )

            # Step 9: Populate result from extracted fields
            _populate_result_from_fields(result, extracted_fields, self._settings)

            # Step 10a: Filename-based group detection (always runs — filename is human-typed
            # and more reliable than OCR for identifying which client this belongs to)
            filename_group = self._company_mapper.map_by_filename(pdf_path.name)

            # Step 10: Company mapper - map detected_company to group
            if result.detected_company:
                is_valid, reason = validate_company(
                    result.detected_company,
                    self._settings.vendor_names,
                )
                if not is_valid:
                    result.flags.append(f"company_invalid:{reason}")
                    result.detected_company = ""
                else:
                    group = self._company_mapper.map_to_group(result.detected_company)
                    if group:
                        result.detected_group = group
                    elif is_clean_company_name(result.detected_company):
                        # Not in mapping but looks like a genuine company — use as its own folder
                        result.detected_group = result.detected_company
                    else:
                        result.detected_group = "未分组"
                        result.detected_company = ""  # Clear garbage company name (e.g. bare "有限公司")

            # Step 10b: Filename override — if filename identifies a known group AND it differs
            # from what OCR extracted, trust the filename (human-typed, more accurate than OCR)
            if filename_group:
                if not result.detected_group or result.detected_group in ("未分组", ""):
                    result.detected_group = filename_group
                elif result.detected_group != filename_group:
                    # Conflict: OCR says one group, filename says another → trust filename
                    result.flags.append(
                        f"group_conflict:ocr={result.detected_group},filename={filename_group}"
                    )
                    result.detected_group = filename_group

            # Step 10c: Company name fallback — fill in if still empty after extraction
            if not result.detected_company:
                # Try 1: match a known canonical company name from the filename
                known_name = self._company_mapper.extract_company_from_filename(pdf_path.name)
                if known_name:
                    is_valid, _ = validate_company(known_name, self._settings.vendor_names)
                    if is_valid:
                        result.detected_company = known_name
                        result.flags.append("company_from_filename_known")

            if not result.detected_company:
                # Try 1b: partial fragment match — filename contains a short form of a known name
                # e.g. "报价单-派克汉尼汾(无锡)-..." → finds "派克汉尼汾流动控制产品(无锡)有限公司"
                import re as _re
                # Extract CJK segments (with optional parens) between separators in the filename stem
                fn_fragments = _re.findall(
                    r"[\u4e00-\u9fa5a-zA-Z][\u4e00-\u9fa5a-zA-Z0-9（）()]{3,}",
                    pdf_path.stem,
                )
                for fragment in fn_fragments:
                    resolved = self._company_mapper.find_company_by_fragment(fragment)
                    if resolved:
                        is_valid, _ = validate_company(resolved, self._settings.vendor_names)
                        if is_valid:
                            result.detected_company = resolved
                            result.flags.append("company_from_filename_fragment")
                            break

            if not result.detected_company:
                # Try 2: regex-extract company names from filename stem
                from src.utils.text_utils import extract_company_names as _ecn
                for name in _ecn(pdf_path.stem):
                    is_valid, _ = validate_company(name, self._settings.vendor_names)
                    if is_valid and is_clean_company_name(name):
                        result.detected_company = name
                        result.flags.append("company_from_filename_regex")
                        break

            if not result.detected_company:
                # Try 3: best OCR/text candidate that matches the known group
                for cand in sorted(candidates.get("company", []), key=lambda c: -c.score):
                    is_valid, _ = validate_company(cand.value, self._settings.vendor_names)
                    if not is_valid or not is_clean_company_name(cand.value):
                        continue
                    cand_group = self._company_mapper.map_to_group(cand.value)
                    if not result.detected_group or cand_group == result.detected_group:
                        result.detected_company = cand.value
                        result.flags.append("company_from_text_candidate")
                        break

            # Step 11: Validators on dates
            for date_field in ["sign_date", "effective_date", "service_period_start", "service_period_end"]:
                val = getattr(result, date_field, "")
                if val:
                    is_valid, reason = validate_date(val)
                    if not is_valid:
                        result.flags.append(f"date_invalid:{date_field}:{reason}")
                        setattr(result, date_field, "")

            # Step 12: Determine report year
            result.report_year = determine_report_year(
                result.sign_date,
                result.effective_date,
                result.service_period_start,
                pdf_path.name,
            )

            # Compute overall confidence
            confidences = [ev.confidence for ev in result.fields.values()]
            if confidences:
                result.confidence_overall = sum(confidences) / len(confidences)

            # Generate summary
            result.summary = self._summarizer.generate(result, self._ai_resolver)

            # Save result to cache
            self._save_result_cache(result)

        except Exception as e:
            logger.error(f"Failed to process {pdf_path}: {e}")
            result.error = str(e)
            result.flags.append("processing_error")

        return result

    def _save_result_cache(self, result: DocumentResult) -> None:
        """Save DocumentResult to JSON cache."""
        if not result.file_md5:
            return
        cache_dir = self._settings.cache_dir / "results"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{result.file_md5}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result.model_dump(), f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save result cache: {e}")

    def process_batch(
        self,
        pdf_paths: list[Path],
        group_filter: str | None = None,
    ) -> list[DocumentResult]:
        """Process multiple PDF files.

        Args:
            pdf_paths: List of PDF paths to process.
            group_filter: If set, only return results for this group.

        Returns:
            List of DocumentResult, one per file (failures included with error field set).
        """
        from tqdm import tqdm

        results: list[DocumentResult] = []
        failed = 0

        for pdf_path in tqdm(pdf_paths, desc="Processing PDFs"):
            try:
                result = self.process_file(pdf_path)
                results.append(result)
            except Exception as e:
                logger.error(f"Unhandled exception for {pdf_path}: {e}")
                err_result = DocumentResult(
                    file_path=str(pdf_path),
                    file_name=pdf_path.name,
                    error=str(e),
                )
                err_result.flags.append("unhandled_exception")
                results.append(err_result)
                failed += 1

        logger.info(f"Processed {len(results)} files, {failed} failed")

        if group_filter:
            results = [r for r in results if r.detected_group == group_filter]
            logger.info(f"Filtered to {len(results)} results for group '{group_filter}'")

        return results
