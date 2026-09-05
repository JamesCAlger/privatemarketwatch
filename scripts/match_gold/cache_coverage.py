"""Measure, per packet, how much of its filing evidence a worker can actually roam.

`worklist.csv`'s `has_cached_filing` is an all-or-nothing flag fixed at build time:
False both when a packet has NO accession numbers at all and when it has six of which
five are cached. Those are different problems with different fixes, and the second is
still adjudicable. The dispatcher selects on the numbers this reports rather than on
that flag, so selection reflects the cache as it is at dispatch time.

    python scripts/match_gold/cache_coverage.py --batch-dir <dir> [--json]

Categories:
  full    -- every accession has cached HTML; the packet is fully adjudicable.
  partial -- some accessions cached; adjudicable with less evidence than intended.
  none    -- accessions exist but none cached; a worker could only guess.
  no_acc  -- the packet's rows carry no accession_number at all (no filing to roam).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.html_soi_evidence import _html_path  # noqa: E402


def _cached(cik: str, accession: str) -> bool:
    try:
        return _html_path("BDC", cik, accession).exists()
    except Exception:
        return False


def coverage(batch_dir: Path) -> dict:
    """Return {packet_id: {n_accessions, n_cached, category, cached: [...]}}."""
    out: dict = {}
    for packet_path in sorted((batch_dir / "packets").glob("*.json")):
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        accessions = packet.get("accessions") or []
        # Resolve each accession's owning CIK from its mini-bundle, not from the packet.
        # Packet rows are blinded and carry no cik, and the packet-level cik is only the
        # representative fund -- wrong for the other side of a cross-fund entity packet,
        # and a wrong CIK always misses (the HTML cache is keyed by fund). The bundle is
        # also exactly what evidence_cli.py will resolve against, so this measures what
        # the worker can actually reach rather than a reconstruction of it.
        default_cik = str(packet.get("cik") or "")
        cached = []
        for acc in accessions:
            bundle_path = packet.get("filing_bundles", {}).get(acc)
            acc_cik = default_cik
            if bundle_path and Path(bundle_path).exists():
                try:
                    acc_cik = str(json.loads(
                        Path(bundle_path).read_text(encoding="utf-8")).get("cik") or default_cik)
                except (json.JSONDecodeError, OSError):
                    pass
            if _cached(acc_cik, acc):
                cached.append(acc)
        if not accessions:
            category = "no_acc"
        elif len(cached) == len(accessions):
            category = "full"
        elif cached:
            category = "partial"
        else:
            category = "none"
        out[packet["packet_id"]] = {
            "packet_type": packet["packet_type"],
            "n_accessions": len(accessions),
            "n_cached": len(cached),
            "category": category,
            "cached": cached,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--json", action="store_true", help="emit the per-packet mapping")
    args = ap.parse_args()

    batch_dir = Path(args.batch_dir)
    cov = coverage(batch_dir)
    if args.json:
        print(json.dumps(cov))
        return 0

    counts = Counter(v["category"] for v in cov.values())
    print(f"packets: {len(cov)}")
    for cat in ("full", "partial", "none", "no_acc"):
        print(f"  {cat:8s} {counts.get(cat, 0)}")

    # Stratum breakdown needs the meta sidecars; skip cleanly if the dispatcher is
    # holding them outside the repo for blinding.
    meta_dir = batch_dir / "packets_meta"
    if meta_dir.is_dir():
        rows: dict[tuple[str, str], Counter] = {}
        for pid, v in cov.items():
            meta_path = meta_dir / f"{pid}.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            key = (meta["packet_type"], meta["stratum"])
            rows.setdefault(key, Counter())[v["category"]] += 1
        print()
        print(f"{'packet_type':<12}{'stratum':<26}{'full':>6}{'partial':>9}{'none':>6}{'no_acc':>8}")
        for key in sorted(rows):
            c = rows[key]
            print(f"{key[0]:<12}{key[1]:<26}{c['full']:>6}{c['partial']:>9}"
                  f"{c['none']:>6}{c['no_acc']:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
