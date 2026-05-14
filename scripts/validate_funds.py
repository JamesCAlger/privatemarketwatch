"""Fund validation script for per-CIK review of frontend JSON data.

Runs deterministic pre-screening flags, provides structured briefings for
agent review, and tracks review verdicts. Designed for Claude Code instances
to claim funds and work through them.

Usage:
    python scripts/validate_funds.py --prescreen              # Flag all 386 funds
    python scripts/validate_funds.py --next                   # Claim next unreviewed
    python scripts/validate_funds.py --fund 0001803958        # Briefing (no claim)
    python scripts/validate_funds.py --verdict 0001803958 --status PASS
    python scripts/validate_funds.py --progress               # Pass/fail/pending
    python scripts/validate_funds.py --failures               # List FAIL verdicts
    python scripts/validate_funds.py --queue                  # Ordered review queue
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DATA_DIR = _ROOT / "frontend" / "public" / "data"
FUND_LIST_FILE = FRONTEND_DATA_DIR / "fund_list.json"
FUND_DETAILS_DIR = FRONTEND_DATA_DIR / "fund_details"

OUTPUT_DIR = _ROOT / "data" / "output" / "fund_validation"
PROGRESS_FILE = OUTPUT_DIR / "progress.json"
PRESCREEN_FILE = OUTPUT_DIR / "prescreen.csv"
VERDICTS_DIR = OUTPUT_DIR / "verdicts"

_CLAIMS_LOCK_FILE = PROGRESS_FILE.with_suffix(".lock")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_fund_list():
    """Load fund_list.json -> list of dicts."""
    with open(FUND_LIST_FILE) as f:
        return json.load(f)


def _load_fund_detail(cik):
    """Load fund_details/{cik}.json -> dict."""
    path = FUND_DETAILS_DIR / f"{cik}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _load_prescreen():
    """Load prescreen.csv -> list of dicts."""
    if not PRESCREEN_FILE.exists():
        return []
    with open(PRESCREEN_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _safe_float(val, default=None):
    """Safely convert to float, returning default on None/error."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Claims management (file-based lock, copied from learn_template.py)
# ---------------------------------------------------------------------------

