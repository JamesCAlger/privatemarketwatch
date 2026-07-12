"""Rebuild unified holdings for a single CIK into a trial directory.

This is an iteration artifact for wrapper development, NOT a production
rebuild.  It reads from the existing production bdc_holdings and
nport_holdings, filters to the target CIK, and runs
build_unified_holdings() with trial output paths.

The wrapper staging logic is applied during the build, so changes to
wrapper JSON configs are reflected in the trial output.

Usage:
    python scripts/rebuild_unified_cik_trial.py --cik 0001849894
    python scripts/rebuild_unified_cik_trial.py --cik 0001572694 --match
"""

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("trial_rebuild")


def _normalize_cik(raw: str) -> str:
    digits = "".join(c for c in raw if c.isdigit())
    return digits.zfill(10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild unified holdings for one CIK into a trial directory.",
    )
    parser.add_argument("--cik", required=True, help="Target CIK (e.g. 0001849894)")
    parser.add_argument("--match", action="store_true",
                        help="Run position matching on trial output and show diagnostics")
    parser.add_argument("--corrections", default=None,
                        help="Dir of staged B2 correction-leaf JSONs; post-staging appliers "
                             "are applied to the trial holdings (writes *.corrected.csv).")
    parser.add_argument("--stage", type=int, default=None,
                        help="Restrict applied corrections to one precedence stage (1/2/3).")
    parser.add_argument("--wrapper-dir", default=None,
                        help="Trial wrapper dir overlaid on production (B2 wrapper-patch "
                             "corrections, e.g. subtotal_filter) before the build.")
    args = parser.parse_args(argv)

    # Overlay a trial wrapper (e.g. a staged subtotal_filter patch) before any staging runs.
    if args.wrapper_dir:
        from pipeline.bdc_xbrl_wrapper import reload_wrapper_specs
        reload_wrapper_specs(override_dir=Path(args.wrapper_dir))
        logger.info("Overlaid trial wrapper dir: %s", args.wrapper_dir)

    cik = _normalize_cik(args.cik)

    from pipeline.config import (
        BDC_HOLDINGS_FILE,
        BDC_HOLDINGS_PARQUET_FILE,
        NPORT_HOLDINGS_FILE,
        NPORT_HOLDINGS_PARQUET_FILE,
        OUTPUT_DIR,
        UNIFIED_HOLDINGS_FILE,
    )

    # Trial output directory
    trial_dir = OUTPUT_DIR / "bdc_xbrl_wrapper_trial" / cik / "unified_trial"
    trial_csv = trial_dir / f"private_markets_holdings.{cik}.csv"
    trial_orphan = trial_dir / f"universe_orphan_holdings.{cik}.csv"

    # --- Load and filter BDC holdings to one CIK ---
    bdc_path = (
        BDC_HOLDINGS_PARQUET_FILE
        if BDC_HOLDINGS_PARQUET_FILE.exists()
        else BDC_HOLDINGS_FILE
    )
    if not bdc_path.exists():
        logger.error("BDC holdings file not found: %s", bdc_path)
        return 1

    logger.info("Loading BDC holdings from %s", bdc_path.name)
    t0 = time.time()

    import duckdb

    con = duckdb.connect()
    safe_path = str(bdc_path).replace("\\", "/")
    read_fn = "read_parquet" if bdc_path.suffix == ".parquet" else "read_csv_auto"
    bdc_df = con.execute(
        f"""
        SELECT * FROM {read_fn}('{safe_path}')
        WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '{cik}'
        """
    ).fetchdf()
    con.close()

    logger.info(
        "BDC holdings for CIK %s: %d rows in %.1f s",
        cik, len(bdc_df), time.time() - t0,
    )
    if bdc_df.empty:
        logger.warning("No BDC holdings found for CIK %s", cik)

    # --- Load and filter N-PORT holdings to one CIK ---
    nport_path = (
        NPORT_HOLDINGS_PARQUET_FILE
        if NPORT_HOLDINGS_PARQUET_FILE.exists()
        else NPORT_HOLDINGS_FILE
    )

    nport_df = None
    if nport_path.exists():
        logger.info("Loading N-PORT holdings from %s", nport_path.name)
        t1 = time.time()

        con = duckdb.connect()
        safe_nport = str(nport_path).replace("\\", "/")
        read_fn_n = "read_parquet" if nport_path.suffix == ".parquet" else "read_csv_auto"
        nport_df = con.execute(
            f"""
            SELECT * FROM {read_fn_n}('{safe_nport}')
            WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '{cik}'
            """
        ).fetchdf()
        con.close()

        logger.info(
            "N-PORT holdings for CIK %s: %d rows in %.1f s",
            cik, len(nport_df), time.time() - t1,
        )
    else:
        logger.info("N-PORT holdings file not found; building BDC-only trial")

    # --- Load staged B2 corrections and apply raw-staging corrections before unified build ---
    staged_corrections = []
    raw_correction_audits = []
    if args.corrections:
        import json

        from pipeline.correction_leaf import stage_for

        corr_dir = Path(args.corrections)
        for p in sorted(corr_dir.glob("**/*.json")):
            try:
                staged_corrections.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                logger.warning("skip unreadable correction: %s", p)
        staged_corrections = [
            c for c in staged_corrections
            if _normalize_cik(str(c.get("cik", ""))) == cik
            and (args.stage is None or stage_for(str(c.get("fix_class") or "")) == args.stage)
        ]

        raw_corrections = [
            c for c in staged_corrections
            if str(c.get("fix_class") or "") == "comparative_period_filter"
        ]
        if raw_corrections:
            from pipeline.agent_b2_appliers import apply_comparative_period_filter

            for c in raw_corrections:
                bdc_df, audit = apply_comparative_period_filter(bdc_df, c.get("template") or {})
                audit["cik"] = c.get("cik")
                audit["layer"] = "raw_bdc_staging"
                raw_correction_audits.append(audit)
            logger.info("Applied %d raw-staging correction(s); audits=%s",
                        len(raw_corrections), raw_correction_audits)

    # --- Build unified holdings into trial directory ---
    import pandas as pd

    from pipeline.unified_holdings import build_unified_holdings

    logger.info("Building trial unified holdings -> %s", trial_csv)
    t2 = time.time()
    trial_df = build_unified_holdings(
        bdc_df=bdc_df,
        nport_df=nport_df if nport_df is not None else pd.DataFrame(),
        output_file=trial_csv,
        orphan_file=trial_orphan,
    )
    elapsed = time.time() - t2
    logger.info("Trial unified holdings: %d rows in %.1f s", len(trial_df), elapsed)

    # --- Apply staged B2 post-staging corrections, if requested (trial only) ---
    if args.corrections:
        from pipeline.agent_b2_appliers import run_corrections

        post_corrections = [
            c for c in staged_corrections
            if str(c.get("fix_class") or "") != "comparative_period_filter"
        ]
        post_audits = []
        if post_corrections:
            trial_df, post_audits = run_corrections(trial_df, post_corrections, stage=args.stage)
        audits = raw_correction_audits + post_audits
        if staged_corrections:
            corrected_csv = trial_dir / f"private_markets_holdings.{cik}.corrected.csv"
            trial_df.to_csv(corrected_csv, index=False)
            (trial_dir / f"corrections_audit.{cik}.json").write_text(
                json.dumps(audits, indent=2), encoding="utf-8")
            logger.info("Applied %d correction(s) (stage=%s) -> %s; audits=%s",
                        len(staged_corrections), args.stage, corrected_csv.name, audits)
        else:
            logger.info("No corrections for CIK %s in %s", cik, Path(args.corrections))

    # --- Summary: compare with production if available ---
    if UNIFIED_HOLDINGS_FILE.exists():
        logger.info("Comparing with production private_markets_holdings.csv")
        con = duckdb.connect()
        safe_prod = str(UNIFIED_HOLDINGS_FILE).replace("\\", "/")
        # Use parquet if available for speed
        prod_parquet = UNIFIED_HOLDINGS_FILE.with_suffix(".parquet")
        if prod_parquet.exists():
            safe_prod = str(prod_parquet).replace("\\", "/")
            prod_read = "read_parquet"
        else:
            prod_read = "read_csv_auto"
        prod_summary = con.execute(
            f"""
            SELECT
                source,
                report_date,
                COUNT(*) AS row_count,
                SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
            FROM {prod_read}('{safe_prod}')
            WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '{cik}'
            GROUP BY source, report_date
            ORDER BY source, report_date
            """
        ).fetchdf()
        con.close()

        trial_summary = (
            trial_df.assign(
                fv=pd.to_numeric(trial_df.get("fair_value", pd.Series(dtype=float)), errors="coerce"),
            )
            .groupby(["source", "report_date"], dropna=False)
            .agg(row_count=("source", "size"), total_fv=("fv", "sum"))
            .reset_index()
            .sort_values(["source", "report_date"])
        )

        summary_path = trial_dir / f"trial_vs_production_summary.{cik}.csv"
        merged = pd.merge(
            prod_summary.rename(columns={"row_count": "prod_rows", "total_fv": "prod_fv"}),
            trial_summary.rename(columns={"row_count": "trial_rows", "total_fv": "trial_fv"}),
            on=["source", "report_date"],
            how="outer",
        ).fillna(0)
        merged["row_delta"] = merged["trial_rows"] - merged["prod_rows"]
        merged["fv_delta"] = merged["trial_fv"] - merged["prod_fv"]
        merged.to_csv(summary_path, index=False)

        logger.info("Trial vs production summary: %s", summary_path.name)
        total_prod = int(merged["prod_rows"].sum())
        total_trial = int(merged["trial_rows"].sum())
        delta_rows = total_trial - total_prod
        logger.info(
            "  Production: %d rows, Trial: %d rows, Delta: %+d rows",
            total_prod, total_trial, delta_rows,
        )
    else:
        logger.info("No production unified holdings found; skipping comparison")

    # --- Position matching on trial output ---
    if args.match:
        from pipeline.position_matching import match_positions
        from pipeline.oracle_checks import (
            check_J01_position_key_stability,
            check_J03_fuzzy_fallback_rate,
            diagnose_fuzzy_fallbacks,
        )

        trial_matches_file = trial_dir / f"position_matches.{cik}.csv"
        logger.info("Running position matching on trial output -> %s", trial_matches_file.name)
        t3 = time.time()
        matches_df = match_positions(
            unified_df=trial_df,
            bdc_raw_df=bdc_df,
            output_file=trial_matches_file,
        )
        logger.info(
            "Trial position matching: %d pairs in %.1f s",
            len(matches_df), time.time() - t3,
        )

        # Tier distribution summary
        if len(matches_df) > 0 and "match_method" in matches_df.columns:
            tier_counts = matches_df["match_method"].value_counts()
            logger.info("Match tier distribution:")
            for method, count in tier_counts.items():
                pct = 100 * count / len(matches_df)
                logger.info("  %s: %d (%.1f%%)", method, count, pct)

        # J01/J03 oracle checks
        j01_results = check_J01_position_key_stability(matches_df)
        for r in j01_results:
            logger.info("J01 %s: %s (metric=%.3f, threshold=%.3f) -- %s",
                        r.scope, r.status, r.metric_value, r.threshold, r.message)

        j03_results = check_J03_fuzzy_fallback_rate(matches_df)
        for r in j03_results:
            logger.info("J03 %s: %s (metric=%.3f, threshold=%.3f) -- %s",
                        r.scope, r.status, r.metric_value, r.threshold, r.message)

        # Fuzzy fallback diagnostics
        diag_df = diagnose_fuzzy_fallbacks(matches_df, trial_df)
        if not diag_df.empty:
            diag_path = trial_dir / f"matching_diagnostic.{cik}.csv"
            diag_df.to_csv(diag_path, index=False)
            logger.info("Fuzzy fallback diagnostics: %d rows -> %s", len(diag_df), diag_path.name)
            # Show first 10 rows
            preview = diag_df.head(10)
            for _, row in preview.iterrows():
                logger.info(
                    "  %s | %s -> %s | %s",
                    row.get("begin_issuer_name", ""),
                    row.get("begin_position_key", ""),
                    row.get("end_position_key", ""),
                    row.get("key_diff_summary", ""),
                )
        else:
            logger.info("No D_fuzzy matches to diagnose")

        # Match quality triage (C/D/E pair heuristic flags)
        from pipeline.match_triage import triage_match_quality

        triage_df = triage_match_quality(matches_df, trial_df, cik=cik)
        if not triage_df.empty:
            triage_path = trial_dir / f"match_triage.{cik}.csv"
            triage_df.to_csv(triage_path, index=False)
            n_flagged = int((triage_df["triage_flags"] > 0).sum())
            total_triaged = len(triage_df)
            logger.info(
                "Match triage: %d of %d C/D/E pairs flagged (%.1f%%)",
                n_flagged,
                total_triaged,
                100 * n_flagged / max(total_triaged, 1),
            )
            for flag_col in [c for c in triage_df.columns if c.startswith("flag_")]:
                n = int(triage_df[flag_col].sum())
                if n > 0:
                    logger.info("  %s: %d", flag_col, n)
        else:
            logger.info("No C/D/E matches to triage")

    logger.info("Trial rebuild complete for CIK %s", cik)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
