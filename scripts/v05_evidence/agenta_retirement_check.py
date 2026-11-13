"""Deterministic check behind the agentA verdict retirements (standing rule D-252, REQ-APZ-1).

A real-error verdict on an agentA finding (agentA_maturity_vs_xbrl / _spread_vs_xbrl /
_reference_uncorroborated) may be retired when every row it cites is published at its filed
(printed) value, or is correctly excluded. For each cited published row this script:

  1. finds the row's own printed line: the inline-XBRL <tr> that carries an
     us-gaap:InvestmentOwnedAtFairValue fact whose contextRef is the row's src_context_id
     (the Apollo reviewer's method; no value search, no member text);
  2. reads the rule's field from that line and asserts the published value equals it:
       maturity_date  - the published date is printed on the line and is the latest date there;
       basis_spread   - the margin printed after the reference code ('S + 5.25 %', 'SOFR + 6.00%',
                        'S+525' in basis points, 'SOFR 5.00 %') equals the published spread (0.005);
       reference_rate - the code before the margin maps to the published reference rate; for the
                        reference rule the margin is checked too.
A cited context with no published row passes only when it is correctly excluded: a JV look-through
row (accounting_record_class 'underlying_schedule') or a context carrying no fair value and no cost.
Anything else fails, and a failing entry is not retired.

    python scripts/v05_evidence/agenta_retirement_check.py build --review-ids R1 R2 ... --out results.json
    python scripts/v05_evidence/agenta_retirement_check.py verify --store data/overrides/verdict_retirements/standing_rule_agenta_repair_2026-11-13.json
    python scripts/v05_evidence/agenta_retirement_check.py verify --store ... --plant   # must FAIL every entry

``build`` takes the cited rows from the flags file the verdicts were written against (the 2026-07-24
data/output/shadow/agent_a_flags.csv, identifiers cut at 300 characters, joined by prefix on the
fund-quarter's published identifiers) and from the extracted contexts for unpublished ones. ``verify``
re-checks the row ids recorded in the store. Read-only; ASCII output.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "v05_evidence"))
from fund_gate import normalise  # noqa: E402
from pipeline import config  # noqa: E402

FIELD = {"agentA_maturity_vs_xbrl": ["maturity_date"],
         "agentA_spread_vs_xbrl": ["basis_spread"],
         "agentA_reference_uncorroborated": ["reference_rate_type", "basis_spread"]}
_CODES = {"S": "SOFR", "SF": "SOFR", "SOFR": "SOFR", "TSOFR": "SOFR", "L": "LIBOR", "LIBOR": "LIBOR",
          "E": "EURIBOR", "EURIBOR": "EURIBOR", "P": "PRIME", "PRIME": "PRIME", "SONIA": "SONIA",
          "SARON": "SARON", "STIBOR": "STIBOR", "CORRA": "CORRA", "BBSY": "BBSY", "BBSW": "BBSW",
          "CDOR": "CDOR", "NIBOR": "NIBOR", "C": "CDOR", "SA": "SARON"}
_MARGIN = re.compile(r"\b([A-Z]{1,6})(?:\s*\([A-Z0-9]{1,3}\))?\s*(?:\+\s*|\s+(?=\d))(\d{1,4}(?:\.\d+)?)\s*(%?)")
_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?![\d/])")


@lru_cache(maxsize=8)
def _page(cik: str, accession: str) -> str:
    p = config.BDC_HTML_CACHE_DIR / cik.lstrip("0") / (accession.replace("-", "") + ".html")
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def printed_line(cik: str, accession: str, context: str) -> str | None:
    """The <tr> carrying the context's fair-value fact, as normalised text; None if there is none."""
    text = _page(cik, accession)
    if not text or not context:
        return None
    ctx = re.escape(context)
    fv = re.compile(r'name="[^"]*:InvestmentOwnedAtFairValue"[^>]*contextRef="%s"|contextRef="%s"[^>]*'
                    r'name="[^"]*:InvestmentOwnedAtFairValue"' % (ctx, ctx))
    for m in fv.finditer(text):
        s, e = text.rfind("<tr", 0, m.start()), text.find("</tr>", m.start())
        if s >= 0 and e >= 0:
            return normalise(re.sub(r"<[^>]+>", " ", text[s:e]))
    return None


def printed_dates(line: str) -> list[date]:
    out = []
    for mo, dd, yy in _DATE.findall(line):
        year = int(yy) + (2000 if len(yy) == 2 else 0)
        try:
            out.append(date(year, int(mo), int(dd)))
        except ValueError:
            continue
    return out


def printed_margin(line: str) -> tuple[str, float] | None:
    """(benchmark, margin in pct) of the first 'CODE + n' on the line; None if there is none."""
    for code, num, pct in _MARGIN.findall(line):
        bench = _CODES.get(code.upper())
        if not bench:
            continue
        value = float(num)
        if not pct and "." not in num and value >= 25:
            value /= 100.0  # basis points ('S+525')
        return bench, value
    return None


_REF = re.compile(r"\b([A-Z]{1,6})(?:\s*\([A-Z0-9]{1,3}\))?\s*(\+|-\s|\s)\s*\d")


