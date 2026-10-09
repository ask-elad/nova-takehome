"""Typed schemas for reader output.

Each document type has a Pydantic model:
  ContractTerms  – MSA and amendments
  BillingDoc     – invoice, credit note, statement
  EmailFacts     – any email
  SheetMap       – tracking export, payment register
  ShipmentDoc    – AWB and DG declaration

Values (money, dates, strings) are wrapped in Val(value, ref) so verify.py
can confirm every extracted value appears on the line it cites.

Row-level models (RateRow, FuelRow, …) carry a single ref for the whole row;
verify.py checks every string field of a row against that ref.

`flatten_schema(schema)` inlines all $defs references so the result is a
valid Messages-API tool input_schema.
"""
from __future__ import annotations

import copy
from typing import Any, Literal, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Core building blocks
# ---------------------------------------------------------------------------

class Ref(BaseModel):
    """Source location: page (1-indexed) and line (1-indexed) within the text layer."""
    page: int
    line: int
    line_end: Optional[int] = None


class Val(BaseModel):
    """A single extracted value with its source line.

    value conventions:
      money / rates  → normalised decimal string, e.g. "5235.09" or "6.69"
      percentage     → decimal string without %, e.g. "20.16"
      date           → ISO YYYY-MM-DD, e.g. "2031-12-17"
      string         → text as printed in the document
    """
    value: str
    ref: Ref


# ---------------------------------------------------------------------------
# ContractTerms sub-models
# ---------------------------------------------------------------------------

class RatePeriod(BaseModel):
    """One named rate period from Annex A header (e.g. P1, P2)."""
    label: str    # "P1"
    start: str    # ISO date "2031-12-17"
    end: str      # ISO date "2032-06-16"
    ref: Ref      # line that defines this period


class RatePeriodRate(BaseModel):
    """One rate entry keyed to a specific rate period."""
    period: Optional[str] = None  # "P1", "P2"; None for amendments with no named period
    rate: str                     # "6.01"


class RateRow(BaseModel):
    """One row of Annex A (express rates table)."""
    lane: str                        # "USE2-INE2"
    band: str                        # "minimum charge"  or  "0-44.5 kg"
    band_min_kg: Optional[float] = None  # None for minimum-charge rows
    band_max_kg: Optional[float] = None  # None for minimum-charge or open-top bands
    is_minimum_charge: bool = False
    rates: list[RatePeriodRate]      # one entry per period; period=None for amendments
    ref: Ref


class FuelRow(BaseModel):
    """One month of Annex C (fuel surcharge)."""
    month: str    # "2031-12"
    rate: str     # percentage value without %, e.g. "20.16"
    ref: Ref


class Accessorial(BaseModel):
    """One row of Annex D (accessorial fees)."""
    code: str                         # "DG"
    label: str                        # "Dangerous goods fee"
    rate: str                         # "284.91"
    basis: str                        # "USD per shipment" – kept as printed
    basis_kind: Literal[
        "per_kg", "per_shipment", "pct_of_freight",
        "per_month", "per_piece", "other",
    ]
    condition: Optional[str] = None   # e.g. "for pickups in September to November"
    months: Optional[list[str]] = None
    ref: Ref


class ChargeCodeAlias(BaseModel):
    """One row of Annex E (charge-code alias table)."""
    code: str           # "FRT"
    label: str          # "Air freight"
    aliases: list[str]  # ["Express freight", "Freight charge"]
    ref: Ref


class RebateTier(BaseModel):
    """One tier row of the volume rebate clause."""
    threshold: str   # "70000.00"  (USD quarterly spend)
    rate: str        # "5"  (percentage)
    ref: Ref


class PromisedCredit(BaseModel):
    """Annual improvement credit or other promised credit (clause 9)."""
    label: str      # "Annual improvement credit"
    rate: Val       # "1.27"  (percentage of qualifying spend)
    due_days: Val   # "60"  (days after anniversary)
    ref: Ref        # the clause line


class FXRow(BaseModel):
    """One month of Annex F (FX rate table)."""
    month: str   # "2031-12"
    rate: str    # "83.50"  (INR per 1 USD)
    ref: Ref


