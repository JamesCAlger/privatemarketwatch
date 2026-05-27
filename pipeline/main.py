"""Orchestrator — runs the full universe-building pipeline.

Usage:
    python -m pipeline.main
    python -m pipeline.main --exhaustive
    python pipeline/main.py
"""

import argparse
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pipeline.config import OUTPUT_DIR
from pipeline.edgar_client import EdgarClient
from pipeline.bdc_universe import build_bdc_universe
from pipeline.fund_universe import build_fund_universe
from pipeline.third_party import fetch_all_third_party_lists
from pipeline.merge import merge_universes


def _setup_logging() -> None:
    """Configure logging to console and file."""
    log_file = OUTPUT_DIR / "pipeline.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file), mode="w", encoding="utf-8"),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Private Markets Universe Builder — SEC EDGAR pipeline",
    )
    parser.add_argument(
        "--exhaustive",
        action="store_true",
        help="Run all 6 discovery methods for maximum fund coverage "
             "(slower, ~45-60 min first run). Default runs the fast subset.",
    )
    parser.add_argument(
        "--holdings",
        action="store_true",
        help="Download BDC 10-K/10-Q XBRL and extract investee holdings "
             "(~2-4 hours first run).",
    )
    parser.add_argument(
        "--ciks",
        nargs="+",
        help="Limit --holdings/--nport to specific CIKs (e.g. --ciks 1418076 1655050). "
             "Skips Steps 1-4 and runs holdings extraction only.",
    )
    parser.add_argument(
        "--nport",
        action="store_true",
        help="Extract N-PORT holdings for interval/tender offer funds "
             "(~30-60 min first run).",
    )
    parser.add_argument(
        "--nport-xml",
        action="store_true",
        help="Supplement N-PORT data with liquidity classification from raw XML "
             "(adds ~1-2 hrs).",
    )
    parser.add_argument(
        "--unified",
        action="store_true",
        help="Build unified private markets holdings from BDC + N-PORT data.",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Run LLM extraction of structured fields from BDC identifiers. "
             "Requires OPENAI_API_KEY in .env. Requires --unified or existing "
             "unified holdings.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation checks on unified holdings (spot-check, aggregate audit, "
             "coverage analysis). Requires --unified or existing unified holdings file.",
    )
    parser.add_argument(
        "--validate-rules",
        action="store_true",
        help="Run report-only V1 DuckDB validation rules over output CSV artifacts.",
    )
    parser.add_argument(
        "--validate-all",
        action="store_true",
        help="Run cached fund financial, holdings, and rule-registry validation.",
    )
    parser.add_argument(
        "--reconcile-full",
        action="store_true",
        help="Force BDC source-fact extraction and all source reconciliation CIK partitions.",
    )
    parser.add_argument(
        "--rules-category",
        nargs="+",
        choices=["PC", "IDX", "T", "S", "R", "XS", "F", "M", "RI"],
        help="Limit --validate-rules to one or more rule categories.",
    )
    parser.add_argument(
        "--llm-review",
        action="store_true",
        help="Run LLM-assisted classification on remaining UNCLASSIFIED holdings. "
             "Requires --unified or existing unified holdings file.",
    )
    parser.add_argument(
        "--llm-review-dry-run",
        action="store_true",
        help="Export LLM review candidates without calling the API.",
    )
    parser.add_argument(
        "--entities",
        action="store_true",
        help="Run entity resolution on unified holdings (name extraction, "
             "dedup, fuzzy clustering, cross-source linking).",
    )
    parser.add_argument(
        "--returns",
        action="store_true",
        help="Run position matching and index return computation. "
             "Requires --unified or existing unified holdings file.",
    )
    parser.add_argument(
        "--classify-gics",
        action="store_true",
        help="Run position-level GICS industry classification on unified holdings. "
             "Requires OPENAI_API_KEY for LLM phase.",
    )
    parser.add_argument(
        "--gics-web-search",
        type=int,
        nargs="?",
        const=5000,
        default=None,
        metavar="N",
        help="Reclassify top N unclassified companies using OpenAI web search. "
             "Default N=5000. Requires OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--extract-html",
        action="store_true",
        help="Extract pre-XBRL filings using per-CIK templates (no LLM, $0).",
    )
    parser.add_argument(
        "--financials",
        action="store_true",
        help="Build fund-level financials from companyfacts + N-PORT fund info.",
    )
    parser.add_argument(
        "--load-db",
        action="store_true",
        help="Load pipeline CSVs into Postgres (requires DATABASE_URL).",
    )
    parser.add_argument(
        "--export-frontend",
        action="store_true",
        help="Export aggregated JSON for the static Next.js frontend.",
    )
    parser.add_argument(
        "--llm-fund-validation",
        action="store_true",
        help="Run blind LLM validation of fund classification accuracy. "
             "Requires OPENAI_API_KEY in .env.",
    )
    parser.add_argument(
        "--classify-funds",
        action="store_true",
        help="Classify UNCLASSIFIED fund positions via LLM. Auto-applies "
             "PE/Credit/RE (high precision), writes HF/SC to review CSV. "
             "Requires OPENAI_API_KEY in .env.",
    )
    return parser.parse_args()


