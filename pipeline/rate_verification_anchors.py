"""Exact source-fact anchors for reviewed rate concept/context mislabelling.

Verification only: no value is supplied by the declaration and extraction is unchanged.
The independent review must establish the printed row linking both contexts and the
concept's actual meaning. The verifier still reads the fact from the cached instance.
"""
import re


def entry_errors(entry):
    required = {
        "accession", "context", "field", "source_context", "source_concept",
        "source_units", "evidence",
    }
    if not isinstance(entry, dict) or set(entry) != required:
        return ["rate anchor requires exact source coordinates, units and evidence"]
    errors = []
    if not isinstance(entry["accession"], str) or not re.fullmatch(
        r"\d{10}-\d{2}-\d{6}", entry["accession"]
    ):
        errors.append("invalid accession")
    for key in ("context", "source_context"):
        if not isinstance(entry[key], str) or not re.fullmatch(r"\S+", entry[key]):
            errors.append("invalid " + key)
    if entry["field"] not in ("interest_rate", "pik_rate"):
        errors.append("only total coupon and PIK rate anchors are supported")
    if entry["source_concept"] not in (
        "InvestmentInterestRate", "InvestmentInterestRatePaidInKind",
        "InvestmentInterestRatePaidInCash",
    ):
        errors.append("source concept must be an explicit rate fact")
    if entry["source_units"] != "fraction":
        errors.append("source fact must be a fraction, published in percentage points")
    if not isinstance(entry["evidence"], str) or len(entry["evidence"].strip()) < 20:
        errors.append("printed-row evidence required")
    return errors


def load_anchors():
    from pipeline.source_encodings import load_encodings

    return {
        (cik, e["accession"], e["context"], e["field"]): e
        for cik, encoding in load_encodings().items()
        for e in encoding.get("rate_verification_anchors", [])
    }
