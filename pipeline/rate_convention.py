"""Per-CIK interest-rate reporting-convention classifier (measurement only).

Decides, for each BDC filer with PIK evidence, whether the tagged/stored
``interest_rate`` is the ALL-IN coupon (PIK included) or the CASH leg only
(PIK on top). This is the prerequisite the retired ``pik_le_interest_rate``
identity rule named: a field that distinguishes cash-leg from all-in storage.
It does NOT modify holdings -- it writes an audited artifact that a future
normalization transform (interest_rate -> all-in) will consume.

Signals, in order of authority:

  S0  tag fingerprint (concept QName + linkbase labels): the us-gaap SOI
      taxonomy has THREE position-rate elements -- InvestmentInterestRate
      (bare), InvestmentInterestRatePaidInCash and ...PaidInKind. A filer
      whose stored interest_rate column is dominated by PaidInCash facts has
      machine-readably declared cash-leg storage; a filer whose bare rate
      arithmetically equals cash + PIK within contexts has proven all-in.
      Label guard: observed concept MISUSE (Main Street tags PaidInCash with
      plabel "PIK Rate"; First Eagle tags PaidInKind as a concentration, not
      a rate) means a cash_leg conviction additionally requires presentation-
      linkbase labels that do not contradict the concept, else it abstains.
      Built by scripts/build_s0_convention_signal.py from cached instance
      XML + SEC BDC dataset pre.tsv; consumed here via S0_CONVENTION_SIGNAL_FILE.
  S1  ordering violations (tagged numbers only): rows with
      interest_rate < pik_rate PROVE cash-leg storage (PIK cannot exceed an
      all-in rate that contains it). Asymmetric: zero violations proves
      nothing (cash legs are usually larger than PIK legs).
  S2  income reconciliation (source-anchored): under accrual accounting PIK
      interest is inside the income statement's interest income. Predicted
      quarterly interest under all-in storage = sum(interest*principal)/4;
      under cash-leg storage the PIK term is added on top. The ratio
      r = (interest_income - base) / pik_add is ~0 for all-in filers and ~1
      for cash-leg filers. The filer produced interest_income independently
      of position-rate tagging, so this signal cannot be satisfied by our
      own parsing.
  S3  phrasing votes (only text contact; three global regexes, recomputed
      live each run -- no stored per-CIK grammar to go stale): explicit
      "N% cash" phrasing votes cash-leg, "incl ... PIK" votes all-in.
  S4  stability: violations concentrated in some quarters but absent in
      others (both well-populated) suggest a format change -> unknown.

Labels: cash_leg | all_in | unknown | no_pik (immaterial PIK exposure).
Conservative by design: conflicting signals produce unknown, never a guess.

Cache-only, read-only over data/output inputs. ASCII-only logs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.config import (
    UNIFIED_HOLDINGS_FILE,
    BDC_FUND_INCOME_FILE,
    RATE_CONVENTION_FILE,
    RATE_CONVENTION_OVERRIDES_DIR,
    S0_CONVENTION_SIGNAL_FILE,
)

logger = logging.getLogger(__name__)

METHOD_VERSION = "1.0"

# --- decision thresholds (documented so the audit trail is interpretable) ---
MIN_PIK_ROWS = 5            # below this, PIK exposure is immaterial -> no_pik
MIN_DUAL_ROWS = 10          # S1 needs enough dual-rate rows to convict
# Any GENUINE interest<pik row proves cash-leg storage; the gate below only
# guards against parse noise. Known cash-leg filers (Barings 14%, Golub 7-8%)
# sit well under a naive 20% rate threshold because most of their positions
# have cash > PIK -- hence rate + absolute-count, not rate alone.
S1_VIOLATION_RATE = 0.05    # minimum share of dual-rate rows violating
S1_VIOLATION_COUNT = 8      # ... and at least this many violating rows
S1_HIGH_CONF_RATE = 0.40
INCOME_R_ALL_IN = 0.35      # median r at or below -> all_in vote
INCOME_R_CASH = 0.65        # median r at or above -> cash_leg vote
INCOME_MIN_QUARTERS = 2     # informative quarters needed for an income vote
INCOME_MIN_PIK_SHARE = 0.03  # pik_add/base below this -> quarter uninformative
INCOME_COVERAGE_BAND = (0.4, 2.5)  # base/interest_income sanity (extraction coverage)
# interest_income is tagged for only ~14% of quarterly income rows. Fallback:
# estimate it as total_investment_income * (1 - non_interest_share), share
# calibrated per CIK from quarters carrying both, else the cross-sectional
# median. Estimated quarters carry fee noise into r, so they face stricter
# gates: a larger PIK signal and wider decision margins.
INCOME_EST_MIN_PIK_SHARE = 0.10
INCOME_EST_R_ALL_IN = 0.25
INCOME_EST_R_CASH = 0.75
# A strongly negative r means predicted base income alone OVERSHOOTS actual
# interest income -- a measurement problem (non-accruals, principal/coverage
# noise), not evidence of all-in storage. Such quarters must not vote all_in.
INCOME_R_FLOOR = -0.25
# Statistical ceiling (all_in conviction): confirmed cash-leg filers violate on
# 7-40% of dual rows because borrower PIK legs routinely exceed cash legs. A
# filer with MANY rows where pik sits near/at the interest_rate cap
# (pik >= 0.8*ir, incl. exact equality = 100%-PIK positions) yet ZERO rows
# above it exhibits a hard ceiling at exactly ir -- the signature of pik being
# a SUBSET of ir (all-in storage), not an independent leg that never once
# crossed it.
CEILING_MIN_DUAL = 60
CEILING_MIN_NEARCAP = 8
# S5 spread arithmetic (ALL_IN-ONLY evidence): for floating PIK rows, when
# ir = spread + SOFR_q + pik the spread is the cash spread while ir includes
# PIK -- an unambiguous all-in signature. The converse (ir = spread + SOFR_q)
# is AMBIGUOUS, not cash evidence: "incl. PIK" filers quote an all-in spread
# too, so ir - spread - SOFR ~ 0 holds under BOTH conventions (held-out eval
# 2026-07-12: a cash vote from d0~0 wrongly convicted 14 gold all-in filers).
# SOFR_q is implied internally as the per-quarter median of (ir - spread) over
# NON-PIK floating rows, where the convention question does not exist.
S5_ROW_MARGIN = 0.10
S5_MIN_ROWS = 8
S5_DOMINANCE = 3            # d1-rows must dominate d0-rows 3x for the vote
PHRASE_MIN_ROWS = 3         # decisive phrasing needs >=3 rows and 3x dominance
STABILITY_MIN_ROWS = 5      # per-quarter dual rows for the S4 split test
# S0 tag fingerprint (concept QName evidence from cached instance XML).
# wb/wc = contexts where the bare / PaidInCash concept won the pipeline's
# stored interest_rate column under bdc_filings first-match-wins semantics.
S0_MIN_STORED = 50          # minimum wb+wc contexts before S0 can speak
S0_CASH_SHARE = 0.90        # wc share at/above this -> stored column is cash-leg
S0_ALLIN_MAX_CASH_SHARE = 0.05  # all_in proof requires ~no cash contamination
S0_MIN_TRIPLE = 30          # contexts tagging bare+cash+pik for the sum test
S0_SUM_OK_SHARE = 0.80      # bare ~= cash+pik must hold on this share of triples
S0_MIXED_LOW = 0.10         # wc share inside (LOW, CASH_SHARE) with volume ->
S0_MIXED_MIN_STORED = 200   # ... stored column mixes concept semantics; flag it
S0_MIXED_MIN_CASH = 100     # (migration must use per-row provenance, not a
                            # single per-CIK convention)


def s0_from_fingerprint(wb: int, wc: int, triple: int, sum_ok: int,
                        label_status: str = "no_labels") -> dict:
    """Pure S0 decision over one CIK's tag fingerprint.

    wb / wc: contexts where the bare / PaidInCash concept won the stored
    interest_rate column. triple / sum_ok: contexts tagging bare+cash+pik and
    those where bare ~= cash + pik held. label_status: 'ok_cash' (PaidInCash
    labels look like cash-rate labels), 'contradiction' (labels contradict the
    concept -- observed filer misuse), or 'no_labels' (no dataset coverage).
    Returns {s0_vote, s0_confidence, s0_mixed, s0_reason}.
    """
    out = {"s0_vote": None, "s0_confidence": None, "s0_mixed": False,
           "s0_reason": ""}
    denom = (wb or 0) + (wc or 0)
    if denom < S0_MIN_STORED:
        return out
    share = wc / denom
    if share >= S0_CASH_SHARE:
        if label_status == "contradiction":
            out["s0_reason"] = (
                f"cash-concept dominant ({wc}/{denom}) but linkbase labels "
                "contradict the concept (tag misuse) -- S0 abstains")
            return out
        out["s0_vote"] = "cash_leg"
        out["s0_confidence"] = "high" if label_status == "ok_cash" else "medium"
        out["s0_reason"] = (
            f"stored interest_rate won by InvestmentInterestRatePaidInCash in "
            f"{wc}/{denom} contexts (labels: {label_status})")
        if share < 0.99:
            out["s0_reason"] += "; residual bare-concept rows -> use per-row provenance at migration"
        return out
    if (share <= S0_ALLIN_MAX_CASH_SHARE and triple >= S0_MIN_TRIPLE
            and sum_ok >= S0_SUM_OK_SHARE * triple):
        out["s0_vote"] = "all_in"
        out["s0_confidence"] = "high"
        out["s0_reason"] = (
            f"bare rate == cash + PIK within {sum_ok}/{triple} triple-tagged "
            f"contexts (arithmetic all-in proof; cash share {share:.0%})")
        return out
    if (denom >= S0_MIXED_MIN_STORED and wc >= S0_MIXED_MIN_CASH
            and share >= S0_MIXED_LOW):
        out["s0_mixed"] = True
        out["s0_reason"] = (
            f"stored interest_rate mixes concept semantics (bare {wb} vs "
            f"PaidInCash {wc} contexts) -- per-CIK convention is ill-posed; "
            "migration must use per-row concept provenance")
    return out


def classify_cik(stats: dict) -> dict:
    """Pure decision rule over one CIK's aggregated signals.

    ``stats`` keys: n_pik_rows, n_dual, n_viol, n_cash_phrase, n_incl_phrase,
    income_r_median, income_quarters (informative count), unstable (bool);
    optional S0 keys: s0_vote, s0_confidence, s0_mixed, s0_reason.
    Returns {convention, confidence, basis, reasons}.
    """
    def _i(key):
        v = stats.get(key)
        return 0 if v is None or pd.isna(v) else int(v)

    n_pik = _i("n_pik_rows")
    n_dual = _i("n_dual")
    n_viol = _i("n_viol")
    viol_rate = (n_viol / n_dual) if n_dual else 0.0
    n_cash = _i("n_cash_phrase")
    n_incl = _i("n_incl_phrase")
    r_med = stats.get("income_r_median")
    if r_med is not None and pd.isna(r_med):
        r_med = None
    r_quarters = _i("income_quarters")
    unstable = bool(stats.get("unstable"))

    reasons: list[str] = []
    if n_pik < MIN_PIK_ROWS:
        return {"convention": "no_pik", "confidence": "high", "basis": "immaterial",
                "reasons": [f"only {n_pik} PIK rows (< {MIN_PIK_ROWS})"]}

    # income vote (S2): pre-aggregated per-quarter votes (source-specific
    # thresholds applied in aggregation); a side needs >= INCOME_MIN_QUARTERS
    # votes and 2x dominance over the opposing side.
    v_allin = _i("income_votes_allin")
    v_cash = _i("income_votes_cash")
    income_vote = None
    if v_allin >= INCOME_MIN_QUARTERS and v_allin >= 2 * v_cash and v_allin > v_cash:
        income_vote = "all_in"
    elif v_cash >= INCOME_MIN_QUARTERS and v_cash >= 2 * v_allin and v_cash > v_allin:
        income_vote = "cash_leg"
    if income_vote:
        reasons.append(f"income votes allin={v_allin} cash={v_cash} "
                       f"(r_median={r_med if r_med is None else round(float(r_med), 2)}, "
                       f"{r_quarters} informative quarters) -> {income_vote}")

    # phrasing vote (S3)
    phrase_vote = None
    if n_cash >= PHRASE_MIN_ROWS and n_cash > 3 * n_incl:
        phrase_vote = "cash_leg"
        reasons.append(f"phrasing: {n_cash} explicit-cash rows vs {n_incl} incl rows")
    elif n_incl >= PHRASE_MIN_ROWS and n_incl > 3 * n_cash:
        phrase_vote = "all_in"
        reasons.append(f"phrasing: {n_incl} incl rows vs {n_cash} explicit-cash rows")

    # S5 spread-arithmetic vote (all_in only; d0-dominance is ambiguous)
    s5_d0 = _i("s5_rows_d0")
    s5_allin = _i("s5_rows_allin")
    s5_vote = None
    if s5_allin >= S5_MIN_ROWS and s5_allin >= S5_DOMINANCE * s5_d0 and s5_allin > s5_d0:
        s5_vote = "all_in"
        reasons.append(f"spread arithmetic: {s5_allin} rows fit ir=spread+bench+pik "
                       f"vs {s5_d0} ambiguous -> all_in")

    other_says_allin = "all_in" in (income_vote, s5_vote, phrase_vote)
    other_says_cash = "cash_leg" in (income_vote, s5_vote, phrase_vote)

    s1_convicts = (n_dual >= MIN_DUAL_ROWS and viol_rate >= S1_VIOLATION_RATE
                   and n_viol >= S1_VIOLATION_COUNT)
    n_nearcap = _i("n_nearcap")
    ceiling_fires = (n_viol == 0 and n_dual >= CEILING_MIN_DUAL
                     and n_nearcap >= CEILING_MIN_NEARCAP)

    # S0 tag fingerprint: concept-QName evidence about the STORED column.
    s0_vote = stats.get("s0_vote") or None
    s0_conf = stats.get("s0_confidence") or "medium"
    s0_reason = str(stats.get("s0_reason") or "")
    if bool(stats.get("s0_mixed")):
        reasons.append(f"S0: {s0_reason}" if s0_reason else
                       "S0: mixed concept semantics in stored interest_rate")
    # Only NUMERIC signals (S1/ceiling/income/S5) can block an S0 conviction.
    # S3 phrasing infers the convention from "N% cash" text; the S0 sum test
    # directly measures the stored value against that same printed
    # decomposition, so a phrasing-only disagreement is recorded, not blocking
    # (WhiteHorse: 589/594 sum proof + 0/300 violations + ceiling, yet 11
    # "x% cash" phrase rows -- the phrase describes the decomposition).
    numeric_says_cash = "cash_leg" in (income_vote, s5_vote)
    numeric_says_allin = "all_in" in (income_vote, s5_vote)
    if s0_vote == "all_in":
        reasons.insert(0, f"S0: {s0_reason}")
        if s1_convicts:
            reasons.append(f"CONFLICT: ordering violations {n_viol}/{n_dual} "
                           "say cash_leg despite S0 arithmetic all-in proof")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "s0_s1_conflict", "reasons": reasons}
        if numeric_says_cash:
            reasons.append("CONFLICT: a numeric signal says cash_leg despite S0 all-in proof")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "s0_conflict", "reasons": reasons}
        if phrase_vote == "cash_leg":
            reasons.append("note: cash phrasing present but non-blocking "
                           "(S0 sum test measures the same printed decomposition)")
        return {"convention": "all_in", "confidence": "high",
                "basis": "tag_fingerprint", "reasons": reasons}
    if s0_vote == "cash_leg":
        reasons.insert(0, f"S0: {s0_reason}")
        if ceiling_fires:
            reasons.append(f"CONFLICT: hard ceiling (0 violations in {n_dual} "
                           f"dual rows, {n_nearcap} near-cap) says all_in "
                           "despite S0 cash-concept dominance")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "s0_ceiling_conflict", "reasons": reasons}
        if numeric_says_allin:
            reasons.append("CONFLICT: a numeric signal says all_in despite S0 cash-concept dominance")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "s0_conflict", "reasons": reasons}
        if phrase_vote == "all_in":
            reasons.append("note: incl-PIK phrasing present but non-blocking")
        conf = "high" if (s0_conf == "high" or s1_convicts) else "medium"
        if s1_convicts:
            reasons.append(f"ordering violations {n_viol}/{n_dual} corroborate")
        return {"convention": "cash_leg", "confidence": conf,
                "basis": "tag_fingerprint", "reasons": reasons}

    # S1 conviction: violations prove cash_leg (unless another signal contradicts)
    if (n_dual >= MIN_DUAL_ROWS and viol_rate >= S1_VIOLATION_RATE
            and n_viol >= S1_VIOLATION_COUNT):
        reasons.insert(0, f"ordering violations {n_viol}/{n_dual} ({viol_rate:.0%})")
        if other_says_allin:
            reasons.append("CONFLICT: another signal says all_in despite violations")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "s1_conflict", "reasons": reasons}
        if unstable:
            reasons.append("violations unstable across quarters (format change?)")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "s1_unstable", "reasons": reasons}
        conf = "high" if viol_rate >= S1_HIGH_CONF_RATE else "medium"
        return {"convention": "cash_leg", "confidence": conf,
                "basis": "ordering_violations", "reasons": reasons}

    # Statistical ceiling: zero violations + heavy near-cap mass convicts all_in
    n_nearcap = _i("n_nearcap")
    if (n_viol == 0 and n_dual >= CEILING_MIN_DUAL and n_nearcap >= CEILING_MIN_NEARCAP):
        reasons.insert(0, f"hard ceiling: 0 violations in {n_dual} dual rows with "
                          f"{n_nearcap} near-cap rows (pik >= 0.8*interest)")
        if other_says_cash:
            reasons.append("CONFLICT: another signal says cash_leg despite ceiling")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "ceiling_conflict", "reasons": reasons}
        conf = "high" if ("all_in" in (income_vote, s5_vote)) else "medium"
        return {"convention": "all_in", "confidence": conf,
                "basis": "statistical_ceiling", "reasons": reasons}

    # Numeric votes (income, spread arithmetic) decide when S1/ceiling cannot
    numeric = [v for v in (income_vote, s5_vote) if v]
    if numeric:
        if len(set(numeric)) > 1:
            reasons.append("CONFLICT: income and spread arithmetic disagree")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "s2_s5_conflict", "reasons": reasons}
        vote = numeric[0]
        if phrase_vote and phrase_vote != vote:
            reasons.append(f"CONFLICT: phrasing says {phrase_vote}")
            return {"convention": "unknown", "confidence": "low",
                    "basis": "numeric_s3_conflict", "reasons": reasons}
        conf = "high" if (len(numeric) == 2 or phrase_vote == vote) else "medium"
        basis = ("income_reconciliation" if income_vote == vote and s5_vote != vote
                 else "spread_arithmetic" if s5_vote == vote and income_vote != vote
                 else "income_and_spread")
        return {"convention": vote, "confidence": conf, "basis": basis,
                "reasons": reasons}

    # S3 alone: weakest acceptable basis
    if phrase_vote:
        return {"convention": phrase_vote, "confidence": "low",
                "basis": "phrasing_only", "reasons": reasons}

    reasons.append("no decisive signal (violations below threshold, income uninformative, phrasing sparse)")
    return {"convention": "unknown", "confidence": "low", "basis": "no_signal",
            "reasons": reasons}


def _aggregate_signals(
    holdings: pd.DataFrame, income: pd.DataFrame
) -> pd.DataFrame:
    """DuckDB aggregation of S1-S4 signal inputs per CIK. Pure over the frames."""
    con = duckdb.connect()
    con.register("h", holdings)
    con.register("inc", income)

    base = con.execute("""
        WITH bdc AS (
            SELECT ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') AS cik,
                   CAST(report_date AS VARCHAR) AS q,
                   TRY_CAST(interest_rate AS DOUBLE) AS ir,
                   TRY_CAST(pik_rate AS DOUBLE) AS pik,
                   TRY_CAST(principal_amount AS DOUBLE) AS prin,
                   lower(COALESCE(bdc_investment_identifier, '')) AS ident
            FROM h WHERE lower(COALESCE(source, '')) = 'bdc'
        ),
        pik_rows AS (SELECT * FROM bdc WHERE pik > 0 OR ident LIKE '%pik%'),
        per_cik AS (
            SELECT cik,
                COUNT(*) AS n_pik_rows,
                SUM(CASE WHEN pik > 0 AND ir IS NOT NULL THEN 1 ELSE 0 END) AS n_dual,
                -- 0.01pp epsilon: ir == pik is LEGITIMATE under all-in storage
                -- (100%-PIK positions report the PIK rate as the all-in), and
                -- float noise on equal values must not count as violations.
                SUM(CASE WHEN pik > 0 AND ir IS NOT NULL AND ir < pik - 0.01 THEN 1 ELSE 0 END) AS n_viol,
                SUM(CASE WHEN pik > 0 AND ir IS NOT NULL
                          AND (pik >= 0.8 * ir OR abs(ir - pik) <= 0.01)
                         THEN 1 ELSE 0 END) AS n_nearcap,
                SUM(CASE WHEN regexp_matches(ident, '[0-9][0-9.,]*\\s*%[^a-z]{0,6}cash|cash[^a-z]{0,6}[0-9][0-9.,]*\\s*%')
                         THEN 1 ELSE 0 END) AS n_cash_phrase,
                SUM(CASE WHEN regexp_matches(ident, 'incl[a-z.]*[^a-z]{0,25}pik|pik[^a-z]{0,25}incl')
                         THEN 1 ELSE 0 END) AS n_incl_phrase
            FROM pik_rows GROUP BY cik
        )
        SELECT * FROM per_cik
    """).df()

    # S2: quarterly income reconciliation ratio r = (interest_income - base)/pik_add.
    # interest_income is sparsely tagged; estimated quarters (total_investment_income
    # scaled by a calibrated non-interest share) face stricter gates.
    r_q = con.execute("""
        WITH bdc AS (
            SELECT ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') AS cik,
                   CAST(report_date AS VARCHAR) AS q,
                   TRY_CAST(interest_rate AS DOUBLE) AS ir,
                   TRY_CAST(pik_rate AS DOUBLE) AS pik,
                   TRY_CAST(principal_amount AS DOUBLE) AS prin
            FROM h WHERE lower(COALESCE(source, '')) = 'bdc'
        ),
        pred AS (
            SELECT cik, q,
                   SUM(CASE WHEN ir > 0 AND prin > 0 THEN ir/100.0*prin/4.0 ELSE 0 END) AS base,
                   SUM(CASE WHEN pik > 0 AND prin > 0 THEN pik/100.0*prin/4.0 ELSE 0 END) AS pik_add
            FROM bdc GROUP BY cik, q
        ),
        inq AS (
            SELECT ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') AS cik,
                   CAST(report_date AS VARCHAR) AS q,
                   max(TRY_CAST(interest_income AS DOUBLE)) AS ii,
                   max(TRY_CAST(total_investment_income AS DOUBLE)) AS tii
            FROM inc
            WHERE TRY_CAST(duration_months AS DOUBLE) BETWEEN 2 AND 4
            GROUP BY 1, 2
        ),
        shares AS (   -- per-CIK non-interest share of total income, where both tagged
            SELECT cik, median(1.0 - ii / tii) AS share
            FROM inq WHERE ii > 0 AND tii > 0 AND ii <= tii GROUP BY cik
        ),
        gshare AS (
            SELECT COALESCE(median(1.0 - ii / tii), 0.08) AS gs
            FROM inq WHERE ii > 0 AND tii > 0 AND ii <= tii
        ),
        income_eff AS (
            SELECT i.cik, i.q,
                   CASE WHEN i.ii > 0 THEN i.ii
                        ELSE i.tii * (1.0 - COALESCE(s.share, (SELECT gs FROM gshare)))
                   END AS income,
                   CASE WHEN i.ii > 0 THEN 'tagged' ELSE 'est' END AS src
            FROM inq i LEFT JOIN shares s USING (cik)
            WHERE i.ii > 0 OR i.tii > 0
        )
        SELECT p.cik, p.q, e.src,
               (e.income - p.base) / p.pik_add AS r,
               p.pik_add / p.base AS pik_share
        FROM pred p JOIN income_eff e ON p.cik = e.cik AND substr(p.q,1,10) = substr(e.q,1,10)
        WHERE p.pik_add > 0 AND p.base > 0 AND e.income > 0
          AND p.base / e.income BETWEEN ? AND ?
    """, [INCOME_COVERAGE_BAND[0], INCOME_COVERAGE_BAND[1]]).df()

    if len(r_q):
        tagged = r_q["src"] == "tagged"
        informative = ((tagged & (r_q["pik_share"] >= INCOME_MIN_PIK_SHARE))
                       | (~tagged & (r_q["pik_share"] >= INCOME_EST_MIN_PIK_SHARE)))
        r_q = r_q[informative].copy()
    if len(r_q):
        tagged = r_q["src"] == "tagged"
        in_floor = r_q["r"] >= INCOME_R_FLOOR
        r_q["vote_allin"] = (in_floor & ((tagged & (r_q["r"] <= INCOME_R_ALL_IN))
                             | (~tagged & (r_q["r"] <= INCOME_EST_R_ALL_IN)))).astype(int)
        r_q["vote_cash"] = ((tagged & (r_q["r"] >= INCOME_R_CASH))
                            | (~tagged & (r_q["r"] >= INCOME_EST_R_CASH))).astype(int)
        r_agg = r_q.groupby("cik").agg(
            income_r_median=("r", "median"), income_quarters=("r", "count"),
            income_votes_allin=("vote_allin", "sum"),
            income_votes_cash=("vote_cash", "sum")).reset_index()
    else:
        r_agg = pd.DataFrame(columns=["cik", "income_r_median", "income_quarters",
                                      "income_votes_allin", "income_votes_cash"])

    # S5: spread arithmetic on floating PIK rows. SOFR_q implied from NON-PIK
    # floating rows (their ir is unambiguous), so the signal is self-contained.
    s5 = con.execute("""
        WITH bdc AS (
            SELECT ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') AS cik,
                   CAST(report_date AS VARCHAR) AS q,
                   TRY_CAST(interest_rate AS DOUBLE) AS ir,
                   TRY_CAST(pik_rate AS DOUBLE) AS pik,
                   TRY_CAST(basis_spread AS DOUBLE) AS spr
            FROM h WHERE lower(COALESCE(source, '')) = 'bdc'
        ),
        sofr AS (
            SELECT q, median(ir - spr) AS bench
            FROM bdc
            WHERE spr > 0 AND ir > 0 AND (pik IS NULL OR pik = 0)
            GROUP BY q HAVING COUNT(*) >= 25
        ),
        rows5 AS (
            SELECT b.cik,
                   b.ir - b.spr - s.bench AS d0,
                   b.ir - b.spr - s.bench - b.pik AS d1
            FROM bdc b JOIN sofr s ON b.q = s.q
            WHERE b.pik > 0 AND b.spr > 0 AND b.ir > 0
        )
        SELECT cik,
               SUM(CASE WHEN abs(d0) + ? < abs(d1) THEN 1 ELSE 0 END) AS s5_rows_d0,
               SUM(CASE WHEN abs(d1) + ? < abs(d0) THEN 1 ELSE 0 END) AS s5_rows_allin
        FROM rows5 GROUP BY cik
    """, [S5_ROW_MARGIN, S5_ROW_MARGIN]).df()

    # S4: per-quarter violation split (well-populated quarters disagreeing)
    stab = con.execute("""
        WITH bdc AS (
            SELECT ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') AS cik,
                   CAST(report_date AS VARCHAR) AS q,
                   TRY_CAST(interest_rate AS DOUBLE) AS ir,
                   TRY_CAST(pik_rate AS DOUBLE) AS pik
            FROM h WHERE lower(COALESCE(source, '')) = 'bdc'
        ),
        per_q AS (
            SELECT cik, q, COUNT(*) AS n,
                   SUM(CASE WHEN ir < pik - 0.01 THEN 1 ELSE 0 END) AS v
            FROM bdc WHERE pik > 0 AND ir IS NOT NULL
            GROUP BY cik, q HAVING COUNT(*) >= ?
        )
        SELECT cik,
               SUM(CASE WHEN v * 1.0 / n >= 0.2 THEN 1 ELSE 0 END) AS q_viol,
               SUM(CASE WHEN v = 0 THEN 1 ELSE 0 END) AS q_clean
        FROM per_q GROUP BY cik
    """, [STABILITY_MIN_ROWS]).df()
    con.close()

    out = (base.merge(r_agg, on="cik", how="left")
               .merge(s5, on="cik", how="left")
               .merge(stab, on="cik", how="left"))
    out["unstable"] = (out.get("q_viol", 0).fillna(0) >= 2) & (out.get("q_clean", 0).fillna(0) >= 2)
    return out


def load_s0_signal(path: Path = S0_CONVENTION_SIGNAL_FILE) -> dict:
    """{int_cik: {s0_vote, s0_confidence, s0_mixed, s0_reason}} from the S0
    artifact (scripts/build_s0_convention_signal.py). Empty dict if absent."""
    p = Path(path)
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    out: dict[int, dict] = {}
    for _, r in df.iterrows():
        try:
            cik = int(r["cik"])
        except (ValueError, TypeError):
            continue
        out[cik] = {
            "s0_vote": (str(r["s0_vote"]) if pd.notna(r.get("s0_vote"))
                        and str(r.get("s0_vote")) else None),
            "s0_confidence": (str(r["s0_confidence"])
                              if pd.notna(r.get("s0_confidence")) else None),
            "s0_mixed": bool(r.get("s0_mixed")),
            "s0_reason": str(r["s0_reason"]) if pd.notna(r.get("s0_reason")) else "",
        }
    return out


def build_rate_convention(
    holdings: pd.DataFrame | None = None,
    income: pd.DataFrame | None = None,
    *,
    suppress_phrasing: bool = False,
    s0: dict | None = None,
) -> pd.DataFrame:
    """Classify every BDC CIK with PIK evidence. Frames are injectable for tests;
    ``suppress_phrasing`` zeroes S3 before deciding (held-out evaluation mode).
    ``s0``: optional {int_cik: s0-signal dict} (load_s0_signal); opt-in so
    injected-frame runs and tests are unaffected unless provided."""
    if holdings is None:
        holdings = pd.read_csv(UNIFIED_HOLDINGS_FILE, low_memory=False,
                               usecols=["source", "cik", "report_date", "interest_rate",
                                        "pik_rate", "principal_amount", "basis_spread",
                                        "bdc_investment_identifier"])
    if income is None:
        income = pd.read_csv(BDC_FUND_INCOME_FILE, low_memory=False)

    out_cols = ["cik", "convention", "confidence", "basis", "n_pik_rows", "n_dual",
                "n_viol", "n_cash_phrase", "n_incl_phrase", "income_r_median",
                "income_quarters", "income_votes_allin", "income_votes_cash",
                "n_nearcap", "s5_rows_d0", "s5_rows_allin",
                "unstable", "s0_vote", "s0_confidence", "mixed_tag_semantics",
                "reasons", "method_version"]
    sig = _aggregate_signals(holdings, income)
    if len(sig) == 0:
        return pd.DataFrame(columns=out_cols)
    rows = []
    for _, s in sig.iterrows():
        stats = s.to_dict()
        if suppress_phrasing:
            stats["n_cash_phrase"] = 0
            stats["n_incl_phrase"] = 0
        s0_stats = (s0 or {}).get(int(s["cik"]), {})
        stats.update(s0_stats)
        r = classify_cik(stats)
        rows.append({
            "cik": str(s["cik"]).zfill(10),
            "convention": r["convention"],
            "confidence": r["confidence"],
            "basis": r["basis"],
            "n_pik_rows": int(s["n_pik_rows"]),
            "n_dual": int(s["n_dual"] or 0),
            "n_viol": int(s["n_viol"] or 0),
            "n_cash_phrase": int(s["n_cash_phrase"] or 0),
            "n_incl_phrase": int(s["n_incl_phrase"] or 0),
            "income_r_median": (round(float(s["income_r_median"]), 3)
                                if pd.notna(s.get("income_r_median")) else None),
            "income_quarters": (int(s["income_quarters"])
                                if pd.notna(s.get("income_quarters")) else 0),
            "income_votes_allin": (int(s["income_votes_allin"])
                                   if pd.notna(s.get("income_votes_allin")) else 0),
            "income_votes_cash": (int(s["income_votes_cash"])
                                  if pd.notna(s.get("income_votes_cash")) else 0),
            "n_nearcap": int(s["n_nearcap"]) if pd.notna(s.get("n_nearcap")) else 0,
            "s5_rows_d0": (int(s["s5_rows_d0"])
                           if pd.notna(s.get("s5_rows_d0")) else 0),
            "s5_rows_allin": (int(s["s5_rows_allin"])
                              if pd.notna(s.get("s5_rows_allin")) else 0),
            "unstable": bool(s.get("unstable")),
            "s0_vote": s0_stats.get("s0_vote") or "",
            "s0_confidence": s0_stats.get("s0_confidence") or "",
            "mixed_tag_semantics": bool(s0_stats.get("s0_mixed")),
            "reasons": " | ".join(r["reasons"]),
            "method_version": METHOD_VERSION,
        })
    return pd.DataFrame(rows).sort_values("cik").reset_index(drop=True)


def load_convention_overrides(overrides_dir: Path = RATE_CONVENTION_OVERRIDES_DIR) -> dict:
    """{cik_unpadded: promoted convention leaf} from the adjudicator override
    store. utf-8-sig: sandbox workers write BOMs."""
    out: dict[str, dict] = {}
    d = Path(overrides_dir)
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("unreadable convention override skipped: %s", p.name)
            continue
        cik = str(leaf.get("cik") or p.stem).lstrip("0")
        if cik:
            out[cik] = leaf
    return out


def apply_convention_overrides(df: pd.DataFrame, overrides: dict) -> pd.DataFrame:
    """Merge adjudicated verdicts into the deterministic table (pure).

    - an override supersedes a deterministic ``unknown``;
    - an override NEVER silently beats a deterministic conviction: on
      contradiction the row demotes to unknown/demoted_override and the CIK
      re-enters the adjudication queue (self-detecting staleness);
    - ``indeterminate`` is terminal: distinct from unknown, consumed by the
      migration as the conservative-default flag;
    - ``no_pik`` rows are never touched (the verdict is irrelevant there).
    """
    if not overrides or len(df) == 0:
        return df
    df = df.copy()
    for i, row in df.iterrows():
        ov = overrides.get(str(row["cik"]).lstrip("0"))
        if ov is None or row["convention"] == "no_pik":
            continue
        ov_conv = str(ov.get("convention") or "")
        tier_conf = "high" if str(ov.get("verify_tier") or "") == "HIGH" else "medium"
        det = row["convention"]
        if ov_conv == "indeterminate":
            df.loc[i, ["convention", "confidence", "basis"]] = \
                ["indeterminate", tier_conf, "adjudicated_indeterminate"]
            df.loc[i, "reasons"] = f"{row['reasons']} | adjudicated indeterminate (filing silent)"
        elif det == "unknown":
            df.loc[i, ["convention", "confidence", "basis"]] = \
                [ov_conv, tier_conf, "adjudicated_override"]
            df.loc[i, "reasons"] = f"{row['reasons']} | adjudicated: {ov_conv}"
        elif det == ov_conv:
            df.loc[i, "confidence"] = "high"
            df.loc[i, "reasons"] = f"{row['reasons']} | adjudicated verdict corroborates"
        else:
            df.loc[i, ["convention", "confidence", "basis"]] = \
                ["unknown", "low", "demoted_override"]
            df.loc[i, "reasons"] = (f"{row['reasons']} | STALE OVERRIDE: adjudicated "
                                    f"{ov_conv} but deterministic signals now say {det} "
                                    f"-- re-adjudicate")
    return df


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s0 = load_s0_signal()
    if s0:
        logger.info("S0 tag-fingerprint signal loaded for %d CIKs", len(s0))
    df = build_rate_convention(s0=s0 or None)
    df = apply_convention_overrides(df, load_convention_overrides())
    RATE_CONVENTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RATE_CONVENTION_FILE, index=False)
    summary = df[df["convention"] != "no_pik"].groupby(
        ["convention", "confidence"]).size().to_dict()
    logger.info("rate_convention: %d CIKs classified -> %s",
                len(df), RATE_CONVENTION_FILE.name)
    logger.info("label x confidence (excl no_pik): %s",
                json.dumps({f"{k[0]}/{k[1]}": v for k, v in sorted(summary.items())}))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
