"""Extract fund-level BDC derivative net fair value + notional from cached XBRL,
and classify each as a portfolio position vs. a financing/ALM hedge of the BDC's
own borrowings (`derivative_role`).

Analytics-only. Derivatives are NEVER index constituents -- this module writes a
separate artifact (`bdc_derivatives.csv`); it does not touch unified_holdings,
position matching, or the indices.

Design: docs/derivative_role_classifier_design.md. Evidence:
data/output/data_investigation_results.md (2026-06-16).

Net FV is READ from the standard us-gaap concepts (not derived from gross
unrealized gain/loss, which is tagged by only ~3 filers):
  net_fv = DerivativeFairValueOfDerivativeAsset - DerivativeFairValueOfDerivativeLiability
  (fallback: DerivativeAssets - DerivativeLiabilities)
per instrument type where dimensioned on us-gaap:DerivativeInstrumentRiskAxis,
else entity-level allocated to type by notional share. Notional is kept strictly
separate from FV.

Public API
----------
extract_bdc_derivatives(filings_index=None, financials=None) -> pd.DataFrame
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

import pandas as pd
from lxml import etree

from pipeline.config import (
    BDC_DERIVATIVES_FILE,
    BDC_FILINGS_INDEX_FILE,
    DERIVATIVE_ROLE_REVIEW_FILE,
    FUND_FINANCIALS_FILE,
)

logger = logging.getLogger(__name__)

# --- net-FV concepts (lowercase local names), preferred then fallback ---
_ASSET_PREF = "derivativefairvalueofderivativeasset"
_LIAB_PREF = "derivativefairvalueofderivativeliability"
_ASSET_FALLBACK = "derivativeassets"
_LIAB_FALLBACK = "derivativeliabilities"
# Exact-match net-FV concepts we read (avoid substring collisions like
# DerivativeAssetsAndLiabilityFairValue... or *TextBlock).
_NET_CONCEPTS = {_ASSET_PREF, _LIAB_PREF, _ASSET_FALLBACK, _LIAB_FALLBACK}

_DERIV_RISK_AXIS_RE = re.compile(r"derivativeinstrumentrisk", re.I)
_DESIGNATION_RE = re.compile(
    r"designatedashedginginstrument|fairvaluehedging|cashflowhedging|hedgeditems",
    re.I,
)
# Member text naming the BDC's OWN debt (financing hedge).
_OWN_DEBT_RE = re.compile(
    r"note|bond|debenture|facility|revolver|borrowing|seniorunsecured|term.?loan",
    re.I,
)

# Canonical instrument type from a DerivativeInstrumentRiskAxis member local name.
# IMPORTANT: only applied to members on the derivative-risk axis -- do NOT match
# InvestmentInterestRateFloorAxis (a loan attribute, not a floor derivative).
_TYPE_RULES = [
    ("TOTAL_RETURN_SWAP", re.compile(r"totalreturnswap", re.I)),
    ("INTEREST_RATE_SWAP", re.compile(r"interestrateswap", re.I)),
    ("INTEREST_RATE_FLOOR", re.compile(r"interestratefloor", re.I)),
    ("INTEREST_RATE_CAP_COLLAR", re.compile(r"interestrate(cap|collar)", re.I)),
    ("CURRENCY_SWAP", re.compile(r"currencyswap", re.I)),
    ("FX_FORWARD", re.compile(r"foreignexchangeforward|fxforward", re.I)),
    ("FX_CURRENCY_OTHER", re.compile(r"foreignexchange|foreigncurrency", re.I)),
    ("OPTION", re.compile(r"option", re.I)),
    ("WARRANT", re.compile(r"warrant", re.I)),
    ("FUTURE", re.compile(r"future", re.I)),
]

# Type prior -> role (before evidence upgrades / notional gate).
_HEDGE_PRIOR_TYPES = {
    "INTEREST_RATE_SWAP", "INTEREST_RATE_FLOOR",
    "INTEREST_RATE_CAP_COLLAR", "CURRENCY_SWAP",
}
_PORTFOLIO_PRIOR_TYPES = {
    "TOTAL_RETURN_SWAP", "FX_FORWARD", "FX_CURRENCY_OTHER",
    "OPTION", "WARRANT", "FUTURE",
}
_IR_FAMILY = {
    "INTEREST_RATE_SWAP", "INTEREST_RATE_FLOOR",
    "INTEREST_RATE_CAP_COLLAR", "CURRENCY_SWAP",
}

DERIVATIVE_COLUMNS = [
    "cik", "entity_name", "report_date", "derivative_type",
    "net_fv", "net_fv_source", "notional",
    "derivative_role", "role_confidence", "role_mechanism",
    "designated", "names_own_debt",
]
REVIEW_COLUMNS = [
    "cik", "report_date", "mechanism", "role_confidence",
    "net_fv", "notional", "evidence",
]


def _local_name(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _canon_type(member_local: str) -> Optional[str]:
    for name, pat in _TYPE_RULES:
        if pat.search(member_local):
            return name
    return None


def _num(text: Any) -> Optional[float]:
    try:
        return float(str(text).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_contexts(root: etree._Element) -> dict[str, dict]:
    """Map context id -> {end, deriv_type, designated, names_own_debt, is_entity}.

    `deriv_type` is the canonical type from the DerivativeInstrumentRiskAxis member
    (None if the context is not on that axis). `is_entity` is True when the context
    has no explicit/typed dimension at all (entity-level total).
    """
    contexts: dict[str, dict] = {}
    for ctx in root.iter():
        if _local_name(ctx.tag) != "context":
            continue
        cid = ctx.get("id", "")
        if not cid:
            continue
        end = ""
        deriv_type = None
        designated = False
        own_debt = False
        n_dims = 0
        for el in ctx.iter():
            ln = _local_name(el.tag)
            if ln in ("instant", "endDate"):
                end = (el.text or "").strip()
            elif ln in ("explicitMember", "typedMember"):
                n_dims += 1
                dim = el.get("dimension", "") or ""
                member = (el.text or "").strip()
                member_ln = _local_name(member)
                if _DERIV_RISK_AXIS_RE.search(dim):
                    t = _canon_type(member_ln)
                    if t and deriv_type is None:
                        deriv_type = t
                    if _OWN_DEBT_RE.search(member_ln):
                        own_debt = True
                if _DESIGNATION_RE.search(dim) or _DESIGNATION_RE.search(member_ln):
                    designated = True
        contexts[cid] = {
            "end": end,
            "deriv_type": deriv_type,
            "designated": designated,
            "names_own_debt": own_debt,
            "is_entity": n_dims == 0,
        }
    return contexts


def _extract_filing(root: etree._Element, report_date: str) -> dict:
    """Return per-type net FV/notional + entity-level net FV at report_date."""
    contexts = _parse_contexts(root)
    # per-type accumulators
    type_asset: dict[str, dict[str, float]] = {}   # type -> {pref, fallback}
    type_liab: dict[str, dict[str, float]] = {}
    type_notional: dict[str, float] = {}
    type_designated: set[str] = set()
    type_own_debt: set[str] = set()
    ent_asset: dict[str, float] = {}
    ent_liab: dict[str, float] = {}

    for el in root.iter():
        cref = el.get("contextRef")
        if not cref or cref not in contexts:
            continue
        info = contexts[cref]
        if info["end"] != report_date:
            continue
        nil = el.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        if nil and nil.lower() == "true":
            continue
        local = _local_name(el.tag).lower()
        val = _num(el.text)
        if val is None:
            continue
        t = info["deriv_type"]
        # net-FV concepts
        if local in _NET_CONCEPTS:
            is_asset = local in (_ASSET_PREF, _ASSET_FALLBACK)
            pref = "pref" if local in (_ASSET_PREF, _LIAB_PREF) else "fallback"
            if t is not None:
                tgt = type_asset if is_asset else type_liab
                tgt.setdefault(t, {}).setdefault(pref, 0.0)
                tgt[t][pref] += abs(val)
                if info["designated"]:
                    type_designated.add(t)
                if info["names_own_debt"]:
                    type_own_debt.add(t)
            elif info["is_entity"]:
                tgt = ent_asset if is_asset else ent_liab
                tgt[pref] = tgt.get(pref, 0.0) + abs(val)
        # notional (period-end; exclude averages)
        elif "notional" in local and "average" not in local and t is not None:
            type_notional[t] = type_notional.get(t, 0.0) + abs(val)
            if info["designated"]:
                type_designated.add(t)
            if info["names_own_debt"]:
                type_own_debt.add(t)

    def _net(asset: dict, liab: dict) -> Optional[float]:
        a = asset.get("pref", asset.get("fallback"))
        l = liab.get("pref", liab.get("fallback"))
        if a is None and l is None:
            return None
        return (a or 0.0) - (l or 0.0)

    per_type_net: dict[str, float] = {}
    for t in set(type_asset) | set(type_liab):
        n = _net(type_asset.get(t, {}), type_liab.get(t, {}))
        if n is not None:
            per_type_net[t] = n
    entity_net = _net(ent_asset, ent_liab)

    # any filing-level designation evidence (for IR types that don't co-tag it
    # on the risk-axis context)
    filing_designated = any(c["designated"] for c in contexts.values())

    return {
        "per_type_net": per_type_net,
        "type_notional": type_notional,
        "type_designated": type_designated,
        "type_own_debt": type_own_debt,
        "entity_net": entity_net,
        "filing_designated": filing_designated,
    }


def _classify_role(
    dtype: str,
    notional: float,
    designated: bool,
    own_debt: bool,
    ir_notional_ratio: Optional[float],
) -> tuple[str, float, str]:
    """Return (derivative_role, confidence, mechanism)."""
    if own_debt:
        return "financing_hedge", 0.95, "names_own_debt"
    if designated:
        return "financing_hedge", 0.97, "asc815_designated"
    if dtype == "TOTAL_RETURN_SWAP":
        return "portfolio", 0.85, "type_prior_trs"
    if dtype in _IR_FAMILY:
        if ir_notional_ratio is not None:
            if 0.1 <= ir_notional_ratio <= 1.5:
                return "financing_hedge", 0.90, "notional_ties_debt"
            if ir_notional_ratio > 1.5:
                return "uncertain", 0.50, "notional_exceeds_debt"
        return "financing_hedge", 0.70, "type_prior_ir"
    if dtype in ("FX_FORWARD", "FX_CURRENCY_OTHER"):
        return "portfolio", 0.70, "type_prior_fx"
    if dtype in ("OPTION", "WARRANT", "FUTURE"):
        return "portfolio", 0.65, "type_prior_optlike"
    return "uncertain", 0.40, "no_signal"


def extract_bdc_derivatives(
    filings_index: Optional[pd.DataFrame] = None,
    financials: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Extract + classify fund-level BDC derivatives from cached XBRL.

    Writes bdc_derivatives.csv and derivative_role_review.csv. Cache-only.
    """
    t0 = time.time()
    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.warning("No filings index at %s", BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame(columns=DERIVATIVE_COLUMNS)
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    # borrowings lookup for the notional-to-debt gate
    borrow: dict[tuple[str, str], float] = {}
    if financials is None and FUND_FINANCIALS_FILE.exists():
        financials = pd.read_csv(FUND_FINANCIALS_FILE, dtype=str)
    if financials is not None and not financials.empty:
        fin = financials.copy()
        fin["ciknorm"] = fin["cik"].astype(str).str.replace(r"[^0-9]", "", regex=True).str.zfill(10)
        for r in fin.itertuples():
            b = _num(getattr(r, "borrowings", None))
            if b and b > 0:
                borrow[(r.ciknorm, str(r.report_date))] = b

    cached = filings_index[
        filings_index["xbrl_download_status"].isin(["cached", "downloaded"])
        & filings_index["xbrl_local_path"].notna()
        & (filings_index["xbrl_local_path"] != "")
    ].copy()
    logger.info("Scanning %d cached XBRL files for derivatives", len(cached))

    rows: list[dict] = []
    review: list[dict] = []
    parsed = 0
    errors = 0
    for _, frow in cached.iterrows():
        xml_path = frow["xbrl_local_path"]
        report_date = str(frow.get("report_date", ""))
        cik = str(frow.get("cik", "")).replace(".0", "")
        cik10 = re.sub(r"[^0-9]", "", cik).zfill(10)
        entity = str(frow.get("entity_name", ""))
        # cheap prefilter: skip files with no derivative net-FV / risk axis
        try:
            with open(xml_path, "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        if (b"DerivativeInstrumentRiskAxis" not in blob
                and b"DerivativeAssets" not in blob
                and b"DerivativeLiabilities" not in blob
                and b"DerivativeFairValueOfDerivative" not in blob):
            continue
        try:
            root = etree.fromstring(blob)
            data = _extract_filing(root, report_date)
            parsed += 1
        except Exception as exc:  # pragma: no cover - defensive
            errors += 1
            if errors <= 5:
                logger.debug("derivative parse error %s: %s", xml_path, exc)
            continue

        per_type_net = data["per_type_net"]
        type_notional = data["type_notional"]
        all_types = set(per_type_net) | set(type_notional)
        if not all_types:
            continue

        # IR-family notional-to-debt ratio for the gate
        ir_notional = sum(v for t, v in type_notional.items() if t in _IR_FAMILY)
        debt = borrow.get((cik10, report_date))
        ir_ratio = (ir_notional / debt) if (debt and ir_notional > 0) else None

        # entity-level net allocation by notional when per-type net absent
        entity_net = data["entity_net"]
        have_per_type_net = len(per_type_net) > 0
        total_notional = sum(type_notional.values())

        for dtype in sorted(all_types):
            notional = type_notional.get(dtype, 0.0)
            designated = (dtype in data["type_designated"]
                          or (data["filing_designated"] and dtype in _IR_FAMILY))
            own_debt = dtype in data["type_own_debt"]
            role, conf, mech = _classify_role(
                dtype, notional, designated, own_debt, ir_ratio
            )
            # net FV: per-type if available; else allocate entity net by notional
            if dtype in per_type_net:
                net_fv = per_type_net[dtype]
                net_src = "per_type"
            elif (not have_per_type_net and entity_net is not None
                  and total_notional > 0 and notional > 0):
                net_fv = entity_net * (notional / total_notional)
                net_src = "entity_allocated"
            else:
                net_fv = None
                net_src = "none"
            rows.append({
                "cik": cik10, "entity_name": entity, "report_date": report_date,
                "derivative_type": dtype,
                "net_fv": net_fv, "net_fv_source": net_src,
                "notional": notional if notional else None,
                "derivative_role": role, "role_confidence": round(conf, 2),
                "role_mechanism": mech,
                "designated": designated, "names_own_debt": own_debt,
            })
            if role == "uncertain":
                review.append({
                    "cik": cik10, "report_date": report_date,
                    "mechanism": ("derivative_role_notional_contradiction"
                                  if mech == "notional_exceeds_debt"
                                  else "derivative_role_uncertain"),
                    "role_confidence": "medium" if mech == "notional_exceeds_debt" else "low",
                    "net_fv": net_fv,
                    "notional": notional if notional else None,
                    "evidence": f"type={dtype} mech={mech} ir_ratio="
                                f"{round(ir_ratio, 2) if ir_ratio is not None else 'na'}",
                })

    logger.info("Parsed %d derivative filings (%d errors); %d type-rows, %d review rows (%.1fs)",
                parsed, errors, len(rows), len(review), time.time() - t0)

    df = pd.DataFrame(rows, columns=DERIVATIVE_COLUMNS)
    # dedup: one row per (cik, report_date, type) -- prefer richest (per_type net)
    if not df.empty:
        df["_src_rank"] = df["net_fv_source"].map(
            {"per_type": 0, "entity_allocated": 1, "none": 2}).fillna(2)
        df = (df.sort_values(["cik", "report_date", "derivative_type", "_src_rank"])
                .drop_duplicates(["cik", "report_date", "derivative_type"], keep="first")
                .drop(columns="_src_rank"))
    df.to_csv(BDC_DERIVATIVES_FILE, index=False)

    review_df = pd.DataFrame(review, columns=REVIEW_COLUMNS)
    if not review_df.empty:
        review_df = review_df.drop_duplicates()
    review_df.to_csv(DERIVATIVE_ROLE_REVIEW_FILE, index=False)

    if not df.empty:
        n_ciks = df["cik"].nunique()
        by_role = df.groupby("derivative_role")["net_fv"].agg(
            lambda s: pd.to_numeric(s, errors="coerce").sum())
        logger.info("  derivatives: %d CIKs; net FV by role (M): %s",
                    n_ciks, {k: round(v / 1e6, 1) for k, v in by_role.items()})
    return df
