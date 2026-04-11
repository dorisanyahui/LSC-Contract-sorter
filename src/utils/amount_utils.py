from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.schema import Candidate

from src.models.enums import FieldSource


# Chinese numeral mapping
_CN_NUM: dict[str, int] = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "两": 2,
}
_CN_UNIT: dict[str, int] = {
    "十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000,
}


def ocr_digit_fix(s: str) -> str:
    """Fix common OCR misrecognitions in numeric strings.

    Replaces O->0, I/l->1, S->5, B->8 when in a numeric context.
    Only transforms characters that are within a primarily-numeric string.
    """
    # Build list of chars and fix common OCR errors
    result = []
    for i, ch in enumerate(s):
        if ch in ("O", "o"):
            result.append("0")
        elif ch in ("I", "l") and i > 0 and (s[i - 1].isdigit() or (i + 1 < len(s) and s[i + 1].isdigit())):
            result.append("1")
        elif ch == "S" and i > 0 and s[i - 1].isdigit():
            result.append("5")
        elif ch == "B" and i > 0 and s[i - 1].isdigit():
            result.append("8")
        else:
            result.append(ch)
    return "".join(result)


def normalize_amount(s: str) -> float | None:
    """Parse an amount string into a float.

    Handles:
    - Comma-separated thousands: 6,750 / 33,750.00
    - OCR digit errors: 8OOO -> 8000, 675O -> 6750
    - Chinese 万: 3.375万 -> 33750
    - Plain integers and decimals
    """
    if not s:
        return None
    s = s.strip()

    # Remove currency symbols
    s = re.sub(r"[¥￥$€£]", "", s)
    s = s.strip()

    # Handle Chinese 万
    wan_match = re.match(r"^([\d,，.]+)\s*万$", s)
    if wan_match:
        inner = wan_match.group(1).replace(",", "").replace("，", "")
        try:
            return float(inner) * 10000
        except ValueError:
            pass

    # Try Chinese number parsing first
    cn_result = parse_chinese_amount(s)
    if cn_result is not None:
        return cn_result

    # Apply OCR digit fixes
    s_fixed = ocr_digit_fix(s)

    # Remove thousands separators (comma)
    s_fixed = s_fixed.replace(",", "").replace("，", "")

    # Handle OCR dot-as-thousands: "5.198" → 5198, "40.755" → 40755
    # Pattern: X.XXX where X < 100 and exactly 3 fractional digits (thousands separator)
    dot_thousands = re.match(r"^(\d{1,3})\.(\d{3})$", s_fixed.strip())
    if dot_thousands:
        try:
            val = float(dot_thousands.group(1) + dot_thousands.group(2))
            if val >= 500:
                return val
        except ValueError:
            pass

    # Extract numeric portion
    match = re.search(r"\d+(?:\.\d+)?", s_fixed)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            pass

    return None


