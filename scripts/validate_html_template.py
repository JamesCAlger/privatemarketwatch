"""CLI wrapper for HTML template validation.

Usage::

    python -m scripts.validate_html_template --cik 1287750
    python -m scripts.validate_html_template --all
"""

import argparse
import logging

from pipeline.validate_html_template import (
    _print_cik_report,
    validate_all,
    validate_cik,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Validate HTML template extraction against companyfacts + carry rates"
    )
    parser.add_argument("--cik", help="Validate a single CIK")
    parser.add_argument("--all", action="store_true", help="Validate all template CIKs")
    args = parser.parse_args()

    if args.cik:
        result = validate_cik(args.cik)
        _print_cik_report(result)
    elif args.all:
        validate_all()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
