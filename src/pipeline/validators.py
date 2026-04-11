from __future__ import annotations

import re

from src.models.schema import Candidate
from src.utils.amount_utils import validate_amount_range
from src.utils.date_utils import parse_date


_INVALID_COMPANY_PREFIXES = (
    "鉴于", "除了", "甲方公司", "乙方公司", "实施公司", "交通费",
    "根据", "按照", "基于", "为了", "由于", "通过其", "（无）",
    "兹", "经", "现",  # single-char contract preamble characters
    "（", "(",         # bare bracket-prefix fragments like "（无锡）有限公司"
    "family", "home", "house", "above", "least", "corporation(",
)

_INVALID_COMPANY_SUBSTRINGS = (
    "通过其", "（通过其", "(通过其",  # contract clause fragments
)

_VALID_COMPANY_SUFFIXES = (
    "有限公司", "有限责任公司", "股份有限公司", "股份公司", "集团", "控股",
    "corp", "corporation", "ltd", "limited", "inc", "group",
    "co.", "gmbh", "ag", "bv", "llc", "llp", "plc",
)


def is_clean_company_name(value: str) -> bool:
    """Return True only if value looks like a genuine company name.

    Requires a valid company suffix and rejects known garbage prefixes.
    """
    if not value:
        return False
    v = value.strip()
    v_lower = v.lower()

    # Must have a valid suffix, but the name cannot BE just a suffix alone
    matched_suffix = next((s for s in _VALID_COMPANY_SUFFIXES if v_lower.endswith(s)), None)
    if not matched_suffix:
        return False
    if v_lower == matched_suffix or len(v) - len(matched_suffix) < 2:
        return False  # e.g. bare "有限公司" or "X集团" with only 1 meaningful char

    # Must not start with known non-company phrases
    if any(v.startswith(p) for p in _INVALID_COMPANY_PREFIXES):
        return False

    # Must not contain clause fragments
    if any(s in v for s in _INVALID_COMPANY_SUBSTRINGS):
        return False

    # Length sanity: real company names are 4–50 chars
    if not (4 <= len(v) <= 50):
        return False

    return True


def validate_company(value: str, vendor_list: list[str]) -> tuple[bool, str]:
    """Validate a company name.

    Returns (is_valid, reason).
    """
    if not value or len(value.strip()) < 4:
        return False, "Company name too short (< 4 chars)"

    value_stripped = value.strip()

    # Check against vendor list (乙方 filter)
    for vendor in vendor_list:
        if vendor.lower() in value_stripped.lower():
            return False, f"Matches vendor blocklist: {vendor}"

    # Check for template/prompt text
    if len(value_stripped) > 60 and "注意" in value_stripped:
        return False, "Looks like template text"

    # Reject known garbage prefixes and clause fragments
    if any(value_stripped.startswith(p) for p in _INVALID_COMPANY_PREFIXES):
        return False, "Starts with non-company phrase"
    if any(s in value_stripped for s in _INVALID_COMPANY_SUBSTRINGS):
        return False, "Contains clause fragment"

    return True, ""


def validate_date(value: str) -> tuple[bool, str]:
    """Validate a date string.

    Returns (is_valid, reason).
    """
    if not value:
        return False, "Empty date"

    parsed = parse_date(value)
    if parsed is None:
        return False, f"Cannot parse date: {value}"

    if parsed.year < 1990 or parsed.year > 2040:
        return False, f"Year out of range: {parsed.year}"

    return True, ""


def validate_amount(value: float, field_name: str, ranges: dict) -> tuple[bool, str]:
    """Validate an amount value against configured ranges.

    Returns (is_valid, reason).
    """
    if value is None:
        return False, "Amount is None"

    if value <= 0:
        return False, f"Amount must be positive, got {value}"

    # Reject values that look like calendar years (e.g. "2023" extracted from "2023年11月")
    if value == int(value) and 1990 <= int(value) <= 2035:
        return False, f"Amount {value} looks like a year, not a monetary value"

    if not validate_amount_range(value, field_name, ranges):
        field_range = ranges.get(field_name, [1000, 200000])
        return False, f"Amount {value} outside range {field_range} for {field_name}"

    return True, ""


def validate_tax_rate(value: str) -> tuple[bool, str]:
    """Validate a tax rate string.

    Returns (is_valid, reason).
    """
    if not value:
        return False, "Empty tax rate"

    # Allow formats like 13%, 6%, 13.0%, 0%
    m = re.match(r"^(\d{1,2}(?:\.\d+)?)\s*%?$", value.strip())
    if not m:
        return False, f"Cannot parse tax rate: {value}"

    rate = float(m.group(1))
    # Known valid Chinese tax rates (营业税/增值税 historical and current)
    _VALID_CN_TAX_RATES = {3.0, 5.0, 6.0, 9.0, 10.0, 11.0, 13.0, 16.0, 17.0}
    if rate not in _VALID_CN_TAX_RATES and not (rate != int(rate) and 0 < rate <= 17):
        return False, f"Tax rate {rate}% not a known CN tax rate (valid: 3,5,6,9,10,11,13,16,17%)"

    return True, ""


def careful_check_amount(
    value: float,
    candidates: list[Candidate],
    field_name: str,
    ranges: dict,
) -> float | None:
    """Re-examine other candidates if the primary value fails validation.

    Returns a valid amount or None if no valid candidate is found.
    """
    # First check if the primary value is valid
    is_valid, _ = validate_amount(value, field_name, ranges)
    if is_valid:
        return value

    # Try other candidates sorted by score descending
    sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
    for candidate in sorted_candidates:
        try:
            alt_value = float(candidate.normalized_value)
        except (ValueError, TypeError):
            from src.utils.amount_utils import normalize_amount
            alt_value = normalize_amount(candidate.value)
            if alt_value is None:
                continue

        is_valid, _ = validate_amount(alt_value, field_name, ranges)
        if is_valid:
            return alt_value

    return None