class Schedule1Row(BaseModel):
    """One person row in Schedule 1."""
    name: str
    title: str
    party: str              # "TBX-US"  or  "QMP-US"
    categories: list[str]   # ["rates"]  or  ["waivers", "payment_terms"]
    email: str
    ref: Ref


class MarginStepRow(BaseModel):
    """One row of the handling-margin step-down table."""
    threshold: str   # qualifying-spend threshold, e.g. "500000.00"
    from_pct: str    # margin percentage before step, e.g. "3.0"
    to_pct: str      # margin percentage after step, e.g. "2.5"
    period: str      # period label or description, e.g. "P2"
    ref: Ref


class ReferTo(BaseModel):
    """One document this instrument refers to."""
    name: str            # document name exactly as cited
    ref: Ref             # line where the reference appears
    quote: Optional[Val] = None  # required for cannot_determine items


class KeyClause(BaseModel):
    """A clause the rules engine needs to cite in evidence."""
    number: str    # "3.2"
    topic: str     # "Pricing date"
    ref: Ref


SourceKind = Literal["msa", "amendment", "rate_notice", "annex", "schedule1_email"]


class UnrankedPair(BaseModel):
    """A pair of source kinds the contract declares as unranked in precedence.

    If both members of the pair carry an authorised disagreeing value, the
    rules engine reports a conflict rather than picking a winner.
    """
    a: SourceKind
    b: SourceKind
    ref: Ref   # the clause line that lists this pair


# ---------------------------------------------------------------------------
# ContractTerms (MSA and amendments)
# ---------------------------------------------------------------------------

class ContractTerms(BaseModel):
    """Facts extracted from a Master Services Agreement or an Amendment."""

    id: Val                          # "TBX-US-EXP-E60"
    kind: Literal["msa", "amendment"]
    amends: Optional[Val] = None     # amendment only: the MSA id it amends

    parties: list[str]               # ["Quillmere Pharma Inc.", "Tarrowby Express Inc."]
    parties_ref: Optional[Ref] = None

    dated: Val                       # signing date ISO
    effective_from: Val              # "2031-12-17"
    end_date: Optional[Val] = None   # "2032-12-16"

    # Term / auto-renewal
    auto_renewal: bool
    auto_renewal_ref: Optional[Ref] = None
    renewal_notice_days: Optional[int] = None
    renewal_notice_ref: Optional[Ref] = None

    # Precedence
    precedence_order: Optional[list[str]] = None  # ["signed_amendment", "msa", "annexes"]
    precedence_ref: Optional[Ref] = None
    unranked_pairs: Optional[list[UnrankedPair]] = None

    # Rates (Annex A)
    rate_periods: list[RatePeriod]
    rate_rows: list[RateRow]

    # Fuel surcharge (Annex C)
    fuel_not_applicable: Optional[Ref] = None
    fuel_rows: Optional[list[FuelRow]] = None

    # Accessorials (Annex D)
    accessorials_not_applicable: Optional[Ref] = None
    accessorials: Optional[list[Accessorial]] = None

    # Charge-code aliases (Annex E)
    charge_code_aliases: Optional[list[ChargeCodeAlias]] = None

    # Volume rebate (clause 7)
    rebate_not_applicable: Optional[Ref] = None
    rebate_tiers: Optional[list[RebateTier]] = None
    rebate_tier_rule: Optional[Literal["whole", "marginal"]] = None
    rebate_tier_rule_ref: Optional[Ref] = None
    rebate_tier_rule_text: Optional[Val] = None  # the clause text as printed
    rebate_period: Optional[Literal["quarter", "contract_year"]] = None
    rebate_due_days: Optional[Val] = None    # "45"
    # Qualifying-spend definition for rebate/credits. Categories drive arithmetic;
    # qs_text is the clause as printed, kept for evidence.
    qs_includes: Optional[list[BillingCategory]] = None
    qs_excludes: Optional[list[BillingCategory]] = None
    qs_text: Optional[Val] = None

    # Handling margin / step-down (clause 8)
    margin_not_applicable: Optional[Ref] = None
    margin_step_down: Optional[list[MarginStepRow]] = None

    # Promised credits (clause 9)
    promised_credits_not_applicable: Optional[Ref] = None
    promised_credits: Optional[list[PromisedCredit]] = None

    # Payment terms (clause 10)
    payment_due_days: Val            # "45"
    payment_grace_days: Val          # "0" or "5"
    late_fee_rate: Val               # "1.19"  (percent per month)
    late_fee_compounding: bool
    late_fee_compounding_ref: Optional[Ref] = None
    who_may_extend: Optional[Val] = None  # "payment_terms" (the Schedule 1 category)

    # FX (Annex F)
    fx_not_applicable: Optional[Ref] = None
    fx_rows: Optional[list[FXRow]] = None

    # Schedule 1
    schedule1_rows: list[Schedule1Row]

    # Key clauses cited in evidence
    key_clauses: Optional[list[KeyClause]] = None

    # Documents this instrument refers to (e.g. an amendment names its MSA)
    refers_to: Optional[list[ReferTo]] = None


