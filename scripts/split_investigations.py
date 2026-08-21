"""Split data_investigation_results.md into topical docs under docs/investigations/.

DERIVED-VIEW GENERATOR (pre-cutover design): the single source of truth remains
data/output/data_investigation_results.md until the owner ratifies the AGENTS.md
convention change. This script deterministically regenerates the topic files from
the source on every run, so concurrent appends to the source file by other agents
are harmless -- just re-run. After cutover, this script becomes the one-time
migrator and the topic files become canonical/appendable.

Mapping is by EXACT heading text (line numbers shift in an append-only file).
Headings not in the map go to uncategorized.md and are counted loudly -- an entry
can never be silently dropped. Verification: entries in == entries out, and body
line counts are preserved per entry.

Usage:
  python scripts/split_investigations.py
  python scripts/split_investigations.py --check   # verify only, write nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data" / "output" / "data_investigation_results.md"
OUT_DIR = REPO_ROOT / "docs" / "investigations"

TOPICS = {
    "classification_holdings_eda.md": "Holdings classification & EDA",
    "frontend_data_checks.md": "Frontend / public data checks",
    "data_quality_audits.md": "Data-quality audits & triage",
    "source_reconciliation.md": "Source reconciliation & blocker chains",
    "wrapper_residuals.md": "Per-CIK wrapper residual reviews",
    "conservation_shadow_engine.md": "Conservation / shadow-panel engine",
    "identifier_rate_semantics.md": "Identifier & rate semantics (Agent A)",
    "agent_campaigns.md": "Agentic campaign retrospectives",
    "quarter_eda.md": "Quarter-over-quarter EDA",
    "uncategorized.md": "Uncategorized (needs mapping)",
}

# Exact heading text (without the leading '## ') -> topic file.
HEADING_MAP = {
    "1. Position Classification Stability Across Quarters (2026-04-07)": "classification_holdings_eda.md",
    "2. Firm-Level Exposure Breakdown (2026-04-08)": "classification_holdings_eda.md",
    "5. BDCs with Holdings but Missing from Unified (2026-05-04)": "classification_holdings_eda.md",
    "2026-06-16 - Derivative universe characterization + hedge-vs-portfolio base rates": "classification_holdings_eda.md",
    "iXBRL capture of instrument type (revolver / DDTL / term loan), like lien (2026-06-17)": "classification_holdings_eda.md",
    "2026-06-17 - iXBRL field-status overlay was joining on the WRONG key; fix recovers lien/maturity": "classification_holdings_eda.md",
    "Per-position instrument-type XBRL reconciliation: measured ~0 lift (2026-06-17)": "classification_holdings_eda.md",

    "2026-05-17: BDC Credit Stress Chart Validation": "frontend_data_checks.md",
    "Blackstone Private Credit Fund return chart drop - 2026-05-17": "frontend_data_checks.md",
    "2026-05-24 - Frontend Fund and Position Data Source Spot Check": "frontend_data_checks.md",

    "Fund financials schema flags audit - 2026-05-17": "data_quality_audits.md",
    "Validation warning triage - 2026-05-17": "data_quality_audits.md",
    "Non-accrual reconciliation - 2025q4": "data_quality_audits.md",
    "Data quality root-cause audit - 2026-05-18": "data_quality_audits.md",
    "Universe gating residuals - 2026-05-18": "data_quality_audits.md",
    "2026-06-15 - bdc_fund_highlights balance-sheet fields broadly unreliable": "data_quality_audits.md",

    "BDC source reconciliation blockers - 2026-05-19": "source_reconciliation.md",
    "BDC source-only blocker classification - 2026-05-20": "source_reconciliation.md",
    "BDC source-only percentage hierarchy split - 2026-05-20": "source_reconciliation.md",
    "Crescent hierarchy percentage leaf parser repair - 2026-05-20": "source_reconciliation.md",
    "Aggregate leak suspect spot-check review - 2026-05-21": "source_reconciliation.md",
    "BDC source-blocker manual review progress - 2026-05-27": "source_reconciliation.md",
    "2026-05-27 - MSD Investment Corp. Source-Reconciliation Blocker": "source_reconciliation.md",
    "2026-06-17 - JV look-through double-count: BCRED Emerald JV ($6.5B), surfaced via gold-set labeling": "source_reconciliation.md",
    # The 2026-07-21/22 parts 1-8 chain is kept WHOLE here: parts 1-2 measure
    # rule quality on the same blocker pool parts 3-8 diagnose; splitting a
    # numbered chain across files would orphan the numbering.
    "2026-07-21 - Do high-FP review rules catch real errors no other rule catches? (unique-catch analysis)": "source_reconciliation.md",
    "2026-07-21 (part 2) - Row-level unique-catch analysis: high-FP rules DO catch unique row-level errors": "source_reconciliation.md",
    "2026-07-21 (part 3) - Disposition-trace diagnosis of source-only blocking rows: the parser loses NOTHING; drops are aggregate-filter and promoted-rule effects": "source_reconciliation.md",
    "2026-07-21 (part 4) - Row-level verification of Wave-1 promoted exclusions against the E1 blockers": "source_reconciliation.md",
    "2026-07-21 (part 5) - Phase-2 semantics adjudication of the five verified promoted-exclusion rules (printed-SOI evidence)": "source_reconciliation.md",
    "2026-07-22 (part 6) - Two evidence-class excusal mechanisms added to the source-only classifier; blocking pool 2,305 -> 2,065": "source_reconciliation.md",
    "2026-07-22 (part 7) - Attribution of the rule-unexplained E1 drops (Ares $14.8B solved)": "source_reconciliation.md",
    "2026-07-22 (part 8) - Global JV-axis staging drop REJECTED by evidence; the pipeline already has a retain-and-flag design the conservation engine ignores": "source_reconciliation.md",

    "2026-06-04 - Golub bare-name 2024-06-30 wrapper residuals": "wrapper_residuals.md",
    "2026-06-04 - Oaktree wrapper comparison against cached HTML": "wrapper_residuals.md",
    "2026-06-05 - North Haven wrapper comparison against cached HTML": "wrapper_residuals.md",
    "2026-06-05 - Monroe wrapper economic-reality residual review": "wrapper_residuals.md",
    "2026-06-05 - Ares Core Infrastructure cached HTML wrapper check": "wrapper_residuals.md",
    "2026-06-05 - Barings Private Credit wrapper residual closeout": "wrapper_residuals.md",
    "2026-06-05 - MidCap Financial wrapper residual closeout": "wrapper_residuals.md",

    "2026-06-15 - Top overshoot 0001851322 2025-12-31 = duplicate filing (10-K + 10-K/A)": "conservation_shadow_engine.md",
    "2026-06-15 - Shadow-gate overshoot bucket: concentrated in ~5 funds, not 204": "conservation_shadow_engine.md",
    "2026-06-15 - Dominant-fund overshoot diagnosis: issuer-subtotal duplication in UNWRAPPED CIKs": "conservation_shadow_engine.md",
    "2026-06-16 - Shadow-panel adapter assessment: false positives in conservation engine + fund_financials MODERATE": "conservation_shadow_engine.md",
    "2026-06-16 - Shadow panel: complete surfaced-category assessment (all 6,441 surfaced flags)": "conservation_shadow_engine.md",
    "2026-06-16 - Re-anchoring the conservation engine: explored, not worth it (retirement validated)": "conservation_shadow_engine.md",
    "2026-06-16 - cost_conservation is WORSE than fv_conservation (do not keep cost-only)": "conservation_shadow_engine.md",
    "2026-06-16 - CORRECTION: a fund-level reported cost DOES exist (companyfacts InvestmentOwnedAtCost)": "conservation_shadow_engine.md",
    "2026-06-16 - \"15 leaked category headers\" RESOLVED: MidCap flattened-identifier issuer mis-parse (not subtotal leaks)": "conservation_shadow_engine.md",
    "2026-06-16 - Strong-anchor blind-spot profile: broad, skews pre-XBRL/N-PORT; published cohort 25.7%": "conservation_shadow_engine.md",
    "2026-06-16 - BDC cross-target anchor coverage: CUSIP zero, N-PORT issuer coupled to paused entity resolution": "conservation_shadow_engine.md",

    "2026-06-19 - Structured-XBRL-twin coverage for freeform investment_identifier (Agent A anchor budget)": "identifier_rate_semantics.md",
    "2026-06-19 - Format-signature (cik, shape) clustering probe: TWO REGIMES, naive mask is regime-dependent": "identifier_rate_semantics.md",
    "2026-06-20 - Why text-spread disagrees with the XBRL basis_spread tag (Agent A gold conflicts)": "identifier_rate_semantics.md",
    "2026-06-20 - CORRECTION to the above: all-in reconciliation REVERSES it (tag, not text)": "identifier_rate_semantics.md",
    "2026-06-21 - Twin (structured) vs identifier (text) disagreements: who is right, and where to resolve": "identifier_rate_semantics.md",
    "2026-06-23 - Why the 8 Agent A \"completeness\" FAILs fail: 0% encoding, ~84% regex/sampling, ~16% scope-out": "identifier_rate_semantics.md",
    "2026-07-20 - XBRL linkbase-layer evidence: rate-concept fingerprints, presentation labels, calc arcs, domain-default anchors": "identifier_rate_semantics.md",

    "2026-07-07 - Per-fingerprint stratification retrospective re-cut of ens2 B1 adjudications": "agent_campaigns.md",
    "2026-08-20 - B2 correction-agent Q4 2025 track record: cross-batch metrics rollup + round-4 fleet acceptance criteria": "agent_campaigns.md",

    "2026-07-24 - Why Q1 2026 has fewer facts than Q4 2025 (quarter-over-quarter EDA)": "quarter_eda.md",
    "2026-07-24 (part 2) - Per-fact shadow rule-firing comparison, Q4 2025 vs Q1 2026": "quarter_eda.md",
}

GENERATED_HEADER = """<!-- GENERATED by scripts/split_investigations.py -- DERIVED VIEW, do not edit or append here.
     Canonical source (pre-cutover): data/output/data_investigation_results.md
     Re-run the script after the source changes. This banner is removed at the
     AGENTS.md cutover, when these files become canonical and appendable. -->
