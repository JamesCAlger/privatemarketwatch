"""Deterministic checks behind the 2026-11-13 verdict-retirement campaign (standing rule D-252).

A real-error verdict is retired only when a deterministic check shows that what the verdict claims is
wrong in the published data is now at its filed values. One mode per rule; each mode tests the
verdict's own claim, not something adjacent:

  A07  "the filing prints a percent of net assets per position and the build publishes none (sum 0)".
       Passes only when every published row of the fund-quarter carries pct_of_net_assets equal to
       the InvestmentOwnedPercentOfNetAssets fact of its OWN context (the printed percent on the row's
       line). A row whose context carries no percent fact cannot be confirmed and fails.
  PP03 "earlier-period (comparative schedule) rows are retained in the quarter".  Passes only when
       every published row of the fund-quarter comes from the quarter's own filing and sits on a
       context whose instant is the report date, and no published row comes from a roll-forward
       table only (its fair-value fact must also be printed on a schedule-of-investments line, i.e.
       a <tr> whose fair-value fact is the row's own context).
  fv_conservation  "the published fair value does not sum to the filed total investments" (with or
       without a named culprit: cash equivalents, look-through, double count, omitted rows).
       Passes only when (a) every published row equals the InvestmentOwnedAtFairValue fact of its own
       context, on a context dated the report date, (b) the published sum equals the filed total
       investments - the undimensioned InvestmentOwnedAtFairValue fact at the report date - within two
       units of the total's own rounding, either over all published rows or over the non-CASH rows (the
       basis used is recorded), and (c) when the non-CASH basis is used, every CASH row is a cash
       equivalent the filer prints outside its total (the CASH sum equals the filed total of investments
       and cash equivalents less the filed total, or the filer's own cash-equivalents fact).
  B01  "leaves without fair value / comparative or structural leaves in the quarter / fair value short
       of the filed total". Passes on the fv_conservation test plus: every published row has a fair
       value fact in its own context (no published row without a filed fair value).
  C04  "equity rows are published without the share count the filing prints". Passes only when every
       published equity row (the rule's own population) sits on a context dated the report date and
       its shares_held equals the count printed on its own line: the InvestmentOwnedBalanceShares (or,
       in a 'Par Amount / Shares' column, InvestmentOwnedBalancePrincipalAmount) fact of its own
       context, the fact element inside the row's <tr>. A row with no tagged count fails (cannot be
       confirmed from the line), unless the line prints a dash in place of a count and nothing is
       published.

The printed line of a published row is the inline-XBRL <tr> that carries the
us-gaap:InvestmentOwnedAtFairValue fact whose contextRef is the row's src_context_id. The filing is
parsed with an XML parser (lxml); facts are read with their scale and sign. Lines are normalised as
scripts/v05_evidence/fund_gate.page_text normalises the page, so every quoted line is a verbatim
substring of the cached page.

    python scripts/v05_evidence/campaign_retirement_check.py build --rule PP03 --review-ids R1 R2 ... --ledger L --out res.json
    python scripts/v05_evidence/campaign_retirement_check.py verify --store data/overrides/verdict_retirements/standing_rule_campaign_PP03_2026-11-13.json
    python scripts/v05_evidence/campaign_retirement_check.py verify --store ... --plant     # every plant must FAIL

Read-only. --holdings defaults to <PM_OUTPUT_DIR or data/output>/private_markets_holdings.parquet.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "v05_evidence"))
from fund_gate import normalise, page_text  # noqa: E402
from pipeline import config  # noqa: E402

NS_IX = "http://www.xbrl.org/2013/inlineXBRL"
NS_XBRLI = "http://www.xbrl.org/2003/instance"
NS_XBRLDI = "http://xbrl.org/2006/xbrldi"
FV = "InvestmentOwnedAtFairValue"
PCT = "InvestmentOwnedPercentOfNetAssets"
SHARES = ("InvestmentOwnedBalanceShares", "InvestmentOwnedBalancePrincipalAmount")
CASH_EQ = ("CashEquivalentsAtCarryingValue", "CashAndCashEquivalentsAtFairValue")
CASH_CONCEPT = re.compile(r"CashEquivalent|MoneyMarket|CashAndCash", re.I)
RULES = ("A07", "PP03", "fv_conservation", "B01", "C04")
FV_TOL = 1.0          # dollars: a published row equals its own fact (facts are exact in their unit)
DASH = re.compile(r"^[\s\-—–$]*$")


# --------------------------------------------------------------------------------------------- filing

def _local(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and "}" in tag else str(tag)


def _num(el) -> float | None:
    """The value of an ix:nonFraction element with its scale and sign; None if unreadable."""
    text = "".join(el.itertext()).strip()
    fmt = (el.get("format") or "").lower()
    if "zero" in fmt or DASH.match(text):
        v = 0.0
    else:
        t = text.replace(",", "").replace("$", "").replace(" ", "")
        if "numcommadecimal" in fmt.replace("-", ""):
            t = text.replace(".", "").replace(",", ".").replace(" ", "")
        try:
            v = float(t)
        except ValueError:
            return None
    v *= 10 ** int(el.get("scale") or 0)
    return -v if el.get("sign") == "-" else v


class Filing:
    """One cached inline-XBRL filing: contexts, numeric facts, and the <tr> each fact sits in."""

    def __init__(self, cik: str, accession: str, path: Path | None = None):
        from lxml import etree
        self.cik, self.accession = cik, accession
        self.path = path or (config.BDC_HTML_CACHE_DIR / cik.lstrip("0") / (accession.replace("-", "") + ".html"))
        self.ok = self.path.exists()
        self.contexts: dict[str, dict] = {}
        self.facts: dict[tuple[str, str], list[dict]] = {}   # (local name, context) -> facts
        self.by_name: dict[str, list[dict]] = {}
        if not self.ok:
            return
        tree = etree.parse(str(self.path), etree.XMLParser(recover=True, huge_tree=True))
        for c in tree.iter("{%s}context" % NS_XBRLI):
            dims = {}
            for m in c.iter("{%s}explicitMember" % NS_XBRLDI, "{%s}typedMember" % NS_XBRLDI):
                dims[m.get("dimension")] = "".join(m.itertext()).strip()
            inst = c.find(".//{%s}instant" % NS_XBRLI)
            end = c.find(".//{%s}endDate" % NS_XBRLI)
            self.contexts[c.get("id")] = {"instant": inst.text.strip() if inst is not None and inst.text else None,
                                          "end": end.text.strip() if end is not None and end.text else None,
                                          "dims": dims}
        self.units: dict[str, str] = {}
        for u in tree.iter("{%s}unit" % NS_XBRLI):
            self.units[u.get("id")] = " ".join(t.strip() for t in u.itertext() if t.strip())
        self._tr_text: dict[str, str] = {}
        for el in tree.iter("{%s}nonFraction" % NS_IX):
            qname = el.get("name", "")
            # us-gaap concepts by local name; a filer's own concept keeps its prefix (never confused)
            name = qname.split(":", 1)[1] if qname.startswith("us-gaap:") else qname
            tr = el
            while tr is not None and _local(tr.tag) != "tr":
                tr = tr.getparent()
            key = tree.getpath(tr) if tr is not None else None  # stable; id() of an lxml proxy is not
            if tr is not None and key not in self._tr_text:
                self._tr_text[key] = normalise(" ".join(tr.itertext()))
            f = {"name": name, "context": el.get("contextRef"), "value": _num(el),
                 "shown": "".join(el.itertext()).strip(), "scale": int(el.get("scale") or 0),
                 "tr": key, "line": self._tr_text.get(key) if key is not None else None,
                 "unit": (el.get("unitRef") or "")}
            self.facts.setdefault((name, f["context"]), []).append(f)
            self.by_name.setdefault(name, []).append(f)

    def is_usd(self, f: dict) -> bool:
        return self.units.get(f.get("unit"), f.get("unit") or "").upper().endswith("USD")

    def fv_facts(self, context: str) -> list[dict]:
        """The context's fair-value facts in US dollars (a filer may also tag the local-currency value
        on the same context, under another unit)."""
        facts = [f for f in self.facts.get((FV, context), []) if f["value"] is not None]
        usd = [f for f in facts if self.is_usd(f)]
        return usd if usd else facts

    def dominant_fv_scale(self) -> int:
        if not hasattr(self, "_dom"):
            from collections import Counter
            cnt = Counter(f["scale"] for f in self.by_name.get(FV, []) if f["value"])
            self._dom = cnt.most_common(1)[0][0] if cnt else 0
        return self._dom

    def printed_line(self, context: str) -> str | None:
        """The <tr> carrying the context's own fair-value fact (the first one in document order)."""
        for f in self.facts.get((FV, context), []):
            if f["line"]:
                return f["line"]
        return None

    def undimensioned_total(self, report_date: str) -> dict | None:
        """The filed total investments: the InvestmentOwnedAtFairValue fact on a context with no
        dimension, dated the report date. None when there is none or they disagree."""
        cands = [f for f in self.by_name.get(FV, []) if f["value"] is not None
                 and (self.contexts.get(f["context"]) or {}).get("instant") == report_date
                 and not (self.contexts.get(f["context"]) or {}).get("dims")]
        cands = [f for f in cands if self.is_usd(f)] or cands
        vals = {round(f["value"], 2) for f in cands}
        if len(vals) != 1:
            return None
        lined = [f for f in cands if f["line"]]
        return (lined or cands)[0]

    def cash_equivalents(self, report_date: str) -> list[float]:
        out = []
        for n in CASH_EQ:
            for f in self.by_name.get(n, []):
                c = self.contexts.get(f["context"]) or {}
                if f["value"] is not None and c.get("instant") == report_date and not c.get("dims"):
                    out.append(f["value"])
        return sorted(set(out))


