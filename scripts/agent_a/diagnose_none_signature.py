"""Agent A diagnostic: summarize rows still landing in the '(none)' signature.

Cache-only. This is a parent-side diagnostic for remediation prompts: it applies the
chosen anchor vocabulary to all current-period rows for one CIK and writes bounded
residual summaries under data/output/agent_a/quarter/<quarter>/diagnostics/.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pipeline import config
from pipeline.identifier_rate import normalize_identifier_text
from pipeline.identifier_signature import keyword_signature, load_anchors


_NONE_SIGNATURE = "(none)"
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_WS_RE = re.compile(r"\s+")


def proposal_anchor_path(cik: str) -> Path:
    return config.OUTPUT_DIR / "agent_a" / "proposals" / f"{cik}.anchors.json"


def load_anchor_spec(path: Path):
    spec = json.loads(path.read_text(encoding="utf-8"))
    return load_anchor_spec_from_dict(spec)


def load_anchor_spec_from_dict(spec: dict):
    return [(a["label"], re.compile(a["regex"], re.I)) for a in spec["anchors"]]


def load_selected_anchors(cik: str, staged: bool):
    if staged:
        path = proposal_anchor_path(cik)
        if not path.exists():
            raise FileNotFoundError(f"missing staged anchor proposal: {path}")
        return load_anchor_spec(path)
    return load_anchors(cik)


def residual_family(identifier: str) -> str:
    """Coarse, human-reviewable family label for residual none rows.

    These labels are diagnostics only. They deliberately require acquisition-date context
    for equity/warrant families so broad subtotal text such as "Common Equity (5% of
    class)" is not presented as an anchor-ready position pattern.
    """
    s = normalize_identifier_text(identifier or "")
    if re.search(r"\bCLO\s+Subordinated\s+Notes\b", s, re.I):
        return "clo_subordinated_notes"
    if re.search(r"\bCommon\s+Equity\b.*\b(?:Initial\s+)?Acquisition\s+Date\b", s, re.I):
        return "common_equity_acquisition_date"
    if re.search(r"\bCommon\s+Stock\b.*\bInitial\s+Acquisition\s+Date\b", s, re.I):
        return "common_stock_initial_acquisition_date"
    if re.search(r"\bWarrants?\b.*\bInitial\s+Acquisition\s+Date\b", s, re.I):
        if re.search(r"\bSPAC\b|\bDe-SPAC\b", s, re.I):
            return "spac_warrants_initial_acquisition_date"
        return "warrants_initial_acquisition_date"
    compact = _DATE_RE.sub("<DATE>", s)
    compact = _NUM_RE.sub("<NUM>", compact)
    compact = _WS_RE.sub(" ", compact).strip()
    return compact[:120] or "(empty)"


def fetch_rows(cik: str, parquet_path: str) -> list[tuple[str, str]]:
    import duckdb

    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT CAST(report_date AS VARCHAR) rd,
               CAST(investment_identifier AS VARCHAR) ident
        FROM '{parquet_path}'
        WHERE CAST(cik AS VARCHAR) = '{cik}'
          AND investment_identifier IS NOT NULL
          AND CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
        ORDER BY rd, ident
        """
    ).fetchall()
    con.close()
    return rows


def build_diagnostic(rows: list[tuple[str, str]], anchors, examples_per_family: int = 5) -> tuple[list[dict], list[dict]]:
    quarter_totals: Counter = Counter()
    quarter_none: Counter = Counter()
    family_counts: Counter = Counter()
    family_quarters: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)

    for rd, ident in rows:
        quarter_totals[rd] += 1
        if keyword_signature(ident, anchors) != _NONE_SIGNATURE:
            continue
        quarter_none[rd] += 1
        family = residual_family(ident)
        family_counts[family] += 1
        family_quarters[family][rd] += 1
        if len(examples[family]) < examples_per_family:
            examples[family].append(ident[:400])

    quarter_rows = []
    for rd in sorted(quarter_totals):
        n = quarter_totals[rd]
        none = quarter_none[rd]
        quarter_rows.append({
            "quarter": rd,
            "n_rows": n,
            "none_rows": none,
            "none_pct": round(100.0 * none / n, 1) if n else 0.0,
        })

    family_rows = []
    for family, count in family_counts.most_common():
        family_rows.append({
            "family": family,
            "none_rows": count,
            "quarters": "|".join(
                f"{rd}:{family_quarters[family][rd]}" for rd in sorted(family_quarters[family])
            ),
            "examples": " || ".join(examples[family]),
        })
    return quarter_rows, family_rows


def write_outputs(
    cik: str,
    quarter: str,
    quarter_rows: list[dict],
    family_rows: list[dict],
    top: int,
) -> tuple[Path, Path]:
    out_dir = config.OUTPUT_DIR / "agent_a" / "quarter" / quarter / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{cik}_none_signature_residuals.csv"
    md_path = out_dir / f"{cik}_none_signature_residuals.md"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["family", "none_rows", "quarters", "examples"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(family_rows[:top])

    lines = [f"# Agent A none-signature residuals: {cik}", ""]
    lines.append("## Quarter Summary")
    lines.append("")
    lines.append("| quarter | rows | none_rows | none_pct |")
    lines.append("|---|---:|---:|---:|")
    for r in quarter_rows:
        lines.append(f"| {r['quarter']} | {r['n_rows']} | {r['none_rows']} | {r['none_pct']} |")
    lines.append("")
    lines.append("## Top Residual Families")
    lines.append("")
    for r in family_rows[:top]:
        lines.append(f"### {r['family']} ({r['none_rows']} rows)")
        lines.append(f"Quarters: {r['quarters']}")
        for ex in r["examples"].split(" || "):
            if ex:
                lines.append(f"- {ex}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cik", required=True)
    parser.add_argument("--quarter", required=True, help="Batch quarter for output directory")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--parquet", default=str(config.OUTPUT_DIR / "bdc_holdings.parquet"))
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--examples", type=int, default=5)
    args = parser.parse_args(argv)

    anchors = load_selected_anchors(args.cik, args.staged)
    rows = fetch_rows(args.cik, args.parquet)
    quarter_rows, family_rows = build_diagnostic(rows, anchors, examples_per_family=args.examples)
    csv_path, md_path = write_outputs(args.cik, args.quarter, quarter_rows, family_rows, args.top)
    total_none = sum(r["none_rows"] for r in quarter_rows)
    print(f"none-signature diagnostic {args.cik}: {total_none} residual row(s)")
    print(f"  csv: {csv_path}")
    print(f"  md:  {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
