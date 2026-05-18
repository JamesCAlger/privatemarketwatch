"""CLI helpers for the validation rule registry."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline import config
from pipeline.validation_rules import RULE_REGISTRY, _affected_outputs


CATALOG_PATH = Path("docs/validation_hardening/rule_catalog.md")


def _trend_by_rule(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    trend_path = Path(path or config.VALIDATION_RULES_TREND_FILE)
    if not trend_path.exists():
        return {}
    trend_df = pd.read_csv(trend_path, dtype=str).fillna("")
    if "rule_id" not in trend_df.columns:
        return {}
    return {
        str(row["rule_id"]): row.to_dict()
        for _, row in trend_df.sort_values("rule_id", kind="mergesort").iterrows()
    }


def generate_catalog(
    path: str | Path = CATALOG_PATH,
    trend_path: str | Path | None = None,
) -> Path:
    """Write a markdown catalog of registered validation rules."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trends = _trend_by_rule(trend_path)
    lines = [
        "# Validation Rule Catalog",
        "",
        "| Namespace | Rule ID | Category | Title | Severity | Promoted | Dependencies | Required tables | Affected outputs | Trend | Output artifact |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rule in RULE_REGISTRY.values():
        namespace = "".join(ch for ch in rule.rule_id if ch.isalpha())
        deps = ", ".join(rule.depends_on) if rule.depends_on else ""
        tables = ", ".join(rule.required_tables)
        affected_outputs = ", ".join(_affected_outputs(rule))
        trend_flag = trends.get(rule.rule_id, {}).get("trend_flag", "")
        artifact = "validation_rules_detail.csv"
        title = rule.title.replace("|", "\\|")
        lines.append(
            f"| {namespace} | {rule.rule_id} | {rule.category} | {title} | "
            f"{rule.severity} | {str(rule.promoted).lower()} | {deps} | "
            f"{tables} | {affected_outputs} | {trend_flag} | {artifact} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validation rules utilities")
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="Generate docs/validation_hardening/rule_catalog.md",
    )
    parser.add_argument(
        "--catalog-path",
        default=str(CATALOG_PATH),
        help="Catalog output path",
    )
    parser.add_argument(
        "--trend-path",
        default=None,
        help="Optional validation_rules_trend.csv path",
    )
    args = parser.parse_args()
    if args.catalog:
        path = generate_catalog(args.catalog_path, trend_path=args.trend_path)
        print(f"Wrote validation rule catalog: {path}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
