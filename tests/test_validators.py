"""Tests for pipeline validators."""
import pytest

from src.pipeline.validators import (
    validate_company,
    validate_date,
    validate_amount,
    validate_tax_rate,
    careful_check_amount,
)
from src.models.schema import Candidate
from src.models.enums import FieldSource

VENDOR_LIST = ["上海莱升", "莱升信息", "泛纬软件", "LICENSE CONSULTING", "LSC"]

AMOUNT_RANGES = {
    "annual_maintenance_fee": [1000, 200000],
    "tax_included_amount": [1000, 200000],
}


class TestValidateCompany:
    """Tests for validate_company function."""

    def test_valid_company(self):
        is_valid, reason = validate_company("派克汉尼汾（中国）有限公司", VENDOR_LIST)
        assert is_valid is True
        assert reason == ""

    def test_vendor_name_blocked(self):
        is_valid, reason = validate_company("上海莱升信息科技有限公司", VENDOR_LIST)
        assert is_valid is False
        assert "vendor blocklist" in reason.lower() or "上海莱升" in reason

    def test_partial_vendor_name_blocked(self):
        is_valid, reason = validate_company("LSC技术公司", VENDOR_LIST)
        assert is_valid is False

    def test_too_short(self):
        is_valid, reason = validate_company("公司", VENDOR_LIST)
        assert is_valid is False
        assert "short" in reason.lower() or "4" in reason

    def test_empty_string(self):
        is_valid, reason = validate_company("", VENDOR_LIST)
        assert is_valid is False

    def test_template_text_blocked(self):
        """Long text with 注意: should be rejected as template text."""
        template_text = "请注意：" + "X" * 60
        is_valid, reason = validate_company(template_text, VENDOR_LIST)
        assert is_valid is False


class TestValidateDate:
    """Tests for validate_date function."""

    def test_valid_iso_date(self):
        is_valid, reason = validate_date("2021-01-08")
        assert is_valid is True

    def test_valid_chinese_date(self):
        is_valid, reason = validate_date("2021年1月8日")
        assert is_valid is True

    def test_empty_date(self):
        is_valid, reason = validate_date("")
        assert is_valid is False

    def test_invalid_format(self):
        is_valid, reason = validate_date("not a date")
        assert is_valid is False

    def test_year_out_of_range_future(self):
        is_valid, reason = validate_date("2050-01-01")
        assert is_valid is False

    def test_year_out_of_range_past(self):
        is_valid, reason = validate_date("1985-01-01")
        assert is_valid is False


class TestValidateAmount:
    """Tests for validate_amount function."""

    def test_valid_amount(self):
        is_valid, reason = validate_amount(6750.0, "annual_maintenance_fee", AMOUNT_RANGES)
        assert is_valid is True

    def test_amount_too_low(self):
        is_valid, reason = validate_amount(999.0, "annual_maintenance_fee", AMOUNT_RANGES)
        assert is_valid is False

    def test_amount_too_high(self):
        is_valid, reason = validate_amount(300000.0, "annual_maintenance_fee", AMOUNT_RANGES)
        assert is_valid is False

    def test_zero_amount(self):
        is_valid, reason = validate_amount(0.0, "annual_maintenance_fee", AMOUNT_RANGES)
        assert is_valid is False

    def test_negative_amount(self):
        is_valid, reason = validate_amount(-100.0, "annual_maintenance_fee", AMOUNT_RANGES)
        assert is_valid is False

    def test_none_amount(self):
        is_valid, reason = validate_amount(None, "annual_maintenance_fee", AMOUNT_RANGES)
        assert is_valid is False


class TestValidateTaxRate:
    """Tests for validate_tax_rate function."""

    def test_valid_13_percent(self):
        is_valid, reason = validate_tax_rate("13%")
        assert is_valid is True

    def test_valid_6_percent(self):
        is_valid, reason = validate_tax_rate("6%")
        assert is_valid is True

    def test_valid_without_percent(self):
        is_valid, reason = validate_tax_rate("13")
        assert is_valid is True

    def test_valid_decimal(self):
        is_valid, reason = validate_tax_rate("13.0%")
        assert is_valid is True

    def test_empty_string(self):
        is_valid, reason = validate_tax_rate("")
        assert is_valid is False

    def test_invalid_format(self):
        is_valid, reason = validate_tax_rate("not a rate")
        assert is_valid is False

    def test_out_of_range(self):
        is_valid, reason = validate_tax_rate("50%")
        assert is_valid is False


class TestCarefulCheckAmount:
    """Tests for careful_check_amount function."""

    def _make_candidate(self, value: str, normalized: str, label: str = "amount_generic") -> Candidate:
        return Candidate(
            value=value,
            normalized_value=normalized,
            label=label,
            page=0,
            score=0.7,
            source=FieldSource.OCR,
        )

    def test_valid_primary_value_returned(self):
        candidates = [self._make_candidate("6750", "6750")]
        result = careful_check_amount(6750.0, candidates, "annual_maintenance_fee", AMOUNT_RANGES)
        assert result == 6750.0

    def test_invalid_primary_finds_alternative(self):
        """When primary is invalid, should find a valid candidate."""
        candidates = [
            self._make_candidate("999", "999"),    # invalid (below range)
            self._make_candidate("6750", "6750"),  # valid
        ]
        result = careful_check_amount(999.0, candidates, "annual_maintenance_fee", AMOUNT_RANGES)
        assert result == 6750.0

    def test_all_invalid_returns_none(self):
        """When all candidates are invalid, return None."""
        candidates = [
            self._make_candidate("50", "50"),   # below range
            self._make_candidate("100", "100"),  # below range
        ]
        result = careful_check_amount(50.0, candidates, "annual_maintenance_fee", AMOUNT_RANGES)
        assert result is None
