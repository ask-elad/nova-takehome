"""Billing reader: invoices, credit notes, statements of account."""
from __future__ import annotations

from nova.llm import LLMClient
from nova.mailbox import DocRecord
from nova.readers import ReadResult, read_doc
from nova.schemas import BillingDoc

prompt_version = "billing-4"

_INSTRUCTIONS = (
    "This document is an invoice, credit note or statement of account.\n"
    "Fill the BillingDoc schema from what the document says.\n"
    "\n"
    "Rules:\n"
    "- Each extracted value must appear on the line you cite (use [pN LM]).\n"
    "- Money and rates: plain decimal strings (no currency symbol, no commas, no %).\n"
    "- Dates: ISO YYYY-MM-DD.\n"
    "- `kind`: \"invoice\" | \"credit_note\" | \"statement\".\n"
    "- `issuer`: the issuing party's name as printed in the header.\n"
    "- `currency`: \"USD\", \"INR\" etc., read from the amount column header or totals.\n"
    "- `lines`: one record per charge line. Fill `charge_label` with the\n"
    "  charge description as printed, but strip any trailing parenthetical\n"
    "  cross-reference such as `(ref TE12345678)` or `(ref INV-1)` — these\n"
    "  are back-references to another document, not part of the charge name.\n"
    "  Classify each line into one of the `category` values. A late-fee line\n"
    "  should set `category=\"late_fee\"` and `refers_to_invoice` to the invoice\n"
    "  id it is charged on.\n"
    "- For each line, record `awb`, `lane`, `pickup_date`, `qty`, `unit`, `rate`\n"
    "  and `amount` whenever they are printed; omit a field if the line does not\n"
    "  show it. The `awb` is the FULL waybill number as printed in the line's\n"
    "  waybill column, including any house suffix like `-H1` or `-H2`. Never\n"
    "  strip a house suffix to the master AWB, even when the line mentions the\n"
    "  master in a parenthetical like `(MAWB CA12345678)` — the master is\n"
    "  context, not the shipment id. Two house AWBs under one master are two\n"
    "  different shipments.\n"
    "- A credit note sets `kind=\"credit_note\"`, often has a `credit_type` such as\n"
    "  \"rebate\" or \"improvement\", a `credit_period`, and may list the invoices it\n"
    "  credits in `credited_invoices`.\n"
    "- Billing marks: set `is_copy`, `is_reminder`, `is_for_your_records`, and\n"
    "  `asks_for_payment` according to any banner or stamp (COPY, DUPLICATE, FOR\n"
    "  YOUR RECORDS, REMINDER, etc.) and point `marks_ref` at that line."
)


def read(client: LLMClient, record: DocRecord) -> ReadResult:
    return read_doc(
        client, record, BillingDoc,
        tier="fast", purpose="read_billing", prompt_version=prompt_version,
        instructions=_INSTRUCTIONS, max_tokens=8192,
    )
