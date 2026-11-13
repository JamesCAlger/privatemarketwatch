"""Deterministic checks behind round 2 of the 2026-11-13 verdict-retirement campaign (standing rule D-252).

Same contract as campaign_retirement_check.py (whose filing reader, printed-line locator and quarter
tests this reuses): a real-error verdict is retired only when the check recomputes the verdict's own
claim on today's published data and finds every row it is about at the value printed on that row's own
line (the <tr> carrying the row's own context's fair-value fact). A check that went silent is never
evidence. Modes:

  D06   "issuer_name carries instrument text / hierarchy labels / suffixes, so issuers do not persist".
        Every published row of the quarter AND of the previous published quarter has an issuer_name equal
        (case, punctuation, footnote markers ignored) to the issuer printed on its own line: the line's
        first cell, or, where the first cell is an instrument or blank, the issuer of the nearest line
        above in the same table.
  FX01  "non-USD debt principal published without principal_amount_usd". Every published debt row whose
        own line prints a non-USD currency (code or symbol) carries that currency in
        principal_amount_currency, the printed par in principal_amount (its own principal fact), and a
        principal_amount_usd; within one currency the usd/local ratio is one rate.
  FX02  "fair_value_currency is a foreign unit (par currency bled into the valuation)". Every published
        row has a US-dollar fair_value_currency and a fair value equal to its own context's US-dollar
        fair-value fact.
  X07   "cost (or fair value) is not the row's own printed figure / a row is mis-classed non-equity".
        Every published row's cost and fair value equal its own context's facts (sign included); a cited
        row the verdict says is equity is published as PRIVATE_EQUITY.
  X02   "a credit row is published with neither rate nor spread although its line prints one / a non-credit
        row (equity, warrant, subtotal, continuation line) is published as credit". Per verdict: cited
        loans carry the printed margin (D-031 reading) or the printed rate; cited non-credit rows are not
        PRIVATE_CREDIT; subtotal/continuation claims: every published row is a position with its own fair
        value fact, one row per context.
  pik_le_interest_rate  "interest_rate holds the cash leg where the line prints cash and PIK legs; the
        all-in coupon is cash + PIK". Every published row whose own context carries a PIK rate fact and
        whose line prints the cash and PIK legs separately has interest_rate = cash + PIK and pik_rate =
        PIK. (The identity rule itself was retired 2026-06-19, so its silence is by scope.)
  E07   position-count / aggregate claims. A count claim passes when the published rows of the quarter
        are exactly the filing's position contexts dated the report date that carry a fair value (no
        position missing, none extra, one row per context, each equal to its own fact). Claims about a
        figure the holdings do not carry (purchases, liabilities, borrowings) are not testable and fail.

    python scripts/v05_evidence/campaign_round2_check.py build --rule D06 --review-ids ... --holdings H --ledger L --verdict-dir V --out res.json
    python scripts/v05_evidence/campaign_round2_check.py verify --store S --holdings H [--plant]
Read-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "v05_evidence"))
import campaign_retirement_check as base  # noqa: E402
from campaign_retirement_check import filing, printed_value, row_fv, row_period, _eq, FV  # noqa: E402
from agenta_retirement_check import field_ok  # noqa: E402
from pipeline import config  # noqa: E402

RULES = ("D06", "FX01", "FX02", "X07", "X02", "pik_le_interest_rate", "E07")
COST = "InvestmentOwnedAtCost"
PRINC = "InvestmentOwnedBalancePrincipalAmount"
RATE = "InvestmentInterestRate"
PIKR = "InvestmentInterestRatePaidInKind"
CASHR = "InvestmentInterestRatePaidInCash"
SPREAD = "InvestmentBasisSpreadVariableRate"

COLS = base.COLS + """, CAST(asset_class AS VARCHAR) asset_class, TRY_CAST("cost" AS DOUBLE) AS "cost",
    TRY_CAST(interest_rate AS DOUBLE) interest_rate, TRY_CAST(basis_spread AS DOUBLE) basis_spread,
    TRY_CAST(pik_rate AS DOUBLE) pik_rate, TRY_CAST(principal_amount AS DOUBLE) principal_amount,
    CAST(principal_amount_currency AS VARCHAR) principal_amount_currency,
    TRY_CAST(principal_amount_usd AS DOUBLE) principal_amount_usd,
    CAST(fair_value_currency AS VARCHAR) fair_value_currency"""


def quarter_rows(con, holdings: str, cik: str, rd: str, keep_underlying: bool = False) -> list[dict]:
    extra = "" if keep_underlying else "AND coalesce(CAST(accounting_record_class AS VARCHAR),'')<>'underlying_schedule'"
    df = con.execute(f"""SELECT {COLS} FROM read_parquet('{holdings}')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')=? AND CAST(report_date AS VARCHAR)[:10]=? {extra}
        ORDER BY row_id""", [cik, rd]).fetchdf()
    return df.astype(object).where(df.notna(), None).to_dict("records")


def previous_quarter(con, holdings: str, cik: str, rd: str) -> str | None:
    r = con.execute(f"""SELECT max(CAST(report_date AS VARCHAR)[:10]) FROM read_parquet('{holdings}')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')=? AND CAST(report_date AS VARCHAR)[:10] < ?""", [cik, rd]).fetchone()
    return r[0] if r else None


