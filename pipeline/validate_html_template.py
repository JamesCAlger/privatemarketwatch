"""Template-level validation for HTML holdings extraction.

Two complementary checks per CIK:

1. **Aggregate FV** -- Compare sum(html_extracted_fv) against the balance-sheet
   ``InvestmentsAtFairValue`` concept from the SEC companyfacts API.  The API
   has data back to ~2009, long before position-level XBRL (~2022).

2. **Cross-quarter carry rate** -- A healthy BDC portfolio turns over ~5-15%
   per quarter.  If extraction shows <70% positions carrying forward, something
   is wrong (wrong table, missed pages, broken continuation detection).

Usage::

    python -m scripts.validate_html_template --cik 1287750
    python -m scripts.validate_html_template --all
"""

import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Optional

import pandas as pd

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_HTML_CACHE_DIR,
    COMPANYFACTS_CACHE_DIR,
    HTML_TEMPLATE_DIR,
    HTML_TEMPLATE_VALIDATION_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section A: companyfacts fetcher
# ---------------------------------------------------------------------------

_CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def _fetch_companyfacts(
    cik: str,
    client: Optional[object] = None,
) -> dict:
    """Fetch companyfacts JSON for *cik*, with 7-day disk cache.

    Returns parsed JSON dict, or empty dict on failure.
    """
    cik_padded = str(cik).zfill(10)
    cache_path = COMPANYFACTS_CACHE_DIR / f"{cik_padded}.json"

    # Check cache freshness
    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < _CACHE_MAX_AGE_SECONDS:
            try:
                with open(cache_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    # Fetch from SEC
    if client is None:
        from pipeline.edgar_client import EdgarClient
        client = EdgarClient()

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    try:
        data = client.get_json(url)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("Failed to fetch companyfacts for CIK %s: %s", cik, exc)
        return {}

    # Save to cache
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(data, f)
    except OSError as exc:
        logger.debug("Cache write failed for CIK %s: %s", cik, exc)

    return data


# ---------------------------------------------------------------------------
# Section B: aggregate FV concept finder
# ---------------------------------------------------------------------------

_FV_CONCEPT_KEYWORDS = [
    "investmentsatfairvalue",
    "investmentownedatfairvalue",
    "fairvalueinvestments",
    "totalinvestmentsfairvalue",
    "investmentsinfairvalue",
]


def _find_investment_fv_series(facts: dict) -> dict[str, float]:
    """Extract {report_date: aggregate_fv} from companyfacts JSON.

    Searches all taxonomies for concepts containing FV keywords.
    Picks the concept with the most data points.  Filters to instant
    facts (have ``end`` but no ``start``) in USD units.
    """
    if not facts:
        return {}

    all_facts = facts.get("facts", {})
    best_series: dict[str, float] = {}

    for taxonomy, concepts in all_facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept_name, concept_data in concepts.items():
            name_lower = concept_name.lower()
            if not any(kw in name_lower for kw in _FV_CONCEPT_KEYWORDS):
                continue

            units = concept_data.get("units", {})
            usd_entries = units.get("USD", [])
            if not usd_entries:
                continue

            # Filter to instant facts (have end, no start)
            series: dict[str, float] = {}
            for entry in usd_entries:
                end_date = entry.get("end")
                start_date = entry.get("start")
                val = entry.get("val")
                if end_date and not start_date and val is not None:
                    try:
                        series[end_date] = float(val)
                    except (ValueError, TypeError):
                        continue

            if len(series) > len(best_series):
                best_series = series

    return best_series


# ---------------------------------------------------------------------------
# Section C: dollar unit auto-detection
# ---------------------------------------------------------------------------

_MULTIPLIERS = [1e-6, 1e-3, 1, 1e3, 1e6]


def _auto_detect_unit(
    html_sum: float,
    xbrl_agg: float,
) -> tuple[float, float, float]:
    """Find the power-of-10 multiplier that brings html_sum closest to xbrl_agg.

    Returns (adjusted_ratio, best_multiplier, raw_ratio).
    """
    if xbrl_agg == 0 or html_sum == 0:
        return (0.0, 1.0, 0.0)

    raw_ratio = html_sum / xbrl_agg
    best_mult = 1.0
    best_log_dist = float("inf")

    for mult in _MULTIPLIERS:
        ratio = (html_sum * mult) / xbrl_agg
        if ratio <= 0:
            continue
        log_dist = abs(math.log10(ratio))
        if log_dist < best_log_dist:
            best_log_dist = log_dist
            best_mult = mult

    adj_ratio = (html_sum * best_mult) / xbrl_agg
    return (adj_ratio, best_mult, raw_ratio)


# ---------------------------------------------------------------------------
# Section D: carry rate computation
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Lightweight name normalization for carry rate matching."""
    if not name or not isinstance(name, str):
        return ""
    s = name.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(",;.")
    return s.strip()


def _compute_carry_rates(
    positions_by_date: dict[str, list[str]],
) -> list[dict]:
    """Compute carry rates between consecutive report dates.

    Input: {report_date: [list of issuer_names]}.
    Returns list of dicts with carry/new rate info.
    """
    dates = sorted(positions_by_date.keys())
    if len(dates) < 2:
        return []

    results: list[dict] = []
    for i in range(len(dates) - 1):
        d1, d2 = dates[i], dates[i + 1]
        names1 = {_normalize_name(n) for n in positions_by_date[d1] if n}
        names2 = {_normalize_name(n) for n in positions_by_date[d2] if n}

        # Remove empty strings
        names1.discard("")
        names2.discard("")

        carried = names1 & names2
        carry_rate = len(carried) / len(names1) if names1 else 0.0
        new_rate = len(names2 - names1) / len(names2) if names2 else 0.0

        results.append({
            "begin_date": d1,
            "end_date": d2,
            "begin_count": len(names1),
            "end_count": len(names2),
            "carried": len(carried),
            "carry_rate": round(carry_rate, 4),
            "new_rate": round(new_rate, 4),
        })

    return results


# ---------------------------------------------------------------------------
# Section D2: self-referential subtotal validation
# ---------------------------------------------------------------------------

_SUBTOTAL_PATTERNS = [
    r"total\s+investments?\s+at\s+fair\s+value",
    r"total\s+investments",
    r"total\s+portfolio",
    r"total\s+fair\s+value",
    r"grand\s+total",
]
_SUBTOTAL_RE = re.compile(
    "|".join(f"(?:{p})" for p in _SUBTOTAL_PATTERNS),
    re.IGNORECASE,
)


def _find_subtotal_fv(holdings: list[dict]) -> Optional[float]:
    """Find the highest-level subtotal FV from extracted rows.

    Searches for rows whose issuer_name matches subtotal patterns.
    Returns the FV of the best match, or None if no subtotal found.
    """
    candidates: list[tuple[str, float]] = []
    for row in holdings:
        name = row.get("investment_identifier") or row.get("issuer_name", "")
        if not name:
            continue
        if _SUBTOTAL_RE.search(name):
            fv = _safe_float(row.get("fair_value"))
            if fv is not None and fv > 0:
                candidates.append((name, fv))
    if not candidates:
        return None
    # Pick the largest FV (highest-level subtotal)
    return max(candidates, key=lambda x: x[1])[1]


def _self_referential_check(
    holdings: list[dict],
) -> dict:
    """Compare sum of position FVs vs HTML's own subtotal row.

    Returns dict with subtotal_fv, position_fv_sum, ratio, status.
    """
    subtotal_fv = _find_subtotal_fv(holdings)
    if subtotal_fv is None:
        return {"status": "NO_SUBTOTAL", "subtotal_fv": None,
                "position_fv_sum": None, "ratio": None}

    # Sum FV of non-subtotal rows
    position_fv = 0.0
    for r in holdings:
        if r.get("is_subtotal", False):
            continue
        name = r.get("investment_identifier") or r.get("issuer_name", "") or ""
        if _SUBTOTAL_RE.search(name):
            continue
        fv = _safe_float(r.get("fair_value"))
        if fv is not None:
            position_fv += fv

    if position_fv == 0:
        return {"status": "NO_POSITIONS", "subtotal_fv": subtotal_fv,
                "position_fv_sum": 0.0, "ratio": 0.0}

    ratio = position_fv / subtotal_fv
    status = "PASS" if 0.85 <= ratio <= 1.15 else "FAIL"

    return {
        "status": status,
        "subtotal_fv": round(subtotal_fv, 2),
        "position_fv_sum": round(position_fv, 2),
        "ratio": round(ratio, 4),
    }


# ---------------------------------------------------------------------------
# Section D3: position count stability
# ---------------------------------------------------------------------------

def _check_position_count_stability(
    counts_by_date: dict[str, int],
) -> list[dict]:
    """Check QoQ position count changes.

    Flags transitions where count changes by >50%.
    """
    dates = sorted(counts_by_date.keys())
    if len(dates) < 2:
        return []

    results: list[dict] = []
    for i in range(len(dates) - 1):
        d1, d2 = dates[i], dates[i + 1]
        c1, c2 = counts_by_date[d1], counts_by_date[d2]
        if c1 == 0:
            continue
        change = abs(c2 - c1) / c1
        results.append({
            "begin_date": d1, "end_date": d2,
            "begin_count": c1, "end_count": c2,
            "pct_change": round(change, 4),
            "status": "WARN" if change > 0.50 else "OK",
        })
    return results


# ---------------------------------------------------------------------------
# Section E: per-CIK validator
# ---------------------------------------------------------------------------

def validate_cik(
    cik: str,
    client: Optional[object] = None,
) -> dict:
    """Run aggregate FV + carry rate validation for one CIK.

    Returns a results dict with per-filing details and summary.
    """
    from pipeline.html_template import extract_filing_with_template, load_template

    cik_stripped = str(cik).lstrip("0") or "0"

    # Load template
    template = load_template(cik_stripped)
    if template is None:
        return {"cik": cik_stripped, "error": "no_template", "filings": []}

    entity_name = template.get("entity_name", "")

    # Load filing index
    if not BDC_FILINGS_INDEX_FILE.exists():
        return {"cik": cik_stripped, "error": "no_filings_index", "filings": []}

    idx = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
    idx["cik_stripped"] = idx["cik"].str.lstrip("0")
    cik_filings = idx[idx["cik_stripped"] == cik_stripped].copy()

    if cik_filings.empty:
        return {"cik": cik_stripped, "error": "no_filings", "filings": []}

    # Fetch companyfacts
    facts = _fetch_companyfacts(cik_stripped, client)
    fv_series = _find_investment_fv_series(facts)

    # Process each filing with cached HTML
    filing_results: list[dict] = []
    positions_by_date: dict[str, list[str]] = {}
    counts_by_date: dict[str, int] = {}

    for _, frow in cik_filings.iterrows():
        acc = str(frow["accession_number"])
        acc_nodashes = acc.replace("-", "")
        html_path = BDC_HTML_CACHE_DIR / cik_stripped / f"{acc_nodashes}.html"

        if not html_path.exists() or html_path.stat().st_size < 1024:
            continue

        report_date = str(frow.get("report_date", ""))
        form_type = str(frow.get("form_type", ""))

        # Read and extract
        try:
            html_content = html_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        filing_meta = {
            "cik": cik_stripped,
            "entity_name": entity_name,
            "accession_number": acc,
            "form_type": form_type,
            "filing_date": str(frow.get("filing_date", "")),
            "report_date": report_date,
        }

        try:
            html_rows, stats = extract_filing_with_template(
                html_content, filing_meta, template
            )
        except Exception as exc:
            logger.debug("Extraction failed for %s/%s: %s", cik_stripped, acc, exc)
            continue

        if not html_rows:
            continue

        # Compute aggregate FV
        fv_values = []
        names = []
        for row in html_rows:
            fv = _safe_float(row.get("fair_value"))
            if fv is not None:
                fv_values.append(fv)
            name = row.get("investment_identifier") or row.get("issuer_name", "")
            if name:
                names.append(name)

        html_fv_sum = sum(fv_values)
        html_count = len(html_rows)

        # Collect positions for carry rate (exclude subtotals)
        non_subtotal_names = []
        for row in html_rows:
            if row.get("is_subtotal", False):
                continue
            name = row.get("investment_identifier") or row.get("issuer_name", "")
            if name and not _SUBTOTAL_RE.search(name):
                non_subtotal_names.append(name)
        if report_date and non_subtotal_names:
            positions_by_date.setdefault(report_date, []).extend(non_subtotal_names)
            counts_by_date[report_date] = len(non_subtotal_names)

        # Self-referential subtotal check
        self_ref = _self_referential_check(html_rows)

        # Compare against companyfacts (supplementary)
        cf_fv = fv_series.get(report_date)
        adj_ratio = None
        unit_multiplier = None
        raw_ratio = None
        agg_status = "NO_DATA"

        if cf_fv is not None and cf_fv != 0 and html_fv_sum != 0:
            adj_ratio, unit_multiplier, raw_ratio = _auto_detect_unit(
                html_fv_sum, cf_fv
            )
            agg_status = "PASS" if 0.5 <= adj_ratio <= 2.0 else "FAIL"

        filing_results.append({
            "cik": cik_stripped,
            "entity_name": entity_name,
            "report_date": report_date,
            "form_type": form_type,
            "html_count": html_count,
            "position_count": len(non_subtotal_names),
            "html_fv_sum": round(html_fv_sum, 2) if html_fv_sum else 0,
            "cf_fv": cf_fv,
            "raw_ratio": round(raw_ratio, 6) if raw_ratio is not None else None,
            "unit_multiplier": unit_multiplier,
            "adj_ratio": round(adj_ratio, 4) if adj_ratio is not None else None,
            "agg_status": agg_status,
            "self_ref_status": self_ref["status"],
            "self_ref_ratio": self_ref["ratio"],
            "self_ref_subtotal_fv": self_ref.get("subtotal_fv"),
            "self_ref_position_fv": self_ref.get("position_fv_sum"),
            "variant_used": stats.get("variant_id"),
            "drift_detected": stats.get("drift_detected", False),
        })

    # Compute carry rates
    carry_rates = _compute_carry_rates(positions_by_date)

    # Position count stability
    count_stability = _check_position_count_stability(counts_by_date)

    # Add carry info to filing results
    carry_by_end = {cr["end_date"]: cr for cr in carry_rates}
    for fr in filing_results:
        rd = fr["report_date"]
        cr = carry_by_end.get(rd)
        if cr:
            fr["carry_rate"] = cr["carry_rate"]
            fr["carry_status"] = "PASS" if cr["carry_rate"] >= 0.70 else "FAIL"
        else:
            fr["carry_rate"] = None
            fr["carry_status"] = "NO_PRIOR"

    # Summary
    agg_results = [f for f in filing_results if f["agg_status"] != "NO_DATA"]
    carry_results = [f for f in filing_results if f["carry_status"] != "NO_PRIOR"]

    agg_pass = sum(1 for f in agg_results if f["agg_status"] == "PASS")
    carry_pass = sum(1 for f in carry_results if f["carry_status"] == "PASS")

    adj_ratios = [f["adj_ratio"] for f in agg_results if f["adj_ratio"] is not None]
    carry_vals = [f["carry_rate"] for f in carry_results if f["carry_rate"] is not None]

    # Detect unit mismatch (consistent multiplier != 1)
    multipliers = [f["unit_multiplier"] for f in agg_results if f["unit_multiplier"] is not None]
    non_unity = [m for m in multipliers if m != 1.0]
    unit_mismatch = len(non_unity) > len(multipliers) * 0.5 if multipliers else False

    # Self-referential subtotal stats
    sr_results = [f for f in filing_results if f.get("self_ref_status") not in (None, "NO_SUBTOTAL")]
    sr_pass = sum(1 for f in sr_results if f["self_ref_status"] == "PASS")
    sr_fail = sum(1 for f in sr_results if f["self_ref_status"] == "FAIL")
    sr_no_subtotal = sum(1 for f in filing_results if f.get("self_ref_status") == "NO_SUBTOTAL")
    sr_ratios = [f["self_ref_ratio"] for f in sr_results if f.get("self_ref_ratio") is not None]

    # Count stability stats
    count_warnings = sum(1 for cs in count_stability if cs["status"] == "WARN")

    summary = {
        "filings_total": len(filing_results),
        "filings_with_html": len(filing_results),
        # Companyfacts aggregate (supplementary)
        "agg_validated": len(agg_results),
        "agg_pass": agg_pass,
        "agg_fail": len(agg_results) - agg_pass,
        "median_adj_ratio": round(_median(adj_ratios), 4) if adj_ratios else None,
        "unit_mismatch_detected": unit_mismatch,
        "agg_overall": "PASS" if agg_results and agg_pass == len(agg_results) else (
            "FAIL" if agg_results else "NO_DATA"
        ),
        # Self-referential subtotal (primary for pre-2019)
        "self_ref_validated": len(sr_results),
        "self_ref_pass": sr_pass,
        "self_ref_fail": sr_fail,
        "self_ref_no_subtotal": sr_no_subtotal,
        "median_self_ref_ratio": round(_median(sr_ratios), 4) if sr_ratios else None,
        "self_ref_overall": "PASS" if sr_results and sr_pass == len(sr_results) else (
            "FAIL" if sr_results else "NO_DATA"
        ),
        # Carry rate
        "carry_pairs": len(carry_results),
        "carry_pass": carry_pass,
        "carry_fail": len(carry_results) - carry_pass,
        "median_carry": round(_median(carry_vals), 4) if carry_vals else None,
        "min_carry": round(min(carry_vals), 4) if carry_vals else None,
        "carry_overall": "PASS" if carry_results and _median(carry_vals) >= 0.75 else (
            "FAIL" if carry_results else "NO_DATA"
        ),
        "low_carry_pairs": sum(1 for v in carry_vals if v < 0.50),
        # Position count stability
        "count_instability": count_warnings,
    }

    # Overall PASS/FAIL: self-referential (when available) + count stability
    # Carry rate and companyfacts are informational (not gates)
    overall = "PASS"
    if count_warnings > 0:
        overall = "FAIL"
    elif summary["self_ref_overall"] == "FAIL":
        overall = "FAIL"
    elif (summary["self_ref_overall"] == "NO_DATA"
          and summary["agg_overall"] == "NO_DATA"
          and not count_stability):
        overall = "NO_DATA"

    return {
        "cik": cik_stripped,
        "entity_name": entity_name,
        "filings": filing_results,
        "carry_rates": carry_rates,
        "count_stability": count_stability,
        "summary": summary,
        "overall": overall,
    }


def _safe_float(val) -> Optional[float]:
    """Convert to float safely, return None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (ValueError, TypeError):
        return None


def _median(values: list[float]) -> float:
    """Simple median without numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


# ---------------------------------------------------------------------------
# Section F: multi-CIK orchestrator
# ---------------------------------------------------------------------------

def validate_all(
    ciks: Optional[set[str]] = None,
    client: Optional[object] = None,
) -> pd.DataFrame:
    """Run validation across all (or selected) template CIKs.

    Returns DataFrame with per-filing results.
    """
    # Discover template CIKs
    template_files = list(HTML_TEMPLATE_DIR.glob("*.json"))
    all_template_ciks = {f.stem for f in template_files}

    if ciks:
        target_ciks = {c.lstrip("0") for c in ciks} & all_template_ciks
    else:
        target_ciks = all_template_ciks

    if not target_ciks:
        logger.warning("No template CIKs found")
        return pd.DataFrame()

    logger.info("Validating %d template CIKs", len(target_ciks))

    all_filings: list[dict] = []
    summaries: list[dict] = []

    for cik in sorted(target_ciks):
        result = validate_cik(cik, client=client)
        if result.get("error"):
            logger.debug("Skipping CIK %s: %s", cik, result["error"])
            continue

        all_filings.extend(result["filings"])
        summaries.append({
            "cik": result["cik"],
            "entity_name": result.get("entity_name", ""),
            "overall": result["overall"],
            **result["summary"],
        })

        _print_cik_report(result)

    if not all_filings:
        logger.warning("No filings could be validated")
        return pd.DataFrame()

    df = pd.DataFrame(all_filings)
    df.to_csv(HTML_TEMPLATE_VALIDATION_FILE, index=False)
    logger.info("Validation results written to %s", HTML_TEMPLATE_VALIDATION_FILE)

    # Print overall summary
    _print_overall_summary(summaries)

    return df


# ---------------------------------------------------------------------------
# Section G: output formatting
# ---------------------------------------------------------------------------

def _print_cik_report(result: dict) -> None:
    """Print validation results for one CIK."""
    s = result.get("summary", {})
    cik = result["cik"]
    name = result.get("entity_name", "")

    print(f"\n=== Template Validation: CIK {cik} ({name}) ===")

    # Self-referential subtotal check (primary)
    print("\nSelf-Referential Subtotal Check:")
    sr_total = s.get("self_ref_pass", 0) + s.get("self_ref_fail", 0)
    sr_none = s.get("self_ref_no_subtotal", 0)
    print(f"  Filings with subtotals: {sr_total}")
    print(f"  Filings without subtotals: {sr_none}")
    if s.get("median_self_ref_ratio") is not None:
        print(f"  Median ratio: {s['median_self_ref_ratio']:.4f}")
    print(f"  In range (0.85-1.15): {s.get('self_ref_pass', 0)}/{sr_total}")
    print(f"  STATUS: {s.get('self_ref_overall', 'NO_DATA')}")

    # Show self-ref failures
    sr_fails = [f for f in result.get("filings", [])
                if f.get("self_ref_status") == "FAIL"]
    if sr_fails:
        print("  Failing filings:")
        for f in sr_fails[:5]:
            print(f"    {f['report_date']} ({f['form_type']}): "
                  f"ratio={f.get('self_ref_ratio', '?')}, "
                  f"positions=${f.get('self_ref_position_fv', 0):,.0f}, "
                  f"subtotal=${f.get('self_ref_subtotal_fv', 0):,.0f}")

    # Position count stability (gate)
    count_warnings = s.get("count_instability", 0)
    print(f"\nPosition Count Stability:")
    print(f"  QoQ jumps > 50%: {count_warnings}")
    if count_warnings > 0:
        for cs in result.get("count_stability", []):
            if cs["status"] == "WARN":
                print(f"    {cs['begin_date']} -> {cs['end_date']}: "
                      f"{cs['begin_count']} -> {cs['end_count']} "
                      f"({cs['pct_change']:.0%} change)")
    print(f"  STATUS: {'PASS' if count_warnings == 0 else 'FAIL'}")

    # Carry rate (informational)
    print("\nCross-Quarter Carry Rate (informational):")
    print(f"  Quarter pairs: {s.get('carry_pairs', 0)}")
    if s.get("median_carry") is not None:
        print(f"  Median carry: {s['median_carry']:.0%}")
    if s.get("min_carry") is not None:
        print(f"  Min carry: {s['min_carry']:.0%}")
    low_carry = s.get("low_carry_pairs", 0)
    if low_carry > 0:
        print(f"  Pairs below 50%: {low_carry}")
        carry_fails = [cr for cr in result.get("carry_rates", [])
                       if cr["carry_rate"] < 0.50]
        for cr in carry_fails:
            print(f"    {cr['begin_date']} -> {cr['end_date']}: "
                  f"{cr['carry_rate']:.0%} carry "
                  f"({cr['carried']}/{cr['begin_count']} carried)")

    # Aggregate FV (companyfacts -- informational)
    print("\nAggregate FV (companyfacts, informational):")
    print(f"  Companyfacts coverage: {s.get('agg_validated', 0)}/{s.get('filings_with_html', 0)}")
    if s.get("unit_mismatch_detected"):
        print("  Unit mismatch: DETECTED (auto-corrected)")
    if s.get("median_adj_ratio") is not None:
        print(f"  Median adjusted ratio: {s['median_adj_ratio']:.4f}")

    print(f"\nOverall: {result.get('overall', 'NO_DATA')}")


def _print_overall_summary(summaries: list[dict]) -> None:
    """Print aggregate summary across all CIKs."""
    if not summaries:
        return

    print("\n" + "=" * 60)
    print("OVERALL SUMMARY")
    print("=" * 60)

    total = len(summaries)
    passed = sum(1 for s in summaries if s["overall"] == "PASS")
    failed = sum(1 for s in summaries if s["overall"] == "FAIL")
    no_data = sum(1 for s in summaries if s["overall"] == "NO_DATA")

    print(f"  CIKs validated: {total}")
    print(f"  PASS: {passed}")
    print(f"  FAIL: {failed}")
    print(f"  NO_DATA: {no_data}")

    # Median ratios across CIKs
    adj_ratios = [s["median_adj_ratio"] for s in summaries if s.get("median_adj_ratio") is not None]
    carry_vals = [s["median_carry"] for s in summaries if s.get("median_carry") is not None]

    if adj_ratios:
        print(f"  Cross-CIK median adj ratio: {_median(adj_ratios):.4f}")
    if carry_vals:
        print(f"  Cross-CIK median carry: {_median(carry_vals):.0%}")

    # List failures
    failures = [s for s in summaries if s["overall"] == "FAIL"]
    if failures:
        print("\nFailed CIKs:")
        for s in failures:
            reasons = []
            if s.get("agg_overall") == "FAIL":
                reasons.append(f"agg ratio {s.get('median_adj_ratio', '?')}")
            if s.get("carry_overall") == "FAIL":
                reasons.append(f"carry {s.get('median_carry', '?')}")
            print(f"  {s['cik']} ({s.get('entity_name', '')}): {', '.join(reasons)}")

    print()


# ---------------------------------------------------------------------------
# Module-level entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Validate HTML template extraction against companyfacts + carry rates"
    )
    parser.add_argument("--cik", help="Validate a single CIK")
    parser.add_argument("--all", action="store_true", help="Validate all template CIKs")
    args = parser.parse_args()

    if args.cik:
        result = validate_cik(args.cik)
        _print_cik_report(result)
    elif args.all:
        validate_all()
    else:
        parser.print_help()
