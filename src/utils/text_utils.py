from __future__ import annotations

import re
import unicodedata


# Full-width to half-width translation table
_FW_HW_TABLE = str.maketrans(
    "　！＂＃＄％＆＇（）＊＋，－．／０１２３４５６７８９：；＜＝＞？＠"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "［＼］＾＿｀ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ｛｜｝～",
    " !\"#$%&'()*+,-./0123456789:;<=>?@"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
)


def normalize_text(text: str) -> str:
    """Normalize full/half-width characters, clean spaces and punctuation."""
    if not text:
        return ""
    # Unicode NFC normalization
    text = unicodedata.normalize("NFC", text)
    # Full-width to half-width
    text = text.translate(_FW_HW_TABLE)
    # Collapse multiple spaces (but not newlines)
    text = re.sub(r"[ \t]+", " ", text)
    # Normalize Chinese punctuation variants
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text.strip()


def strip_vendor_names(text: str, vendor_list: list[str]) -> str:
    """Remove vendor name occurrences from text."""
    for vendor in vendor_list:
        text = text.replace(vendor, "")
    return text.strip()


def extract_company_names(text: str) -> list[str]:
    """Extract Chinese and English company names from text using regex patterns."""
    patterns = [
        r"[\u4e00-\u9fa5a-zA-Z0-9（）()]{2,30}(?:有限责任公司|股份有限公司|有限公司)",
        r"[\u4e00-\u9fa5a-zA-Z0-9（）()]{2,20}集团(?:有限公司|股份有限公司)?",
        r"[\u4e00-\u9fa5]{2,15}(?:公司|企业)",
        # English: "Siemens Power Equipment Packages Co., Ltd." / "Diageo (Shanghai) Ltd." style
        r"[A-Z][A-Za-z0-9 \-&',\.()]{4,60}(?:Co\.,?\s*Ltd\.?|Ltd\.?|Corporation|Corp\.?|Incorporated|Inc\.?|Limited|GmbH|PLC|LLC)",
    ]
    # Words that are form labels, not company name starts
    _LABEL_PREFIXES = (
        "company ", "buyer ", "seller ", "client ", "vendor ",
        "party ", "supplier ", "rmb ", "usd ", "cny ", "eur ",
    )
    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            name = m.group(0).strip()
            if name in seen or len(name) < 4:
                continue
            # Skip if starts with a form-label word or currency indicator
            if name.lower().startswith(_LABEL_PREFIXES):
                continue
            # Skip if the name contains too many digits (likely an amount line)
            digit_count = sum(1 for c in name if c.isdigit())
            if digit_count > 4:
                continue
            found.append(name)
            seen.add(name)
    return found


def clean_ocr_text(text: str) -> str:
    """Remove common header/footer patterns and deduplicate lines."""
    if not text:
        return ""

    lines = text.splitlines()
    cleaned: list[str] = []
    seen_lines: set[str] = set()

    header_footer_patterns = [
        re.compile(r"^\s*第\s*\d+\s*页\s*(?:共\s*\d+\s*页)?\s*$"),
        re.compile(r"^\s*-\s*\d+\s*-\s*$"),
        re.compile(r"^\s*page\s+\d+\s*(?:of\s+\d+)?\s*$", re.IGNORECASE),
        re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
        re.compile(r"^\s*$"),
    ]

    for line in lines:
        stripped = line.strip()
        # Skip header/footer lines
        is_header_footer = any(p.match(stripped) for p in header_footer_patterns)
        if is_header_footer:
            continue
        # Deduplicate consecutive identical lines
        if stripped in seen_lines:
            continue
        seen_lines.add(stripped)
        cleaned.append(line)

    return "\n".join(cleaned)


def contains_keywords(text: str, keywords: list[str]) -> bool:
    """Check if text contains any of the given keywords (case-insensitive for ASCII)."""
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False
