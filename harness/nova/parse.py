"""Tolerant date/amount parsing (audit B3).

One parser per primitive, used by rules so a single bad extraction doesn't
raise `ValueError` and drop a whole batch. Dates accept ISO, D/M/Y, M/D/Y
when the day is over 12 (unambiguous US order), and month names. Amounts
accept commas, currency symbols and codes.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

_MONTHS = {m: i for i, ms in enumerate(
    [["january", "jan"], ["february", "feb"], ["march", "mar"],
     ["april", "apr"], ["may"], ["june", "jun"], ["july", "jul"],
     ["august", "aug"], ["september", "sep"], ["october", "oct"],
     ["november", "nov"], ["december", "dec"]], start=1) for m in ms}

_MONEY_CLEAN = re.compile(r"[\s,$£€₹]|\b(USD|INR|EUR|GBP|JPY|AUD|CAD)\b", re.IGNORECASE)


def parse_amount(s: object) -> Decimal:
    """Return a Decimal from a loose numeric string.

    Accepts "1,234.56", "$1,234.56", "USD 1,234.56", "1234". Raises
    InvalidOperation when nothing numeric is left.
    """
    if isinstance(s, (int, float, Decimal)):
        return Decimal(str(s))
    text = str(s or "").strip()
    cleaned = _MONEY_CLEAN.sub("", text)
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise InvalidOperation(f"not a number: {s!r}") from e


def try_amount(s: object, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """parse_amount or `default` on failure. Never raises."""
    try:
        return parse_amount(s)
    except (InvalidOperation, TypeError, ValueError):
        return default


_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTHNAME_RE = re.compile(
    r"^(?P<d>\d{1,2})\s+(?P<m>[A-Za-z]+)\s+(?P<y>\d{4})$"
)
_MONTHNAME_US_RE = re.compile(
    r"^(?P<m>[A-Za-z]+)\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})$"
)


def parse_date(s: object) -> Optional[str]:
    """Return an ISO ``YYYY-MM-DD`` from a loose date string, or None.

    Accepts ISO, D/M/Y, M/D/Y when day > 12, "17 July 2030", "July 17,
    2030". Never raises.
    """
    if s is None:
        return None
    text = str(s).strip()
    if not text:
        return None
    m = _ISO_RE.match(text)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = _SLASH_RE.match(text)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        # Unambiguous: day > 12 forces one order.
        if a > 12 and b <= 12:
            d, mo = a, b                 # D/M/Y
        elif b > 12 and a <= 12:
            d, mo = b, a                 # M/D/Y (US)
        else:
            d, mo = a, b                 # Default to D/M/Y
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    for pat in (_MONTHNAME_RE, _MONTHNAME_US_RE):
        m = pat.match(text)
        if m:
            mo = _MONTHS.get(m["m"].lower())
            if mo is None:
                return None
            try:
                return date(int(m["y"]), mo, int(m["d"])).isoformat()
            except ValueError:
                return None
    return None
