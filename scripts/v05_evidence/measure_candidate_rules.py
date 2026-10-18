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
        "the class. Text kinds only since D-207 (the first run's rate_on_common, 399 rows, is gone)."),
}


# Written 2026-10-18 after reading the seed-20261017 samples of the revised run (52 funds). A rerun
# on changed sandboxes draws other rows; re-read before quoting these. Precision on a fund-capped
# sample of 30 per rule is in v05_rule_candidates_falsealarm_2026-10-18.md (pre-fix rules).
READS = {
    "issuer_name_differs_from_page": (
        "9 of 10 real: 8 carry the member's group name in front of the legal name (Apollo Debt Solutions 'Delivery "
        "Hero Delivery Hero Finco Germany GmbH', 'Golden Hippo Altern Marketing, LLC'; Apollo is 4,177 of the "
        "5,759 rows), 1 a heading residue (Sixth Street 'and Consumer Products Rapid Data GmbH'). 1 cosmetic: "
        "Crescent 'Bankers Toolbox' for the printed 'Banker's Toolbox' (kind spacing_only; an apostrophe, not a "
        "build error). The New Mountain industry-cell leaks are gone with the blind-quarter suppression. "
        "(Read on the 2026-10-18 run; the 2026-10-19 near-spelling restriction adds 175 rows, the Wildcat shape "
        "and misjoined printed rows that the broad 'printed elsewhere' pass had hidden; not re-sampled.)"),
    "unit_count_differs_from_row_text": (
        "Finding kinds: 9 of 10 real (Ares AthenaHealth 198,505 for 10,487,951; Carlyle Talon 1,018,000 for "
        "145,631; ASIF Mustang 883 for 883,420; BCRED Point Broadband, Zoro, Jupiter), 1 unclear (BCRED GTCR/Jupiter "
        "'Blocker Note', a note classed equity whose 115,036 is a par). units_scale_unclear holds HPS-type rows "
        "as asked, but the same shape also covers rows the review called real (26North FH DMI 400,429,000 for "
        "400,429) and Blue Owl rows (Insight CP 989,000 for 989): read it as 'x1000, scale not on the row', not as "
        "'probably fine'."),
    "pik_printed_not_published": (
        "Printed on the row, not published: 10 of 10 real (MidCap KLO 'SOFR+500 PIK', Ares WorkWave '10.90% PIK', "
        "Crescent 'including 50 PIK', HPS VetCor '14.75% PIK', Sixth Street Volante '16.50% PIK'). Mismatch: 10 of 10 "
        "real by the review's standard: pik_rate holds the all-in coupon (Ares '11.95% (3.50% PIK)' published 11.95, "
        "7 rows) or the spread (Blue Owl Kaseya 6.25, Barings Marmoutier 5.75 for '5.75%, 6.7% PIK'). Member-only "
        "(weaker): mixed, as expected; Goldman Sachs BDC Gainsight 'S + 6.75 PIK' has no printed row to check, "
        "Crescent Lighthouse and iLending print no PIK on the row."),
    "industry_not_published": (
        "10 of 10 are funded rows with no published industry. Carlyle prints 'Construction & Building' on the row; "
        "New Mountain prints the industry cell under each company; HPS prints industry as section headings (the "
        "review's correction). Fillable gaps, not coverage limits. Blackstone Private Real Estate Credit is now "
        "exempt with evidence."),
    "preferred_published_as_common": (
        "9 of 10 real: the filer says preferred or preference and the build publishes common (Ares McLaren 'Senior "
        "preference shares', Blue Owl PCF 'Series A Preferred Units', North Haven Vardiman 'Preferred Equity', AB "
        "venture rows under 'U.S. Preferred Stock'). 1 unclear: AB Avant 'Class A Units' listed under the filer's "
        "'U.S. Preferred Stock' heading (the review's Swyft shape). AB is 101 of the 147 rows. (Read on the "
        "2026-10-18 run. Since 2026-10-19 heading-only rows, 100, all AB, are the weaker kind "
        "preferred_heading_only, so the AB venture rows and Avant leave the findings; 47 remain.)"),
}