def own_fact(r: dict, name: str) -> dict | None:
    fl = filing(r["cik"], r["accession_number"])
    fs = [f for f in fl.facts.get((name, r["src_context_id"]), []) if f["value"] is not None] if fl.ok else []
    usd = [f for f in fs if fl.is_usd(f)]
    return (usd or fs or [None])[0]


def pct(f: dict | None) -> float | None:
    """A rate fact as a percent (facts are decimals: 0.0525 -> 5.25)."""
    if f is None:
        return None
    v = f["value"]
    return v * 100.0 if abs(v) < 1.5 else v


# ------------------------------------------------------------------------------------------------ D06

FOOT = re.compile(r"(\(\s*[a-z0-9]{1,3}\s*\)|[\*\^#†‡+]|\s\d{1,2}(?=\s|$))", re.I)
INSTR = re.compile(r"\b(first|second|1st|2nd|lien|term loan|revolv|delayed draw|ddtl|notes?|common|preferred|warrants?|"
                   r"units?|equity|stock|shares?|interests?|senior|subordinat|unitranche|one stop|loan|debt|"
                   r"membership|partnership|class [a-z0-9])\b", re.I)


def name_key(s: str | None) -> str:
    s = FOOT.sub(" ", str(s or ""))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _cells(fl, tr_path: str) -> list[str]:
    return fl.cells_by_tr.get(tr_path) or []


def printed_issuer(r: dict) -> tuple[str | None, str]:
    """(issuer printed for the row, how it was read)."""
    fl = filing(r["cik"], r["accession_number"])
    tr = next((f["tr"] for f in fl.facts.get((FV, r["src_context_id"]), []) if f["tr"]), None)
    if tr is None:
        return None, "no printed line"
    cells = _cells(fl, tr)
    first = cells[0] if cells else ""
    if first and not INSTR.search(first) and re.search(r"[A-Za-z]{2}", first):
        return first, "first cell"
    # carried: nearest line above in the same table whose first cell is a name
    prev = fl.prev_trs.get(tr, [])
    for p in prev:
        c = _cells(fl, p)
        if c and c[0] and not INSTR.search(c[0]) and re.search(r"[A-Za-z]{2}", c[0]) \
                and not re.match(r"(?i)total\b", c[0]):
            return c[0], "carried from the line above"
    return (first or None), "first cell (instrument-like)"


def check_issuer(r: dict) -> tuple[bool, str]:
    iss, how = printed_issuer(r)
    if iss is None:
        return False, "issuer not read from the line"
    ok = name_key(r["issuer_name"]) == name_key(iss)
    if not ok:
        # the printed cell may hold issuer then instrument ('Acme, LLC - Term Loan'); accept the issuer
        # as the leading part only when the remainder is instrument text
        k, ki = name_key(r["issuer_name"]), name_key(iss)
        rest = re.sub(r"^[\s,\-:|]+", "", base.normalise(iss)[len(r["issuer_name"] or ""):]) if ki.startswith(k) and k else ""
        ok = bool(k) and ki.startswith(k) and bool(INSTR.search(rest)) and base.normalise(iss).lower().startswith(
            base.normalise(r["issuer_name"] or "").lower())
    return ok, "published %r, printed %r (%s)" % (r["issuer_name"], iss[:80], how)


