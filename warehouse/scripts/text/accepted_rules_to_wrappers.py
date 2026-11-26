"""Writes the rate-text rules the owner accepted on 2026-11-26 into each fund's wrapper copy (text slice R phase 3).

Usage (from warehouse/):  .venv\\Scripts\\python.exe scripts\\text\\accepted_rules_to_wrappers.py [--check]

Reads target/warehouse.duckdb read-only (the verdicts of int_text_proposal_verdict after the phase 3 check fixes, the
legends of int_text_legend_rate, the seeds) and replaces, in warehouse/wrappers/<cik>.json, every `reading_rules` entry
whose target is `rate_text` with the entries computed here. Every other key and entry is kept as it is. Output is
sorted and deterministic; --check writes nothing and exits 1 if a wrapper would change.

What is accepted (docs/owner_review_text_rates_2026-11-26.md, "Owner's answers"); nothing else is written:
  rate_column  a column the verdicts accept by check (grade checked), or one the owner accepted: items 8 (reference-code
               columns), 9 (Ares Coupon as all-in rate), 10 (Blue Owl "Interest": rate terms) (grade owner).
               Share-of-net-assets columns are not rate columns and get no rule.
  rate_role    one number role of one shape in one column. accepted_by_check -> checked (evidence: the check and its
               counts); a floor (item 5) -> untested; a rare shape (under 5 positions, both orders agree, no tagged row
               and no leg identity differs; item 7) -> matches_few_rows when some tagged row matches, else untested;
               Blue Owl's code-free "#%" in "Interest" (item 11, no all-in tag) -> fixed_rate_pct, untested.
               Anything else (unstable, contradicted, a non-floor role with no check on a shape of 5+ positions) gets no
               rule and stays unread.
  rate_code    the fund's dated code table (items 2, 3): for each code printed in a ruled column and each rate a
               filing's own legend gives it alone, the first and last report date of those filings and the latest of
               them as evidence. Grade checked when a proposal for that code and rate is accepted by check, else owner
               (item 2 one rate over time, item 3 several). Item 4: L, P, E, S with no legend anywhere in the fund,
               where every stable proposal of the fund names one rate -> owner, undated. Item 13: "Base Rate" and
               "CAD Base Rate" -> their own reference_rate rows (no benchmark), owner.
  rate_text_not_a_code  item 13: "Equity plus", "Variable".
  rate_printed_wins     the BCRED 2022-09-30 finding: in filing 0001803498-22-000021, table 25, printed rows 826 to 835,
               the printed all-in rate wins over the tag (owner "as recommended").
Item 1 (a code that is a rate's own name) is the general rule of seed reference_rate, not a wrapper entry.
"""
import json
import os
import sys

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
WAREHOUSE = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(WAREHOUSE, "target", "warehouse.duckdb")
WRAPPERS = os.path.join(WAREHOUSE, "wrappers")
CIKS = ["0001287750", "0001803498", "0001812554", "0001837532", "0001838126"]
REVIEW = "docs/owner_review_text_rates_2026-11-26.md"

OWNER_COLUMNS = {  # unit_key -> (column_holds, item)
    "1de53b4d55ea4050": ("all_in_rate", 9),
    "9ecddf9faf035680": ("reference_rate_code", 8),
    "501a2d64caadc662": ("reference_rate_code", 8),
    "aceeb6ccc5200e42": ("reference_rate_code", 8),
    "0dd66cba8d2b8641": ("rate_terms", 10),
}
FIXED_UNTESTED = {("25606633f0b6d5c8", "#%")}  # item 11, Blue Owl: no all-in tag to test it
WHOLE_COUPON_UNITS = {"1de53b4d55ea4050"}      # fix round 1 item 3: Ares "Coupon" (owner item 9)
NA_FIXED = [("010c6461a4a6ff27", "#%", "interest/ref.rate"),  # fix round 1 item 7: Blue Owl "Cash" beside "Ref. Rate"
            ("0429e10a0d4a5b47", "#%", "interest/ref.rate")]
