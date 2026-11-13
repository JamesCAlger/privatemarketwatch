"""Deterministic checks behind round 4 of the 2026-11-13 verdict-retirement campaign (standing rule D-252):
the real_error_check_silent findings of the rules rounds 1-2 did not attempt.

Same contract as rounds 1-3: recompute the verdict's own claim on today's published rows, each read on its
own printed line; silence is never evidence. With no assessment pointer, the rows a verdict is about are the
published rows of the fund-quarter whose issuer the verdict names (campaign_round3_check.names_in_verdict),
or a row id the verdict quotes; every such row must pass (strict: a verdict that names an issuer with five
tranches is tested on all five).

Modes (claim -> test):
  quarter totals  GAV_BDC02, A04, E01, E02, F20, html_agg, gav_reconciliation: the round-1 fv_conservation
                  test anchored on the verdict's filed total (top-level, every row equal to its own fact).
                  A GAV_BDC02 verdict about a missing comparison denominator is about the GAV artifact, not
                  holdings: not testable.
  B02             one published row per context, each a position line equal to its own fair-value fact and
                  bound to its context (round-2 positions test), every row on a report-date context.
  C201 / FX03 / cost_conservation / SRC_BDC01  the round-3 modes.
  C006            every published row carries the filing's accession and is bound to its context.
  C008            every published row carries an entity_name, the one the verdict quotes.
  named-row value rules (rows the verdict names):
     fmt_cost, C103, C104, X08, SRC_BDC03, C107  cost and fair value equal their own facts (page sign);
     C404, fmt_pct_of_net_assets, pct_position_concentration, pct_of_net_assets_identity  pct equals its own
         percent fact (or is blank where the line prints none);
     X10, maturity_not_past  the header-aware page reader's maturity cell (agenta check) equals the published
         maturity, or both are blank (N/A printed);
     X04, C115, D07, dl_rate_fill, C01, fmt_basis_spread  the round-3 per-row rate tests;
     C206, C203, fmt_issuer_name, PP01  issuer_name equals the issuer printed on the row's own line;
     no_provenance  the quoted row has a source context and equals its own fair-value fact;
     fmt_exposure_type  exposure_type populated, not a cash class on a non-cash line.
Not testable here: F10/F21/F23/F25/F26/F28/F33/income_identity/balance_sheet_identity (fund-level
financials, not holdings).

    python scripts/v05_evidence/campaign_round4_check.py build --rule R --review-ids ... --holdings H --ledger L --verdict-dir V --out res.json
    python scripts/v05_evidence/campaign_round4_check.py write --results res.json --holdings H --verdict-dir V --out store.json
    python scripts/v05_evidence/campaign_round4_check.py verify --store S --holdings H [--plant]
Read-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "v05_evidence"))
import campaign_retirement_check as base  # noqa: E402
import campaign_round2_check as c2  # noqa: E402
import campaign_round3_check as c3  # noqa: E402
from campaign_retirement_check import _eq, filing, row_fv  # noqa: E402
from pipeline import config  # noqa: E402

TOTALS = {"GAV_BDC02", "A04", "E01", "E02", "F20", "html_agg", "gav_reconciliation"}
VALUE = {"fmt_cost", "C103", "C104", "X08", "SRC_BDC03", "C107"}
PCTR = {"C404", "fmt_pct_of_net_assets", "pct_position_concentration", "pct_of_net_assets_identity"}
MATR = {"X10", "maturity_not_past"}
RATER = {"X04": "X04", "C115": "X05", "D07": "X05", "dl_rate_fill": "dl_rate_fill", "C01": "C01",
         "fmt_basis_spread": "fmt_basis_spread"}
ISSR = {"C206", "C203", "fmt_issuer_name", "PP01"}
R3 = {"C201", "FX03", "cost_conservation", "SRC_BDC01"}
UNTESTABLE = {r: "the claim is about fund-level financials (net assets, income, distributions), not holdings rows"
              for r in ("F10", "F21", "F23", "F25", "F26", "F28", "F33", "income_identity", "balance_sheet_identity")}
COLS = c3.COLS + ", CAST(entity_name AS VARCHAR) entity_name, CAST(maturity_date AS VARCHAR)[:10] maturity_date"


def quarter_rows(con, holdings, cik, rd):
    df = con.execute(f"""SELECT {COLS} FROM read_parquet('{holdings}')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')=? AND CAST(report_date AS VARCHAR)[:10]=?
          AND coalesce(CAST(accounting_record_class AS VARCHAR),'')<>'underlying_schedule'
        ORDER BY row_id""", [cik, rd]).fetchdf()
    return df.astype(object).where(df.notna(), None).to_dict("records")


def named_rows(rows, spec):
    ids = set(spec.get("row_ids") or [])
    return [r for r in rows if r["row_id"] in ids or (not ids and c3.names_in_verdict(r["issuer_name"], spec.get("vtext", "")))]


def t_value(r):
    return [(f["test"], False, f["why"]) for f in c2.t_cost_fv([r])] or [("cost_fv", True, "cost and fair value at their facts")]


def t_pct(r):
    fl = filing(r["cik"], r["accession_number"])
    facts = [f for f in fl.facts.get((base.PCT, r["src_context_id"]), []) if f["value"] is not None] if fl.ok else []
    if not facts:
        return [("pct", r["pct_of_net_assets"] in (None, 0.0), "no percent fact; published %s" % r["pct_of_net_assets"])]
    ok, why = base.row_pct(r)
    if not ok and r["pct_of_net_assets"] in (None, 0.0) and facts[0]["value"] == 0.0:
        ok = True
    return [("pct", ok, why)]


def t_maturity(r):
    import agenta_retirement_check as ag
    cell = ag.reader_maturity(r["cik"], r["accession_number"], r["report_date"], r["src_context_id"])
    pub = (r["maturity_date"] or "")[:10] or None
    return [("maturity_date", cell == pub, "published %s, reader's maturity cell %s" % (pub, cell))]


def check(rule, spec, con, holdings, cik, rd, rows=None):
    if rule in UNTESTABLE:
        return {"ok": False, "fails": [{"test": "claim", "why": UNTESTABLE[rule]}], "detail": {}}
    if spec.get("untestable"):
        return {"ok": False, "fails": [{"test": "claim", "why": spec["untestable"]}], "detail": {}}
    if rule in TOTALS:
        rows = rows if rows is not None else base.quarter_rows(con, holdings, cik, rd)
        return base.check_quarter("fv_conservation", rows, cik, rd, total_ctx=spec.get("total_ctx"),
                                  anchors=tuple(spec.get("anchors", ())))
    if rule in R3:
        return c3.check(rule, spec, con, holdings, cik, rd, rows=rows)
    rows = rows if rows is not None else quarter_rows(con, holdings, cik, rd)
    ctx = {"n_rows": len(rows), "accessions": sorted({r["accession_number"] for r in rows if r.get("accession_number")})}
    fails = []
    if rule == "B02":
        fails += c2.t_positions(rows)
    elif rule == "C006":
        want = spec.get("accession")
        for r in rows:
            if (r["accession_number"] or "") != want:
                fails.append({"row_id": r["row_id"], "test": "accession", "why": "published %r, filing %r" % (r["accession_number"], want)})
            ok, why = c2.row_bound(r)
            if not ok:
                fails.append({"row_id": r["row_id"], "test": "row_id", "why": why})
    elif rule == "C008":
        want = c2.name_key(spec.get("anchor"))
        for r in rows:
            if not want or c2.name_key(r["entity_name"]) != want:
                fails.append({"row_id": r["row_id"], "test": "entity_name", "why": "published %r, filing %r" % (r["entity_name"], spec.get("anchor"))})
            ok, why = c2.row_bound(r)
            if not ok:
                fails.append({"row_id": r["row_id"], "test": "row_id", "why": why})
    else:
        hit = named_rows(rows, spec)
        ctx["cited_rows"] = [r["row_id"] for r in hit]
        if not hit:
            fails.append({"test": "cited", "why": "no published row the verdict names"})
        for r in hit:
            tests = [("period",) + base.row_period(r)]
            if rule in VALUE:
                tests += t_value(r)
            elif rule in PCTR:
                tests += t_pct(r)
            elif rule in MATR:
                tests += t_maturity(r)
            elif rule in RATER:
                from pipeline.printed_margin import parse_rate
                if (rule == "X04" and r["basis_spread"] is None and not r["coupon_type"]
                        and parse_rate(base.row_line(r) or "") is None and c2.own_fact(r, c2.RATE) is None
                        and r["asset_class"] != "PRIVATE_CREDIT"):
                    continue   # a named non-credit row (equity) with no rate terms: not what X04 is about.
                    # A credit row whose line the reader cannot parse is tested, and fails (round-4 review).
                tests += c3.t_cited(RATER[rule], r, spec)[1:]
            elif rule in ISSR:
                tests.append(("issuer_name",) + c2.check_issuer(r))
            elif rule == "no_provenance":
                tests += [("fair_value",) + row_fv(r, require_fact=True), ("row_id",) + c2.row_bound(r)]
            elif rule == "fmt_exposure_type":
                v = (r["exposure_type"] or "").strip()
                tests.append(("exposure_type", bool(v) and not re.search("CASH|LIQUID", v, re.I) or bool(c3.MONEY.search(base.row_line(r) or "")),
                              "published %r" % v))
            else:
                tests.append(("claim", False, "no mode for rule %s" % rule))
            ctx["tested"] = ctx.get("tested", 0) + 1
            for name, ok, why in tests:
                if not ok:
                    fails.append({"row_id": r["row_id"], "test": name, "why": why})
        if hit and not ctx.get("tested"):
            fails.append({"test": "cited", "why": "none of the named rows carries the terms the claim is about"})
    return {"ok": not fails, "fails": fails, "detail": ctx}


def plants(rule, spec, rows):
    if rule in TOTALS:
        return base.plants("fv_conservation", rows, rows[0]["cik"], rows[0]["report_date"], total_ctx=spec.get("total_ctx")) if rows else []
    if rule in R3:
        return c3.plants(rule, spec, rows)
    out = []

    def swap(t, **kw):
        return [dict(r, **kw) if r is t else r for r in rows]
    hit = named_rows(rows, spec)
    t = hit[0] if hit else (rows[len(rows) // 2] if rows else None)
    if t is None:
        return out
    out.append(("row_from_other_filing", swap(t, accession_number="0000000000-00-000000")))
    if rule == "B02":
        out.append(("duplicate_row", rows + [dict(t, row_id=t["row_id"] + "|dup1")]))
    if rule == "C006":
        out.append(("accession_blank", swap(t, accession_number="")))
    if rule == "C008":
        out.append(("entity_blank", swap(t, entity_name="")))
    if rule in VALUE:
        out += [("cost_sign", swap(t, cost=-(t["cost"] or 1000.0))), ("fv_x1000", swap(t, fair_value=(t["fair_value"] or 1.0) * 1000)),
                ("cost_from_fv", swap(t, cost=(t["fair_value"] or 0) + 5000.0))]
    if rule in PCTR:
        out += [("pct_shift", swap(t, pct_of_net_assets=(t["pct_of_net_assets"] or 0.0) + 0.1)),
                ("pct_negative", swap(t, pct_of_net_assets=-0.1))]
    if rule in MATR:
        out.append(("acquisition_date_as_maturity", swap(t, maturity_date="2020-01-15")))
    if rule in RATER:
        tt = next((r for r in hit if r["basis_spread"] or r["coupon_type"]), t)
        out += [p for p in c3.plants(RATER[rule], dict(spec, context=tt["src_context_id"]), rows) if p[0] != "row_from_other_filing"]
        if rule == "X04" and tt["basis_spread"]:
            out.append(("spread_shift", swap(tt, basis_spread=tt["basis_spread"] + 0.25)))
            out.append(("pik_as_spread", swap(tt, basis_spread=(tt["pik_rate"] or 7.0) + 0.01)))
    if rule in ISSR:
        out.append(("path_in_issuer", swap(t, issuer_name="Debt Investments " + (t["issuer_name"] or "") + " First Lien")))
    if rule == "no_provenance":
        out.append(("no_context", swap(t, src_context_id="")))
    if rule == "fmt_exposure_type":
        out.append(("exposure_blank", swap(t, exposure_type="")))
    return out


def make_spec(rule, v):
    vtext = c3.verdict_text(v)
    spec = {"mechanism": v.get("mechanism"), "anchor": str(v.get("anchor_value") or ""), "vtext": vtext[:4000],
            "context": None}
    if rule in TOTALS or rule == "cost_conservation":
        spec["anchors"] = list(base.verdict_anchors(v))
    if rule == "GAV_BDC02" and (re.search(r"no_comparison|denominator", str(v.get("observed_value")) + vtext[:600], re.I)
                                and str(v.get("mechanism")) in ("extraction_gap", "anchor_bad")):
        spec["untestable"] = "the verdict's claim is the GAV reconciliation's missing comparison denominator, an artifact field, not holdings"
    if rule == "C006":
        m = re.search(r"\d{10}-\d{2}-\d{6}", str(v.get("anchor_value")) + " " + vtext)
        spec["accession"] = m.group(0) if m else None
    ids = sorted(set(re.findall(r"ROW-[0-9a-f]{16}", vtext)))
    if ids:
        spec["row_ids"] = ids
    if rule == "SRC_BDC01":
        spec.update(c3.make_spec(rule, {"printed_context": ""}, v))
    return spec


def build(rule, review_ids, holdings, ledger, verdict_dir):
    led = {r["review_id"]: r for r in csv.DictReader(open(ledger, newline="", encoding="utf-8-sig")) if r["review_id"] in review_ids}
    con = base._con()
    out = []
    for rid in review_ids:
        L = led[rid]
        cik, rd = L["cik"].zfill(10), L["report_date"][:10]
        vp = [p for p in (Path(verdict_dir) / s / (rid + ".json") for s in ("review_queue", "bdc_cik_review")) if p.exists()]
        v = json.loads(vp[0].read_text(encoding="utf-8-sig"))
        spec = make_spec(rule, v)
        res = check(rule, spec, con, holdings, cik, rd)
        res.update(review_id=rid, cik=cik, report_date=rd, rule_name=rule, engine=L["engine"], spec=spec)
        res["detail"].setdefault("accessions", sorted({r["accession_number"] for r in base.quarter_rows(con, holdings, cik, rd)
                                                       if r.get("accession_number")}))
        out.append(res)
        print("%s %s %s %s: %s fails=%d %s" % (rid, cik, rd, rule, "PASS" if res["ok"] else "FAIL", len(res["fails"]),
              ("; ".join(sorted({f.get("test", "") + ": " + str(f["why"])[:110] for f in res["fails"]}))[:420]).encode("ascii", "replace").decode()), flush=True)
        filing.cache_clear()
    return out


def _rows(con, holdings, rule, cik, rd):
    if rule in TOTALS:
        return base.quarter_rows(con, holdings, cik, rd)
    if rule in R3:
        return c3.quarter_rows(con, holdings, cik, rd)
    return quarter_rows(con, holdings, cik, rd)


def verify(store, holdings, plant):
    data = json.loads(Path(store).read_text(encoding="utf-8-sig"))
    con = base._con()
    passed = failed = 0
    tally = {}
    for e in data["retirements"]:
        spec = dict(e.get("check_spec", {}), total_ctx=e.get("filed_total_context"))
        rule, cik, rd = e["rule_name"], e["cik"], e["report_date"]
        rows = _rows(con, holdings, rule, cik, rd)
        if not plant:
            res = check(rule, spec, con, holdings, cik, rd, rows=rows)
            ok = res["ok"] and len(rows) == e.get("published_rows", len(rows))
            passed += ok
            failed += not ok
            print("%s %s %s %s: %s" % (e["retirement_id"], e["review_id"], rule, rd, "PASS" if ok else "FAIL"))
            for f in res["fails"][:5]:
                print("   %s" % json.dumps(f)[:300])
            continue
        caught = escaped = 0
        for name, p in plants(rule, spec, rows):
            bad = check(rule, spec, con, holdings, cik, rd, rows=p)["ok"]
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


def write(results, holdings, verdict_dir, out, other_store_dirs):
    from fund_gate import page_text
    from pipeline import verdict_retirements as vr
    taken = {}
    for d in other_store_dirs:
        for p in Path(d).glob("*.json"):
            if p.name == Path(out).name:
                continue
            for e in json.loads(p.read_text(encoding="utf-8-sig")).get("retirements") or []:
                taken.setdefault(e["review_id"], p.name)
    res = json.loads(Path(results).read_text(encoding="utf-8"))
    con = base._con()
    entries, skipped = [], []
    for r in res:
        if not r["ok"]:
            continue
        rid, rule, cik, rd = r["review_id"], r["rule_name"], r["cik"], r["report_date"]
        if rid in taken:
            skipped.append((rid, taken[rid]))
            print("SKIP %s: already retired in %s" % (rid, taken[rid]))
            continue
        vp = [p for p in (Path(verdict_dir) / s / (rid + ".json") for s in ("review_queue", "bdc_cik_review")) if p.exists()][0]
        rows = _rows(con, holdings, rule, cik, rd)
        spec = r["spec"]
        pool = rows if (rule in TOTALS or rule in R3 or rule in ("B02", "C006", "C008")) else named_rows(rows, spec)
        accs = sorted({x["accession_number"] for x in rows if x.get("accession_number")})
        page = page_text(cik, accs[0]) or "" if accs else ""
        lines = []
        tot = (r["detail"].get("total") or {}).get("total_line")
        for line in ([tot] if tot else []) + [base.row_line(x) for x in sorted(pool, key=lambda x: -abs(x["fair_value"] or 0))[:4]]:
            if line and line in page and line not in lines:
                lines.append(line)
            if len(lines) >= 3:
                break
        if not lines:
            print("SKIP %s: no verbatim printed line" % rid)
            continue
        t = r["detail"].get("total") or {}
        q = "private_markets_holdings.parquet (batch b1112b build), published basis: %d rows of %s %s from %s; rows the claim is about: %d" % (
            len(rows), cik, rd, ", ".join(accs), len(pool))
        if t:
            q += "; published sum %.0f (non-CASH %.0f); filed total %.0f (context %s); basis %s" % (
                t["sum_all"], t["sum_ex_cash"], t["total"], t["total_context"], t["basis"])
        e = {"retirement_id": "VR-CMP4-%s-%03d" % (rule, len(entries) + 1), "review_id": rid,
             "verdict_sha256": hashlib.sha256(vp.read_bytes()).hexdigest(), "cik": cik, "engine": r["engine"],
             "rule_name": rule, "report_date": rd,
             "reason": "Standing rule D-252: the check recomputes the verdict's claim (%s, rule %s) on the published rows it is about, "
                       "each read on its own printed line, and finds them at their filed values." % (
                           r["spec"].get("mechanism"), rule),
             "evidence": [{"source": "code", "quote": "scripts/v05_evidence/campaign_round4_check.py (%s); every realistic plant fails" % rule},
                          {"source": "query", "quote": q}] +
                         [{"source": "filing", "accession": accs[0], "quote": ln, "verbatim": True} for ln in lines],
             "cited_rows": [x["row_id"] for x in pool], "published_rows": len(rows),
             "rerun": "python scripts/v05_evidence/campaign_round4_check.py verify --store data/overrides/verdict_retirements/%s "
                      "--holdings <batch output>/private_markets_holdings.parquet (the b1112b build was used); add --plant: every "
                      "plant must fail. Needs the cached filings under data/raw/filings/bdc_html." % Path(out).name,
             "owner_words": ("run as recommended (standing rule D-252): an agent may retire a real-error verdict when a deterministic "
                             "check shows every row the verdict cites is published at its filed (printed) values in today's published "
                             "data, or is correctly excluded"),
             "decided_by": "owner", "decided_on": "2026-11-10",
             "applied_by": ("agent:retire-campaign-20261113-opus under the standing rule (owner ruling D-252, 2026-11-10); owner "
                            "2026-11-13: \"do it\" (retirement campaign round 4)"),
             "cohort_left": False,
             # rows a verdict names are recorded by id, so verify (and every plant) tests the same rows
             "check_spec": spec if pool is rows else dict(spec, row_ids=[x["row_id"] for x in pool])}
        if t.get("total_context"):
            e["filed_total_context"] = t["total_context"]
        probs = vr.validate(e)
        if probs:
            raise SystemExit("invalid entry %s: %s" % (rid, probs))
        entries.append(e)
        filing.cache_clear()
    Path(out).write_text(json.dumps({"_note": "Verdict-retirement campaign round 4 (2026-11-13), rule %s (standing rule D-252). "
                                              "Generated by campaign_round4_check.py write." % (res[0]["rule_name"] if res else ""),
                                     "retirements": entries}, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print("written %d entries to %s (skipped as already retired: %d)" % (len(entries), out, len(skipped)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    hold = str(Path(config.OUTPUT_DIR) / "private_markets_holdings.parquet")
    b = sub.add_parser("build")
    b.add_argument("--rule", required=True)
    b.add_argument("--review-ids", nargs="+", required=True)
    b.add_argument("--holdings", default=hold)
    b.add_argument("--ledger", required=True)
    b.add_argument("--verdict-dir", default=str(ROOT / "data" / "decisions" / "verdict_files"))
    b.add_argument("--out", required=True)
    w = sub.add_parser("write")
    w.add_argument("--results", required=True)
    w.add_argument("--holdings", default=hold)
    w.add_argument("--verdict-dir", default=str(ROOT / "data" / "decisions" / "verdict_files"))
    w.add_argument("--out", required=True)
    w.add_argument("--other-store-dir", action="append", default=[], help="store directories to check for an existing retirement")
    v = sub.add_parser("verify")
    v.add_argument("--store", required=True)
    v.add_argument("--holdings", default=hold)
    v.add_argument("--plant", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        res = build(a.rule, a.review_ids, Path(a.holdings).as_posix(), a.ledger, a.verdict_dir)
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        return 0
    if a.cmd == "write":
        dirs = a.other_store_dir or [str(ROOT / "data" / "overrides" / "verdict_retirements")]
        return write(a.results, Path(a.holdings).as_posix(), a.verdict_dir, a.out, dirs)
    return verify(Path(a.store), Path(a.holdings).as_posix(), a.plant)


if __name__ == "__main__":
    sys.exit(main())