# ------------------------------------------------------------------------------------------------ FX

CUR = re.compile(r"(?<![A-Za-z])(EUR|GBP|CAD|AUD|NZD|SEK|NOK|DKK|CHF|JPY|C\$|A\$|NZ\$)(?![A-Za-z])")
CUR_MAP = {"C$": "CAD", "A$": "AUD", "NZ$": "NZD"}


def printed_currency(line: str) -> str | None:
    found = {CUR_MAP.get(m, m) for m in CUR.findall(line or "")}
    return found.pop() if len(found) == 1 else ("AMBIGUOUS" if found else None)


def is_usd_text(s) -> bool:
    return str(s or "").strip().upper() in ("USD", "U_USD", "ISO4217:USD", "US$")


# ------------------------------------------------------------------------------------------------ tests

_H10 = {}


def h10_rate(cur: str, rd: str) -> float | None:
    """USD per unit from data/reference/monetary_conversion/fred_h10_usd_per_unit.csv: the quote on the
    report date or the latest within seven days before it."""
    from datetime import date, timedelta
    if not _H10:
        p = ROOT / "data" / "reference" / "monetary_conversion" / "fred_h10_usd_per_unit.csv"
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    _H10.setdefault(r["currency"].upper(), {})[r["date"]] = float(r["usd_per_unit"])
                except ValueError:
                    continue
    q = _H10.get(cur.upper(), {})
    d = date.fromisoformat(rd)
    for k in range(0, 8):
        v = q.get((d - timedelta(days=k)).isoformat())
        if v is not None:
            return v
    return None


def t_fx01(rows, ctx) -> list[dict]:
    fails, ratios = [], {}
    for r in rows:
        if r["index_classification"] != "DIRECT_LENDING":
            continue
        line = base.row_line(r) or ""
        cur = printed_currency(line)
        pub = (r["principal_amount_currency"] or "").strip().upper() or "USD"
        if cur == "AMBIGUOUS":
            fails.append({"row_id": r["row_id"], "test": "currency", "why": "two currencies on the line: %s" % line[:120]})
            continue
        if cur is None:
            if pub not in ("USD", ""):
                fails.append({"row_id": r["row_id"], "test": "currency", "why": "published %s, line prints none" % pub})
            continue
        if pub != cur:
            fails.append({"row_id": r["row_id"], "test": "currency", "why": "published %s, printed %s" % (pub, cur)})
            continue
        fl = filing(r["cik"], r["accession_number"])
        tr = next((f["tr"] for f in fl.facts.get((FV, r["src_context_id"]), []) if f["tr"]), None)
        pf = own_fact(r, PRINC)
        if pf is not None and pf["tr"] == tr and tr is not None:
            # the par fact printed on the row's own line, in the units it prints
            ok = _eq(r["principal_amount"], printed_value(fl, pf), 1.0)
            why = "published %s, printed %s" % (r["principal_amount"], printed_value(fl, pf))
        else:
            # no par fact on the line (or a hidden USD par fact): the published local par must be the
            # figure the line prints, at the schedule's scale
            unit = 10 ** fl.dominant_fv_scale()
            tok = "{:,.0f}".format((r["principal_amount"] or 0) / unit) if r["principal_amount"] else None
            ok = bool(tok) and tok in (fl.cells_by_tr.get(tr) or []) + line.split()
            why = "published %s (%s at the schedule scale) %s on the line" % (r["principal_amount"], tok,
                                                                               "printed" if ok else "not printed")
        if not ok:
            fails.append({"row_id": r["row_id"], "test": "principal", "why": why})
            continue
        if r["principal_amount_usd"] is None:
            fails.append({"row_id": r["row_id"], "test": "principal_usd", "why": "blank on a %s row" % cur})
            continue
        if r["principal_amount"]:
            ratios.setdefault(cur, []).append((r["row_id"], r["principal_amount_usd"] / r["principal_amount"]))
    for cur, rs in ratios.items():
        vals = [x for _, x in rs]
        if max(vals) - min(vals) > 1e-4 * max(abs(v) for v in vals):
            fails.append({"test": "fx_rate", "why": "%s rows converted at %d different rates (%.6f..%.6f)"
                          % (cur, len(set(round(v, 6) for v in vals)), min(vals), max(vals))})
    ctx["fx_rates"] = {c: rs[0][1] for c, rs in ratios.items()}
    ctx["fx_rows"] = sum(len(v) for v in ratios.values())
    return fails