COMMON_LETTERS = {"L", "P", "E", "S"}          # item 4
BASE_RATE_CODES = {"BASERATE": "Base Rate", "CADBASERATE": "CAD Base Rate"}  # item 13
NOT_A_CODE = {"EQUITYPLUS": "Equity plus", "VARIABLE": "Variable"}          # item 13
PRINTED_WINS = {"cik": "0001803498", "accession": "0001803498-22-000021", "table_index": 25, "first_row": 826,
                "last_row": 835}


def q(con, sql):
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def owner(item, text=""):
    return f"owner 2026-11-26 item {item} ({REVIEW})" + (f": {text}" if text else "")


def column_rules(con):
    rows = q(con, """
        select v.unit_key, v.cik, v.proposal, v.verdict, v.checks_confirming, v.tag_tagged_rows, v.tag_dominant_field,
               v.tag_dominant_share, u.table_signature, u.header_signature, u.header_text, u.group_header_text
        from int_text_proposal_verdict v join int_text_column_unit u on u.unit_key = v.unit_key
        where v.proposal_kind = 'column' order by v.cik, v.unit_key""")
    out = {}
    for r in rows:
        holds = r["proposal"].split("|")[0]
        if r["unit_key"] in OWNER_COLUMNS:
            holds, item = OWNER_COLUMNS[r["unit_key"]]
            grade, ev = "owner", owner(item, f"column holds {holds}")
        elif r["verdict"] == "accepted_by_check" and holds != "pct_of_net_assets":
            grade = "checked"
            ev = (f"check column_tags: {r['tag_tagged_rows']} tagged rows, dominant tag {r['tag_dominant_field']} "
                  f"share {r['tag_dominant_share']:.3f}")
        else:
            continue
        out[r["unit_key"]] = r
        yield r["cik"], {
            "target": "rate_text", "action": "rate_column",
            "parameter": {"table_signature": r["table_signature"], "header_signature": r["header_signature"],
                          "header_text": r["header_text"], "column_holds": holds, "source_grade": grade},
            "evidence": ev + f" (unit {r['unit_key']})"}
    column_rules.units = out


