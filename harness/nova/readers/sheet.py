"""Sheet reader: maps spreadsheet header labels to our field names.

The reader never reads data rows — nova/sheets.py parses them from the header
mapping produced here.
"""
from __future__ import annotations

from nova.llm import LLMClient
from nova.mailbox import DocRecord
from nova.readers import ReadResult, read_doc
from nova.schemas import SheetMap

prompt_version = "sheet-1"

_INSTRUCTIONS = (
    "This document is a spreadsheet rendered page-by-sheet, one row per line.\n"
    "For sheet 1, identify the header row and map the printed column labels to\n"
    "our field names. Fill the SheetMap schema.\n"
    "\n"
    "Rules:\n"
    "- `kind`: \"tracking_export\" if the sheet lists shipments with AWB/weight/\n"
    "  dates, \"payment_register\" if it lists invoice payments, otherwise \"other\".\n"
    "- `sheet_number` = 1 (first sheet) unless the document says otherwise.\n"
    "- `columns`: a dict from our field name to the header text exactly as\n"
    "  printed. Common fields:\n"
    "  tracking_export: awb, lane, pickup_date, pieces, actual_weight,\n"
    "                   chargeable_weight, status, delivered_date.\n"
    "  payment_register: invoice, paid_date, amount, method, reference.\n"
    "  Only include fields the header actually shows.\n"
    "- `ref` must point to the header row (page=sheet number, line=header line)."
)


def read(client: LLMClient, record: DocRecord) -> ReadResult:
    return read_doc(
        client, record, SheetMap,
        tier="fast", purpose="read_sheet", prompt_version=prompt_version,
        instructions=_INSTRUCTIONS, max_tokens=1024,
    )
