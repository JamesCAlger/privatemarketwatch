"""Test GICS web search reclassification on top 100 companies.

Validates:
1. API connectivity and response format
2. Classification quality (non-Other rate)
3. GICS name validity (exact match to reference list)
4. Evidence quality (non-empty explanations)
5. FV coverage of reclassified companies

Usage:
    python scripts/test_gics_web_search.py             # Run on top 100
    python scripts/test_gics_web_search.py --dry-run   # Show candidates only
    python scripts/test_gics_web_search.py -n 50       # Run on top 50
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_gics_web_search")


def main():
    parser = argparse.ArgumentParser(description="Test GICS web search reclassification")
    parser.add_argument("-n", type=int, default=100,
                        help="Number of companies to test (default: 100)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show candidates without calling API")
    args = parser.parse_args()

    from pipeline.gics_classification import (
        _load_gics_names,
        reclassify_with_web_search,
    )

    if args.dry_run:
        logger.info("=== DRY RUN: Top %d unclassified companies by FV ===", args.n)
        results_df = reclassify_with_web_search(n=args.n, dry_run=True)
        if results_df.empty:
            logger.info("No candidates found")
            return

        print(f"\nTop {min(args.n, len(results_df))} unclassified companies:")
        print(f"{'Rank':<5} {'Search Name':<40} {'Norm Name':<35} {'FV ($M)':<12}")
        print("-" * 95)
        for i, row in results_df.head(50).iterrows():
            fv_m = row["total_fv"] / 1e6
            search = row.get("search_name", row["company_name_norm"])[:38]
            norm = row["company_name_norm"][:33]
            print(f"{i+1:<5} {search:<40} {norm:<35} {fv_m:>10,.0f}")
        print(f"\nTotal: {len(results_df)} companies, "
              f"${results_df['total_fv'].sum()/1e9:.1f}B FV")
        return

    # Run the web search classification
    logger.info("=== Testing GICS Web Search on top %d companies ===", args.n)
    results_df = reclassify_with_web_search(n=args.n)

    if results_df.empty:
        logger.error("No results returned")
        sys.exit(1)

    # === Validation ===
    gics_names = _load_gics_names()
    gics_set = set(gics_names) | {"Other"}

    print("\n" + "=" * 80)
    print("VALIDATION RESULTS")
    print("=" * 80)

    # 1. Response completeness
    total = len(results_df)
    print(f"\n1. Response completeness: {total}/{args.n} companies processed")

    # 2. Non-Other rate
    non_other = results_df[results_df["gics_sub_industry"] != "Other"]
    non_other_pct = len(non_other) / total * 100 if total else 0
    print(f"\n2. Classification rate: {len(non_other)}/{total} "
          f"({non_other_pct:.1f}%) classified (non-Other)")
    if non_other_pct < 30:
        print("   WARNING: Low classification rate (<30%). Web search may not be finding companies.")
    elif non_other_pct > 70:
        print("   GOOD: High classification rate (>70%).")

    # 3. GICS name validity
    invalid_gics = []
    for _, row in results_df.iterrows():
        gics = row["gics_sub_industry"]
        if gics not in gics_set:
            invalid_gics.append((row["company_name_norm"], gics))
    print(f"\n3. GICS name validity: {total - len(invalid_gics)}/{total} valid")
    if invalid_gics:
        print("   INVALID entries (hallucinated GICS names):")
        for name, gics in invalid_gics[:10]:
            print(f"     - {name}: '{gics}'")

    # 4. Evidence quality
    has_evidence = (results_df["evidence"].str.len() > 5).sum()
    print(f"\n4. Evidence quality: {has_evidence}/{total} "
          f"({100*has_evidence/total:.0f}%) have evidence text")

    # 5. Confidence distribution
    if "confidence" in results_df.columns:
        conf_dist = results_df["confidence"].value_counts()
        print(f"\n5. Confidence distribution:")
        for conf, count in conf_dist.items():
            print(f"   {conf}: {count} ({100*count/total:.0f}%)")

    # 6. FV coverage
    if "total_fv" in results_df.columns:
        total_fv = results_df["total_fv"].sum()
        classified_fv = non_other["total_fv"].sum() if not non_other.empty else 0
        print(f"\n6. FV coverage:")
        print(f"   Total FV of tested companies: ${total_fv/1e9:.1f}B")
        print(f"   FV classified (non-Other): ${classified_fv/1e9:.1f}B "
              f"({100*classified_fv/total_fv:.0f}%)" if total_fv else "   N/A")

    # 7. Top classified industries
    if not non_other.empty:
        print(f"\n7. Top 15 industries assigned:")
        industry_fv = non_other.groupby("gics_sub_industry")["total_fv"].sum()
        industry_fv = industry_fv.sort_values(ascending=False)
        for gics, fv in industry_fv.head(15).items():
            count = (non_other["gics_sub_industry"] == gics).sum()
            print(f"   {gics:<45} {count:>3} companies  ${fv/1e9:.1f}B")

    # 8. Sample results (show first 20 non-Other)
    print(f"\n8. Sample classifications (first 20 non-Other):")
    print(f"   {'Company':<40} {'GICS Sub-Industry':<40} {'Conf':<6} {'Evidence'}")
    print("   " + "-" * 130)
    for _, row in non_other.head(20).iterrows():
        evidence = str(row.get("evidence", ""))[:50]
        print(f"   {row['company_name_norm']:<40} "
              f"{row['gics_sub_industry']:<40} "
              f"{row.get('confidence', '?'):<6} "
              f"{evidence}")

    # 9. Sample "Other" results (show some that remained Other)
    others = results_df[results_df["gics_sub_industry"] == "Other"]
    if not others.empty:
        print(f"\n9. Sample 'Other' results (top 10 by FV that couldn't be classified):")
        print(f"   {'Company':<50} {'FV ($M)':<12} {'Evidence'}")
        print("   " + "-" * 100)
        for _, row in others.head(10).iterrows():
            evidence = str(row.get("evidence", ""))[:60]
            fv_m = row.get("total_fv", 0) / 1e6
            print(f"   {row['company_name_norm']:<50} {fv_m:>10,.0f} {evidence}")

    # Save results for inspection
    output_path = Path("data/output/gics_web_search_test_results.csv")
    results_df.to_csv(output_path, index=False)
    print(f"\nResults saved to: {output_path}")

    # Overall assessment
    print("\n" + "=" * 80)
    print("OVERALL ASSESSMENT")
    print("=" * 80)
    passed = []
    failed = []

    if non_other_pct >= 40:
        passed.append(f"Classification rate {non_other_pct:.0f}% >= 40%")
    else:
        failed.append(f"Classification rate {non_other_pct:.0f}% < 40%")

    if not invalid_gics:
        passed.append("All GICS names valid")
    else:
        failed.append(f"{len(invalid_gics)} invalid GICS names")

    if has_evidence / total >= 0.5:
        passed.append(f"Evidence coverage {100*has_evidence/total:.0f}% >= 50%")
    else:
        failed.append(f"Evidence coverage {100*has_evidence/total:.0f}% < 50%")

    if total >= args.n * 0.9:
        passed.append(f"Completeness {total}/{args.n} >= 90%")
    else:
        failed.append(f"Completeness {total}/{args.n} < 90%")

    for p in passed:
        print(f"  PASS: {p}")
    for f in failed:
        print(f"  FAIL: {f}")

    print(f"\n  Result: {'ALL PASSED' if not failed else f'{len(failed)} FAILED'}")


if __name__ == "__main__":
    main()