def role_rules(con):
    units = column_rules.units
    shapes = q(con, """
        select unit_key, shape, verdict, positions, stable, nt_differs, leg_fail
        from int_text_proposal_verdict where proposal_kind = 'shape'""")
    shape_info = {(s["unit_key"], s["shape"]): s for s in shapes}
    roles = q(con, """
        select v.unit_key, v.cik, v.shape, v.number_index, v.role, v.verdict, v.reason, v.stable, v.checks_confirming,
               v.nt_compared, v.nt_equal, v.nt_differs, v.leg_fail, v.label_changed_by, v.positions
        from int_text_proposal_verdict v
        where v.proposal_kind = 'role' order by v.cik, v.unit_key, v.shape, v.number_index""")
    by_shape = {}
    for r in roles:
        by_shape.setdefault((r["unit_key"], r["shape"]), []).append(r)
    for (unit, shape), rs in sorted(by_shape.items()):
        if unit not in units:
            continue
        u = units[unit]
        info = shape_info[(unit, shape)]
        rare_clean = (info["positions"] < 5 and all(r["stable"] for r in rs)
                      and sum(r["nt_differs"] or 0 for r in rs) == 0 and sum(r["leg_fail"] or 0 for r in rs) == 0)
        # fix round 1 item 9: a shape with any unstable or contradicted role gets no rule at all (its floor included)
        broken = any(r["verdict"] in ("unstable", "contradicted", "contradicted_small") for r in rs)
        single = shape.count("#") == 1
        for r in rs:
            role = r["role"]
            extra = {}
            if (unit, shape) in FIXED_UNTESTED and r["number_index"] == 1:
                role, grade = "fixed_rate_pct", "untested"
                ev = owner(11, "no rate code and a single number: a fixed rate; the fund files no all-in rate tag, so "
                               "the equality check cannot run")
            elif broken or role in ("pct_of_net_assets", "other_number", "cannot_tell") or not r["stable"]:
                continue
            elif r["verdict"] == "accepted_by_check":
                grade = "checked"
                ev = (f"check {r['checks_confirming']}: {r['nt_equal']} of {r['nt_compared']} compared rows equal")
                if r["label_changed_by"]:
                    ev += "; label fixed_rate set by check fixed_rate_no_code, " + owner(11)
            elif r["label_changed_by"] and r["verdict"] == "needs_owner" and not (r["nt_differs"] or 0):
                # fix round 1 item 8: the fixed-rate check found every compared row equal to the all-in tag, on fewer
                # than 5 rows; the spread label it replaces is not kept (item 11), the few rows grade it (item 7)
                grade = "matches_few_rows"
                ev = (owner(11, "no rate code, the number equals the all-in tag on every compared row: a fixed rate")
                      + f"; check fixed_rate_no_code {r['nt_equal']} of {r['nt_compared']}, under the 5-row bar")
            elif role == "floor_pct" and r["verdict"] == "needs_owner":
                grade, ev = "untested", owner(5, "the number before the word Floor is the floor; no filer tags a "
                                                 "floor, so no check exists")
            elif rare_clean and r["verdict"] == "needs_owner":
                if r["nt_compared"]:
                    grade = "matches_few_rows"
                    ev = owner(7, f"rare shape ({info['positions']} positions); {r['nt_equal']} of "
                                  f"{r['nt_compared']} tagged rows match, under the 5-row bar")
                else:
                    grade = "untested"
                    ev = owner(7, f"rare shape ({info['positions']} positions); no tagged row to compare")
            else:
                continue
            if unit in WHOLE_COUPON_UNITS and role == "pik_rate_pct" and single:
                # fix round 1 item 3 (owner item 9, controller ruling): "10.00% PIK" in the all-in column is the whole
                # coupon paid in kind: the number is the all-in rate and the PIK rate; no cash rate is written
                extra["whole_coupon"] = True
                ev += "; whole coupon paid in kind: also the all-in rate, " + owner(9) + ", controller ruling fix round 1"
            yield r["cik"], {
                "target": "rate_text", "action": "rate_role",
                "parameter": dict({"table_signature": u["table_signature"], "header_signature": u["header_signature"],
                                   "shape": shape, "number_index": r["number_index"], "role": role,
                                   "source_grade": grade}, **extra),
                "evidence": ev + f" (unit {unit})"}
    # fix round 1 item 7 (owner item 11, Blue Owl ruling; controller ruling): a number in the "Cash" column on a row
    # whose "Ref. Rate" cell prints N/A is a fixed rate; the printed N/A is the evidence that no reference rate exists
    for unit, shape, cond_header in NA_FIXED:
        if unit not in units:
            continue
        u = units[unit]
        yield u["cik"], {
            "target": "rate_text", "action": "rate_role",
            "parameter": {"table_signature": u["table_signature"], "header_signature": u["header_signature"],
                          "shape": shape, "number_index": 1, "role": "fixed_rate_pct", "source_grade": "untested",
                          "condition_header_signature": cond_header, "condition_text": "N/A"},
            "evidence": owner(11, "a number with no reference rate is a fixed rate; the row's Ref. Rate cell prints "
                                  "N/A; no all-in tag, so untested") + f", controller ruling fix round 1 (unit {unit})"}