def t_fx02(rows, ctx) -> list[dict]:
    fails = []
    for r in rows:
        if not is_usd_text(r["fair_value_currency"]) and str(r["fair_value_currency"] or "").strip():
            fails.append({"row_id": r["row_id"], "test": "fair_value_currency", "why": str(r["fair_value_currency"])})
            continue
        ok, why = row_fv(r, require_fact=False)
        if not ok:
            fails.append({"row_id": r["row_id"], "test": "fair_value", "why": why})
    return fails


def t_cost_fv(rows) -> list[dict]:
    fails = []
    for r in rows:
        ok, why = row_fv(r, require_fact=False)
        if not ok:
            fails.append({"row_id": r["row_id"], "test": "fair_value", "why": why})
        cf = own_fact(r, COST)
        if cf is None:
            if r["cost"] not in (None, 0.0) and filing(r["cik"], r["accession_number"]).fv_facts(r["src_context_id"]):
                fails.append({"row_id": r["row_id"], "test": "cost", "why": "published %s, no cost fact" % r["cost"]})
            continue
        fl = filing(r["cik"], r["accession_number"])
        cfs = [f for f in fl.facts.get((COST, r["src_context_id"]), []) if f["value"] is not None]
        cfs = [f for f in cfs if fl.is_usd(f)] or cfs
        ok, v, note = base.match_printed(fl, cfs, r["cost"], 1.0)
        if not ok and not (r["cost"] is None and printed_value(fl, cf) == 0.0):
            fails.append({"row_id": r["row_id"], "test": "cost", "why": "published %s, printed %s%s" % (r["cost"], v, note)})
    return fails


def t_positions(rows, require_fact=True) -> list[dict]:
    """every row a position with its own fair-value fact at the report date, one row per context"""
    fails, seen = [], {}
    for r in rows:
        ok, why = row_period(r)
        if not ok:
            fails.append({"row_id": r["row_id"], "test": "period", "why": why})
            continue
        ok, why = row_fv(r, require_fact=require_fact)
        if not ok:
            fails.append({"row_id": r["row_id"], "test": "fair_value", "why": why})
        k = (r["accession_number"], r["src_context_id"])
        if k in seen:
            fails.append({"row_id": r["row_id"], "test": "duplicate_context", "why": "same context as %s" % seen[k]})
        seen.setdefault(k, r["row_id"])
    return fails


def all_in_expected(r: dict) -> tuple[float | None, str]:
    """The all-in coupon printed on the row's line: cash + PIK where the legs print separately."""
    pikf = own_fact(r, PIKR)
    if pikf is None:
        return None, "no PIK fact"
    pik = pct(pikf)
    line = base.row_line(r) or ""
    if re.search(r"(?i)incl", line):
        rf = own_fact(r, RATE)
        return (pct(rf), "line prints an all-in rate including PIK") if rf else (None, "includes-PIK line, no rate fact")
    cf = own_fact(r, CASHR) or own_fact(r, RATE)
    if cf is None:
        return pik, "PIK-only coupon"
    if cf["shown"] and pikf["shown"] and cf["tr"] == pikf["tr"]:
        return round(pct(cf) + pik, 6), "cash %s + PIK %s printed separately" % (pct(cf), pik)
    return None, "cash and PIK legs not both on the line"