# ---------------------------------------------------------------------------
# BillingDoc (invoice, credit note, statement)
# ---------------------------------------------------------------------------

BillingCategory = Literal[
    "freight", "fuel", "security", "accessorial", "minimum_charge",
    "tax", "duty", "disbursement", "late_fee", "credit",
    "programme_fee", "other",
]


class BillingLine(BaseModel):
    """One charge line of an invoice, credit note or statement."""
    line_no: Optional[str] = None
    awb: Optional[str] = None
    charge_label: str
    category: BillingCategory
    refers_to_invoice: Optional[str] = None  # a late-fee line names the invoice it is charged on
    lane: Optional[str] = None
    pickup_date: Optional[str] = None    # ISO "2031-12-25"
    collected_date: Optional[str] = None # ISO; Caldrith "Collected" column
    qty: Optional[str] = None           # "241"
    unit: Optional[str] = None          # "kg", "shpt", "%"
    rate: Optional[str] = None          # "6.69" or "20.16"
    amount: str                          # "1612.29"
    sac_code: Optional[str] = None      # INR invoices only
    ref: Ref


class BillingDoc(BaseModel):
    """Facts extracted from an invoice, credit note or statement of account."""

    id: Val                            # "TX-US-2032-5394"
    kind: Literal["invoice", "credit_note", "statement"]
    issuer: Val
    contract_ref: Optional[Val] = None
    currency: Val                      # "USD" or "INR"

    invoice_date: Optional[Val] = None
    due_date: Optional[Val] = None

    subtotal: Optional[Val] = None
    tax: Optional[Val] = None
    total: Val

    # Billing marks
    is_copy: bool = False
    is_reminder: bool = False
    is_for_your_records: bool = False
    asks_for_payment: bool = True
    marks_ref: Optional[Ref] = None

    # Credit-note fields
    credit_type: Optional[str] = None   # "rebate", "improvement", ...
    credit_period: Optional[Val] = None
    credited_invoices: Optional[list[str]] = None

    lines: list[BillingLine]


# ---------------------------------------------------------------------------
# EmailFacts
# ---------------------------------------------------------------------------

class WaiverDetails(BaseModel):
    charge: str                    # "Delivery fee"
    awb: Optional[str] = None
    invoice: Optional[str] = None
    month: Optional[str] = None    # "2033-06"
    condition: Optional[str] = None
    ref: Ref


class ExtensionDetails(BaseModel):
    invoice: str      # "TX-US-2032-5494"
    new_date: str     # ISO "2032-08-25"
    ref: Ref


class RateNoticeRow(BaseModel):
    lane: str
    band: str
    rate: str                        # decimal string
    currency: Optional[str] = None
    ref: Ref


class RateNoticeDetails(BaseModel):
    reference: Optional[Val] = None  # "TBX-US-EXP-E90/RN-USW1-USC3-2032-06-05"
    lane: Optional[str] = None
    effective_from: Optional[Val] = None
    effective_to: Optional[Val] = None
    rows: list[RateNoticeRow]
    ref: Ref


