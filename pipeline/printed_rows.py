"""Schedule rows printed in a filing and carrying no XBRL context, declared from the printed line.

Owner ruling 2026-10-18 (OVR-T8Y-R2, option a): a printed schedule row with no XBRL context may be
published from its printed line. TCW Direct Lending VIII, 10-Q 2023-09-30 (0000950170-23-060972),
prints Harvey Gulf Term Loans A and B and the Lenox Term Loan (92.4M fair value) with no tag and no
2023-09-30 context; the quarter's published total was 92.4M short of the printed one.

A fund's wrapper lists each row under ``source_encodings.printed_rows_without_context``: the
accession, the quarter, the issuer and instrument as printed, the printed fair value, cost and
principal, and the verbatim printed line (an optional ``industry`` is the printed heading above
it). The loader (``pipeline.source_encodings.load_encodings``) refuses an entry whose line does not
contain its issuer, its instrument and its three numbers as printed. The extractor adds one record
per entry and nothing it was not given. An entry may also declare the printed interest rate, spread,
reference rate, floor, maturity and percent of net assets (OVR-T8Z-R2, orchestrator under the owner's
delegation, 2026-10-18, D-208); the loader refuses any of them not printed in the line, and staging
labels each printed_page where a ``*_source`` column exists. Nothing is parsed from the line itself.

The record's context id is ``printed_page:<hash>`` (no such context exists in the instance), its
dimension path ``printedpage=<issuer> | <instrument>``, and staging labels its fair value, cost and
principal ``printed_page`` in the ``*_source`` columns, so no check reads it as an XBRL fact.

A listed row the filing does tag on a current-period context is refused, not duplicated: if any
record of the filing for the quarter names the issuer and the instrument, or carries the same fair
value and cost, the entry is logged and skipped.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

ENCODING_KEY = "printed_rows_without_context"
CONTEXT_PREFIX = "printed_page:"
SOURCE_LABEL = "printed_page"
REQUIRED_FIELDS = ("accession", "quarter", "issuer", "instrument", "fair_value", "cost", "principal_amount",
                   "printed_line")
# Printed terms a declared row may carry (orchestrator ruling OVR-T8Z-R2 under the owner's delegation,
# 2026-10-18, D-208). Percent fields are declared as printed (12.63 for '12.63%'); the record stores
# them as fractions, as a tagged fact would be, so staging reads them exactly as it reads tagged ones.
PERCENT_FIELDS = ("interest_rate", "basis_spread", "interest_rate_floor", "pct_of_net_assets")
TERM_FIELDS = PERCENT_FIELDS + ("reference_rate_type", "maturity_date")
# printed_scale (HPS Corporate Capital Solutions, 2026-11-15): a schedule printed in thousands. The declared
# dollars are the printed figures times the scale; the loader looks for each figure as printed (230,000 -> 230).
SCALES = (1000, 1000000)
OPTIONAL_FIELDS = ("industry", "printed_scale", "tagged_twin") + TERM_FIELDS

_ACCESSION_RE = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_REFERENCE_RE = re.compile(r"[A-Z]{2,12}")


def _percent_in_line(line: str, value: float, after: str = "") -> bool:
    """The percent is printed in the line: a number equal to ``value`` followed by '%' (spaces allowed),
    then ``after`` (a regex, e.g. the word Floor) when given."""
    candidates = {("%." + str(d) + "f") % value for d in range(0, 5)} | {repr(float(value))}
    for text in candidates:
        try:
            if float(text) != float(value):
                continue
        except ValueError:
            continue
        if re.search(r"(?<![0-9.])" + re.escape(text) + r"\s*%" + after, line):
            return True
    return False


def _date_in_line(line: str, day: str) -> bool:
    """The maturity is printed in the line as MM/DD/YY or MM/DD/YYYY."""
    year, month, dom = day.split("-")
    for text in (month + "/" + dom + "/" + year[2:], month + "/" + dom + "/" + year):
        if re.search(r"(?<![0-9/])" + re.escape(text) + r"(?![0-9/])", line):
            return True
    return False


def _squash(text: Any) -> str:
    return " ".join(str(text or "").split())


def _printed_number(value: float) -> str:
    """The number as a schedule prints it: whole dollars with thousands separators."""
    return "{:,}".format(int(round(float(value))))


def entry_errors(entry: Any) -> list[str]:
    """Why one declared row is not admissible (an empty list when it is)."""
    if not isinstance(entry, dict):
        return ["an entry is an object"]
    errors = []
    missing = [k for k in REQUIRED_FIELDS if k not in entry]
    extra = sorted(set(entry) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS))
    if missing:
        errors.append("missing " + ", ".join(missing))
    if extra:
        errors.append("unknown keys " + ", ".join(extra))
    if errors:
        return errors
    if not _ACCESSION_RE.fullmatch(str(entry["accession"])):
        errors.append("accession must read 0000000000-00-000000")
    if not _DATE_RE.fullmatch(str(entry["quarter"])):
        errors.append("quarter must read YYYY-MM-DD")
    for key in ("issuer", "instrument", "printed_line", "industry", "reference_rate_type", "maturity_date"):
        if key in entry and (not isinstance(entry[key], str) or not entry[key].strip()):
            errors.append(key + " must be non-empty text")
    for key in PERCENT_FIELDS:
        if key in entry and (isinstance(entry[key], bool) or not isinstance(entry[key], (int, float))
                             or not 0 <= float(entry[key]) < 100):
            errors.append(key + " must be a percent as printed (12.63 for '12.63%')")
    if "maturity_date" in entry and isinstance(entry["maturity_date"], str) and not _DATE_RE.fullmatch(entry["maturity_date"]):
        errors.append("maturity_date must read YYYY-MM-DD")
    if "reference_rate_type" in entry and isinstance(entry["reference_rate_type"], str) \
            and not _REFERENCE_RE.fullmatch(entry["reference_rate_type"]):
        errors.append("reference_rate_type must be the printed code in capitals (SOFR)")
    for key in ("fair_value", "cost", "principal_amount"):
        value = entry[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(float(value)):
            errors.append(key + " must be a whole-dollar number")
    if "tagged_twin" in entry and entry["tagged_twin"] is not True:
        errors.append("tagged_twin must be true when given")
    scale = entry.get("printed_scale", 1)
    if "printed_scale" in entry and (isinstance(scale, bool) or scale not in SCALES):
        errors.append("printed_scale must be one of %s" % (SCALES,))
    if errors:
        return errors
    line = _squash(entry["printed_line"])
    for key in ("issuer", "instrument"):
        if _squash(entry[key]) not in line:
            errors.append(key + " is not in the printed line")
    for key in ("fair_value", "cost", "principal_amount"):
        shown = _printed_number(float(entry[key]) / scale)
        if float(entry[key]) % scale or shown not in line:
            errors.append(key + " " + shown + " is not in the printed line")
    # every declared term must be printed in the line (OVR-T8Z-R2): a value not on the page is refused
    for key in PERCENT_FIELDS:
        if key in entry and not _percent_in_line(line, float(entry[key])):
            errors.append(key + " " + str(entry[key]) + "% is not in the printed line")
    if "interest_rate_floor" in entry and not _percent_in_line(line, float(entry["interest_rate_floor"]), r"\s*,?\s*Floor\b"):
        errors.append("interest_rate_floor " + str(entry["interest_rate_floor"]) + "% is not printed as the floor")
    if "reference_rate_type" in entry and not re.search(r"\b" + re.escape(entry["reference_rate_type"]) + r"\b", line):
        errors.append("reference_rate_type " + entry["reference_rate_type"] + " is not in the printed line")
    if "maturity_date" in entry and not _date_in_line(line, entry["maturity_date"]):
        errors.append("maturity_date " + entry["maturity_date"] + " is not in the printed line")
    return errors


def context_id(entry: dict) -> str:
    """Stable synthetic context id of a declared row (accession, quarter, issuer, instrument)."""
    key = "|".join(_squash(entry[k]).lower() for k in ("accession", "quarter", "issuer", "instrument"))
    return CONTEXT_PREFIX + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def identifier(entry: dict) -> str:
    return _squash(entry["issuer"]) + " | " + _squash(entry["instrument"])


def _index(encodings: dict) -> dict[tuple[str, str], tuple[dict, ...]]:
    result: dict[tuple[str, str], list[dict]] = {}
    for cik, encoding in encodings.items():
        for entry in encoding.get(ENCODING_KEY, []):
            result.setdefault((cik, str(entry["accession"])), []).append(entry)
    return {key: tuple(entries) for key, entries in result.items()}


@lru_cache(maxsize=1)
def _by_accession() -> dict[tuple[str, str], tuple[dict, ...]]:
    from pipeline.source_encodings import load_encodings
    return _index(load_encodings())


def listed_rows(cik: Any, accession: Any, encodings: dict | None = None) -> tuple[dict, ...]:
    owner = re.sub(r"\D", "", str(cik or "")).zfill(10)
    index = _by_accession() if encodings is None else _index(encodings)
    return index.get((owner, str(accession or "").strip()), ())


def _already_tagged(entry: dict, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A current-period record of the filing that is this row: names its issuer and instrument, or
    carries its fair value and cost."""
    issuer = _squash(entry["issuer"]).lower()
    instrument = _squash(entry["instrument"]).lower()
    quarter = str(entry["quarter"])
    for rec in records:
        if str(rec.get("period", ""))[:10] != quarter:
            continue
        text = _squash(rec.get("investment_identifier", "")).lower()
        # the instrument as a whole phrase: 'Term Loan' is not 'Term Loan A' (a tranche letter or number after it)
        if issuer and instrument and issuer in text and re.search(
                r"(?<![a-z0-9])" + re.escape(instrument) + r"(?![a-z0-9]|\s+[a-z0-9](?![a-z0-9]))", text):
            return rec
        fv, cost = rec.get("fair_value"), rec.get("cost")
        if entry.get("tagged_twin") is True:
            continue    # printed twin of a tagged row (same values, another instrument line): only the name test applies
        if (isinstance(fv, (int, float)) and isinstance(cost, (int, float))
                and abs(float(fv) - float(entry["fair_value"])) < 0.5
                and abs(float(cost) - float(entry["cost"])) < 0.5):
            return rec
    return None


