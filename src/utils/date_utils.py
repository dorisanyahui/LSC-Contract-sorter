from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.schema import Candidate

from src.models.enums import FieldSource


_CN_MONTH: dict[str, int] = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}


def _two_digit_year(yy: int) -> int:
    """Convert 2-digit year to 4-digit year."""
    if yy >= 0 and yy <= 30:
        return 2000 + yy
    return 1900 + yy


def parse_date(s: str) -> date | None:
    """Parse date string in various formats.

    Handles:
    - YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
    - YYYY年MM月DD日 (Chinese)
    - YY-MM-DD (2-digit year)
    - Partial dates like YYYY-MM or YYYY年MM月
    """
    if not s:
        return None
    s = s.strip()

    # Standard ISO format: YYYY-MM-DD
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # Chinese format: YYYY年MM月DD日
    m = re.match(r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # Chinese with partial: YYYY年MM月
    m = re.match(r"^(\d{4})\s*年\s*(\d{1,2})\s*月$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass

    # Format with Chinese month name: YYYY年一月DD日
    m = re.match(r"^(\d{4})\s*年\s*(十?[一二三四五六七八九]|十[一二]?)\s*月\s*(\d{1,2})\s*日?$", s)
    if m:
        year = int(m.group(1))
        cn_month = m.group(2)
        day = int(m.group(3))
        month = _CN_MONTH.get(cn_month)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # 2-digit year: YY-MM-DD or YY.MM.DD (hyphen/dot only — slash dates are MM/DD/YY or DD/MM/YY)
    m = re.match(r"^(\d{2})[.-](\d{1,2})[.-](\d{1,2})$", s)
    if m:
        year = _two_digit_year(int(m.group(1)))
        try:
            return date(year, int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # M/DD/YY format (slash only, e.g. "2/09/14" = Feb 9, 2014)
    m = re.match(r"^(\d{1,2})/(\d{2})/(\d{2})$", s)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        year = _two_digit_year(int(m.group(3)))
        if 1 <= month <= 12:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # Compact: YYYYMMDD
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # Try dateutil as fallback
    try:
        from dateutil import parser as du_parser
        dt = du_parser.parse(s, dayfirst=False)
        if 1990 <= dt.year <= 2040:
            return dt.date()
    except Exception:
        pass

    return None


def _repair_ocr_date(s: str) -> str:
    """Fix common OCR misreads in handwritten dates.

    Examples:
      "202/.1. 8"  -> "2021.1.8"   (/ misread from handwritten 1)
      "202l.1.8"   -> "2021.1.8"   (l misread from 1)
      "2O21.1.8"   -> "2021.1.8"   (O misread from 0)
      "2021. 1. 8" -> "2021.1.8"   (spaces around separator)
    """
    # Remove spaces around common date separators
    s = re.sub(r"\s*([-/.])\s*", r"\1", s)
    # Fix O/o -> 0 in numeric positions
    s = re.sub(r"(?<=\d)[Oo](?=\d)", "0", s)
    s = re.sub(r"(?<=[^\d])[Oo](?=\d{2,4})", "0", s)
    # Fix l/I/| -> 1 in numeric positions (e.g. 202/ -> 2021, 202l -> 2021)
    # Pattern: 3 digits followed by /|l|I then a date separator
    s = re.sub(r"(\d{3})[/|lI]([.\-])", r"\g<1>1\2", s)
    return s


def extract_date_candidates(text: str, page: int) -> list["Candidate"]:
    """Extract date candidates from text with contextual labels."""
    from src.models.schema import Candidate

    candidates: list[Candidate] = []

    # Label patterns to check in context
    label_map = [
        (r"签字|签署|签订|甲乙双方|盖章|Authorized", "sign_date"),
        (r"生效|起始|开始执行", "effective_date"),
        (r"服务期.*?开始|开始服务", "service_period_start"),
        (r"服务期.*?结束|终止|到期|服务结束", "service_period_end"),
        (r"服务期间|维护期间|服务期限", "service_period"),
    ]

    import datetime as _dt
    current_year = _dt.date.today().year

    date_patterns = [
        re.compile(r"\d{4}[-/.]\s*\d{1,2}[-/.]\s*\d{1,2}"),  # allow spaces around separators e.g. "2021. 2.26"
        re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日?"),
        re.compile(r"\d{2}[.-]\d{1,2}[.-]\d{1,2}"),  # YY.MM.DD or YY-MM-DD (no slash)
        # OCR-noisy year: 3 digits + one of /|lI + separator (e.g. "202/.1.8")
        re.compile(r"\d{3}[/|lI][-/.]\d{1,2}[-/.]\s*\d{1,2}"),
        # M/DD/YY format (e.g. "2/09/14" = Feb 9, 2014) — context required
        re.compile(r"\b\d{1,2}/\d{2}/\d{2}\b"),
    ]

    # Context keywords that indicate a date field (required for 2-digit years and generic dates)
    date_ctx_pattern = re.compile(
        r"签字|签署|签订|Date|日期|盖章|生效|服务期|维护期|Authorized|时间|order\s*date|issued",
        re.IGNORECASE,
    )

    lines = text.splitlines()

    # Build a list of (line_idx, text_to_scan, source_line_for_evidence)
    # Include individual lines AND adjacent-pair stitches to catch OCR line-splits
    # e.g. "...于2015年11\n月11日...签署" → stitch → "...于2015年11月11日...签署"
    scan_pairs: list[tuple[int, str, str]] = []
    for i, ln in enumerate(lines):
        scan_pairs.append((i, ln, ln))
    for i in range(len(lines) - 1):
        stitched = lines[i].rstrip() + lines[i + 1].lstrip()
        # Only consider stitching when the join creates a plausible date bridge
        if re.search(r"\d{4}年\d{1,2}月|\d{4}[-/.]\d{1,2}[-/.]", stitched):
            # Use i as line index so context window is centred there
            scan_pairs.append((i, stitched, lines[i] + " | " + lines[i + 1]))

    seen_dates: set[str] = set()  # avoid duplicate candidates from stitching

    for line_idx, line, evidence_line in scan_pairs:
        for dp in date_patterns:
            for m in dp.finditer(line):
                raw = m.group(0)
                repaired = _repair_ocr_date(raw)
                parsed = parse_date(repaired)
                if parsed is None or parsed.year < 1990:
                    continue
                # Reject clearly future dates (more than 1 year ahead)
                if parsed.year > current_year + 1:
                    continue

                # Determine label from context
                ctx_start = max(0, line_idx - 2)
                ctx_end = min(len(lines), line_idx + 3)
                context = "\n".join(lines[ctx_start:ctx_end])

                label = "date_generic"
                for pattern_str, lbl in label_map:
                    if re.search(pattern_str, context):
                        label = lbl
                        break

                # Downgrade sign_date to date_condition if the context is a
                # conditional or deadline clause ("如果在X之前", "before X", etc.)
                # These are not actual signing dates.
                if label == "sign_date":
                    _CONDITIONAL_CTX = re.compile(
                        r"如果|如在|在.*之前|以前|不晚于|须在.*前|应在.*前"
                        r"|before\s+\w|deadline|截止|优惠期|折扣期",
                        re.IGNORECASE,
                    )
                    if _CONDITIONAL_CTX.search(context):
                        label = "date_condition"

                # For 2-digit-year matches and generic labels, require context keyword
                is_2digit = bool(re.match(r"^\d{2}[-/.]", raw))
                is_mddyy = bool(re.match(r"^\d{1,2}/\d{2}/\d{2}$", raw))
                if (is_2digit or is_mddyy) and label == "date_generic" and not date_ctx_pattern.search(context):
                    continue

                # Skip duplicate dates from stitching (same ISO date, same label)
                dedup_key = f"{parsed.isoformat()}:{label}"
                if dedup_key in seen_dates:
                    continue
                seen_dates.add(dedup_key)

                # Higher score for dates with strong contextual signals
                base_score = 0.7 if repaired == raw else 0.55
                _STRONG_SIGN_CTX = re.compile(r"签署|签订|签字|盖章|Authorized|双方.*签|order\s*date", re.IGNORECASE)
                if label == "sign_date" and _STRONG_SIGN_CTX.search(context):
                    base_score = min(base_score + 0.15, 0.95)

                candidates.append(
                    Candidate(
                        value=repaired,
                        normalized_value=parsed.isoformat(),
                        label=label,
                        page=page,
                        evidence_text=evidence_line.strip(),
                        score=base_score,
                        source=FieldSource.OCR,
                    )
                )

    return candidates


def determine_report_year(
    sign_date: str | None,
    effective_date: str | None,
    service_start: str | None,
    filename: str,
) -> int | None:
    """Determine the report year from available date fields and filename.

    Priority: sign_date > effective_date > service_start > filename year.
    Exception: if service_start is > sign_date by more than 2 years, prefer
    service_start (sign_date was likely extracted from a clause referencing an
    older agreement, not the actual signing of this document).
    """
    sign_parsed = parse_date(sign_date) if sign_date else None
    start_parsed = parse_date(service_start) if service_start else None

    # If service period start is much later than sign date, the sign date is likely
    # from a reference clause (e.g. "pursuant to the agreement signed on 2015-06-30").
    if (sign_parsed and start_parsed
            and 1990 <= sign_parsed.year <= 2040
            and 1990 <= start_parsed.year <= 2040
            and start_parsed.year - sign_parsed.year > 2):
        return start_parsed.year

    for date_str in [sign_date, effective_date, service_start]:
        if date_str:
            parsed = parse_date(date_str)
            if parsed and 1990 <= parsed.year <= 2040:
                return parsed.year

    # Try to extract year from filename
    m = re.search(r"(20\d{2}|19\d{2})", filename)
    if m:
        year = int(m.group(1))
        if 1990 <= year <= 2040:
            return year

    return None