def _snapshot_outputs(logger: logging.Logger) -> Path | None:
    """Copy existing output CSVs/JSONs to a timestamped snapshot directory.

    Returns the snapshot directory path, or None if there was nothing to copy.
    """
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    snapshot_dir = OUTPUT_DIR.parent / "snapshots" / f"pre_run_{stamp}"
    sources = [
        p for p in OUTPUT_DIR.iterdir()
        if p.is_file() and p.suffix in (".csv", ".json")
    ]
    if not sources:
        logger.info("No existing output files to snapshot")
        return None
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for src in sources:
        shutil.copy2(src, snapshot_dir / src.name)
    logger.info(
        "Snapshot: %d files saved to %s", len(sources), snapshot_dir.name
    )
    return snapshot_dir


def _is_validate_only(args: argparse.Namespace) -> bool:
    return (
        args.validate
        and not args.exhaustive
        and not args.holdings
        and not args.ciks
        and not args.nport
        and not args.nport_xml
        and not args.unified
        and not args.extract
        and not args.validate_rules
        and not args.validate_all
        and not args.llm_review
        and not args.llm_review_dry_run
        and not args.entities
        and not args.returns
        and not args.classify_gics
        and args.gics_web_search is None
        and not args.extract_html
        and not args.financials
        and not args.load_db
        and not args.export_frontend
        and not args.llm_fund_validation
        and not args.classify_funds
    )


def _is_validate_rules_only(args: argparse.Namespace) -> bool:
    return (
        args.validate_rules
        and not args.exhaustive
        and not args.holdings
        and not args.ciks
        and not args.nport
        and not args.nport_xml
        and not args.unified
        and not args.extract
        and not args.validate
        and not args.validate_all
        and not args.llm_review
        and not args.llm_review_dry_run
        and not args.entities
        and not args.returns
        and not args.classify_gics
        and args.gics_web_search is None
        and not args.extract_html
        and not args.financials
        and not args.load_db
        and not args.export_frontend
        and not args.llm_fund_validation
        and not args.classify_funds
    )


def _is_validate_all_only(args: argparse.Namespace) -> bool:
    return (
        args.validate_all
        and not args.exhaustive
        and not args.holdings
        and not args.ciks
        and not args.nport
        and not args.nport_xml
        and not args.unified
        and not args.extract
        and not args.validate
        and not args.validate_rules
        and not args.llm_review
        and not args.llm_review_dry_run
        and not args.entities
        and not args.returns
        and not args.classify_gics
        and args.gics_web_search is None
        and not args.extract_html
        and not args.financials
        and not args.load_db
        and not args.export_frontend
        and not args.llm_fund_validation
        and not args.classify_funds
    )


def _is_export_frontend_only(args: argparse.Namespace) -> bool:
    return (
        args.export_frontend
        and not args.exhaustive
        and not args.holdings
        and not args.ciks
        and not args.nport
        and not args.nport_xml
        and not args.unified
        and not args.extract
        and not args.validate
        and not args.validate_rules
        and not args.validate_all
        and not args.llm_review
        and not args.llm_review_dry_run
        and not args.entities
        and not args.returns
        and not args.classify_gics
        and args.gics_web_search is None
        and not args.extract_html
        and not args.financials
        and not args.load_db
        and not args.llm_fund_validation
        and not args.classify_funds
    )


def _run_cached_validation(logger: logging.Logger, reconcile_full: bool = False) -> None:
    import pandas as pd

    unified_path = OUTPUT_DIR / "private_markets_holdings.csv"
    if not unified_path.exists():
        logger.error("Unified holdings file not found: %s", unified_path)
        return

    t = time.time()
    unified_df = pd.read_csv(unified_path, dtype=str)
    logger.info("Loaded cached unified holdings: %d rows", len(unified_df))

    from pipeline.validate_holdings import validate_holdings
    reports = validate_holdings(unified_df=unified_df, reconcile_full=reconcile_full)
    for name, report_df in reports.items():
        logger.info("  Validation '%s': %d rows", name, len(report_df))

    from pipeline.validate_fund_financials import validate_fund_financials
    fund_reports = validate_fund_financials(holdings_df=unified_df)
    for name, report_df in fund_reports.items():
        logger.info("  Fund validation '%s': %d rows", name, len(report_df))

    logger.info("Cached validation completed in %.1f s", time.time() - t)