@lru_cache(maxsize=6)
def filing(cik: str, accession: str) -> Filing:
    return Filing(cik, accession)


# --------------------------------------------------------------------------------------------- rows

def _con():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'")
    return con


COLS = """CAST(row_id AS VARCHAR) row_id, lpad(CAST(cik AS VARCHAR),10,'0') cik,
    CAST(accession_number AS VARCHAR) accession_number, CAST(src_context_id AS VARCHAR) src_context_id,
    CAST(report_date AS VARCHAR)[:10] report_date, TRY_CAST(fair_value AS DOUBLE) fair_value,
    TRY_CAST(shares_held AS DOUBLE) shares_held, TRY_CAST(pct_of_net_assets AS DOUBLE) pct_of_net_assets,
    coalesce(CAST(asset_category AS VARCHAR),'') asset_category,
    coalesce(CAST(index_classification AS VARCHAR),'') index_classification,
    coalesce(CAST(accounting_record_class AS VARCHAR),'') record_class,
    CAST(issuer_name AS VARCHAR) issuer_name, CAST(instrument_description AS VARCHAR) instrument_description"""


def quarter_rows(con, holdings: str, cik: str, rd: str) -> list[dict]:
    """Published rows of a fund-quarter (published basis: JV look-through rows excluded)."""
    df = con.execute(f"""SELECT {COLS} FROM read_parquet('{holdings}')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')=? AND CAST(report_date AS VARCHAR)[:10]=?
          AND coalesce(CAST(accounting_record_class AS VARCHAR),'')<>'underlying_schedule'
        ORDER BY row_id""", [cik, rd]).fetchdf()
    return df.astype(object).where(df.notna(), None).to_dict("records")


