"""Task 8: fund-income yield evidence through the inherited S2 signal (spec 6.3; ruling R28).

The fund-income yield contract REUSES pipeline.rate_convention._aggregate_signals (S2)
on explicit input frames; this module writes no yield formula of its own. Before the
S2 result is interpreted, the inputs must prove, in order:

  shape      the holdings frame carries the S2 columns (source, cik, report_date,
             interest_rate, pik_rate, principal_amount, ...) plus the provenance
             columns used below. bdc_holdings.csv does NOT: it has no `source` column
             and stores raw decimal rates, so S2 would silently see no rows. The pinned
             private_markets_holdings slice (S2's production input) is used instead.
  rows       at least one source='bdc' row for (cik, quarter).
  rate_units every stored interest_rate / positive pik_rate carries the declared
             deterministic conversion `interest_rate:rate_x100` / `pik_rate:rate_x100`
             in src_transforms (raw XBRL decimal -> percent, the unit S2 divides by 100).
  duration   a bdc_fund_income row for the quarter with 2 <= duration_months <= 4 and
             end_date = quarter (S2's own quarterly filter); annual-only = mismatch.
  income     a positive interest_income (tagged) or total_investment_income
             (estimated); an estimate must be calibrated on this CIK's own quarters
             (the global fallback share depends on the slice's CIK set).
  scope      the holdings rows and the income row come from the same accession.
  currency   every rated holdings row maps to a census position whose principal is
             USD, and the census quarterly income facts are USD.
  meaning    the census concepts behind the rated rows' interest_rate are one
             semantic class (PaidInCash vs bare InvestmentInterestRate), never mixed.

`interest_rate` is passed to S2 unchanged (the stored leg) and `pik_rate` separately:
S2 adds the PIK term itself, so the adapter never adds PIK a second time. S2 reports
per-CIK aggregates only; holdings are restricted to ONE (cik, quarter), so its
income_r_median is that quarter's r. Base/PIK sums are mirrored here ONLY to attribute
a missing S2 result to a named cause and to report coverage; a tagged-quarter r that
disagrees with the mirror is a defect and raises. Income rows are as-of the quarter
(report_date <= quarter) so learning never sees a later quarter's income.
"""
from __future__ import annotations

from contextlib import nullcontext
import math

S2_COLUMNS = ("source", "cik", "report_date", "interest_rate", "pik_rate", "principal_amount", "basis_spread",
              "bdc_investment_identifier")
EVIDENCE_COLUMNS = ("src_transforms", "src_context_id", "accession_number")
INCOME_REQUIRED = ("cik", "report_date", "accession_number", "end_date", "duration_months",
                   "total_investment_income", "interest_income")
S2_CONSTANT_NAMES = ("METHOD_VERSION", "INCOME_R_ALL_IN", "INCOME_R_CASH", "INCOME_MIN_QUARTERS",
                     "INCOME_MIN_PIK_SHARE", "INCOME_COVERAGE_BAND", "INCOME_EST_MIN_PIK_SHARE",
                     "INCOME_EST_R_ALL_IN", "INCOME_EST_R_CASH", "INCOME_R_FLOOR")
S2_FUNCTION = "pipeline/rate_convention.py:_aggregate_signals"
INCOME_FIELDS = ("income_interest", "income_total", "income_interest_and_dividend")
MIRROR_TOLERANCE = 1e-6


class IncomeEvidenceError(RuntimeError):
    """The S2 mirror disagrees with S2 itself: a defect in this adapter, never a verdict."""


def s2_constants() -> dict:
    from pipeline import rate_convention as rc
    out = {}
    for name in S2_CONSTANT_NAMES:
        value = getattr(rc, name)
        out[name] = list(value) if isinstance(value, tuple) else value
    return out


def cik_s2(cik) -> str:
    return str(int(str(cik)))


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) or math.isinf(out) else out