def _status_from_reports(reports: dict[str, object]) -> str:
    from pipeline.validation_status import status_from_reports

    return status_from_reports(reports)


def _log_validation_summary(logger: logging.Logger, rows: list[tuple[str, str, int]]) -> None:
    from pipeline.validation_status import normalize_status

    logger.info("Validation summary:")
    logger.info("  %-28s %-8s %10s", "check", "status", "rows")
    for name, status, count in rows:
        logger.info("  %-28s %-8s %10d", name, normalize_status(status), count)


def _run_validate_all(logger: logging.Logger, reconcile_full: bool = False) -> None:
    import pandas as pd

    unified_path = OUTPUT_DIR / "private_markets_holdings.csv"
    if not unified_path.exists():
        logger.error("Unified holdings file not found: %s", unified_path)
        return
    t = time.time()
    unified_df = pd.read_csv(unified_path, dtype=str)
    rows: list[tuple[str, str, int]] = []

    from pipeline.validate_fund_financials import validate_fund_financials
    fund_reports = validate_fund_financials(holdings_df=unified_df)
    fund_count = sum(len(df) for df in fund_reports.values())
    rows.append(("fund_financials", _status_from_reports(fund_reports), fund_count))

    from pipeline.validate_holdings import validate_holdings
    holding_reports = validate_holdings(unified_df=unified_df, reconcile_full=reconcile_full)
    holding_count = sum(len(df) for df in holding_reports.values())
    rows.append(("holdings", _status_from_reports(holding_reports), holding_count))

    from pipeline.validation_rules import run_all
    from pipeline.validation_status import status_from_rule_aggregate

    aggregate_df, detail_df = run_all()
    rules_status = status_from_rule_aggregate(aggregate_df)
    rows.append(("validation_rules", rules_status, len(detail_df)))
    _log_validation_summary(logger, rows)
    logger.info("Validate-all completed in %.1f s", time.time() - t)


