"""Verify that every extracted value appears on the line it cites.

verify_object(obj, pages) walks a schema instance and returns a list of
VerifyFailure objects for every value that cannot be found on its cited line.

Value matching rules (from the task spec):
  Money   – compare after removing thousands-separator commas and currency codes.
  Dates   – accept ISO (YYYY-MM-DD), DD/MM/YYYY, or month-name forms on the line.
  Strings – case-insensitive substring match.
  Percentage values are stored as plain numbers (e.g. "20.16" not "20.16%");
  the match succeeds because "20.16" is a substring of "20.16%".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, get_origin

from pydantic import BaseModel

from nova.schemas import Ref, Val
from nova.textlayer import norm


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(r'\b(USD|INR|EUR|GBP)\b')
_MONEY_RE = re.compile(r'^[\d]+\.\d+$')
_ISO_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_MONTH_RE = re.compile(r'^\d{4}-\d{2}$')
_NUMERIC_RE = re.compile(r'^\d+(\.\d+)?$')

_MONTH_NAMES = {
    1: ["january", "jan"],
    2: ["february", "feb"],
    3: ["march", "mar"],
    4: ["april", "apr"],
    5: ["may"],
    6: ["june", "jun"],
    7: ["july", "jul"],
    8: ["august", "aug"],
    9: ["september", "sep"],
    10: ["october", "oct"],
    11: ["november", "nov"],
    12: ["december", "dec"],
}


def _strip_money(s: str) -> str:
    """Remove thousands-separator commas and currency codes."""
    s = s.replace(",", "")
    s = _CURRENCY_RE.sub("", s)
    return " ".join(s.split())


def _date_variants(iso: str) -> list[str]:
    """Return every plausible printed form of an ISO date.

    Accepts ISO (YYYY-MM-DD), D/M/Y, M/D/Y (when the day is over 12 to
    disambiguate from D/M/Y), month-name forms. Audit B3.
    """
    variants = [iso]
    try:
        y, m, d = iso.split("-")
        di, mi = int(d), int(m)
        variants.append(f"{d}/{m}/{y}")               # 17/07/2030 (D/M/Y)
        variants.append(f"{di}/{mi}/{y}")             # 7/4/2030 (no zero-pad D/M/Y)
        # US M/D/Y variants: safe to accept when the day > 12 (unambiguous)
        if di > 12:
            variants.append(f"{m}/{d}/{y}")           # 07/17/2030
            variants.append(f"{mi}/{di}/{y}")         # 7/17/2030
        dt = date(int(y), int(m), int(d))
        variants.append(dt.strftime("%d %B %Y"))      # 17 July 2030
        variants.append(dt.strftime("%-d %B %Y"))     # 17 July 2030 (no zero-pad)
        variants.append(dt.strftime("%d %b %Y"))      # 17 Jul 2030
        variants.append(dt.strftime("%-d %b %Y"))     # 17 Jul 2030 (no zero-pad)
        variants.append(dt.strftime("%B %d, %Y"))     # July 17, 2030
        variants.append(dt.strftime("%B %-d, %Y"))    # July 17, 2030 (no zero-pad)
        variants.append(dt.strftime("%b %d, %Y"))     # Jul 17, 2030
        variants.append(dt.strftime("%b %-d, %Y"))    # Jul 17, 2030 (no zero-pad)
    except (ValueError, AttributeError):
        pass
    return variants


def _number_whole_token(value: str, text: str) -> bool:
    """True iff numeric *value* appears as a whole token in *text*.

    Fails if the match is immediately preceded by a digit, or followed by a
    digit or by a decimal point and a digit (e.g. "340.1" must not match
    "340.12", and "44" must not match "144").
    """
    pattern = r'(?<!\d)' + re.escape(value) + r'(?!\d|\.\d)'
    return bool(re.search(pattern, text))


def _date_whole_token(variant: str, text: str) -> bool:
    """True iff date *variant* appears as a whole token in *text* (case-insensitive)."""
    return bool(re.search(r'\b' + re.escape(variant) + r'\b', text, re.IGNORECASE))


def _value_on_line(value: str, line: str) -> bool:
    """Return True iff *value* can be found in *line* under the matching rules."""
    norm_line = norm(line)
    norm_val = norm(value)

    # ISO date: whole-token check on each printed variant
    if _ISO_DATE_RE.match(norm_val):
        for variant in _date_variants(norm_val):
            if _date_whole_token(variant, norm_line):
                return True
        return False

    # Strip thousands-separator commas and currency codes for money matching
    stripped_val = _strip_money(norm_val)
    stripped_line = _strip_money(norm_line)

    # Numeric values: whole-token match (after stripping) to avoid partial hits
    if stripped_val and _NUMERIC_RE.match(stripped_val):
        return _number_whole_token(stripped_val, stripped_line)

    # Strings and codes: case-insensitive substring match
    if norm_val.lower() in norm_line.lower():
        return True
    if stripped_val and stripped_val in stripped_line:
        return True

    return False


# ---------------------------------------------------------------------------
# Failure record
# ---------------------------------------------------------------------------

@dataclass
class VerifyFailure:
    path: str
    value: str
    ref: Ref
    line_text: str
    reason: str

    def __str__(self) -> str:
        return (
            f"{self.path}: {self.value!r} "
            f"(p{self.ref.page} L{self.ref.line}) – {self.reason} | line: {self.line_text!r}"
        )


# ---------------------------------------------------------------------------
# Line lookup
# ---------------------------------------------------------------------------

def _get_line(pages: list[str], ref: Ref) -> str | None:
    """Return the text of the cited line, or None if the ref is out of range."""
    if not (1 <= ref.page <= len(pages)):
        return None
    page_lines = pages[ref.page - 1].split("\n")
    if not (1 <= ref.line <= len(page_lines)):
        return None
    if ref.line_end is not None:
        end = min(ref.line_end, len(page_lines))
        return " ".join(page_lines[ref.line - 1 : end])
    return page_lines[ref.line - 1]


# ---------------------------------------------------------------------------
# Core walker
# ---------------------------------------------------------------------------

def verify_object(
    obj: Any,
    pages: list[str],
    path: str = "",
) -> list[VerifyFailure]:
    """Walk *obj* and return failures for every value not found on its cited line.

    Rules:
    - Val instances: verify Val.value against Val.ref.
    - Row-level BaseModel instances (those with a ``ref: Ref`` field):
      verify each plain string field and each plain string in list[str] fields
      against the row's ref.
    - Recursively descend into nested BaseModel instances and lists.
    - Ref, bool, int, float, None: skip.
    """
    return list(_walk(obj, pages, path))


def _walk(obj: Any, pages: list[str], path: str):
    if obj is None or isinstance(obj, (bool, int, float)):
        return

    if isinstance(obj, Val):
        line = _get_line(pages, obj.ref)
        if line is None:
            yield VerifyFailure(
                path, obj.value, obj.ref, "",
                f"page {obj.ref.page} line {obj.ref.line} does not exist "
                f"(doc has {len(pages)} page(s))",
            )
        elif not _value_on_line(obj.value, line):
            yield VerifyFailure(path, obj.value, obj.ref, line, "value not found on line")
        return

    if isinstance(obj, Ref):
        return

    if isinstance(obj, str):
        return

    if isinstance(obj, BaseModel):
        # Collect row-level ref (if any) for checking plain string fields
        row_ref: Ref | None = None
        model_fields = type(obj).model_fields
        fields_with_ref = {
            n for n, f in model_fields.items()
            if f.annotation is Ref or (
                hasattr(f.annotation, "__origin__") is False
                and isinstance(getattr(obj, n, None), Ref)
            )
        }
        if "ref" in fields_with_ref:
            candidate = getattr(obj, "ref", None)
            if isinstance(candidate, Ref):
                row_ref = candidate

        for field_name, field_val in obj:
            field_path = f"{path}.{field_name}" if path else field_name

            if isinstance(field_val, Ref):
                continue
            if isinstance(field_val, Val):
                yield from _walk(field_val, pages, field_path)
                continue
            if isinstance(field_val, BaseModel):
                yield from _walk(field_val, pages, field_path)
                continue
            if isinstance(field_val, bool) or field_val is None:
                continue
            if isinstance(field_val, (int, float)):
                continue

            # Skip Literal-annotated fields (controlled vocabulary, not extracted text)
            field_info = model_fields.get(field_name)
            if field_info and get_origin(field_info.annotation) is Literal:
                continue

            # Plain string field on a row model
            if isinstance(field_val, str) and field_val and row_ref is not None:
                line = _get_line(pages, row_ref)
                if line is not None and not _value_on_line(field_val, line):
                    yield VerifyFailure(
                        field_path, field_val, row_ref, line,
                        "value not found on row line",
                    )
                continue

            # list field
            if isinstance(field_val, list):
                for i, item in enumerate(field_val):
                    item_path = f"{field_path}[{i}]"
                    if isinstance(item, BaseModel):
                        yield from _walk(item, pages, item_path)
                    elif isinstance(item, str) and item and row_ref is not None:
                        line = _get_line(pages, row_ref)
                        if line is not None and not _value_on_line(item, line):
                            yield VerifyFailure(
                                item_path, item, row_ref, line,
                                "value not found on row line",
                            )

            # dict field (e.g. SheetMap.columns) – check string values against row ref
            if isinstance(field_val, dict):
                for k, v in field_val.items():
                    item_path = f"{field_path}.{k}"
                    if isinstance(v, str) and v and row_ref is not None:
                        line = _get_line(pages, row_ref)
                        if line is not None and not _value_on_line(v, line):
                            yield VerifyFailure(
                                item_path, v, row_ref, line,
                                "value not found on row line",
                            )
                    else:
                        yield from _walk(v, pages, item_path)
        return

    if isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _walk(item, pages, f"{path}[{i}]")
        return

    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, pages, f"{path}.{k}")
