"""Sheet reader: maps spreadsheet header labels to our field names.

The reader never reads data rows — nova/sheets.py parses them from the header
mapping produced here.
"""
from __future__ import annotations

from nova.llm import LLMClient
from nova.mailbox import DocRecord
from nova.readers import ReadResult, read_doc
from nova.schemas import SheetMap

prompt_version = "sheet-2"

_INSTRUCTIONS = (
    "This document is a spreadsheet rendered page-by-sheet, one row per line.\n"
    "For sheet 1, identify the header row and map the printed column labels to\n"
    "our field names. Fill the SheetMap schema.\n"
    "\n"
    "Rules:\n"
    "- `kind`: \"tracking_export\" if the sheet lists shipments with AWB/dates\n"
    "  and events; \"payment_register\" if it lists invoices paid/scheduled;\n"
    "  otherwise \"other\".\n"
    "- `sheet_number` = 1 (first sheet) unless the document says otherwise.\n"
    "- `columns`: a dict from our field name (the key) to the header text\n"
    "  exactly as printed (the value). Only include fields whose header is\n"
    "  actually present. Use these field-name keys:\n"
    "  tracking_export → awb, event, date, station, reason_code, lane,\n"
    "                    pieces, actual_weight, chargeable_weight,\n"
    "                    pickup_date, delivered_date, status.\n"
    "  payment_register → invoice_id, invoice_date, due_date, amount,\n"
    "                     status, paid_date, method, reference.\n"
    "- `ref` must point to the header row (page=sheet number, line=header line)."
)


def read(client: LLMClient, record: DocRecord) -> ReadResult:
    return read_doc(
        client, record, SheetMap,
        tier="fast", purpose="read_sheet", prompt_version=prompt_version,
        instructions=_INSTRUCTIONS, max_tokens=1024,
    )
