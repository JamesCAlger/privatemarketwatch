"""Source checks for rows whose tagged fact is defective and whose published value is the printed one.

Owner ruling 2026-11-10 ("fix the check for the 10 of 13"). A filer's tagged fact can disagree
with its own printed schedule: an unscaled tag, an ixt:fixed-zero format, values cross-tagged
between two lines, split digits, a dropped bracket or sign, a fact on a neighbour's context, a
leading digit printed in its own cell, a value tagged in thousands. An audited row correction (or a
promoted rule) then publishes the printed value, and the quarter ties to the filed total, but the
source reconciliation compares the published value with the tag and reports a blocking
``value_mismatch`` (row_validation SRC_BDC03, source_recon blocking_fair_value_*).

The correction's own claim is not trusted. A matched row is re-labelled only when the page says
the same thing, read independently of the correction and of the tag:

* every mismatched field (fair_value, cost, principal_amount) is in the published row's
  ``corrected_fields`` (a row correction or promoted rule set it); a mismatched unit count, or a
  mismatched field nothing corrected, keeps the row blocking;
* the filing's printed scale is read from the page: on the same accession's uncontested rows (the
  published fair value equals the tag), the tagged fair value is found among the row's printed
  figures at one scale (1, 1,000 or 1,000,000) on at least ``MIN_SCALE_VOTES`` rows and on at least
  ``SCALE_AGREEMENT`` of the voting rows; no clear scale, no re-label;
* one printed row of the same filing (``bdc_ixbrl_field_status.csv`` ``printed_row``, current
  period; a member printed on two rows has none) shows the published principal, cost and fair value
  together, each in its own cell, in that left-to-right order, at that scale, to the digits printed,
  with the printed sign (brackets are negative, a dash is zero). The row is the row's own member's
  printed line, or, where the filer put the facts on another member's line (cross-tagged values), any
  line of the filing that prints all three of a published non-zero principal, cost and fair value.

A re-labelled row keeps ``status = 'value_mismatch'`` and its mismatched fields, and becomes
non-blocking with ``calibrated_status = 'page_verified_correction'``; the printed row it was read
against is written to ``evidence``. Row validation lists it as SRC_BDC03P (INFO, TRACK_ONLY) and the
residual classification as ``documented_page_verified_correction``, so the case stays visible.
Rows with no correction, or whose published value is not the printed one, are unchanged.

Not covered: a published value that is not a printed figure (a commitment netted under D-091 from
a fact tagged on another member) and a row whose printed line the page reader did not keep (a
member printed on two lines, or a line whose fair-value fact carries a neighbour's context, so the
line is keyed to the neighbour). Those stay blocking. ASCII-only. Read-only.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

PAGE_VERIFIED_STATUS = "page_verified_correction"
PAGE_VERIFIED_MECHANISM = "documented_page_verified_correction"
# Printed left to right in a schedule: principal (par), amortized cost, fair value.
AMOUNT_FIELDS = ("principal_amount", "cost", "fair_value")
VERIFIABLE_FIELDS = frozenset(AMOUNT_FIELDS)
SCALES = (1.0, 1e3, 1e6)
MIN_SCALE_VOTES = 3
SCALE_AGREEMENT = 0.8
# Uncontested rows read per accession to find its printed scale (deterministic order).
MAX_SCALE_VOTERS = 300
PRINTED_ROW_COLUMNS = ["cik", "accession_number", "raw_id_lower", "printed_row"]

_CURRENCY = re.compile(r"\b(?:USD|EUR|GBP|CAD|AUD|CHF|SEK|NOK|DKK|JPY|NZD)\b|[$]")
_DASH = re.compile(r"^[-‐-―−]+$")
_FIGURE = re.compile(r"^(\()?\s*(-)?\s*(\d[\d,]*(?:\.\d+)?)\s*(\))?$")
_TRUE = {"true", "1", "yes"}


def printed_figures(printed_row: Any) -> list[tuple[int, float, int]]:
    """The amount cells of a printed row as (cell index, signed value, decimals printed).

    Cells are separated by ' | '. A closing bracket or percent sign printed in a cell of its own
    belongs to the figure before it (as in pipeline.disposition_validity). A cell is an amount only
    when, currency marks removed, it is one figure: '(70)' is -70, '1,433' is 1433, a lone dash is
    zero. Words, percentages, dates and cells holding two or more figures (footnote marks such as
    '(7) (8)') are not amounts.
    """
    text = str(printed_row or "")
    if not text.strip():
        return []
    joined = re.sub(r" \| (?=[%)]\s*(?: \||$))", "", text)
    out: list[tuple[int, float, int]] = []
    for index, cell in enumerate(joined.split(" | ")):
        bare = _CURRENCY.sub(" ", cell).strip()
        if not bare:
            continue
        if _DASH.match(bare):
            out.append((index, 0.0, 0))
            continue
        m = _FIGURE.match(bare)
        if not m:
            continue
        opened, minus, digits, closed = m.groups()
        if bool(opened) != bool(closed):
            continue
        value = float(digits.replace(",", ""))
        if opened or minus:
            value = -value
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        out.append((index, value, decimals))
    return out


def figure_matches(value: float, printed: float, decimals: int, scale: float) -> bool:
    """Is the published value this printed figure at this scale, to the digits printed, with its sign?"""
    if value == 0.0 or printed == 0.0:
        return value == 0.0 and printed == 0.0
    if (value < 0) != (printed < 0):
        return False
    unit = 10.0 ** -decimals
    return abs(printed * scale - value) <= max(0.51 * unit * scale, 1.0)


def tuple_on_row(published: dict[str, float], figures: list[tuple[int, float, int]], scale: float) -> bool:
    """True when every published amount is printed in its own cell, in principal-cost-fair value order."""
    fields = [f for f in AMOUNT_FIELDS if f in published]
    if not fields:
        return False

    def place(i: int, after: int) -> bool:
        if i == len(fields):
            return True
        value = published[fields[i]]
        for cell, printed, decimals in figures:
            if cell > after and figure_matches(value, printed, decimals, scale) and place(i + 1, cell):
                return True
        return False

    return place(0, -1)


def printed_scale(pairs: list[tuple[float, list[tuple[int, float, int]]]]) -> Optional[float]:
    """The filing's printed scale from (tagged fair value, printed figures) of uncontested rows."""
    votes = {scale: 0 for scale in SCALES}
    voting = 0
    for value, figures in pairs:
        hit = [scale for scale in SCALES
               if any(figure_matches(value, p, d, scale) for _c, p, d in figures)]
        if hit:
            voting += 1
            for scale in hit:
                votes[scale] += 1
    if not voting:
        return None
    best = max(SCALES, key=lambda s: (votes[s], -s))
    ranked = sorted(votes.values(), reverse=True)
    if votes[best] < MIN_SCALE_VOTES or votes[best] < SCALE_AGREEMENT * voting or ranked[0] == ranked[1]:
        return None
    return best


