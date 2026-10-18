"""Class a filer's rows by the schedule section its page prints them under (opt-in per wrapper).

BCRED prints its CLO tranches under 'Structured Finance Obligations' (from 2024-09-30 split into
'- Debt Instruments' and '- Equity Instruments'). The shared classifier reads the class from the
name: tranches whose vehicle name lacks 'CLO' (Octagon 55, CIFC Funding, Balboa Bay Loan Funding,
Magnetite XXXII, RR 19 ...) were published as direct lending, and the subordinated notes and units
printed as equity instruments as loans (page sample of sandbox bcpc, 2026-10-18).

A wrapper opts in with ``dispatch.structured_credit_sections``::

    {"heading_re": "<regex: a top-level section heading>",
     "structured_re": "<regex: headings whose rows are structured credit>",
     "equity_re": "<regex: headings whose rows are structured equity tranches>"}

For every filing of the fund, each table row that carries a current-period fair-value fact is
assigned the last top-level heading printed above it ('(continued)' and the affiliation suffix
ignored; industry sub-headings do not match ``heading_re``). The key is the fact's contextRef, so
the reading is per position, not a name guess. Rows under ``structured_re`` become
STRUCTURED_CREDIT (asset_class STRUCTURED_CREDIT, no lien tier); rows under ``equity_re`` also
take asset_category EQUITY_COMMON. Nothing else is changed, and no fund without the key is read.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CONTINUED_RE = re.compile(r"(?i)\s*\(continued\)\s*$")
_AFFILIATION_SUFFIX_RE = re.compile(r"(?i)\s+-\s+(?:non-)?controlled\s*/\s*(?:non-)?affiliated(?:\s*\([^)]*\))?\s*$")
_VALUE_RE = re.compile(r"[$(]?\d[\d,]*(?:\.\d+)?%?\)?")


def section_settings(wrapper_dir: Path | None = None) -> dict[str, dict[str, re.Pattern[str]]]:
    """cik10 -> compiled {heading, structured, equity} for wrappers with dispatch.structured_credit_sections."""
    if wrapper_dir is None:
        from pipeline.config import OVERRIDES_DIR
        wrapper_dir = OVERRIDES_DIR / "bdc_xbrl_wrappers"
    result: dict[str, dict[str, re.Pattern[str]]] = {}
    for path in sorted(Path(wrapper_dir).glob("*.json")) if Path(wrapper_dir).exists() else []:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        spec = raw.get("dispatch", {}).get("structured_credit_sections")
        if not spec:
            continue
        result[str(raw["cik"]).zfill(10)] = {
            "heading": re.compile(spec["heading_re"]),
            "structured": re.compile(spec["structured_re"]),
            "equity": re.compile(spec["equity_re"]) if spec.get("equity_re") else None,
        }
    return result


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace(" ", " ")).strip()


def _cells(tr) -> list[str]:
    out = []
    for td in tr:
        if _local(td.tag) in ("td", "th"):
            text = _norm("".join(td.itertext()))
            if text:
                out.append(text)
    return out


@lru_cache(maxsize=256)
def sections_of_filing(html_path: str, report_date: str, heading_pattern: str) -> dict[str, str]:
    """contextRef -> printed top-level heading for the current-period fair-value facts of one filing."""
    from lxml import etree
    heading_re = re.compile(heading_pattern)
    root = etree.parse(html_path).getroot()
    instant: dict[str, str] = {}
    for el in root.iter():
        if _local(el.tag) == "context":
            for sub in el.iter():
                if _local(sub.tag) == "instant":
                    instant[el.get("id")] = _norm(sub.text)
    result: dict[str, str] = {}
    section = ""
    for tr in root.iter():
        if _local(tr.tag) != "tr":
            continue
        cells = _cells(tr)
        if not cells:
            continue
        if len(cells) == 1 and not _VALUE_RE.search(cells[0]):
            label = _AFFILIATION_SUFFIX_RE.sub("", _CONTINUED_RE.sub("", cells[0])).strip()
            if heading_re.search(label):
                section = label
            continue
        for el in tr.iter():
            if _local(el.tag) == "nonFraction" and (el.get("name") or "").rsplit(":", 1)[-1] == "InvestmentOwnedAtFairValue" \
                    and instant.get(el.get("contextRef")) == report_date:
                result.setdefault(el.get("contextRef"), section)
                break
    return result


def apply_structured_sections(df: pd.DataFrame, settings: dict | None = None, html_dir: Path | None = None) -> pd.DataFrame:
    """Re-class the opted-in funds' rows printed under structured-credit sections (see module doc)."""
    settings = section_settings() if settings is None else settings
    if not settings or df.empty:
        return df
    if html_dir is None:
        from pipeline.config import BDC_HTML_CACHE_DIR
        html_dir = BDC_HTML_CACHE_DIR
    cik10 = df["cik"].astype(str).str.strip().str.zfill(10)
    for cik, spec in settings.items():
        rows = df.index[(cik10 == cik) & (df["source"].astype(str) == "bdc")]
        if len(rows) == 0:
            continue
        heading = pd.Series("", index=rows, dtype="object")
        part = df.loc[rows, ["accession_number", "report_date", "src_context_id"]].astype(str)
        for (acc, rd), grp in part.groupby(["accession_number", "report_date"]):
            path = Path(html_dir) / cik.lstrip("0") / (acc.replace("-", "") + ".html")
            if not path.exists():
                logger.warning("printed sections: %s %s has no cached page; rows left as classed", cik, acc)
                continue
            found = sections_of_filing(str(path), str(rd)[:10], spec["heading"].pattern)
            heading.loc[grp.index] = grp["src_context_id"].str.strip().map(found).fillna("")
        structured = heading.map(lambda h: bool(h) and bool(spec["structured"].search(h)))
        equity = heading.map(lambda h: bool(h) and spec["equity"] is not None and bool(spec["equity"].search(h)))
        s_idx = structured[structured].index
        changed_class = int((df.loc[s_idx, "index_classification"].astype(str) != "STRUCTURED_CREDIT").sum())
        df.loc[s_idx, "index_classification"] = "STRUCTURED_CREDIT"
        df.loc[s_idx, "asset_class"] = "STRUCTURED_CREDIT"
        if "lien_position" in df.columns:
            df.loc[s_idx, "lien_position"] = None
        e_idx = equity[equity & structured].index
        changed_cat = int((df.loc[e_idx, "asset_category"].astype(str) != "EQUITY_COMMON").sum())
        df.loc[e_idx, "asset_category"] = "EQUITY_COMMON"
        # An equity tranche's 'Par Amount/Units' figure is tagged InvestmentOwnedBalanceShares; the
        # staging step moved it to principal_amount (src_transforms 'principal_amount:from_shares_tag')
        # because the row read as a loan. As an equity row it is also the unit count: publish it there
        # too, from the same tag, where no count is published (principal is left as it is).
        units_filled = 0
        if "shares_held" in df.columns and "src_transforms" in df.columns and len(e_idx):
            from_tag = df.loc[e_idx, "src_transforms"].astype(str).str.contains("principal_amount:from_shares_tag", regex=False)
            no_units = pd.to_numeric(df.loc[e_idx, "shares_held"], errors="coerce").isna()
            par = pd.to_numeric(df.loc[e_idx, "principal_amount"], errors="coerce")
            fill = from_tag & no_units & par.notna()
            idx = fill[fill].index
            df.loc[idx, "shares_held"] = par[fill]
            units_filled = len(idx)
        logger.info("Printed sections %s: %d rows under structured headings (%d re-classed), %d equity tranches "
                    "(%d to EQUITY_COMMON, %d unit counts from the shares tag), %d rows with no heading read", cik,
                    len(s_idx), changed_class, len(e_idx), changed_cat, units_filled, int((heading == "").sum()))
    return df