def printed_row_records(records: list[dict[str, Any]], filing_meta: dict[str, Any],
                        encodings: dict | None = None) -> list[dict[str, Any]]:
    """Records for the rows the wrapper declares for this filing, ready to append to ``records``.

    Each carries the declared fair value, cost and principal and nothing else; its src_facts holds the
    printed line under ``_printed_page``. A declared row the filing already tags is refused (logged).
    Returns an empty list for every filing no wrapper lists.
    """
    entries = listed_rows(filing_meta.get("cik", ""), filing_meta.get("accession_number", ""), encodings)
    if not entries:
        return []
    report_date = str(filing_meta.get("report_date", "") or "")[:10]
    added = []
    for entry in entries:
        if report_date and str(entry["quarter"]) != report_date:
            logger.warning("printed row %s %s %s: quarter %s is not the filing's report date %s; left out",
                           filing_meta.get("cik", ""), entry["accession"], entry["issuer"], entry["quarter"], report_date)
            continue
        tagged = _already_tagged(entry, records)
        if tagged is not None:
            logger.warning("printed row %s %s %s %s: the filing tags it on context %s; refused, not duplicated",
                           filing_meta.get("cik", ""), entry["accession"], entry["issuer"], entry["instrument"],
                           tagged.get("_context_id", ""))
            continue
        ident = identifier(entry)
        record: dict[str, Any] = {
            "_context_id": context_id(entry),
            "period": str(entry["quarter"]),
            "investment_identifier": ident,
            "industry": _squash(entry.get("industry", "")),
            "investment_type": "",
            "affiliation": "",
            "dimensions_raw": "printedpage=" + ident,
            "fair_value": float(entry["fair_value"]),
            "cost": float(entry["cost"]),
            "principal_amount": float(entry["principal_amount"]),
            "fair_value_unit": "",
            "cost_unit": "",
            "principal_amount_unit": "",
            "interest_rate_concept": "",
            "src_facts": json.dumps({"_printed_page": {
                "issuer": _squash(entry["issuer"]),
                "instrument": _squash(entry["instrument"]),
                "industry": _squash(entry.get("industry", "")),
                "line": _squash(entry["printed_line"]),
                "terms": {k: entry[k] for k in TERM_FIELDS if k in entry},
            }}, sort_keys=True, separators=(",", ":")),
        }
        # printed terms (OVR-T8Z-R2): percents stored as fractions, as a tagged fact holds them
        for key in PERCENT_FIELDS:
            if key in entry:
                record[key] = round(float(entry[key]) / 100.0, 10)
        for key in ("reference_rate_type", "maturity_date"):
            if key in entry:
                record[key] = entry[key]
        added.append(record)
        logger.info("printed row %s %s %s %s: added from the printed line (no XBRL context)",
                    filing_meta.get("cik", ""), entry["accession"], entry["issuer"], entry["instrument"])
    return added