def code_rules(con):
    units = column_rules.units
    unit_list = ",".join(f"'{k}'" for k in sorted(units))
    printed = q(con, f"""
        select distinct cik, upper(replace(reference_rate_code, ' ', '')) as code_key, reference_rate_code as code
        from int_text_rate_proposed
        where field = 'reference_rate_code' and unit_key in ({unit_list})""")
    spelling = {}
    for p in printed:
        spelling.setdefault((p["cik"], p["code_key"]), set()).add(p["code"])
    legend = q(con, """
        select cik, code_key, rates[1] as rate, min(report_date) as first_date, max(report_date) as last_date,
               max_by(accession, report_date) as evidence_accession, count(*) as filings
        from int_text_legend_rate where verdict = 'one_rate' group by 1, 2, 3""")
    legend_any = {(r["cik"], r["code_key"]) for r in q(con, "select distinct cik, code_key from int_text_legend_rate")}
    accepted = {(r["cik"], r["code_key"], r["rate"]) for r in q(con, """
        select v.cik, upper(replace(v.code, ' ', '')) as code_key, c.rate_name as rate
        from int_text_proposal_verdict v
        join text_proposed_code c on c.unit_key = v.unit_key and c.code = v.code
        where v.proposal_kind = 'code' and v.verdict = 'accepted_by_check'""")}
    proposals = q(con, """
        select u.cik, upper(replace(c.code, ' ', '')) as code_key, c.rate_name, c.same_in_both_orders
        from text_proposed_code c join int_text_column_unit u on u.unit_key = c.unit_key""")
    names = {r["rate_name"].upper().replace(" ", ""): r["rate_name"]
             for r in q(con, "select rate_name from reference_rate")}
    n_rates = {}
    for r in legend:
        n_rates[(r["cik"], r["code_key"])] = n_rates.get((r["cik"], r["code_key"]), 0) + 1
    written = set()
    for r in sorted(legend, key=lambda x: (x["cik"], x["code_key"], str(x["first_date"]))):
        key = (r["cik"], r["code_key"])
        if key not in spelling:
            continue
        if (r["cik"], r["code_key"], r["rate"]) in accepted:
            grade = "checked"
            ev = f"check legend: the proposal for this code and rate is accepted; {r['filings']} filings' own legends"
        else:
            item = 3 if n_rates[key] > 1 else 2
            grade = "owner"
            ev = owner(item, f"{r['filings']} filings' own legends give this code this rate alone")
        written.add(key)
        yield r["cik"], {
            "target": "rate_text", "action": "rate_code",
            "parameter": {"code": sorted(spelling[key])[0], "rate": r["rate"],
                          "first_filing_date": str(r["first_date"]), "last_filing_date": str(r["last_date"]),
                          "evidence_accession": r["evidence_accession"], "source_grade": grade},
            "evidence": ev}
    for (cik, code_key), spells in sorted(spelling.items()):
        if (cik, code_key) in written:
            continue
        code = sorted(spells)[0]
        if code_key in BASE_RATE_CODES:
            yield cik, {"target": "rate_text", "action": "rate_code",
                        "parameter": {"code": code, "rate": BASE_RATE_CODES[code_key], "source_grade": "owner"},
                        "evidence": owner(13, "stored as printed; it names no single benchmark")}
        elif code_key in NOT_A_CODE:
            yield cik, {"target": "rate_text", "action": "rate_text_not_a_code",
                        "parameter": {"code": code, "source_grade": "owner"},
                        "evidence": owner(13, "not a rate code")}
        elif code_key in COMMON_LETTERS and (cik, code_key) not in legend_any and code_key not in names:
            named = {p["rate_name"] for p in proposals if p["cik"] == cik and p["code_key"] == code_key}
            stable = all(p["same_in_both_orders"] for p in proposals if p["cik"] == cik and p["code_key"] == code_key)
            if stable and len(named) == 1 and next(iter(named)) in names.values():
                yield cik, {"target": "rate_text", "action": "rate_code",
                            "parameter": {"code": code, "rate": next(iter(named)), "source_grade": "owner"},
                            "evidence": owner(4, "no legend in the fund; the fund's proposals name this rate in "
                                                 "every column, both orders")}


