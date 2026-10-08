"""Money arithmetic for the rules engine.

Everything is Decimal. The only rounding is round_half_up to a given number
of decimal places. INR amounts are converted to USD once per finding using
the FX row for the invoice-date calendar month, taken from the contract's
Annex F. A month missing from Annex F raises CannotDetermine; the caller
turns that into a cannot_determine item.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Union

Number = Union[Decimal, str, int]


class CannotDetermine(Exception):
    """Raised when a required FX row (or similar fact) is missing."""


def round_half_up(x: Number, places: int) -> Decimal:
    """Round half-up (ties away from zero) to *places* decimal places."""
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    q = Decimal(1).scaleb(-places)  # 10 ** -places as a Decimal
    return d.quantize(q, rounding=ROUND_HALF_UP)


def _month_of(iso_date: str) -> str:
    # ISO "YYYY-MM-DD" → "YYYY-MM". No parsing cost, no validation beyond length.
    return iso_date[:7]


def inr_to_usd(
    amount_inr: Number,
    invoice_date: str,
    fx: Mapping[str, Number],
) -> Decimal:
    """Convert an INR amount to USD using the Annex F rate for the invoice month.

    Rounds half-up to cents. Raises CannotDetermine if the month is absent.
    """
    month = _month_of(invoice_date)
    if month not in fx:
        raise CannotDetermine(f"no FX row for {month}")
    rate = fx[month]
    rate_d = rate if isinstance(rate, Decimal) else Decimal(str(rate))
    amount_d = amount_inr if isinstance(amount_inr, Decimal) else Decimal(str(amount_inr))
    return round_half_up(amount_d / rate_d, 2)
