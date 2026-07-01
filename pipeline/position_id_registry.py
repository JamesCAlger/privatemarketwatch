"""Persisted component->position_id registry (stable identifier layer).

Replaces the unstable global sort-rank labelling of ``position_id`` with a
governed lookup: a chain (union-find component) inherits its id from a
persisted registry keyed on a drift-resistant per-row natural key.  New
chains mint a fresh id from a monotonic counter; merges retire the absorbed
id with an audited record; identifier (``rawid``) drift on closed quarters is
carried forward rather than re-minted.

This module is pure orchestration over an already-formed component set -- it
never changes which rows chain together (that stays in
``position_matching.assign_position_ids``).  See
``docs/position_id_stable_identifier_design.md`` for the full rationale and the
measured drift evidence that motivated the key choice.

Key facts the design depends on (all measured, 2026-06-16):
  - ``issuer_name`` drifts ~12% and ``fair_value`` is a restatement hazard, so
    both are EXCLUDED from the natural key.
  - ``rawid`` drifts ~1.6% (2.7% for the wrapped cohort) from extraction-code
    fixes -- handled as a governed carry-forward, not a silent re-mint.
  - The composite ``(cik, source, report_date, rawid, principal, shares)`` has
    ~0.012% within-quarter residual collision, disambiguated deterministically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)

# Columns of the persisted registry artifact.
REGISTRY_COLUMNS = [
    "natural_key", "position_id", "first_seen_report_date",
    "last_seen_report_date",
]
RETIREMENT_COLUMNS = [
    "retired_position_id", "surviving_position_id", "reason",
    "report_date", "natural_key",
]

_PID_FMT = "POS-{:08d}"


# ---------------------------------------------------------------------------
# Natural key
# ---------------------------------------------------------------------------

def _norm(series: pd.Series) -> pd.Series:
    """Trim + stringify a column, mapping NaN/None to ''."""
    return series.astype(str).where(series.notna(), "").str.strip().replace(
        {"nan": "", "None": "", "<NA>": ""}
    )


def compute_natural_keys(unified_df: pd.DataFrame) -> pd.Series:
    """Return the drift-resistant per-row natural key, aligned to ``unified_df``.

    Base key = ``cik | source | report_date | rawid | principal | shares``
    where ``rawid = coalesce(bdc_investment_identifier, nport_holding_id)``.

    Base-key collisions within a report quarter (~0.02% of BDC rows) are
    disambiguated in two stable stages, never by frame row order:

      1. ``#dim:<bdc_dimensions_raw>`` -- the full XBRL dimension path.  XBRL
         guarantees distinct positions in one filing have distinct dimension
         contexts, so this is a per-filing-unique, cache-deterministic anchor
         (resolves ~93% of residual collisions, 175 -> 12 rows measured).
      2. ``@<lot>`` -- a deterministic ordinal over the remaining (genuinely
         XBRL-identical / HTML-sourced) rows, sorted only on STABLE structural
         fields (maturity/rate/spread/instrument), with ``fair_value``/``cost``
         as the last resort.  ``issuer_name`` (12% drift) is excluded entirely.

    The rows reaching stage 2 share an identical XBRL context, so they are
    interchangeable and the ordinal choice is invisible downstream.
    """
    df = unified_df
    n = len(df)
    if n == 0:
        return pd.Series([], dtype=str)

    def col(name: str) -> pd.Series:
        if name in df.columns:
            return _norm(df[name]).reset_index(drop=True)
        return pd.Series([""] * n, dtype=str)

    cik = col("cik")
    source = col("source")
    report_date = col("report_date")
    bdc_id = col("bdc_investment_identifier")
    nport_id = col("nport_holding_id")
    rawid = bdc_id.where(bdc_id.ne(""), nport_id)
    principal = col("principal_amount")
    shares = col("shares_held")

    base = (
        cik + "|" + source + "|" + report_date + "|"
        + rawid + "|" + principal + "|" + shares
    )
    grp = ["cik", "source", "report_date"]
    grp_df = pd.DataFrame({"cik": cik, "source": source,
                           "report_date": report_date})

    def collisions(key: pd.Series) -> pd.Series:
        tmp = grp_df.assign(_k=key)
        return tmp.groupby(grp + ["_k"], dropna=False)["_k"].transform("size") > 1

    keys = base.copy()

    # Stage 1: XBRL dimension-context disambiguation for base-key collisions.
    collided = collisions(base)
    if collided.any():
        dim = col("bdc_dimensions_raw")
        dim_disc = dim.where(dim.ne(""), "")
        stage1 = base.where(~collided, base + "#dim:" + dim_disc)
        keys = stage1
    else:
        stage1 = base

    # Stage 2: deterministic ordinal for rows still colliding (identical XBRL
    # context, or HTML rows lacking a dimension path).
    collided2 = collisions(stage1)
    if collided2.any():
        struct = (
            col("maturity_date") + "|" + col("interest_rate") + "|"
            + col("basis_spread") + "|" + col("reference_rate_type") + "|"
            + col("instrument_description")
        )
        tb = pd.DataFrame({
            "k": stage1,
            "struct": struct,
            "fair_value": pd.to_numeric(col("fair_value"), errors="coerce"),
            "cost": pd.to_numeric(col("cost"), errors="coerce"),
        })
        work = pd.concat([grp_df, tb], axis=1)[collided2.values]
        work = work.sort_values(
            grp + ["k", "struct", "fair_value", "cost"],
            kind="mergesort", na_position="last",
        )
        lot = work.groupby(grp + ["k"], dropna=False).cumcount() + 1
        suffixed = work["k"].astype(str) + "@" + lot.astype(str)
        keys = keys.copy()
        keys.loc[suffixed.index] = suffixed

    keys.index = df.index
    return keys


# ---------------------------------------------------------------------------
# Registry resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolveResult:
    uid_to_pid: dict[int, str]
    registry_df: pd.DataFrame
    retirements_df: pd.DataFrame
    n_inherited: int = 0
    n_minted: int = 0
    n_merged: int = 0
    n_split_reassigned: int = 0
    counts: dict[str, int] = field(default_factory=dict)


def _next_counter(existing_ids: set[str]) -> int:
    """Smallest unused ordinal above every id ever issued (no reuse)."""
    mx = 0
    for pid in existing_ids:
        if isinstance(pid, str) and pid.startswith("POS-"):
            try:
                mx = max(mx, int(pid[4:]))
            except ValueError:
                continue
    return mx + 1


def resolve_position_ids(
    components: list[list[int]],
    unified_df: pd.DataFrame,
    natural_keys: pd.Series,
    registry_df: pd.DataFrame | None,
) -> ResolveResult:
    """Assign a stable ``position_id`` to every unified row via the registry.

    Parameters
    ----------
    components
        Connected components as lists of unified row ids (``_uid``).  Each row
        NOT in any component is treated as a singleton component of size 1.
    unified_df
        Unified holdings (row order = ``_uid`` order).
    natural_keys
        Output of :func:`compute_natural_keys`, aligned to ``unified_df``.
    registry_df
        Prior registry (``REGISTRY_COLUMNS``) or None for a cold start.

    Returns
    -------
    ResolveResult
    """
    n_rows = len(unified_df)
    nk_by_uid = natural_keys.reset_index(drop=True).tolist()
    report_dates = (
        _norm(unified_df["report_date"]).reset_index(drop=True).tolist()
        if "report_date" in unified_df.columns else [""] * n_rows
    )

    # Prior registry map: natural_key -> position_id.
    key_to_pid: dict[str, str] = {}
    retired_ever: set[str] = set()
    if registry_df is not None and not registry_df.empty:
        for k, p in zip(
            registry_df["natural_key"].astype(str),
            registry_df["position_id"].astype(str),
        ):
            if k:
                key_to_pid[k] = p

    # Build the full component list (chains + singleton rows).
    in_component = set()
    comp_list: list[list[int]] = []
    for members in components:
        comp_list.append(sorted(members))
        in_component.update(members)
    for uid in range(n_rows):
        if uid not in in_component:
            comp_list.append([uid])

    # Stable iteration order so minted-id assignment is reproducible.
    def comp_sort_key(members: list[int]) -> str:
        return min(nk_by_uid[u] for u in members)

    comp_list.sort(key=comp_sort_key)

    retirements: list[dict] = []
    # Pass 1: tentative id per component (inherit / merge / mint-marker).
    tentative: list[str | None] = []
    existing_ids = set(key_to_pid.values())
    for members in comp_list:
        ids = {
            key_to_pid[nk_by_uid[u]]
            for u in members
            if nk_by_uid[u] in key_to_pid
        }
        if not ids:
            tentative.append(None)  # mint in pass 3
        elif len(ids) == 1:
            tentative.append(next(iter(ids)))
        else:
            # Merge: keep the lowest-ordinal (oldest) id, retire the rest.
            survivor = min(ids, key=lambda p: _ordinal(p))
            tentative.append(survivor)
            for dead in ids - {survivor}:
                retirements.append({
                    "retired_position_id": dead,
                    "surviving_position_id": survivor,
                    "reason": "chain_merge",
                    "report_date": min(report_dates[u] for u in members),
                    "natural_key": comp_sort_key(members),
                })
                retired_ever.add(dead)

    # Pass 2: split guard -- an id claimed by >1 component keeps one, others
    # are re-minted, preserving (cik, source, report_date) uniqueness.
    claims: dict[str, list[int]] = {}
    for i, pid in enumerate(tentative):
        if pid is not None:
            claims.setdefault(pid, []).append(i)
    n_split = 0
    evicted_from: dict[int, str] = {}  # component idx -> id it was evicted from
    for pid, idxs in claims.items():
        if len(idxs) <= 1:
            continue
        # Keep the component with the most member-keys already on this id;
        # tiebreak by smallest natural key for determinism (min over
        # (-hits, key) => most hits first, then lexicographically smallest).
        def keep_rank(i: int) -> tuple[int, str]:
            members = comp_list[i]
            hits = sum(
                1 for u in members if key_to_pid.get(nk_by_uid[u]) == pid
            )
            return (-hits, comp_sort_key(members))
        keeper = min(idxs, key=keep_rank)
        for i in idxs:
            if i != keeper:
                tentative[i] = None  # re-mint
                evicted_from[i] = pid
                n_split += 1

    # Pass 3: mint ids for components with no (surviving) inherited id.
    counter = _next_counter(existing_ids | retired_ever)
    n_inherited = n_minted = n_merged = 0
    for i, members in enumerate(comp_list):
        pid = tentative[i]
        ids = {
            key_to_pid[nk_by_uid[u]]
            for u in members if nk_by_uid[u] in key_to_pid
        }
        if pid is None:
            pid = _PID_FMT.format(counter)
            counter += 1
            n_minted += 1
            if i in evicted_from:
                # Audit the split: these rows carried `evicted_from[i]` last
                # build (a chain that has since split); they now carry `pid`.
                # Unlike a merge, the source id still lives (the keeper holds
                # it) -- reason distinguishes the two for re-finders.
                retirements.append({
                    "retired_position_id": evicted_from[i],
                    "surviving_position_id": pid,
                    "reason": "chain_split",
                    "report_date": min(report_dates[u] for u in members),
                    "natural_key": comp_sort_key(members),
                })
        else:
            n_inherited += 1
            if len(ids) > 1:
                n_merged += 1
        tentative[i] = pid

    # Materialise uid -> pid and the refreshed registry map.
    uid_to_pid: dict[int, str] = {}
    new_key_to_pid: dict[str, str] = dict(key_to_pid)
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}
    if registry_df is not None and not registry_df.empty:
        for k, fs, ls in zip(
            registry_df["natural_key"].astype(str),
            registry_df["first_seen_report_date"].astype(str),
            registry_df["last_seen_report_date"].astype(str),
        ):
            first_seen[k] = fs
            last_seen[k] = ls

    for i, members in enumerate(comp_list):
        pid = tentative[i]
        for u in members:
            uid_to_pid[u] = pid
            k = nk_by_uid[u]
            new_key_to_pid[k] = pid
            rd = report_dates[u]
            if k not in first_seen or (rd and rd < first_seen[k]):
                first_seen[k] = rd
            if k not in last_seen or (rd and rd > last_seen[k]):
                last_seen[k] = rd

    reg_rows = [
        {
            "natural_key": k,
            "position_id": p,
            "first_seen_report_date": first_seen.get(k, ""),
            "last_seen_report_date": last_seen.get(k, ""),
        }
        for k, p in sorted(new_key_to_pid.items())
    ]
    out_registry = pd.DataFrame(reg_rows, columns=REGISTRY_COLUMNS)
    out_retire = pd.DataFrame(retirements, columns=RETIREMENT_COLUMNS)

    return ResolveResult(
        uid_to_pid=uid_to_pid,
        registry_df=out_registry,
        retirements_df=out_retire,
        n_inherited=n_inherited,
        n_minted=n_minted,
        n_merged=n_merged,
        n_split_reassigned=n_split,
        counts={
            "components": len(comp_list),
            "registry_keys": len(out_registry),
            "retirements": len(out_retire),
        },
    )


def _ordinal(pid: str) -> int:
    if isinstance(pid, str) and pid.startswith("POS-"):
        try:
            return int(pid[4:])
        except ValueError:
            return 1 << 62
    return 1 << 62


def load_registry(path) -> pd.DataFrame | None:
    """Load a registry CSV, or None if absent/empty."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return None
    df = pd.read_csv(p, dtype=str).fillna("")
    if df.empty:
        return None
    for c in REGISTRY_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[REGISTRY_COLUMNS]
