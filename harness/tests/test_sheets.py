"""Tests for the production sheet-row parser."""
from __future__ import annotations

from pathlib import Path

from nova.schemas import Ref, SheetMap
from nova.sheets import rows
from nova.textlayer import Mailbox


def test_tracking_export_overcharge_mailbox():
    mb = Mailbox(Path("data/examples/overcharge/docs"))
    doc = "batch_01/0005.eml#tracking-2031-07-01.xlsx"
    pages, _ = mb.pages(doc)
    sm = SheetMap(
        kind="tracking_export",
        sheet_number=1,
        columns={"awb": "AWB", "event": "Event", "date": "Date", "station": "Station"},
        ref=Ref(page=1, line=1),
    )
    out = rows(pages, sm)
    assert len(out) == 10
    first = out[0]
    assert first["awb"] == "TE56915687"
    assert first["event"] == "PICKED_UP"
    assert first["date"] == "2031-12-25"
    assert first["_page"] == 1
    assert first["_line"] == 2
    assert any(r["event"] == "PICKED_UP" and r["awb"] == "TE68271803" for r in out)


def test_payment_register_scenarios_mailbox():
    mb = Mailbox(Path("data/scenarios"))
    doc = "ap-register-2035-05-31.xlsx"
    pages, _ = mb.pages(doc)
    sm = SheetMap(
        kind="payment_register",
        sheet_number=1,
        columns={
            "invoice_no": "Invoice no.",
            "invoice_date": "Invoice date",
            "due_date": "Due date",
            "amount": "Amount",
            "status": "Status",
            "paid_date": "Paid date",
        },
        ref=Ref(page=1, line=1),
    )
    out = rows(pages, sm)
    assert len(out) >= 5
    assert out[0]["invoice_no"] == "TX-US-2034-0379"
    assert out[0]["status"] == "paid"
    assert out[0]["_line"] == 2


def test_tracking_export_scenarios_mailbox():
    mb = Mailbox(Path("data/scenarios"))
    doc = "tracking-2034-10-01.xlsx"
    pages, _ = mb.pages(doc)
    sm = SheetMap(
        kind="tracking_export",
        sheet_number=1,
        columns={"awb": "AWB", "event": "Event", "date": "Date"},
        ref=Ref(page=1, line=1),
    )
    out = rows(pages, sm)
    assert out, "tracking rows should be parsed"
    assert all("awb" in r and "event" in r and "date" in r for r in out)
    picked = [r for r in out if r["event"] == "PICKED_UP"]
    assert picked, "at least one PICKED_UP event expected"


def test_missing_header_label_returns_empty():
    mb = Mailbox(Path("data/examples/overcharge/docs"))
    pages, _ = mb.pages("batch_01/0005.eml#tracking-2031-07-01.xlsx")
    sm = SheetMap(
        kind="tracking_export",
        sheet_number=1,
        columns={"awb": "AWB", "event": "No Such Column"},
        ref=Ref(page=1, line=1),
    )
    assert rows(pages, sm) == []
