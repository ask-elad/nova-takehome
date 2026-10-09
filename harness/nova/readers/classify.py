"""Fast classifier: sorts a document into one of the kinds the readers handle."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from nova.llm import LLMClient
from nova.mailbox import DocRecord
from nova.readers import UNTRUSTED_SYSTEM

prompt_version = "classify-1"

DocKind = Literal[
    "contract", "amendment", "invoice", "credit_note", "statement",
    "awb", "dg_declaration", "tracking_export", "payment_register",
    "email", "other",
]


class Classification(BaseModel):
    kind: DocKind
    reason: str   # one short sentence, cited by its own text


_INSTRUCTIONS = (
    "Sort this document into exactly one kind. Use these definitions:\n"
    "- contract: a Master Services Agreement (MSA) or similar signed services agreement.\n"
    "- amendment: a signed amendment that changes a term of an MSA (e.g. a rate).\n"
    "- invoice: a request for payment with charge lines.\n"
    "- credit_note: a document that credits an invoice or period (e.g. rebate credit note).\n"
    "- statement: a statement of account summarising invoices and balances.\n"
    "- awb: an Air Waybill (shipment movement document).\n"
    "- dg_declaration: a Dangerous Goods declaration for a shipment.\n"
    "- tracking_export: a spreadsheet of shipment tracking rows.\n"
    "- payment_register: a spreadsheet of payments made.\n"
    "- email: an .eml message (the top page starts with From/To/Date/Subject).\n"
    "- other: anything else, including notices, rate notices, DG notices, etc."
)


def read(client: LLMClient, record: DocRecord) -> Classification | None:
    """Classify *record* using the fast tier."""
    from nova.readers import read_doc

    result = read_doc(
        client, record, Classification,
        tier="fast", purpose="classify", prompt_version=prompt_version,
        instructions=_INSTRUCTIONS, max_tokens=512, max_doc_lines=40,
    )
    return result.instance