def is_equity(r: dict) -> bool:
    """The C04 population (pipeline/oracle_checks.check_C04_equity_has_shares)."""
    return (r["index_classification"].lower() in ("equity", "equity_other")
            or bool(re.search(r"equity|stock", r["asset_category"].lower())))


def _eq(a, b, tol) -> bool:
    return a is not None and b is not None and not (isinstance(a, float) and math.isnan(a)) and abs(a - b) <= tol


# --------------------------------------------------------------------------------------------- tests

def row_period(r: dict) -> tuple[bool, str]:
    """The row comes from a context of its own filing dated the report date."""
    if not r.get("accession_number") or not r.get("src_context_id"):
        return False, "no accession or source context"
    fl = filing(r["cik"], r["accession_number"])
    if not fl.ok:
        return False, "filing not cached"
    ctx = fl.contexts.get(r["src_context_id"])
    if ctx is None:
        return False, "context %s not in the filing" % r["src_context_id"]
    if ctx["instant"] != r["report_date"]:
        return False, "context dated %s, not %s" % (ctx["instant"] or ctx["end"], r["report_date"])
    return True, "context %s dated %s" % (r["src_context_id"], ctx["instant"])


def printed_value(fl: "Filing", f: dict) -> float:
    """The value the line prints, in dollars. A fact whose scale differs from the scale of the
    filing's other fair-value facts (a filer tagging one '121' in a thousands schedule without
    scale="3") is read at the schedule's scale: the printed figure in the schedule's unit."""
    dom = fl.dominant_fv_scale()
    if f["scale"] == dom or f["value"] is None:
        return f["value"]
    shown = _num_text(f["shown"])
    if shown is None:
        return f["value"]
    v = shown * 10 ** dom
    return -v if f["value"] < 0 else v