def printed_reference(line: str) -> str | None:
    """The benchmark code printed ahead of a number ('S + 5.25', 'SOFR(Q) - 6.76', 'SOFR 5.00');
    a one- or two-letter code counts only before '+'."""
    for code, sep in _REF.findall(line):
        bench = _CODES.get(code.upper())
        if bench and (len(code) > 2 or sep == "+"):
            return bench
    return None


def percent_printed(line: str, value: float) -> bool:
    """The value is printed on the line as a percent ('5.75 %') or as basis points after '+' ('+575')."""
    for num in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", line):
        if abs(float(num) - value) <= 0.005:
            return True
    return any(abs(int(b) / 100.0 - value) <= 0.005 for b in re.findall(r"\+\s*(\d{2,4})(?![\d.%])", line))


def field_ok(field: str, published, line: str, rule: str = "") -> tuple[bool, str]:
    if field == "maturity_date":
        dates = printed_dates(line)
        if published in (None, "") or not dates:
            return False, "no published or printed date"
        pub = date.fromisoformat(str(published)[:10])
        return (pub in dates and pub == max(dates)), "printed dates %s" % [d.isoformat() for d in dates]
    if field == "reference_rate_type":
        code = printed_reference(line)
        return (code is not None and str(published or "").upper() == code), "printed code %s" % code
    if field == "basis_spread" and rule == "agentA_reference_uncorroborated":
        # the reference rule's verdicts are about a spread not carried: the published spread must be
        # a percent printed on the row's own line (a separate Spread column has no 'CODE +' form)
        ok = published is not None and percent_printed(line, float(published))
        return ok, "published spread printed on the line: %s" % ok
    if field == "basis_spread":
        margin = printed_margin(line)
        if margin is None:
            return False, "no 'CODE + margin' printed"
        ok = published is not None and abs(float(published) - margin[1]) <= 0.005
        return ok, "printed margin %s" % margin[1]
    raise ValueError(field)


def _con():
    import duckdb
    return duckdb.connect()


def published_rows(con, holdings: str, row_ids: list[str]) -> dict[str, dict]:
    if not row_ids:
        return {}
    df = con.execute(f"""SELECT CAST(row_id AS VARCHAR) row_id, lpad(CAST(cik AS VARCHAR),10,'0') cik,
            CAST(accession_number AS VARCHAR) accession_number, CAST(src_context_id AS VARCHAR) src_context_id,
            CAST(report_date AS VARCHAR)[:10] report_date, CAST(maturity_date AS VARCHAR)[:10] maturity_date,
            TRY_CAST(basis_spread AS DOUBLE) basis_spread, CAST(reference_rate_type AS VARCHAR) reference_rate_type,
            coalesce(CAST(accounting_record_class AS VARCHAR),'') record_class
        FROM read_parquet('{holdings}') WHERE row_id IN (SELECT unnest(?))""", [row_ids]).fetchdf()
    return {r["row_id"]: r for r in df.astype(object).where(df.notna(), None).to_dict("records")}


def check_rows(rule: str, rows: list[dict], plant: bool = False) -> list[dict]:
    """One result per cited published row: ok, line, detail per field. ``plant`` shifts every
    published value (a day, a quarter point, another benchmark) so a correct check must fail."""
    out = []
    for r in rows:
        r = dict(r)
        if plant:
            if r.get("maturity_date"):
                r["maturity_date"] = (date.fromisoformat(r["maturity_date"]) + timedelta(days=1)).isoformat()
            r["basis_spread"] = (r.get("basis_spread") or 0.0) + 0.25
            r["reference_rate_type"] = "LIBOR" if r.get("reference_rate_type") != "LIBOR" else "SOFR"
            if r.get("record_class") == "underlying_schedule":
                r["record_class"] = ""  # a planted row is not excused as a look-through row
        if r.get("record_class") == "underlying_schedule":
            out.append({"row_id": r["row_id"], "ok": True, "excluded": "underlying_schedule", "line": None})
            continue
        line = printed_line(r["cik"], r["accession_number"], r["src_context_id"])
        if line is None:
            out.append({"row_id": r["row_id"], "ok": False, "detail": "printed line not found", "line": None})
            continue
        details, ok = {}, True
        for field in FIELD[rule]:
            f_ok, why = field_ok(field, r.get(field), line, rule)
            details[field] = {"published": r.get(field), "ok": f_ok, "why": why}
            ok = ok and f_ok
        out.append({"row_id": r["row_id"], "ok": ok, "detail": details, "line": line,
                    "accession_number": r["accession_number"]})
    return out


# --------------------------------------------------------------------------------------------- build

