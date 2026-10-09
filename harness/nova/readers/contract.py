"""Contract reader: fills ContractTerms for an MSA or amendment."""
from __future__ import annotations

from nova.llm import LLMClient
from nova.mailbox import DocRecord
from nova.readers import ReadResult, read_doc
from nova.schemas import ContractTerms

prompt_version = "contract-2"

_INSTRUCTIONS = (
    "This document is a Master Services Agreement (MSA) or a signed Amendment.\n"
    "Fill the ContractTerms schema from what the document says.\n"
    "\n"
    "Rules:\n"
    "- Each extracted value must appear on the line you cite (use [pN LM]).\n"
    "- Normalise money and rates as plain decimal strings (no currency symbols, no %).\n"
    "- Normalise dates as ISO YYYY-MM-DD.\n"
    "- `kind` = \"msa\" for the main agreement, \"amendment\" for a signed amendment.\n"
    "- `precedence_order` lists the kinds in the order the contract gives precedence,\n"
    "  e.g. [\"signed_amendment\", \"msa\", \"annexes\"].\n"
    "- `unranked_pairs` lists pairs that the contract declares as unranked (e.g.\n"
    "  rate_notice and amendment). Each pair has `a`, `b` and a `ref` to the clause.\n"
    "- For every \"Not applicable\" clause (fuel, accessorials, rebate, margin,\n"
    "  promised credits, fx), set the corresponding `_not_applicable` ref to the line.\n"
    "- `payment_due_days`, `payment_grace_days`, `late_fee_rate` are the printed\n"
    "  numbers from the Payment clause; set `late_fee_compounding` to true iff the\n"
    "  clause says the late fee compounds.\n"
    "- `schedule1_rows` must include every person row in Schedule 1 with their\n"
    "  categories.\n"
    "- `rate_rows`: each row is one lane × band with its rate per rate period.\n"
    "  For minimum-charge rows set `is_minimum_charge=true` and leave band_min_kg\n"
    "  and band_max_kg null.\n"
    "- If this instrument refers to other documents (an amendment to its MSA, an\n"
    "  MSA to a referenced annex), list them in `refers_to` with a quote.\n"
    "- Fill `qs_includes` and `qs_excludes` from the Qualifying Spend definition.\n"
    "- Leave `key_clauses` null — the rules engine does not use it.\n"
    "- `rebate_tier_rule` must be exactly one of: whole, marginal (output the bare\n"
    "  string without any surrounding quotes, e.g. whole not \"whole\").\n"
    "- `rebate_period` must be exactly one of: quarter, contract_year (bare string).\n"
    "- For each `rebate_tiers` row, cite the line that contains the threshold amount\n"
    "  and rate number — not the section-header line."
)


def read(client: LLMClient, record: DocRecord) -> ReadResult:
    return read_doc(
        client, record, ContractTerms,
        tier="main", purpose="read_contract", prompt_version=prompt_version,
        instructions=_INSTRUCTIONS, max_tokens=12288,
    )
