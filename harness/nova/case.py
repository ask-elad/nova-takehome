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
    ChargeCodeAlias,
    ContractTerms,
    EmailFacts,
    FXRow,
    FuelRow,
    RateNoticeDetails,
    RateNoticeRow,
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
# Terms-in-force value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TermSource:
    """Where a term came from, with its authority."""
    kind: str              # "msa" | "amendment" | "rate_notice"
    doc: str
    authority_level: int   # 1 = signed, 2 = authorised email, …
    rank: int              # higher beats lower per precedence clause


@dataclass
class RateNoticeSource:
    """A rate notice in force on a date, kept separate from merged terms."""
    doc: str
    notice: RateNoticeDetails
    source: TermSource


@dataclass
class Terms:
    """Terms in force on a date for one contract, each value carrying its source."""
    msa: ContractRecord
    rate_periods: list
    rate_rows: list              # list[tuple[RateRow, TermSource]]
    fuel_rows: list              # list[tuple[FuelRow, TermSource]]
    accessorials: list           # list[tuple[Accessorial, TermSource]]
    fx_rows: list                # list[tuple[FXRow, TermSource]]
    rate_notices: list           # list[RateNoticeSource]
    # Amendment clauses that defer a lane's rates to an external document
    # whose effective_from <= on_date. Each entry is (AmendmentRateRef, TermSource).
    amendment_rate_refs: list = field(default_factory=list)

    def rate_rows_for(self, lane: str) -> list[tuple[RateRow, TermSource]]:
        return [rs for rs in self.rate_rows if rs[0].lane == lane]

    def accessorial_by_code(self, code: str) -> Optional[tuple[Accessorial, TermSource]]:
        for a, s in self.accessorials:
            if a.code == code:
                return a, s
        return None

    def fuel_for_month(self, month: str) -> Optional[tuple[FuelRow, TermSource]]:
        for fr, s in self.fuel_rows:
            if fr.month == month:
                return fr, s
        return None

    def fx_for_month(self, month: str) -> Optional[tuple[FXRow, TermSource]]:
        for fx, s in self.fx_rows:
            if fx.month == month:
                return fx, s
        return None


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
    # Pre-rules facts from feedback.json (see nova.feedback). Each entry is a
    # dict with its own date window. These layer in on top of Schedule 1 and
    # authored rate notices so later rules see them without having to know
    # about feedback themselves.
    extra_authorities: list[dict] = field(default_factory=list)
    rate_accepted_facts: list[dict] = field(default_factory=list)
    precedence_facts: list[dict] = field(default_factory=list)

    # ----- construction -----

    @classmethod
    def from_records(
        cls,
        records: list[dict],
        as_of: str,
        judge: JudgeFn = null_judge,
        mailbox: Any = None,
        pre_rule_facts: Optional[dict] = None,
    ) -> "Case":
        """Build a case from a list of {type, doc, received_at?, data} dicts.

        Entries whose received_at > as_of are dropped. Entries without
        received_at are kept (the fixtures model documents assumed in-scope).

        When a mailbox is given, SheetMap records are parsed into rows using
        `nova.sheets.rows`, so the rules engine sees tracking events and
        payment-register rows in production. Explicit `rows` in a record
        override the parsed rows.
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
                row_data = entry.get("rows")
                if row_data is None and mailbox is not None:
                    from nova.sheets import rows as _parse_rows
                    try:
                        pages, _scan = mailbox.pages(doc)
                        row_data = _parse_rows(pages, obj)
                    except (LookupError, ValueError):
                        row_data = []
                sheets.append(SheetRecord(doc=doc, received_at=received, sheet=obj,
                                          rows=row_data or []))
            elif cls_name == "ShipmentDoc":
                shipments.append(ShipmentRecord(doc=doc, received_at=received, ship=obj))

        prf = pre_rule_facts or {}
        return cls(
            as_of=as_of,
            contracts=contracts,
            billings=billings,
            emails=emails,
            sheets=sheets,
            shipments=shipments,
            judge=judge,
            extra_authorities=list(prf.get("sender_authority") or []),
            rate_accepted_facts=list(prf.get("rate_accepted") or []),
            precedence_facts=list(prf.get("precedence") or []),
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

    # ----- terms in force -----

    def terms_on(self, contract_id: str, on_date: str) -> Optional["Terms"]:
        """Return the terms in force on *on_date* for *contract_id*.

        Base is the MSA; signed amendments to it with effective_from ≤ on_date
        are layered on in effective-date order. A later amendment replaces the
        rows it restates per (lane, band). Fuel, accessorials and FX fall
        through to the MSA unless an amendment restates them. Each returned
        value carries its source, authority level and precedence rank. Rate
        notices in force on on_date — sent by Schedule 1 `rates` contacts —
        are returned separately and never merged into rate rows.
        """
        msa = self.msa_for(contract_id)
        if msa is None:
            return None
        d = _parse_date(on_date)
        msa_src = TermSource(kind="msa", doc=msa.doc, authority_level=1,
                             rank=self._rank_for("msa", msa))

        rate_rows: dict[tuple[str, str], tuple[RateRow, TermSource]] = {}
        for r in msa.terms.rate_rows:
            rate_rows[(r.lane, r.band)] = (r, msa_src)
        fuel_rows: dict[str, tuple[FuelRow, TermSource]] = {
            fr.month: (fr, msa_src) for fr in (msa.terms.fuel_rows or [])
        }
        accessorials: dict[str, tuple[Accessorial, TermSource]] = {
            a.code: (a, msa_src) for a in (msa.terms.accessorials or [])
        }
        fx_rows: dict[str, tuple[FXRow, TermSource]] = {
            fx.month: (fx, msa_src) for fx in (msa.terms.fx_rows or [])
        }

        amendments = [
            c for c in self.contracts
            if c.is_amendment and c.amends == contract_id
            and _parse_date(c.effective_from) <= d
            and (c.end_date is None or _parse_date(c.end_date) >= d)
        ]
        amendments.sort(key=lambda c: _parse_date(c.effective_from))
        amendment_rate_refs: list = []
        for amd in amendments:
            amd_src = TermSource(kind="amendment", doc=amd.doc, authority_level=1,
                                 rank=self._rank_for("signed_amendment", msa))
            for r in amd.terms.rate_rows:
                rate_rows[(r.lane, r.band)] = (r, amd_src)
            for fr in amd.terms.fuel_rows or []:
                fuel_rows[fr.month] = (fr, amd_src)
            for a in amd.terms.accessorials or []:
                accessorials[a.code] = (a, amd_src)
            for fx in amd.terms.fx_rows or []:
                fx_rows[fx.month] = (fx, amd_src)
            for arr in amd.terms.amendment_rate_refs or []:
                if _parse_date(arr.effective_from) <= d:
                    amendment_rate_refs.append((arr, amd_src))

        notices = self._rate_notices_in_force(contract_id, on_date)

        return Terms(
            msa=msa,
            rate_periods=list(msa.terms.rate_periods),
            rate_rows=list(rate_rows.values()),
            fuel_rows=list(fuel_rows.values()),
            accessorials=list(accessorials.values()),
            fx_rows=list(fx_rows.values()),
            rate_notices=notices,
            amendment_rate_refs=amendment_rate_refs,
        )

    def _rank_for(self, source_kind: str, msa: ContractRecord) -> int:
        """Precedence rank from the MSA's precedence_order (higher wins).
        source_kind in {"signed_amendment","msa","annexes","rate_notice"}."""
        order = msa.terms.precedence_order or ["signed_amendment", "msa", "annexes"]
        if source_kind in order:
            return len(order) - order.index(source_kind)
        return 0

    def _rate_notices_in_force(self, contract_id: str, on_date: str) -> list["RateNoticeSource"]:
        d = _parse_date(on_date)
        msa = self.msa_for(contract_id)
        if msa is None:
            return []
        out: list[RateNoticeSource] = []
        for em in self.emails:
            rn = em.email.rate_notice
            if rn is None:
                continue
            sender_addr = _addr_of(em.email.sender.value)
            if not self.authority_of(sender_addr, contract_id, "rates",
                                     on_date=on_date):
                # Feedback `rate_accepted` can admit a notice whose sender
                # isn't on Schedule 1: when the human has told us to treat
                # this notice as the rate for one of its lanes.
                accepted = False
                for row in (rn.rows or []):
                    if self.rate_accepted_for(contract_id, row.lane, on_date):
                        accepted = True
                        break
                if not accepted:
                    continue
            if rn.effective_from and _parse_date(rn.effective_from.value) > d:
                continue
            if rn.effective_to and _parse_date(rn.effective_to.value) < d:
                continue
            src = TermSource(
                kind="rate_notice", doc=em.doc, authority_level=2,
                rank=self._rank_for("rate_notice", msa),
            )
            out.append(RateNoticeSource(doc=em.doc, notice=rn, source=src))
        return out

    def charge_code_for_label(self, msa: ContractRecord, label: str) -> Optional[str]:
        """Resolve a billed charge label to its Annex E code (case-insensitive).

        Falls through to matching the Annex D label when no alias row applies.
        """
        if label is None:
            return None
        low = label.strip().lower()
        for alias in (msa.terms.charge_code_aliases or []):
            if alias.label.strip().lower() == low:
                return alias.code
            if any(a.strip().lower() == low for a in alias.aliases):
                return alias.code
        for a in (msa.terms.accessorials or []):
            if a.label.strip().lower() == low:
                return a.code
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

    # ----- dangerous goods status -----

    def dg_status_for(self, awb: str) -> Optional[tuple[str, SourceRef]]:
        """Return the dangerous-goods status of a shipment from its DG declaration.

        The returned string is one of:
          - ``"refrigerant_only"`` — the declaration says the refrigerant is
            the only hazard, or lists only UN1845 (dry ice). The DG fee does
            not apply (MSA 5.2/5.3): the full DG fee billed is an overcharge.
          - ``"dg"`` — the declaration lists one or more dangerous goods, with
            or without dry ice (a mixed shipment). The DG fee applies **once**.
          - ``None`` — no DG declaration is held for this AWB.
        """
        for sh in self.shipments:
            if sh.ship.kind != "dg_declaration":
                continue
            if sh.ship.awb.value != awb:
                continue
            un_nums = {u.value.upper() for u in (sh.ship.un_numbers or [])}
            if sh.ship.refrigerant_only is True:
                ref_src = SourceRef.from_ref(
                    sh.doc,
                    sh.ship.refrigerant_only_ref or sh.ship.awb.ref,
                )
                return "refrigerant_only", ref_src
            if un_nums and un_nums <= {"UN1845"}:
                # Only dry ice is listed.
                any_ref = next(
                    (u.ref for u in (sh.ship.un_numbers or [])),
                    sh.ship.awb.ref,
                )
                return "refrigerant_only", SourceRef.from_ref(sh.doc, any_ref)
            if un_nums:
                any_ref = next(
                    (u.ref for u in (sh.ship.un_numbers or [])),
                    sh.ship.awb.ref,
                )
                return "dg", SourceRef.from_ref(sh.doc, any_ref)
        return None

    # ----- authority (Schedule 1) -----

    def authority_of(self, email_addr: str, contract_id: str, category: str,
                     on_date: Optional[str] = None) -> bool:
        """True iff *email_addr* is authorised for *category* on *contract_id*.

        Schedule 1 wins first. Feedback standing facts (``sender_authority`` and
        ``rate_accepted``) grant the category to a person inside their dates;
        if *on_date* is given it must sit within valid_from → valid_to, else
        the fact's dates are only sanity-checked against ``as_of``.
        """
        addr = email_addr.strip().lower()
        for c in self.contracts:
            if c.id != contract_id and (not c.amends or c.amends != contract_id):
                continue
            for row in c.terms.schedule1_rows:
                if row.email.strip().lower() == addr and category in row.categories:
                    return True
        probe = on_date or self.as_of
        probe_d = _parse_date(probe) if probe else None
        for ex in self.extra_authorities:
            if ex.get("contract_id") != contract_id:
                continue
            if category not in (ex.get("categories") or []):
                continue
            if ex.get("email", "").strip().lower() != addr:
                continue
            if not _within_window(probe_d, ex.get("valid_from"), ex.get("valid_to")):
                continue
            return True
        return False

    def precedence_fact_for(self, contract_id: str, lane: str,
                            on_date: str) -> Optional[str]:
        """Feedback-level precedence override for a (contract, lane) at a date.

        Returns the source kind (e.g. ``"amendment"``) the human picked, or
        None. Used by the overcharge rule to resolve a conflict pair.
        """
        d = _parse_date(on_date)
        for pf in self.precedence_facts:
            if pf.get("contract_id") != contract_id:
                continue
            if pf.get("lane") != lane:
                continue
            if not _within_window(d, pf.get("valid_from"), pf.get("valid_to")):
                continue
            return pf.get("use")
        return None

    def rate_accepted_for(self, contract_id: str, lane: str,
                          on_date: str) -> Optional[dict]:
        """Feedback ``rate_accepted`` fact in force for (contract, lane) at a date."""
        d = _parse_date(on_date)
        for ra in self.rate_accepted_facts:
            if ra.get("contract_id") != contract_id:
                continue
            if ra.get("lane") != lane:
                continue
            if not _within_window(d, ra.get("valid_from"), ra.get("valid_to")):
                continue
            return ra
        return None

    def contract_for_invoice(self, bill: "BillingRecord") -> Optional[ContractRecord]:
        """Pick the MSA referenced by the invoice's contract_ref, not by lane."""
        bd = bill.bill
        if bd.contract_ref is None:
            return None
        want = bd.contract_ref.value.strip()
        for c in self.contracts:
            if not c.is_amendment and c.id == want:
                return c
        return None

    def is_doc_name_held(self, name: str) -> bool:
        """True iff a contract/amendment with that printed name/id is held.

        Match is loose: ``name`` is compared (case-insensitively) against each
        held contract's id and the basename of its doc path, as well as any
        ``refers_to.name`` already captured on another instrument. Used by the
        overcharge rule when an amendment hands a lane's rate to an external
        document.
        """
        if not name:
            return False
        want = name.strip().lower()
        if not want:
            return False
        for c in self.contracts:
            if c.id and want == c.id.strip().lower():
                return True
            # doc path is "<batch>/<eml>#<file>"; try the attachment filename stem.
            base = c.doc.rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
            if base and want in base:
                return True
            if base and base.replace(".pdf", "") == want:
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
    # Accept both "YYYY-MM-DD" and full ISO datetimes "YYYY-MM-DDTHH:..."
    s = iso.split("T")[0]
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def _within_window(probe: Optional[date], valid_from: Optional[str],
                   valid_to: Optional[str]) -> bool:
    """Half-open-ish window: probe must sit within [valid_from, valid_to].

    None on either side opens that end. None probe passes (used when the
    caller doesn't know the on-date — the feedback is treated as potentially
    active and the rule layer must still enforce its own date checks).
    """
    if probe is None:
        return True
    if valid_from and probe < _parse_date(valid_from):
        return False
    if valid_to and probe > _parse_date(valid_to):
        return False
    return True


def _addr_of(sender: str) -> str:
    """Extract the bare email address from a `Name <addr>` sender string."""
    s = sender.strip()
    lt = s.rfind("<")
    gt = s.rfind(">")
    if 0 <= lt < gt:
        return s[lt + 1 : gt].strip()
    return s