def _num_text(text: str) -> float | None:
    if DASH.match(text or ""):
        return 0.0
    try:
        return float(text.replace(",", "").replace("$", "").replace(" ", ""))
    except ValueError:
        return None


def row_fv(r: dict, *, require_fact: bool) -> tuple[bool, str]:
    """The published fair value equals the value printed by the fair-value fact of the row's own
    context. A CASH row may carry its value under a cash-equivalent concept instead."""
    fl = filing(r["cik"], r["accession_number"])
    facts = fl.fv_facts(r["src_context_id"]) if fl.ok else []
    if not facts and r.get("asset_category") == "CASH" and fl.ok:
        facts = [f for (n, cx), fs in fl.facts.items() if cx == r["src_context_id"] and CASH_CONCEPT.search(n)
                 for f in fs if f["value"] is not None and fl.is_usd(f)]   # dollars only, not a percent
    if not facts:
        if require_fact:
            return False, "no fair-value fact in the row's context"
        return (r["fair_value"] in (None, 0.0)), "no fair-value fact; published %s" % r["fair_value"]
    vals = {round(printed_value(fl, f), 2) for f in facts}
    if len(vals) != 1:
        return False, "the context's fair-value facts disagree %s" % sorted(vals)
    v = printed_value(fl, facts[0])
    note = "" if v == facts[0]["value"] else " (fact %s at scale %s read at the schedule scale)" % (
        facts[0]["value"], facts[0]["scale"])
    return _eq(r["fair_value"], v, FV_TOL), "published %s, printed %s%s" % (r["fair_value"], v, note)


def row_pct(r: dict) -> tuple[bool, str]:
    fl = filing(r["cik"], r["accession_number"])
    facts = [f for f in fl.facts.get((PCT, r["src_context_id"]), []) if f["value"] is not None] if fl.ok else []
    if not facts:
        return False, "no percent-of-net-assets fact in the row's context (cannot confirm the line)"
    v = facts[0]["value"] * (100.0 if facts[0]["scale"] == -2 or abs(facts[0]["value"]) < 1.5 else 1.0)
    return _eq(r["pct_of_net_assets"], v, 0.0051), "published %s, printed %s" % (r["pct_of_net_assets"], v)


def row_shares(r: dict) -> tuple[bool, str]:
    fl = filing(r["cik"], r["accession_number"])
    line_tr = None
    for f in fl.facts.get((FV, r["src_context_id"]), []):
        line_tr = f["tr"]
        break
    if line_tr is None:
        return False, "printed line not found"
    facts = []
    for n in SHARES:
        facts += [f for f in fl.facts.get((n, r["src_context_id"]), []) if f["value"] is not None and f["tr"] == line_tr]
    if not facts:
        return untagged_count(fl, r, line_tr)
    v = facts[0]["value"]
    if v == 0.0 and r["shares_held"] in (None, 0.0):
        return True, "printed dash, nothing published"
    ok = _eq(r["shares_held"], v, 0.0001 + 1e-9 * abs(v))
    why = "published %s, tagged %s (%s, shown %r, scale %s)" % (r["shares_held"], v, facts[0]["name"],
                                                                facts[0]["shown"], facts[0]["scale"])
    if not ok and facts[0]["scale"] != 0 and _eq(r["shares_held"], _num_text(facts[0]["shown"]), 0.0001):
        why = "unit ambiguous: " + why   # printed digits published, the filer's tag scales them
    return ok, why


COUNT_WORD = r"(?:shares?|units?|interests?|warrants?)"


