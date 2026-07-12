"""Seed the stable position_id registry from the current holdings, preserving
today's labels (no flag-day renumber), scoped to Q4-2022 onward.

Mechanism: build a pre-seed map natural_key -> current position_id for every
in-scope row that already has a label, then run the real registry resolver with
the current chain structure as the components.  Existing labels are inherited
(unchanged); rows that currently lack a position_id are minted fresh ids above
the existing max.  The resolver's own output registry is written as the seed.

Self-check (printed): in-scope labelled rows whose id changed (MUST be 0),
plus merge/split counts (MUST be 0 for a faithful seed).

Writes only data/output/position_id_registry.csv (+ retirements).  Does NOT
touch private_markets_holdings.csv.  No network.

Usage:  python scripts/seed_position_id_registry.py
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from pipeline.config import (
    UNIFIED_HOLDINGS_FILE,
    POSITION_ID_REGISTRY_FILE,
    POSITION_ID_RETIREMENTS_FILE,
)
from pipeline.position_id_registry import (
    compute_natural_keys,
    resolve_position_ids,
    REGISTRY_COLUMNS,
)

SCOPE_START = "2022-10-01"


def main() -> None:
    t0 = time.time()
    # Label source: the last fully-labelled build (the live holdings file may
    # have blank position_id if the assignment step hasn't been re-run).
    source = sys.argv[1] if len(sys.argv) > 1 else str(UNIFIED_HOLDINGS_FILE)
    print(f"label source: {source}", flush=True)
    df = pd.read_csv(source, dtype=str).fillna("")
    df = df[df["report_date"] >= SCOPE_START].reset_index(drop=True)
    df["_uid"] = range(len(df))
    nk = compute_natural_keys(df).reset_index(drop=True)
    pid = df["position_id"].astype(str).str.strip()
    labelled = pid.ne("")
    print(f"in-scope rows (>= {SCOPE_START}): {len(df)}; labelled: {int(labelled.sum())} "
          f"({100*labelled.mean():.2f}%)  [{time.time()-t0:.1f}s]", flush=True)

    # Pre-seed registry: natural_key -> current position_id (labelled rows only).
    pre = pd.DataFrame({
        "natural_key": nk[labelled].values,
        "position_id": pid[labelled].values,
        "first_seen_report_date": df["report_date"][labelled].values,
        "last_seen_report_date": df["report_date"][labelled].values,
    })
    multi_pid = pre.groupby("natural_key")["position_id"].nunique()
    conflicts = int((multi_pid > 1).sum())
    print(f"natural_keys mapping to >1 current pid: {conflicts} "
          f"(must be 0 for a clean seed)", flush=True)
    if conflicts:
        print(multi_pid[multi_pid > 1].head().to_string(), flush=True)
        raise SystemExit("seed aborted: inconsistent current labels")
    pre = pre.drop_duplicates("natural_key")[REGISTRY_COLUMNS]

    # Components = current chains (same position_id on >1 in-scope row).
    comps: list[list[int]] = []
    for _pid, grp in df[labelled].groupby(pid[labelled].values):
        uids = list(grp["_uid"])
        if len(uids) > 1:
            comps.append(uids)
    print(f"current chains (multi-row position_ids): {len(comps)}  "
          f"[{time.time()-t0:.1f}s]", flush=True)

    # Resolve: inherit existing labels, mint for unlabelled rows.
    res = resolve_position_ids(comps, df, nk, pre)
    print(f"resolve: inherited={res.n_inherited} minted={res.n_minted} "
          f"merged={res.n_merged} split={res.n_split_reassigned}  "
          f"[{time.time()-t0:.1f}s]", flush=True)

    # --- Self-check: labelled rows must be unchanged ---
    changed = sum(
        1 for u in range(len(df))
        if labelled.iloc[u] and res.uid_to_pid[u] != pid.iloc[u]
    )
    print(f"\nCHECK labelled rows whose position_id changed: {changed} (want 0)",
          flush=True)
    print(f"CHECK merges: {res.n_merged} (want 0); splits: "
          f"{res.n_split_reassigned} (want 0)", flush=True)
    print(f"CHECK minted (rows that previously had no label): {res.n_minted}",
          flush=True)

    # Registry coverage
    out = res.registry_df
    print(f"\nregistry keys: {len(out)}; distinct position_ids: "
          f"{out['position_id'].nunique()}", flush=True)
    dupkey = out["natural_key"].duplicated().sum()
    print(f"duplicate natural_keys in registry: {dupkey} (want 0)", flush=True)

    if changed or res.n_merged or res.n_split_reassigned or dupkey:
        raise SystemExit("seed self-check FAILED -- registry not written")

    POSITION_ID_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(POSITION_ID_REGISTRY_FILE, index=False)
    res.retirements_df.to_csv(POSITION_ID_RETIREMENTS_FILE, index=False)
    print(f"\nWROTE {POSITION_ID_REGISTRY_FILE} ({len(out)} keys) and "
          f"{POSITION_ID_RETIREMENTS_FILE} ({len(res.retirements_df)} rows)  "
          f"[{time.time()-t0:.1f}s]", flush=True)

    # --- Cross-build coverage: how many CURRENT-build rows would inherit a
    # seeded id by direct natural-key match vs mint (the real-world signal). ---
    if source != str(UNIFIED_HOLDINGS_FILE):
        cur = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str).fillna("")
        cur = cur[cur["report_date"] >= SCOPE_START].reset_index(drop=True)
        cur_nk = compute_natural_keys(cur)
        seeded_keys = set(out["natural_key"])
        hit = cur_nk.isin(seeded_keys).sum()
        print(f"\nCROSS-BUILD coverage on live holdings ({len(cur)} rows): "
              f"{hit} ({100*hit/max(len(cur),1):.2f}%) inherit a seeded id by "
              f"natural-key; {len(cur)-hit} would mint  [{time.time()-t0:.1f}s]",
              flush=True)


if __name__ == "__main__":
    main()