# The first measurement (commit 6751318, 2026-10-17, 51 funds), before the 2026-10-18 review fixes
# (D-207): rows, fund-quarters, funds, FV flagged in millions.
OLD_TOTALS = {
    "issuer_name_differs_from_page": (6537, 370, 48, 217529.3),
    "unit_count_differs_from_row_text": (459, 140, 27, 5981.8),
    "pik_printed_not_published": (245, 88, 22, 3271.5),
    "industry_not_published": (4676, 57, 13, 40291.7),
    "preferred_published_as_common": (546, 122, 18, 5861.4),
}
# Findings of the first revision (commit ddc0e92, 2026-10-18, 52 funds), for the rows column.
REV1_ROWS = {
    "issuer_name_differs_from_page": 5759, "unit_count_differs_from_row_text": 416,
    "pik_printed_not_published": 221, "industry_not_published": 4461, "preferred_published_as_common": 147,
}
# The kinds the review (docs/investigations/v05_rule_candidates_falsealarm_2026-10-18.md) and the
# owner (D-207) treat as findings. Everything else a rule emits is weaker evidence, reported apart.
FINDING_KINDS = cr.FINDING_KINDS

# Changelog entries for these changes. Kept here, not in docs/agent_changelog.md, so the branch does not
# collide with other sessions' uncommitted edits to that file (orchestrator, 2026-10-19); append on merge.
CHANGELOG = """\
### 2026-10-17 - Five candidate page rules built and measured, not switched on
- New `pipeline/candidate_rules.py` (issuer name, unit count, PIK, industry coverage, preferred-as-common): DuckDB over published rows joined to the page reader's `printed_row`. Measured on the 51 accepted sandboxes (`docs/investigations/v05_rule_candidates_2026-10-17.md`). 18 tests.

### 2026-10-18 - Candidate page rules revised after the false-alarm review (D-207)
- Rule 1 legal-form tails, blind-quarter suppression and blind-spot table; rule 2 issuer name stripped, printed count passes, `units_scale_unclear`; rule 3 page-only findings, `pik_member_text_only`; rule 4 finding < 0.80, warning < 0.90, Blackstone Private Real Estate Credit exempt with evidence; rule 5 text kinds only. Re-measured on 52 sandboxes; 26 tests.

### 2026-10-19 - Page rules wired into the ledger (D-207, orchestrator under the owner's standing delegation)
- Rule 1 passes a near spelling the fund prints for the same issuer (26North Ascend, Antares Clear Capital) and flags another group entity on the row again (MidCap Wildcat); rule 5 heading-only evidence is the weaker kind `preferred_heading_only`.
- `scripts/shadow_identity_engine.py`: `ensure_page_rules` runs the rules fund by fund over the wrapped cohort into table `page_rule_rows` (one row per tested row); five identity rules `issuer_name_printed`, `units_printed`, `pik_printed`, `industry_coverage`, `preferred_printed` (tier tight) read it, so failures reach the shadow ledger, the review queue (blocker lane) and the findings ledger like spread_printed. A fund-quarter with no tested row gets no result. `scripts/shadow_validation_runner.py` calls it before the identity rules.
- Informational, never in the ledger: `data/output/shadow/page_rules_informational.csv` (weaker kinds, rule-1 flags in untested fund-quarters), `page_rules_name_blind_spots.csv`; finding detail in `page_rule_findings.csv`.
- Tests: test_candidate_rules.py, test_shadow_identity_rules.py (+3 engine tests), test_oracle_checks.py, shadow runner / review-queue tests. No production run; dry run on the v0.5 sandbox: 74 fund-quarters tested per rule, 4,317 / 305 / 114 / 790 / 15 finding rows.
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", type=Path, default=_default_main())
    ap.add_argument("--ciks", default="")
    args = ap.parse_args(argv)
    main_dir: Path = args.main
    registry = json.loads((main_dir / "docs/investigations/v05_readings/accepted_sandboxes.json").read_text(encoding="utf-8"))
    wanted = {c.strip().zfill(10) for c in args.ciks.split(",") if c.strip()}
    flagged, coverage, funds, blind = [], [], [], []
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
            if "blind_spots" in df.attrs:
                spots = df.attrs["blind_spots"].copy()
                spots["fund"] = name
                blind.append(spots)
                df.attrs.clear()
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
    blindf = pd.concat(blind, ignore_index=True)
    blindf.to_csv(docs / f"{STEM}_rule1_blind_spots.csv", index=False)

    write_report(docs / f"{STEM}.md", rows, summ, cov, fundf, main_dir, blindf)
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


def write_report(path: Path, rows, summ, cov, fundf, main_dir: Path, blindf: pd.DataFrame) -> None:
    L = []
    L.append("# v0.5 candidate rules, measured on the accepted sandboxes (2026-10-17, revised 2026-10-18)")
    L.append("")
    L.append("Revision 2026-10-18: the rules were changed after the independent false-alarm review "
             "(`v05_rule_candidates_falsealarm_2026-10-18.md`) and the owner's rulings (D-207): rule 1 passes a name "
             "printed as a name elsewhere in the filing and a trailing legal-form difference, and raises no page flags "
             "in a fund-quarter that is %d pct or more untested (blind-spot table below); rule 2 strips the issuer name, "
             "passes a count printed on the row, and reports exact x1000 cases as `units_scale_unclear`; rule 3 raises "
             "on the printed row only (member text alone is `pik_member_text_only`) and passes a tag rounded to fewer "
             "decimals; rule 4 finds below %.2f, warns below %.2f, and exempts funds whose filings print no industry; "
             "rule 5 keeps the text kinds only. Counts below are this run; the first run's are beside them." % (
                 round(100 * cr.NAME_BLIND_LIMIT), cr.INDUSTRY_COVERAGE_THRESHOLD, cr.INDUSTRY_COVERAGE_WARNING))
    L.append("")
    L.append("Owner, 2026-10-17: \"do it\" -- build the five candidate rules and measure them; do NOT switch them on. "
             "Code: `pipeline/candidate_rules.py` (not imported by the build, ledger, shadow engines, quarter pass or gate). "
             "Script: `scripts/v05_evidence/measure_candidate_rules.py`. Inputs: each fund's accepted sandbox in "
             "`docs/investigations/v05_readings/accepted_sandboxes.json`, published basis (no `underlying_schedule` rows). "
             "Page access: `printed_row` from that sandbox's `bdc_ixbrl_field_status` (current period, member printed once).")
    L.append("")
    L.append("Files: `%s.csv` (rule x fund), `%s_rows.csv` (every flagged row), `%s_industry_coverage.csv` (rule 4, "
             "with level), `%s_rule1_blind_spots.csv` (rule 1, per fund-quarter)." % (STEM, STEM, STEM, STEM))
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
    L.append("Findings are the kinds the review and D-207 treat as errors (`candidate_rules.FINDING_KINDS`); weaker kinds "
             "(`units_scale_unclear`, `pik_member_text_only`, `preferred_heading_only`) are counted apart. Old = commit "
             "6751318 (51 funds, all kinds then emitted); 10-18 = commit ddc0e92 (first revision, 52 funds); new = this run "
             "(2026-10-19 follow-ups: rule 1 near-spelling pass, rule 5 heading-only to the weaker kind). Not counted here: "
             "the ledger also leaves out rule-1 shape flags in untested fund-quarters (`ledger_rows`).")
    L.append("")
    L.append("| rule | old rows | 10-18 rows | new rows (findings) | weaker kinds | old FQ | new FQ | old funds | new funds | old FV (M) | new FV (M) | kinds |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    rng = random.Random(SEED)
    for rule in cr.RULES:
        g = rows[rows["rule"] == rule]
        keep = FINDING_KINDS[rule]
        f = g if keep is None else g[g["kind"].isin(keep)]
        weak = len(g) - len(f)
        fq = f[["cik", "report_date"]].drop_duplicates().shape[0]
        kinds = "; ".join("%s:%d" % (k, v) for k, v in g["kind"].value_counts().items())
        o = OLD_TOTALS[rule]
        L.append("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %.1f | %.1f | %s |" % (
            rule, o[0], REV1_ROWS[rule], len(f), weak, o[1], fq, o[2], f["cik"].nunique(), o[3],
            f["fair_value"].fillna(0).sum() / 1e6, kinds))
    L.append("")
    for rule in cr.RULES:
        g = rows[rows["rule"] == rule]
        L.append("## %s" % rule)
        L.append("")
        L.append("**Overlap with existing rules.** " + OVERLAP[rule])
        L.append("")
        if rule == "industry_not_published":
            _industry_section(L, cov)
        if rule == "issuer_name_differs_from_page":
            _blind_section(L, blindf)
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
                      (" (kind pik_value_mismatch, reported separately)", g[g["kind"] == "pik_value_mismatch"]),
                      (" (weaker kind pik_member_text_only)", g[g["kind"] == "pik_member_text_only"])]
        if rule == "preferred_published_as_common":
            groups = [(" (finding kinds)", g[g["kind"] != "preferred_heading_only"]),
                      (" (weaker kind preferred_heading_only)", g[g["kind"] == "preferred_heading_only"])]
        if rule == "unit_count_differs_from_row_text":
            groups = [(" (finding kinds)", g[g["kind"] != "units_scale_unclear"]),
                      (" (weaker kind units_scale_unclear)", g[g["kind"] == "units_scale_unclear"])]
        if rule in READS:
            L.append("**Read of the samples below (agent; not a disposition).** " + READS[rule])
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
    L.append("## Ledger wiring (2026-10-19)")
    L.append("")
    L.append("The five rules now produce findings through the shadow identity engine (`scripts/shadow_identity_engine.py`, "
             "`ensure_page_rules`), ledger names: " + ", ".join("`%s` (%s)" % (cr.LEDGER_NAMES[r], r) for r in cr.RULES) +
             ". Only these finding kinds raise: " + "; ".join(
                 "%s: %s" % (cr.LEDGER_NAMES[r], ", ".join(sorted(k))) for r, k in cr.FINDING_KINDS.items()) +
             ". Weaker kinds and rule 1's blind-spot table go to `data/output/shadow/page_rules_informational.csv` and "
             "`page_rules_name_blind_spots.csv`; a fund-quarter with no tested row gets no ledger result.")
    L.append("")
    L.append("## Changelog entries (to append to docs/agent_changelog.md on merge)")
    L.append("")
    L.append(CHANGELOG)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _blind_section(L, b: pd.DataFrame) -> None:
    rows, nb = int(b["n_rows"].sum()), int((b["n_no_printed_row"] + b["n_no_name_cell"]).sum())
    sup = b[b["page_test_suppressed"]]
    L.append("**Blind spots (part of the rule's result).** Of %d published rows with an issuer name, %d (%.1f pct) "
             "could not be tested on the page (%d with no printed row, %d with a printed row but no name cell). "
             "%d fund-quarters are %d pct or more untested and raise no page-basis flags (shape flags still run). "
             "A clean rule-1 result there means 'not looked at'. Funds with the most untested fund-quarters:" % (
                 rows, nb, 100.0 * nb / max(rows, 1), int(b["n_no_printed_row"].sum()), int(b["n_no_name_cell"].sum()),
                 len(sup), round(100 * cr.NAME_BLIND_LIMIT)))
    L.append("")
    g = b.groupby(["cik", "fund"]).agg(fq=("report_date", "count"), suppressed=("page_test_suppressed", "sum"),
                                       rows=("n_rows", "sum"), blind_rows=("n_no_name_cell", "sum"),
                                       no_row=("n_no_printed_row", "sum")).reset_index()
    g["blind_share"] = (g["blind_rows"] + g["no_row"]) / g["rows"]
    L.append("| cik | fund | fund-quarters | suppressed | blind share (rows) |")
    L.append("|---|---|---:|---:|---:|")
    for r in g.sort_values(["suppressed", "blind_share"], ascending=False).head(15).itertuples():
        L.append("| %s | %s | %d | %d | %.2f |" % (r.cik, _fmt(r.fund, 45), r.fq, r.suppressed, r.blind_share))
    L.append("")


def _industry_section(L, cov: pd.DataFrame) -> None:
    lv = cov["level"].value_counts().to_dict()
    L.append("Levels (D-207: finding below %.2f, warning below %.2f): %s." % (
        cr.INDUSTRY_COVERAGE_THRESHOLD, cr.INDUSTRY_COVERAGE_WARNING,
        ", ".join("%s %d" % (k, lv.get(k, 0)) for k in ("finding", "warning", "ok", "too_few_rows", "exempt"))))
    L.append("")
    for cik, ex in cr.INDUSTRY_EXEMPTIONS.items():
        L.append("Exempt: %s %s (checked %s). Evidence: %s" % (cik, ex["fund"], ex["checked_on"], ex["evidence"]))
        L.append("")
    w = cov[cov["level"] == "warning"].sort_values("gics_coverage")
    if not w.empty:
        L.append("Warning fund-quarters (no rows raised): " + "; ".join(
            "%s %s %.3f" % (_fmt(r.fund, 30), r.report_date, r.gics_coverage) for r in w.itertuples()) + ".")
        L.append("")
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
             "flagged rows below: %.2f (owner ruling D-207). The distribution includes exempt funds." % (
                 q[0.05], q[0.1], q[0.25], q[0.5], cr.INDUSTRY_COVERAGE_THRESHOLD))
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
