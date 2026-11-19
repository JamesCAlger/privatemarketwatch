"""Command line: parse the cached filings of the scope funds into the filed layer."""
import argparse
import importlib
import json
import re
import sys
import time
from pathlib import Path

from . import PARSER_VERSION, dashed_accession, inline, instance, store

SCOPE_FILE = Path("data/reference/quarter_acceptance_thresholds.json")


def _pad_cik(text):
    digits = text.strip()
    if not digits.isdigit():
        raise SystemExit(f"bad cik: {text}")
    return digits.zfill(10)


def _plain_accession(text):
    t = text.strip()
    if re.fullmatch(r"\d{10}-\d{2}-\d{6}", t):
        return t.replace("-", "")
    return t


def parse_html(path, accession=None):
    return inline.parse_inline(path, accession=accession)


def load_scope(scope_file):
    data = json.loads(Path(scope_file).read_text(encoding="utf-8"))
    return [_pad_cik(c) for c in data["findings_scope"]["ciks"]]


def discover(raw, ciks, accessions):
    """List of (cik10, dashed accession, xml path, html path or None), ordered by cik then accession."""
    found = []
    for cik in ciks:
        xml_dir = Path(raw) / "bdc_xbrl" / cik.lstrip("0")
        for xml in sorted(xml_dir.glob("*.xml")):
            html = Path(raw) / "bdc_html" / cik.lstrip("0") / (xml.stem + ".html")
            found.append((cik, dashed_accession(xml.stem), xml, html if html.exists() else None))
    if accessions:
        wanted = {_plain_accession(a) for a in accessions}
        found = [f for f in found if f[2].stem in wanted]
        missing = wanted - {f[2].stem for f in found}
        if missing:
            raise SystemExit("accession not found in cache: " + ", ".join(sorted(missing)))
    return found


def _inputs(raw, xml, html):
    inputs = store.describe_file(xml, raw, "instance")
    inputs.update(store.describe_file(html, raw, "html"))
    return inputs


def _parse_all(xml, html, accession):
    tables = instance.parse_instance(xml, accession=accession)
    if html is not None:
        extra = parse_html(html, accession)
        tables["stats"] = list(tables.get("stats", [])) + list(extra.pop("stats", []))
        tables.update(extra)
    return tables


def _totals(out, filings):
    rows = {t: 0 for t in store.TABLES}
    stats = {}
    pkd = 0
    parsers = {}
    n = 0
    for cik, acc, _, _ in filings:
        m = store._read_manifest(store.folder_for(out, cik, acc))
        if m is None:
            continue
        n += 1
        for t, v in m["tables"].items():
            rows[t] += v["rows"]
        for k, v in m.get("stats", {}).items():
            stats[k] = stats.get(k, 0) + v
        pkd += sum(m.get("pk_duplicates", {}).values())
        parsers[m.get("html_parser")] = parsers.get(m.get("html_parser"), 0) + 1
    print(f"TOTAL filings with manifest: {n}")
    print(f"TOTAL html_parser: {parsers}")
    for t, c in rows.items():
        print(f"TOTAL rows {t}: {c}")
    for k, v in sorted(stats.items()):
        print(f"TOTAL {k}: {v}")
    print(f"TOTAL primary key duplicates: {pkd}")


def run(args):
    ciks = [_pad_cik(c) for c in args.cik] if args.cik else load_scope(args.scope_file)
    filings = discover(args.raw, ciks, args.accession)
    out = Path(args.out)
    store.sweep_staging(out)
    failed = 0
    counts = {"written": 0, "skipped": 0, "skipped_version": 0}
    t_all = time.time()
    for i, (cik, acc, xml, html) in enumerate(filings, 1):
        t0 = time.time()
        prefix = f"[{i}/{len(filings)}] {cik} {acc}"
        try:
            inputs = _inputs(args.raw, xml, html)
            if args.verify:
                problems = store.verify_filing(out, cik, acc, _parse_all(xml, html, acc), inputs)
                if problems:
                    failed += 1
                    print(f"{prefix} MISMATCH {'; '.join(problems)}")
                else:
                    counts["written"] += 1
                    print(f"{prefix} match {time.time() - t0:.1f}s")
                continue
            action = store.decide(out, cik, acc, inputs, args.reparse)
            if action == "write":
                m = store.write_filing(out, cik, acc, _parse_all(xml, html, acc), inputs, args.reparse)
            else:
                m = store._read_manifest(store.folder_for(out, cik, acc))
                m["status"] = "skipped" if action == "skip" else "skipped_version"
            counts[m["status"]] += 1
            print(f"{prefix} {m['status']} facts={m['tables']['tagged_fact']['rows']} "
                  f"{time.time() - t0:.1f}s")
        except Exception as exc:  # one failed filing must not hide the others
            failed += 1
            print(f"{prefix} FAILED {type(exc).__name__}: {str(exc)[:300]}")
    elapsed = time.time() - t_all
    if args.verify:
        print(f"VERIFY matched={counts['written']} mismatched={failed} of {len(filings)} in {elapsed:.1f}s")
    else:
        print(f"DONE written={counts['written']} skipped={counts['skipped']} "
              f"skipped_version={counts['skipped_version']} failed={failed} in {elapsed:.1f}s")
        _totals(out, filings)
    return 1 if failed else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="filed_parser", description="Parse cached filings into the filed layer.")
    p.add_argument("--cik", action="append", help="cik (repeatable); default: findings_scope.ciks")
    p.add_argument("--accession", action="append", help="dashed or 18-digit accession (repeatable)")
    p.add_argument("--reparse", action="store_true", help="overwrite existing filing folders")
    p.add_argument("--verify", action="store_true", help="re-parse and compare hashes; write nothing")
    p.add_argument("--out", default="warehouse/data/filed")
    p.add_argument("--raw", default="data/raw/filings")
    p.add_argument("--scope-file", default=str(SCOPE_FILE))
    args = p.parse_args(argv)
    if args.verify and args.reparse:
        p.error("--verify and --reparse cannot be combined")
    print(f"filed_parser version {PARSER_VERSION}")
    return run(args)
