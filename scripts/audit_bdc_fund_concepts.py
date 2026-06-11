"""Audit all fund-level XBRL concepts from non-listed BDC filings.

Scans the most recent XBRL filing for each unlisted BDC CIK and catalogs
every concept that appears at fund level (not position-level investment
schedule data). Outputs a coverage matrix showing which concepts exist
across the universe.

Usage:
    python scripts/audit_bdc_fund_concepts.py
    python scripts/audit_bdc_fund_concepts.py --top 50
    python scripts/audit_bdc_fund_concepts.py --cik 0001837532
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import BDC_XBRL_CACHE_DIR

UNLISTED_REF = ROOT / "data" / "overrides" / "bdc_xbrl_wrappers" / "unlisted_bdc_xbrl_reference.json"
V1_MANIFEST = ROOT / "data" / "overrides" / "wrapper_cohorts" / "v1_39_wrapper_manifest.json"
OUTPUT_DIR = ROOT / "data" / "output"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# XBRL infrastructure tags to skip
INFRA_TAGS = frozenset({
    "context", "entity", "identifier", "period", "startDate", "endDate",
    "instant", "segment", "unit", "measure", "schemaRef", "explicitMember",
    "divide", "unitNumerator", "unitDenominator", "footnote", "footnoteLink",
    "footnoteArc", "loc", "roleRef", "arcroleRef",
})

# Concepts that are clearly position-level investment schedule data
# (appear hundreds/thousands of times per filing)
POSITION_LEVEL_PREFIXES = (
    "investmentcompanyinvestment",  # N-PORT style
)


def _local_name(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _parse_contexts(root) -> dict:
    """Parse all xbrli:context elements, extracting dimensions and periods."""
    contexts = {}
    for ctx in root.iter("{http://www.xbrl.org/2003/instance}context"):
        ctx_id = ctx.get("id", "")
        dims = {}
        for member in ctx.iter("{http://xbrl.org/2006/xbrldi}explicitMember"):
            axis_raw = member.get("dimension", "")
            val_raw = member.text or ""
            # Extract local names
            axis = axis_raw.split(":")[-1] if ":" in axis_raw else axis_raw
            val = val_raw.split(":")[-1] if ":" in val_raw else val_raw
            dims[axis] = val

        instant = ctx.find(".//{http://www.xbrl.org/2003/instance}instant")
        start = ctx.find(".//{http://www.xbrl.org/2003/instance}startDate")
        end = ctx.find(".//{http://www.xbrl.org/2003/instance}endDate")

        if instant is not None:
            period = instant.text or ""
            period_type = "instant"
        elif start is not None and end is not None:
            period = f"{start.text} to {end.text}"
            period_type = "duration"
        else:
            period = ""
            period_type = ""

        contexts[ctx_id] = {
            "dims": dims,
            "period": period,
            "period_type": period_type,
        }
    return contexts


def _is_fund_level(concept_lower: str, count: int, total_elements: int) -> bool:
    """Heuristic: fund-level concepts appear a small number of times.

    Position-level data (schedule of investments) appears hundreds+ times.
    Fund-level data (balance sheet, income, highlights) appears <60 times.
    """
    if count > 80:
        return False
    for prefix in POSITION_LEVEL_PREFIXES:
        if concept_lower.startswith(prefix):
            return False
    return True


def scan_filing(xml_path: Path) -> dict:
    """Scan a single XBRL filing and return fund-level concept inventory.

    Returns dict with:
        concepts: {concept_name: [{"value", "period", "dims", "share_class"}]}
        share_classes: set of share class member names found
    """
    try:
        tree = etree.parse(str(xml_path))
    except Exception as e:
        logger.warning("  Failed to parse %s: %s", xml_path.name, e)
        return {"concepts": {}, "share_classes": set()}

    root = tree.getroot()
    contexts = _parse_contexts(root)

    # First pass: count occurrences of each concept
    concept_counts = Counter()
    for elem in root.iter():
        local = _local_name(elem.tag)
        if local.lower() in INFRA_TAGS:
            continue
        text = (elem.text or "").strip()
        if text and len(text) < 500:
            concept_counts[local] += 1

    total = sum(concept_counts.values())

    # Second pass: extract fund-level concepts with context detail
    concepts = defaultdict(list)
    share_classes = set()

    for elem in root.iter():
        local = _local_name(elem.tag)
        if local.lower() in INFRA_TAGS:
            continue
        text = (elem.text or "").strip()
        if not text or len(text) >= 500:
            continue

        count = concept_counts.get(local, 0)
        if not _is_fund_level(local.lower(), count, total):
            continue

        ctx_ref = elem.get("contextRef", "")
        ctx = contexts.get(ctx_ref, {})
        dims = ctx.get("dims", {})

        # Identify share class
        share_class = dims.get("StatementClassOfStockAxis", "")
        if share_class:
            share_classes.add(share_class)

        # Only keep a few examples per concept (avoid bloat)
        if len(concepts[local]) < 6:
            concepts[local].append({
                "value": text[:80],
                "period": ctx.get("period", ""),
                "share_class": share_class,
                "dims": dims,
            })
        elif len(concepts[local]) == 6:
            concepts[local].append({"value": "...", "period": "", "share_class": "", "dims": {}})

    return {"concepts": dict(concepts), "share_classes": share_classes}


def main():
    parser = argparse.ArgumentParser(description="Audit BDC fund-level XBRL concepts")
    parser.add_argument("--top", type=int, default=0, help="Show top N concepts by coverage")
    parser.add_argument("--cik", type=str, default="", help="Scan single CIK only")
    parser.add_argument("--v1-only", action="store_true", help="Restrict to v1_39 manifest CIKs")
    args = parser.parse_args()

    # Load CIK universe
    if args.cik:
        target_ciks = {args.cik.zfill(10)}
    elif args.v1_only and V1_MANIFEST.exists():
        data = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
        target_ciks = {e["cik"] for e in data.get("entries", [])}
        logger.info("Scanning %d v1 manifest CIKs", len(target_ciks))
    elif UNLISTED_REF.exists():
        data = json.loads(UNLISTED_REF.read_text(encoding="utf-8"))
        target_ciks = {e["cik"] for e in data.get("entries", [])}
        logger.info("Scanning %d unlisted BDC CIKs", len(target_ciks))
    else:
        logger.error("No CIK reference file found")
        return

    # Map CIK -> latest XML file
    cik_files = {}
    for cik in sorted(target_ciks):
        cik_stripped = cik.lstrip("0") or "0"
        cache_dir = BDC_XBRL_CACHE_DIR / cik_stripped
        if not cache_dir.exists():
            continue
        xmls = sorted(cache_dir.glob("*.xml"))
        if not xmls:
            continue
        # Latest by filename (accession number ~ chronological)
        cik_files[cik] = xmls[-1]

    logger.info("Found XBRL files for %d / %d CIKs", len(cik_files), len(target_ciks))
    missing = target_ciks - set(cik_files.keys())
    if missing:
        logger.info("No XBRL cache for: %s", ", ".join(sorted(missing)))

    # Scan all filings
    # concept_name -> set of CIKs that have it
    concept_coverage = defaultdict(set)
    # concept_name -> {has_share_class: bool, example_values: [], example_dims: set}
    concept_detail = defaultdict(lambda: {
        "has_share_class": False,
        "example_values": [],
        "example_dims": set(),
        "share_class_ciks": set(),
    })
    # CIK -> set of share classes found
    cik_share_classes = {}

    t0 = time.time()
    for i, (cik, xml_path) in enumerate(sorted(cik_files.items())):
        if (i + 1) % 20 == 0 or i == 0:
            logger.info("  Scanning %d / %d: CIK %s ...", i + 1, len(cik_files), cik)

        result = scan_filing(xml_path)
        cik_share_classes[cik] = result["share_classes"]

        for concept, instances in result["concepts"].items():
            concept_coverage[concept].add(cik)
            detail = concept_detail[concept]

            for inst in instances:
                if inst.get("share_class"):
                    detail["has_share_class"] = True
                    detail["share_class_ciks"].add(cik)
                if len(detail["example_values"]) < 3 and inst["value"] != "...":
                    detail["example_values"].append(inst["value"])
                for dim_name in inst.get("dims", {}):
                    detail["example_dims"].add(dim_name)

    elapsed = time.time() - t0
    logger.info("Scanned %d filings in %.1fs", len(cik_files), elapsed)
    logger.info("")

    # Report
    total_ciks = len(cik_files)

    # Sort by coverage descending
    sorted_concepts = sorted(
        concept_coverage.items(),
        key=lambda x: (-len(x[1]), x[0]),
    )

    if args.top:
        sorted_concepts = sorted_concepts[:args.top]

    # Print summary
    print(f"{'Concept':<80} {'CIKs':>5} {'%':>6} {'Class?':>6}  Example")
    print("-" * 140)
    for concept, ciks in sorted_concepts:
        detail = concept_detail[concept]
        pct = len(ciks) / total_ciks * 100
        has_cls = "YES" if detail["has_share_class"] else ""
        examples = "; ".join(detail["example_values"][:2])[:50]
        print(f"{concept:<80} {len(ciks):>5} {pct:>5.1f}% {has_cls:>6}  {examples}")

    # Share class summary
    ciks_with_classes = {c for c, sc in cik_share_classes.items() if sc}
    print(f"\n{'='*80}")
    print(f"CIKs with share class data: {len(ciks_with_classes)} / {total_ciks}")
    if ciks_with_classes:
        all_classes = set()
        for sc in cik_share_classes.values():
            all_classes |= sc
        print(f"Unique share class members: {len(all_classes)}")
        # Show top classes
        class_counts = Counter()
        for sc in cik_share_classes.values():
            for c in sc:
                class_counts[c] += 1
        for cls, cnt in class_counts.most_common(20):
            print(f"  {cls}: {cnt} CIKs")

    # Write CSV for further analysis
    csv_path = OUTPUT_DIR / "bdc_fund_concept_coverage.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["concept", "cik_count", "pct_coverage", "has_share_class",
                     "share_class_cik_count", "example_values", "dimension_axes"])
        for concept, ciks in sorted_concepts:
            detail = concept_detail[concept]
            w.writerow([
                concept,
                len(ciks),
                round(len(ciks) / total_ciks * 100, 1),
                detail["has_share_class"],
                len(detail["share_class_ciks"]),
                "; ".join(detail["example_values"][:3]),
                "; ".join(sorted(detail["example_dims"])),
            ])
    logger.info("\nWrote coverage CSV to %s", csv_path)

    # Write per-CIK share class detail
    sc_path = OUTPUT_DIR / "bdc_share_class_inventory.csv"
    with open(sc_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cik", "share_classes", "class_count"])
        for cik in sorted(cik_files.keys()):
            classes = sorted(cik_share_classes.get(cik, set()))
            w.writerow([cik, "; ".join(classes), len(classes)])
    logger.info("Wrote share class inventory to %s", sc_path)


if __name__ == "__main__":
    main()
