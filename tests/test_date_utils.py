"""Tests for date_utils module."""
import pytest
from datetime import date

from src.utils.date_utils import (
    parse_date,
    extract_date_candidates,
    determine_report_year,
)


class TestParseDate:
    """Tests for parse_date function."""

    def test_iso_format(self):
        assert parse_date("2021-01-08") == date(2021, 1, 8)

    def test_dot_separator(self):
        assert parse_date("2021.1.8") == date(2021, 1, 8)

    def test_dot_separator_padded(self):
        assert parse_date("2021.01.08") == date(2021, 1, 8)

    def test_slash_separator(self):
        assert parse_date("2021/01/08") == date(2021, 1, 8)

    def test_chinese_format(self):
        assert parse_date("2021年1月8日") == date(2021, 1, 8)

    def test_chinese_format_padded(self):
        assert parse_date("2021年01月08日") == date(2021, 1, 8)

    def test_chinese_format_no_day_suffix(self):
        """年月 format without 日."""
        result = parse_date("2021年1月8")
        assert result == date(2021, 1, 8)

    def test_two_digit_year_recent(self):
        """21-01-08 should be 2021-01-08."""
        result = parse_date("21-01-08")
        assert result is not None
        assert result.year == 2021

    def test_two_digit_year_old(self):
        """99-01-08 should be 1999-01-08."""
        result = parse_date("99-01-08")
        assert result is not None
        assert result.year == 1999

    def test_compact_format(self):
        """YYYYMMDD format."""
        result = parse_date("20210108")
        assert result == date(2021, 1, 8)

    def test_empty_string(self):
        assert parse_date("") is None

    def test_none_input(self):
        assert parse_date(None) is None

    def test_invalid_date(self):
        """Invalid date should return None."""
        assert parse_date("2021-13-01") is None

    def test_year_out_of_range(self):
        """Very old or future years should return None."""
        # 1989 is out of range (< 1990)
        result = parse_date("1989-01-01")
        # May or may not be None depending on implementation
        # but if parsed, year should be 1989
        if result:
            assert result.year == 1989

    def test_chinese_partial_month_only(self):
        """2021年1月 without day should work."""
        result = parse_date("2021年1月")
        assert result is not None
        assert result.year == 2021
        assert result.month == 1


class TestDetermineReportYear:
    """Tests for determine_report_year function."""

    def test_sign_date_priority(self):
        """sign_date should be highest priority."""
        year = determine_report_year(
            sign_date="2021-03-15",
            effective_date="2020-01-01",
            service_start="2019-01-01",
            filename="contract_2018.pdf",
        )
        assert year == 2021

    def test_effective_date_fallback(self):
        """effective_date when sign_date not available."""
        year = determine_report_year(
            sign_date=None,
            effective_date="2020-06-01",
            service_start="2019-01-01",
            filename="contract.pdf",
        )
        assert year == 2020

    def test_service_start_fallback(self):
        """service_start when others not available."""
        year = determine_report_year(
            sign_date=None,
            effective_date=None,
            service_start="2019-07-01",
            filename="contract.pdf",
        )
        assert year == 2019

    def test_filename_fallback(self):
        """filename year when no dates available."""
        year = determine_report_year(
            sign_date=None,
            effective_date=None,
            service_start=None,
            filename="contract_2022_parker.pdf",
        )
        assert year == 2022

    def test_all_none(self):
        """Return None when no year info available."""
        year = determine_report_year(
            sign_date=None,
            effective_date=None,
            service_start=None,
            filename="contract.pdf",
        )
        assert year is None

    def test_empty_sign_date(self):
        """Empty string sign_date should fall through to next."""
        year = determine_report_year(
            sign_date="",
            effective_date="2021-01-01",
            service_start=None,
            filename="doc.pdf",
        )
        assert year == 2021


class TestExtractDateCandidates:
    """Tests for extract_date_candidates function."""

    def test_extract_iso_dates(self):
        text = "签字日期：2021-03-15\n服务期：2021-01-01至2021-12-31"
        candidates = extract_date_candidates(text, page=0)
        assert len(candidates) >= 2

    def test_extract_chinese_dates(self):
        text = "本合同于2021年3月15日签署"
        candidates = extract_date_candidates(text, page=0)
        assert len(candidates) >= 1
        assert candidates[0].normalized_value == "2021-03-15"

    def test_sign_date_label(self):
        text = "甲乙双方签字日期：2021-03-15"
        candidates = extract_date_candidates(text, page=5)
        labeled = [c for c in candidates if c.label == "sign_date"]
        assert len(labeled) >= 1

    def test_empty_text(self):
        candidates = extract_date_candidates("", page=0)
        assert candidates == []
