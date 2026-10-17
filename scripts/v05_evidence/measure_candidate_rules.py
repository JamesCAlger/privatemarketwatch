"""Read-only: measure the five candidate rules (pipeline/candidate_rules.py) on the accepted sandboxes.

    python scripts/v05_evidence/measure_candidate_rules.py [--main <main checkout>] [--ciks c1,c2]

For every fund in docs/investigations/v05_readings/accepted_sandboxes.json (read from the main
checkout, where the gitignored sandboxes live) it loads that fund's published rows from its accepted
sandbox, runs each rule, and writes, in this checkout's docs/investigations/:

    v05_rule_candidates_2026-10-17.md            summary, per rule x fund table, 10 sampled rows per rule
    v05_rule_candidates_2026-10-17.csv           per rule x fund: rows, fund-quarters, fair value flagged
    v05_rule_candidates_2026-10-17_rows.csv      every flagged row
    v05_rule_candidates_2026-10-17_industry_coverage.csv   rule 4: every fund-quarter's coverage

Nothing here is wired into the ledger, the gate or a build. One fund at a time, DuckDB memory 3GB.
"""
from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import candidate_rules as cr  # noqa: E402

STEM = "v05_rule_candidates_2026-10-17"
SEED = 20261017
SAMPLE = 10


def _default_main() -> Path:
    parts = REPO.parts
    if ".claude" in parts:
        return Path(*parts[:parts.index(".claude")])
    return REPO


def _normalise(text: str) -> str:
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[‐-―−]", "-", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip()


_PAGES: dict[tuple[str, str], str | None] = {}


def page_line(main: Path, cik: str, accession: str, issuer: str, width: int = 320) -> str:
    """The first visible line of the cached filing that starts with the issuer's first words.
    Only called for sampled rows with no printed row."""
    key = (cik, accession)
    if key not in _PAGES:
        path = main / "data/raw/filings/bdc_html" / cik.lstrip("0") / (str(accession).replace("-", "") + ".html")
        _PAGES.clear()
        _PAGES[key] = (_normalise(re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="replace")))
                       if path.exists() else None)
    text = _PAGES[key]
    if text is None:
        return "(filing not in the cache)"
    phrase = _normalise(str(issuer or ""))[:24].strip()
    if len(phrase) < 4:
        return "(no issuer name to search)"
    for match in re.finditer(re.escape(phrase), text, flags=re.I):
        window = text[match.start(): match.start() + 200]
        if re.search(r"\d{4}-\d{2}-\d{2} 0\d{9}", window) or "Member" in window[:160]:
            continue
        return "page: " + text[max(0, match.start() - 40): match.start() + width]
    return "(issuer's first words not found on the visible page)"


OVERLAP = {
    "issuer_name_differs_from_page": (
        "Partial. Oracle I09 flags a fund-quarter where more than 5 pct of issuer names equal a GICS "
        "sub-industry label (aggregate; misses isolated rows, the filer's own labels and any name that is "
        "merely wrong). The fund gate's check_names (scripts/v05_evidence/fund_gate.py, not a ledger rule) "
        "looks for instrument words, row numbers, holder labels and a leading industry, above 1 pct of a "
        "fund's rows. Neither compares the name with the printed row, so the observed member-spelling "
        "cases (Covetrus as 'CVET Midco 2', NextCar, 'Global Solutions' for Continuum Global Solutions) "
        "pass both."),
    "unit_count_differs_from_row_text": (
        "None on value. Oracle C04 requires 70 pct of a fund-quarter's equity rows to carry any unit count "
        "(presence only); F11 checks the sign. field_coverage_drop ('unit count on equity') looks at the "
        "share carrying a count against the prior quarter. A wrong count published by the shared normaliser "
        "satisfies all three."),
    "pik_printed_not_published": (
        "None. C116/C117 check that a published pik_rate parses and lies in 0-20; pik_status's pik_terms "
        "proxy reads the published pik_rate. Nothing reads the PIK figure on the printed row or in the "
        "terms text, so a row with no PIK tag publishes no PIK and no rule fires."),
    "industry_not_published": (
        "Partial. field_coverage_drop ('filer industry', extracted_industry) fires on a fall of 20 points "
        "against the fund's previous quarter with 20+ funded rows; it is blind to a fund's first quarters "
        "(Golub 2023, Stone Point 2023-24) and to a gap that never closes (Guardian IV). It also reads "
        "extracted_industry, while the public sector partition reads gics_sub_industry "
        "(pipeline/public_partitions.py). This candidate reads gics_sub_industry and reports both."),
    "preferred_published_as_common": (
        "Partial. Column rule X01 flags a PRIVATE_EQUITY row not classed PREFERRED_EQUITY with interest_rate "
        "> 0, so it catches a dividend rate on a common row but not a PIK-only rate (Commonwealth LNG, KWOR "
        "publish pik_rate and no interest_rate) and never the text. Oracle C05 is a global share of rows whose "
        "instrument text says common and carry a rate. No rule reads 'preferred' on the printed row against "
        "the class."),
}