def printed_wins_rules():
    p = PRINTED_WINS
    yield p["cik"], {
        "target": "rate_text", "action": "rate_printed_wins", "accession": p["accession"],
        "parameter": {"field": "all_in_rate", "table_index": p["table_index"], "first_row": p["first_row"],
                      "last_row": p["last_row"], "source_grade": "owner"},
        "evidence": ("owner 2026-11-26 (BCRED 2022-09-30, as recommended): on printed rows 826 to 835 of this table "
                     "each interest-rate tag sits on its printed row but belongs to the investment of the row above "
                     "(filed layer: docs/baseline_text_rates_phase2_2026-11-26.md section 10.4); the ten rows are the "
                     "evidence. The printed all-in rate wins over the tag on these rows only. No page read by a person.")}


def main():
    check = "--check" in sys.argv
    con = duckdb.connect(DB, read_only=True)
    try:
        entries = {}
        for gen in (column_rules(con), role_rules(con), code_rules(con), printed_wins_rules()):
            for cik, e in gen:
                entries.setdefault(cik, []).append(e)
    finally:
        con.close()
    order = {"rate_column": 0, "rate_role": 1, "rate_code": 2, "rate_text_not_a_code": 3, "rate_printed_wins": 4}
    changed = False
    conflicts = []
    pending = []
    for cik in CIKS:
        path = os.path.join(WRAPPERS, f"{cik}.json")
        with open(path, encoding="utf-8", newline="") as f:
            raw = f.read()
        wrapper = json.loads(raw)
        old = [e for e in wrapper.get("reading_rules", []) if e.get("target") == "rate_text"]
        conflicts += legend_conflicts(cik, old, entries.get(cik, []))
        kept = [e for e in wrapper.get("reading_rules", []) if e.get("target") != "rate_text"]
        new = sorted(entries.get(cik, []), key=lambda e: (order[e["action"]],
                                                          json.dumps(e["parameter"], sort_keys=True)))
        wrapper["reading_rules"] = kept + new
        # keep the file's own escaping: a copy that holds raw non-ASCII text is written so, else everything is escaped
        text = json.dumps(wrapper, indent=2, ensure_ascii=raw.isascii()) + "\n"
        if "\r\n" in raw:
            text = text.replace("\n", "\r\n")
        counts = {}
        for e in new:
            g = (e["action"], e["parameter"]["source_grade"])
            counts[g] = counts.get(g, 0) + 1
        print(cik, ", ".join(f"{a}/{g} {n}" for (a, g), n in sorted(counts.items())))
        if text != raw:
            changed = True
            pending.append((path, text))
    if conflicts and "--accept-legend-change" not in sys.argv:
        # fix round 1 item 4: a legend that contradicts an existing dated entry surfaces; nothing is written
        print("legend change against the existing dated code table (nothing written; look at it, then rerun with "
              "--accept-legend-change):")
        for c in conflicts:
            print("  " + c)
        sys.exit(2)
    if check:
        if changed:
            print("wrappers would change")
            sys.exit(1)
        return
    for path, text in pending:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)


def legend_conflicts(cik, old, new):
    """Dated rate_code entries of the wrapper as it stands that the new table contradicts: a new dated entry for the
    same code whose dates overlap an old one with another rate, or an old (code, rate) that is gone. Extending an
    entry's dates with the same rate (a new filing whose legend agrees) is not a conflict."""
    def dated(entries):
        out = []
        for e in entries:
            p = e.get("parameter") or {}
            if e.get("action") == "rate_code" and p.get("first_filing_date"):
                out.append((p["code"].upper().replace(" ", ""), p["rate"], p["first_filing_date"],
                            p["last_filing_date"]))
        return out
    o, n = dated(old), dated(new)
    found = []
    for code, rate, first, last in o:
        same = [x for x in n if x[0] == code and x[1] == rate]
        if not same:
            found.append(f"{cik} {code}={rate} {first}..{last}: no longer in the table")
        for c2, r2, f2, l2 in n:
            if c2 == code and r2 != rate and f2 <= last and first <= l2:
                found.append(f"{cik} {code}={rate} {first}..{last} overlaps new {code}={r2} {f2}..{l2}")
    return found


if __name__ == "__main__":
    main()
