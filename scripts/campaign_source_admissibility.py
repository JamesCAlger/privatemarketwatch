"""Campaign source-admissibility auditor + backfill for B-agent dispatch tiers.

The q4t0 dispatch (2026-07-24) burned worker quota producing
ambiguous/source_unavailable verdicts because NO batch item had its filing HTML
cached -- bundle evidence_completeness=source_artifact does NOT imply the raw
SOI HTML is on disk. This script makes that gap measurable and fixable BEFORE
any fleet dispatch, item by item, using the exact accession-resolution logic
the worker evidence CLI uses (first resolved accession from bundle evidence
rows).

Subcommands:
  audit --items <csv> [--build-bundles] [--out <csv>]
      Classify every item (csv needs review_id,cik columns; dispatch_tier
      optional): cached / downloadable (accession in bdc_filings_index.csv,
      HTML missing) / not_in_index / no_accession / no_bundle. Exit 0 iff all
      items are cached (= admissible for dispatch).
  extend-index --from-audit <audit csv>
      NETWORK (submissions API, rate-limited EdgarClient): for every CIK with a
      not_in_index item, fetch its submissions and replace that CIK's rows in
      bdc_filings_index.csv (same replace-fetched/preserve-others semantics as
      pipeline.bdc_filings._build_filings_index).
  download --from-audit <audit csv>
      NETWORK (audited sec_download_guard path, manifest-recorded): download
      every missing resolved accession that is present in the filings index.

Run audit again after extend-index/download; dispatch only on exit 0.
ASCII-only output. Production outputs are untouched (writes: the audit CSV,
bdc_filings_index.csv on extend-index, HTML cache + manifest on download).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import config
from pipeline.bdc_filings import _collect_filings
from pipeline.review_bundles import build_review_bundles
from pipeline.sec_download_guard import (
    bdc_html_cache_path,
    download_bdc_html,
    normalize_accession,
    normalize_cik,
)
from pipeline.html_soi_evidence import (
    resolve_accessions_from_index,
    resolve_accessions_from_rows,
)

BUNDLES_DIR = config.OUTPUT_DIR / "review_queue" / "review_bundles"
AGENT_TAG = "campaign_source_admissibility"

REPORT_COLUMNS = ["review_id", "dispatch_tier", "cik", "engine", "rule_name",
                  "primary_accession", "n_accessions", "status", "detail"]


def _read_items(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows or "review_id" not in rows[0] or "cik" not in rows[0]:
        raise SystemExit(f"ERROR: {path} needs review_id and cik columns")
    return rows


def _rows_from_bundle(bundle: dict) -> list[dict]:
    # Same shape the worker evidence CLI walks (scripts/review_agent/evidence_cli.py).
    rows: list[dict] = []
    for ev in bundle.get("evidence_items", []):
        data = ev.get("data")
        if isinstance(data, list):
            rows.extend(r for r in data if isinstance(r, dict))
        elif isinstance(data, dict):
            rows.append(data)
    return rows


def _load_index() -> dict[str, dict]:
    """(cik10, accession) -> index row, keyed for O(1) lookups."""
    out: dict[str, dict] = {}
    if not config.BDC_FILINGS_INDEX_FILE.exists():
        return out
    with open(config.BDC_FILINGS_INDEX_FILE, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                key = normalize_cik(row.get("cik", "")) + "|" + normalize_accession(
                    row.get("accession_number", ""))
            except Exception:
                continue
            out[key] = row
    return out


def audit(items_path: Path, out_path: Path | None, build_bundles: bool) -> int:
    items = _read_items(items_path)
    ids = [str(r["review_id"]).strip() for r in items]

    missing_bundles = [rid for rid in ids if not (BUNDLES_DIR / f"{rid}.json").exists()]
    if missing_bundles and build_bundles:
        print(f"building {len(missing_bundles)} missing bundles ...")
        build_review_bundles(review_ids=set(missing_bundles), overwrite=False)

    index = _load_index()
    report: list[dict] = []
    for row in items:
        rid = str(row["review_id"]).strip()
        rec = {"review_id": rid, "dispatch_tier": row.get("dispatch_tier", ""),
               "cik": row.get("cik", ""), "engine": row.get("engine", ""),
               "rule_name": row.get("rule_name", ""), "primary_accession": "",
               "n_accessions": 0, "status": "", "detail": ""}
        bundle_path = BUNDLES_DIR / f"{rid}.json"
        if not bundle_path.exists():
            rec["status"] = "no_bundle"
            report.append(rec)
            continue
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            rec["status"], rec["detail"] = "no_bundle", f"bad json: {exc}"
            report.append(rec)
            continue
        accs = resolve_accessions_from_rows(_rows_from_bundle(bundle))
        if not accs:
            # Mirror the evidence CLI's filings-index fallback exactly.
            accs = resolve_accessions_from_index(
                "BDC", bundle.get("cik", "") or row.get("cik", ""),
                bundle.get("report_date", "") or row.get("report_date", ""))
            if accs:
                rec["detail"] = "index_fallback"
        rec["n_accessions"] = len(accs)
        if not accs:
            rec["status"] = "no_accession"
            report.append(rec)
            continue
        # The evidence CLI adjudicates against accs[0] only -- that is the
        # admissibility-relevant accession.
        acc = accs[0]
        rec["primary_accession"] = acc
        cik = bundle.get("cik", "") or row.get("cik", "")
        try:
            cached = bdc_html_cache_path(cik, acc).exists()
        except Exception as exc:
            rec["status"], rec["detail"] = "no_accession", f"bad accession: {exc}"
            report.append(rec)
            continue
        if cached:
            rec["status"] = "cached"
        elif (normalize_cik(cik) + "|" + normalize_accession(acc)) in index:
            rec["status"] = "downloadable"
        else:
            rec["status"] = "not_in_index"
        report.append(rec)

    out = out_path or items_path.with_suffix(".admissibility.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_COLUMNS)
        w.writeheader()
        w.writerows(report)

    by_tier: dict[str, Counter] = defaultdict(Counter)
    for rec in report:
        by_tier[str(rec["dispatch_tier"]) or "?"][rec["status"]] += 1
    print(f"items: {len(report)}  report: {out}")
    for tier in sorted(by_tier):
        parts = ", ".join(f"{k}={v}" for k, v in sorted(by_tier[tier].items()))
        print(f"  tier {tier}: {parts}")
    not_ready = [r for r in report if r["status"] != "cached"]
    if not_ready:
        print(f"NOT ADMISSIBLE: {len(not_ready)} items lack cached source "
              f"({Counter(r['status'] for r in not_ready)})")
        return 1
    print("ADMISSIBLE: every item resolves to cached filing HTML.")
    return 0


def extend_index(audit_path: Path) -> int:
    from pipeline.edgar_client import EdgarClient

    with open(audit_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    ciks = sorted({normalize_cik(r["cik"]) for r in rows if r["status"] == "not_in_index"})
    if not ciks:
        print("no not_in_index items; nothing to extend")
        return 0
    print(f"extending filings index for {len(ciks)} CIKs (submissions API) ...")

    client = EdgarClient()
    cutoff_date = f"{config.BDC_XBRL_START_YEAR}-01-01"
    records: list[dict] = []
    fetched: set[str] = set()
    for i, cik in enumerate(ciks, 1):
        try:
            data = client.get_company_submissions(cik)
        except Exception as exc:
            print(f"  [{i}/{len(ciks)}] CIK {cik} submissions FAILED: {exc}")
            continue
        entity_name = data.get("name", "")
        filings_obj = data.get("filings", {})
        n_before = len(records)
        _collect_filings(records, cik, entity_name,
                         filings_obj.get("recent", {}), cutoff_date)
        for page_ref in filings_obj.get("files", []):
            page_name = page_ref.get("name", "")
            if not page_name:
                continue
            try:
                page_data = client.get_json(
                    f"https://data.sec.gov/submissions/{page_name}")
            except Exception:
                continue
            _collect_filings(records, cik, entity_name, page_data, cutoff_date)
        fetched.add(cik)
        print(f"  [{i}/{len(ciks)}] CIK {cik}: {len(records) - n_before} filings")

    if not records:
        print("ERROR: no filings collected; index unchanged")
        return 1

    # Replace fetched CIKs' rows, preserve everything else (the
    # _build_filings_index merge semantics). Index CIKs are zero-padded.
    existing: list[dict] = []
    fieldnames = ["cik", "entity_name", "accession_number", "form_type",
                  "filing_date", "report_date", "primary_document"]
    if config.BDC_FILINGS_INDEX_FILE.exists():
        with open(config.BDC_FILINGS_INDEX_FILE, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or fieldnames
            existing = [r for r in reader
                        if normalize_cik(r.get("cik", "")) not in fetched]

    seen_acc: set[str] = set()
    new_rows: list[dict] = []
    for rec in records:
        acc = rec.get("accession_number", "")
        if acc in seen_acc:
            continue
        seen_acc.add(acc)
        new_rows.append({k: rec.get(k, "") for k in fieldnames})
    merged = existing + new_rows
    merged.sort(key=lambda r: (r.get("cik", ""), r.get("filing_date", "")))
    with open(config.BDC_FILINGS_INDEX_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(merged)
    print(f"index updated: {len(merged)} rows (+{len(new_rows)} for "
          f"{len(fetched)} CIKs) -> {config.BDC_FILINGS_INDEX_FILE.name}")
    return 0


def download(audit_path: Path) -> int:
    from pipeline.edgar_client import EdgarClient

    with open(audit_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    targets: dict[tuple[str, str], None] = {}
    # not_in_index items are deliberately excluded: the download guard requires
    # the (cik, accession) pair in the filings index and would fail-close anyway.
    for r in rows:
        if r["status"] == "downloadable" and r["primary_accession"]:
            targets[(normalize_cik(r["cik"]), r["primary_accession"])] = None
    if not targets:
        print("no missing accessions to download")
        return 0
    print(f"downloading {len(targets)} distinct (cik, accession) targets ...")

    client = EdgarClient()
    counts: Counter = Counter()
    failures: list[str] = []
    for i, (cik, acc) in enumerate(sorted(targets), 1):
        receipt = download_bdc_html(
            client=client, cik=cik, accession=acc, agent=AGENT_TAG,
            reason="Q4 2025 B-campaign tier 0-4 admissibility backfill "
                   "(user-authorized 2026-07-24)")
        counts[receipt["status"]] += 1
        if receipt["status"] == "failed":
            failures.append(f"{cik} {acc}: {receipt.get('stage')} {receipt.get('error')}")
        if i % 25 == 0 or i == len(targets):
            print(f"  [{i}/{len(targets)}] {dict(counts)}")
    for line in failures[:20]:
        print(f"  FAILED {line}")
    if len(failures) > 20:
        print(f"  ... {len(failures) - 20} more failures")
    print(f"done: {dict(counts)}; receipts in {config.SEC_DOWNLOAD_MANIFEST_FILE.name}")
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--items", required=True, type=Path)
    a.add_argument("--out", type=Path, default=None)
    a.add_argument("--build-bundles", action="store_true")
    e = sub.add_parser("extend-index")
    e.add_argument("--from-audit", required=True, type=Path)
    d = sub.add_parser("download")
    d.add_argument("--from-audit", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.mode == "audit":
        return audit(args.items, args.out, args.build_bundles)
    if args.mode == "extend-index":
        return extend_index(args.from_audit)
    return download(args.from_audit)


if __name__ == "__main__":
    sys.exit(main())