# Written after reading the seed-20261017 samples of the run committed with this script. A rerun on
# changed sandboxes draws other rows; re-read before quoting these.
READS = {
    "issuer_name_differs_from_page": (
        "9 of 10 look like real name errors: 7 carry the member's group name in front of the legal name "
        "(Apollo Debt Solutions 'Gannett Gannett Holdings, LLC', 'CINC Systems 1475 Holdings, LLC', 'HKA Mount Olympus "
        "Bidco Limited'), one a sequence word (',Two Recochem, Inc'), one an industry prefix (BlackRock 'Technology "
        "PointClickCare'). 1 false alarm: New Mountain prints an industry heading in the row's first cell "
        "('Consumer Products') that the heading test missed. Apollo alone is 4,179 of the flagged rows: the "
        "group-name prefix is on most of its published names. spacing_only (193) is a separate kind for "
        "'Circus Trix'/'CircusTrix'-type differences; some of those are the page's typo, not the build's."),
    "unit_count_differs_from_row_text": (
        "8 of 10 real: another row's count or a x1000/1000 shift (Ares Storm 3,297,791 for the printed 3,958; "
        "AthenaHealth 198,505 for 10,487,951; BCRED Point Broadband 12,870 for 147,380; Sixth Street SMA 244 for "
        "173,048). 2 unclear: BCRED Genstar 'Blocker Note' (a note classed equity; its printed 159,782 is a par, so "
        "no count applies but the published 1,041 is not printed either) and HPS BCPE Virginia (published 2,000,000 "
        "for a printed 2,000: a thousands scale, not decidable from the row). Almost all flags are shares_held_source "
        "'derived_proxy': the shared normaliser (with_shares_fix) is the cause, as the observations say."),
    "pik_printed_not_published": (
        "Printed-not-published: 9 of 10 real (Ares 'Senior preferred stock 10.00% PIK', HPS 'Foundation Automotive "
        "SF + 7.75% PIK', Crescent 'E + 1000 PIK'); 1 unclear (Crescent iLending, basis member_page_silent: the "
        "member says PIK, the printed row prints no rate at all). Mismatch: 8 of 10 real: pik_rate holds the floor "
        "(MidCap KLO 1.00 and HomeRenew 2.50 for 'SOFR+650 PIK, 2.50% Floor'; AB Single Digits 1.00), the spread "
        "(Blue Owl Kaseya 6.25 for '6.25% (2.50% PIK)') or the all-in coupon (Ares PRG 12.88 for '12.88% (3.13% "
        "PIK)'); 2 unclear (Crescent BioAgilytix 0.75 vs 2.75, AB American Physician 3.5 vs 3.0). Tags rounded to "
        "one decimal are their own kind, pik_value_rounding (3 rows)."),
    "industry_not_published": (
        "10 of 10 are funded rows with no published industry. New Mountain (Guardian IV, Private Credit, NMF SLF) "
        "and Stone Point print the heading on the page and the build does not read it; HPS rows print no industry "
        "on the row and the GICS name cache has no entry. All are real gaps in the field; whether a gap is an "
        "error to fix or a coverage limit is the owner's call."),
    "preferred_published_as_common": (
        "rate_on_common (399 of 546) is mostly not evidence of preferred: of its 10 samples 9 are units the filer "
        "does not call preferred but which carry a PIK or fixed dividend (Ares 'Class A units 8.00% PIK', Monroe "
        "NationsBenefits 'Series B units 5.00% PIK', Sixth Street 'Class AA Units 20.00%', Ares CFC 'Loan "
        "instrument units 9.75% PIK'); outside the sample BCRED Port Arthur LNG 'Class B Units 7.60% PIK' (1,079M) "
        "is the same shape. 1 is a loan published as common equity (HPS DCA Acquisition '13.13% PIK', maturity "
        "12/28/2032; HPS Foundation Automotive 'SF + 7.75% PIK' is another), a real class error but not a preferred "
        "one. The text "
        "kinds are stronger: 10 of 10 text samples read as preferred published as common (9 AB Private Credit "
        "venture rows filed under 'U.S. Preferred Stock', Series C-1 to G; Golub Eclipse 'Preferred stock'), but "
        "the sample is 90 pct one fund. Outside it: Ares McLaren 'Senior preference shares', Blue Owl Metis "
        "'Series A Convertible Preferred Stock'. rate_on_common needs an owner ruling on PIK-dividend units first."),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", type=Path, default=_default_main())
    ap.add_argument("--ciks", default="")
    args = ap.parse_args(argv)
    main_dir: Path = args.main
    registry = json.loads((main_dir / "docs/investigations/v05_readings/accepted_sandboxes.json").read_text(encoding="utf-8"))
    wanted = {c.strip().zfill(10) for c in args.ciks.split(",") if c.strip()}
    flagged, coverage, funds = [], [], []
    for cik, entry in registry.items():
        if wanted and cik not in wanted:
            continue
        label = entry["label"]
        out = main_dir / "scratch/fund_sandbox" / label / "output"
        con = duckdb.connect()
        con.execute("SET memory_limit='3GB'")
        con.execute("SET threads=4")
        cr.load_fund_rows(con, out, cik)
        n_rows, n_printed, n_q = con.execute(
            "SELECT count(*), count(printed_row), count(DISTINCT report_date) FROM cand_rows").fetchone()
        name = con.execute(f"""SELECT any_value(entity_name) FROM read_parquet('{(out / "private_markets_holdings.parquet").as_posix()}')
                               WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '{cik}'""").fetchone()[0]
        funds.append({"cik": cik, "fund": name, "label": label, "rows": n_rows, "rows_on_page": n_printed, "quarters": n_q})
        print("%s %-6s rows=%d on_page=%d" % (cik, label, n_rows, n_printed), flush=True)
        for rule_name, rule in cr.RULES.items():
            df = rule(con)
            if not df.empty:
                df["label"] = label
                df["fund"] = name
                flagged.append(df)
            print("   %-34s %d" % (rule_name, len(df)), flush=True)
        cov = cr.industry_coverage(con)
        cov["fund"] = name
        coverage.append(cov)
        con.close()

    rows = pd.concat(flagged, ignore_index=True) if flagged else pd.DataFrame(columns=cr.OUTPUT_COLUMNS + ["label", "fund"])
    cov = pd.concat(coverage, ignore_index=True)
    fundf = pd.DataFrame(funds)
    docs = REPO / "docs/investigations"
    rows["fair_value"] = pd.to_numeric(rows["fair_value"], errors="coerce")

    # per rule x fund
    summary = []
    for (rule, cik), g in rows.groupby(["rule", "cik"]):
        kinds = g["kind"].value_counts()
        summary.append({"rule": rule, "cik": cik, "fund": g["fund"].iloc[0], "label": g["label"].iloc[0],
                        "rows_flagged": len(g), "fund_quarters_flagged": g["report_date"].nunique(),
                        "fv_flagged_m": round(g["fair_value"].fillna(0).sum() / 1e6, 2),
                        "rows_on_page_basis": int((g["basis"] == "page").sum()),
                        "kinds": "; ".join("%s:%d" % (k, v) for k, v in kinds.items())})
    summ = pd.DataFrame(summary, columns=["rule", "cik", "fund", "label", "rows_flagged", "fund_quarters_flagged",
                                          "fv_flagged_m", "rows_on_page_basis", "kinds"])
    summ.to_csv(docs / f"{STEM}.csv", index=False)
    keep = ["rule", "kind", "basis", "cik", "fund", "label", "report_date", "accession_number", "row_id", "issuer_name",
            "instrument_description", "fair_value", "published", "printed", "printed_row", "member"]
    trimmed = rows[keep].copy()
    for col in ("printed_row", "member", "instrument_description"):
        trimmed[col] = trimmed[col].astype("string").str.slice(0, 300)
    trimmed.sort_values(["rule", "cik", "report_date", "row_id"]).to_csv(docs / f"{STEM}_rows.csv", index=False)
    cov.to_csv(docs / f"{STEM}_industry_coverage.csv", index=False)

    write_report(docs / f"{STEM}.md", rows, summ, cov, fundf, main_dir)
    print("wrote", docs / f"{STEM}.md")
    return 0


def _fmt(v, n=90) -> str:
    s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    s = s.replace("|", "/").replace("\n", " ")
    return (s[:n] + "...") if len(s) > n else s


def _sample(df: pd.DataFrame, k: int, rng: random.Random) -> pd.DataFrame:
    df = df.sort_values(["cik", "report_date", "row_id", "kind"]).reset_index(drop=True)
    if len(df) <= k:
        return df
    return df.iloc[sorted(rng.sample(range(len(df)), k))]


def write_report(path: Path, rows, summ, cov, fundf, main_dir: Path) -> None:
    L = []
    L.append("# v0.5 candidate rules, measured on the accepted sandboxes (2026-10-17)")
    L.append("")
    L.append("Owner, 2026-10-17: \"do it\" -- build the five candidate rules and measure them; do NOT switch them on. "
             "Code: `pipeline/candidate_rules.py` (not imported by the build, ledger, shadow engines, quarter pass or gate). "
             "Script: `scripts/v05_evidence/measure_candidate_rules.py`. Inputs: each fund's accepted sandbox in "
             "`docs/investigations/v05_readings/accepted_sandboxes.json`, published basis (no `underlying_schedule` rows). "
             "Page access: `printed_row` from that sandbox's `bdc_ixbrl_field_status` (current period, member printed once).")
    L.append("")
    L.append("Files: `%s.csv` (rule x fund), `%s_rows.csv` (every flagged row), `%s_industry_coverage.csv` (rule 4)." % (STEM, STEM, STEM))
    L.append("")
    tot_rows, tot_page = int(fundf["rows"].sum()), int(fundf["rows_on_page"].sum())
    L.append("Funds measured: %d; published rows: %d; rows whose printed row is known: %d (%.1f pct). Funds where "
             "the page reader is (almost) never joined fall back to member text and shape tests: %s." % (
                 len(fundf), tot_rows, tot_page, 100.0 * tot_page / max(tot_rows, 1),
                 ", ".join("%s %s (%d of %d)" % (r.cik, _fmt(r.fund, 40), r.rows_on_page, r.rows)
                           for r in fundf.itertuples() if r.rows and r.rows_on_page / r.rows < 0.2) or "none"))
    L.append("")
    L.append("A clean result is not 'data correct': these rules see only what the page reader joined and the shapes coded.")
    L.append("")
    L.append("## Totals")
    L.append("")
    L.append("| rule | rows | fund-quarters | funds | FV flagged (M) | rows on page basis | kinds |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    rng = random.Random(SEED)
    for rule in cr.RULES:
        g = rows[rows["rule"] == rule]
        fq = g[["cik", "report_date"]].drop_duplicates().shape[0]
        kinds = "; ".join("%s:%d" % (k, v) for k, v in g["kind"].value_counts().items())
        L.append("| %s | %d | %d | %d | %.1f | %d | %s |" % (rule, len(g), fq, g["cik"].nunique(),
                                                           g["fair_value"].fillna(0).sum() / 1e6, (g["basis"] == "page").sum(), kinds))
    L.append("")
    for rule in cr.RULES:
        g = rows[rows["rule"] == rule]
        L.append("## %s" % rule)
        L.append("")
        L.append("**Overlap with existing rules.** " + OVERLAP[rule])
        L.append("")
        if rule == "industry_not_published":
            _industry_section(L, cov)
        s = summ[summ["rule"] == rule].sort_values("fv_flagged_m", ascending=False)
        L.append("Per fund (flagged funds only):")
        L.append("")
        L.append("| cik | fund | sandbox | rows | fund-quarters | FV (M) | kinds |")
        L.append("|---|---|---|---:|---:|---:|---|")
        for r in s.itertuples():
            L.append("| %s | %s | %s | %d | %d | %.1f | %s |" % (r.cik, _fmt(r.fund, 45), r.label, r.rows_flagged,
                                                              r.fund_quarters_flagged, r.fv_flagged_m, r.kinds))
        L.append("")
        groups = [("", g)]
        if rule == "pik_printed_not_published":
            groups = [(" (kind pik_printed_not_published)", g[g["kind"] == "pik_printed_not_published"]),
                      (" (kind pik_value_mismatch, reported separately)", g[g["kind"] == "pik_value_mismatch"])]
        if rule == "preferred_published_as_common":
            groups = [(" (text kinds: text_says_preferred, text_and_rate)", g[g["kind"] != "rate_on_common"]),
                      (" (kind rate_on_common)", g[g["kind"] == "rate_on_common"])]
        if rule in READS:
            L.append("**Read of the samples below (agent, 2026-10-17; not a disposition).** " + READS[rule])
            L.append("")
        for title, gg in groups:
            if gg.empty:
                continue
            L.append("Sample of %d flagged rows%s, seed %d:" % (min(SAMPLE, len(gg)), title, SEED))
            L.append("")
            L.append("| # | fund / quarter | kind / basis | issuer | FV | published | printed figure | printed row or page line |")
            L.append("|---|---|---|---|---:|---|---|---|")
            for i, r in enumerate(_sample(gg, SAMPLE, rng).itertuples(), 1):
                line = r.printed_row if isinstance(r.printed_row, str) and r.printed_row else (
                    "member: " + _fmt(r.member, 200) + " ; " + page_line(main_dir, r.cik, r.accession_number, r.issuer_name))
                L.append("| %d | %s %s | %s / %s | %s | %s | %s | %s | %s |" % (
                    i, _fmt(r.fund, 28), r.report_date, r.kind, r.basis, _fmt(r.issuer_name, 50),
                    "" if pd.isna(r.fair_value) else "{:,.0f}".format(r.fair_value), _fmt(r.published, 60),
                    _fmt(r.printed, 60), _fmt(line, 330)))
            L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _industry_section(L, cov: pd.DataFrame) -> None:
    c = cov[cov["n_funded"] >= cr.INDUSTRY_MIN_ROWS]
    L.append("Coverage distribution, fund-quarters with %d+ funded rows (n = %d of %d):" % (
        cr.INDUSTRY_MIN_ROWS, len(c), len(cov)))
    L.append("")
    L.append("| coverage below | gics_sub_industry (published) | extracted_industry (filer) |")
    L.append("|---|---:|---:|")
    for t in (0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 1.0):
        L.append("| %.2f | %d | %d |" % (t, (c["gics_coverage"] < t).sum(), (c["extracted_coverage"] < t).sum()))
    q = c["gics_coverage"].quantile([0.05, 0.1, 0.25, 0.5]).round(3).to_dict()
    L.append("")
    L.append("gics_sub_industry coverage percentiles: p05 %.3f, p10 %.3f, p25 %.3f, median %.3f. Threshold used for the "
             "flagged rows below: %.2f (proposed; see the reply)." % (q[0.05], q[0.1], q[0.25], q[0.5], cr.INDUSTRY_COVERAGE_THRESHOLD))
    L.append("")
    low = c.sort_values("gics_coverage").head(15)
    L.append("Lowest 15 fund-quarters:")
    L.append("")
    L.append("| cik | fund | quarter | funded rows | gics coverage | extracted coverage | FV without gics (M) |")
    L.append("|---|---|---|---:|---:|---:|---:|")
    for r in low.itertuples():
        L.append("| %s | %s | %s | %d | %.3f | %.3f | %.1f |" % (r.cik, _fmt(r.fund, 40), r.report_date, r.n_funded,
                                                           r.gics_coverage, r.extracted_coverage, (r.fv_no_gics or 0) / 1e6))
    L.append("")


if __name__ == "__main__":
    sys.exit(main())