def untagged_count(fl: "Filing", r: dict, line_tr: str) -> tuple[bool, str]:
    """No count fact on the line. The published count must be printed on the row's own line as a
    parenthetical '(N shares|units|...)' or as a cell of its own that is not a tagged figure (cost,
    fair value, percent). Nothing published passes only when the line prints no such count."""
    line = fl._tr_text.get(line_tr) or ""
    # figures on the line tagged as something other than a count (cost, fair value, percent, rate);
    # a count tagged under a neighbour's context (filer swapped contexts) is still the printed count
    tagged = {f["shown"].strip() for fs in fl.facts.values() for f in fs
              if f["tr"] == line_tr and f["name"] not in SHARES}
    paren = [m for m in re.findall(r"\(\s*([\d,]+(?:\.\d+)?)\s*" + COUNT_WORD + r"\b", line, re.I)]
    sh = r["shares_held"]
    if sh in (None, 0.0):
        # nothing published: the line must print no count, neither '(N units)' nor a bare figure
        # that is not a tagged cost / fair value / percent (a date, footnote or percent is not a count)
        bare = [t for t in re.findall(r"(?<![\d/.(])\d{1,3}(?:,\d{3})*(?:\.\d+)?(?![\d/%)]|\s*%)", line)
                if t not in tagged and t not in ("0",)]
        return (not paren and not bare), ("nothing published; line prints counts %s / untagged figures %s: %s"
                                          % (paren, bare, line[:140]))
    txt = "{:,.0f}".format(sh) if float(sh).is_integer() else "{:,}".format(sh)
    if txt in [p.strip() for p in paren]:
        return True, "published %s printed as '(%s ...)' on the line" % (sh, txt)
    cells = [c for c in re.split(r"\s+", line)]
    if txt in cells and txt not in tagged:
        return True, "published %s printed as an untagged cell on the line" % sh
    return False, "published %s not printed on the line: %s" % (sh, line[:140])


def quarter_total(rows: list[dict], cik: str, rd: str, total_ctx: str | None = None,
                  anchors: tuple = ()) -> tuple[bool, dict]:
    """Published sum against the filed undimensioned total (all rows, or non-CASH rows with the CASH rows
    shown to be the filer's cash equivalents printed outside the total)."""
    accs = sorted({r["accession_number"] for r in rows if r.get("accession_number")})
    info = {"accessions": accs}
    if len(accs) != 1:
        return False, dict(info, why="published rows come from %d filings" % len(accs))
    fl = filing(cik, accs[0])
    tot = None
    if fl.ok and total_ctx:
        # the total fact recorded at build time (verify re-reads its value from the filing)
        cand = [f for f in fl.fv_facts(total_ctx)
                if (fl.contexts.get(total_ctx) or {}).get("instant") == rd]
        tot = cand[0] if cand else None
    elif fl.ok:
        # The filed TOTAL investments, confirmed twice: a fair-value fact dated the report date on no
        # position (no InvestmentIdentifierAxis), whose value is a total the verdict itself quotes
        # (fv_conservation: its anchor; B01: a 'Total investments' line it cites). An undimensioned
        # fact alone is not enough: some filers tag only the non-controlled line without dimension
        # and the affiliated lines with one, so the undimensioned fact is a subtotal.
        cand = [f for f in fl.by_name.get(FV, []) if f["value"] is not None and fl.is_usd(f)
                and (fl.contexts.get(f["context"]) or {}).get("instant") == rd
                and "us-gaap:InvestmentIdentifierAxis" not in (fl.contexts.get(f["context"]) or {}).get("dims", {})
                and f["scale"] <= 3     # a rounded 'in billions' figure is not the filed total
                and any(abs(f["value"] - a) <= 0.5 * 10 ** max(f["scale"], 0) for a in anchors)]
        # a quoted figure is tried in dollars and in thousands, so a small fact can match the
        # unscaled reading of a total; the total is the largest matched value
        top = max((f["value"] for f in cand), default=None)
        cand = [f for f in cand if top is not None and abs(f["value"] - top) < 0.5]
        if cand:
            nodim = [f for f in cand if not (fl.contexts.get(f["context"]) or {}).get("dims")]
            lined = [f for f in (nodim or cand) if f["line"]]
            tot = (lined or nodim or cand)[0]
        elif not anchors:
            und = fl.undimensioned_total(rd)
            if und is not None and re.match(r"total (portfolio )?investments?\b(?!.*cash)", und["line"] or "", re.I):
                tot = und
    if tot is None:
        return False, dict(info, why="no filed total-investments fact confirmed by the verdict's quoted total (dated %s)" % rd)
    info["total_context"] = tot["context"]
    info["total_dims"] = (fl.contexts.get(tot["context"]) or {}).get("dims")
    unit = 10 ** min(max(tot["scale"], 0), 3)   # never wider than two thousand dollars
    tol = 2 * unit
    s_all = sum(r["fair_value"] or 0.0 for r in rows)
    cash = [r for r in rows if r["asset_category"] == "CASH"]
    s_cash = sum(r["fair_value"] or 0.0 for r in cash)
    info.update(total=tot["value"], total_line=tot["line"], tol=tol, sum_all=round(s_all, 2),
                sum_ex_cash=round(s_all - s_cash, 2), sum_cash=round(s_cash, 2), n_rows=len(rows), n_cash=len(cash))
    if abs(s_all - tot["value"]) <= tol:
        return True, dict(info, basis="all published rows")
    if cash and abs(s_all - s_cash - tot["value"]) <= tol:
        # The non-CASH rows sum to the filed total, so the CASH rows sit outside it; each CASH row
        # equals its own filed fact (row test). Recorded for the reader: the filer's cash-equivalent
        # facts and whether a filed 'investments and cash equivalents' total equals total + CASH.
        tot_plus = [f["value"] for f in fl.by_name.get(FV, []) if f["value"] is not None
                    and (fl.contexts.get(f["context"]) or {}).get("instant") == rd
                    and abs(f["value"] - tot["value"] - s_cash) <= tol]
        return True, dict(info, basis="non-CASH rows", filed_cash=fl.cash_equivalents(rd),
                          total_plus_cash_fact=bool(tot_plus))
    return False, dict(info, why="published sum %.0f (ex-CASH %.0f) vs filed total %.0f" % (
        s_all, s_all - s_cash, tot["value"]))