def load_printed_rows(path: Optional[Path] = None, ciks: Optional[set[str]] = None) -> pd.DataFrame:
    """Current-period printed rows (cik, accession_number, raw_id_lower, printed_row) of the page artifact.

    A member keyed to more than one current row of a filing has no single printed row and is dropped.
    An artifact without a ``printed_row`` column (written before the page reader kept it) yields no
    rows, so nothing is re-labelled.
    """
    if path is None:
        from pipeline.config import BDC_IXBRL_FIELD_STATUS_FILE
        path = BDC_IXBRL_FIELD_STATUS_FILE
    empty = pd.DataFrame({c: pd.Series(dtype="string") for c in PRINTED_ROW_COLUMNS})
    path = Path(path)
    if not path.exists():
        return empty
    src = path.as_posix().replace("'", "''")
    con = duckdb.connect()
    try:
        columns = {r[0] for r in con.execute(
            f"DESCRIBE SELECT * FROM read_csv('{src}', header=true, all_varchar=true, sample_size=-1)").fetchall()}
        if not {"printed_row", "period_role", "raw_id_lower", "accession_number", "cik"} <= columns:
            return empty
        cik_filter = ""
        if ciks is not None:
            norm = sorted({str(c).strip().zfill(10) for c in ciks if str(c).strip()})
            if not norm:
                return empty
            con.register("wanted", pd.DataFrame({"cik": norm}))
            cik_filter = "AND lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') IN (SELECT cik FROM wanted)"
        rows = con.execute(f"""
            SELECT lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') AS cik,
                   trim(accession_number) AS accession_number, raw_id_lower,
                   any_value(printed_row) AS printed_row, count(*) AS n
            FROM read_csv('{src}', header=true, all_varchar=true, sample_size=-1)
            WHERE period_role = 'current' {cik_filter}
            GROUP BY 1, 2, 3""").fetchdf()
    finally:
        con.close()
    rows = rows[(rows["n"] == 1) & rows["printed_row"].fillna("").str.strip().ne("")]
    return rows[PRINTED_ROW_COLUMNS].reset_index(drop=True)


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _truthy(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.strip().str.lower().isin(_TRUE)


def _false_like(series: pd.Series):
    """'Not blocking' in the representation the column already uses (bool, 0/1 number or text)."""
    if series.dtype == bool:
        return False
    if pd.api.types.is_numeric_dtype(series):
        return 0
    sample = series.dropna().astype(str).str.strip()
    return "0" if sample.isin(["0", "1"]).any() else "False"


def _member_keys(detail: pd.DataFrame) -> pd.Series:
    from pipeline.bdc_xbrl_html_bridge import overlay_member_key
    frame = pd.DataFrame({
        "raw_investment_identifier": detail["raw_investment_identifier"].fillna("").astype(str),
        "dimensions_raw": detail["dimensions_raw"].fillna("").astype(str),
    }, index=detail.index)
    return overlay_member_key(frame, "raw_investment_identifier", "dimensions_raw")


def apply_page_verification(
    detail: pd.DataFrame,
    holdings: pd.DataFrame,
    printed_rows: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """Re-label blocking value mismatches whose corrected published value is the printed one.

    ``detail`` is the reconciliation detail with published ``output_row_id`` (the holdings
    ``row_id``); ``holdings`` carries ``row_id`` and ``corrected_fields``. Returns a copy; rows that
    do not pass every condition in the module docstring are returned unchanged.
    """
    if (detail is None or detail.empty or printed_rows is None or printed_rows.empty
            or holdings is None or holdings.empty
            or not {"row_id", "corrected_fields"} <= set(holdings.columns)):
        return detail
    status = detail["status"].astype(str)
    candidates = status.eq("value_mismatch") & _truthy(detail["blocking_issue"])
    if not candidates.any():
        return detail

    corrected = (holdings[["row_id", "corrected_fields"]].dropna(subset=["row_id"])
                 .astype(str).drop_duplicates("row_id").set_index("row_id")["corrected_fields"])
    out = detail.copy()
    norm_cik = out["cik"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(10)
    accession = out["accession_number"].fillna("").astype(str).str.strip()
    filing_key = norm_cik + "|" + accession
    cand_idx = out.index[candidates]
    wanted = set(filing_key[cand_idx])

    # Only the filings that hold a candidate are read (a handful per fund).
    printed = printed_rows.copy()
    printed["cik"] = printed["cik"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(10)
    printed["accession_number"] = printed["accession_number"].astype(str).str.strip()
    printed = printed[(printed["cik"] + "|" + printed["accession_number"]).isin(wanted)]
    by_filing: dict[tuple[str, str], dict[str, str]] = {}
    for c, a, k, p in printed[["cik", "accession_number", "raw_id_lower", "printed_row"]].itertuples(index=False):
        by_filing.setdefault((c, a), {})[str(k)] = str(p)

    filings = set(by_filing)
    if not filings:
        return detail
    members = pd.Series("", index=out.index, dtype=object)
    in_filings = filing_key.isin({c + "|" + a for c, a in filings})
    members.loc[in_filings] = _member_keys(out.loc[in_filings])

    # The printed scale of each filing, from rows whose published fair value is the tagged one.
    uncontested = in_filings & status.isin(["matched", "diagnostic_field_mismatch"])
    scale_by_filing: dict[tuple[str, str], Optional[float]] = {}
    figure_cache: dict[tuple[str, str, str], list] = {}

    def figures_of(filing: tuple[str, str], key: str) -> list:
        cache_key = (filing[0], filing[1], key)
        if cache_key not in figure_cache:
            figure_cache[cache_key] = printed_figures(by_filing.get(filing, {}).get(key, ""))
        return figure_cache[cache_key]

    voters = out.loc[uncontested, ["source_row_id", "source_fair_value"]].copy()
    voters["filing"] = list(zip(norm_cik[uncontested], accession[uncontested]))
    voters["member"] = members[uncontested]
    voters["fv"] = pd.to_numeric(voters["source_fair_value"], errors="coerce")
    voters = voters[voters["fv"].notna() & voters["fv"].ne(0)].sort_values(["source_row_id"])
    for filing, group in voters.groupby("filing", sort=True):
        pairs = []
        for fv, key in zip(group["fv"], group["member"]):
            if key in by_filing[filing]:
                pairs.append((float(fv), figures_of(filing, key)))
            if len(pairs) >= MAX_SCALE_VOTERS:
                break
        scale_by_filing[filing] = printed_scale(pairs)

    n_verified = 0
    for i in cand_idx:
        filing = (norm_cik[i], accession[i])
        scale = scale_by_filing.get(filing)
        if filing not in filings or not scale:
            continue
        mismatched = {f.strip() for f in str(out.at[i, "mismatched_fields"] or "").split(",") if f.strip()}
        if not mismatched or not mismatched <= VERIFIABLE_FIELDS:
            continue
        row_corrected = {f.strip() for f in str(corrected.get(str(out.at[i, "output_row_id"]), "")).split(";")
                         if f.strip()}
        if not mismatched <= row_corrected:
            continue
        published = {f: v for f in AMOUNT_FIELDS
                     if (v := _num(out.at[i, "output_" + f])) is not None}
        if "fair_value" not in published:
            continue
        own = members[i]
        found = None
        if own in by_filing[filing] and tuple_on_row(published, figures_of(filing, own), scale):
            found = ("own member", by_filing[filing][own])
        elif len(published) == 3 and all(v != 0 for v in published.values()):
            # Facts cross-tagged between lines: the published tuple is printed on another member's line.
            for key in sorted(by_filing[filing]):
                if key != own and tuple_on_row(published, figures_of(filing, key), scale):
                    found = ("another member", by_filing[filing][key])
                    break
        if found is None:
            continue
        where, line = found
        out.at[i, "blocking_issue"] = _false_like(out["blocking_issue"])
        out.at[i, "calibrated_status"] = PAGE_VERIFIED_STATUS
        out.at[i, "issue_severity"] = "INFO"
        out.at[i, "calibration_reason"] = (
            f"{PAGE_VERIFIED_STATUS}: {','.join(sorted(mismatched))} set by an audited correction; the "
            f"printed line ({where}) shows the published principal/cost/fair value at scale "
            f"{int(scale)}; the tagged fact disagrees with the page")
        out.at[i, "evidence"] = "printed_row: " + line[:400]
        n_verified += 1
    if n_verified:
        logger.info("Source reconciliation: %d corrected value mismatch row(s) verified on the printed page",
                    n_verified)
    return out
