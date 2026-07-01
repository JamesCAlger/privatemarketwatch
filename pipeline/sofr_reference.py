"""SOFR benchmark lookup + spread/all-in reconciliation (Agent A validator).

Reads the cached FRED SOFR 90-day average (scripts/fetch_sofr.py) -- a public ~3M
Term-SOFR proxy. The economic identity for a floating loan above its floor is:

    cash_all_in = max(SOFR, floor) + spread

so a spread is trustworthy iff it reconciles with the (independently known) SOFR and the
all-in rate. Used to ADJUDICATE basis_spread conflicts (which of A vs XBRL reconciles) and
as a gate sanity check. Percent units throughout. Read-only (cache only).

CAVEAT: SOFR90DAYAVG is backward-looking; loans reference forward CME Term SOFR. Expect a
~10-20bps proxy gap, so reconciliation cannot resolve spread differences finer than ~0.25pp.
"""

from __future__ import annotations

import bisect
import csv

from pipeline import config

_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        path = config.DATA_DIR / "reference" / "sofr_90day_avg.csv"
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r)  # header
            for d, v in r:
                rows.append((d, float(v)))
        rows.sort()
        _CACHE = (([x[0] for x in rows]), [x[1] for x in rows])
    return _CACHE


def sofr_for(d):
    """SOFR 90-day avg (percent) at the latest observation <= date d ('YYYY-MM-DD').
    Returns None if before the series start or unavailable."""
    if not d:
        return None
    dates, vals = _load()
    i = bisect.bisect_right(dates, str(d)[:10]) - 1
    return vals[i] if i >= 0 else None


def effective_base(sofr_pct, floor_pct):
    """The reference leg actually paid: max(SOFR, floor)."""
    if sofr_pct is None:
        return None
    return max(sofr_pct, floor_pct or 0.0)


def reconcile_residual(cash_all_in_pct, spread_pct, floor_pct, sofr_pct):
    """|(max(SOFR,floor) + spread) - cash_all_in| in percentage points, or None if inputs
    are missing. Lower = better reconciliation."""
    if cash_all_in_pct is None or spread_pct is None or sofr_pct is None:
        return None
    base = effective_base(sofr_pct, floor_pct)
    return round(abs((base + spread_pct) - cash_all_in_pct), 4)


def reconciles(cash_all_in_pct, spread_pct, floor_pct, sofr_pct, tol=0.40):
    r = reconcile_residual(cash_all_in_pct, spread_pct, floor_pct, sofr_pct)
    return None if r is None else r <= tol


def adjudicate_spread(cash_all_in_pct, a_spread_pct, xbrl_spread_pct, floor_pct, sofr_pct,
                      margin=0.10):
    """Which spread reconciles better with the all-in? Returns one of
    'agentA' | 'xbrl' | 'both' | 'neither' | 'undeterminable'. 'both' when the two residuals
    are within `margin` of each other (proxy can't resolve); 'neither' when even the winner
    is implausible (> 1.0pp off)."""
    ra = reconcile_residual(cash_all_in_pct, a_spread_pct, floor_pct, sofr_pct)
    rx = reconcile_residual(cash_all_in_pct, xbrl_spread_pct, floor_pct, sofr_pct)
    if ra is None or rx is None:
        return "undeterminable"
    if min(ra, rx) > 1.0:
        return "neither"
    if abs(ra - rx) <= margin:
        return "both"
    return "agentA" if ra < rx else "xbrl"