def t_pik(rows, cited=None) -> list[dict]:
    fails = []
    for r in rows:
        if own_fact(r, PIKR) is None:
            continue
        if cited and not cited_match(r, cited):
            continue
        exp, why = all_in_expected(r)
        if exp is None:
            fails.append({"row_id": r["row_id"], "test": "interest_rate", "why": "cannot read the all-in coupon: " + why})
            continue
        pk = pct(own_fact(r, PIKR))
        if not (_eq(r["interest_rate"], exp, 0.006) and _eq(r["pik_rate"], pk, 0.006)):
            fails.append({"row_id": r["row_id"], "test": "interest_rate",
                          "why": "published rate %s pik %s; printed all-in %s (%s), PIK %s" % (
                              r["interest_rate"], r["pik_rate"], exp, why, pk)})
    return fails


def cited_match(r: dict, spec: dict) -> bool:
    if not re.search(spec["issuer"], r["issuer_name"] or "", re.I):
        return False
    if spec.get("instrument") and not re.search(spec["instrument"], r["instrument_description"] or "", re.I):
        return False
    line = base.row_line(r) or ""
    return bool(re.search(spec["issuer"], line, re.I))   # the row's own line names the issuer


def t_rate_present(r: dict) -> tuple[bool, str]:
    """A credit row carries the printed margin (D-031) or the printed rate."""
    line = base.row_line(r) or ""
    if r["basis_spread"] is not None:
        ok, why = field_ok("basis_spread", r["basis_spread"], line)
        if ok:
            return True, "spread " + why
    for name in (RATE, CASHR, PIKR):
        f = own_fact(r, name)
        if f is not None and r["interest_rate"] is not None:
            exp, _ = all_in_expected(r) if name == PIKR or own_fact(r, PIKR) else (pct(f), "")
            if exp is not None and _eq(r["interest_rate"], exp, 0.006):
                return True, "rate %s printed" % exp
    return False, "published rate %s spread %s; line: %s" % (r["interest_rate"], r["basis_spread"], line[:120])


def position_contexts(fl, rd: str) -> set:
    """Contexts of positions dated the report date that carry a fair value (InvestmentIdentifierAxis)."""
    return {cx for (n, cx) in fl.facts if n == FV and (fl.contexts.get(cx) or {}).get("instant") == rd
            and "us-gaap:InvestmentIdentifierAxis" in fl.contexts[cx]["dims"] and fl.fv_facts(cx)}


# ------------------------------------------------------------------------------------------------ dispatch

