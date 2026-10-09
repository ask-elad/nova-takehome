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
    header_line = sheet_map.ref.line
    if not (1 <= header_line <= len(lines)):
        return []
    header_cells = [c.strip() for c in lines[header_line - 1].split(SEP)]
    idx_of = {label: i for i, label in enumerate(header_cells)}

    missing = [label for label in sheet_map.columns.values() if label not in idx_of]
    if missing:
        return []

    out: list[dict[str, Any]] = []
    for line_no in range(header_line + 1, len(lines) + 1):
        parts = [p.strip() for p in lines[line_no - 1].split(SEP)]
        if not any(parts):
            continue
        row: dict[str, Any] = {"_page": sheet_map.sheet_number, "_line": line_no}
        for field, label in sheet_map.columns.items():
            i = idx_of[label]
            row[field] = parts[i] if i < len(parts) else ""
        out.append(row)
    return out
