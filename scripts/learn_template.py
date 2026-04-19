"""Runner script for per-CIK HTML template creation.

Lists CIKs needing templates, downloads HTML filings, provides validation
utilities. Designed to be run by Claude Code instances following the prompt
in scripts/learn_template_prompt.md.

Usage:
    # List CIKs needing templates
    python scripts/learn_template.py --list

    # Prepare data for a specific CIK (download HTML if needed)
    python scripts/learn_template.py --prepare 1287750

    # Validate a template against XBRL ground truth
    python scripts/learn_template.py --validate 1287750

    # Show progress summary
    python scripts/learn_template.py --progress
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_HTML_CACHE_DIR,
    HTML_TEMPLATE_DIR,
    OUTPUT_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TEMPLATE_PROGRESS_FILE = OUTPUT_DIR / "template_progress.csv"
TEMPLATE_CLAIMS_FILE = OUTPUT_DIR / "template_claims.json"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_filings_index() -> pd.DataFrame:
    return pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)


def _load_bdc_holdings() -> pd.DataFrame:
    return pd.read_csv(
        OUTPUT_DIR / "bdc_holdings.csv",
        dtype={"cik": str},
        usecols=[
            "cik", "entity_name", "accession_number", "form_type",
            "report_date", "period", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "shares_held", "pik_rate",
        ],
    )


# ---------------------------------------------------------------------------
# List CIKs needing templates
# ---------------------------------------------------------------------------

def list_ciks():
    """Print CIKs that need templates, sorted by filing count."""
    idx = _load_filings_index()
    html_filings = idx[idx["xbrl_download_status"] == "not_found"]

    # Check existing templates
    existing = {f.stem for f in HTML_TEMPLATE_DIR.glob("*.json")}

    # Group by CIK
    grouped = html_filings.groupby("cik").agg(
        entity_name=("entity_name", "first"),
        n_filings=("accession_number", "count"),
        min_date=("filing_date", "min"),
        max_date=("filing_date", "max"),
    ).reset_index()

    # Check which have XBRL ground truth
    try:
        bdc = pd.read_csv(
            OUTPUT_DIR / "bdc_holdings.csv",
            usecols=["cik"], dtype=str,
        )
        xbrl_ciks = set(bdc["cik"].str.lstrip("0"))
    except FileNotFoundError:
        xbrl_ciks = set()

    # Check which have cached HTML
    cached_ciks = set()
    if BDC_HTML_CACHE_DIR.exists():
        for d in BDC_HTML_CACHE_DIR.iterdir():
            if d.is_dir() and list(d.glob("*.html")):
                cached_ciks.add(d.name)

    grouped["cik_stripped"] = grouped["cik"].str.lstrip("0")
    grouped["has_template"] = grouped["cik_stripped"].isin(existing)
    grouped["has_xbrl"] = grouped["cik_stripped"].isin(xbrl_ciks)
    grouped["has_html_cached"] = grouped["cik_stripped"].isin(cached_ciks)

    # Split into done vs needed
    done = grouped[grouped["has_template"]]
    needed = grouped[~grouped["has_template"]].sort_values(
        "n_filings", ascending=False,
    )

    print(f"\n{'='*70}")
    print(f"Template Progress: {len(done)}/{len(grouped)} CIKs complete")
    print(f"{'='*70}")

    if not needed.empty:
        # Prioritize: has XBRL ground truth first, then by filing count
        needed = needed.sort_values(
            ["has_xbrl", "n_filings"], ascending=[False, False],
        )
        print(f"\nCIKs needing templates ({len(needed)}):")
        print(f"{'CIK':>10}  {'Name':<40}  {'Filings':>7}  {'Dates':<23}  {'XBRL':>4}  {'HTML':>4}")
        print("-" * 100)
        for _, row in needed.iterrows():
            cik = row["cik_stripped"]
            name = (row["entity_name"] or "")[:40]
            xbrl = "Y" if row["has_xbrl"] else ""
            html = "Y" if row["has_html_cached"] else ""
            print(
                f"{cik:>10}  {name:<40}  {row['n_filings']:>7}  "
                f"{row['min_date']} - {row['max_date']}  {xbrl:>4}  {html:>4}"
            )

    if not done.empty:
        print(f"\nCompleted ({len(done)}):")
        for _, row in done.iterrows():
            print(f"  {row['cik_stripped']:>10}  {(row['entity_name'] or '')[:50]}")


# ---------------------------------------------------------------------------
# Prepare HTML data for a CIK
# ---------------------------------------------------------------------------

def _count_logical_columns(html_path: Path) -> int | None:
    """Count non-empty header columns in the primary schedule table.

    Returns None if the file can't be parsed or no schedule found.
    """
    try:
        from pipeline.html_holdings import find_schedule_tables
    except ImportError:
        return None
    try:
        html = html_path.read_text(encoding="utf-8", errors="replace")
        tables = find_schedule_tables(html)
        if not tables:
            return None
        header = tables[0].rows[tables[0].header_row_idx]
        return sum(1 for c in header if c.strip())
    except Exception:
        return None


def prepare_cik(cik: str):
    """Download ALL pre-XBRL HTML filings for a CIK and scan for format changes.

    Downloads every filing, counts logical columns in each, and reports
    format boundaries so the instance knows exactly how many template
    variants are needed and which filings represent each format era.
    """
    cik_stripped = cik.lstrip("0")
    idx = _load_filings_index()

    # Get pre-XBRL filings for this CIK
    cik_filings = idx[
        (idx["cik"].str.lstrip("0") == cik_stripped)
        & (idx["xbrl_download_status"] == "not_found")
    ].sort_values("filing_date")

    if cik_filings.empty:
        print(f"No pre-XBRL filings found for CIK {cik_stripped}")
        return

    entity_name = cik_filings.iloc[0]["entity_name"]
    print(f"\nCIK {cik_stripped}: {entity_name}")
    print(f"  Pre-XBRL filings: {len(cik_filings)}")
    print(f"  Date range: {cik_filings['filing_date'].min()} "
          f"to {cik_filings['filing_date'].max()}")

    # ------------------------------------------------------------------
    # Phase 1: Download ALL filings
    # ------------------------------------------------------------------
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    to_download = []
    already_cached = 0
    for _, filing in cik_filings.iterrows():
        acc_nodashes = filing["accession_number"].replace("-", "")
        cache_file = cache_dir / f"{acc_nodashes}.html"
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            already_cached += 1
        else:
            to_download.append(filing)

    print(f"\n  Cached: {already_cached}/{len(cik_filings)}, "
          f"to download: {len(to_download)}")

    if to_download:
        from pipeline.edgar_client import EdgarClient
        from pipeline.html_holdings import download_html_filing
        client = EdgarClient()
        ok, fail = 0, 0
        for filing in to_download:
            primary_doc = filing.get("primary_document", "")
            result = download_html_filing(
                client, cik_stripped,
                filing["accession_number"], primary_doc,
            )
            if result:
                ok += 1
            else:
                fail += 1
        print(f"  Downloaded: {ok}, failed: {fail}")

    # ------------------------------------------------------------------
    # Phase 2: Scan ALL filings for column counts (format detection)
    # ------------------------------------------------------------------
    print(f"\n  Format scan (all filings):")
    print(f"  {'Date':<12} {'Form':<8} {'Cols':>4}  Accession")
    print(f"  {'-'*55}")

    scan_results = []  # (filing_date, form_type, n_cols, accession)
    for _, filing in cik_filings.iterrows():
        acc_nodashes = filing["accession_number"].replace("-", "")
        cache_file = cache_dir / f"{acc_nodashes}.html"
        n_cols = _count_logical_columns(cache_file) if cache_file.exists() else None
        scan_results.append((
            filing["filing_date"], filing["form_type"],
            n_cols, filing["accession_number"],
        ))
        cols_str = str(n_cols) if n_cols is not None else "?"
        print(f"  {filing['filing_date']:<12} {filing['form_type']:<8} "
              f"{cols_str:>4}  {filing['accession_number']}")

    # ------------------------------------------------------------------
    # Phase 3: Detect format boundaries
    # ------------------------------------------------------------------
    # Filter out unparseable filings (0, 1, None) -- amendments and
    # anomalies with no real schedule table.
    col_counts = [(r[0], r[1], r[2], r[3]) for r in scan_results
                  if r[2] is not None and r[2] >= 2]
    skipped = len(scan_results) - len(col_counts)
    if skipped:
        print(f"\n  ({skipped} filings skipped -- no schedule table found, "
              f"likely amendments)")

    if col_counts:
        distinct_counts = sorted(set(c[2] for c in col_counts))
        if len(distinct_counts) == 1:
            print(f"\n  FORMAT: Single format ({distinct_counts[0]} columns "
                  f"across all {len(col_counts)} filings)")
            print(f"  -> Use v1.0 template (single format)")
            print(f"  -> Examine earliest + latest filing for the template")
        else:
            print(f"\n  FORMAT CHANGES DETECTED: {len(distinct_counts)} "
                  f"distinct column counts: {distinct_counts}")

            # Group filings into eras (consecutive runs of same col count)
            eras = []  # (start_date, end_date, cols, count, first_acc)
            current_cols = col_counts[0][2]
            era_start = col_counts[0][0]
            era_first_acc = col_counts[0][3]
            era_count = 0
            prev_date = col_counts[0][0]
            for date, form, cols, acc in col_counts:
                if cols != current_cols:
                    eras.append((era_start, prev_date, current_cols,
                                 era_count, era_first_acc))
                    current_cols = cols
                    era_start = date
                    era_first_acc = acc
                    era_count = 0
                era_count += 1
                prev_date = date
            eras.append((era_start, prev_date, current_cols,
                         era_count, era_first_acc))

            # Merge single-filing blips back into surrounding era
            # (one-off column count differences are noise, not real formats)
            merged = []
            for era in eras:
                if era[3] == 1 and merged and len(eras) > 2:
                    # Single-filing blip -- skip it (noise)
                    continue
                if (merged and merged[-1][2] == era[2]):
                    # Same col count as previous era -- merge
                    merged[-1] = (merged[-1][0], era[1], era[2],
                                  merged[-1][3] + era[3], merged[-1][4])
                else:
                    merged.append(era)
            eras = merged

            # Recount distinct after merging
            distinct_counts = sorted(set(e[2] for e in eras))
            n_variants = len(distinct_counts)

            print(f"\n  Format eras ({n_variants} variants):")
            for start, end, cols, count, first_acc in eras:
                print(f"    {start} to {end}: "
                      f"{cols} cols ({count} filings)  "
                      f"sample: {first_acc}")

            if n_variants == 1:
                print(f"\n  -> Use v1.0 template (single format after "
                      f"merging one-off blips)")
                print(f"  -> Examine earliest + latest filing")
            else:
                print(f"\n  -> Use v2.0 multi-variant template "
                      f"({n_variants} variants)")
                print(f"  -> Examine the 'sample' filing from EACH era")
                print(f"  -> See data/raw/filing_templates/1396440.json "
                      f"(Main Street Capital, 3 variants) as a model")

    # ------------------------------------------------------------------
    # Phase 4: XBRL ground truth
    # ------------------------------------------------------------------
    try:
        bdc = pd.read_csv(
            OUTPUT_DIR / "bdc_holdings.csv",
            dtype={"cik": str},
            usecols=["cik", "report_date", "fair_value"],
        )
        xbrl = bdc[bdc["cik"].str.lstrip("0") == cik_stripped]
        if not xbrl.empty:
            dates = sorted(xbrl["report_date"].unique())
            print(f"\n  XBRL ground truth available:")
            print(f"    Periods: {len(dates)} ({dates[0]} to {dates[-1]})")
            for dt in dates[-4:]:
                n = len(xbrl[xbrl["report_date"] == dt])
                fv_sum = pd.to_numeric(
                    xbrl[xbrl["report_date"] == dt]["fair_value"],
                    errors="coerce",
                ).sum()
                print(f"    {dt}: {n} holdings, FV=${fv_sum/1e6:,.0f}M")
        else:
            print(f"\n  No XBRL ground truth (pre-XBRL only CIK)")
    except FileNotFoundError:
        print(f"\n  bdc_holdings.csv not found")


# ---------------------------------------------------------------------------
# Validate a template
# ---------------------------------------------------------------------------

def validate_template(cik: str):
    """Validate a template against XBRL ground truth and extraction results."""
    cik_stripped = cik.lstrip("0")
    template_file = HTML_TEMPLATE_DIR / f"{cik_stripped}.json"

    if not template_file.exists():
        print(f"No template found for CIK {cik_stripped}")
        return

    with open(template_file) as f:
        template = json.load(f)

    print(f"\nTemplate for CIK {cik_stripped}:")
    print(f"  Entity: {template.get('entity_name', 'N/A')}")
    print(f"  Schema version: {template.get('schema_version', 'N/A')}")

    # Show variant info for v2.0 templates
    variants = template.get("variants", [])
    if variants:
        print(f"  Variants: {len(variants)}")
        for v in variants:
            fmt_id = v.get("format_id", "?")
            desc = v.get("description", "")[:60]
            cc = v.get("programmatic_analysis", {}).get("column_count", "?")
            print(f"    - {fmt_id} ({cc} cols): {desc}")

    # Check column mapping (use first variant for v2.0, or top-level for v1.0)
    if variants:
        col_map = variants[0].get("column_mapping", {})
    else:
        col_map = template.get("column_mapping", {})
    mapped = {k: v for k, v in col_map.items()
              if isinstance(v, dict) and v.get("index") is not None}
    print(f"  Mapped columns (primary variant): {list(mapped.keys())}")

    # Check value formats
    vf = template.get("value_formats", {})
    print(f"  Dollar unit: {vf.get('dollar_unit', 'N/A')}")
    print(f"  Date format: {vf.get('date_format', 'N/A')}")
    print(f"  Rate format: {vf.get('rate_format', 'N/A')}")

    # Try extraction on cached HTML
    from pipeline.html_template import extract_filing_with_template
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    if not cache_dir.exists():
        print(f"\n  No cached HTML to test extraction")
        return

    html_files = sorted(cache_dir.glob("*.html"))
    if not html_files:
        print(f"\n  No cached HTML to test extraction")
        return

    idx = _load_filings_index()
    for html_file in html_files:
        print(f"\n  Testing: {html_file.name}")
        html = html_file.read_text(encoding="utf-8", errors="replace")

        # Find filing metadata
        acc_nodashes = html_file.stem
        filing_row = idx[
            idx["accession_number"].str.replace("-", "") == acc_nodashes
        ]
        if filing_row.empty:
            filing_meta = {
                "cik": cik_stripped,
                "entity_name": template.get("entity_name", ""),
                "accession_number": acc_nodashes,
                "form_type": "10-K",
                "filing_date": "2024-01-01",
                "report_date": "2023-12-31",
            }
        else:
            row = filing_row.iloc[0]
            filing_meta = {
                "cik": cik_stripped,
                "entity_name": row.get("entity_name", ""),
                "accession_number": row.get("accession_number", acc_nodashes),
                "form_type": row.get("form_type", "10-K"),
                "filing_date": row.get("filing_date", ""),
                "report_date": row.get("report_date", ""),
            }

        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )

        variant_id = stats.get("variant_id")
        variant_str = f" (variant: {variant_id})" if variant_id else ""
        print(f"    Holdings: {len(holdings)}{variant_str}")
        print(f"    Drift: {stats['drift_detected']}")
        print(f"    Data rows: {stats['data_rows_found']}")

        if holdings:
            fv_vals = [h["fair_value"] for h in holdings
                       if h.get("fair_value") is not None]
            rate_vals = [h["interest_rate"] for h in holdings
                         if h.get("interest_rate") is not None]
            cost_vals = [h["cost"] for h in holdings
                         if h.get("cost") is not None]
            mat_vals = [h["maturity_date"] for h in holdings
                        if h.get("maturity_date")]
            name_vals = [h["investment_identifier"] for h in holdings
                         if h.get("investment_identifier")]

            total_fv = sum(fv_vals) if fv_vals else 0
            print(f"    FV: {len(fv_vals)}/{len(holdings)} non-null, "
                  f"sum=${total_fv/1e6:,.0f}M")
            print(f"    Rate: {len(rate_vals)}/{len(holdings)} non-null "
                  f"({len(rate_vals)/len(holdings)*100:.0f}%)")
            print(f"    Cost: {len(cost_vals)}/{len(holdings)} non-null "
                  f"({len(cost_vals)/len(holdings)*100:.0f}%)")
            print(f"    Maturity: {len(mat_vals)}/{len(holdings)} non-null "
                  f"({len(mat_vals)/len(holdings)*100:.0f}%)")
            print(f"    Names: {len(name_vals)}/{len(holdings)} non-null "
                  f"({len(name_vals)/len(holdings)*100:.0f}%)")

            # Show first 3 holdings
            print(f"    Sample:")
            for h in holdings[:3]:
                inv = (h.get("investment_identifier") or "")[:45].encode("ascii", "replace").decode("ascii")
                fv = h.get("fair_value")
                fv_s = f"${fv:>12,.0f}" if fv is not None else "        None"
                rate = h.get("interest_rate")
                rate_s = f"{rate:.1f}%" if rate is not None else "None"
                print(f"      {inv:<45} FV={fv_s}  Rate={rate_s}")

    # Compare against XBRL ground truth
    try:
        bdc = _load_bdc_holdings()
        xbrl = bdc[bdc["cik"].str.lstrip("0") == cik_stripped]
        if not xbrl.empty:
            print(f"\n  XBRL comparison:")
            # Get most recent period
            latest_period = xbrl[
                xbrl["period"] == xbrl["report_date"]
            ]["report_date"].max()
            if pd.notna(latest_period):
                xbrl_latest = xbrl[
                    (xbrl["report_date"] == latest_period)
                    & (xbrl["period"] == latest_period)
                ]
                xbrl_fv = pd.to_numeric(
                    xbrl_latest["fair_value"], errors="coerce"
                )
                print(f"    Latest XBRL period: {latest_period}")
                print(f"    XBRL holdings: {len(xbrl_latest)}")
                print(f"    XBRL FV sum: ${xbrl_fv.sum()/1e6:,.0f}M")
    except FileNotFoundError:
        pass

    # --- Aggregate validation ---
    from pipeline.validate_html_template import (
        validate_cik as _validate_cik,
        _print_cik_report,
    )
    print("\n" + "=" * 60)
    print("VALIDATION (self-referential + count stability)")
    print("=" * 60)
    result = _validate_cik(cik_stripped)
    _print_cik_report(result)

    # Actionable guidance
    s = result.get("summary", {})
    if s.get("median_self_ref_ratio") is not None:
        if s["median_self_ref_ratio"] < 0.85:
            print("\n  ACTION: self-ref ratio < 0.85 -- missing positions.")
            print("  Check: continuation detection, multi-table merging")
        elif s["median_self_ref_ratio"] > 1.15:
            print("\n  ACTION: self-ref ratio > 1.15 -- extracting too much.")
            print("  Check: comparative periods, wrong table, dollar_unit")

    if s.get("count_instability", 0) > 0:
        print("\n  ACTION: Position count instability detected.")
        print("  Check: variant boundaries, missing tables, 10-K vs 10-Q")


# ---------------------------------------------------------------------------
# Progress summary
# ---------------------------------------------------------------------------

def show_progress():
    """Show overall template creation progress."""
    idx = _load_filings_index()
    html_filings = idx[idx["xbrl_download_status"] == "not_found"]
    all_ciks = set(html_filings["cik"].str.lstrip("0"))

    existing = {f.stem for f in HTML_TEMPLATE_DIR.glob("*.json")}
    completed = all_ciks & existing
    remaining = all_ciks - existing

    print(f"\n{'='*70}")
    print(f"Template Creation Progress")
    print(f"{'='*70}")
    print(f"  Total CIKs needing templates: {len(all_ciks)}")
    print(f"  Completed: {len(completed)} ({len(completed)/len(all_ciks)*100:.0f}%)")
    print(f"  Remaining: {len(remaining)}")

    if completed:
        print(f"\n  Completed templates:")
        for cik in sorted(completed):
            template_file = HTML_TEMPLATE_DIR / f"{cik}.json"
            with open(template_file) as f:
                t = json.load(f)
            name = t.get("entity_name", "N/A")
            print(f"    {cik:>10}  {name}")

    # Estimate coverage
    completed_filings = html_filings[
        html_filings["cik"].str.lstrip("0").isin(completed)
    ]
    print(f"\n  Filing coverage: {len(completed_filings)}/{len(html_filings)} "
          f"({len(completed_filings)/len(html_filings)*100:.0f}%)")


# ---------------------------------------------------------------------------
# Claim next CIK
# ---------------------------------------------------------------------------

_CLAIMS_LOCK = TEMPLATE_CLAIMS_FILE.with_suffix(".lock")


class _ClaimsLock:
    """File-based lock for atomic read-modify-write of claims JSON.

    Uses O_CREAT|O_EXCL to atomically create a lock file.  Spins with
    backoff for up to ~10 seconds before giving up.
    """

    def __enter__(self):
        for i in range(100):
            try:
                fd = os.open(str(_CLAIMS_LOCK),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                # Stale lock? If older than 60s, break it.
                try:
                    age = time.time() - os.path.getmtime(str(_CLAIMS_LOCK))
                    if age > 60:
                        os.unlink(str(_CLAIMS_LOCK))
                        continue
                except OSError:
                    pass
                time.sleep(0.1)
        raise RuntimeError("Could not acquire claims lock after 10s")

    def __exit__(self, *exc):
        try:
            os.unlink(str(_CLAIMS_LOCK))
        except OSError:
            pass


def _load_claims() -> dict:
    """Load claimed CIKs from JSON file. Returns {cik: status}."""
    if TEMPLATE_CLAIMS_FILE.exists():
        try:
            return json.load(open(TEMPLATE_CLAIMS_FILE))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_claims(claims: dict):
    """Save claims atomically (write tmp + rename)."""
    tmp = TEMPLATE_CLAIMS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(claims, f, indent=2)
    tmp.replace(TEMPLATE_CLAIMS_FILE)


def _get_priority_queue() -> list[dict]:
    """Return CIKs needing templates, sorted by priority (XBRL first, then
    by filing count descending)."""
    idx = _load_filings_index()
    html_filings = idx[idx["xbrl_download_status"] == "not_found"]

    existing = {f.stem for f in HTML_TEMPLATE_DIR.glob("*.json")}

    grouped = html_filings.groupby("cik").agg(
        entity_name=("entity_name", "first"),
        n_filings=("accession_number", "count"),
    ).reset_index()

    try:
        bdc = pd.read_csv(
            OUTPUT_DIR / "bdc_holdings.csv", usecols=["cik"], dtype=str,
        )
        xbrl_ciks = set(bdc["cik"].str.lstrip("0"))
    except FileNotFoundError:
        xbrl_ciks = set()

    grouped["cik_stripped"] = grouped["cik"].str.lstrip("0")
    grouped["has_xbrl"] = grouped["cik_stripped"].isin(xbrl_ciks)

    needed = grouped[~grouped["cik_stripped"].isin(existing)]
    needed = needed.sort_values(
        ["has_xbrl", "n_filings"], ascending=[False, False],
    )

    return [
        {"cik": row["cik_stripped"], "name": row["entity_name"],
         "n_filings": int(row["n_filings"]), "has_xbrl": bool(row["has_xbrl"])}
        for _, row in needed.iterrows()
    ]


def claim_next_cik():
    """Claim the next available CIK and run --prepare on it.

    Uses a JSON claims file with file locking for safe parallel execution.
    A CIK is available if it has no template AND is not already claimed.
    """
    queue = _get_priority_queue()
    if not queue:
        print("All CIKs have templates!")
        return

    # --- Critical section: read claims, pick CIK, write claim ---
    with _ClaimsLock():
        claims = _load_claims()

        # Prune claims for CIKs that now have templates
        existing = {f.stem for f in HTML_TEMPLATE_DIR.glob("*.json")}
        claims = {k: v for k, v in claims.items() if k not in existing}

        claimed_cik = None
        for entry in queue:
            cik = entry["cik"]
            if cik not in claims:
                claimed_cik = entry
                break

        if claimed_cik is None:
            print("All remaining CIKs are claimed by other instances.")
            print(f"  Claimed: {len(claims)}, Queue: {len(queue)}")
            print(f"  If an instance died, delete {TEMPLATE_CLAIMS_FILE} "
                  f"to reset.")
            return

        claims[claimed_cik["cik"]] = "claimed"
        _save_claims(claims)
    # --- End critical section ---

    cik = claimed_cik["cik"]
    print(f"CLAIMED CIK: {cik}")
    print(f"  Name: {claimed_cik['name']}")
    print(f"  Pre-XBRL filings: {claimed_cik['n_filings']}")
    print(f"  XBRL ground truth: {'Yes' if claimed_cik['has_xbrl'] else 'No'}")

    # Run prepare (outside lock -- downloads can be slow)
    prepare_cik(cik)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Manage per-CIK HTML extraction templates",
    )
    parser.add_argument("--list", action="store_true",
                        help="List CIKs needing templates")
    parser.add_argument("--next", action="store_true",
                        help="Claim and prepare the next available CIK")
    parser.add_argument("--prepare", type=str, metavar="CIK",
                        help="Prepare data for a specific CIK")
    parser.add_argument("--validate", type=str, metavar="CIK",
                        help="Validate a template against XBRL ground truth")
    parser.add_argument("--validate-only", type=str, metavar="CIK",
                        help="Run aggregate + carry validation only (no "
                        "extraction detail)")
    parser.add_argument("--progress", action="store_true",
                        help="Show overall progress")

    args = parser.parse_args()

    if args.list:
        list_ciks()
    elif args.next:
        claim_next_cik()
    elif args.prepare:
        prepare_cik(args.prepare)
    elif args.validate:
        validate_template(args.validate)
    elif args.validate_only:
        from pipeline.validate_html_template import (
            validate_cik as _validate_cik,
            _print_cik_report,
        )
        result = _validate_cik(args.validate_only.lstrip("0"))
        _print_cik_report(result)
    elif args.progress:
        show_progress()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