class _ClaimsLock:
    """File-based lock for atomic read-modify-write of claims JSON."""

    def __enter__(self):
        for i in range(100):
            try:
                fd = os.open(str(_CLAIMS_LOCK_FILE),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(str(_CLAIMS_LOCK_FILE))
                    if age > 60:
                        os.unlink(str(_CLAIMS_LOCK_FILE))
                        continue
                except OSError:
                    pass
                time.sleep(0.1)
        raise RuntimeError("Could not acquire claims lock after 10s")

    def __exit__(self, *exc):
        try:
            os.unlink(str(_CLAIMS_LOCK_FILE))
        except OSError:
            pass


def _load_claims():
    """Load progress.json -> dict {cik: "claimed"|"done"}."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_claims(claims):
    """Atomic write of claims dict via temp + rename."""
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(claims, f, indent=2)
    tmp.replace(PROGRESS_FILE)


# ---------------------------------------------------------------------------
# Pre-screening rules
# ---------------------------------------------------------------------------

def _check_name_strategy(fund_list_entry, detail):
    """Flag 1: Fund name contains strategy keyword but dominant class differs."""
    flags = []
    name_lower = fund_list_entry.get("name", "").lower()
    exposure = detail.get("exposure") if detail else None
    if not exposure:
        return flags
    ac = exposure.get("assetClassSplit", {})
    vtype = fund_list_entry.get("vehicleType", "")

    # Real estate / realty
    if re.search(r"\breal\s*estate\b|\brealt[y|ies]\b", name_lower):
        re_pct = _safe_float(ac.get("realEstate"), 0)
        if re_pct < 0.15:
            flags.append(
                f"name_strategy_mismatch: name has 'real estate' but "
                f"realEstate={re_pct:.1%}"
            )

    # Credit / lending (skip BDCs -- they are all credit by nature)
    if re.search(r"\bcredit\b|\blending\b", name_lower) and vtype != "bdc":
        pc_pct = _safe_float(ac.get("privateCredit"), 0)
        if pc_pct < 0.30:
            flags.append(
                f"name_strategy_mismatch: name has 'credit/lending' but "
                f"privateCredit={pc_pct:.1%}"
            )

    # Equity
    if re.search(r"\bequity\b", name_lower):
        pe_pct = _safe_float(ac.get("privateEquity"), 0)
        if pe_pct < 0.20:
            flags.append(
                f"name_strategy_mismatch: name has 'equity' but "
                f"privateEquity={pe_pct:.1%}"
            )

    # Infrastructure
    if re.search(r"\binfrastructure\b", name_lower):
        re_pct = _safe_float(ac.get("realEstate"), 0)
        if re_pct < 0.10:
            flags.append(
                f"name_strategy_mismatch: name has 'infrastructure' but "
                f"realEstate={re_pct:.1%}"
            )

    return flags


def _check_financial_anomaly(fund_list_entry, detail):
    """Flag 2: Financial metrics outside plausible ranges."""
    flags = []

    # Fund-list level checks
    dr = _safe_float(fund_list_entry.get("distributionRate"))
    if dr is not None and dr > 50:
        flags.append(f"financial_anomaly: distribution_rate={dr:.1f}% > 50%")

    tr = _safe_float(fund_list_entry.get("totalReturnPct"))
    if tr is not None and (tr < -40 or tr > 80):
        flags.append(f"financial_anomaly: totalReturnPct={tr:.1f}% outside [-40,80]")

    qr = _safe_float(fund_list_entry.get("quarterlyReturn"))
    if qr is not None and (qr < -25 or qr > 25):
        flags.append(f"financial_anomaly: quarterlyReturn={qr:.1f}% outside [-25,25]")

    er = _safe_float(fund_list_entry.get("expenseRatioPct"))
    if er is not None and er > 10:
        flags.append(f"financial_anomaly: expenseRatioPct={er:.1f}% > 10%")

    lr = _safe_float(fund_list_entry.get("leverageRatio"))
    if lr is not None and lr > 3:
        flags.append(f"financial_anomaly: leverageRatio={lr:.2f} > 3")

    # Series-level checks
    if detail:
        series = detail.get("series", [])
        for s in series:
            q = s.get("quarter", "?")
            s_dr = _safe_float(s.get("distribution_rate_proxy"))
            if s_dr is not None and s_dr > 80:
                flags.append(
                    f"financial_anomaly: {q} distribution_rate_proxy="
                    f"{s_dr:.1f}% > 80%"
                )

    return flags


def _check_exposure_inconsistency(fund_list_entry, detail):
    """Flag 3: Asset splits that contradict each other."""
    flags = []
    exposure = detail.get("exposure") if detail else None
    if not exposure:
        return flags

    asset = exposure.get("assetSplit", {})
    ac = exposure.get("assetClassSplit", {})
    et = exposure.get("exposureTypeSplit", {})

    eq = _safe_float(asset.get("equity"), 0)
    pe = _safe_float(ac.get("privateEquity"), 0)
    fund_a = _safe_float(asset.get("fund"), 0)
    fund_e = _safe_float(et.get("fund"), 0)
    pc = _safe_float(ac.get("privateCredit"), 0)
    debt = _safe_float(asset.get("debt"), 0)
    direct = _safe_float(et.get("direct"), 0)
    hf = _safe_float(ac.get("hedgeFund"), 0)

    # KKR RE pattern: high equity but low PE
    if eq > 0.5 and pe < 0.15:
        flags.append(
            f"exposure_inconsistency: equity={eq:.1%} but "
            f"privateEquity={pe:.1%} (possible RE/other misclass)"
        )

    # Fund in asset split but not in exposure type
    if fund_a > 0.3 and fund_e < 0.1:
        flags.append(
            f"exposure_inconsistency: assetSplit.fund={fund_a:.1%} but "
            f"exposureType.fund={fund_e:.1%}"
        )

    # High private credit but low debt
    if pc > 0.5 and debt < 0.3:
        flags.append(
            f"exposure_inconsistency: privateCredit={pc:.1%} but "
            f"debt={debt:.1%}"
        )

    # High direct + hedge fund (contradictory)
    if direct > 0.9 and hf > 0.05:
        flags.append(
            f"exposure_inconsistency: direct={direct:.1%} but "
            f"hedgeFund={hf:.1%}"
        )

    return flags


def _check_classification_gap(fund_list_entry, detail):
    """Flag 4: High proportion of UNCLASSIFIED or OTHER."""
    flags = []
    exposure = detail.get("exposure") if detail else None
    if not exposure:
        return flags

    ac = exposure.get("assetClassSplit", {})
    asset = exposure.get("assetSplit", {})

    other_ac = _safe_float(ac.get("other"), 0)
    if other_ac > 0.20:
        flags.append(
            f"classification_gap: assetClassSplit.other={other_ac:.1%} > 20%"
        )

    other_a = _safe_float(asset.get("other"), 0)
    if other_a > 0.20:
        flags.append(
            f"classification_gap: assetSplit.other={other_a:.1%} > 20%"
        )

    # Check top holdings for UNCLASSIFIED
    top = detail.get("topHoldings", []) if detail else []
    if top:
        unclass_count = sum(
            1 for h in top
            if "UNCLASSIFIED" in (h.get("assetCategory") or "").upper()
        )
        if len(top) > 0 and unclass_count / len(top) > 0.30:
            flags.append(
                f"classification_gap: {unclass_count}/{len(top)} top holdings "
                f"UNCLASSIFIED ({unclass_count/len(top):.0%})"
            )

    return flags


def _check_stale_missing(fund_list_entry, detail):
    """Flag 5: Missing or stale data."""
    flags = []
    exposure = detail.get("exposure") if detail else None

    if not exposure:
        flags.append("stale_or_missing_data: no exposure data")
        return flags

    total_fv = _safe_float(exposure.get("totalFv"))
    if total_fv is None or total_fv == 0:
        flags.append("stale_or_missing_data: totalFv is null/0")

    qod = _safe_float(fund_list_entry.get("quartersOfData"))
    if qod is not None and qod < 4:
        flags.append(
            f"stale_or_missing_data: quartersOfData={int(qod)} < 4"
        )

    top = detail.get("topHoldings", []) if detail else []
    if not top:
        flags.append("stale_or_missing_data: no top holdings")

    return flags


def _check_implausible_metrics(fund_list_entry, detail):
    """Flag 6: Implausible quarter-over-quarter jumps."""
    flags = []
    if not detail:
        return flags
    series = detail.get("series", [])
    if len(series) < 2:
        return flags

    for i in range(1, len(series)):
        q = series[i].get("quarter", "?")
        q_prev = series[i - 1].get("quarter", "?")

        # NAV jumps > 40% QoQ
        nav = _safe_float(series[i].get("nav_per_share"))
        nav_prev = _safe_float(series[i - 1].get("nav_per_share"))
        if nav and nav_prev and nav_prev > 0:
            nav_chg = abs(nav - nav_prev) / nav_prev
            if nav_chg > 0.40:
                flags.append(
                    f"implausible_metrics: NAV jump {nav_chg:.0%} "
                    f"({q_prev}->{q})"
                )

        # Total assets drop > 80% QoQ
        ta = _safe_float(series[i].get("total_assets"))
        ta_prev = _safe_float(series[i - 1].get("total_assets"))
        if ta and ta_prev and ta_prev > 0:
            ta_chg = (ta_prev - ta) / ta_prev
            if ta_chg > 0.80:
                flags.append(
                    f"implausible_metrics: total_assets drop {ta_chg:.0%} "
                    f"({q_prev}->{q})"
                )

        # Leverage ratio jump > 0.5 in single quarter
        lev = _safe_float(series[i].get("leverage_ratio"))
        lev_prev = _safe_float(series[i - 1].get("leverage_ratio"))
        if lev is not None and lev_prev is not None:
            lev_chg = abs(lev - lev_prev)
            if lev_chg > 0.5:
                flags.append(
                    f"implausible_metrics: leverage_ratio jump "
                    f"{lev_chg:.2f} ({q_prev}->{q})"
                )

    return flags


def _prescreen_fund(fund_list_entry, detail):
    """Run all 6 checks on one fund. Returns list of flag strings."""
    all_flags = []
    all_flags.extend(_check_name_strategy(fund_list_entry, detail))
    all_flags.extend(_check_financial_anomaly(fund_list_entry, detail))
    all_flags.extend(_check_exposure_inconsistency(fund_list_entry, detail))
    all_flags.extend(_check_classification_gap(fund_list_entry, detail))
    all_flags.extend(_check_stale_missing(fund_list_entry, detail))
    all_flags.extend(_check_implausible_metrics(fund_list_entry, detail))
    return all_flags


# ---------------------------------------------------------------------------
# Pre-screen all
# ---------------------------------------------------------------------------

def prescreen_all():
    """Run pre-screening on all funds, save results to CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    funds = _load_fund_list()
    rows = []
    flagged_count = 0

    for entry in funds:
        cik = entry["cik"]
        detail = _load_fund_detail(cik)
        flags = _prescreen_fund(entry, detail)
        flag_categories = set()
        for f in flags:
            cat = f.split(":")[0]
            flag_categories.add(cat)

        row = {
            "cik": cik,
            "name": entry.get("name", ""),
            "vehicle_type": entry.get("vehicleType", ""),
            "total_assets": entry.get("totalAssets", ""),
            "num_flags": len(flags),
            "flag_categories": "|".join(sorted(flag_categories)),
            "flags": " ;; ".join(flags),
        }
        rows.append(row)
        if flags:
            flagged_count += 1

    # Write CSV
    fieldnames = [
        "cik", "name", "vehicle_type", "total_assets",
        "num_flags", "flag_categories", "flags",
    ]
    with open(PRESCREEN_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Pre-screened {len(rows)} funds, {flagged_count} flagged")
    print(f"Saved to {PRESCREEN_FILE}")

    # Print category summary
    all_cats = {}
    for r in rows:
        for cat in r["flag_categories"].split("|"):
            if cat:
                all_cats[cat] = all_cats.get(cat, 0) + 1
    if all_cats:
        print("\nFlag category counts:")
        for cat, cnt in sorted(all_cats.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {cnt}")


# ---------------------------------------------------------------------------
# Queue building
# ---------------------------------------------------------------------------

def _build_queue():
    """Build priority-ordered review queue.

    1. Flagged funds, sorted by num_flags desc then totalAssets desc
    2. Unflagged funds, sorted by totalAssets desc
    """
    prescreen = _load_prescreen()
    claims = _load_claims()

    # Separate flagged from unflagged
    flagged = []
    unflagged = []
    for row in prescreen:
        cik = row["cik"]
        if claims.get(cik) == "done":
            continue
        num_flags = int(row.get("num_flags", 0))
        ta = _safe_float(row.get("total_assets"), 0)
        entry = {
            "cik": cik,
            "name": row.get("name", ""),
            "vehicle_type": row.get("vehicle_type", ""),
            "total_assets": ta,
            "num_flags": num_flags,
            "flag_categories": row.get("flag_categories", ""),
            "claimed": claims.get(cik) == "claimed",
        }
        if num_flags > 0:
            flagged.append(entry)
        else:
            unflagged.append(entry)

    flagged.sort(key=lambda x: (-x["num_flags"], -(x["total_assets"] or 0)))
    unflagged.sort(key=lambda x: -(x["total_assets"] or 0))

    return flagged + unflagged


def _ensure_prescreen():
    """Auto-run prescreen if CSV doesn't exist."""
    if not PRESCREEN_FILE.exists():
        print("Pre-screen data not found, running --prescreen first...\n")
        prescreen_all()
        print()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_assets(val):
    """Dollar formatting: $31.2B, $450.3M, $12.5M, etc."""
    if val is None or val == "" or val == 0:
        return "N/A"
    try:
        v = float(val)
    except (ValueError, TypeError):
        return "N/A"
    if abs(v) >= 1e9:
        return f"${v/1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def _fmt_pct(val, decimals=1):
    """Format as percentage string."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.{decimals}f}%"
    except (ValueError, TypeError):
        return "N/A"


def _fmt_num(val, decimals=2):
    """Format number or N/A."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return "N/A"


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------

def _print_fund_briefing(cik, fund_list_entry=None, detail=None,
                         prescreen_row=None):
    """Print structured briefing to stdout."""
    if fund_list_entry is None:
        funds = _load_fund_list()
        fund_list_entry = next(
            (f for f in funds if f["cik"] == cik), None
        )
    if fund_list_entry is None:
        print(f"ERROR: CIK {cik} not found in fund_list.json")
        return

    if detail is None:
        detail = _load_fund_detail(cik)

    name = fund_list_entry.get("name", "Unknown")
    vtype = fund_list_entry.get("vehicleType", "Unknown")
    adviser = fund_list_entry.get("adviser", "") or "N/A"
    ta = _format_assets(fund_list_entry.get("totalAssets"))

    print("=" * 70)
    print("FUND VALIDATION BRIEFING")
    print("=" * 70)
    print(f"CIK:          {cik}")
    print(f"Name:         {name}")
    print(f"Vehicle Type: {vtype}")
    print(f"Adviser:      {adviser}")
    print(f"Total Assets: {ta}")
    print()

    # Pre-screen flags
    if prescreen_row is None:
        prescreen = _load_prescreen()
        prescreen_row = next(
            (r for r in prescreen if r["cik"] == cik), None
        )

    if prescreen_row:
        num_flags = int(prescreen_row.get("num_flags", 0))
        if num_flags > 0:
            print(f"PRE-SCREEN FLAGS ({num_flags}):")
            flags_str = prescreen_row.get("flags", "")
            for flag in flags_str.split(" ;; "):
                if flag.strip():
                    print(f"  [!] {flag.strip()}")
            print()
        else:
            print("PRE-SCREEN FLAGS: None\n")
    else:
        # Run on the fly
        if detail:
            flags = _prescreen_fund(fund_list_entry, detail)
            if flags:
                print(f"PRE-SCREEN FLAGS ({len(flags)}):")
                for flag in flags:
                    print(f"  [!] {flag}")
                print()
            else:
                print("PRE-SCREEN FLAGS: None\n")

    if not detail:
        print("WARNING: No fund detail JSON found for this CIK.")
        return

    # Financial time series
    series = detail.get("series", [])
    if series:
        print("FINANCIAL TIME SERIES:")
        header = (
            f"{'Quarter':<10} {'NAV':>8} {'TotalAssets':>14} "
            f"{'Leverage':>9} {'TotRet%':>8} {'DistRate':>9} "
            f"{'ExpRatio':>9}"
        )
        print(header)
        print("-" * len(header))
        for s in series:
            q = s.get("quarter", "?")
            nav = _fmt_num(s.get("nav_per_share"))
            ta_s = _format_assets(s.get("total_assets"))
            lev = _fmt_num(s.get("leverage_ratio"))
            tr = _fmt_pct(s.get("total_return_pct"))
            dr = _fmt_pct(s.get("distribution_rate_proxy"))
            er = _fmt_pct(s.get("expense_ratio_pct"))
            print(
                f"{q:<10} {nav:>8} {ta_s:>14} "
                f"{lev:>9} {tr:>8} {dr:>9} {er:>9}"
            )
        print()

    # Exposure breakdown
    exposure = detail.get("exposure")
    if exposure:
        print("EXPOSURE BREAKDOWN:")

        # Asset split
        asset_split = exposure.get("assetSplit", {})
        if asset_split:
            parts = []
            for k in ["debt", "equity", "fund", "structured", "cash", "other"]:
                v = _safe_float(asset_split.get(k), 0)
                if v > 0:
                    parts.append(f"{k}={v:.1%}")
            print(f"  Asset Split:      {', '.join(parts)}")

        # Asset class split
        ac_split = exposure.get("assetClassSplit", {})
        if ac_split:
            parts = []
            for k in ["privateCredit", "privateEquity", "realEstate",
                       "structuredCredit", "hedgeFund", "cash", "other"]:
                v = _safe_float(ac_split.get(k), 0)
                if v > 0:
                    parts.append(f"{k}={v:.1%}")
            print(f"  Asset Class:      {', '.join(parts)}")

        # Exposure type split
        et_split = exposure.get("exposureTypeSplit", {})
        if et_split:
            parts = []
            for k in ["direct", "fund", "liquid"]:
                v = _safe_float(et_split.get(k), 0)
                if v > 0:
                    parts.append(f"{k}={v:.1%}")
            print(f"  Exposure Type:    {', '.join(parts)}")

        # Lien split
        lien_split = exposure.get("lienSplit", {})
        if lien_split:
            parts = []
            for k in ["firstLien", "secondLien", "unsecured"]:
                v = _safe_float(lien_split.get(k), 0)
                if v > 0:
                    parts.append(f"{k}={v:.1%}")
            cov = _safe_float(lien_split.get("coverage"), 0)
            if parts:
                print(
                    f"  Lien Split:       {', '.join(parts)} "
                    f"(coverage={cov:.0%})"
                )

        # Rate type split
        rt_split = exposure.get("rateTypeSplit", {})
        if rt_split:
            parts = []
            for k in ["floating", "fixed"]:
                v = _safe_float(rt_split.get(k), 0)
                if v > 0:
                    parts.append(f"{k}={v:.1%}")
            if parts:
                print(f"  Rate Type:        {', '.join(parts)}")

        # WAC/WAS/WAM
        metrics = []
        wac = _safe_float(exposure.get("wac"))
        if wac is not None:
            cov = _safe_float(exposure.get("wacCoverage"), 0)
            metrics.append(f"WAC={wac:.2f}% (cov={cov:.0%})")
        was = _safe_float(exposure.get("was"))
        if was is not None:
            metrics.append(f"WAS={was:.2f}%")
        wam = _safe_float(exposure.get("wam"))
        if wam is not None:
            cov = _safe_float(exposure.get("wamCoverage"), 0)
            metrics.append(f"WAM={wam:.1f}y (cov={cov:.0%})")
        if metrics:
            print(f"  Metrics:          {', '.join(metrics)}")

        # Position count + total FV
        pos = exposure.get("positionCount")
        tfv = _format_assets(exposure.get("totalFv"))
        print(f"  Positions:        {pos}, Total FV: {tfv}")

        # Concentration
        conc = exposure.get("concentration", {})
        top10 = _safe_float(conc.get("top10Pct"))
        if top10 is not None:
            print(f"  Top 10 Conc:      {top10:.1%}")

        # PIK
        pik = exposure.get("pikExposure", {})
        pik_pct = _safe_float(pik.get("pctOfDebtFv"))
        if pik_pct is not None:
            print(f"  PIK Exposure:     {pik_pct:.1%} of debt FV")

        # Unrealized G/L
        ugl = exposure.get("unrealizedGl", {})
        ugl_pct = _safe_float(ugl.get("aggregatePct"))
        ugl_uw = _safe_float(ugl.get("pctUnderwater"))
        if ugl_pct is not None:
            print(
                f"  Unrealized G/L:   {ugl_pct:.1%} aggregate, "
                f"{ugl_uw:.0%} underwater"
            )

        print()

    # Top holdings
    top_holdings = detail.get("topHoldings", [])
    if top_holdings:
        n_show = min(10, len(top_holdings))
        print(f"TOP {n_show} HOLDINGS:")
        header = (
            f"{'#':<3} {'Issuer':<40} {'FV':>12} {'%Port':>6} "
            f"{'Category':<22} {'Rate':>6} {'Maturity':>10} {'Lien':<6}"
        )
        print(header)
        print("-" * len(header))
        for i, h in enumerate(top_holdings[:n_show]):
            issuer = (h.get("issuerName") or "?")[:39]
            fv = _format_assets(h.get("fairValue"))
            pct = _safe_float(h.get("pctOfPortfolio"))
            pct_s = f"{pct:.1%}" if pct is not None else "N/A"
            cat = (h.get("assetCategory") or "?")[:21]
            rate = _safe_float(h.get("interestRate"))
            rate_s = f"{rate:.2f}" if rate is not None else ""
            mat = h.get("maturityDate") or ""
            lien = h.get("lienPosition") or ""
            print(
                f"{i+1:<3} {issuer:<40} {fv:>12} {pct_s:>6} "
                f"{cat:<22} {rate_s:>6} {mat:>10} {lien:<6}"
            )
        print()

    # Suggested web search
    # Extract clean name (strip CIK suffix)
    clean_name = re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", name).strip()
    print("SUGGESTED WEB SEARCH:")
    print(f'  "{clean_name}" investment strategy portfolio')
    print()

    # Review checklist
    print("REVIEW CHECKLIST:")
    print("  1. Does the fund name match the dominant strategy shown?")
    print("  2. Are the asset class percentages plausible for this fund type?")
    print("  3. Do the top holdings look correctly classified?")
    print("  4. Is the total return trajectory reasonable for the strategy?")
    print("  5. Are there any data quality issues (missing, stale, implausible)?")
    print("  6. Does the leverage ratio make sense for this vehicle type?")
    print("  7. Any positions that need reclassification?")
    print()


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def claim_next_fund():
    """Claim the next unreviewed fund and print its briefing."""
    _ensure_prescreen()
    queue = _build_queue()

    if not queue:
        print("All funds have been reviewed!")
        return

    # Find first unclaimed
    with _ClaimsLock():
        claims = _load_claims()
        target = None
        for entry in queue:
            cik = entry["cik"]
            if cik not in claims:
                target = entry
                break

        if target is None:
            print("All funds are claimed or done!")
            return

        claims[target["cik"]] = "claimed"
        _save_claims(claims)

    print(f"Claimed CIK {target['cik']}")
    print()

    # Load full data and print briefing
    funds = _load_fund_list()
    fund_entry = next(
        (f for f in funds if f["cik"] == target["cik"]), None
    )
    detail = _load_fund_detail(target["cik"])
    _print_fund_briefing(
        target["cik"],
        fund_list_entry=fund_entry,
        detail=detail,
    )


def show_fund_briefing(cik):
    """Print briefing for a specific CIK without claiming."""
    # Zero-pad CIK if needed
    if not cik.startswith("0"):
        cik = cik.zfill(10)
    _print_fund_briefing(cik)


def record_verdict(cik, status):
    """Record a verdict for a fund.

    For PASS: auto-creates minimal verdict JSON.
    For FAIL/UNCERTAIN: expects verdict JSON to already exist in verdicts dir.
    """
    # Zero-pad CIK if needed
    if not cik.startswith("0"):
        cik = cik.zfill(10)

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    verdict_path = VERDICTS_DIR / f"{cik}.json"

    if status.upper() == "PASS":
        # Auto-create minimal verdict
        funds = _load_fund_list()
        fund_entry = next(
            (f for f in funds if f["cik"] == cik), None
        )

        # Get prescreen flags
        prescreen = _load_prescreen()
        ps_row = next((r for r in prescreen if r["cik"] == cik), None)
        flag_cats = []
        if ps_row and ps_row.get("flag_categories"):
            flag_cats = ps_row["flag_categories"].split("|")

        verdict = {
            "cik": cik,
            "entity_name": fund_entry.get("name", "") if fund_entry else "",
            "vehicle_type": fund_entry.get("vehicleType", "") if fund_entry else "",
            "status": "PASS",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "prescreen_flags": flag_cats,
            "findings": [],
            "metrics_review": {
                "total_return_plausible": True,
                "nav_trajectory_plausible": True,
                "leverage_plausible": True,
                "distribution_rate_plausible": True,
            },
            "top_holdings_review": None,
            "position_review_needed": False,
            "position_review_reason": None,
        }
        with open(verdict_path, "w") as f:
            json.dump(verdict, f, indent=2)
        print(f"Created PASS verdict for {cik}")

    elif status.upper() in ("FAIL", "UNCERTAIN"):
        if not verdict_path.exists():
            print(
                f"ERROR: For {status.upper()} verdicts, write the verdict "
                f"JSON first to:\n  {verdict_path}"
            )
            print(
                "\nThe verdict should include findings, metrics_review, "
                "and top_holdings_review."
            )
            return
        # Update status and timestamp in existing verdict
        with open(verdict_path) as f:
            verdict = json.load(f)
        verdict["status"] = status.upper()
        verdict["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        with open(verdict_path, "w") as f:
            json.dump(verdict, f, indent=2)
        print(f"Finalized {status.upper()} verdict for {cik}")

    else:
        print(f"ERROR: Invalid status '{status}'. Use PASS, FAIL, or UNCERTAIN.")
        return

    # Mark as done in claims
    with _ClaimsLock():
        claims = _load_claims()
        claims[cik] = "done"
        _save_claims(claims)

    print(f"Marked {cik} as done in progress.json")


def show_progress():
    """Print summary of review progress."""
    _ensure_prescreen()
    prescreen = _load_prescreen()
    claims = _load_claims()

    total = len(prescreen)
    done = sum(1 for v in claims.values() if v == "done")
    claimed = sum(1 for v in claims.values() if v == "claimed")
    pending = total - done - claimed

    # Count verdicts by status
    verdicts_by_status = {"PASS": 0, "FAIL": 0, "UNCERTAIN": 0}
    if VERDICTS_DIR.exists():
        for vf in VERDICTS_DIR.glob("*.json"):
            try:
                with open(vf) as f:
                    v = json.load(f)
                s = v.get("status", "UNKNOWN")
                verdicts_by_status[s] = verdicts_by_status.get(s, 0) + 1
            except (json.JSONDecodeError, OSError):
                pass

    # Count flagged
    flagged = sum(1 for r in prescreen if int(r.get("num_flags", 0)) > 0)

    print("FUND VALIDATION PROGRESS")
    print("=" * 40)
    print(f"Total funds:     {total}")
    print(f"Flagged:         {flagged}")
    print()
    print(f"Done:            {done}")
    print(f"  PASS:          {verdicts_by_status['PASS']}")
    print(f"  FAIL:          {verdicts_by_status['FAIL']}")
    print(f"  UNCERTAIN:     {verdicts_by_status['UNCERTAIN']}")
    print(f"Claimed:         {claimed}")
    print(f"Pending:         {pending}")
    if total > 0:
        print(f"Progress:        {done}/{total} ({done/total:.0%})")


def show_failures():
    """List all FAIL verdicts with key details."""
    if not VERDICTS_DIR.exists():
        print("No verdicts recorded yet.")
        return

    failures = []
    for vf in sorted(VERDICTS_DIR.glob("*.json")):
        try:
            with open(vf) as f:
                v = json.load(f)
            if v.get("status") == "FAIL":
                failures.append(v)
        except (json.JSONDecodeError, OSError):
            pass

    if not failures:
        print("No FAIL verdicts found.")
        return

    print(f"FAIL VERDICTS ({len(failures)}):")
    print("=" * 70)
    for v in failures:
        cik = v.get("cik", "?")
        name = v.get("entity_name", "?")
        flags = v.get("prescreen_flags", [])
        findings = v.get("findings", [])
        print(f"\n{cik}  {name}")
        if flags:
            print(f"  Flags: {', '.join(flags)}")
        for finding in findings:
            sev = finding.get("severity", "?")
            field = finding.get("field", "?")
            cur = finding.get("current_value", "")
            prop = finding.get("proposed_value", "")
            evidence = finding.get("evidence", "")
            print(f"  [{sev}] {field}: {cur} -> {prop}")
            if evidence:
                print(f"         {evidence}")
        pr = v.get("position_review_needed")
        if pr:
            reason = v.get("position_review_reason", "")
            print(f"  Position review needed: {reason}")


def show_queue():
    """Print the review queue."""
    _ensure_prescreen()
    queue = _build_queue()

    if not queue:
        print("Queue is empty -- all funds reviewed!")
        return

    print(f"REVIEW QUEUE ({len(queue)} remaining):")
    print(
        f"{'#':<4} {'CIK':<12} {'Type':<18} {'Assets':>12} "
        f"{'Flags':>5} {'Categories':<40} {'Status':<8}"
    )
    print("-" * 100)
    for i, entry in enumerate(queue[:50]):
        status = "CLAIMED" if entry["claimed"] else ""
        ta = _format_assets(entry["total_assets"])
        cats = entry.get("flag_categories", "")
        print(
            f"{i+1:<4} {entry['cik']:<12} {entry['vehicle_type']:<18} "
            f"{ta:>12} {entry['num_flags']:>5} {cats:<40} {status:<8}"
        )

    if len(queue) > 50:
        print(f"\n... and {len(queue) - 50} more")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fund validation: pre-screen, review, and record verdicts"
    )
    parser.add_argument(
        "--prescreen", action="store_true",
        help="Run deterministic flags on all funds, save to CSV"
    )
    parser.add_argument(
        "--next", action="store_true", dest="claim_next",
        help="Claim next unreviewed fund, print briefing"
    )
    parser.add_argument(
        "--fund", type=str, default=None,
        help="Print briefing for specific CIK (no claim)"
    )
    parser.add_argument(
        "--verdict", type=str, default=None,
        help="Record verdict for CIK (use with --status)"
    )
    parser.add_argument(
        "--status", type=str, default=None,
        help="Verdict status: PASS, FAIL, or UNCERTAIN"
    )
    parser.add_argument(
        "--progress", action="store_true",
        help="Show pass/fail/pending counts"
    )
    parser.add_argument(
        "--failures", action="store_true",
        help="List all FAIL verdicts"
    )
    parser.add_argument(
        "--queue", action="store_true",
        help="Show ordered review queue"
    )

    args = parser.parse_args()

    if args.prescreen:
        prescreen_all()
    elif args.claim_next:
        claim_next_fund()
    elif args.fund:
        show_fund_briefing(args.fund)
    elif args.verdict:
        if not args.status:
            print("ERROR: --verdict requires --status (PASS/FAIL/UNCERTAIN)")
            sys.exit(1)
        record_verdict(args.verdict, args.status)
    elif args.progress:
        show_progress()
    elif args.failures:
        show_failures()
    elif args.queue:
        show_queue()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