"""


def parse_entries(text: str):
    """Return (preamble_lines, [(heading, body_lines)]) in source order."""
    lines = text.splitlines()
    preamble, entries = [], []
    current = None
    for ln in lines:
        if ln.startswith("## "):
            current = (ln[3:].strip(), [])
            entries.append(current)
        elif current is None:
            preamble.append(ln)
        else:
            current[1].append(ln)
    return preamble, entries


def write_index(buckets) -> None:
    index_lines = [
        "# Data Investigations Index",
        "",
        "GENERATED -- do not edit by hand. Rebuild: python scripts/split_investigations.py --reindex",
        "",
    ]
    for fname, title in TOPICS.items():
        items = buckets.get(fname) or []
        if not items:
            continue
        index_lines.append(f"## {title} ([{fname}]({fname}))")
        index_lines.extend(f"- {heading}" for heading, _ in items)
        index_lines.append("")
    (OUT_DIR / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def reindex() -> int:
    """Rebuild INDEX.md from the topic files themselves (post-cutover mode,
    when docs/investigations/*.md are canonical and the source file is frozen)."""
    buckets = {}
    for fname in TOPICS:
        p = OUT_DIR / fname
        if not p.exists():
            continue
        _, entries = parse_entries(p.read_text(encoding="utf-8"))
        buckets[fname] = entries
        print(f"[split] reindex {fname}: {len(entries)} entries")
    write_index(buckets)
    print("[split] INDEX.md rebuilt from topic files")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify mapping only; write nothing")
    ap.add_argument("--reindex", action="store_true",
                    help="rebuild INDEX.md from the topic files (post-cutover mode)")
    args = ap.parse_args(argv)

    if args.reindex:
        return reindex()

    text = SOURCE.read_text(encoding="utf-8")
    if "CUTOVER-COMPLETE" in text:
        # Post-cutover the topic files are canonical and may hold entries that
        # exist nowhere else; regenerating from the frozen stub (or the archive)
        # would destroy them. Only --reindex remains valid.
        print("[split] CUTOVER COMPLETE: the source file is a frozen stub and the")
        print("[split] topic files under docs/investigations/ are canonical.")
        print("[split] Regenerate mode is disabled; use --reindex to rebuild INDEX.md.")
        return 1
    preamble, entries = parse_entries(text)
    print(f"[split] source entries: {len(entries)}")

    buckets = {fname: [] for fname in TOPICS}
    unmapped = []
    for heading, body in entries:
        fname = HEADING_MAP.get(heading)
        if fname is None:
            unmapped.append(heading)
            fname = "uncategorized.md"
        buckets[fname].append((heading, body))

    for h in unmapped:
        print(f"[split] WARNING unmapped heading -> uncategorized.md: {h[:100]}")

    n_out = sum(len(v) for v in buckets.values())
    body_in = sum(len(b) for _, b in entries)
    body_out = sum(len(b) for v in buckets.values() for _, b in v)
    ok = (n_out == len(entries)) and (body_in == body_out)
    print(f"[split] entries out: {n_out} (match={n_out == len(entries)}), "
          f"body lines {body_in} -> {body_out} (match={body_in == body_out})")
    if not ok:
        print("[split] FATAL: verification failed; nothing written")
        return 1
    if args.check:
        print("[split] --check: verification passed, nothing written")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for fname, title in TOPICS.items():
        items = buckets[fname]
        if not items:
            # remove stale topic file if a re-run emptied it
            stale = OUT_DIR / fname
            if stale.exists():
                stale.unlink()
            continue
        out_lines = [GENERATED_HEADER, f"# {title}", ""]
        for heading, body in items:
            out_lines.append(f"## {heading}")
            out_lines.extend(body)
        (OUT_DIR / fname).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"[split] wrote {fname}: {len(items)} entries")

    write_index(buckets)
    print(f"[split] wrote INDEX.md; done -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
