"""CLI wrapper for HTML-vs-XBRL cross-validation.

Usage:
    python scripts/validate_html_xbrl.py --download     # Download HTML for XBRL-era filings
    python scripts/validate_html_xbrl.py --run           # Run validation (assumes HTML cached)
    python scripts/validate_html_xbrl.py --download --run  # Both
    python scripts/validate_html_xbrl.py --run --ciks 1287750,1803498  # Specific CIKs
"""

import argparse
import logging
import sys

from pipeline.validate_html_extraction import validate_all


def main():
    parser = argparse.ArgumentParser(
        description="Cross-validate HTML template extraction against XBRL data"
    )
    parser.add_argument(
        "--download", action="store_true",
        help="Download HTML primary documents for XBRL-era filings",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Run position-level cross-validation",
    )
    parser.add_argument(
        "--ciks", type=str, default=None,
        help="Comma-separated CIKs to validate (default: all template CIKs)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if not args.download and not args.run:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    ciks = None
    if args.ciks:
        ciks = {c.strip() for c in args.ciks.split(",")}

    df = validate_all(download=args.download, ciks=ciks)

    if df.empty:
        print("No results produced.")
        sys.exit(1)

    print(f"\nResults: {len(df)} filings compared across {df['cik'].nunique()} CIKs")


if __name__ == "__main__":
    main()