def cited_rows(con, holdings: str, parquet: str, flags: str, cik: str, rd: str, rule: str):
    """Published row ids the verdict's flagged identifiers name, and unpublished cited contexts."""
    idents = []
    with open(flags, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["cik"].zfill(10) == cik and r["report_date"][:10] == rd and r["rule_name"] == rule:
                idents.append(r["identifier"])
    idents = sorted(set(idents))
    pub = con.execute(f"""SELECT CAST(row_id AS VARCHAR), CAST(bdc_investment_identifier AS VARCHAR),
            CAST(src_context_id AS VARCHAR), CAST(accession_number AS VARCHAR)
        FROM read_parquet('{holdings}') WHERE lpad(CAST(cik AS VARCHAR),10,'0')=? AND CAST(report_date AS VARCHAR)[:10]=?
          AND CAST(source AS VARCHAR)='bdc'""", [cik, rd]).fetchall()
    ctx = con.execute(f"""SELECT CAST(investment_identifier AS VARCHAR), CAST(src_context_id AS VARCHAR),
            TRY_CAST(fair_value AS DOUBLE), TRY_CAST(cost AS DOUBLE), CAST(accession_number AS VARCHAR)
        FROM read_parquet('{parquet}') WHERE CAST(cik AS VARCHAR)=? AND CAST(report_date AS VARCHAR)[:10]=?
          AND CAST(period AS VARCHAR)=CAST(report_date AS VARCHAR)""", [cik, rd]).fetchall()

    def named(text: str | None, ident: str) -> bool:
        return bool(text) and (text == ident or (len(ident) >= 300 and text.startswith(ident)))

    row_ids, unpublished = [], []
    for ident in idents:
        # the flagged identifier's extracted contexts, then the published rows built from them
        cs = [c for c in ctx if named(c[0], ident)]
        keys = {(c[4], c[1]) for c in cs}
        hits = [rid for rid, pid, pctx, pacc in pub if (pacc, pctx) in keys or named(pid, ident)]
        if hits:
            row_ids += hits
            continue
        unpublished.append({"identifier": ident, "contexts": [
            {"src_context_id": c[1], "fair_value": c[2], "cost": c[3]} for c in cs]})
    return sorted(set(row_ids)), unpublished


def _excluded_ok(u: dict) -> bool:
    """An unpublished cited context is correctly excluded only when it carries no money."""
    return bool(u["contexts"]) and all(abs(c["fair_value"] or 0.0) < 1 and abs(c["cost"] or 0.0) < 1
                                       for c in u["contexts"])


def build(review_ids, holdings, parquet, flags, ledger) -> list[dict]:
    led = {}
    with open(ledger, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            led[r["review_id"]] = r
    con = _con()
    results = []
    for rid in review_ids:
        L = led[rid]
        cik, rd, rule = L["cik"].zfill(10), L["report_date"][:10], L["rule_name"]
        row_ids, unpublished = cited_rows(con, holdings, parquet, flags, cik, rd, rule)
        rows = list(published_rows(con, holdings, row_ids).values())
        checked = check_rows(rule, rows)
        unpub = [{**u, "ok": _excluded_ok(u)} for u in unpublished]
        ok = bool(checked or unpub) and all(c["ok"] for c in checked) and all(u["ok"] for u in unpub)
        results.append({"review_id": rid, "cik": cik, "report_date": rd, "rule_name": rule, "ok": ok,
                        "row_ids": row_ids, "rows": checked, "unpublished": unpub})
        print("%s %s %s %s: %s (%d rows, %d unpublished)" % (rid, cik, rd, rule, "PASS" if ok else "FAIL",
                                                           len(checked), len(unpub)))
    return results


# --------------------------------------------------------------------------------------------- verify

def verify(store: Path, holdings: str, plant: bool) -> int:
    data = json.loads(Path(store).read_text(encoding="utf-8-sig"))
    con = _con()
    passed = failed = 0
    for e in data["retirements"]:
        rows = list(published_rows(con, holdings, e["cited_rows"]).values())
        missing = set(e["cited_rows"]) - {r["row_id"] for r in rows}
        checked = check_rows(e["rule_name"], rows, plant=plant)
        ok = not missing and bool(checked) and all(c["ok"] for c in checked)
        passed += ok
        failed += not ok
        print("%s %s %s: %s%s" % (e["retirement_id"], e["review_id"], e["rule_name"], "PASS" if ok else "FAIL",
                                  " (missing rows %s)" % sorted(missing) if missing else ""))
    print("entries %d: pass %d, fail %d%s" % (passed + failed, passed, failed, " [PLANTED]" if plant else ""))
    if plant:
        return 0 if passed == 0 else 1  # every planted entry must fail
    return 0 if failed == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    out = config.OUTPUT_DIR
    b = sub.add_parser("build")
    b.add_argument("--review-ids", nargs="+", required=True)
    b.add_argument("--holdings", default=str(out / "private_markets_holdings.parquet"))
    b.add_argument("--bdc-holdings", default=str(out / "bdc_holdings.parquet"))
    b.add_argument("--flags", required=True, help="the flags file the verdicts were written against")
    b.add_argument("--ledger", required=True)
    b.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--store", required=True)
    v.add_argument("--holdings", default=str(out / "private_markets_holdings.parquet"))
    v.add_argument("--plant", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        res = build(a.review_ids, Path(a.holdings).as_posix(), Path(a.bdc_holdings).as_posix(), a.flags, a.ledger)
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        return 0
    return verify(Path(a.store), Path(a.holdings).as_posix(), a.plant)


if __name__ == "__main__":
    sys.exit(main())
