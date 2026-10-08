"""Tests for schemas.py and verify.py.

Run:  python -m pytest harness/tests/test_schemas.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pydantic import ValidationError

from nova.schemas import (
    Accessorial,
    BillingDoc,
    ContractTerms,
    EmailFacts,
    Ref,
    SheetMap,
    ShipmentDoc,
    Val,
    flatten_schema,
)
from nova.textlayer import Mailbox
from nova.verify import VerifyFailure, verify_object


def _minimal_contract_terms(**overrides):
    """Return a minimal valid ContractTerms dict for validation tests."""
    base = {
        "id": {"value": "X", "ref": {"page": 1, "line": 1}},
        "kind": "msa",
        "parties": ["A", "B"],
        "dated": {"value": "2031-01-01", "ref": {"page": 1, "line": 1}},
        "effective_from": {"value": "2031-01-01", "ref": {"page": 1, "line": 1}},
        "auto_renewal": False,
        "rate_periods": [],
        "rate_rows": [],
        "payment_due_days": {"value": "45", "ref": {"page": 1, "line": 1}},
        "payment_grace_days": {"value": "0", "ref": {"page": 1, "line": 1}},
        "late_fee_rate": {"value": "1.0", "ref": {"page": 1, "line": 1}},
        "late_fee_compounding": False,
        "schedule1_rows": [],
    }
    base.update(overrides)
    return base

EXAMPLES_DIR = Path("data/examples")
FIXTURES_DIR = Path("harness/tests/fixtures/examples")

EXAMPLES = [
    "overcharge",
    "duplicate",
    "cashback",
    "conflict",
    "late_fees",
    "waived_but_billed",
    "expiry",
    "duplicate_rebilled_4_months",
]

SCHEMA_MAP = {
    "ContractTerms": ContractTerms,
    "BillingDoc": BillingDoc,
    "EmailFacts": EmailFacts,
    "SheetMap": SheetMap,
    "ShipmentDoc": ShipmentDoc,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_fixtures() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for name in EXAMPLES:
        p = FIXTURES_DIR / name / "facts.json"
        if p.exists():
            result[name] = json.loads(p.read_text())
    return result


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

class TestFixtureLoading:
    def test_all_examples_have_fixture_files(self):
        missing = [n for n in EXAMPLES if not (FIXTURES_DIR / n / "facts.json").exists()]
        assert not missing, f"Missing fixture files: {missing}"

    def test_fixtures_load_into_schemas(self, all_fixtures):
        for example_name, entries in all_fixtures.items():
            for entry in entries:
                schema_cls = SCHEMA_MAP.get(entry["type"])
                assert schema_cls is not None, (
                    f"{example_name}: unknown schema type {entry['type']!r}"
                )
                # Should not raise
                obj = schema_cls.model_validate(entry["data"])
                assert obj is not None


# ---------------------------------------------------------------------------
# Verification: passes on fixture values
# ---------------------------------------------------------------------------

class TestVerificationPasses:
    def test_verify_passes_on_all_fixtures(self, all_fixtures):
        failures_found = []
        for example_name, entries in all_fixtures.items():
            mb = Mailbox(EXAMPLES_DIR / example_name / "docs")
            for entry in entries:
                schema_cls = SCHEMA_MAP[entry["type"]]
                obj = schema_cls.model_validate(entry["data"])
                pages, _ = mb.pages(entry["doc"])
                failures = verify_object(obj, pages)
                for f in failures:
                    failures_found.append(
                        f"{example_name}/{entry['doc']}: {f}"
                    )
        assert not failures_found, "\n".join(failures_found)


# ---------------------------------------------------------------------------
# Verification: fails on deliberately wrong inputs
# ---------------------------------------------------------------------------

class TestVerificationFails:
    def _pages(self, *lines: str) -> list[str]:
        return ["\n".join(lines)]

    def test_fails_on_wrong_value(self):
        pages = self._pages("line one", "total 1612.29 USD", "line three")
        ref = Ref(page=1, line=2)
        val = Val(value="9999.99", ref=ref)
        failures = verify_object(val, pages)
        assert len(failures) == 1
        assert "9999.99" in str(failures[0])

    def test_fails_on_wrong_line_number(self):
        pages = self._pages("line one", "total 42.00 here", "line three")
        ref = Ref(page=1, line=3)   # value is on line 2, not 3
        val = Val(value="42.00", ref=ref)
        failures = verify_object(val, pages)
        assert len(failures) == 1

    def test_fails_on_neighbouring_row(self):
        """A rate from the row below the cited row should fail."""
        pages = self._pages(
            "header",
            "USE2-INE2 minimum charge 58.00 58.00",
            "USE2-INE2 0-44.5 kg 7.73 7.93",
        )
        ref = Ref(page=1, line=2)
        val = Val(value="7.73", ref=ref)   # 7.73 is on line 3, not 2
        failures = verify_object(val, pages)
        assert len(failures) == 1

    def test_fails_on_wrong_page(self):
        pages = self._pages("nothing here") + ["total 100.00 USD"]
        ref = Ref(page=1, line=1)
        val = Val(value="100.00", ref=ref)
        failures = verify_object(val, pages)
        assert len(failures) == 1

    def test_fails_on_nonexistent_page(self):
        pages = self._pages("only one page")
        ref = Ref(page=2, line=1)
        val = Val(value="1.00", ref=ref)
        failures = verify_object(val, pages)
        assert len(failures) == 1
        assert "does not exist" in str(failures[0])


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

class TestNormalisation:
    def _pages(self, *lines: str) -> list[str]:
        return ["\n".join(lines)]

    def test_money_thousands_separator(self):
        """5,235.09 on a line should match stored value "5235.09"."""
        pages = self._pages("Total USD 5,235.09")
        ref = Ref(page=1, line=1)
        val = Val(value="5235.09", ref=ref)
        assert not verify_object(val, pages)

    def test_money_currency_code_stripped(self):
        """USD 1,612.29 on a line should match "1612.29"."""
        pages = self._pages("amount USD 1,612.29")
        ref = Ref(page=1, line=1)
        val = Val(value="1612.29", ref=ref)
        assert not verify_object(val, pages)

    def test_date_dmy_slash(self):
        """17/07/2030 on a line should match stored ISO "2030-07-17"."""
        pages = self._pages("due date 17/07/2030 net 30")
        ref = Ref(page=1, line=1)
        val = Val(value="2030-07-17", ref=ref)
        assert not verify_object(val, pages)

    def test_date_iso_exact(self):
        """ISO date on the line should match without conversion."""
        pages = self._pages("Effective date 2031-12-17")
        ref = Ref(page=1, line=1)
        val = Val(value="2031-12-17", ref=ref)
        assert not verify_object(val, pages)

    def test_string_case_insensitive(self):
        """String comparison is case-insensitive."""
        pages = self._pages("AIR WAYBILL TE14764227")
        ref = Ref(page=1, line=1)
        val = Val(value="te14764227", ref=ref)
        assert not verify_object(val, pages)

    def test_percentage_value_without_percent(self):
        """Stored rate "20.16" should match line containing "20.16%"."""
        pages = self._pages("2031-12 20.16%")
        ref = Ref(page=1, line=1)
        val = Val(value="20.16", ref=ref)
        assert not verify_object(val, pages)


# ---------------------------------------------------------------------------
# JSON schema export
# ---------------------------------------------------------------------------

SCHEMA_CLASSES = [ContractTerms, BillingDoc, EmailFacts, SheetMap, ShipmentDoc]


@pytest.mark.parametrize("schema_cls", SCHEMA_CLASSES, ids=lambda c: c.__name__)
def test_schema_is_object_type(schema_cls):
    schema = flatten_schema(schema_cls.model_json_schema())
    assert schema.get("type") == "object", f"{schema_cls.__name__}: top level not 'object'"


@pytest.mark.parametrize("schema_cls", SCHEMA_CLASSES, ids=lambda c: c.__name__)
def test_schema_no_dollar_ref(schema_cls):
    schema = flatten_schema(schema_cls.model_json_schema())
    text = json.dumps(schema)
    assert "$ref" not in text, f"{schema_cls.__name__}: $ref still present after flatten"


@pytest.mark.parametrize("schema_cls", SCHEMA_CLASSES, ids=lambda c: c.__name__)
def test_schema_has_properties(schema_cls):
    schema = flatten_schema(schema_cls.model_json_schema())
    assert "properties" in schema, f"{schema_cls.__name__}: no 'properties' key"


# ---------------------------------------------------------------------------
# Whole-token number matching
# ---------------------------------------------------------------------------

class TestWholeTokenNumbers:
    def _pages(self, *lines: str) -> list[str]:
        return ["\n".join(lines)]

    def test_prefix_digit_fails(self):
        """2.84 must not match 12.84."""
        pages = self._pages("12.84 total")
        ref = Ref(page=1, line=1)
        val = Val(value="2.84", ref=ref)
        assert len(verify_object(val, pages)) == 1

    def test_prefix_digit_int_fails(self):
        """44 must not match 144."""
        pages = self._pages("144 kg")
        ref = Ref(page=1, line=1)
        val = Val(value="44", ref=ref)
        assert len(verify_object(val, pages)) == 1

    def test_absent_between_neighbours_fails(self):
        """6.01 not on a line that has 16.01 and 6.16 but not 6.01."""
        pages = self._pages("16.01 and 6.16")
        ref = Ref(page=1, line=1)
        val = Val(value="6.01", ref=ref)
        assert len(verify_object(val, pages)) == 1

    def test_suffix_digit_fails(self):
        """340.1 must not match 340.12."""
        pages = self._pages("340.12 total")
        ref = Ref(page=1, line=1)
        val = Val(value="340.1", ref=ref)
        assert len(verify_object(val, pages)) == 1

    def test_thousands_stripped_matches(self):
        """5235.09 stored must still match 5,235.09 on the line."""
        pages = self._pages("Total USD 5,235.09")
        ref = Ref(page=1, line=1)
        val = Val(value="5235.09", ref=ref)
        assert not verify_object(val, pages)

    def test_date_dmy_whole_token_matches(self):
        """17/07/2030 on the line still matches stored ISO 2030-07-17."""
        pages = self._pages("due date 17/07/2030 net 30")
        ref = Ref(page=1, line=1)
        val = Val(value="2030-07-17", ref=ref)
        assert not verify_object(val, pages)


# ---------------------------------------------------------------------------
# SheetMap column-value checking
# ---------------------------------------------------------------------------

class TestSheetMapColumnValues:
    def _pages(self, *lines: str) -> list[str]:
        return ["\n".join(lines)]

    def test_correct_column_labels_pass(self):
        pages = self._pages("AWB | Event | Date")
        obj = SheetMap(
            kind="tracking_export",
            sheet_number=1,
            columns={"awb": "AWB", "event": "Event", "date": "Date"},
            ref=Ref(page=1, line=1),
        )
        assert not verify_object(obj, pages)

    def test_wrong_column_label_fails(self):
        pages = self._pages("AWB | Event | Date")
        obj = SheetMap(
            kind="tracking_export",
            sheet_number=1,
            columns={"awb": "AWB", "event": "EventXXX"},
            ref=Ref(page=1, line=1),
        )
        failures = verify_object(obj, pages)
        assert any("EventXXX" in str(f) for f in failures)


# ---------------------------------------------------------------------------
# Typed field validation
# ---------------------------------------------------------------------------

class TestTypedFieldValidation:
    def test_basis_kind_accepts_valid(self):
        obj = Accessorial(
            code="DG", label="Dangerous goods fee", rate="284.91",
            basis="USD per shipment", basis_kind="per_shipment",
            ref=Ref(page=1, line=1),
        )
        assert obj.basis_kind == "per_shipment"

    def test_basis_kind_rejects_invalid(self):
        with pytest.raises(ValidationError):
            Accessorial(
                code="DG", label="Dangerous goods fee", rate="284.91",
                basis="USD per shipment", basis_kind="invalid_kind",
                ref=Ref(page=1, line=1),
            )

    def test_rebate_tier_rule_rejects_invalid(self):
        data = _minimal_contract_terms(rebate_tier_rule="invalid")
        with pytest.raises(ValidationError):
            ContractTerms.model_validate(data)

    def test_rebate_period_rejects_invalid(self):
        data = _minimal_contract_terms(rebate_period="monthly")
        with pytest.raises(ValidationError):
            ContractTerms.model_validate(data)

    def test_rebate_tier_rule_accepts_whole(self):
        data = _minimal_contract_terms(rebate_tier_rule="whole")
        obj = ContractTerms.model_validate(data)
        assert obj.rebate_tier_rule == "whole"

    def test_rebate_period_accepts_quarter(self):
        data = _minimal_contract_terms(rebate_period="quarter")
        obj = ContractTerms.model_validate(data)
        assert obj.rebate_period == "quarter"
