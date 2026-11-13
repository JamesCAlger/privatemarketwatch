"""Deterministic check behind the agentA verdict retirements (standing rule D-252, REQ-APZ-1).

A real-error verdict on an agentA finding (agentA_maturity_vs_xbrl / _spread_vs_xbrl /
_reference_uncorroborated) may be retired when every row it cites is published at its filed
(printed) value, or is correctly excluded. For each cited published row this script:

  1. finds the row's own printed line: the inline-XBRL <tr> that carries an
     us-gaap:InvestmentOwnedAtFairValue fact whose contextRef is the row's src_context_id
     (the Apollo reviewer's method; no value search, no member text);
  2. reads the rule's fields from that line and asserts the published values equal them:
       maturity_date  - the build's header-aware page reader (bdc_xbrl_html_bridge, keyed by the same
                        context) reads a maturity cell with status 'value' equal to the published date,
                        and that date is printed on the line. A blank or unconfirmed maturity cell fails.
       basis_spread   - the margin printed after the benchmark code: 'S + 5.25 %', 'S+525' (basis
                        points), 'SOFR 5.00 %', or the cell labelled Cash / Spread / PIK. Numbers
                        labelled Floor are floors, never the margin. Per D-031 the published spread is
                        the total margin: 'X % Cash + Y % PIK' (or 'X Cash plus Y % PIK') means X + Y;
                        '(includes Y % PIK)' means X. Two or more unlabelled numbers after the code
                        (a floor column next to a spread column) are ambiguous and fail.
       reference_rate - the benchmark code printed ahead of the margin maps to the published code.
     The maturity rule checks maturity_date; the spread rule basis_spread; the reference rule
     reference_rate_type and basis_spread.
A cited context with no published row passes only when it is correctly excluded: a JV look-through
row (accounting_record_class 'underlying_schedule') or a context carrying no fair value and no cost.
Anything else fails, and a failing entry is not retired.

    python scripts/v05_evidence/agenta_retirement_check.py build --review-ids R1 R2 ... --flags F --ledger L --out results.json
    python scripts/v05_evidence/agenta_retirement_check.py verify --store data/overrides/verdict_retirements/standing_rule_agenta_repair_2026-11-13.json
    python scripts/v05_evidence/agenta_retirement_check.py verify --store ... --plant   # every applicable plant must FAIL

Inputs: the published holdings parquet (--holdings, default <PM_OUTPUT_DIR or data/output>/
private_markets_holdings.parquet) and the cached filings under data/raw/filings/bdc_html. ``--plant``
plants each field separately (shifted date, +0.25 margin, other benchmark) and the realistic misreads
(a floor read as the margin, the cash margin where the total is cash + PIK, an acquisition date read as
the maturity); each applicable plant must make its entry fail.

``build`` takes the cited rows from the flags file the verdicts were written against (the 2026-07-24
data/output/shadow/agent_a_flags.csv, identifiers cut at 300 characters) through the extracted
contexts to the published rows. ``verify`` re-checks the row ids recorded in the store. Read-only;
ASCII output.
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
# the margin reading is shared with the engine (pipeline/printed_margin.py)
from pipeline.printed_margin import DATE_RE as _DATE  # noqa: E402
from pipeline.printed_margin import parse_rate  # noqa: E402,F401


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


@lru_cache(maxsize=4)
def _bridges(cik: str, accession: str, report_date: str) -> dict[str, dict]:
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    res = propose_field_bridges_from_ixbrl(cik=cik, accession_number=accession, report_date=report_date)
    return {(b.get("match_evidence") or {}).get("context_ref"): b for b in res.get("bridges", [])}


def reader_maturity(cik: str, accession: str, report_date: str, context: str) -> str | None:
    """The maturity the header-aware page reader reads in the row's maturity cell, or None."""
    b = _bridges(cik, accession, report_date).get(context)
    if not b or b.get("maturity_status") != "value" or not b.get("maturity_date"):
        return None
    return str(b["maturity_date"])[:10]


def printed_dates(line: str) -> list[date]:
    out = []
    for mo, dd, yy in _DATE.findall(line):
        year = int(yy) + (2000 if len(yy) == 2 else 0)
        try:
            out.append(date(year, int(mo), int(dd)))
        except ValueError:
            continue
    return out