def main() -> None:
    args = _parse_args()
    _setup_logging()
    logger = logging.getLogger("pipeline.main")

    # --ciks implies --holdings/--nport and skips Steps 1-4
    if args.ciks:
        if not args.nport:
            args.holdings = True

    logger.info("=" * 70)
    logger.info("PRIVATE MARKETS UNIVERSE BUILDER — STARTING")
    mode_parts = []
    if args.exhaustive:
        mode_parts.append("EXHAUSTIVE")
    if args.holdings:
        mode_parts.append("HOLDINGS")
    if args.nport:
        mode_parts.append("NPORT")
    if args.nport_xml:
        mode_parts.append("NPORT-XML")
    if args.unified:
        mode_parts.append("UNIFIED")
    if args.extract:
        mode_parts.append("EXTRACT")
    if args.validate:
        mode_parts.append("VALIDATE")
    if args.validate_rules:
        if args.rules_category:
            mode_parts.append("VALIDATE-RULES:" + ",".join(args.rules_category))
        else:
            mode_parts.append("VALIDATE-RULES")
    if args.validate_all:
        mode_parts.append("VALIDATE-ALL")
    if args.reconcile_full:
        mode_parts.append("RECONCILE-FULL")
    if args.llm_review:
        mode_parts.append("LLM-REVIEW")
    if args.llm_review_dry_run:
        mode_parts.append("LLM-REVIEW-DRY-RUN")
    if args.entities:
        mode_parts.append("ENTITIES")
    if args.extract_html:
        mode_parts.append("EXTRACT-HTML")
    if args.financials:
        mode_parts.append("FINANCIALS")
    if args.returns:
        mode_parts.append("RETURNS")
    if args.load_db:
        mode_parts.append("LOAD-DB")
    if args.export_frontend:
        mode_parts.append("EXPORT-FRONTEND")
    if args.llm_fund_validation:
        mode_parts.append("LLM-FUND-VALIDATION")
    if args.classify_funds:
        mode_parts.append("CLASSIFY-FUNDS")
    if args.ciks:
        mode_parts.append(f"CIKs: {', '.join(args.ciks)}")
    logger.info("  Mode: %s", " + ".join(mode_parts) if mode_parts else "FAST")
    logger.info("=" * 70)
    t0 = time.time()

    # Snapshot existing outputs before any overwrites (skip read-only modes)
    _read_only = (
        _is_validate_only(args)
        or _is_validate_rules_only(args)
        or _is_validate_all_only(args)
        or _is_export_frontend_only(args)
    )
    if not _read_only:
        _snapshot_outputs(logger)

    if _is_validate_only(args):
        _run_cached_validation(logger, reconcile_full=args.reconcile_full)
        total = time.time() - t0
        logger.info("=== Pipeline complete in %.1f s ===", total)
        return

    if _is_validate_rules_only(args):
        from pipeline.validation_rules import run_all

        aggregate_df, detail_df = run_all(categories=args.rules_category)
        logger.info(
            "Validation rules completed: %d aggregate rows, %d detail rows",
            len(aggregate_df),
            len(detail_df),
        )
        total = time.time() - t0
        logger.info("=== Pipeline complete in %.1f s ===", total)
        return

    if _is_validate_all_only(args):
        _run_validate_all(logger, reconcile_full=args.reconcile_full)
        total = time.time() - t0
        logger.info("=== Pipeline complete in %.1f s ===", total)
        return

    if _is_export_frontend_only(args):
        from pipeline.export_frontend import export_all as export_frontend

        export_frontend()
        total = time.time() - t0
        logger.info("=== Pipeline complete in %.1f s ===", total)
        return

    client = EdgarClient()

    bdc_df = None
    combined = None

    if not args.ciks:
        # ── Step 1: Build BDC universe ──
        logger.info("")
        t1 = time.time()
        try:
            bdc_df = build_bdc_universe(client)
        except Exception as exc:
            logger.error("BDC universe build failed: %s", exc, exc_info=True)
        logger.info("BDC step completed in %.1f s", time.time() - t1)

        # ── Step 2: Build fund universe (interval / tender offer) ──
        logger.info("")
        t2 = time.time()
        try:
            fund_df = build_fund_universe(client, exhaustive=args.exhaustive)
        except Exception as exc:
            logger.error("Fund universe build failed: %s", exc, exc_info=True)
            fund_df = None
        logger.info("Fund step completed in %.1f s", time.time() - t2)

        # ── Step 3: Fetch third-party lists ──
        logger.info("")
        t3 = time.time()
        try:
            third_party = fetch_all_third_party_lists(client)
        except Exception as exc:
            logger.error("Third-party fetch failed: %s", exc, exc_info=True)
            third_party = {}
        logger.info("Third-party step completed in %.1f s", time.time() - t3)

        # ── Step 4: Merge and validate ──
        logger.info("")
        t4 = time.time()
        try:
            combined = merge_universes(bdc_df, fund_df, third_party)
        except Exception as exc:
            logger.error("Merge failed: %s", exc, exc_info=True)
        logger.info("Merge step completed in %.1f s", time.time() - t4)
    else:
        logger.info("")
        logger.info("Skipping Steps 1-4 (--ciks mode)")

    # ── Step 5: BDC holdings extraction (optional) ──
    holdings_df = None
    if args.holdings:
        logger.info("")
        t5 = time.time()
        try:
            from pipeline.bdc_filings import extract_bdc_holdings
            import pandas as pd

            if args.ciks:
                # Build a minimal universe from the provided CIKs
                bdc_subset = pd.DataFrame({"cik": args.ciks})
                holdings_df = extract_bdc_holdings(client, bdc_subset)
            else:
                holdings_df = extract_bdc_holdings(client, bdc_df)
        except Exception as exc:
            logger.error("BDC holdings extraction failed: %s", exc, exc_info=True)
        logger.info("Holdings step completed in %.1f s", time.time() - t5)

    # ── Step 6: N-PORT holdings extraction (optional) ──
    nport_holdings_df = None
    if args.nport:
        logger.info("")
        t6 = time.time()
        try:
            from pipeline.nport_holdings import extract_nport_holdings
            import pandas as pd

            if args.ciks:
                # Build a minimal universe from the provided CIKs
                fund_subset = pd.DataFrame({"cik": args.ciks})
                nport_holdings_df = extract_nport_holdings(
                    client, fund_subset,
                    include_xml_supplement=args.nport_xml,
                )
            else:
                nport_holdings_df = extract_nport_holdings(
                    client,
                    include_xml_supplement=args.nport_xml,
                )
        except Exception as exc:
            logger.error("N-PORT holdings extraction failed: %s", exc, exc_info=True)
        logger.info("N-PORT step completed in %.1f s", time.time() - t6)

    # ── Step 6b: HTML template extraction (optional) ──
    if args.extract_html:
        logger.info("")
        t6b = time.time()
        try:
            from pipeline.html_extract import extract_all_html

            cik_filter = args.ciks if args.ciks else None
            extract_all_html(
                client=client,
                cik_filter=cik_filter,
            )
        except Exception as exc:
            logger.error("HTML template extraction failed: %s", exc,
                         exc_info=True)
        logger.info("HTML template extraction step completed in %.1f s",
                     time.time() - t6b)

    # ── Step 7: Unified private markets holdings (optional) ──
    unified_df = None
    if args.unified:
        logger.info("")
        t7 = time.time()
        try:
            from pipeline.unified_holdings import build_unified_holdings

            unified_df = build_unified_holdings(
                bdc_df=holdings_df,
                nport_df=nport_holdings_df,
            )
        except Exception as exc:
            logger.error("Unified holdings build failed: %s", exc, exc_info=True)
        logger.info("Unified holdings step completed in %.1f s", time.time() - t7)

    # ── Step 7b: Fund financials (optional) ──
    if args.financials:
        logger.info("")
        t7b_fin = time.time()

        # N-CSR discovery + download + extraction (interval/tender funds)
        try:
            from pipeline.ncsr_financials import (
                build_ncsr_filings_index,
                download_ncsr_filings,
                extract_ncsr_financials,
            )
            import pandas as pd

            # Get interval/tender CIKs from universe
            ncsr_universe = None
            if combined is not None and not combined.empty:
                ncsr_universe = combined
            else:
                from pipeline.config import COMBINED_UNIVERSE_FILE
                if COMBINED_UNIVERSE_FILE.exists():
                    ncsr_universe = pd.read_csv(COMBINED_UNIVERSE_FILE, dtype=str)

            if ncsr_universe is not None and not ncsr_universe.empty:
                interval_tender = ncsr_universe[
                    ncsr_universe["vehicle_type"].isin(
                        ["interval_fund", "tender_offer_fund"]
                    )
                ]
                ncsr_ciks = interval_tender["cik"].dropna().unique().tolist()
                if ncsr_ciks:
                    ncsr_index = build_ncsr_filings_index(client, ncsr_ciks)
                    ncsr_index = download_ncsr_filings(client, ncsr_index)
                    extract_ncsr_financials(ncsr_index)
                else:
                    logger.info("No interval/tender CIKs for N-CSR extraction")
            else:
                logger.info("No universe available for N-CSR extraction")
        except Exception as exc:
            logger.error("N-CSR extraction failed: %s", exc, exc_info=True)

        try:
            from pipeline.fund_financials import build_fund_financials
            build_fund_financials(client=client)
        except Exception as exc:
            logger.error("Fund financials build failed: %s", exc,
                         exc_info=True)

        try:
            from pipeline.bdc_sector_breakdown import extract_bdc_sector_breakdown
            from pipeline.bdc_sector_reconciliation import (
                reconcile_bdc_sector_breakdown,
            )
            extract_bdc_sector_breakdown()
            reconcile_bdc_sector_breakdown()
        except Exception as exc:
            logger.error("BDC sector breakdown failed: %s", exc,
                         exc_info=True)
        logger.info("Fund financials step completed in %.1f s",
                     time.time() - t7b_fin)

    # ── Step 7c: LLM identifier extraction (optional) ──
    if args.extract:
        logger.info("")
        t7b = time.time()
        try:
            from pipeline.identifier_extraction import extract_identifiers
            unified_df = extract_identifiers(unified_df=unified_df)
            # Re-save with enriched fields
            unified_df.to_csv(OUTPUT_DIR / "private_markets_holdings.csv",
                              index=False)
        except Exception as exc:
            logger.error("Identifier extraction failed: %s", exc,
                         exc_info=True)
        logger.info("Identifier extraction step completed in %.1f s",
                     time.time() - t7b)

    # ── Step 7d: GICS industry classification (optional) ──
    if args.classify_gics:
        logger.info("")
        t7d = time.time()
        try:
            from pipeline.gics_classification import classify_gics
            unified_df = classify_gics(unified_df=unified_df)
        except Exception as exc:
            logger.error("GICS classification failed: %s", exc, exc_info=True)
        logger.info("GICS classification step completed in %.1f s",
                     time.time() - t7d)

    # ── Step 7e: GICS web search reclassification (optional) ──
    if args.gics_web_search is not None:
        logger.info("")
        t7e = time.time()
        try:
            from pipeline.gics_classification import reclassify_with_web_search
            ws_results = reclassify_with_web_search(
                n=args.gics_web_search, unified_df=unified_df
            )
            non_other = (ws_results["gics_sub_industry"] != "Other").sum() if not ws_results.empty else 0
            logger.info("Web search: %d/%d reclassified", non_other, len(ws_results))
            # Re-apply GICS to holdings from updated cache
            from pipeline.gics_classification import _apply_gics_to_holdings, _load_cache
            cache = _load_cache()
            unified_df = _apply_gics_to_holdings(unified_df, cache)
            unified_df.to_csv(OUTPUT_DIR / "private_markets_holdings.csv", index=False)
        except Exception as exc:
            logger.error("GICS web search failed: %s", exc, exc_info=True)
        logger.info("GICS web search step completed in %.1f s",
                     time.time() - t7e)

    # ── Step 8: Holdings validation (optional) ──
    reports = None
    if args.validate:
        logger.info("")
        t8 = time.time()
        try:
            from pipeline.validate_holdings import validate_holdings
            reports = validate_holdings(
                unified_df=unified_df,
                reconcile_full=args.reconcile_full,
            )
            for name, report_df in reports.items():
                logger.info("  Validation '%s': %d rows", name, len(report_df))
        except Exception as exc:
            logger.error("Holdings validation failed: %s", exc, exc_info=True)
        try:
            from pipeline.validate_fund_financials import validate_fund_financials
            fund_reports = validate_fund_financials(holdings_df=unified_df)
            for name, report_df in fund_reports.items():
                logger.info("  Fund validation '%s': %d rows", name, len(report_df))
        except Exception as exc:
            logger.error("Fund financials validation failed: %s", exc,
                         exc_info=True)
        logger.info("Validation step completed in %.1f s", time.time() - t8)

    if args.validate_all:
        logger.info("")
        try:
            _run_validate_all(logger, reconcile_full=args.reconcile_full)
        except Exception as exc:
            logger.error("Validate-all failed: %s", exc, exc_info=True)

    # ── Step 9: LLM-assisted review (optional) ──
    if args.llm_review or args.llm_review_dry_run:
        logger.info("")
        t9 = time.time()
        try:
            from pipeline.llm_review import run_llm_review
            unified_df = run_llm_review(
                unified_df=unified_df,
                aggregate_suspects=reports.get("aggregate_leaks") if reports else None,
                dry_run=args.llm_review_dry_run,
            )
        except Exception as exc:
            logger.error("LLM review failed: %s", exc, exc_info=True)
        logger.info("LLM review step completed in %.1f s", time.time() - t9)

    # ── Step 10: Entity resolution (optional) ──
    if args.entities:
        logger.info("")
        t10 = time.time()
        try:
            from pipeline.entity_resolution import build_entity_lookup
            build_entity_lookup()
        except Exception as exc:
            logger.error("Entity resolution failed: %s", exc, exc_info=True)
        logger.info("Entity resolution step completed in %.1f s", time.time() - t10)

    # ── Step 11: Position matching and index returns (optional) ──
    matches_df = None
    position_returns_df = None
    index_returns_df = None
    if args.returns:
        logger.info("")
        t11 = time.time()
        try:
            from pipeline.position_matching import (
                match_positions, assign_position_ids,
            )
            from pipeline.index_returns import compute_returns
            from pipeline.match_reconciliation import (
                build_position_match_reconciliation,
            )

            matches_df = match_positions(unified_df=unified_df)

            # Assign stable position IDs and re-save enriched files
            if unified_df is None:
                import pandas as _pd
                unified_df = _pd.read_csv(
                    OUTPUT_DIR / "private_markets_holdings.csv", dtype=str,
                )
            unified_df, matches_df = assign_position_ids(
                unified_df, matches_df,
            )
            # Re-save unified holdings with position_id populated
            unified_df.to_csv(
                OUTPUT_DIR / "private_markets_holdings.csv", index=False,
            )
            # Re-save matches with position_id column
            matches_df.to_csv(
                OUTPUT_DIR / "position_matches.csv", index=False,
            )
            build_position_match_reconciliation(
                holdings_df=unified_df,
                matches_df=matches_df,
            )

            # Extract fund-level income and compute fee uplift
            from pipeline.bdc_fund_income import extract_bdc_fund_income
            from pipeline.fee_uplift import compute_fee_uplift

            fund_income_df = extract_bdc_fund_income()
            fee_uplift_df = compute_fee_uplift(
                fund_income_df=fund_income_df,
                unified_df=unified_df,
            )

            position_returns_df, index_returns_df = compute_returns(
                matches_df=matches_df,
                fee_uplift_df=fee_uplift_df,
            )
        except Exception as exc:
            logger.error("Returns computation failed: %s", exc, exc_info=True)
        logger.info("Returns step completed in %.1f s", time.time() - t11)

    # ── Step 12: Load into Postgres (optional) ──
    if args.load_db:
        logger.info("")
        t12 = time.time()
        try:
            from pipeline.db import load_all
            load_all()
        except Exception as exc:
            logger.error("Database load failed: %s", exc, exc_info=True)
        logger.info("Database load step completed in %.1f s", time.time() - t12)

    # ── Step 12b: LLM fund classification validation (optional) ──
    if args.llm_fund_validation:
        logger.info("")
        t12b = time.time()
        try:
            from pipeline.llm_fund_validation import run_fund_validation
            run_fund_validation()
        except Exception as exc:
            logger.error("LLM fund validation failed: %s", exc,
                         exc_info=True)
        logger.info("LLM fund validation step completed in %.1f s",
                     time.time() - t12b)

    # ── Step 12c: Classify unclassified fund positions (optional) ──
    if args.classify_funds:
        logger.info("")
        t12c = time.time()
        try:
            from pipeline.llm_fund_validation import classify_unclassified_funds
            classify_unclassified_funds()
        except Exception as exc:
            logger.error("Fund classification failed: %s", exc,
                         exc_info=True)
        logger.info("Fund classification step completed in %.1f s",
                     time.time() - t12c)

    # ── Step 13: Export frontend JSON (optional) ──
    if args.export_frontend:
        logger.info("")
        t13 = time.time()
        try:
            from pipeline.export_frontend import export_all as export_frontend
            export_frontend()
        except Exception as exc:
            logger.error("Frontend export failed: %s", exc, exc_info=True)
        logger.info("Frontend export step completed in %.1f s",
                     time.time() - t13)

    validation_rules_aggregate_df = None
    validation_rules_detail_df = None
    if args.validate_rules:
        logger.info("")
        t14 = time.time()
        try:
            from pipeline.validation_rules import run_all

            validation_rules_aggregate_df, validation_rules_detail_df = run_all(
                categories=args.rules_category,
            )
            logger.info(
                "Validation rules: %d aggregate rows, %d detail rows",
                len(validation_rules_aggregate_df),
                len(validation_rules_detail_df),
            )
        except Exception as exc:
            logger.error("Validation rules failed: %s", exc, exc_info=True)
        logger.info("Validation rules step completed in %.1f s", time.time() - t14)

    # ── Summary ──
    total_time = time.time() - t0
    logger.info("")
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE — %.1f s total", total_time)
    logger.info("=" * 70)

    if combined is not None and not combined.empty:
        logger.info("Total entities: %d", len(combined))
        logger.info("  BDCs: %d", (combined["vehicle_type"] == "bdc").sum())
        logger.info("  Interval funds: %d",
                     (combined["vehicle_type"] == "interval_fund").sum())
        logger.info("  Tender offer funds: %d",
                     (combined["vehicle_type"] == "tender_offer_fund").sum())
        logger.info("  Other/unknown: %d",
                     (~combined["vehicle_type"].isin(
                         ["bdc", "interval_fund", "tender_offer_fund"]
                     )).sum())

        # Verify every entity has at least one discovery method
        no_method = combined[
            combined["discovery_methods"].isna()
            | (combined["discovery_methods"] == "")
            | (combined["discovery_methods"] == "unknown")
        ]
        if not no_method.empty:
            logger.warning(
                "%d entities have no discovery method — investigate",
                len(no_method),
            )

        # Check for well-known entities
        well_known = [
            "ares capital", "blue owl", "fs kkr",
            "pimco flexible credit", "apollo credit",
        ]
        found_names = combined["entity_name"].str.lower().tolist()
        for name in well_known:
            if any(name in fn for fn in found_names if isinstance(fn, str)):
                logger.info("  Spot-check PASS: '%s' found", name)
            else:
                logger.info("  Spot-check NOTE: '%s' not found (may need review)", name)
    elif not args.ciks:
        logger.warning("No combined universe produced — check errors above")

    if holdings_df is not None and not holdings_df.empty:
        logger.info("  BDC holdings records: %d", len(holdings_df))
        if "cik" in holdings_df.columns:
            logger.info("  BDCs with holdings: %d", holdings_df["cik"].nunique())

    if nport_holdings_df is not None and not nport_holdings_df.empty:
        logger.info("  N-PORT holdings records: %d", len(nport_holdings_df))
        if "cik" in nport_holdings_df.columns:
            logger.info("  Funds with N-PORT holdings: %d",
                         nport_holdings_df["cik"].nunique())
        if "quarter" in nport_holdings_df.columns:
            logger.info("  N-PORT quarters: %d",
                         nport_holdings_df["quarter"].nunique())

    if unified_df is not None and not unified_df.empty:
        logger.info("  Unified holdings records: %d", len(unified_df))

    if matches_df is not None and not matches_df.empty:
        logger.info("  Position matches: %d", len(matches_df))
    if position_returns_df is not None and not position_returns_df.empty:
        logger.info("  Position returns: %d", len(position_returns_df))
    if index_returns_df is not None and not index_returns_df.empty:
        logger.info("  Index return quarters: %d", len(index_returns_df))
    if validation_rules_aggregate_df is not None:
        logger.info("  Validation rule rows: %d aggregate, %d detail",
                    len(validation_rules_aggregate_df),
                    len(validation_rules_detail_df)
                    if validation_rules_detail_df is not None else 0)

    logger.info("")
    logger.info("Output files:")
    output_files = []
    if not args.ciks:
        output_files.extend([
            OUTPUT_DIR / "bdc_universe.csv",
            OUTPUT_DIR / "fund_universe.csv",
            OUTPUT_DIR / "combined_universe.csv",
            OUTPUT_DIR / "combined_universe.json",
            OUTPUT_DIR / "validation_report.csv",
        ])
        if args.exhaustive:
            output_files.append(OUTPUT_DIR / "exhaustive_fund_universe.csv")
    if args.holdings:
        output_files.extend([
            OUTPUT_DIR / "bdc_filings_index.csv",
            OUTPUT_DIR / "bdc_holdings.csv",
        ])
    if args.nport:
        output_files.extend([
            OUTPUT_DIR / "nport_holdings.csv",
            OUTPUT_DIR / "nport_filings_index.csv",
            OUTPUT_DIR / "nport_fund_info.csv",
        ])
    if args.unified:
        output_files.append(OUTPUT_DIR / "private_markets_holdings.csv")
    if args.extract_html:
        output_files.append(OUTPUT_DIR / "html_extraction_holdings.csv")
    if args.financials:
        output_files.append(OUTPUT_DIR / "ncsr_filings_index.csv")
        output_files.append(OUTPUT_DIR / "ncsr_financials.csv")
        output_files.append(OUTPUT_DIR / "fund_financials.csv")
        output_files.append(OUTPUT_DIR / "bdc_sector_breakdown.csv")
    if args.extract:
        output_files.append(OUTPUT_DIR / "identifier_extraction_lookup.csv")
    if args.validate or args.validate_all:
        output_files.extend([
            OUTPUT_DIR / "holdings_validation_report.csv",
            OUTPUT_DIR / "holdings_spot_check.csv",
            OUTPUT_DIR / "holdings_coverage.csv",
            OUTPUT_DIR / "row_validation_issues.csv",
            OUTPUT_DIR / "validate_all_residual_summary.csv",
            OUTPUT_DIR / "column_quality_metrics.csv",
            OUTPUT_DIR / "data_quality_metrics.csv",
            OUTPUT_DIR / "fund_financials_validation_current.csv",
            OUTPUT_DIR / "fund_financials_quality_metrics.csv",
            OUTPUT_DIR / "fund_financials_cross_level.csv",
        ])
    if args.llm_review or args.llm_review_dry_run:
        output_files.extend([
            OUTPUT_DIR / "llm_review_candidates.csv",
            OUTPUT_DIR / "llm_review_lookup.csv",
        ])
    if args.entities:
        output_files.extend([
            OUTPUT_DIR / "entity_lookup.csv",
            OUTPUT_DIR / "entity_resolution_stats.csv",
        ])
    if args.returns:
        output_files.extend([
            OUTPUT_DIR / "position_matches.csv",
            OUTPUT_DIR / "position_returns.csv",
            OUTPUT_DIR / "index_returns.csv",
            OUTPUT_DIR / "bdc_fund_income.csv",
            OUTPUT_DIR / "fee_uplift.csv",
        ])
    if args.export_frontend:
        from pipeline.export_frontend import FRONTEND_DATA_DIR
        for jf in sorted(FRONTEND_DATA_DIR.glob("*.json")):
            output_files.append(jf)
    if args.validate_rules or args.validate_all:
        output_files.extend([
            OUTPUT_DIR / "validation_rules_aggregate.csv",
            OUTPUT_DIR / "validation_rules_detail.csv",
            OUTPUT_DIR / "validation_rules_history.csv",
            OUTPUT_DIR / "validation_rules_trend.csv",
        ])

    for path in output_files:
        if path.exists():
            size_kb = path.stat().st_size / 1024
            logger.info("  %s (%.1f KB)", path.name, size_kb)
        else:
            logger.info("  %s (not created)", path.name)


if __name__ == "__main__":
    main()
