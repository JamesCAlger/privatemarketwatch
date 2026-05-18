"""CLI helpers for the validation rule registry."""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.validation_rules import RULE_REGISTRY


CATALOG_PATH = Path("docs/validation_hardening/rule_catalog.md")


def generate_catalog(path: str | Path = CATALOG_PATH) -> Path:
    """Write a markdown catalog of registered validation rules."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Validation Rule Catalog",
        "",
        "| Namespace | Rule ID | Category | Title | Severity | Promoted | Dependencies | Required tables | Output artifact |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rule in RULE_REGISTRY.values():
        namespace = "".join(ch for ch in rule.rule_id if ch.isalpha())
        deps = ", ".join(rule.depends_on) if rule.depends_on else ""
        tables = ", ".join(rule.required_tables)
        artifact = "validation_rules_detail.csv"
        title = rule.title.replace("|", "\\|")
        lines.append(
            f"| {namespace} | {rule.rule_id} | {rule.category} | {title} | "
            f"{rule.severity} | {str(rule.promoted).lower()} | {deps} | "
            f"{tables} | {artifact} |"
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
    args = parser.parse_args()
    if args.catalog:
        path = generate_catalog(args.catalog_path)
        print(f"Wrote validation rule catalog: {path}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