def field_ok(field: str, published, line: str, *, mat_cell: str | None = None) -> tuple[bool, str]:
    if field == "maturity_date":
        if published in (None, ""):
            return False, "no published maturity"
        if mat_cell is None:
            return False, "the reader confirms no maturity cell on the line"
        pub = date.fromisoformat(str(published)[:10])
        ok = mat_cell == pub.isoformat() and pub in printed_dates(line)
        return ok, "maturity cell %s" % mat_cell
    rate = parse_rate(line)
    if rate is None:
        return False, "no benchmark code printed"
    if field == "reference_rate_type":
        return str(published or "").upper() == rate["code"], "printed code %s" % rate["code"]
    if field == "basis_spread":
        if rate["total"] is None:
            return False, "margin ambiguous (floor and spread not told apart)"
        ok = published is not None and abs(float(published) - rate["total"]) <= 0.005
        return ok, "printed margin total %s (cash %s, PIK %s)" % (rate["total"], rate["cash"], rate["pik"])
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
        FROM read_parquet('{holdings}') WHERE row_id IN (SELECT unnest(?)) ORDER BY row_id""", [row_ids]).fetchdf()
    return {r["row_id"]: r for r in df.astype(object).where(df.notna(), None).to_dict("records")}


def check_row(rule: str, r: dict) -> dict:
    if r.get("record_class") == "underlying_schedule":
        return {"row_id": r["row_id"], "ok": True, "excluded": "underlying_schedule", "line": None}
    line = printed_line(r["cik"], r["accession_number"], r["src_context_id"])
    if line is None:
        return {"row_id": r["row_id"], "ok": False, "detail": "printed line not found", "line": None}
    mat_cell = (reader_maturity(r["cik"], r["accession_number"], r["report_date"], r["src_context_id"])
                if "maturity_date" in FIELD[rule] else None)
    details, ok = {}, True
    for field in FIELD[rule]:
        f_ok, why = field_ok(field, r.get(field), line, mat_cell=mat_cell)
        details[field] = {"published": r.get(field), "ok": f_ok, "why": why}
        ok = ok and f_ok
    return {"row_id": r["row_id"], "ok": ok, "detail": details, "line": line,
            "accession_number": r["accession_number"]}


def check_rows(rule: str, rows: list[dict]) -> list[dict]:
    return [check_row(rule, r) for r in rows]


def plants(rule: str, r: dict) -> list[tuple[str, dict]]:
    """(name, planted row) for every plant that applies to this row and rule."""
    out = []
    line = printed_line(r["cik"], r["accession_number"], r["src_context_id"]) or ""
    if "maturity_date" in FIELD[rule] and r.get("maturity_date"):
        pub = date.fromisoformat(r["maturity_date"])
        out.append(("maturity_shift", dict(r, maturity_date=(pub + timedelta(days=1)).isoformat())))
        others = sorted({d for d in printed_dates(line) if d != pub})
        if others:
            out.append(("acquisition_date_as_maturity", dict(r, maturity_date=others[0].isoformat())))
    if "basis_spread" in FIELD[rule]:
        out.append(("spread_shift", dict(r, basis_spread=(r.get("basis_spread") or 0.0) + 0.25)))
        rate = parse_rate(line) or {}
        for fl in rate.get("floors") or []:
            if rate.get("total") is None or abs(fl - rate["total"]) > 0.005:
                out.append(("floor_as_spread", dict(r, basis_spread=fl)))
                break
        if rate.get("pik") and rate.get("cash"):
            out.append(("cash_not_total", dict(r, basis_spread=rate["cash"])))
    if "reference_rate_type" in FIELD[rule]:
        out.append(("reference_swap", dict(r, reference_rate_type="LIBOR" if r.get("reference_rate_type") != "LIBOR"
                                           else "SOFR")))
    for name, p in out:
        if p.get("record_class") == "underlying_schedule":
            p["record_class"] = ""  # a planted row is not excused as a look-through row
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
    plant_tally: dict[str, list[int]] = {}
    for e in data["retirements"]:
        rows = list(published_rows(con, holdings, e["cited_rows"]).values())
        missing = set(e["cited_rows"]) - {r["row_id"] for r in rows}
        if not plant:
            checked = check_rows(e["rule_name"], rows)
            ok = not missing and bool(checked) and all(c["ok"] for c in checked)
            for c in checked:
                if not c["ok"]:
                    print("   row %s: %s" % (c["row_id"], json.dumps(c.get("detail"))[:300]))
            passed += ok
            failed += not ok
            print("%s %s %s: %s%s" % (e["retirement_id"], e["review_id"], e["rule_name"], "PASS" if ok else "FAIL",
                                      " (missing rows %s)" % sorted(missing) if missing else ""))
            continue
        # planted: each applicable plant, on one row at a time, must make the entry fail
        caught = escaped = 0
        for r in rows:
            for name, planted in plants(e["rule_name"], r):
                bad = check_row(e["rule_name"], planted)["ok"]
                plant_tally.setdefault(name, [0, 0])[0 if not bad else 1] += 1
                caught += not bad
                escaped += bad
                if bad:
                    print("   ESCAPED plant %s on %s" % (name, r["row_id"]))
        passed += escaped == 0 and caught > 0
        failed += not (escaped == 0 and caught > 0)
        print("%s %s: planted %d, caught %d, escaped %d" % (e["retirement_id"], e["rule_name"], caught + escaped,
                                                           caught, escaped))
    if plant:
        print("plants by kind (caught, escaped): %s" % {k: tuple(v) for k, v in sorted(plant_tally.items())})
        print("entries %d: every plant caught in %d, a plant escaped in %d [PLANTED]" % (passed + failed, passed, failed))
        return 0 if failed == 0 else 1
    print("entries %d: pass %d, fail %d" % (passed + failed, passed, failed))
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
    v.add_argument("--holdings", default=str(out / "private_markets_holdings.parquet"),
                   help="published holdings parquet (default <PM_OUTPUT_DIR or data/output>/private_markets_holdings.parquet)")
    v.add_argument("--plant", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        res = build(a.review_ids, Path(a.holdings).as_posix(), Path(a.bdc_holdings).as_posix(), a.flags, a.ledger)
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        return 0
    return verify(Path(a.store), Path(a.holdings).as_posix(), a.plant)


if __name__ == "__main__":
    sys.exit(main())
