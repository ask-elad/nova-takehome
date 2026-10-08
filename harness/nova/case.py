"""Case model: assembled facts the rules engine queries.

Built from a list of document records (type, doc path, received_at, data)
and an as_of date. Only documents received on or before as_of count.

Primitives exposed to rule modules:
  Case.contracts_in_force(on_date)         -> list[ContractEntry]
  Case.rate_rows_in_force(contract, lane, on_date) -> list[RateSource]
  Case.fuel_pct(contract, pickup_month, on_date)   -> Optional[Decimal]
  Case.accessorial(contract, code, on_date)        -> Optional[Accessorial]
  Case.pickup_date(awb)                            -> Optional[(iso_date, source_ref)]
  Case.authority_of(email_addr, contract, category) -> bool
  Case.judge(question_id, context)                 -> (bool, ref)

Each contract/amendment carries its origin doc path for evidence.
The Judge interface is pluggable: the test judge reads from a fixtures
dict; the production judge calls Claude.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from pydantic import ValidationError

from nova.schemas import (
    Accessorial,
    BillingDoc,
    BillingLine,
    ContractTerms,
    EmailFacts,
    FXRow,
    FuelRow,
    RateRow,
    Ref,
    Schedule1Row,
    SheetMap,
    ShipmentDoc,
    Val,
)

SCHEMA_MAP = {
    "ContractTerms": ContractTerms,
    "BillingDoc": BillingDoc,
    "EmailFacts": EmailFacts,
    "SheetMap": SheetMap,
    "ShipmentDoc": ShipmentDoc,
}


@dataclass(frozen=True)
class SourceRef:
    """Where a fact was read from."""
    doc: str
    page: int
    line: int
    line_end: Optional[int] = None

    @classmethod
    def from_ref(cls, doc: str, ref: Ref) -> "SourceRef":
        return cls(doc=doc, page=ref.page, line=ref.line, line_end=ref.line_end)


@dataclass
class ContractRecord:
    """A contract or amendment, with origin doc."""
    doc: str
    received_at: Optional[date]
    terms: ContractTerms

    @property
    def id(self) -> str:
        return self.terms.id.value

    @property
    def amends(self) -> Optional[str]:
        return self.terms.amends.value if self.terms.amends else None

    @property
    def is_amendment(self) -> bool:
        return self.terms.kind == "amendment"

    @property
    def effective_from(self) -> str:
        return self.terms.effective_from.value

    @property
    def end_date(self) -> Optional[str]:
        return self.terms.end_date.value if self.terms.end_date else None


@dataclass
class BillingRecord:
    doc: str
    received_at: Optional[date]
    bill: BillingDoc


@dataclass
class EmailRecord:
    doc: str
    received_at: Optional[date]
    email: EmailFacts


@dataclass
class SheetRecord:
    doc: str
    received_at: Optional[date]
    sheet: SheetMap
    # Rows loaded from the mailbox using sheet.columns; filled by the harness.
    rows: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ShipmentRecord:
    doc: str
    received_at: Optional[date]
    ship: ShipmentDoc


# ---------------------------------------------------------------------------
# Judge interface
# ---------------------------------------------------------------------------

JudgeFn = Callable[[str, Mapping[str, Any]], tuple[bool, Optional[SourceRef]]]


def null_judge(question_id: str, context: Mapping[str, Any]) -> tuple[bool, Optional[SourceRef]]:
    """Default judge: refuses to decide. Rules can treat None as cannot_determine."""
    raise NotImplementedError(f"no judge for {question_id!r}")


def fixture_judge(answers: Mapping[str, dict]) -> JudgeFn:
    """Return a judge that reads yes/no answers from a loaded judgements.json dict.

    Each entry looks like {"<question_id>": {"answer": true, "ref": {...}}}.
    """
    def judge(question_id: str, context: Mapping[str, Any]) -> tuple[bool, Optional[SourceRef]]:
        if question_id not in answers:
            raise KeyError(f"no fixture answer for {question_id!r}")
        a = answers[question_id]
        ref = a.get("ref")
        src = SourceRef(**ref) if ref else None
        return bool(a["answer"]), src
    return judge


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------

@dataclass
class Case:
    as_of: str  # ISO
    contracts: list[ContractRecord]
    billings: list[BillingRecord]
    emails: list[EmailRecord]
    sheets: list[SheetRecord]
    shipments: list[ShipmentRecord]
    judge: JudgeFn

    # ----- construction -----

    @classmethod
    def from_records(
        cls,
        records: list[dict],
        as_of: str,
        judge: JudgeFn = null_judge,
    ) -> "Case":
        """Build a case from a list of {type, doc, received_at?, data} dicts.

        Entries whose received_at > as_of are dropped. Entries without
        received_at are kept (the fixtures model documents assumed in-scope).
        """
        as_of_d = _parse_date(as_of)
        contracts: list[ContractRecord] = []
        billings: list[BillingRecord] = []
        emails: list[EmailRecord] = []
        sheets: list[SheetRecord] = []
        shipments: list[ShipmentRecord] = []

        for entry in records:
            received = _parse_date(entry.get("received_at")) if entry.get("received_at") else None
            if received is not None and received > as_of_d:
                continue
            cls_name = entry["type"]
            model = SCHEMA_MAP.get(cls_name)
            if model is None:
                raise ValueError(f"unknown record type {cls_name!r}")
            try:
                obj = model.model_validate(entry["data"])
            except ValidationError as e:  # pragma: no cover - fixtures are already valid
                raise ValueError(f"invalid {cls_name} in {entry.get('doc')}: {e}") from e
            doc = entry["doc"]
            if cls_name == "ContractTerms":
                contracts.append(ContractRecord(doc=doc, received_at=received, terms=obj))
            elif cls_name == "BillingDoc":
                billings.append(BillingRecord(doc=doc, received_at=received, bill=obj))
            elif cls_name == "EmailFacts":
                emails.append(EmailRecord(doc=doc, received_at=received, email=obj))
            elif cls_name == "SheetMap":
                sheets.append(SheetRecord(doc=doc, received_at=received, sheet=obj,
                                          rows=entry.get("rows", [])))
            elif cls_name == "ShipmentDoc":
                shipments.append(ShipmentRecord(doc=doc, received_at=received, ship=obj))

        return cls(
            as_of=as_of,
            contracts=contracts,
            billings=billings,
            emails=emails,
            sheets=sheets,
            shipments=shipments,
            judge=judge,
        )

    # ----- contracts & terms -----

    def msa_for(self, contract_id: str) -> Optional[ContractRecord]:
        for c in self.contracts:
            if not c.is_amendment and c.id == contract_id:
                return c
        return None

    def contracts_in_force(self, on_date: str) -> list[ContractRecord]:
        """MSAs plus amendments whose effective_from <= on_date <= end_date (or no end)."""
        d = _parse_date(on_date)
        result = []
        for c in self.contracts:
            if _parse_date(c.effective_from) > d:
                continue
            if c.end_date and _parse_date(c.end_date) < d:
                continue
            result.append(c)
        return result

    def period_for(self, msa: ContractRecord, on_date: str) -> Optional[str]:
        """Return the Annex A rate-period label containing on_date, if any."""
        d = _parse_date(on_date)
        for p in msa.terms.rate_periods:
            if _parse_date(p.start) <= d <= _parse_date(p.end):
                return p.label
        return None

    def rate_rows_for(self, msa: ContractRecord, lane: str) -> list[RateRow]:
        return [r for r in msa.terms.rate_rows if r.lane == lane]

    def fuel_pct(self, msa: ContractRecord, pickup_month: str) -> Optional[tuple[Decimal, SourceRef]]:
        for row in msa.terms.fuel_rows or []:
            if row.month == pickup_month:
                return Decimal(row.rate), SourceRef.from_ref(msa.doc, row.ref)
        return None

    def accessorial(self, msa: ContractRecord, code: str) -> Optional[Accessorial]:
        for a in msa.terms.accessorials or []:
            if a.code == code:
                return a
        return None

    def accessorial_by_label(self, msa: ContractRecord, label: str) -> Optional[Accessorial]:
        low = label.strip().lower()
        for a in msa.terms.accessorials or []:
            if a.label.strip().lower() == low:
                return a
        return None

    def fx_for(self, msa: ContractRecord) -> dict[str, Decimal]:
        return {r.month: Decimal(r.rate) for r in (msa.terms.fx_rows or [])}

    # ----- pickup date -----

    def pickup_date(self, awb: str) -> Optional[tuple[str, SourceRef]]:
        """Return (iso_date, source_ref) using the fallback chain:
        tracking PICKED_UP → carrier pickup email → AWB executed date → invoice line.
        """
        # 1. tracking export
        for s in self.sheets:
            if s.sheet.kind != "tracking_export":
                continue
            for row in s.rows:
                if row.get("awb") == awb and row.get("event") == "PICKED_UP" and row.get("date"):
                    ref = Ref(page=s.sheet.sheet_number, line=row.get("_line", s.sheet.ref.line))
                    return row["date"], SourceRef.from_ref(s.doc, ref)
        # 2. pickup email
        for e in self.emails:
            p = e.email.pickup
            if p and p.awb == awb and p.date:
                return p.date, SourceRef.from_ref(e.doc, p.ref)
        # 3. AWB executed date
        for sh in self.shipments:
            if sh.ship.awb.value == awb and sh.ship.executed_date:
                return sh.ship.executed_date.value, SourceRef.from_ref(sh.doc, sh.ship.executed_date.ref)
        # 4. invoice line pickup_date
        for b in self.billings:
            for ln in b.bill.lines:
                if ln.awb == awb and ln.pickup_date:
                    return ln.pickup_date, SourceRef.from_ref(b.doc, ln.ref)
        return None

    # ----- authority (Schedule 1) -----

    def authority_of(self, email_addr: str, contract_id: str, category: str) -> bool:
        """True iff the exact email address is a Schedule 1 contact for the
        category on the contract. Exact match (case-insensitive)."""
        addr = email_addr.strip().lower()
        for c in self.contracts:
            if c.id != contract_id and (not c.amends or c.amends != contract_id):
                continue
            for row in c.terms.schedule1_rows:
                if row.email.strip().lower() == addr and category in row.categories:
                    return True
        return False

    def schedule1_contact(self, contract_id: str, category: str) -> Optional[Schedule1Row]:
        for c in self.contracts:
            if c.id != contract_id and (not c.amends or c.amends != contract_id):
                continue
            for row in c.terms.schedule1_rows:
                if category in row.categories:
                    return row
        return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse_date(iso: str) -> date:
    y, m, d = iso.split("-")
    return date(int(y), int(m), int(d))
