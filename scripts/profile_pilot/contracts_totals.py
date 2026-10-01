"""Independent-totals contract kind (spec 2026-09-29 section 5, D-floor).

Two whole-filing criteria that cannot abstain on a pure scale flip: the census current-period
FV sum ON the census published basis (census_published, census-published.v1; SP3 Task 0, after the SP1
finding 2026-10-01 that the raw census sum over-counts) against the fund's filed
investments_at_fair_value, and the pct-of-net-assets sum. Income reconciliation is EVIDENCE ONLY here
(detection_not_claimed); the criterion is deferred to sub-project 2.
Pure functions: no I/O, no tolerances access beyond the band dict passed in.

The totals kind uses the census published basis's SINGLE period end (census_published.period_end); when
there is none the observation carries no_period_end=True and fv_residual_pct=None, and both totals
contracts abstain (learn and evaluate) with cause no_period_end instead of breaching at -100%.
contracts._check_frozen refuses a totals contract whose applies_to differs from APPLIES_TO.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation

from scripts.profile_pilot import census_published

KIND = "independent_totals"
# TOTALS_FIELD/PCT_FIELD intentionally duplicate m2_backtest.TOTALS_FIELD/PCT_FIELD
# (not imported, to avoid a circular import); Task 4 adds an equality test.
TOTALS_FIELD = "fair_value"
PCT_FIELD = "pct_of_net_assets"
FIELDS = (TOTALS_FIELD, PCT_FIELD)
BAND_KEYS = ("fv_residual_pct", "pct_sum_min", "pct_sum_max", "pct_sum_shift_pp", "min_positions")
ANCHOR_SOURCE = "fund_financials.investments_at_fair_value"
PARTITION = "whole_filing"
INCOME_LABEL = "detection_not_claimed"
# partition_id stays whole_filing (contract ids unchanged); applies_to names the census partition version
APPLIES_TO = {PARTITION: True, "census_published": census_published.CENSUS_PUBLISHED_VERSION}


def _num(value):
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _current(doc):
    ends = set(doc["document_metadata"]["document_period_end_dates"])
    return [p for p in doc["positions"] if p["period"].get("instant") in ends]


def current_positions(doc: dict) -> list:
    """Public accessor: the current-period positions (instant in document_period_end_dates)."""
    return _current(doc)


def numeric_value(value):
    """Public accessor: Decimal of a census field value, None when blank or unparsable."""
    return _num(value)


def _sum(positions, field):
    values = [_num((p["fields"].get(field) or {}).get("value")) for p in positions]
    filled = [v for v in values if v is not None]
    return sum(filled, Decimal(0)), len(filled)


def observe_totals(doc: dict, *, financials: dict | None, cik: str, cache: dict | None = None) -> dict:
    """Totals on the census published basis (census_published, census-published.v1): the FV sum equals
    census_published.published_fv_sum (published positions plus R7 cash-equivalent-axis facts); counts and the
    pct sum run over the published positions. classify runs ONCE here (R5 is quadratic in the live rows);
    `cache` (a dict scoped to ONE contracts._evaluate call) memoises it per (id(doc), cik) across the two
    totals contracts of that call; the entry stores (doc, part) and is reused only when it holds the SAME
    doc object (an id() reused after garbage collection never returns a stale partition). cache=None is the
    pure path."""
    key = (id(doc), cik)
    cached = cache.get(key) if cache is not None else None
    if cached is not None and cached[0] is doc:
        part = cached[1]
    else:
        part = census_published.classify(doc, cik=cik)
        if cache is not None:
            cache[key] = (doc, part)
    positions = [p for p in doc["positions"] if part["rows"][p["context_id"]]["published"]]
    fv_sum, fv_filled = _sum(positions, TOTALS_FIELD)
    fv_sum += sum((f["fair_value"] for f in census_published.r7_cash_axis_facts(doc, part["period_end"])),
                  Decimal(0))
    pct_sum, pct_filled = _sum(positions, PCT_FIELD)
    anchor = _num((financials or {}).get("investments_at_fair_value"))
    no_pe = bool(part.get("no_period_end"))
    residual = None if no_pe or anchor in (None, Decimal(0)) else float(100 * (fv_sum - anchor) / anchor)
    return dict(n_positions=len(positions), fv_sum=float(fv_sum), fv_filled=fv_filled,
                fv_anchor=None if anchor is None else float(anchor), fv_residual_pct=residual,
                pct_sum=float(pct_sum), pct_filled=pct_filled,
                anchor_source=ANCHOR_SOURCE if anchor is not None else None,
                published_version=part["version"], removed_by_rule=part["removed_by_rule"],
                extra_fv_facts=len(part["extra_fv_facts"]), no_period_end=no_pe,
                near_misses=part["near_misses"], r7_conflicts=len(part["r7_conflicts"]))


def _contract(cik, field, tier, band, learn_status, learn_cause, expectation, evidence):
    return dict(contract_id=cik + ":" + KIND + ":" + field + ":" + PARTITION, cik=cik, kind=KIND, field=field,
                partition_id=PARTITION, applies_to=dict(APPLIES_TO), tier=tier, band=dict(band),
                learn_status=learn_status, learn_cause=learn_cause, expectation=expectation,
                evidence=evidence, status_basis="provisional")


def learn_totals(cik: str, tier: str, band: dict, q1_doc: dict, *, financials_q1: dict | None) -> list[dict]:
    obs = observe_totals(q1_doc, financials=financials_q1, cik=cik)
    few = obs["n_positions"] < band["min_positions"]
    out = []
    if obs["no_period_end"]:
        return [_contract(cik, f, tier, band, "insufficient_evidence", "no_period_end", None, obs) for f in FIELDS]
    if few:
        out.append(_contract(cik, TOTALS_FIELD, tier, band, "insufficient_evidence", "too_few_positions", None, obs))
    elif obs["fv_anchor"] is None:
        out.append(_contract(cik, TOTALS_FIELD, tier, band, "insufficient_evidence", "no_anchor", None, obs))
    else:
        out.append(_contract(cik, TOTALS_FIELD, tier, band, "learned", None,
                             dict(anchor_source=ANCHOR_SOURCE, fv_residual_pct_q1=obs["fv_residual_pct"]),
                             dict(obs, income=INCOME_LABEL)))
    if few or obs["pct_filled"] < band["min_positions"]:
        out.append(_contract(cik, PCT_FIELD, tier, band, "insufficient_evidence",
                             "too_few_positions" if few else "pct_not_filled", None, obs))
    else:
        out.append(_contract(cik, PCT_FIELD, tier, band, "learned", None, dict(pct_sum_q1=obs["pct_sum"]), obs))
    return out


def _result(c, status, q2, *, cause=None, expected=None, observed=None):
    return dict(contract_id=c["contract_id"], cik=c["cik"], kind=c["kind"], field=c["field"],
                partition_id=c["partition_id"], applies_to=c["applies_to"], tier=c["tier"], status=status,
                cause=cause, expected=expected, observed=observed, violating_keys=[], q2=q2, band=c["band"],
                status_basis="provisional")


def evaluate_totals(contract: dict, q2: dict, q2_doc: dict, *, financials_q2: dict | None, band: dict,
                    cache: dict | None = None) -> dict:
    obs = observe_totals(q2_doc, financials=financials_q2, cik=contract["cik"], cache=cache)
    exp = contract["expectation"]
    if obs["no_period_end"]:
        return _result(contract, "insufficient_evidence", q2, cause="no_period_end", expected=exp, observed=obs)
    # Whole-book gate, shared by both fields: when the book itself is smaller than
    # min_positions, "too_few_positions" is the true cause for BOTH fields. A field
    # that is merely sparsely filled within an adequately sized book is a different
    # cause (pct_not_filled below) and is checked only after this gate passes.
    if obs["n_positions"] < band["min_positions"]:
        return _result(contract, "insufficient_evidence", q2, cause="too_few_positions", expected=exp, observed=obs)
    if contract["field"] == TOTALS_FIELD:
        if obs["fv_residual_pct"] is None:
            return _result(contract, "insufficient_evidence", q2, cause="no_anchor", expected=exp, observed=obs)
        if abs(obs["fv_residual_pct"]) > band["fv_residual_pct"]:
            return _result(contract, "breach", q2, cause="fv_residual_outside_band", expected=exp, observed=obs)
        return _result(contract, "holds", q2, expected=exp, observed=obs)
    if obs["pct_filled"] < band["min_positions"]:
        return _result(contract, "insufficient_evidence", q2, cause="pct_not_filled", expected=exp, observed=obs)
    if obs["pct_sum"] < band["pct_sum_min"] or obs["pct_sum"] > band["pct_sum_max"]:
        return _result(contract, "breach", q2, cause="pct_sum_outside_band", expected=exp, observed=obs)
    if abs(obs["pct_sum"] - exp["pct_sum_q1"]) > band["pct_sum_shift_pp"]:
        return _result(contract, "breach", q2, cause="pct_sum_shifted", expected=exp, observed=obs)
    return _result(contract, "holds", q2, expected=exp, observed=obs)