CASH_LINE = re.compile(r"money market|cash|treasur|government|liquidity|fedfund|short[- ]term|t-?bill", re.I)


def row_line(r: dict) -> str | None:
    """The row's own printed line: the <tr> of its fair-value fact, else of any fact of its context."""
    fl = filing(r["cik"], r["accession_number"])
    if not fl.ok:
        return None
    line = fl.printed_line(r["src_context_id"])
    if line:
        return line
    for (n, cx), fs in fl.facts.items():
        if cx == r["src_context_id"]:
            for f in fs:
                if f["line"]:
                    return f["line"]
    return None


def check_quarter(rule: str, rows: list[dict], cik: str, rd: str, total_ctx: str | None = None,
                  anchors: tuple = ()) -> dict:
    """The rule's test on one fund-quarter's published rows. Returns ok, per-row failures and detail."""
    fails, detail = [], {"n_rows": len(rows)}
    if not rows:
        return {"ok": False, "fails": [{"why": "no published rows"}], "detail": detail}
    accs = sorted({r["accession_number"] for r in rows if r.get("accession_number")})
    detail["accessions"] = accs
    pool = [r for r in rows if is_equity(r)] if rule == "C04" else rows
    detail["n_tested"] = len(pool)
    for r in pool:
        ok, why = row_period(r)
        if not ok:
            fails.append({"row_id": r["row_id"], "test": "period", "why": why})
            continue
        tests = []
        if rule in ("fv_conservation", "B01"):
            tests.append(("fair_value",) + row_fv(r, require_fact=(rule == "B01")))
        if rule == "A07":
            tests.append(("pct_of_net_assets",) + row_pct(r))
        if rule == "C04":
            tests.append(("shares_held",) + row_shares(r))
        if rule == "PP03":
            fl = filing(r["cik"], r["accession_number"])
            line = fl.printed_line(r["src_context_id"])
            fv_ok = bool(fl.fv_facts(r["src_context_id"]))
            # a row with a fair value must have a printed schedule line carrying it
            tests.append(("printed_line", (line is not None) or not fv_ok,
                          "line found" if line else "no fair-value fact on any line"))
            # the row's value is its own context's (not a comparative fact carried onto a current row)
            tests.append(("fair_value",) + row_fv(r, require_fact=False))
        for name, ok, why in tests:
            if not ok:
                fails.append({"row_id": r["row_id"], "test": name, "why": why})
    if len(accs) != 1:
        fails.append({"test": "accession", "why": "rows from %d filings: %s" % (len(accs), accs)})
    if rule in ("fv_conservation", "B01", "PP03"):
        # one published row per source context: a second row on the same context is a double count
        seen: dict = {}
        for r in rows:
            k = (r.get("accession_number"), r.get("src_context_id"))
            if k in seen:
                fails.append({"row_id": r["row_id"], "test": "duplicate_context",
                              "why": "same context as %s" % seen[k]})
            seen.setdefault(k, r["row_id"])
    if rule in ("fv_conservation", "B01"):
        # a CASH row must be a cash instrument on its own printed line (a loan classed CASH is not)
        for r in rows:
            if r["asset_category"] == "CASH":
                line = row_line(r)
                if not CASH_LINE.search(line or ""):
                    fails.append({"row_id": r["row_id"], "test": "cash_line",
                                  "why": "CASH row whose own line names no cash instrument: %s" % (line or "")[:100]})
        ok, info = quarter_total(rows, cik, rd, total_ctx=total_ctx, anchors=anchors)
        detail["total"] = info
        if not ok:
            fails.append({"test": "total", "why": info.get("why")})
    if rule == "C04" and not pool:
        fails.append({"test": "population", "why": "no published equity rows"})
    return {"ok": not fails, "fails": fails, "detail": detail}


