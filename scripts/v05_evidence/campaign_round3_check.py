"""Deterministic checks behind round 3 of the 2026-11-13 verdict-retirement campaign (standing rule D-252):
the 124 real-error verdicts the parallel B2 assessment classed (b), "already fixed in production"
(scratch/2026-11-13_b2_assess/assessment.csv, states remediation_staged / remediation_pulled).

The assessment is used only as a pointer: for each finding it names the context of the row the verdict
cites. The check reads that row's own printed line (the <tr> carrying the context's own fair-value fact,
from campaign_retirement_check), requires the published row to name an issuer the verdict itself names,
and recomputes the verdict's claim on today's published data. Silence of the rule is never evidence.
Rules already covered by rounds 1-2 reuse those modes unchanged (FX01, FX02, B01, C04, fv_conservation).

Modes added here (the claim each tests, on the cited row unless stated):
  FX03            every published row has a US-dollar cost_currency and a cost equal to its own context's
                  US-dollar cost fact.
  cost_conservation  every row's cost equals its own fact and the published cost sums to the filed total
                  cost (an InvestmentOwnedAtCost fact on no position, dated the report date, equal to the
                  verdict's anchor, with no larger such fact).
  gav_reconciliation the round-1 fv_conservation test, anchored on the verdict's filed total.
  B02             duplicate positions: one published row per context, each equal to its own fair-value fact,
                  and the cited row at its printed fair value.
  C01, X02, dl_rate_fill  the cited credit row carries the printed margin (D-031) or the printed rate; for a
                  verdict whose mechanism is classification, the cited row is not classed private credit.
  X05, fmt_basis_spread  the cited row's basis_spread equals the printed margin.
  X04             the cited row's coupon type matches its line: a benchmark printed -> Floating with the
                  printed margin; none -> Fixed with no spread.
  X01             the cited row is not classed private equity and its interest_rate equals the printed rate.
  C107            the cited row's cost and fair value equal its own facts (sign from the page).
  C110, fmt_principal_amount  the cited row's principal_amount equals its own principal fact.
  C201            every published row is a position (own fair-value fact, own context) and none has a blank
                  issuer or a 'Total ...' issuer.
  C203, C206      the cited row's issuer_name equals the issuer printed on its own line.
  C301, C303, C304  the cited row's index_classification / exposure_type / asset_class is populated and
                  matches the class the verdict's anchor names (a money-market or short-term fund: a cash
                  class).
  SRC_BDC01       every position the verdict quotes is published: a row whose own line names it, equal to
                  its own fair-value fact.
Not testable here (reported, never retired): F16 / F33 (a fund-level distribution rate, not holdings),
nonaccrual_flag (filed non-accrual totals are not tagged facts), balance_sheet_identity, D06.

    python scripts/v05_evidence/campaign_round3_check.py build --rule X02 --review-ids ... --holdings H --ledger L --assessment A --verdict-dir V --out res.json
    python scripts/v05_evidence/campaign_round3_check.py verify --store S --holdings H [--plant]
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
import campaign_round2_check as c2  # noqa: E402
from agenta_retirement_check import field_ok  # noqa: E402
from campaign_retirement_check import FV, _eq, filing, printed_value, row_fv  # noqa: E402
from pipeline import config  # noqa: E402
from pipeline.printed_margin import parse_rate  # noqa: E402

ROUND1 = {"B01", "C04", "fv_conservation", "gav_reconciliation"}
ROUND2 = {"FX01", "FX02"}
CITED = {"C01", "X02", "dl_rate_fill", "X05", "fmt_basis_spread", "X04", "X01", "C107", "C110",
         "fmt_principal_amount", "C203", "C206", "C301", "C303", "C304", "B02"}
UNTESTABLE = {
    "F16": "the claim is about the fund-level distribution rate (fund_financials), not a holdings field",
    "F33": "the claim is about the fund-level distribution rate (fund_financials), not a holdings field",
    "nonaccrual_flag": "the filed non-accrual totals the verdict cites are not tagged facts; no deterministic read",
    "balance_sheet_identity": "the claim is about balance-sheet totals (members' capital), not holdings rows",
    "D06": "issuer names are not read reliably from this filer's lines (round-2 D06 reader)",
}
COLS = c2.COLS + """, CAST(cost_currency AS VARCHAR) cost_currency, CAST(coupon_type AS VARCHAR) coupon_type,
    CAST(exposure_type AS VARCHAR) exposure_type"""
MONEY = re.compile(r"money market|short[- ]term|treasur|liquidity|cash management|t-?fund", re.I)


def quarter_rows(con, holdings: str, cik: str, rd: str) -> list[dict]:
    df = con.execute(f"""SELECT {COLS} FROM read_parquet('{holdings}')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')=? AND CAST(report_date AS VARCHAR)[:10]=?
          AND coalesce(CAST(accounting_record_class AS VARCHAR),'')<>'underlying_schedule'
        ORDER BY row_id""", [cik, rd]).fetchdf()
    return df.astype(object).where(df.notna(), None).to_dict("records")


def verdict_text(v: dict) -> str:
    parts = [str(v.get(k) or "") for k in ("rationale", "observed_value", "anchor_value")]
    parts += [str(c.get("quoted_text") or "") for c in v.get("culprit_citations") or []]
    parts += [str(f.get("detail") or "") for f in v.get("findings") or [] if isinstance(f, dict)]
    return " ".join(parts)


def names_in_verdict(issuer: str, vtext: str) -> bool:
    """The published issuer is named by the verdict: its first two words (letters/digits) occur in it."""
    words = re.findall(r"[A-Za-z0-9&]+", issuer or "")
    words = [w for w in words if w.lower() not in ("the", "inc", "llc", "lp", "ltd", "co", "corp")]
    if not words:
        return False
    key = c2.name_key(" ".join(words[:2]))
    return len(key) >= 4 and key in c2.name_key(vtext)


def cited_rows(rows: list[dict], spec: dict) -> list[dict]:
    ctx = spec.get("context")
    return [r for r in rows if ctx and r["src_context_id"] == ctx]


def t_cited(rule: str, r: dict, spec: dict) -> list[tuple[str, bool, str]]:
    """(test, ok, why) for the cited row."""
    line = base.row_line(r) or ""
    fl = filing(r["cik"], r["accession_number"])
    out = []
    ok, why = base.row_period(r)
    out.append(("period", ok, why))
    if rule in ("C01", "X02", "dl_rate_fill"):
        if spec.get("mechanism") == "classification_lookthrough" and r["asset_class"] != "PRIVATE_CREDIT":
            out.append(("class", True, "published %s (not private credit)" % r["asset_class"]))
        else:
            out.append(("rate",) + c2.t_rate_present(r))
    elif rule in ("X05", "fmt_basis_spread"):
        out.append(("basis_spread",) + field_ok("basis_spread", r["basis_spread"], line))
    elif rule == "X04":
        rate = parse_rate(line)
        if rate:
            ok = (r["coupon_type"] or "").lower() == "floating"
            out.append(("coupon_type", ok, "printed benchmark %s; published %s" % (rate["code"], r["coupon_type"])))
            out.append(("basis_spread",) + field_ok("basis_spread", r["basis_spread"], line))
        else:
            ok = (r["coupon_type"] or "").lower() == "fixed" and not r["basis_spread"]
            out.append(("coupon_type", ok, "no benchmark printed; published %s spread %s" % (r["coupon_type"], r["basis_spread"])))
    elif rule == "X01":
        out.append(("class", r["asset_class"] != "PRIVATE_EQUITY", "published %s" % r["asset_class"]))
        rf = c2.own_fact(r, c2.RATE)
        out.append(("interest_rate", rf is not None and _eq(r["interest_rate"], c2.pct(rf), 0.006),
                    "published %s, printed %s" % (r["interest_rate"], c2.pct(rf) if rf else None)))
    elif rule == "C107":
        fails = c2.t_cost_fv([r])
        out.append(("cost_fv", not fails, "; ".join(f["why"] for f in fails) or "cost and fair value at their facts"))
    elif rule in ("C110", "fmt_principal_amount"):
        pfs = [f for f in fl.facts.get((c2.PRINC, r["src_context_id"]), []) if f["value"] is not None]
        if not pfs:
            out.append(("principal", r["principal_amount"] in (None, 0.0), "no principal fact; published %s" % r["principal_amount"]))
        else:
            ok, v, note = base.match_printed(fl, pfs, r["principal_amount"], 0.01)
            if not ok and r["principal_amount"] in (None, 0.0) and printed_value(fl, pfs[0]) == 0.0:
                ok = True
            out.append(("principal", ok, "published %s, printed %s%s" % (r["principal_amount"], v, note)))
    elif rule in ("C203", "C206"):
        out.append(("issuer_name",) + c2.check_issuer(r))
    elif rule in ("C301", "C303", "C304"):
        field = {"C301": "index_classification", "C303": "exposure_type", "C304": "asset_class"}[rule]
        val = (r.get(field) or "").strip()
        anchor = spec.get("anchor") or ""
        want = re.findall(r"\b[A-Z][A-Z_]{3,}\b", anchor)
        if MONEY.search(anchor):
            ok = bool(re.search(r"CASH|LIQUID|MONEY", val, re.I))
            why = "published %s %r; the verdict's anchor is a money-market / short-term fund" % (field, val)
        elif want:
            ok = val.upper() in want or (want[0] == "PRIVATE_CREDIT" and val == "PRIVATE_CREDIT")
            why = "published %s %r; the verdict expects %s" % (field, val, want)
        else:
            # the verdict names a non-cash line (a revolver, a loan): populated, and not a cash class
            ok = bool(val) and not re.search(r"CASH|LIQUID|MONEY", val, re.I)
            why = "published %s %r (the verdict's claim: blank; its line is not cash)" % (field, val)
        out.append((field, ok and bool(val), why))
    elif rule == "B02":
        out.append(("fair_value",) + row_fv(r, require_fact=True))
    return out


def check(rule: str, spec: dict, con, holdings: str, cik: str, rd: str, rows=None) -> dict:
    if rule in UNTESTABLE:
        return {"ok": False, "fails": [{"test": "claim", "why": UNTESTABLE[rule]}], "detail": {}}
    if rule in ROUND1:
        rows = rows if rows is not None else base.quarter_rows(con, holdings, cik, rd)
        r1 = "fv_conservation" if rule == "gav_reconciliation" else rule
        return base.check_quarter(r1, rows, cik, rd, total_ctx=spec.get("total_ctx"),
                                  anchors=tuple(spec.get("anchors", ())))
    if rule in ROUND2:
        return c2.check(rule, spec, con, holdings, cik, rd, rows=rows)
    rows = rows if rows is not None else quarter_rows(con, holdings, cik, rd)
    ctx = {"n_rows": len(rows), "accessions": sorted({r["accession_number"] for r in rows if r.get("accession_number")})}
    fails = []
    if rule == "FX03":
        for r in rows:
            if str(r["cost_currency"] or "").strip() and not c2.is_usd_text(r["cost_currency"]):
                fails.append({"row_id": r["row_id"], "test": "cost_currency", "why": str(r["cost_currency"])})
        fails += c2.t_cost_fv(rows)
    elif rule == "cost_conservation":
        fails += c2.t_cost_fv(rows)
        fl = filing(cik, ctx["accessions"][0]) if len(ctx["accessions"]) == 1 else None
        anchors = spec.get("anchors", [])
        cands = [f for f in (fl.by_name.get(c2.COST, []) if fl else []) if f["value"] is not None and fl.is_usd(f)
                 and (fl.contexts.get(f["context"]) or {}).get("instant") == rd
                 and "us-gaap:InvestmentIdentifierAxis" not in (fl.contexts.get(f["context"]) or {}).get("dims", {})]
        tot = [f for f in cands if any(abs(f["value"] - a) <= 0.5 * 10 ** max(f["scale"], 0) for a in anchors)]
        s = sum(r["cost"] or 0.0 for r in rows)
        if not tot:
            fails.append({"test": "total", "why": "no filed total cost fact equal to the verdict's anchor %s" % anchors})
        else:
            t = max(f["value"] for f in tot)
            larger = [f["value"] for f in cands if f["value"] > t + 2000 and not re.search(r"cash|liabilit", f["line"] or "", re.I)]
            ctx.update(total_cost=t, sum_cost=s, larger=larger[:3])
            if larger:
                fails.append({"test": "total", "why": "a larger cost fact %s is not explained" % larger[0]})
            if abs(s - t) > 2000:
                fails.append({"test": "total", "why": "published cost %.0f vs filed total cost %.0f" % (s, t)})
    elif rule == "C201":
        fails += c2.t_positions(rows)
        for r in rows:
            if not (r["issuer_name"] or "").strip() or re.match(r"(?i)\s*(sub)?total\b", r["issuer_name"] or ""):
                fails.append({"row_id": r["row_id"], "test": "issuer_name", "why": "issuer %r" % r["issuer_name"]})
    elif rule == "SRC_BDC01":
        for q in spec.get("quoted_positions", []):
            pat = re.escape(q[:40])
            hit = [r for r in rows if re.search(pat, base.row_line(r) or "", re.I)]
            if not hit:
                fails.append({"test": "cited", "why": "no published row whose own line names %r" % q})
            for r in hit:
                ok, why = row_fv(r, require_fact=True)
                if not ok:
                    fails.append({"row_id": r["row_id"], "test": "fair_value", "why": why})
        if not spec.get("quoted_positions"):
            fails.append({"test": "claim", "why": "the verdict quotes no position to look for"})
    elif rule in CITED:
        hit = cited_rows(rows, spec)
        if not hit:
            fails.append({"test": "cited", "why": "no published row on the cited context %s" % spec.get("context")})
        for r in hit:
            if not names_in_verdict(r["issuer_name"], spec.get("vtext", "")):
                fails.append({"row_id": r["row_id"], "test": "cited", "why": "the verdict does not name %r" % r["issuer_name"]})
            for name, ok, why in t_cited(rule, r, spec):
                if not ok:
                    fails.append({"row_id": r["row_id"], "test": name, "why": why})
        if rule == "B02":
            fails += c2.t_positions(rows)
        ctx["cited_rows"] = [r["row_id"] for r in hit]
    else:
        fails.append({"test": "claim", "why": "no mode for rule %s" % rule})
    return {"ok": not fails, "fails": fails, "detail": ctx}


def plants(rule: str, spec: dict, rows: list[dict]) -> list[tuple[str, list[dict]]]:
    if rule in ROUND1 or rule in ROUND2:
        return []   # the round-1/2 plants are run by their own verify (see verify below)
    out = []

    def swap(t, **kw):
        return [dict(r, **kw) if r is t else r for r in rows]
    hit = cited_rows(rows, spec)
    if rule == "SRC_BDC01" and spec.get("quoted_positions"):
        # plant on a row the claim is about: one whose own line names a quoted position
        q = spec["quoted_positions"][0]
        hit = [r for r in rows if re.search(re.escape(q[:40]), base.row_line(r) or "", re.I)]
    t = hit[0] if hit else (rows[len(rows) // 2] if rows else None)
    if t is None:
        return out
    out.append(("row_from_other_filing", swap(t, accession_number="0000000000-00-000000")))
    if rule in ("C01", "X02", "dl_rate_fill"):
        if spec.get("mechanism") == "classification_lookthrough" and t["asset_class"] != "PRIVATE_CREDIT":
            out.append(("non_credit_as_credit", swap(t, asset_class="PRIVATE_CREDIT")))
        else:
            out.append(("rate_dropped", swap(t, interest_rate=None, basis_spread=None)))
            out.append(("rate_shift", swap(t, interest_rate=(t["interest_rate"] or 0) + 1.0,
                                           basis_spread=(t["basis_spread"] or 0) + 0.75)))
    if rule in ("X05", "fmt_basis_spread"):
        out += [("spread_shift", swap(t, basis_spread=(t["basis_spread"] or 0) + 0.25)), ("spread_zero", swap(t, basis_spread=0.0))]
    if rule == "X04":
        out.append(("coupon_flipped", swap(t, coupon_type="Fixed" if (t["coupon_type"] or "").lower() == "floating" else "Floating")))
    if rule == "X01":
        out += [("as_private_equity", swap(t, asset_class="PRIVATE_EQUITY")), ("rate_20", swap(t, interest_rate=20.0))]
    if rule == "C107":
        out += [("cost_sign", swap(t, cost=-(t["cost"] or 1000.0))), ("cost_x1000", swap(t, cost=(t["cost"] or 1.0) * 1000))]
    if rule in ("C110", "fmt_principal_amount"):
        out += [("principal_sign", swap(t, principal_amount=-(t["principal_amount"] or 3144.0))),
                ("pct_as_principal", swap(t, principal_amount=0.24))]
    if rule in ("C203", "C206"):
        out.append(("path_in_issuer", swap(t, issuer_name="Debt Investments " + (t["issuer_name"] or "") + " Term Loan")))
    if rule in ("C301", "C303", "C304"):
        f = {"C301": "index_classification", "C303": "exposure_type", "C304": "asset_class"}[rule]
        out += [("blank_class", swap(t, **{f: ""})), ("wrong_class", swap(t, **{f: "PRIVATE_EQUITY" if MONEY.search(spec.get("anchor", "")) else "CASH"}))]
    if rule == "B02":
        out.append(("duplicate_row", rows + [dict(t, row_id="PLANT-DUP")]))
    if rule == "FX03":
        out += [("cost_currency_eur", swap(t, cost_currency="U_EUR")), ("cost_local", swap(t, cost=(t["cost"] or 0) * 0.9 + 1000))]
    if rule == "cost_conservation":
        out += [("row_dropped", [r for r in rows if r is not t]), ("cost_x1000", swap(t, cost=(t["cost"] or 1.0) * 1000))]
    if rule == "C201":
        out += [("subtotal_row", rows + [dict(t, row_id="PLANT-TOT", issuer_name="Total Debt Investments")]),
                ("blank_issuer", swap(t, issuer_name=""))]
    if rule == "SRC_BDC01":
        q = (spec.get("quoted_positions") or [""])[0]
        out.append(("cited_position_dropped", [r for r in rows if not re.search(re.escape(q[:40]), base.row_line(r) or "", re.I)]))
    return out


# ------------------------------------------------------------------------------------------------ build / verify

def make_spec(rule: str, a: dict, v: dict) -> dict:
    spec = {"context": a.get("printed_context") or None, "mechanism": v.get("mechanism"),
            "anchor": str(v.get("anchor_value") or ""), "vtext": verdict_text(v)[:4000]}
    if rule in ("fv_conservation", "gav_reconciliation", "B01", "cost_conservation"):
        spec["anchors"] = list(base.verdict_anchors(v))
    if rule == "SRC_BDC01":
        qs = []
        for c in v.get("culprit_citations") or []:
            q = str(c.get("quoted_text") or "").split("|")[0].strip()
            if len(q) >= 6 and not re.match(r"(?i)total", q):
                qs.append(q)
        spec["quoted_positions"] = sorted(set(qs))
    return spec


def build(rule, review_ids, holdings, ledger, assessment, verdict_dir) -> list[dict]:
    led = {r["review_id"]: r for r in csv.DictReader(open(ledger, newline="", encoding="utf-8-sig")) if r["review_id"] in review_ids}
    ass = {r["review_id"]: r for r in csv.DictReader(open(assessment, newline="", encoding="utf-8-sig")) if r["review_id"] in review_ids}
    con = base._con()
    out = []
    for rid in review_ids:
        L, A = led[rid], ass[rid]
        cik, rd = L["cik"].zfill(10), L["report_date"][:10]
        vp = [Path(verdict_dir) / s / (rid + ".json") for s in ("review_queue", "bdc_cik_review")]
        v = json.loads([p for p in vp if p.exists()][0].read_text(encoding="utf-8-sig"))
        spec = make_spec(rule, A, v)
        res = check(rule, spec, con, holdings, cik, rd)
        res.update(review_id=rid, cik=cik, report_date=rd, rule_name=rule, engine=L["engine"], spec=spec,
                   still_fires=A.get("check_now", ""))
        if rule in ROUND1:
            res["detail"].setdefault("accessions", sorted({r["accession_number"] for r in base.quarter_rows(con, holdings, cik, rd)}))
        out.append(res)
        print("%s %s %s %s: %s fails=%d %s" % (rid, cik, rd, rule, "PASS" if res["ok"] else "FAIL", len(res["fails"]),
              ("; ".join(sorted({f.get("test", "") + ": " + str(f["why"])[:110] for f in res["fails"]}))[:420]).encode(
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
        if rule in ROUND1:
            rows = base.quarter_rows(con, holdings, cik, rd)
        elif rule in ROUND2:
            rows = c2.quarter_rows(con, holdings, cik, rd)
        else:
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
        if rule in ROUND1:
            r1 = "fv_conservation" if rule == "gav_reconciliation" else rule
            planted = base.plants(r1, rows, cik, rd, total_ctx=spec.get("total_ctx"))
        elif rule in ROUND2:
            planted = c2.plants(rule, spec, rows)
        else:
            planted = plants(rule, spec, rows)
        caught = escaped = 0
        for name, p in planted:
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


CLAIM3 = {
    "FX01": "non-USD debt par published without principal_amount_usd; every debt row whose line prints a foreign currency now carries that currency, the printed par and principal_amount_usd at the H.10 reference rate",
    "FX02": "a foreign unit in fair_value_currency; every published row has a US-dollar fair_value_currency and a fair value equal to its own US-dollar fair-value fact",
    "FX03": "a foreign unit in cost_currency; every published row has a US-dollar cost_currency and a cost equal to its own US-dollar cost fact",
    "B01": "the quarter's leaves without fair value / polluted population; every published row has its own fair-value fact at the report date and equals it, and the published sum equals the top-level filed total investments",
    "C04": "equity rows without the printed count; every published equity row's shares_held equals the count on its own line",
    "fv_conservation": "the published fair value did not sum to the filed total investments; every row equals its own fact and the sum equals the top-level filed total",
    "gav_reconciliation": "the published position sum did not reconcile to the filed total investments; every row equals its own fact and the sum equals the top-level filed total",
    "cost_conservation": "the published cost did not sum to the filed total cost; every row's cost equals its own fact and the sum equals the filed total cost",
    "B02": "duplicate positions; one published row per context, each equal to its own fair-value fact, the cited row at its printed fair value",
    "C01": "the cited debt row had no rate; it now carries the printed margin or rate",
    "X02": "the cited credit row had no rate or spread (or a non-credit line was classed credit); it now carries the printed margin or rate, or is not classed private credit",
    "dl_rate_fill": "the cited direct-lending row had no rate; it now carries the printed margin or rate",
    "X05": "the cited floating row had a zero spread; its basis_spread now equals the printed margin",
    "fmt_basis_spread": "the cited row's spread was unreadable; its basis_spread now equals the printed margin (D-031)",
    "X04": "the cited row's coupon type contradicted its line; the coupon type and spread now match what the line prints",
    "X01": "the cited row was classed private equity with a stray rate; it is now not private equity and carries its printed rate",
    "C107": "the cited row's cost was not its printed cost; cost and fair value now equal its own facts",
    "C110": "the cited row's principal was not its printed principal; principal_amount now equals its own fact",
    "fmt_principal_amount": "the cited row's principal was a percent; principal_amount now equals its own principal fact",
    "C201": "subtotal rows with blank issuers were published; every published row is a position with its own fair-value fact and none has a blank or 'Total' issuer",
    "C203": "the cited row's issuer_name carried row text; it now equals the issuer printed on its own line",
    "C206": "the cited row's issuer_name carried path / instrument text; it now equals the issuer printed on its own line",
    "C301": "the cited row's index_classification was blank; it is now populated with the class the verdict names",
    "C303": "the cited row's exposure_type was blank; it is now populated with the class the verdict names",
    "C304": "the cited row's asset_class was blank or wrong; it now equals the class the verdict names",
    "SRC_BDC01": "positions printed in the schedule were not published; every position the verdict quotes now has a published row equal to its own fair-value fact",
}


def write(results: str, holdings: str, verdict_dir: str, out: str) -> int:
    import hashlib
    from fund_gate import page_text
    from pipeline import verdict_retirements as vr
    res = json.loads(Path(results).read_text(encoding="utf-8"))
    con = base._con()
    entries = []
    for r in res:
        if not r["ok"]:
            continue
        rid, rule, cik, rd = r["review_id"], r["rule_name"], r["cik"], r["report_date"]
        vp = [p for p in (Path(verdict_dir) / s / (rid + ".json") for s in ("review_queue", "bdc_cik_review")) if p.exists()][0]
        if rule in ROUND1:
            rows = base.quarter_rows(con, holdings, cik, rd)
        elif rule in ROUND2:
            rows = c2.quarter_rows(con, holdings, cik, rd)
        else:
            rows = quarter_rows(con, holdings, cik, rd)
        spec = r["spec"]
        pool = cited_rows(rows, spec) if rule in CITED else rows
        if rule == "C04":
            pool = [x for x in rows if base.is_equity(x)]
        accs = sorted({x["accession_number"] for x in rows if x.get("accession_number")})
        page = page_text(cik, accs[0]) or ""
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
        q = "private_markets_holdings.parquet (batch b1112b build), published basis: %d rows of %s %s from %s; rows the claim is about: %d" % (
            len(rows), cik, rd, ", ".join(accs), len(pool))
        t = r["detail"].get("total") or {}
        if t:
            q += "; published sum %.0f (non-CASH %.0f); filed total %.0f (context %s); basis %s" % (
                t["sum_all"], t["sum_ex_cash"], t["total"], t["total_context"], t["basis"])
        if r["detail"].get("total_cost"):
            q += "; published cost %.0f; filed total cost %.0f" % (r["detail"]["sum_cost"], r["detail"]["total_cost"])
        e = {"retirement_id": "VR-CMP3-%s-%03d" % (rule, len(entries) + 1), "review_id": rid,
             "verdict_sha256": hashlib.sha256(vp.read_bytes()).hexdigest(), "cik": cik, "engine": r["engine"],
             "rule_name": rule, "report_date": rd,
             "reason": "Standing rule D-252: the verdict found %s." % CLAIM3[rule],
             "evidence": [{"source": "code", "quote": "scripts/v05_evidence/campaign_round3_check.py (%s); every realistic plant fails" % rule},
                          {"source": "query", "quote": q}] +
                         [{"source": "filing", "accession": accs[0], "quote": ln, "verbatim": True} for ln in lines],
             "cited_rows": [x["row_id"] for x in pool], "published_rows": len(rows),
             "rerun": "python scripts/v05_evidence/campaign_round3_check.py verify --store data/overrides/verdict_retirements/%s "
                      "--holdings <batch output>/private_markets_holdings.parquet (the b1112b build was used); add --plant: every "
                      "plant must fail. Needs the cached filings under data/raw/filings/bdc_html." % Path(out).name,
             "owner_words": ("run as recommended (standing rule D-252): an agent may retire a real-error verdict when a deterministic "
                             "check shows every row the verdict cites is published at its filed (printed) values in today's published "
                             "data, or is correctly excluded"),
             "decided_by": "owner", "decided_on": "2026-11-10",
             "applied_by": ("agent:retire-campaign-20261113-opus under the standing rule (owner ruling D-252, 2026-11-10); owner "
                            "2026-11-13: \"do it\" (retirement campaign; round 3 = the B2 assessment's class (b) findings)"),
             "cohort_left": False, "check_spec": {k: v for k, v in spec.items() if k != "vtext"} | {"vtext": spec.get("vtext", "")},
             "still_fires_on_other_rows": r.get("still_fires", "").startswith(("OPEN", "warn"))}
        if t.get("total_context"):
            e["filed_total_context"] = t["total_context"]
        probs = vr.validate(e)
        if probs:
            raise SystemExit("invalid entry %s: %s" % (rid, probs))
        entries.append(e)
        filing.cache_clear()
    Path(out).write_text(json.dumps({"_note": "Verdict-retirement campaign round 3 (2026-11-13): the B2 assessment's class (b) "
                                              "real-error verdicts whose claim the deterministic check shows is no longer true of "
                                              "the published data (standing rule D-252). Generated by campaign_round3_check.py write.",
                                     "retirements": entries}, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print("written %d entries to %s" % (len(entries), out))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    hold = str(Path(config.OUTPUT_DIR) / "private_markets_holdings.parquet")
    b = sub.add_parser("build")
    b.add_argument("--rule", required=True)
    b.add_argument("--review-ids", nargs="+", required=True)
    b.add_argument("--holdings", default=hold)
    b.add_argument("--ledger", required=True)
    b.add_argument("--assessment", required=True)
    b.add_argument("--verdict-dir", default=str(ROOT / "data" / "decisions" / "verdict_files"))
    b.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--store", required=True)
    v.add_argument("--holdings", default=hold)
    v.add_argument("--plant", action="store_true")
    w = sub.add_parser("write")
    w.add_argument("--results", required=True)
    w.add_argument("--holdings", default=hold)
    w.add_argument("--verdict-dir", default=str(ROOT / "data" / "decisions" / "verdict_files"))
    w.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "write":
        return write(a.results, Path(a.holdings).as_posix(), a.verdict_dir, a.out)
    if a.cmd == "build":
        res = build(a.rule, a.review_ids, Path(a.holdings).as_posix(), a.ledger, a.assessment, a.verdict_dir)
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        return 0
    return verify(Path(a.store), Path(a.holdings).as_posix(), a.plant)


if __name__ == "__main__":
    sys.exit(main())
