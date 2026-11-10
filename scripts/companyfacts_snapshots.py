"""Companyfacts snapshot store and pins (pipeline.companyfacts_store). No network.

    python scripts/companyfacts_snapshots.py import [--repin]
    python scripts/companyfacts_snapshots.py show <cik>
    python scripts/companyfacts_snapshots.py diff <cik> <snapA> <snapB> [--limit N] [--json]
    python scripts/companyfacts_snapshots.py pin --file <pin.json> --cik <cik> ... (--latest | --snapshot <ref>) [--note ...]
    python scripts/companyfacts_snapshots.py pin --published --yes --cik ... (--latest | --snapshot <ref>) --note "..."
    python scripts/companyfacts_snapshots.py verify [--pin-file <pin.json>] [--all] [--against-legacy]

``import`` bootstraps the store from what is on disk, oldest first: the pre-Q2 backups
(quarter_backup_import), the Q2 downloads (quarter_download_import), then the live legacy
cache (live_cache_import, retrieved_at = file mtime). It then pins every CIK to the snapshot
byte-identical to its live-cache file and checks sha(pinned) == sha(live) for all of them
(exit 1 otherwise), so switching readers to the pin changes nothing. A snapshot reference
(<snapA>, --snapshot) is a store-relative path, a file name, or a sha256 prefix.
ASCII-only output.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import config  # noqa: E402
from pipeline import companyfacts_store as store  # noqa: E402

QUARTER_DOWNLOADS = config.FILINGS_DIR / "quarter_downloads" / "companyfacts_2026-06-30"


def _import_groups() -> list[tuple[str, list[Path]]]:
    def files(folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        return sorted((p for p in folder.glob("*.json") if p.is_file()),
                      key=lambda p: (p.stat().st_mtime, p.name))
    return [("quarter_backup_import", files(QUARTER_DOWNLOADS / "before")),
            ("quarter_download_import", files(QUARTER_DOWNLOADS)),
            ("live_cache_import", files(Path(config.COMPANYFACTS_CACHE_DIR)))]


def cmd_import(args) -> int:
    rows = store.read_manifest()
    counts: dict[str, list[int]] = {}
    for source, paths in _import_groups():
        created = skipped = 0
        for i, path in enumerate(paths, 1):
            _, new = store.add_snapshot(path.stem, path.read_bytes(), source=source,
                                        retrieved_at=path.stat().st_mtime, manifest_rows=rows)
            created += new
            skipped += not new
            if i % 50 == 0:
                print("  %s: %d/%d" % (source, i, len(paths)), flush=True)
        counts[source] = [len(paths), created, skipped]
        print("%s: %d file(s), %d new snapshot(s), %d already stored" % (source, len(paths), created, skipped))

    # Pin every CIK to the snapshot byte-identical to its live legacy file.
    by_key = {(r["cik"], r["sha256"]): r for r in rows}
    live = sorted(p for p in Path(config.COMPANYFACTS_CACHE_DIR).glob("*.json") if p.is_file())
    pins, live_sha = {}, {}
    for path in live:
        cik = store.cik10(path.stem)
        live_sha[cik] = store.sha256_file(path)
        pins[cik] = by_key[(cik, live_sha[cik])]["path"]
    published = store.published_pin_file()
    current = store.load_pin(published)
    if current is not None and current["pins"] != pins and not args.repin:
        print("published pin %s exists and differs from the live cache; not rewritten (pass --repin)" % published)
        return 1
    store.write_pin(published, pins, promoted_by="scripts/companyfacts_snapshots.py import (" + getpass.getuser() + ")",
                    note="Bootstrap: every CIK pinned to the snapshot byte-identical to its legacy "
                         "data/raw/companyfacts_cache file at import time (zero behaviour change).",
                    allow_published=True)
    bad = [cik for cik, rel in store.load_pin(published)["pins"].items()
           if store.sha256_file(store.snapshot_root() / rel) != live_sha[cik]]
    print("published pin written: %s (%d CIKs)" % (published, len(pins)))
    print("sha(pinned) == sha(live): %d/%d match" % (len(pins) - len(bad), len(pins)))
    for cik in bad:
        print("  MISMATCH %s" % cik)
    return 1 if bad or len(pins) != len(live) else 0


def cmd_show(args) -> int:
    cik = store.cik10(args.cik)
    active = store.load_pin() or {"pins": {}}
    published = store.load_pin(store.published_pin_file()) or {"pins": {}}
    rows = store.snapshots_for(cik)
    print("CIK %s: %d snapshot(s); active pin file %s" % (cik, len(rows), store.active_pin_file()))
    for r in rows:
        marks = []
        if active["pins"].get(cik) == r["path"]:
            marks.append("ACTIVE")
        if published["pins"].get(cik) == r["path"]:
            marks.append("PUBLISHED")
        print("  %s  %s  %-24s max_end=%s facts=%s bytes=%s %s" % (
            r["path"], r["retrieved_at"], r["source"], r["max_fact_end"], r["fact_count"], r["bytes"],
            " ".join(marks)))
    if not active["pins"].get(cik):
        print("  (not pinned in the active pin file)")
    return 0


def cmd_diff(args) -> int:
    a = store.resolve_snapshot_ref(args.cik, args.snap_a)
    b = store.resolve_snapshot_ref(args.cik, args.snap_b)
    result = store.diff_facts(json.loads(a.read_text(encoding="utf-8")),
                              json.loads(b.read_text(encoding="utf-8")), limit=args.limit)
    if args.json:
        print(json.dumps(dict(a=str(a), b=str(b), **result), indent=2, default=str))
        return 0
    s = result["summary"]
    print("A %s\nB %s" % (a, b))
    print("fact keys A %d, B %d | restated %d | added %d | removed %d" % (
        s["keys_a"], s["keys_b"], s["restated"], s["added"], s["removed"]))
    fields = ("taxonomy", "concept", "unit", "end", "start", "form", "fy", "fp")
    for label, items in (("RESTATED", result["restated"]), ("ADDED", result["added"]), ("REMOVED", result["removed"])):
        for item in items:
            key = " ".join("%s=%s" % (f, item.get(f)) for f in fields)
            vals = ("%s -> %s" % (item["values_a"], item["values_b"])) if "values_a" in item else str(item["values"])
            print("  %s %s : %s" % (label, key, vals))
    return 0


def cmd_pin(args) -> int:
    published = store.published_pin_file()
    if args.published:
        if not args.yes:
            print("refusing: --published requires --yes")
            return 2
        target = published
    elif args.file is None:
        print("pin needs --file <pin.json> (or --published --yes)")
        return 2
    else:
        target = args.file
    if args.snapshot and len(args.cik) != 1:
        print("--snapshot takes exactly one --cik")
        return 2
    updates = {}
    for cik in args.cik:
        if args.latest:
            row = store.latest_snapshot(cik)
            if row is None:
                print("no snapshot for %s" % store.cik10(cik))
                return 1
            updates[store.cik10(cik)] = row["path"]
        else:
            path = store.resolve_snapshot_ref(cik, args.snapshot)
            updates[store.cik10(cik)] = path.resolve().relative_to(store.snapshot_root().resolve()).as_posix()
    try:
        store.write_candidate_pin(target, updates,
                                  promoted_by=args.by or getpass.getuser(), note=args.note or "",
                                  allow_published=bool(args.published and args.yes))
    except store.CompanyfactsStoreError as exc:
        print("refusing: %s" % exc)
        return 2
    for cik, rel in sorted(updates.items()):
        print("%s -> %s" % (cik, rel))
    print("pin written: %s" % target)
    return 0


def cmd_verify(args) -> int:
    pin_file = args.pin_file or store.active_pin_file()
    problems = store.verify(pin_file, all_snapshots=args.all)
    doc = store.load_pin(pin_file)
    n = len(doc["pins"]) if doc else 0
    if args.against_legacy and doc:
        legacy = Path(config.COMPANYFACTS_CACHE_DIR)
        same = differ = absent = 0
        for cik, rel in sorted(doc["pins"].items()):
            path = legacy / (cik + ".json")
            if not path.is_file():
                absent += 1
            elif store.sha256_file(path) == store.sha256_file(store.snapshot_root() / rel):
                same += 1
            else:
                differ += 1
                print("  legacy differs from pin: %s" % cik)
        print("against legacy cache: %d identical, %d differ, %d absent from legacy" % (same, differ, absent))
    print("verify %s: %d pinned CIK(s), %d snapshot(s) in manifest, %d problem(s)" % (
        pin_file, n, len(store.read_manifest()), len(problems)))
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import", help="bootstrap the store from on-disk files and pin the live versions")
    p.add_argument("--repin", action="store_true", help="overwrite an existing, different published pin")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("show", help="list a CIK's snapshots")
    p.add_argument("cik")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("diff", help="restated / added / removed facts between two snapshots")
    p.add_argument("cik")
    p.add_argument("snap_a")
    p.add_argument("snap_b")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff)
    p = sub.add_parser("pin", help="write a candidate pin (published only with --published --yes)")
    p.add_argument("--file", type=Path)
    p.add_argument("--cik", nargs="+", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--latest", action="store_true")
    g.add_argument("--snapshot")
    p.add_argument("--published", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--note", default="")
    p.add_argument("--by", default=os.environ.get("PM_PROMOTED_BY"))
    p.set_defaults(func=cmd_pin)
    p = sub.add_parser("verify", help="every pinned snapshot exists and matches its manifest sha")
    p.add_argument("--pin-file", type=Path)
    p.add_argument("--all", action="store_true", help="also check every manifest snapshot")
    p.add_argument("--against-legacy", action="store_true", help="compare pinned bytes with the legacy cache")
    p.set_defaults(func=cmd_verify)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