# --------------------------------------------------------------------------------------------- plants

def plants(rule: str, rows: list[dict], cik: str, rd: str, total_ctx: str | None = None) -> list[tuple[str, list[dict]]]:
    """(name, planted rows) for each realistic plant; each must make the quarter FAIL."""
    out = []
    if not rows:
        return out
    accs = sorted({r["accession_number"] for r in rows if r.get("accession_number")})
    fl = filing(cik, accs[0]) if accs else None
    used = {r["src_context_id"] for r in rows}
    # a context of the same filing dated earlier that carries a fair value (a comparative-schedule row)
    prior = None
    if fl is not None and fl.ok:
        for (name, ctx), facts in fl.facts.items():
            c = fl.contexts.get(ctx) or {}
            if name == FV and ctx not in used and c.get("instant") and c["instant"] < rd and c.get("dims"):
                prior = (ctx, facts[0]["value"])
                break
    pool = [r for r in rows if is_equity(r)] if rule == "C04" else rows
    if not pool:
        return out
    srt = sorted(pool, key=lambda r: abs(r["fair_value"] or 0.0))
    med = srt[len(srt) // 2]

    def swap(target, **kw):
        return [dict(r, **kw) if r is target else r for r in rows]

    if prior:
        # a comparative row added to the quarter (the PP03/B01 leak)
        out.append(("comparative_row_added", rows + [dict(med, row_id="PLANT-PRIOR", src_context_id=prior[0],
                                                           fair_value=prior[1])]))
        out.append(("row_on_prior_context", swap(med, src_context_id=prior[0])))
    out.append(("row_from_other_filing", swap(med, accession_number="0000000000-00-000000")))
    if rule in ("fv_conservation", "B01"):
        big = max(rows, key=lambda r: abs(r["fair_value"] or 0.0))
        out.append(("scale_x1000", swap(med, fair_value=(med["fair_value"] or 0.0) * 1000)))
        out.append(("row_dropped", [r for r in rows if r is not med]))
        out.append(("row_doubled", rows + [dict(big, row_id="PLANT-DUP")]))
        out.append(("fv_shift_one_unit", swap(med, fair_value=(med["fair_value"] or 0.0) + 1000.0)))
        cash = [r for r in rows if r["asset_category"] == "CASH"]
        # a cash equivalent counted as an investment is an error only where the filer prints it
        # outside its total (non-CASH basis); where the filer's total includes it, it is one
        basis = quarter_total(rows, cik, rd, total_ctx=total_ctx)[1].get("basis")
        if cash and basis == "non-CASH rows":
            out.append(("cash_row_as_investment", swap(cash[0], asset_category="OTHER")))
        noncash = [r for r in rows if r["asset_category"] != "CASH" and (r["fair_value"] or 0) > 0]
        if noncash:
            out.append(("investment_as_cash", swap(noncash[len(noncash) // 2], asset_category="CASH")))
    if rule == "A07":
        out.append(("pct_shift", swap(med, pct_of_net_assets=(med["pct_of_net_assets"] or 0.0) + 0.1)))
        out.append(("pct_as_fraction", swap(med, pct_of_net_assets=(med["pct_of_net_assets"] or 0.0) / 100)))
    if rule == "C04":
        withs = [r for r in pool if r["shares_held"]]
        t = withs[len(withs) // 2] if withs else med
        out.append(("shares_missing", swap(t, shares_held=None)))
        out.append(("shares_shift", swap(t, shares_held=(t["shares_held"] or 0.0) + 1)))
        out.append(("shares_x1000", swap(t, shares_held=(t["shares_held"] or 1.0) * 1000)))
        if t.get("fair_value"):
            out.append(("fair_value_as_shares", swap(t, shares_held=t["fair_value"])))
    return out


# --------------------------------------------------------------------------------------------- build / verify

TOTAL_QUOTE = re.compile(r"^\s*(total\s+(portfolio\s+)?investments?(\s+portfolio)?|grand total)\b", re.I)


def verdict_anchors(verdict: dict) -> tuple:
    """Totals the verdict quotes from the page (dollars; a quoted figure is also tried in thousands),
    used only to pick the filed total fact when the filing has no undimensioned one."""
    out = []
    try:
        a = float(verdict.get("anchor_value"))
        if a >= 1e5:
            out.append(a)
    except (TypeError, ValueError):
        pass
    for c in verdict.get("culprit_citations") or []:
        q = str(c.get("quoted_text") or "")
        if TOTAL_QUOTE.search(q) and not re.search(r"cash|before|non-?control|affiliat|debt|equity", q, re.I):
            for n in re.findall(r"\d{1,3}(?:,\d{3})+", q):
                v = float(n.replace(",", ""))
                out += [v, v * 1000]
    return tuple(sorted(set(out)))


def build(rule: str, review_ids: list[str], holdings: str, ledger: str, verdict_dir: Path) -> list[dict]:
    led = {}
    with open(ledger, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["review_id"] in review_ids:
                led[r["review_id"]] = r
    con = _con()
    out = []
    for rid in review_ids:
        L = led[rid]
        cik, rd = L["cik"].zfill(10), L["report_date"][:10]
        assert L["rule_name"] == rule, (rid, L["rule_name"])
        vp = [verdict_dir / s / (rid + ".json") for s in ("review_queue", "bdc_cik_review")]
        vp = [p for p in vp if p.exists()]
        verdict = json.loads(vp[0].read_text(encoding="utf-8-sig")) if vp else {}
        rows = quarter_rows(con, holdings, cik, rd)
        res = check_quarter(rule, rows, cik, rd, anchors=verdict_anchors(verdict))
        res.update(review_id=rid, cik=cik, report_date=rd, rule_name=rule, engine=L["engine"],
                   published_rows=len(rows), row_ids=[r["row_id"] for r in rows if rule != "C04" or is_equity(r)])
        out.append(res)
        print("%s %s %s %s: %s rows=%d fails=%d %s" % (rid, cik, rd, rule, "PASS" if res["ok"] else "FAIL",
              res["detail"].get("n_tested", 0), len(res["fails"]),
              ("; ".join(sorted({f["test"] + ": " + str(f["why"])[:90] for f in res["fails"]}))[:400]).encode(
                  "ascii", "replace").decode()), flush=True)
        filing.cache_clear()
    return out


def verify(store: Path, holdings: str, plant: bool) -> int:
    data = json.loads(Path(store).read_text(encoding="utf-8-sig"))
    con = _con()
    passed = failed = 0
    tally: dict[str, list[int]] = {}
    for e in data["retirements"]:
        rule, cik, rd = e["rule_name"], e["cik"], e["report_date"]
        rows = quarter_rows(con, holdings, cik, rd)
        tctx = e.get("filed_total_context")
        if not plant:
            res = check_quarter(rule, rows, cik, rd, total_ctx=tctx)
            ok = res["ok"] and len(rows) == e.get("published_rows", len(rows))
            passed += ok
            failed += not ok
            print("%s %s %s %s: %s (rows %d)" % (e["retirement_id"], e["review_id"], rule, rd,
                                                  "PASS" if ok else "FAIL", len(rows)))
            for f in res["fails"][:5]:
                print("   %s" % json.dumps(f)[:300])
            continue
        caught = escaped = 0
        for name, planted in plants(rule, rows, cik, rd, total_ctx=tctx):
            bad = check_quarter(rule, planted, cik, rd, total_ctx=tctx)["ok"]
            tally.setdefault(name, [0, 0])[1 if bad else 0] += 1
            caught += not bad
            escaped += bad
            if bad:
                print("   ESCAPED plant %s" % name)
        ok = escaped == 0 and caught > 0
        passed += ok
        failed += not ok
        print("%s %s %s: planted %d, caught %d, escaped %d" % (e["retirement_id"], rule, rd, caught + escaped, caught,
                                                               escaped))
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
    b.add_argument("--verdict-dir", default=str(ROOT / "data" / "decisions" / "verdict_files"))
    v = sub.add_parser("verify")
    v.add_argument("--store", required=True)
    v.add_argument("--holdings", default=hold)
    v.add_argument("--plant", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        res = build(a.rule, a.review_ids, Path(a.holdings).as_posix(), a.ledger, Path(a.verdict_dir))
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        return 0
    return verify(Path(a.store), Path(a.holdings).as_posix(), a.plant)


if __name__ == "__main__":
    sys.exit(main())
