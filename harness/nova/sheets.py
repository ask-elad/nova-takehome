"""Parse spreadsheet rows using a SheetMap.

The mailbox text layer renders each XLSX sheet as one page: the header row is
on the SheetMap's ref line, data rows follow. Cells are joined by " | ".
`rows(pages, sheet_map)` returns a list of dicts keyed by the field names in
SheetMap.columns. Each row also carries `_page` and `_line` so callers can
cite it in evidence.
"""
from __future__ import annotations

from typing import Any

from nova.schemas import SheetMap

SEP = " | "


def rows(pages: list[str], sheet_map: SheetMap) -> list[dict[str, Any]]:
    page_idx = sheet_map.sheet_number - 1
    if not (0 <= page_idx < len(pages)):
        return []
    lines = pages[page_idx].splitlines()

    # Audit B6: the header row may not be the first line. Search the first 15
    # rows for the row whose cells best match the column labels, falling back
    # to the ref line.
    want_labels = list(sheet_map.columns.values())
    header_line = _find_header(lines, want_labels, hint=sheet_map.ref.line, window=15)
    if header_line is None:
        header_line = sheet_map.ref.line
    if not (1 <= header_line <= len(lines)):
        return []
    header_cells = [c.strip() for c in lines[header_line - 1].split(SEP)]
    idx_of = {label: i for i, label in enumerate(header_cells)}

    # Audit B6: partial mappings keep their rows. A field whose header isn't
    # present is simply left blank per-row (never a reason to drop the sheet).
    present_fields: dict[str, int] = {
        field: idx_of[label]
        for field, label in sheet_map.columns.items()
        if label in idx_of
    }
    if not present_fields:
        return []

    out: list[dict[str, Any]] = []
    for line_no in range(header_line + 1, len(lines) + 1):
        parts = [p.strip() for p in lines[line_no - 1].split(SEP)]
        if not any(parts):
            continue
        row: dict[str, Any] = {"_page": sheet_map.sheet_number, "_line": line_no}
        for field, i in present_fields.items():
            val = parts[i] if i < len(parts) else ""
            # Audit B6: normalise AWBs (strip and uppercase) so a mix of
            # casings/spaces across tracking/AWB/invoice still joins.
            if field == "awb":
                val = "".join(val.split()).upper()
            row[field] = val
        out.append(row)
    return out


def _find_header(lines: list[str], want_labels: list[str], hint: int, window: int) -> int | None:
    """Return the 1-indexed line number whose cells best match *want_labels*.

    Prefer the ``hint`` line when it matches at all; otherwise scan the first
    *window* lines and pick the one with the most matches. Return None if no
    line contains any wanted label.
    """
    want = {w for w in want_labels if w}
    best = (0, None)
    scan_end = min(window, len(lines))
    hint_idx = hint - 1
    if 0 <= hint_idx < len(lines):
        cells = {c.strip() for c in lines[hint_idx].split(SEP)}
        if want and want.issubset(cells):
            return hint
    for i in range(scan_end):
        cells = {c.strip() for c in lines[i].split(SEP)}
        hits = len(want & cells)
        if hits > best[0]:
            best = (hits, i + 1)
    return best[1]
