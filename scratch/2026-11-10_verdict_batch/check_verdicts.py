"""Deterministic re-check of real-error verdicts against today's published data (standing rule D-252).

For each target verdict (targets.csv: findings reopened as real_error_check_silent) this script parses
what the verdict cites (culprit_citations quoted rows, anchor/observed values) and tests, against the
main checkout's published data, whether every cited row is published at its filed (printed) values
and the defect the verdict names is gone, or the cited row is correctly excluded. Read-only.

    python scratch/2026-11-10_verdict_batch/check_verdicts.py                 # all targets -> results.csv
    python scratch/2026-11-10_verdict_batch/check_verdicts.py --review-id RVQ_REV_xxx   # one verdict, printed
    python scratch/2026-11-10_verdict_batch/check_verdicts.py --write-retirements      # + standing-rule store

Outcomes: PASS (retire under D-252), FAIL (cited error still present), UNCLEAR (rows not identifiable,
no deterministic check for this verdict shape, or judgement needed). Never PASS on "the check no longer
fires": every PASS needs the cited rows (or the cited printed total) matched in the published data.

Families (by rule):
  total_fv   fv_conservation, E01, A04, nav_identity, html_agg: published-basis sum(fair_value) equals the
             verdict's filed total (anchor_value at its scale) within 5e-5; cited holding rows matched.
  total_cost cost_conservation: same on sum(cost).
  pct_sum    A07, F22: published-basis sum(pct_of_net_assets) within 0.5 pt of the filed total pct.
  nav        E04, F11, F30: companyfacts nav_per_share / net_assets equal the cited printed values.
  row_field  FX01/FX02/FX03, C115, C01/dl_rate_fill/X02, C206/fmt_issuer_name, C107, SRC_BDC01:
             each cited holding row found at its printed fair value (+ cost or par) and the named field
             fixed on it; FX rules also need zero offending rows in the fund-quarter.
  pp03       PP03: cited current-period rows present once; cited comparative-period rows (values that
             differ from the current row) absent at the report date.
  b01        B01 (extraction_gap): no published row without fair value in the fund-quarter and every
             cited dash row published at 0.
Limits: name matching is token based (first three significant tokens of the printed issuer); printed
values are matched at the page scale (1, 1e3 or 1e6) to half a unit of the last printed digit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
WT = HERE.parents[1]
MAIN = Path("C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl")
HOLD = MAIN / "data/output/private_markets_holdings.parquet"
FF = MAIN / "data/output/fund_financials.csv"
VERDICT_DIRS = (MAIN / "data/output/review_queue/verdicts", MAIN / "data/output/bdc_cik_review/verdicts")
OUT_STORE = WT / "data/overrides/verdict_retirements/standing_rule_2026-11-10.json"
SCRIPT_REL = "scratch/2026-11-10_verdict_batch/check_verdicts.py"
OWNER_WORDS = "run as recommended (standing rule D-252)"

STOP = {"inc", "llc", "ltd", "lp", "l", "p", "corp", "corporation", "co", "the", "and", "of", "a", "s", "sa",
        "sarl", "bv", "b", "v", "gmbh", "limited", "plc", "dba", "company", "llp", "pte", "pty", "ab", "as", "ag", "nv"}
TOTAL_WORDS = re.compile(r"\b(total|subtotal|net assets|net asset value|shares outstanding|common shares|"
                         r"cash and cash equivalents|investments at fair value|investment portfolio|continuation)\b", re.I)


# ---------------------------------------------------------------- parsing
def norm_tokens(s: str) -> list[str]:
    s = re.sub(r"\((?:\s*[0-9a-z]{1,3}\s*)\)", " ", str(s or "").lower())     # footnote marks (4) (c)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return [t for t in s.split() if t not in STOP]


_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}/\d{4}\b|\b\d{1,2}/\d{2}\b")
_PCT = re.compile(r"[-+]?\d[\d,]*\.?\d*\s*%")
_NUM = re.compile(r"\(\s*\d[\d,]*\.?\d*\s*\)|(?<![\w.])-?\d[\d,]*\.?\d*")


def parse_numbers(text: str) -> list[tuple[float, float]]:
    """Printed numeric cells as (value, half-unit). Percents, dates and rate terms are dropped.
    A bare '-' cell is a printed zero. Parenthesised values are taken as negatives and as positives
    (a footnote mark looks the same)."""
    t = _DATE.sub(" ", text)
    t = _PCT.sub(" ", t)
    t = re.sub(r"\b[SEPCL]\s*\+\s*\d+(?:\.\d+)?", " ", t)          # S + 550, E + 600
    t = re.sub(r"\b(SOFR|SONIA|EURIBOR|CORRA|BBSY|CA|C|E|S|P|L)\s*\+", " ", t)
    out = []
    for m in _NUM.finditer(t):
        tok = m.group(0)
        neg = tok.startswith("(")
        core = tok.strip("()").strip().replace(",", "")
        try:
            v = float(core)
        except ValueError:
            continue
        dec = len(core.split(".")[1]) if "." in core else 0
        half = 0.5 * 10 ** (-dec)
        out.append((-abs(v) if neg else v, half))
        if neg:
            out.append((abs(v), half))
    if re.search(r"(^|\|)\s*-\s*(\||$)|Fair Value\s*-\s*$|Fair Value\s*-\s*\|", text):
        out.append((0.0, 0.5))
    return out


def split_citation(q: str) -> tuple[str, str]:
    """(name, rest) from a quoted citation."""
    q = str(q or "").strip()
    if ":" in q and "|" in q.split(":")[0] and q.split(":")[0].count("|") >= 2:   # 'header | header: Name | ...'
        q = q.split(":", 1)[1].strip()
    if "|" in q:
        name, rest = q.split("|", 1)
    elif " - " in q:
        name, rest = q.split(" - ", 1)
    else:
        # prose citation: '<Issuer> first lien ... shows Principal EUR 937, Cost 1,020 and Market Value 1,046'
        m = re.search(r"\s(?:par amount|principal|shows|first[- ]lien|second[- ]lien|delayed draw|term loan|"
                      r"revolv\w*|senior secured|unsecured|row\b|is\b|has\b|with\b)", q, re.I)
        if m and m.start() > 2:
            name, rest = q[:m.start()], q[m.start():]
        elif ";" in q:
            name, rest = q.split(";", 1)
        else:
            name, rest = q, ""
    name = re.sub(r"^(Raw investment row is|Continuation/subtotal row:?)\s*", "", name.strip(), flags=re.I)
    return name.strip(), rest


def classify_citation(q: str) -> dict:
    name, rest = split_citation(q)
    nums = parse_numbers(rest)
    # a header row prints no number outside footnote parentheses
    if not parse_numbers(re.sub(r"\([^)]*\)", " ", rest)):
        nums = []
    is_total = (bool(TOTAL_WORDS.search(name)) or bool(TOTAL_WORDS.search(q.split("|")[0][:60]))
                or not norm_tokens(name) or not any(ch.isalpha() for ch in name)
                or bool(re.match(r"^(january|february|march|april|may|june|july|august|september|october|"
                                 r"november|december)\b", name.strip(), re.I)))
    return {"quote": q, "name": name, "nums": nums, "is_total": is_total,
            "is_holding": (not is_total) and len(nums) >= 1 and len(norm_tokens(name)) >= 1}


# ---------------------------------------------------------------- data
class Data:
    def __init__(self, pairs: set[tuple[str, str]]):
        con = duckdb.connect()
        con.execute("SET memory_limit='2GB'")
        qs = set(pairs)
        for c, d in pairs:
            qs.add((c, prev_quarter(d)))
        keys = pd.DataFrame(sorted(qs), columns=["cik", "report_date"])
        con.register("keys", keys)
        self.h = con.execute(f"""
            SELECT h.cik, CAST(h.report_date AS VARCHAR) AS report_date, h.source, h.issuer_name,
                   h.instrument_description, h.fair_value, h.cost, h.principal_amount, h.principal_amount_currency,
                   h.principal_amount_usd, h.fair_value_currency, h.cost_currency, h.pct_of_net_assets,
                   h.interest_rate, h.basis_spread, h.index_classification, h.asset_class, h.asset_category, h.exposure_type, h.pik_rate,
                   COALESCE(h.accounting_record_class, '') AS arc, h.row_id
            FROM read_parquet('{HOLD.as_posix()}') h
            JOIN keys k ON h.cik = k.cik AND CAST(h.report_date AS VARCHAR) = k.report_date""").df()
        self.ff =con.execute(f"""SELECT cik, report_date, source, nav_per_share, net_assets, shares_outstanding,
                   investments_at_fair_value FROM read_csv_auto('{FF.as_posix()}', all_varchar=true)""").df()
        self.ff["cik"] = self.ff.cik.str.zfill(10)
        self.groups = {k: g for k, g in self.h.groupby(["cik", "report_date"])}
        self._tok_done: set = set()

    def fq(self, cik, rd):
        """One fund-quarter (a few thousand rows at most); name tokens built on first use."""
        g = self.groups.get((cik, rd))
        if g is None:
            g = self.h.iloc[0:0].assign(toks=pd.Series(dtype=object))
            return g
        if (cik, rd) not in self._tok_done:
            g = g.assign(toks=(g.issuer_name.fillna("") + " " + g.instrument_description.fillna("")).map(
                lambda s: set(norm_tokens(s))))
            self.groups[(cik, rd)] = g
            self._tok_done.add((cik, rd))
        return g


def prev_quarter(d: str) -> str:
    y, m = int(d[:4]), int(d[5:7])
    m -= 3
    if m <= 0:
        m += 12
        y -= 1
    import calendar
    last = calendar.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-{last:02d}"


def _eq(x, v, half, s):
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and abs(x - v * s) <= half * s + 1e-6


def match_rows(g: pd.DataFrame, cit: dict) -> tuple[pd.DataFrame, float | None]:
    """Published rows of one fund-quarter whose issuer tokens contain the cited name's first three
    significant tokens and whose fair value (and cost or par, when two or more numbers are printed)
    equal printed cells at one page scale."""
    # 'Issuer, LLC (4) - Preferred Units': the issuer is the part before ' - '
    toks = norm_tokens(cit["name"].split(" - ")[0])[:3]
    if not toks or g.empty:
        return g.iloc[0:0], None
    cand = g[g.toks.map(lambda s: all(t in s for t in toks))]
    if cand.empty:
        return cand, None
    nums = cit["nums"]
    for s in (1e3, 1e6, 1.0):
        def ok(r):
            fv_hits = [i for i, (v, h) in enumerate(nums) if _eq(r.fair_value, v, h, s)]
            if not fv_hits:
                return False
            if len({round(v, 6) for v, _ in nums}) <= 1 or len(nums) == 1:
                return True
            for i, (v, h) in enumerate(nums):
                if (_eq(r.cost, v, h, s) or _eq(r.principal_amount, v, h, s)) and (i not in fv_hits or len(fv_hits) > 1
                                                                                    or abs(v) == 0):
                    return True
                if (_eq(r.cost, v, h, s) or _eq(r.principal_amount, v, h, s)) and nums.count(nums[i]) > 1:
                    return True
            return False
        hit = cand[[ok(r) for r in cand.itertuples()]]
        if not hit.empty:
            return hit, s
    # a citation that prints only the par amount: match the principal instead
    if len({round(v, 6) for v, _ in nums}) == 1 and re.search(r"\bpar\b|principal", cit["quote"], re.I):
        v, h = nums[0]
        for s in (1e3, 1.0, 1e6):
            hit = cand[[_eq(r.principal_amount, v, h, s) for r in cand.itertuples()]]
            if not hit.empty:
                return hit, s
    return cand.iloc[0:0], None


def published(g):
    return g[g.arc.ne("underlying_schedule")]


def fmt_rows(rows: pd.DataFrame, cols=("issuer_name", "principal_amount", "cost", "fair_value", "arc")) -> str:
    out = []
    for r in rows.head(4).itertuples():
        bits = []
        for c in cols:
            v = getattr(r, c)
            if isinstance(v, float):
                v = "" if math.isnan(v) else f"{v:,.0f}" if abs(v) >= 100 else f"{v:g}"
            bits.append(f"{c}={str(v)[:60]}")
        out.append("; ".join(bits))
    return " || ".join(out) + (f" (+{len(rows) - 4} more)" if len(rows) > 4 else "")


def as_float(x):
    try:
        v = float(str(x).replace(",", ""))
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- families
def cited_holdings_present(D, cik, rd, cits, require_all=True):
    """Every cited holding citation matched; returns (ok, lines, matched frames)."""
    g = D.fq(cik, rd)
    lines, frames, missing = [], [], []
    for c in cits:
        if not c["is_holding"]:
            continue
        rows, s = match_rows(g, c)
        if rows.empty:
            missing.append(c["name"][:60])
            lines.append(f"cited row NOT found at printed values: {c['quote'][:140]}")
        else:
            frames.append(rows)
            lines.append(f"cited '{c['name'][:50]}' found x{len(rows)} at scale {s:g}: {fmt_rows(rows)}")
    return (not missing) if require_all else bool(frames), lines, frames, missing


def fam_total(D, t, v, cits, field):
    cik, rd = t.cik, t.report_date
    anchor = as_float(v.get("anchor_value"))
    g = published(D.fq(cik, rd))
    if anchor is None or anchor <= 0:
        return "UNCLEAR", "verdict has no numeric filed total", []
    if g.empty:
        return "FAIL", "no published rows for the fund-quarter", []
    pub = g[field].sum(skipna=True)
    s = min((1.0, 1e3, 1e6), key=lambda k: abs(math.log(max(anchor * k, 1) / max(pub, 1))))
    target = anchor * s
    diff = pub - target
    line = (f"published-basis sum({field}) {pub:,.0f} vs filed total {anchor:g} x {s:g} = {target:,.0f}; "
            f"diff {diff:,.0f} ({diff / target:.6%}); verdict observed {v.get('observed_value')}")
    ok_hold, lines, _, missing = cited_holdings_present(D, cik, rd, cits)
    if abs(diff) <= 5e-5 * target:
        if not ok_hold:
            return "UNCLEAR", "total ties but cited holding rows not found: " + "; ".join(missing), [line] + lines
        return "PASS", f"published sum({field}) equals the filed total the verdict cites", [line] + lines
    if abs(diff) <= 5e-3 * target:
        return "UNCLEAR", (f"cited overshoot gone but published sum({field}) is {diff:,.0f} ({diff / target:.3%}) "
                           "off the filed total; residual needs judgement"), [line] + lines
    return "FAIL", f"published sum({field}) still differs from the filed total by {diff / target:.3%}", [line] + lines


def fam_pct(D, t, v, cits):
    anchor = as_float(v.get("anchor_value"))
    g = published(D.fq(t.cik, t.report_date))
    pct = g.pct_of_net_assets.sum(skipna=True) if g.pct_of_net_assets.notna().any() else None
    filled = int(g.pct_of_net_assets.notna().sum())
    line = f"published-basis pct_of_net_assets: {filled}/{len(g)} rows filled, sum {pct}; filed total pct {anchor}"
    if pct is None or filled == 0:
        return "FAIL", "pct_of_net_assets still not populated on published rows", [line]
    if anchor is None or abs(anchor - 100.0) < 1e-9:
        return "UNCLEAR", "filed anchor is not a percent-of-net-assets total", [line]
    if abs(pct - anchor) <= 0.5:
        return "PASS", "published pct sum equals the filed total pct within 0.5 pt", [line]
    return "FAIL", f"published pct sum {pct:.2f} vs filed {anchor:.2f}", [line]


def fam_nav(D, t, v, cits):
    f = D.ff[(D.ff.cik == t.cik) & (D.ff.report_date == t.report_date)]
    if f.empty:
        return "UNCLEAR", "no fund_financials row", []
    navs = {as_float(x) for x in f.nav_per_share if as_float(x) is not None}
    nas = {as_float(x) for x in f.net_assets if as_float(x) is not None}
    text = " ".join(str(c["quote"]) for c in cits) + " " + str(v.get("anchor_value"))
    printed_nav = set()
    for c in cits:
        q = str(c["quote"])
        if re.search(r"per share|\bNAV\b", q, re.I):
            # first two-decimal amount after the NAV label = the current-period column
            m = re.search(r"(?:per share|\bNAV\b)[^0-9]*?(?:\$\s*\|?\s*)?(\d{1,3}\.\d{2})\b", q, re.I)
            if m:
                printed_nav.add(float(m.group(1)))
            else:
                printed_nav |= {float(x) for x in re.findall(r"\$\s*(\d{1,3}\.\d{2})\b", q)}
    m2 = re.findall(r"Total net assets[^0-9]*([\d,]{6,})", text, flags=re.I)
    printed_na = {float(x.replace(",", "")) for x in m2}
    line = f"fund_financials nav_per_share {sorted(navs)}, net_assets {sorted(nas)}; printed NAV {sorted(printed_nav)}, printed net assets {sorted(printed_na)}"
    if not printed_nav and not printed_na:
        return "UNCLEAR", "no printed NAV or net assets parsed from the verdict", [line]
    ok = True
    if printed_nav:
        ok &= any(abs(n - p) < 0.005 for n in navs for p in printed_nav) and all(abs(n - 1000) > 1 for n in navs)
    if printed_na:
        ok &= any(abs(n - p * s) <= 0.5 * s for n in nas for p in printed_na for s in (1e3, 1.0))
    return ("PASS", "published NAV per share / net assets equal the printed values", [line]) if ok else \
           ("FAIL", "published NAV per share or net assets differ from the printed values", [line])


USD_RE = re.compile(r"(^|[^A-Z])USD([^A-Z]|$)")


def printed_rates(q: str) -> tuple[set, set]:
    """(all printed rate figures in percent, printed spreads in percent). '5.00 %' -> 5.0;
    'S + 550' (basis points) -> 5.5; 'S+ 6.25 %' -> 6.25."""
    pct = {float(x.replace(",", "")) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", q)}
    spreads = set()
    for m in re.finditer(r"(?:\b[A-Z]{1,8}|C\$)\s*\+\s*(\d+(?:\.\d+)?)\s*(%?)", q):
        v = float(m.group(1))
        spreads.add(v / 100 if (not m.group(2) and v >= 20) else v)
    return pct | spreads, spreads


def _in(x, vals, tol=0.006):
    return any(abs(x - v) <= tol for v in vals)


LEAK_RE = re.compile(r"acquisition date|maturity date|of net assets|debt securities,|interest rate|"
                     r"\binvestment type\b|\bindustry\b", re.I)


def is_usd(x):
    s = str(x or "").strip().upper()
    return s in ("", "NAN", "NONE") or bool(USD_RE.search(s))


def fam_row(D, t, v, cits):
    rule = t.rule
    hold = [c for c in cits if c["is_holding"]]
    if not hold:
        return "UNCLEAR", "verdict cites no identifiable holding row with printed values", []
    ok_all, lines, frames, missing = cited_holdings_present(D, t.cik, t.report_date, cits)
    g = D.fq(t.cik, t.report_date)
    agg_line, agg_ok = "", True
    if rule == "FX01":
        bad = g[g.index_classification.eq("DIRECT_LENDING") & ~g.principal_amount_currency.map(is_usd)
                & g.principal_amount.notna() & g.principal_amount_usd.isna()]
        agg_ok, agg_line = bad.empty, f"fund-quarter non-USD debt rows without principal_amount_usd: {len(bad)}"
    elif rule in ("FX02", "FX03"):
        col = "fair_value_currency" if rule == "FX02" else "cost_currency"
        bad = g[g.source.eq("bdc") & ~g[col].map(is_usd)]
        agg_ok, agg_line = bad.empty, f"fund-quarter bdc rows with non-USD {col}: {len(bad)}"
    elif rule == "C01":
        # same population as oracle C01 (funded debt rows), recomputed here on the published rows
        debt = g[(g.index_classification.fillna("").str.lower().isin(
            ["senior_secured_debt", "subordinated_debt", "debt", "senior secured debt", "subordinated debt"]))
            | g.asset_category.fillna("").str.lower().str.contains("debt|loan")]
        debt = debt[debt.fair_value.fillna(0) > 0]
        if len(debt):
            cov = ((debt.interest_rate.fillna(0) != 0) | (debt.basis_spread.fillna(0) != 0)).mean()
            agg_ok, agg_line = cov >= 0.8, f"fund-quarter funded debt rows with a rate: {cov:.1%} of {len(debt)}"
    if agg_line:
        lines.append(agg_line)
    if missing:
        return "UNCLEAR" if agg_ok else "FAIL", ("cited rows not found at printed values: " + "; ".join(missing)
                                                 + ("" if agg_ok else "; " + agg_line)), lines
    if not agg_ok:
        return "FAIL", agg_line, lines
    rows = pd.concat(frames)
    pairs = list(zip([c for c in hold if c["name"][:60] not in missing], frames))
    if rule == "FX01":
        bad = rows[~rows.principal_amount_currency.map(is_usd) & rows.principal_amount_usd.isna()]
        if not bad.empty:
            return "FAIL", "cited non-USD rows still lack principal_amount_usd", lines
        lost = []
        for c, fr in pairs:
            if re.search(r"\b(EUR|GBP|CAD|AUD|NZD|SEK|NOK|DKK|CHF|JPY)\b|C\$|NZ\$|A\$|€|£", c["quote"]):
                lost += [str(r.issuer_name)[:40] for r in fr.itertuples() if is_usd(r.principal_amount_currency)]
        if lost:
            return "FAIL", ("printed non-USD par now published as USD/blank currency (no conversion): "
                            + "; ".join(lost[:3])), lines
        if rows.principal_amount_currency.map(is_usd).all():
            return "UNCLEAR", "cited rows are no longer non-USD (currency changed; needs judgement)", lines
    elif rule in ("FX02", "FX03"):
        col = "fair_value_currency" if rule == "FX02" else "cost_currency"
        if not rows[col].map(is_usd).all():
            return "FAIL", f"cited rows still carry non-USD {col}", lines
    elif rule == "C115":
        lines.append(fmt_rows(rows, ("issuer_name", "basis_spread")))
        bad, unc = [], []
        for c, fr in pairs:
            _, spreads = printed_rates(c["quote"])
            for r in fr.itertuples():
                bs = None if pd.isna(r.basis_spread) else float(r.basis_spread)
                if bs is not None and not (0 <= bs <= 15):
                    bad.append(f"{r.issuer_name[:40]} basis_spread {bs}")
                elif spreads and (bs is None or not _in(bs, spreads)):
                    unc.append(f"{r.issuer_name[:40]} basis_spread {bs} vs printed {sorted(spreads)}")
        if bad:
            return "FAIL", "cited rows: basis_spread still outside 0-15: " + "; ".join(bad[:2]), lines
        if unc:
            return "UNCLEAR", "cited rows: basis_spread not equal to the printed spread: " + "; ".join(unc[:2]), lines
    elif rule in ("C01", "dl_rate_fill", "X02"):
        lines.append(fmt_rows(rows, ("issuer_name", "interest_rate", "basis_spread", "pik_rate")))
        if (rows.interest_rate.isna() & rows.basis_spread.isna()).any():
            return "FAIL", "cited rows still have no interest_rate or basis_spread", lines
        unc = []
        for c, fr in pairs:
            allr, _ = printed_rates(c["quote"])
            if not allr:
                unc.append(f"{c['name'][:40]}: no printed rate parsed")
                continue
            for r in fr.itertuples():
                for col in ("interest_rate", "basis_spread"):
                    x = getattr(r, col)
                    if not pd.isna(x) and not _in(float(x), allr):
                        unc.append(f"{r.issuer_name[:40]} {col} {x} not a printed figure {sorted(allr)}")
                if re.search(r"\bPIK\b", c["quote"]) and (pd.isna(r.pik_rate) or not _in(float(r.pik_rate), allr)) \
                        and (pd.isna(r.interest_rate) or not _in(float(r.interest_rate), allr)):
                    unc.append(f"{r.issuer_name[:40]} printed PIK not carried")
        if unc:
            return "UNCLEAR", "rate present but not shown equal to the printed terms: " + "; ".join(unc[:2]), lines
    elif rule in ("C206", "fmt_issuer_name"):
        bad, unc = [], []
        for c, fr in pairs:
            want = set(norm_tokens(c["name"]))
            for r in fr.itertuples():
                have = set(norm_tokens(r.issuer_name))
                if LEAK_RE.search(str(r.issuer_name)) or len(str(r.issuer_name)) > 120:
                    bad.append(f"{str(r.issuer_name)[:80]}")
                elif not have <= want and (have & want):
                    unc.append(f"{str(r.issuer_name)[:60]} vs printed {c['name'][:50]}")
                elif not (have & want):
                    # citation's first cell is an instrument line (continuation row): name not checkable
                    unc.append(f"printed cell '{c['name'][:40]}' is not an issuer name")
        lines.append(fmt_rows(rows, ("issuer_name", "fair_value")))
        if bad:
            return "FAIL", "cited rows' issuer_name still carries leaked schedule text: " + "; ".join(bad[:2]), lines
        if unc:
            return "UNCLEAR", "issuer_name differs from the printed cell: " + "; ".join(unc[:2]), lines
    elif rule == "C107":
        if rows.cost.notna().any() and (rows.cost < 0).any():
            return "FAIL", "cited rows still carry a negative cost", lines + [fmt_rows(rows)]
    elif rule == "X01":
        pref = [c for c in hold if re.search(r"preferred", c["quote"], re.I)]
        if not pref or len(pref) != len(hold):
            return "UNCLEAR", "X01 verdict does not cite a printed preferred instrument on every row", lines
        if not rows.index_classification.eq("PREFERRED_EQUITY").all():
            return "FAIL", "cited preferred rows not classified PREFERRED_EQUITY", lines + [
                fmt_rows(rows, ("issuer_name", "index_classification", "interest_rate"))]
        lines.append(fmt_rows(rows, ("issuer_name", "index_classification", "interest_rate")))
    elif rule in ("C301", "C303", "C304"):
        col = {"C301": "index_classification", "C303": "exposure_type", "C304": "asset_class"}[rule]
        blank = g[g[col].fillna("").astype(str).str.strip().eq("")]
        lines.append(f"fund-quarter rows with blank {col}: {len(blank)}")
        if len(blank) or rows[col].fillna("").astype(str).str.strip().eq("").any():
            return "FAIL", f"{len(blank)} rows still have blank {col}", lines
        lines.append(fmt_rows(rows, ("issuer_name", col, "fair_value")))
    elif rule == "pct_of_net_assets_identity":
        # identity: pct = fair value / filed net assets; a printed pct on the row must be the published one
        f = D.ff[(D.ff.cik == t.cik) & (D.ff.report_date == t.report_date) & D.ff.source.eq("companyfacts")]
        nav = [as_float(x) for x in f.net_assets if as_float(x)]
        if not nav:
            return "UNCLEAR", "no companyfacts net assets to test the identity", lines
        bad = []
        for c, fr in pairs:
            printed = {float(x.replace(",", "")) for x in re.findall(r"(\d[\d,]*\.?\d*)\s*%", c["quote"])}
            for r in fr.itertuples():
                pv = None if pd.isna(r.pct_of_net_assets) else float(r.pct_of_net_assets)
                calc = 100.0 * float(r.fair_value) / nav[0]
                if pv is None:
                    if _in(calc, printed, 0.06):
                        bad.append(f"{r.issuer_name[:40]} pct missing though the row prints ~{calc:.2f}")
                    continue
                if abs(pv - calc) > 0.06 + 0.01 * abs(calc) and not _in(pv, printed, 0.051):
                    bad.append(f"{r.issuer_name[:40]} pct {pv} vs FV/NA {calc:.3f}")
        lines.append(f"companyfacts net assets {nav[0]:,.0f}")
        lines.append(fmt_rows(rows, ("issuer_name", "pct_of_net_assets", "fair_value")))
        if bad:
            return "FAIL", "cited rows' pct_of_net_assets still off the FV/net-assets identity: " + "; ".join(bad[:2]), lines
    elif rule == "SRC_BDC01":
        pass
    else:
        return "UNCLEAR", f"no field predicate for rule {rule}", lines
    return "PASS", "every cited row is published at its printed values with the named field fixed", lines


def fam_pp03(D, t, v, cits):
    hold = [c for c in cits if c["is_holding"]]
    if not hold:
        return "UNCLEAR", "verdict cites no identifiable holding row with printed values", []
    g, gp = D.fq(t.cik, t.report_date), D.fq(t.cik, prev_quarter(t.report_date))
    lines, verdict_ok, unclear = [], True, []
    by_name: dict[str, list] = {}
    for c in hold:
        by_name.setdefault(" ".join(norm_tokens(c["name"])[:3]), []).append(c)
    for key, cs in by_name.items():
        sigs = {tuple(sorted(round(v_, 3) for v_, _ in c["nums"])) for c in cs}
        res = []
        for c in cs:
            cur, _ = match_rows(g, c)
            prv, _ = match_rows(gp, c)
            # a match that sits only in a JV/subsidiary's own schedule is outside the published basis
            if len(cur) and cur.arc.eq("underlying_schedule").all():
                lines.append(f"'{c['name'][:40]}': at {t.report_date} only as underlying_schedule x{len(cur)} "
                             "(outside the published basis)")
                if len(cs) == 1 and len(prv):
                    # the cited comparative row is still retained under the report date, only unpublished
                    unclear.append(f"{key}: cited comparative row still retained at the report date as "
                                   "underlying_schedule (unpublished); period error not shown fixed")
                    res.append((c, cur, prv))
                    continue
            res.append((c, cur, prv))
            lines.append(f"'{c['name'][:40]}' {c['quote'][-60:]!r}: at {t.report_date} x{len(cur)}, at prior quarter x{len(prv)}")
        if any(u.startswith(key + ":") for u in unclear):
            continue
        if len(cs) == 1:
            c, cur, prv = res[0]
            if len(cur) == 0 and len(prv) >= 1:
                continue          # cited comparative row: absent now, present as the prior quarter's row
            unclear.append(f"{key}: single cited row {'present' if len(cur) else 'absent'} at report date "
                           f"(prior quarter x{len(prv)}); cannot tell current from comparative")
            continue
        if len(sigs) == 1:
            # identical printed rows in both periods: the position must be published once
            n = max(len(r[1]) for r in res)
            if n != 1:
                verdict_ok = False
                lines.append(f"  identical cited rows published x{n} at report date (want 1)")
        else:
            present = [r for r in res if len(r[1]) >= 1]
            absent = [r for r in res if len(r[1]) == 0]
            if len(present) == 1 and absent and all(len(r[1]) == 1 for r in present):
                if not any(len(r[2]) >= 1 for r in absent):
                    unclear.append(f"{key}: absent cited row not found at prior quarter either")
            elif len(present) == 0:
                # only comparative rows cited: they must be absent and be prior-quarter rows
                if not all(len(r[2]) >= 1 for r in res):
                    unclear.append(f"{key}: cited rows absent at report date and not matched at prior quarter")
            else:
                verdict_ok = False
                lines.append(f"  {len(present)} of {len(res)} differing cited rows still published at report date")
    if not verdict_ok:
        return "FAIL", "comparative-period row still published at the report date", lines
    if unclear:
        return "UNCLEAR", "; ".join(unclear), lines
    # guard: a comparative schedule leak inflates the total; published basis must tie to the filed total
    f = D.ff[(D.ff.cik == t.cik) & (D.ff.report_date == t.report_date) & D.ff.source.eq("companyfacts")]
    filed = [as_float(x) for x in f.investments_at_fair_value if as_float(x)]
    pub = published(g).fair_value.sum()
    if not filed:
        return "UNCLEAR", "cited rows clean but no companyfacts investments total to guard the fund-quarter", lines
    gap = (pub - filed[0]) / filed[0]
    lines.append(f"guard: published-basis FV {pub:,.0f} vs companyfacts investments at FV {filed[0]:,.0f} ({gap:.4%})")
    if abs(gap) > 5e-3:
        return "UNCLEAR", f"cited rows clean but fund-quarter FV is {gap:.2%} off the filed total", lines
    return "PASS", "cited comparative-period rows absent at the report date; current rows published once", lines


def fam_b01(D, t, v, cits):
    if v.get("mechanism") != "extraction_gap":
        return "UNCLEAR", f"B01 verdict mechanism {v.get('mechanism')} needs judgement", []
    g = D.fq(t.cik, t.report_date)
    nnull = int(g.fair_value.isna().sum())
    lines = [f"fund-quarter rows without fair_value: {nnull} of {len(g)}"]
    if nnull:
        return "FAIL", f"{nnull} published rows still without fair value", lines
    miss, checked = [], 0
    for c in cits:
        toks = norm_tokens(c["name"])[:3]
        if not toks or c["is_total"]:
            continue
        checked += 1
        cand = g[g.toks.map(lambda s: all(x in s for x in toks))]
        dash = (0.0, 0.5) in c["nums"]
        if not dash:
            hit, _ = match_rows(g, c)       # a valued leaf must be published at its printed values
            if hit.empty:
                miss.append(c["name"][:50] + " (not at printed values)")
        elif cand.empty or not (cand.fair_value == 0).any():
            miss.append(c["name"][:50])
        lines.append(f"'{c['name'][:40]}': {len(cand)} rows, fv {sorted(cand.fair_value.round(0).tolist())[:6]}")
    if miss:
        return "UNCLEAR", "cited dash rows not found at 0: " + "; ".join(miss), lines
    if not checked:
        return "UNCLEAR", "verdict cites no identifiable leaf row; aggregate alone is not enough", lines
    return "PASS", "no published row lacks a fair value and cited dash rows are published at 0", lines


FAMILY = {"fv_conservation": "total_fv", "E01": "total_fv", "A04": "total_fv", "nav_identity": "total_fv",
          "html_agg": "total_fv", "cost_conservation": "total_cost", "A07": "pct", "F22": "pct",
          "E04": "nav", "F11": "nav", "F30": "nav", "PP03": "pp03", "B01": "b01"}
for _r in ("FX01", "FX02", "FX03", "C115", "C01", "dl_rate_fill", "X02", "C206", "fmt_issuer_name", "C107", "SRC_BDC01",
           "X01", "C301", "C303", "C304", "pct_of_net_assets_identity"):
    FAMILY[_r] = "row"


def load_verdict(rid):
    for d in VERDICT_DIRS:
        p = d / f"{rid}.json"
        if p.exists():
            return p, json.loads(p.read_text(encoding="utf-8-sig"))
    return None, None


def evaluate(D, t):
    p, v = load_verdict(t.review_id)
    if v is None:
        return dict(status="UNCLEAR", family="", reason="verdict file not found", lines=[], sha="", path="")
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    if v.get("verdict") != "real_error":
        return dict(status="UNCLEAR", family="", reason=f"verdict is {v.get('verdict')}", lines=[], sha=sha, path=str(p))
    cits = [classify_citation(c.get("quoted_text") or "") for c in (v.get("culprit_citations") or [])
            if c.get("quoted_text")]
    fam = FAMILY.get(t.rule, "")
    if t.rule == "SRC_BDC01" and str(v.get("mechanism")) != "extraction_gap":
        fam = "row"
    try:
        if fam == "total_fv":
            st, why, lines = fam_total(D, t, v, cits, "fair_value")
        elif fam == "total_cost":
            st, why, lines = fam_total(D, t, v, cits, "cost")
        elif fam == "pct":
            st, why, lines = fam_pct(D, t, v, cits)
        elif fam == "nav":
            st, why, lines = fam_nav(D, t, v, cits)
        elif fam == "row":
            st, why, lines = fam_row(D, t, v, cits)
        elif fam == "pp03":
            st, why, lines = fam_pp03(D, t, v, cits)
        elif fam == "b01":
            st, why, lines = fam_b01(D, t, v, cits)
        else:
            st, why, lines = "UNCLEAR", f"no deterministic check for rule {t.rule}", []
    except Exception as e:  # a check that cannot run is never a pass
        st, why, lines = "UNCLEAR", f"check error: {type(e).__name__}: {e}", []
    return dict(status=st, family=fam, reason=why, lines=lines, sha=sha, path=str(p), verdict=v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review-id", action="append")
    ap.add_argument("--write-retirements", action="store_true")
    ap.add_argument("--max-priority", type=int, default=9)
    a = ap.parse_args()
    t = pd.read_csv(HERE / "targets.csv", dtype=str).fillna("")
    t["priority"] = t.priority.astype(int)
    if a.review_id:
        t = t[t.review_id.isin(a.review_id)]
    t = t[t.priority <= a.max_priority]
    D =Data(set(zip(t.cik, t.report_date)))
    print(f"loaded {len(D.h)} published rows for {len(D.groups)} fund-quarters; {len(t)} verdicts", flush=True)
    res = []
    for i, r in enumerate(t.itertuples()):
        out = evaluate(D, r)
        res.append(dict(review_id=r.review_id, cik=r.cik, rule=r.rule, report_date=r.report_date, engine=r.engine,
                        priority=r.priority, v05=r.v05, cohort=r.cohort, src=r.src, family=out["family"],
                        status=out["status"], reason=out["reason"], evidence=" | ".join(out["lines"])[:3000],
                        sha=out["sha"], mechanism=(out.get("verdict") or {}).get("mechanism", "")))
        if a.review_id:
            print(json.dumps({k: res[-1][k] for k in ("review_id", "rule", "report_date", "status", "reason")}))
            for ln in out["lines"]:
                print("   ", ln.encode("ascii", "replace").decode())
        elif i % 100 == 0:
            print(f"  {i}/{len(t)}", flush=True)
    df = pd.DataFrame(res)
    if not a.review_id:
        df.to_csv(HERE / "results.csv", index=False)
        print(df.groupby(["priority", "status"]).size().unstack(fill_value=0).to_string())
    if a.write_retirements:
        write_store(df[df.status.eq("PASS")])


def write_store(p: pd.DataFrame):
    entries = []
    for n, r in enumerate(p.sort_values(["priority", "cik", "report_date", "rule"]).itertuples(), 1):
        if not r.engine:
            print("skip (engine unknown):", r.review_id)
            continue
        entries.append({
            "retirement_id": f"VR-SR-{n:04d}",
            "review_id": r.review_id,
            "verdict_sha256": r.sha,
            "cik": r.cik, "engine": r.engine, "rule_name": r.rule, "report_date": r.report_date,
            "reason": f"Standing rule D-252: deterministic check ({r.family}) shows {r.reason}.",
            "evidence": [
                {"source": "query", "quote": r.evidence.encode("ascii", "replace").decode()[:2000]},
                {"source": "code", "quote": f"{SCRIPT_REL} family {r.family}; published data "
                                            "data/output/private_markets_holdings.parquet (built 2026-11-10)"},
            ],
            "rerun": f"python {SCRIPT_REL} --review-id {r.review_id}",
            "owner_words": OWNER_WORDS,
            "decided_by": "owner", "decided_on": "2026-11-10",
        })
    doc = {"_note": ("Standing rule D-252 (owner 2026-11-10, 'run as recommended'): real-error verdicts retired "
                     "because a deterministic check shows every row the verdict cites is published at its filed "
                     "values, or correctly excluded, in the 2026-11-10 published data. Check: " + SCRIPT_REL + "."),
           "retirements": entries}
    OUT_STORE.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print("wrote", len(entries), "retirements to", OUT_STORE)


if __name__ == "__main__":
    main()
