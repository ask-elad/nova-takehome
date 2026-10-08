"""Unit tests for nova/money.py — glossary §Amounts."""
from __future__ import annotations

from decimal import Decimal

import pytest

from nova.money import CannotDetermine, inr_to_usd, round_half_up


class TestRoundHalfUp:
    def test_rounds_half_up_positive(self):
        assert round_half_up(Decimal("1.005"), 2) == Decimal("1.01")

    def test_rounds_half_up_tie_at_cent(self):
        # 2.675 → 2.68 (not banker's 2.68 either way; just ensures half-up)
        assert round_half_up(Decimal("2.675"), 2) == Decimal("2.68")

    def test_rounds_half_up_negative_away_from_zero(self):
        assert round_half_up(Decimal("-1.005"), 2) == Decimal("-1.01")

    def test_no_rounding_when_already_exact(self):
        assert round_half_up(Decimal("1612.29"), 2) == Decimal("1612.29")

    def test_accepts_string_input(self):
        assert round_half_up("5235.085", 2) == Decimal("5235.09")

    def test_zero_places(self):
        assert round_half_up(Decimal("1.5"), 0) == Decimal("2")


class TestInrToUsd:
    FX = {"2032-07": Decimal("83.50"), "2032-08": Decimal("83.75")}

    def test_converts_once_per_finding(self):
        # 100000 INR @ 83.50 → 1197.60 (rounded half-up)
        assert inr_to_usd(Decimal("100000"), "2032-07-15", self.FX) == Decimal("1197.60")

    def test_rounds_half_up_at_cents(self):
        # 83.505 at fx 1.00 would round to 83.51; use real fx row
        amount = Decimal("83.505")
        assert inr_to_usd(amount, "2032-07-01", {"2032-07": Decimal("1")}) == Decimal("83.51")

    def test_missing_month_raises_cannot_determine(self):
        with pytest.raises(CannotDetermine):
            inr_to_usd(Decimal("1000"), "2032-09-01", self.FX)

    def test_month_boundary(self):
        # Last day of month uses that month's fx
        assert inr_to_usd(Decimal("83500"), "2032-07-31", self.FX) == Decimal("1000.00")
        # First day of next month uses the next month's fx
        assert inr_to_usd(Decimal("83750"), "2032-08-01", self.FX) == Decimal("1000.00")
