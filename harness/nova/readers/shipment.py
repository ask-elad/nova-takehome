"""Shipment reader: AWB and Dangerous Goods declarations."""
from __future__ import annotations

from nova.llm import LLMClient
from nova.mailbox import DocRecord
from nova.readers import ReadResult, read_doc
from nova.schemas import ShipmentDoc

prompt_version = "shipment-1"

_INSTRUCTIONS = (
    "This document is an Air Waybill (AWB) or a Dangerous Goods declaration.\n"
    "Fill the ShipmentDoc schema.\n"
    "\n"
    "Rules:\n"
    "- `kind`: \"awb\" or \"dg_declaration\".\n"
    "- `awb`: the AWB number as printed, cited to its line.\n"
    "- `master_or_house`: \"master\" or \"house\" if the document says so.\n"
    "- Dates: ISO YYYY-MM-DD.\n"
    "- Weights: plain decimal strings in kilograms.\n"
    "- For DG declarations fill `un_numbers` (each as \"UN####\") and set\n"
    "  `refrigerant_only=true` with its ref iff the declaration states that only\n"
    "  the refrigerant (e.g. dry ice) is dangerous — meaning the shipment\n"
    "  contents themselves are not dangerous goods."
)


def read(client: LLMClient, record: DocRecord) -> ReadResult:
    return read_doc(
        client, record, ShipmentDoc,
        tier="fast", purpose="read_shipment", prompt_version=prompt_version,
        instructions=_INSTRUCTIONS, max_tokens=2048,
    )
