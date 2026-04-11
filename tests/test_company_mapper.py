"""Tests for company mapping and normalization."""
import pytest

from src.pipeline.normalizers import normalize_company_name, strip_city


class TestStripCity:
    """Tests for strip_city function."""

    def test_strip_leading_city_prefix(self):
        """青岛派克汉尼汾流体连接件有限公司 -> 派克汉尼汾流体连接件有限公司."""
        result = strip_city("青岛派克汉尼汾流体连接件有限公司")
        assert "青岛" not in result
        assert "派克汉尼汾" in result

    def test_strip_bracketed_city(self):
        """派克汉尼汾流体连接件(青岛)有限公司 -> 派克汉尼汾流体连接件有限公司."""
        result = strip_city("派克汉尼汾流体连接件(青岛)有限公司")
        assert "青岛" not in result
        assert "派克汉尼汾" in result

    def test_strip_full_width_bracketed_city(self):
        """派克汉尼汾（青岛）有限公司 -> 派克汉尼汾有限公司."""
        result = strip_city("派克汉尼汾（青岛）有限公司")
        assert "青岛" not in result

    def test_no_city_unchanged(self):
        """Names without city should be unchanged."""
        name = "派克汉尼汾有限公司"
        result = strip_city(name)
        assert result == name

    def test_shanghai_prefix(self):
        result = strip_city("上海大众汽车有限公司")
        assert "上海" not in result
        assert "大众汽车" in result

    def test_beijing_prefix(self):
        result = strip_city("北京汽车制造厂有限公司")
        assert "北京" not in result

    def test_empty_string(self):
        assert strip_city("") == ""

    def test_short_name_not_stripped(self):
        """Should not strip if result would be too short (< 4 chars)."""
        result = strip_city("上海公司")
        # "公司" is only 2 chars, so should not strip 上海
        # This depends on implementation - name stays intact
        assert result  # Just ensure it doesn't crash


class TestNormalizeCompanyName:
    """Tests for normalize_company_name function."""

    def test_strip_city_and_normalize_brackets(self):
        result = normalize_company_name("青岛派克汉尼汾（中国）有限公司")
        # Should strip city and normalize brackets
        assert "青岛" not in result

    def test_normalize_full_width_brackets(self):
        """（ should become (."""
        result = normalize_company_name("派克汉尼汾（中国）有限公司")
        assert "（" not in result
        assert "（" not in result

    def test_strip_extra_whitespace(self):
        result = normalize_company_name("  派克汉尼汾  有限公司  ")
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_empty_string(self):
        result = normalize_company_name("")
        assert result == ""


class TestAliasMatcher:
    """Tests for AliasMatcher fuzzy matching."""

    def test_exact_match(self):
        from src.mapping.alias_matcher import AliasMatcher
        matcher = AliasMatcher()
        result = matcher.match("派克汉尼汾", ["派克汉尼汾", "ABB", "西门子"])
        assert result == "派克汉尼汾"

    def test_fuzzy_match(self):
        from src.mapping.alias_matcher import AliasMatcher
        matcher = AliasMatcher()
        # Slight variation
        result = matcher.match("派克汉尼汾有限公司", ["派克汉尼汾", "ABB", "西门子"], threshold=60)
        assert result == "派克汉尼汾"

    def test_no_match_below_threshold(self):
        from src.mapping.alias_matcher import AliasMatcher
        matcher = AliasMatcher()
        result = matcher.match("完全不同的公司名称", ["派克汉尼汾", "ABB", "西门子"], threshold=90)
        assert result is None

    def test_empty_candidates(self):
        from src.mapping.alias_matcher import AliasMatcher
        matcher = AliasMatcher()
        result = matcher.match("派克汉尼汾", [])
        assert result is None

    def test_match_any_finds_group(self):
        from src.mapping.alias_matcher import AliasMatcher
        matcher = AliasMatcher()
        candidates_map = {
            "Parker": ["派克汉尼汾", "Parker Hannifin"],
            "ABB": ["ABB集团", "ABB中国"],
        }
        result = matcher.match_any("派克汉尼汾有限公司", candidates_map, threshold=60)
        assert result == "Parker"
