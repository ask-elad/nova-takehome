"""Tests for the tolerant date/amount parsers (audit B3) and the
end-to-end guarantee that one bad fact doesn't crash the batch."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pytest

from nova.parse import parse_amount, parse_date, try_amount


# ---------------------------------------------------------------------------
# parse_amount
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("inp,expected", [
    ("1234.56", Decimal("1234.56")),
    ("1,234.56", Decimal("1234.56")),
    ("$1,234.56", Decimal("1234.56")),
    ("USD 1,234.56", Decimal("1234.56")),
    ("1,234.56 INR", Decimal("1234.56")),
    ("(42.10)", Decimal("-42.10")),
    ("-15.00", Decimal("-15.00")),
])
def test_parse_amount_tolerant(inp, expected):
    assert parse_amount(inp) == expected


def test_parse_amount_raises_on_junk():
    with pytest.raises(InvalidOperation):
        parse_amount("n/a")


def test_try_amount_never_raises():
    assert try_amount("n/a") is None
    assert try_amount("—") is None
    assert try_amount("1,000.00") == Decimal("1000.00")


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("inp,expected", [
    ("2031-04-03", "2031-04-03"),
    ("17/07/2030", "2030-07-17"),       # D/M/Y, day > 12 is unambiguous
    ("03/17/2030", "2030-03-17"),       # M/D/Y (US), day > 12
    ("17 July 2030", "2030-07-17"),
    ("July 17, 2030", "2030-07-17"),
    ("Jul 17, 2030", "2030-07-17"),
    ("17 Jul 2030", "2030-07-17"),
])
def test_parse_date_tolerant(inp, expected):
    assert parse_date(inp) == expected


def test_parse_date_rejects_junk():
    assert parse_date("tomorrow") is None
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date("2031-13-01") is None  # invalid month


# ---------------------------------------------------------------------------
# Verify still accepts US M/D/Y when the day is over 12 (audit B3)
# ---------------------------------------------------------------------------

def test_verify_accepts_us_date_when_day_over_12():
    """A line like 'Mar 17, 2030' or '03/17/2030' passes verification
    against ISO 2030-03-17."""
    from nova.verify import _date_variants
    variants = set(_date_variants("2030-03-17"))
    assert "2030-03-17" in variants
    assert "03/17/2030" in variants
    assert "3/17/2030" in variants
    assert "Mar 17, 2030" in variants


def test_verify_us_mdy_variants_only_when_day_over_12():
    """M/D/Y variants are only emitted when the day > 12 (unambiguous)."""
    from nova.verify import _date_variants
    unambiguous = set(_date_variants("2030-03-17"))
    assert "03/17/2030" in unambiguous
    ambiguous = set(_date_variants("2030-03-04"))
    assert "04/03/2030" in ambiguous   # D/M/Y of day=4,month=3 (always)
    assert "03/04/2030" not in ambiguous  # M/D/Y variant not added