def _clean(value):
    """JSON-safe scalars (numpy -> python; NaN -> None)."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _series(frame, column):
    import pandas as pd
    return pd.to_numeric(frame[column], errors="coerce")


def _positions_by_context(doc: dict | None) -> dict:
    if not doc:
        return {}
    dped = set(doc["document_metadata"]["document_period_end_dates"])
    return {p["context_id"]: p for p in doc["positions"] if p["period"].get("instant") in dped}


def _field(position: dict | None, name: str) -> dict:
    return ((position or {}).get("fields") or {}).get(name) or {}


def _rate_class(concepts) -> str:
    names = {str(c).rsplit(":", 1)[-1].lower() for c in concepts or []}
    if not names:
        return "no_concept"
    if all("paidincash" in n for n in names):
        return "paid_in_cash"
    if names == {"investmentinterestrate"}:
        return "bare_investment_interest_rate"
    return "other:" + ",".join(sorted(names))


# ---------------------------------------------------------------- preconditions

def _preconditions(h, inc, *, cik: str, q: str, census_doc: dict | None) -> tuple[dict, str | None, dict]:
    pre: dict = {}
    missing = [c for c in S2_COLUMNS + EVIDENCE_COLUMNS if c not in h.columns]
    missing_income = [c for c in INCOME_REQUIRED if c not in inc.columns]
    pre["shape"] = dict(ok=not (missing or missing_income), missing_holdings_columns=missing,
                        missing_income_columns=missing_income,
                        rule="S2 input = private_markets_holdings shape (source + percent rates)")
    if not pre["shape"]["ok"]:
        return pre, "holdings_frame_not_s2_shaped", {}
    mine = h[(h["cik"].map(lambda v: cik_s2(v) if str(v).strip().isdigit() else "") == cik_s2(cik))
             & (h["report_date"].astype(str).str[:10] == q)]
    bdc = mine[mine["source"].fillna("").astype(str).str.lower() == "bdc"]
    pre["rows"] = dict(ok=len(bdc) > 0, bdc_rows=int(len(bdc)), frame_rows=int(len(h)))
    if not len(bdc):
        return pre, "no_holdings_rows_for_quarter", {}
    ir, pik, prin = _series(bdc, "interest_rate"), _series(bdc, "pik_rate"), _series(bdc, "principal_amount")
    transforms = bdc["src_transforms"].fillna("").astype(str)
    ir_rows = ir.notna()
    pik_rows = pik > 0
    ir_unproven = ir_rows & ~transforms.str.contains("interest_rate:rate_x100", regex=False)
    pik_unproven = pik_rows & ~transforms.str.contains("pik_rate:rate_x100", regex=False)
    pre["rate_units"] = dict(ok=not (ir_unproven.any() or pik_unproven.any()),
                             interest_rate_rows=int(ir_rows.sum()), interest_rate_unproven=int(ir_unproven.sum()),
                             pik_rows=int(pik_rows.sum()), pik_unproven=int(pik_unproven.sum()),
                             declared_conversion="src_transforms interest_rate:rate_x100 / pik_rate:rate_x100 "
                                                 "(raw decimal -> percent)",
                             unproven_context_ids=sorted(bdc.loc[ir_unproven | pik_unproven, "src_context_id"]
                                                         .fillna("").astype(str))[:50])
    work = dict(bdc=bdc, ir=ir, pik=pik, prin=prin)
    if not pre["rate_units"]["ok"]:
        return pre, "rate_units_not_proven", work

    inc_cik = inc["cik"].map(lambda v: cik_s2(v) if str(v).strip().isdigit() else "")
    rows = inc[(inc_cik == cik_s2(cik)) & (inc["report_date"].astype(str).str[:10] == q)]
    months = _series(rows, "duration_months")
    quarterly = rows[(months >= 2) & (months <= 4) & (rows["end_date"].astype(str).str[:10] == q)]
    pre["duration"] = dict(ok=len(quarterly) > 0, income_rows=int(len(rows)),
                           durations_months=sorted({str(v) for v in rows["duration_months"].tolist()}),
                           rule="2 <= duration_months <= 4 and end_date == quarter (S2's quarterly filter)")
    if not len(rows):
        return pre, "no_fund_income_row", work
    if not len(quarterly):
        return pre, "duration_mismatch_no_quarterly_income", work
    ii = _series(quarterly, "interest_income").max()
    tii = _series(quarterly, "total_investment_income").max()
    ii, tii = _num(ii), _num(tii)
    tagged = ii is not None and ii > 0
    own = inc[(inc_cik == cik_s2(cik))]
    own_ii, own_tii = _series(own, "interest_income"), _series(own, "total_investment_income")
    own_m = _series(own, "duration_months")
    calibration = int(((own_ii > 0) & (own_tii > 0) & (own_ii <= own_tii) & (own_m >= 2) & (own_m <= 4)).sum())
    pre["income"] = dict(ok=tagged or (tii is not None and tii > 0 and calibration > 0),
                         src="tagged" if tagged else "est", interest_income=ii, total_investment_income=tii,
                         cik_calibration_quarters=calibration,
                         note="tagged = interest_income > 0 (as S2); est = total income x (1 - non-interest share)")
    work.update(ii=ii, tii=tii, tagged=tagged, quarterly=quarterly)
    if not tagged and not (tii is not None and tii > 0):
        return pre, "no_income_value", work
    if not pre["income"]["ok"]:
        return pre, "estimated_income_uncalibrated", work

    holdings_acc = sorted({str(a) for a in bdc["accession_number"].tolist()})
    income_acc = sorted({str(a) for a in quarterly["accession_number"].tolist()})
    pre["scope"] = dict(ok=len(income_acc) == 1 and holdings_acc == income_acc, holdings_accessions=holdings_acc,
                        income_accessions=income_acc, holdings_rows=int(len(bdc)),
                        rule="holdings rows and the quarterly income row come from one accession")
    if not pre["scope"]["ok"]:
        return pre, "scope_accession_mismatch", work

    positions = _positions_by_context(census_doc)
    rated = ((ir > 0) | (pik > 0)) & (prin > 0)
    currencies: dict[str, int] = {}
    meaning: dict[str, int] = {}
    for ctx, is_ir in zip(bdc.loc[rated, "src_context_id"].astype(str), (ir[rated] > 0).tolist()):
        position = positions.get(ctx)
        principal = _field(position, "principal_amount")
        ccy = (principal.get("currency") or "none") if position else "not_in_census"
        currencies[ccy] = currencies.get(ccy, 0) + 1
        if is_ir and position:
            cls = _rate_class(_field(position, "interest_rate").get("concepts"))
            meaning[cls] = meaning.get(cls, 0) + 1
    income_ccy: dict[str, int] = {}
    for item in (census_doc or {}).get("fund_income") or []:
        period = item.get("period") or {}
        if item.get("field") in INCOME_FIELDS and period.get("kind") == "duration" and period.get("end") == q:
            income_ccy[str(item.get("currency"))] = income_ccy.get(str(item.get("currency")), 0) + 1
    pre["currency"] = dict(ok=set(currencies) <= {"USD"} and set(income_ccy) == {"USD"},
                           rated_rows_by_principal_currency=currencies,
                           census_quarter_income_facts_by_currency=income_ccy,
                           rule="rated rows -> census principal currency (via src_context_id); census income USD")
    if not pre["currency"]["ok"]:
        cause = "principal_currency_not_proven_usd" if set(currencies) - {"USD"} else "income_currency_not_proven_usd"
        return pre, cause, work
    pre["meaning"] = dict(ok=len(meaning) <= 1, stored_interest_rate_concept_classes=meaning,
                          rule="one concept class behind the stored interest_rate (never mixed cash/bare)")
    if not pre["meaning"]["ok"]:
        return pre, "mixed_rate_concept_semantics", work
    return pre, None, work


# ---------------------------------------------------------------- S2

def _mirror(work: dict) -> dict:
    ir, pik, prin = work["ir"], work["pik"], work["prin"]
    m, mp = (ir > 0) & (prin > 0), (pik > 0) & (prin > 0)
    base = float((ir[m] / 100.0 * prin[m] / 4.0).sum())
    pik_add = float((pik[mp] / 100.0 * prin[mp] / 4.0).sum())
    rated_fv = _series(work["bdc"], "fair_value") if "fair_value" in work["bdc"].columns else None
    share = None
    if rated_fv is not None:
        total = float(rated_fv[prin > 0].sum())
        share = float(rated_fv[m].sum()) / total if total > 0 else None
    return dict(base=base, pik_add=pik_add, pik_share=(pik_add / base) if base > 0 else None,
                rated_rows=int(m.sum()), pik_rows=int(mp.sum()), rated_principal_fv_share=share,
                note="attribution mirror of S2's pred CTE; the verdict uses S2's own output")


def _no_result_cause(mirror: dict, work: dict, constants: dict) -> tuple[str, float | None]:
    if mirror["pik_add"] <= 0:
        return "no_pik_exposure_s2_uninformative", None
    if mirror["base"] <= 0:
        return "no_rated_principal", None
    lo, hi = constants["INCOME_COVERAGE_BAND"]
    if work.get("tagged"):
        coverage = mirror["base"] / work["ii"]
        if not lo <= coverage <= hi:
            return "coverage_outside_income_coverage_band", coverage
        if mirror["pik_share"] < constants["INCOME_MIN_PIK_SHARE"]:
            return "pik_share_below_informative_minimum", coverage
        return "s2_no_quarter_result", coverage
    if mirror["pik_share"] < constants["INCOME_EST_MIN_PIK_SHARE"]:
        return "pik_share_below_informative_minimum", None
    return "s2_no_quarter_result_estimated_income", None


def income_evidence(holdings, income, *, cik: str, report_date: str, census_doc: dict | None, aggregate=None,
                    cwd=None) -> dict:
    """Yield evidence for one (cik, quarter): preconditions, S2 output, vote or named cause."""
    from pipeline import rate_convention
    aggregate = aggregate or rate_convention._aggregate_signals
    cwd = cwd or nullcontext
    q = str(report_date)[:10]
    constants = s2_constants()
    pre, cause, work = _preconditions(holdings, income, cik=cik, q=q, census_doc=census_doc)
    out = dict(cik=str(cik).zfill(10), report_date=q, status="insufficient_evidence", vote=None, cause=cause,
               preconditions=pre, interpreted=False,
               inherited=dict(s2_function=S2_FUNCTION, method_version=constants["METHOD_VERSION"],
                              holdings="private_markets_holdings pinned slice, source='bdc' rows for the quarter",
                              income="bdc_fund_income pinned slice, rows with report_date <= quarter"),
               s2=None)
    if "bdc" not in work:
        return _json_safe(out)
    frame = work["bdc"][list(S2_COLUMNS)].copy()
    asof = income[income["report_date"].astype(str).str[:10] <= q].copy() if "report_date" in income.columns \
        else income.copy()
    with cwd():
        signals = aggregate(frame, asof)
    row = signals[signals["cik"].astype(str) == cik_s2(cik)]
    mirror = _mirror(work)
    src = None if "tagged" not in work else ("tagged" if work["tagged"] else "est")
    s2 = dict(function=S2_FUNCTION, constants=constants, mirror=mirror, src=src, interest_income=work.get("ii"),
              total_investment_income=work.get("tii"), r=None, income_quarters=0, votes_all_in=0, votes_cash=0,
              coverage_ratio=None, income_used=None)
    if len(row):
        r0 = row.iloc[0]
        s2.update(income_quarters=int(_num(r0.get("income_quarters")) or 0),
                  votes_all_in=int(_num(r0.get("income_votes_allin")) or 0),
                  votes_cash=int(_num(r0.get("income_votes_cash")) or 0),
                  r=_num(r0.get("income_r_median")))
    out["s2"] = s2
    if cause is not None:
        s2["note"] = "S2 output recorded but NOT interpreted: precondition " + cause + " failed"
        return _json_safe(out)
    out["interpreted"] = True
    if not s2["income_quarters"] or s2["r"] is None:
        out["cause"], s2["coverage_ratio"] = _no_result_cause(mirror, work, constants)
        return _json_safe(out)
    r = s2["r"]
    s2["income_used"] = mirror["base"] + r * mirror["pik_add"]
    s2["coverage_ratio"] = mirror["base"] / s2["income_used"] if s2["income_used"] else None
    if work.get("tagged"):
        mirrored = (work["ii"] - mirror["base"]) / mirror["pik_add"]
        if abs(mirrored - r) > MIRROR_TOLERANCE * max(1.0, abs(r)):
            raise IncomeEvidenceError("S2 r %.9f disagrees with the attribution mirror %.9f for %s %s"
                                      % (r, mirrored, cik, q))
    if s2["votes_cash"] and not s2["votes_all_in"]:
        out.update(status="vote", vote="cash_leg", cause=None)
    elif s2["votes_all_in"] and not s2["votes_cash"]:
        out.update(status="vote", vote="all_in", cause=None)
    elif r < constants["INCOME_R_FLOOR"]:
        out["cause"] = "r_below_floor_measurement_problem"
    else:
        out["cause"] = "unknown_convention_r_between_thresholds"
    return _json_safe(out)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return _clean(value)


# ---------------------------------------------------------------- pinned slices (light DuckDB reads)

def read_quarter_frames(paths, *, holdings_path, income_path, cik: str, report_date: str):
    from scripts.profile_pilot.paths import pilot_duckdb
    con = pilot_duckdb(paths)
    try:
        h = con.execute("SELECT * FROM read_parquet(?) WHERE lpad(cik, 10, '0') = ? "
                        "AND substr(report_date, 1, 10) = ?", [str(holdings_path), str(cik).zfill(10),
                                                               str(report_date)[:10]]).df()
        inc = con.execute("SELECT * FROM read_parquet(?) WHERE substr(report_date, 1, 10) <= ?",
                          [str(income_path), str(report_date)[:10]]).df()
    finally:
        con.close()
    return h, inc


def load_income_evidence(paths, *, cik: str, report_date: str, holdings_path, income_path,
                         census_doc: dict | None) -> dict:
    """The S2 adapter over the pinned slices; S2 runs with cwd = run root (its own DuckDB)."""
    from scripts.profile_pilot.paths import pilot_cwd
    h, inc = read_quarter_frames(paths, holdings_path=holdings_path, income_path=income_path, cik=cik,
                                 report_date=report_date)
    ev = income_evidence(h, inc, cik=cik, report_date=report_date, census_doc=census_doc,
                         cwd=lambda: pilot_cwd(paths))
    return _json_safe(ev)