def condition_sql(context_column: str = "src_context_id") -> str:
    """SQL: true for a row added from a printed line (its context id carries the reserved prefix)."""
    return "starts_with(COALESCE(CAST(" + context_column + " AS VARCHAR), ''), '" + CONTEXT_PREFIX + "')"


DECLARED_STATUS = "printed_page_declared"


def declaration_sql(context_column: str = "src_context_id",
                    fair_value_source_column: str = "fair_value_source") -> str:
    """SQL: true for a published row declared under printed_rows_without_context.

    Keyed on the declaration itself (the reserved context prefix AND the fair value labelled
    'printed_page' by staging), never on a row merely lacking a context: a row with no context that
    was not declared keeps whatever result the check gives it today (OVR-T8Z-R1/R3, 2026-10-18).
    Checks give such rows the non-blocking status ``printed_page_declared``: never matched, never
    verified, never blocking, still counted.
    """
    return ("(" + condition_sql(context_column) + " AND COALESCE(CAST(" + fair_value_source_column
            + " AS VARCHAR), '') = '" + SOURCE_LABEL + "')")


def declared_sql(name: str, facts_column: str = "src_facts") -> str:
    """SQL: a declared text field (issuer, instrument, industry) of a printed row, from its src_facts."""
    return ("json_extract_string(NULLIF(CAST(" + facts_column + " AS VARCHAR), ''), '$._printed_page." + name + "')")
