"""Record a decision in the decision store (data/decisions), or list what stands.

    python scripts/decide.py append entry.json --actor agent:<your id>
    python scripts/decide.py append entries.json --actor owner           # a JSON list records several
    python scripts/decide.py show [--cik 0001234567] [--type fix_record] [--finding RVQ_...]

``append`` validates each entry (pipeline.decision_store.validate), refuses an actor that is not
the entry's ``decided_by`` or may not record that type (only ``owner`` or ``delegate:<id>`` records an
owner_ruling), and checks every filing quote against the cached page of that filing: a quote that
is not on the page is refused. All entries of one file are checked before any is written.
Entry types and fields: see pipeline/decision_store.py. Nothing is ever edited; to change a
decision append a new entry with ``supersedes`` set to the old decision_id. ASCII-only output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import decision_store  # noqa: E402


def page_quote_ok(cik: str, accession: str, quote: str) -> bool:
    """The quote, normalised as the fund gate compares quotes, is on the cached page of the filing."""
    sys.path.insert(0, str(ROOT / "scripts" / "v05_evidence"))
    from fund_gate import normalise, page_text
    page = page_text(cik, accession) if cik else None
    text = normalise(quote)
    return bool(page) and len(text) >= 20 and text in page


def append_file(path: Path, *, actor: str, directory: Path | None = None, quote_ok=page_quote_ok) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    entries = data if isinstance(data, list) else [data]
    problems = []
    for number, entry in enumerate(entries, 1):
        errs = decision_store.validate(entry)
        if not errs and isinstance(entry, dict):
            if entry.get("decided_by") != actor:
                errs.append("decided_by %r is not the actor %r" % (entry.get("decided_by"), actor))
            for item in entry.get("evidence", []):
                if item.get("source") == "filing" and quote_ok is not None \
                        and not quote_ok(str(entry.get("cik") or ""), item["accession"], item["quote"]):
                    errs.append("filing quote not on the cached page: %s %r" % (item["accession"], item["quote"][:60]))
        if errs:
            problems.append("entry %d: %s" % (number, "; ".join(errs)))
    if problems:
        raise ValueError("nothing recorded: " + " | ".join(problems))
    return [decision_store.append(entry, actor=actor, directory=directory) for entry in entries]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    add = sub.add_parser("append")
    add.add_argument("file", type=Path)
    add.add_argument("--actor", required=True)
    show = sub.add_parser("show")
    show.add_argument("--cik")
    show.add_argument("--type", choices=decision_store.NATIVE_TYPES)
    show.add_argument("--finding")
    show.add_argument("--limit", type=int, default=50)
    args = ap.parse_args(argv)
    if args.command == "append":
        try:
            written = append_file(args.file, actor=args.actor)
        except (ValueError, PermissionError) as exc:
            print("REFUSED: %s" % exc)
            return 2
        for entry in written:
            print("recorded %s %s" % (entry["decision_id"], entry["type"]))
        return 0
    entries = decision_store.standing(decision_store.load_native())
    shown = 0
    for e in entries:
        if args.cik and e.get("cik") != args.cik.zfill(10):
            continue
        if args.type and e["type"] != args.type:
            continue
        if args.finding and args.finding not in e.get("finding_ids", []):
            continue
        shown += 1
        if shown <= args.limit:
            print("%s  %-20s %s  %s  %s" % (e["decision_id"], e["type"], e.get("decided_on"), e.get("decided_by"),
                                           " ".join(str(e.get("statement") or "").split())[:110]))
    print("%d standing decision(s) match%s" % (shown, "" if shown <= args.limit else " (first %d shown)" % args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
