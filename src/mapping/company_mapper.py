from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from loguru import logger

from src.mapping.alias_matcher import AliasMatcher
from src.pipeline.normalizers import normalize_company_name, strip_city

# Trailing internal accounting codes appended by finance systems, e.g. "-legris", "(685)", "_AUTOMATION(648)"
_INTERNAL_CODE_RE = re.compile(
    r'(?:[-_][A-Za-z]+(?:\(\d+\))?|\(\d{3,}\))$'
)


def _strip_internal_code(name: str) -> str:
    """Remove trailing internal accounting codes from a company name."""
    return _INTERNAL_CODE_RE.sub("", name).strip()


class CompanyMapper:
    """Maps company names to group names using the Excel mapping file."""

    def __init__(self) -> None:
        self._df: pd.DataFrame | None = None
        self._exact_map: dict[str, str] = {}          # normalized_name -> group
        self._alias_map: dict[str, str] = {}          # alias -> group
        self._group_names_map: dict[str, list[str]] = {}  # group -> [company names]
        self._keyword_map: dict[str, str] = {}        # distinctive substring -> group
        self._matcher = AliasMatcher()
        self._loaded = False

    def load(self, excel_path: Path) -> None:
        """Load company-to-group mapping from Excel file."""
        try:
            df = pd.read_excel(excel_path, dtype=str)
            df = df.fillna("")
            self._df = df

            # Expected columns: 名称, 所属集团名称, 简称
            if "名称" not in df.columns or "所属集团名称" not in df.columns:
                logger.error(f"Mapping file missing required columns. Found: {list(df.columns)}")
                return

            for _, row in df.iterrows():
                raw_name = str(row.get("名称", "")).strip()
                group = str(row.get("所属集团名称", "")).strip()
                alias = str(row.get("简称", "")).strip()

                if not raw_name or not group:
                    continue

                # Normalize the name and add to exact map
                norm = normalize_company_name(raw_name)
                self._exact_map[norm] = group
                self._exact_map[raw_name] = group

                # Also map version without internal accounting codes (e.g. "-legris", "(685)")
                plain = _strip_internal_code(raw_name)
                if plain != raw_name:
                    self._exact_map[plain] = group
                    self._exact_map[normalize_company_name(plain)] = group

                # Also map stripped city version
                stripped = strip_city(raw_name)
                if stripped != raw_name:
                    self._exact_map[stripped] = group
                    plain_stripped = _strip_internal_code(stripped)
                    if plain_stripped != stripped:
                        self._exact_map[plain_stripped] = group
                        self._exact_map[normalize_company_name(plain_stripped)] = group

                # Add alias mapping
                if alias:
                    self._alias_map[alias] = group
                    norm_alias = normalize_company_name(alias)
                    self._alias_map[norm_alias] = group

                # Build per-group name list for fuzzy matching
                if group not in self._group_names_map:
                    self._group_names_map[group] = []
                self._group_names_map[group].append(norm)
                if alias:
                    self._group_names_map[group].append(alias)

            # Build keyword map: find substrings that appear in ≥2 companies of the same group
            # and are ≥4 chars. These become reliable group identifiers.
            self._keyword_map = self._build_keyword_map()

            # Pre-sort exact_map keys by length (longest first) for filename matching
            self._exact_map_by_length: list[tuple[str, str]] = sorted(
                self._exact_map.items(), key=lambda x: -len(x[0])
            )

            self._loaded = True
            logger.info(f"Loaded {len(self._exact_map)} company mappings across {len(self._group_names_map)} groups")

        except Exception as e:
            logger.error(f"Failed to load mapping file {excel_path}: {e}")

    # Tokens that must never become keywords (legal/geographic noise)
    _KW_BLOCKLIST = {
        "有限公司", "有限责任", "股份有限", "有限责任公司", "股份有限公司",
        "集团", "控股", "中国", "上海", "北京", "广州", "深圳",
        "天津", "无锡", "成都", "武汉", "南京", "杭州", "沈阳",
    }

    def _build_keyword_map(self) -> dict[str, str]:
        """Build keyword→group map.

        Two sources:
        1. Group name + English aliases (always included).
        2. Chinese substrings of length ≥5 that appear in ≥3 companies of ONE group only.
           Substrings shared across multiple groups are discarded to avoid false positives.
        """
        keyword_map: dict[str, str] = {}

        # Source 1: group name + English aliases
        for group in self._group_names_map:
            if len(group) >= 3:
                keyword_map.setdefault(group.lower(), group)
        for alias, group in self._alias_map.items():
            alias_clean = alias.strip().lower()
            if len(alias_clean) >= 3 and alias_clean.isascii():
                keyword_map.setdefault(alias_clean, group)

        # Source 2: shared Chinese substrings unique to one group
        # Build: substr → {group: count}
        from collections import defaultdict
        substr_groups: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        _LEGAL_SFXS = ("有限公司", "有限责任公司", "股份有限公司", "集团", "控股")

        for group, names in self._group_names_map.items():
            for name in names:
                # Strip internal accounting codes first (e.g. "-legris", "(685)")
                # so they don't block legal suffix detection
                name = _strip_internal_code(name)
                # Strip legal suffix to get the distinctive core
                core = name
                for sfx in _LEGAL_SFXS:
                    if core.endswith(sfx):
                        core = core[: -len(sfx)]
                        break
                # Extract Chinese substrings of length 5–8
                for length in range(5, min(len(core) + 1, 9)):
                    for start in range(len(core) - length + 1):
                        substr = core[start: start + length]
                        if substr in self._KW_BLOCKLIST:
                            continue
                        # Skip substrings that are mostly ASCII or digits
                        chinese_chars = sum(1 for c in substr if '\u4e00' <= c <= '\u9fff')
                        if chinese_chars < len(substr) * 0.6:
                            continue
                        substr_groups[substr][group] += 1

        # Only keep substrings that belong to EXACTLY ONE group with count ≥ 3
        for substr, group_counts in substr_groups.items():
            if len(group_counts) == 1:
                group, count = next(iter(group_counts.items()))
                if count >= 3 and substr.lower() not in keyword_map:
                    keyword_map[substr.lower()] = group

        return keyword_map

    def map_to_group(self, company_name: str) -> str:
        """Map a company name to its group name.

        Tries: exact match -> alias match -> strip_city + exact -> fuzzy match.
        Returns empty string if no match found.
        """
        if not company_name or not self._loaded:
            return ""

        # 1. Exact match
        if company_name in self._exact_map:
            return self._exact_map[company_name]

        # 2. Normalized exact match
        norm = normalize_company_name(company_name)
        if norm in self._exact_map:
            return self._exact_map[norm]

        # 3. Alias match
        if company_name in self._alias_map:
            return self._alias_map[company_name]
        if norm in self._alias_map:
            return self._alias_map[norm]

        # 4. Strip city and try again
        stripped = strip_city(company_name)
        if stripped != company_name:
            if stripped in self._exact_map:
                return self._exact_map[stripped]
            norm_stripped = normalize_company_name(stripped)
            if norm_stripped in self._exact_map:
                return self._exact_map[norm_stripped]

        # 5. Keyword match: group name or English alias appears in company name
        norm_lower = norm.lower()
        best_kw: str | None = None
        best_group: str | None = None
        for kw, grp in self._keyword_map.items():
            if kw in norm_lower and (best_kw is None or len(kw) > len(best_kw)):
                best_kw = kw
                best_group = grp
        if best_group:
            return best_group

        return ""

    def extract_company_from_filename(self, filename: str) -> str:
        """Return the longest known company name found in the filename, or empty string.

        Uses the same bracket-normalization as map_by_filename.
        The returned name is the canonical key from the mapping file (accurate).
        """
        if not filename or not self._loaded:
            return ""
        fname_norm = filename.replace("（", "(").replace("）", ")")
        fname_lower = fname_norm.lower()
        for company_name, _group in self._exact_map_by_length:
            if len(company_name) >= 5 and company_name.lower() in fname_lower:
                return company_name
        return ""

    def find_company_by_fragment(self, fragment: str) -> str:
        """Find the best matching company where the fragment is a substring of the name.

        Used when the filename contains a partial company name like '派克汉尼汾(无锡)'
        that is not itself a full entry in the mapping but is a prefix/fragment of one.

        Supports two matching strategies:
        1. Exact substring: "派克汉尼汾" ⊂ company name
        2. Token-based: fragment split by brackets → all tokens must appear in company name
           e.g. "派克汉尼汾(无锡)" → ["派克汉尼汾", "无锡"] both in company

        Returns the SHORTEST matching company name (most specific match), or "".
        """
        if not fragment or not self._loaded or len(fragment) < 4:
            return ""
        frag_norm = fragment.replace("（", "(").replace("）", ")").lower()

        # Build token list: split by brackets and use all non-empty parts
        tokens = [t.strip("(（）)").strip() for t in re.split(r"[（）()]", frag_norm) if t.strip("(（）)").strip()]

        # Walk shortest-first so we return the most specific (shortest) match
        best: tuple[int, str] = (10**9, "")
        for company_name, _group in reversed(self._exact_map_by_length):  # reversed = shortest first
            if len(company_name) < 4:
                continue
            cn_norm = company_name.replace("（", "(").replace("）", ")").lower()
            # Strategy 1: exact substring match
            if frag_norm in cn_norm:
                if len(company_name) < best[0]:
                    best = (len(company_name), company_name)
            # Strategy 2: all tokens present (handles "派克汉尼汾(无锡)" → name with both parts)
            elif len(tokens) >= 2 and all(tok in cn_norm for tok in tokens):
                if len(company_name) < best[0]:
                    best = (len(company_name), company_name)
        return best[1]

    def map_by_filename(self, filename: str) -> str:
        """Try to determine group from the filename when company extraction failed.

        Chinese keywords use substring match; ASCII keywords require whole-word match
        to avoid false positives like 'wofe' matching 'wofe1'.
        Returns group name or empty string.
        """
        if not filename or not self._loaded:
            return ""
        # Normalize filename brackets so full-width （） matches half-width () in exact_map
        fname_norm = filename.replace("（", "(").replace("）", ")")
        fname_lower = fname_norm.lower()

        # First: check known company full names in filename (longest match wins)
        for company_name, group in self._exact_map_by_length:
            if len(company_name) >= 5 and company_name.lower() in fname_lower:
                return group

        # Second: keyword map (group names + English aliases + high-freq substrings)
        best_kw: str | None = None
        best_group: str | None = None
        for kw, grp in self._keyword_map.items():
            if kw.isascii():
                matched = bool(re.search(r'\b' + re.escape(kw) + r'\b', fname_lower))
            else:
                matched = kw in fname_lower
            if matched and (best_kw is None or len(kw) > len(best_kw)):
                best_kw = kw
                best_group = grp
        return best_group or ""

    def resolve_company_role(
        self,
        text_snippet: str,
        company_names: list[str],
    ) -> dict[str, str]:
        """Determine buyer/seller roles from text context.

        Returns dict with keys: buyer, seller.
        """
        buyer_keywords = ["甲方", "采购方", "买方", "client", "buyer", "purchaser"]
        seller_keywords = ["乙方", "供应商", "卖方", "vendor", "seller", "supplier", "service provider"]

        result: dict[str, str] = {"buyer": "", "seller": ""}

        for company in company_names:
            # Look for company in lines with buyer/seller context
            lines = text_snippet.splitlines()
            for line in lines:
                if company not in line:
                    continue

                line_lower = line.lower()
                has_buyer = any(kw.lower() in line_lower for kw in buyer_keywords)
                has_seller = any(kw.lower() in line_lower for kw in seller_keywords)

                if has_buyer and not result["buyer"]:
                    result["buyer"] = company
                elif has_seller and not result["seller"]:
                    result["seller"] = company

        return result

    def get_all_groups(self) -> list[str]:
        """Return a list of all known group names."""
        return list(self._group_names_map.keys())