def check(rule: str, spec: dict, con, holdings: str, cik: str, rd: str, rows=None, prev_rows=None) -> dict:
    rows = rows if rows is not None else quarter_rows(con, holdings, cik, rd)
    ctx = {"n_rows": len(rows), "accessions": sorted({r["accession_number"] for r in rows if r.get("accession_number")})}
    fails = []
    if not rows:
        return {"ok": False, "fails": [{"why": "no published rows"}], "detail": ctx}
    if spec.get("untestable"):
        return {"ok": False, "fails": [{"test": "claim", "why": spec["untestable"]}], "detail": ctx}
    for r in rows:
        ok, why = row_period(r)
        if not ok:
            fails.append({"row_id": r["row_id"], "test": "period", "why": why})
    if rule == "D06":
        prev_q = previous_quarter(con, holdings, cik, rd)
        prev_rows = prev_rows if prev_rows is not None else (quarter_rows(con, holdings, cik, prev_q) if prev_q else [])
        ctx["previous_quarter"], ctx["n_prev_rows"] = prev_q, len(prev_rows)
        for r in rows + prev_rows:
            ok, why = check_issuer(r)
            if not ok:
                fails.append({"row_id": r["row_id"], "test": "issuer_name", "why": why})
        from pipeline.oracle_checks import _d06_issuer_key
        import pandas as pd
        a = set(_d06_issuer_key(pd.Series([r["issuer_name"] for r in prev_rows]))) - {""}
        b = set(_d06_issuer_key(pd.Series([r["issuer_name"] for r in rows]))) - {""}
        ctx["continuity"] = round(len(a & b) / len(a), 4) if a else None
    elif rule == "FX01":
        fails += t_fx01(rows, ctx)
        if ctx.get("fx_rates"):
            # the conversion rate is the admitted reference: the FRED H.10 quote on the report date or the
            # latest within seven days before it (pipeline/monetary_fx.py, the build's own rule)
            for cur, rate in ctx["fx_rates"].items():
                ref = h10_rate(cur, rd)
                ctx.setdefault("fx_reference", {})[cur] = ref
                if ref is None or abs(rate - ref) > 1e-6 * abs(ref):
                    fails.append({"test": "fx_rate", "why": "%s converted at %s; the H.10 reference for %s is %s"
                                  % (cur, rate, rd, ref)})
        if not ctx.get("fx_rows"):
            # nothing to test: no published debt row's own line prints a foreign currency, so the
            # verdict's foreign-par rows cannot be confirmed from their lines
            fails.append({"test": "claim", "why": "no published debt row whose own line prints a foreign currency"})
    elif rule == "FX02":
        fails += t_fx02(rows, ctx)
    elif rule == "X07":
        fails += t_cost_fv(rows)
        for c in spec.get("equity", []):
            hit = [r for r in rows if cited_match(r, c)]
            if not hit:
                fails.append({"test": "cited", "why": "no published row for %s" % c})
            for r in hit:
                if r["asset_class"] != "PRIVATE_EQUITY":
                    fails.append({"row_id": r["row_id"], "test": "class", "why": "%s published %s" % (r["issuer_name"], r["asset_class"])})
    elif rule == "X02":
        for c in spec.get("rated", []):
            hit = [r for r in rows if cited_match(r, c)]
            if not hit:
                fails.append({"test": "cited", "why": "no published row for %s" % c})
            for r in hit:
                ok, why = t_rate_present(r)
                if not ok:
                    fails.append({"row_id": r["row_id"], "test": "rate", "why": why})
        for c in spec.get("not_credit", []):
            hit = [r for r in rows if cited_match(r, c)]
            if not hit:
                fails.append({"test": "cited", "why": "no published row for %s" % c})
            for r in hit:
                if r["asset_class"] == "PRIVATE_CREDIT":
                    fails.append({"row_id": r["row_id"], "test": "class", "why": "%s %s published PRIVATE_CREDIT" % (
                        r["issuer_name"], r["instrument_description"])})
        if spec.get("positions"):
            fails += t_positions(rows)
    elif rule in ("pik_le_interest_rate", "E07") and (spec.get("rate") or rule == "pik_le_interest_rate"):
        if not spec.get("rate"):
            fails += t_pik(rows)          # verdict names no rows: every PIK row of the quarter
        cited_n = 0
        for c in spec.get("rate", []):
            hit = [r for r in rows if cited_match(r, c) and own_fact(r, PIKR) is not None]
            if not hit:
                fails.append({"test": "cited", "why": "no published row with a PIK fact for %s" % c})
            cited_n += len(hit)
            fails += t_pik(hit)
        ctx["cited_rows"] = cited_n
        # recorded, not tested: the quarter's other PIK rows (the claim is about the cited rows)
        ctx["other_pik_rows_not_all_in"] = len(t_pik(rows)) if spec.get("rate") else None
    elif rule == "E07":
        if False:
            pass
        else:
            allrows = quarter_rows(con, holdings, cik, rd, keep_underlying=True)
            fails += t_positions(allrows)
            fl = filing(cik, ctx["accessions"][0]) if len(ctx["accessions"]) == 1 else None
            if fl is None:
                fails.append({"test": "accession", "why": "rows from %d filings" % len(ctx["accessions"])})
            else:
                # a position is an InvestmentIdentifierAxis member with a fair value at the report date;
                # the same member on a second context (a roll-forward table adding an affiliation axis)
                # is the same position, so positions are compared by member, not by context
                ax = "us-gaap:InvestmentIdentifierAxis"
                want = {fl.contexts[cx]["dims"][ax] for cx in position_contexts(fl, rd)}
                have_ctx = {r["src_context_id"] for r in allrows}
                have = {(fl.contexts.get(cx) or {}).get("dims", {}).get(ax) for cx in have_ctx} - {None}
                ctx.update(filing_positions=len(want), published=len(allrows), published_members=len(have),
                           missing=sorted(want - have)[:20], n_missing=len(want - have))
                if want - have:
                    fails.append({"test": "count", "why": "%d positions with a fair value not published (of %d): %s"
                                  % (len(want - have), len(want), sorted(want - have)[:3])})
                if len(have) != len(allrows):
                    fails.append({"test": "count", "why": "%d published rows for %d positions" % (len(allrows), len(have))})
            ok, info = base.quarter_total(rows, cik, rd, total_ctx=spec.get("total_ctx"), anchors=tuple(spec.get("anchors", ())))
            ctx["total"] = info
            if not ok:
                fails.append({"test": "total", "why": info.get("why")})
    return {"ok": not fails, "fails": fails, "detail": ctx}


