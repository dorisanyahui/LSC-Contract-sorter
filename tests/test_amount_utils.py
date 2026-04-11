"""Tests for amount_utils module."""
import pytest

from src.utils.amount_utils import (
    normalize_amount,
    validate_amount_range,
    extract_amount_candidates,
    ocr_digit_fix,
)

AMOUNT_RANGES = {
    "annual_maintenance_fee": [1000, 200000],
    "tax_included_amount": [1000, 200000],
    "tax_excluded_amount": [1000, 200000],
    "contract_total_amount": [1000, 200000],
}


class TestNormalizeAmount:
    """Tests for normalize_amount function."""

    def test_comma_separated_thousands(self):
        assert normalize_amount("6,750") == 6750.0

    def test_comma_separated_decimal(self):
        assert normalize_amount("33,750.00") == 33750.0

    def test_ocr_error_O_for_0(self):
        """8OOO should be recognized as 8000 after OCR fix."""
        result = normalize_amount("8OOO")
        assert result == 8000.0

    def test_ocr_error_O_for_0_partial(self):
        """675O should be recognized as 6750 after OCR fix."""
        result = normalize_amount("675O")
        assert result == 6750.0

    def test_plain_integer(self):
        assert normalize_amount("12000") == 12000.0

    def test_decimal(self):
        assert normalize_amount("5500.50") == 5500.50

    def test_with_yuan_symbol(self):
        result = normalize_amount("¥6,750")
        assert result == 6750.0

    def test_with_full_width_comma(self):
        result = normalize_amount("6，750")
        assert result == 6750.0

    def test_wan_unit(self):
        """3.375万 should be 33750."""
        result = normalize_amount("3.375万")
        assert result == 33750.0

    def test_none_input(self):
        assert normalize_amount("") is None
        assert normalize_amount(None) is None

    def test_small_number(self):
        assert normalize_amount("100") == 100.0

    def test_large_number(self):
        assert normalize_amount("1,234,567.89") == 1234567.89


class TestOCRDigitFix:
    """Tests for ocr_digit_fix function."""

    def test_O_to_0(self):
        result = ocr_digit_fix("8OOO")
        assert result == "8000"

    def test_partial_fix(self):
        result = ocr_digit_fix("675O")
        assert result == "6750"

    def test_no_change_needed(self):
        result = ocr_digit_fix("12345")
        assert result == "12345"


class TestValidateAmountRange:
    """Tests for validate_amount_range function."""

    def test_valid_amount(self):
        assert validate_amount_range(6750, "annual_maintenance_fee", AMOUNT_RANGES) is True

    def test_below_minimum(self):
        assert validate_amount_range(999, "annual_maintenance_fee", AMOUNT_RANGES) is False

    def test_above_maximum(self):
        assert validate_amount_range(300000, "annual_maintenance_fee", AMOUNT_RANGES) is False

    def test_at_minimum(self):
        assert validate_amount_range(1000, "annual_maintenance_fee", AMOUNT_RANGES) is True

    def test_at_maximum(self):
        assert validate_amount_range(200000, "annual_maintenance_fee", AMOUNT_RANGES) is True

    def test_unknown_field_name_defaults_to_builtin_range(self):
        """Unknown field names fall back to [1000, 200000] default range."""
        # 999 < 1000, so fails the default range
        assert validate_amount_range(999, "unknown_field", {}) is False
        # 5000 is within [1000, 200000] default
        assert validate_amount_range(5000, "unknown_field", {}) is True

    def test_tax_included_valid(self):
        assert validate_amount_range(33750, "tax_included_amount", AMOUNT_RANGES) is True

    def test_zero_is_invalid(self):
        assert validate_amount_range(0, "annual_maintenance_fee", AMOUNT_RANGES) is False


class TestExtractAmountCandidates:
    """Tests for extract_amount_candidates function."""

    def test_extract_basic_amount(self):
        text = "年度维护费：6,750元"
        candidates = extract_amount_candidates(text, page=0)
        assert len(candidates) > 0
        values = [c.value for c in candidates]
        assert any("6,750" in v or "6750" in v for v in values)

    def test_extract_with_label(self):
        text = "年度维护费 33,750.00 元\n合同总金额 38,812.50 元"
        candidates = extract_amount_candidates(text, page=1)
        assert len(candidates) >= 2

    def test_skip_small_amounts(self):
        """Amounts less than 100 should be skipped."""
        text = "序号 1 数量 2 单价 50"
        candidates = extract_amount_candidates(text, page=0)
        # Should not find amounts < 100
        for c in candidates:
            val = float(c.normalized_value) if c.normalized_value else 0
            assert val >= 100