class PickupDetails(BaseModel):
    awb: str
    date: Optional[str] = None   # ISO
    ref: Ref


class OwnTextBlock(BaseModel):
    """A range of lines in the email's own (non-quoted) text.

    The model does not copy the text; the reader cites the line range and the
    rules engine reads it from the document.
    """
    ref: Ref   # set line_end to span multiple lines


class QuotedTextBlock(BaseModel):
    """A range of quoted lines in an email reply."""
    original_sender: Optional[str] = None
    ref: Ref   # set line_end to span multiple lines


class PaymentRequest(BaseModel):
    """An invoice the email asks to be paid."""
    invoice_id: str
    is_copy: bool = False
    is_reminder: bool = False
    is_for_your_records: bool = False
    asks_for_payment: bool = True
    ref: Ref


class EmailFacts(BaseModel):
    """Facts extracted from an email (body only, not attachments)."""

    kind: Literal[
        "waiver", "due_date_extension", "rate_notice",
        "pickup", "delivery", "customs_event",
        "billing_query", "invoice_transmittal", "contract_transmittal", "other"
    ]
    sender: Val    # "Elspeth Iyengar <elspeth.iyengar@tarrowby.example>"

    own_lines: list[OwnTextBlock]      # line ranges, not copied text
    quoted_lines: list[QuotedTextBlock]

    # Waivers (list; a single email may waive multiple charges)
    waivers: Optional[list[WaiverDetails]] = None

    # Due-date extensions (list)
    extensions: Optional[list[ExtensionDetails]] = None

    # Rate notice
    rate_notice: Optional[RateNoticeDetails] = None

    # Pickup confirmation
    pickup: Optional[PickupDetails] = None

    # Invoices the email asks to be paid
    payment_requests: Optional[list[PaymentRequest]] = None

    # Prompt-injection flags (always extracted, always with a ref)
    addresses_automation: bool = False
    addresses_automation_ref: Optional[Ref] = None
    gives_orders: bool = False
    gives_orders_ref: Optional[Ref] = None


# ---------------------------------------------------------------------------
# SheetMap (spreadsheet column mapping)
# ---------------------------------------------------------------------------

class SheetMap(BaseModel):
    """Column layout of a spreadsheet (tracking export, payment register, …)."""

    kind: Literal["tracking_export", "payment_register", "other"]
    sheet_number: int              # 1-indexed
    sheet_name: Optional[str] = None
    # field_name → column_label as it appears in the header row
    columns: dict[str, str]
    ref: Ref                       # the header row


# ---------------------------------------------------------------------------
# ShipmentDoc (AWB and DG declaration)
# ---------------------------------------------------------------------------

class ShipmentDoc(BaseModel):
    """Facts extracted from an Air Waybill or Dangerous Goods Declaration."""

    awb: Val
    kind: Literal["awb", "dg_declaration"]
    master_or_house: Optional[Literal["master", "house"]] = None

    executed_date: Optional[Val] = None
    origin: Optional[Val] = None
    destination: Optional[Val] = None
    pieces: Optional[Val] = None
    actual_weight: Optional[Val] = None
    chargeable_weight: Optional[Val] = None
    goods: Optional[Val] = None

    # Dangerous goods
    un_numbers: Optional[list[Val]] = None
    refrigerant_only: Optional[bool] = None
    refrigerant_only_ref: Optional[Ref] = None


# ---------------------------------------------------------------------------
# JSON schema utility (inlines $defs so the Anthropic API can accept it)
# ---------------------------------------------------------------------------

def flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *schema* with every $ref replaced by its definition.

    Pydantic v2 emits schemas with $defs / $ref.  The Anthropic Messages API
    requires an ``input_schema`` that is a plain object (no unresolved $ref).
    """
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def resolve(obj: Any) -> Any:
        if isinstance(obj, dict):
            if "$ref" in obj and len(obj) == 1:
                name = obj["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(defs[name]))
            return {k: resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [resolve(item) for item in obj]
        return obj

    return resolve(schema)
