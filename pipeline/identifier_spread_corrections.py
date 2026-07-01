"""Apply audited Agent A basis_spread corrections in BDC staging.

A keyed OVERRIDE (not blank-only): for the per-position rows where the freeform-identifier
spread reconciles with all-in + SOFR and the XBRL tag does not (verdict 'agentA', plausible
values only), replace basis_spread with the reconciled value. Reversible -- the override
records old_value_xbrl. Matched on (cik, report_date, identifier). Vectorized.
"""

from __future__ import annotations

import json

from pipeline import config

CORRECTIONS_FILE = config.DATA_DIR / "overrides" / "identifier_spread_corrections.json"


def load_corrections():
    if not CORRECTIONS_FILE.exists():
        return []
    with open(CORRECTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("corrections", [])


def apply_spread_corrections(df, identifier_col="bdc_investment_identifier",
                             corrections=None, log=print):
    """Override basis_spread on matched rows. Returns (df, n_applied)."""
    import pandas as pd

    if corrections is None:
        corrections = load_corrections()
    if not corrections or df is None or len(df) == 0:
        return df, 0
    if "basis_spread" not in df.columns or identifier_col not in df.columns:
        return df, 0

    corr_df = pd.DataFrame([
        {"_kc": str(c["cik"]).zfill(10), "_kr": str(c["report_date"])[:10],
         "_ki": str(c["identifier"]), "_new": float(c["new_value_decimal"])}
        for c in corrections
    ]).drop_duplicates(["_kc", "_kr", "_ki"])

    tmp = pd.DataFrame({
        "_kc": df["cik"].astype(str).str.zfill(10),
        "_kr": df["report_date"].astype(str).str[:10],
        "_ki": df[identifier_col].astype(str),
    })
    merged = tmp.merge(corr_df, on=["_kc", "_kr", "_ki"], how="left")
    mask = merged["_new"].notna().to_numpy()
    n = int(mask.sum())
    if n:
        df = df.copy()
        df.loc[mask, "basis_spread"] = merged.loc[mask, "_new"].to_numpy()
    log(f"  Agent A basis_spread corrections applied: {n} rows "
        f"(of {len(corr_df)} corrections)")
    return df, n