# ------------------------------------------------------------------------------------------------ plants

def plants(rule: str, spec: dict, rows: list[dict]) -> list[tuple[str, list[dict]]]:
    out = []

    def swap(t, **kw):
        return [dict(r, **kw) if r is t else r for r in rows]
    if not rows:
        return out
    med = sorted(rows, key=lambda r: abs(r["fair_value"] or 0))[len(rows) // 2]
    out.append(("row_from_other_filing", swap(med, accession_number="0000000000-00-000000")))
    if rule == "D06":
        out.append(("instrument_in_issuer", swap(med, issuer_name=(med["issuer_name"] or "") + " First Lien Term Loan")))
        out.append(("hierarchy_label_in_issuer", swap(med, issuer_name="Debt Investments " + (med["issuer_name"] or ""))))
        out.append(("suffix_in_issuer", swap(med, issuer_name=(med["issuer_name"] or "") + " 2")))
    if rule == "FX01":
        fx = [r for r in rows if r["principal_amount_usd"] is not None and (r["principal_amount_currency"] or "USD").upper() != "USD"]
        if fx:
            t = fx[len(fx) // 2]
            out += [("usd_blank", swap(t, principal_amount_usd=None)), ("currency_usd", swap(t, principal_amount_currency="USD")),
                    ("usd_rate_off", swap(t, principal_amount_usd=t["principal_amount_usd"] * 1.05)),
                    ("par_x1000", swap(t, principal_amount=(t["principal_amount"] or 0) * 1000))]
    if rule == "FX02":
        out += [("fv_currency_eur", swap(med, fair_value_currency="U_EUR")),
                ("fv_local_value", swap(med, fair_value=(med["fair_value"] or 0) * 0.92 + 1000))]
    if rule == "X07":
        wc = [r for r in rows if r["cost"]]
        t = wc[len(wc) // 2] if wc else med
        out += [("cost_sign", swap(t, cost=-(t["cost"] or 0) if t["cost"] else 5000.0)),
                ("cost_x1000_short", swap(t, cost=(t["cost"] or 0) / 1000)),
                ("neighbour_fv", swap(t, fair_value=(t["fair_value"] or 0) + 1_000_000))]
        for c in spec.get("equity", []):
            hit = [r for r in rows if cited_match(r, c)]
            if hit:
                out.append(("equity_as_credit", swap(hit[0], asset_class="PRIVATE_CREDIT")))
    if rule == "X02":
        for c in spec.get("rated", [])[:1]:
            hit = [r for r in rows if cited_match(r, c)]
            if hit:
                out.append(("rate_dropped", swap(hit[0], interest_rate=None, basis_spread=None)))
                out.append(("floor_as_spread", swap(hit[0], basis_spread=(hit[0]["basis_spread"] or 0) + 0.75, interest_rate=None)))
        for c in spec.get("not_credit", [])[:1]:
            hit = [r for r in rows if cited_match(r, c)]
            if hit:
                out.append(("equity_as_credit", swap(hit[0], asset_class="PRIVATE_CREDIT")))
        if spec.get("positions"):
            out.append(("continuation_duplicate", rows + [dict(med, row_id="PLANT-DUP")]))
    if rule == "pik_le_interest_rate" or (rule == "E07" and spec.get("rate")):
        # plant on a row the check tests: a cited PIK row (or, with no citation, any PIK row)
        pk = [r for r in rows if r["pik_rate"] and own_fact(r, PIKR) is not None
              and (not spec.get("rate") or any(cited_match(r, c) for c in spec["rate"]))]
        if pk:
            out.append(("cash_leg_only", swap(pk[0], interest_rate=(pk[0]["interest_rate"] or 0) - (pk[0]["pik_rate"] or 0))))
    if rule == "E07" and not spec.get("rate"):
        out += [("row_dropped", [r for r in rows if r is not med]), ("row_doubled", rows + [dict(med, row_id="PLANT-DUP")])]
    return out


# ------------------------------------------------------------------------------------------------ build / verify

def load_specs() -> dict:
    p = ROOT / "scripts" / "v05_evidence" / "campaign_round2_specs.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build(rule, review_ids, holdings, ledger) -> list[dict]:
    led = {}
    with open(ledger, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["review_id"] in review_ids:
                led[r["review_id"]] = r
    specs = load_specs()
    con = base._con()
    out = []
    for rid in review_ids:
        L = led[rid]
        cik, rd = L["cik"].zfill(10), L["report_date"][:10]
        spec = specs.get(rid, {})
        res = check(rule, spec, con, holdings, cik, rd)
        res.update(review_id=rid, cik=cik, report_date=rd, rule_name=rule, engine=L["engine"], spec=spec)
        out.append(res)
        print("%s %s %s %s: %s fails=%d %s" % (rid, cik, rd, rule, "PASS" if res["ok"] else "FAIL", len(res["fails"]),
              ("; ".join(sorted({f.get("test", "") + ": " + str(f["why"])[:100] for f in res["fails"]}))[:500]).encode(
                  "ascii", "replace").decode()), flush=True)
        filing.cache_clear()
    return out


def verify(store: Path, holdings: str, plant: bool) -> int:
    data = json.loads(Path(store).read_text(encoding="utf-8-sig"))
    con = base._con()
    passed = failed = 0
    tally = {}
    for e in data["retirements"]:
        spec = dict(e.get("check_spec", {}), total_ctx=e.get("filed_total_context"))
        rule, cik, rd = e["rule_name"], e["cik"], e["report_date"]
        rows = quarter_rows(con, holdings, cik, rd)
        if not plant:
            res = check(rule, spec, con, holdings, cik, rd, rows=rows)
            ok = res["ok"] and len(rows) == e.get("published_rows", len(rows))
            passed += ok
            failed += not ok
            print("%s %s %s %s: %s" % (e["retirement_id"], e["review_id"], rule, rd, "PASS" if ok else "FAIL"))
            for f in res["fails"][:5]:
                print("   %s" % json.dumps(f)[:300])
            continue
        prev = None
        if rule == "D06":
            pq = previous_quarter(con, holdings, cik, rd)
            prev = quarter_rows(con, holdings, cik, pq) if pq else []
        caught = escaped = 0
        for name, planted in plants(rule, spec, rows):
            bad = check(rule, spec, con, holdings, cik, rd, rows=planted, prev_rows=prev)["ok"]
            tally.setdefault(name, [0, 0])[1 if bad else 0] += 1
            caught += not bad
            escaped += bad
            if bad:
                print("   ESCAPED plant %s" % name)
        ok = escaped == 0 and caught > 0
        passed += ok
        failed += not ok
        print("%s %s %s: planted %d, caught %d, escaped %d" % (e["retirement_id"], rule, rd, caught + escaped, caught, escaped))
        filing.cache_clear()
    if plant:
        print("plants by kind (caught, escaped): %s" % {k: tuple(v) for k, v in sorted(tally.items())})
        print("entries %d: every plant caught in %d, a plant escaped in %d [PLANTED]" % (passed + failed, passed, failed))
    else:
        print("entries %d: pass %d, fail %d" % (passed + failed, passed, failed))
    return 0 if failed == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    hold = str(Path(config.OUTPUT_DIR) / "private_markets_holdings.parquet")
    b = sub.add_parser("build")
    b.add_argument("--rule", required=True, choices=RULES)
    b.add_argument("--review-ids", nargs="+", required=True)
    b.add_argument("--holdings", default=hold)
    b.add_argument("--ledger", required=True)
    b.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--store", required=True)
    v.add_argument("--holdings", default=hold)
    v.add_argument("--plant", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        res = build(a.rule, a.review_ids, Path(a.holdings).as_posix(), a.ledger)
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        return 0
    return verify(Path(a.store), Path(a.holdings).as_posix(), a.plant)


if __name__ == "__main__":
    sys.exit(main())