def parse_chinese_amount(s: str) -> float | None:
    """Parse Chinese number strings like 三万三千七百五十 -> 33750."""
    if not s:
        return None

    # Only attempt if the string contains Chinese numerals
    has_cn = any(ch in _CN_NUM or ch in _CN_UNIT for ch in s)
    if not has_cn:
        return None

    # Strip any non-Chinese-numeric characters
    s_clean = "".join(ch for ch in s if ch in _CN_NUM or ch in _CN_UNIT)
    if not s_clean:
        return None

    try:
        result = 0
        current = 0
        prev_unit = 1

        for ch in s_clean:
            if ch in _CN_NUM:
                current = _CN_NUM[ch]
            elif ch in _CN_UNIT:
                unit = _CN_UNIT[ch]
                if unit == 10 and current == 0:
                    current = 1
                if unit >= 10000:
                    result = (result + current * prev_unit) * (unit // prev_unit) if prev_unit < unit else result + current * unit
                    result = (result + current) * unit if current > 0 else result * (unit // 10000) if ch == "亿" else result + current * unit
                    # Simpler approach: accumulate
                    current = 0
                    prev_unit = unit
                else:
                    result += current * unit
                    current = 0
                    prev_unit = unit

        result += current
        return float(result) if result > 0 else None
    except Exception:
        return None


def extract_amount_candidates(text: str, page: int) -> list["Candidate"]:
    """Find all monetary amounts in text with contextual labels and quality scores."""
    from src.models.schema import Candidate

    candidates: list[Candidate] = []

    # Labels to look for near amounts (order = priority)
    label_patterns = [
        (r"年度维护费|年维护费|年度服务费|年服务费|年度维护服务费|维护服务费用|年度.*服务费用", "annual_maintenance_fee"),
        (r"维护费|服务费", "maintenance_fee"),
        (r"含税(?:总)?价?(?:格)?|含税金额|Total.*(?:VAT|tax)|(?:VAT|tax).*[Ii]nclusive", "tax_included_amount"),
        (r"不含税(?:总)?价?(?:格)?|不含税金额|[Ee]xcluding.*[Tt]ax|[Ww]/[Oo]\s*VAT", "tax_excluded_amount"),
        (r"合同总(?:金额|价格|价)|Total\s+(?:Order|Amount|Price)|合计|总价", "contract_total_amount"),
        (r"金额|amount", "amount_generic"),
        (r"价格|price", "price_generic"),
        (r"费用|fee|charge", "fee_generic"),
    ]

    # Lines containing these patterns are noise — skip entirely
    _NOISE_LINE = re.compile(
        r"电话|传真|Fax\b|Tel\b|Phone\b|地址|Address\b|邮编|Postal\b|Zip\b"
        r"|账号|开户行|Bank\b|swift|IBAN"
        r"|页码|Page\s*\d|第\s*\d+\s*页",
        re.IGNORECASE,
    )

    # High-confidence monetary context: amount is definitely financial
    _HIGH_CTX = re.compile(
        r"年度维护|年度服务|维护费用|服务费用|合同金额|合同总价|总金额|总价|合计"
        r"|[Tt]otal\s*[Aa]mount|[Tt]otal\s*[Pp]rice|[Tt]otal\s*[Oo]rder"
        r"|[Aa]nnual.*[Ff]ee|[Mm]aintenance.*[Ff]ee|[Ss]ervice.*[Ff]ee"
        r"|[Cc]ontract\s*[Vv]alue|[Ss]ubtotal"
        r"|含税|不含税|Unit\s*Price|VAT",
        re.IGNORECASE,
    )

    # Medium-confidence: likely financial but less certain
    _MED_CTX = re.compile(
        r"人民币|RMB\b|USD\b|EUR\b|CNY\b|元[^\w]|费用|金额|价格|价款"
        r"|[Aa]mount|[Pp]rice|[Ff]ee|[Cc]harge|[Cc]ost",
        re.IGNORECASE,
    )

    # Amount pattern: digits with optional commas/decimal, optional currency markers
    amount_pattern = re.compile(
        r"[¥￥$€£]?\s*(\d[\d,，Oo Il]*(?:\.\d+)?)\s*(?:元|人民币|CNY|USD|EUR)?",
        re.IGNORECASE,
    )

    lines = text.splitlines()
    for line_idx, line in enumerate(lines):
        # Skip lines that are clearly phone numbers / addresses / headers
        if _NOISE_LINE.search(line):
            continue

        for amt_match in amount_pattern.finditer(line):
            raw_val = amt_match.group(1)
            value = normalize_amount(raw_val)
            if value is None or value < 100:
                continue

            # Skip address-number pattern: digit followed immediately by 号/室/楼/层
            pos_after = amt_match.end()
            after_chars = line[pos_after: pos_after + 4].strip()
            if after_chars and after_chars[0] in "号室楼层栋":
                continue

            # Skip invoice/document reference numbers: patterns like "186/V" or "686/v发票底票"
            if re.match(r"^\s*/[Vv]", line[pos_after: pos_after + 5]):
                continue

            # Context window (±3 lines)
            ctx_start = max(0, line_idx - 2)
            ctx_end = min(len(lines), line_idx + 3)
            context = "\n".join(lines[ctx_start:ctx_end])

            # Assign label from context
            label = "amount_generic"
            for pattern_str, lbl in label_patterns:
                if re.search(pattern_str, context):
                    label = lbl
                    break

            # Score based on context quality.
            # A standalone bare number (short line, no currency markers) is
            # penalised even when neighbouring lines have high-context keywords,
            # because those keywords may belong to a DIFFERENT amount on the
            # next/previous line (e.g. a section-number "140" before a fee line).
            is_bare_number = (
                len(line.strip()) < 15
                and not re.search(r"[元年月日￥¥$€£]|CNY|USD|EUR|RMB", line)
            )
            if is_bare_number:
                # Still assign score based on same-line context (none), but cap low
                score = 0.35
            elif _HIGH_CTX.search(line):
                # High-context keyword ON the amount line itself → very confident
                score = 0.95
            elif _HIGH_CTX.search(context):
                # High-context only in neighbouring lines → moderately confident
                score = 0.75
            elif _MED_CTX.search(context):
                score = 0.80
            else:
                score = 0.60

            candidates.append(
                Candidate(
                    value=raw_val,
                    normalized_value=str(value),
                    label=label,
                    page=page,
                    evidence_text=line.strip(),
                    score=score,
                    source=FieldSource.OCR,
                )
            )

    return candidates


def validate_amount_range(value: float, field_name: str, ranges: dict) -> bool:
    """Check if a value falls within the configured range for a field."""
    field_range = ranges.get(field_name, [1000, 200000])
    if isinstance(field_range, (list, tuple)) and len(field_range) >= 2:
        return field_range[0] <= value <= field_range[1]
    return True
