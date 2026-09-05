"""Deterministic per-verdict gate for the match-gold fleet.

The dispatcher runs this after every worker exits, the same way
dispatch_agent_b_workers.ps1 runs validate_leaf_verdicts: a worker that exits 0
but wrote nothing, wrote BOM'd bytes, or wrote an off-schema document must be
counted as a failure, not silently scored later.

Expected edge indices are read from the PACKET (`edges[].edge_index`), not from
`packets_meta/`, so the gate keeps working while the dispatcher holds the meta
sidecars outside the repo for filesystem blinding. The two are equal by
construction in build_packets.write_batch (both enumerate the same resolved
edge list); tests/test_match_gold_packets.py pins that.

Exit 0 = valid, 1 = invalid (errors on stderr), 2 = usage/IO error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.match_verdict_leaf import validate_match_verdict  # noqa: E402


def validate_file(packet_path: Path, verdict_path: Path) -> list[str]:
    """Return a list of error strings; empty means the verdict is valid."""
    if not verdict_path.exists():
        return [f"no verdict written at {verdict_path}"]
    raw = verdict_path.read_bytes()
    if not raw.strip():
        return [f"empty verdict file at {verdict_path}"]
    # utf-8-sig: tolerate a BOM here (score_gold does too) but report it, since a
    # BOM is a reliable signal the worker used a PowerShell redirect rather than
    # apply_patch and may have mangled other bytes as well.
    errs: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        errs.append("verdict has a UTF-8 BOM (worker should write plain UTF-8)")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return errs + [f"unreadable verdict JSON: {exc}"]
    if not isinstance(doc, dict):
        return errs + [f"verdict is {type(doc).__name__}, expected a JSON object"]

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    expected = [e["edge_index"] for e in packet.get("edges", [])]

    # A verdict filed under the wrong packet_id would be scored against the wrong
    # sample row, so treat identity drift as a hard error rather than a warning.
    if doc.get("packet_id") != packet["packet_id"]:
        errs.append(
            f"packet_id mismatch: verdict says {doc.get('packet_id')!r}, "
            f"packet is {packet['packet_id']!r}")
    if doc.get("packet_type") != packet["packet_type"]:
        errs.append(
            f"packet_type mismatch: verdict says {doc.get('packet_type')!r}, "
            f"packet is {packet['packet_type']!r}")

    return errs + validate_match_verdict(doc, expected_edges=expected)


def scan_batch(batch_dir: Path) -> dict:
    """Classify every packet in a batch as valid / invalid / missing.

    One interpreter start for the whole batch: the dispatcher calls this to decide
    what still needs dispatching (so an aborted fleet resumes without re-running
    packets that already produced a good verdict) and again at the end to report.
    Deliberately reads `packets/`, not `worklist.csv`, so it still works while the
    dispatcher holds the worklist outside the repo for blinding.
    """
    packets_dir = batch_dir / "packets"
    verdicts_dir = batch_dir / "verdicts"
    out: dict = {"valid": [], "invalid": {}, "missing": []}
    for packet_path in sorted(packets_dir.glob("*.json")):
        pid = packet_path.stem
        verdict_path = verdicts_dir / f"{pid}.json"
        if not verdict_path.exists():
            out["missing"].append(pid)
            continue
        try:
            errs = validate_file(packet_path, verdict_path)
        except OSError as exc:
            errs = [f"{exc}"]
        if errs:
            out["invalid"][pid] = errs
        else:
            out["valid"].append(pid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--packet", help="path to packets/<pid>.json")
    ap.add_argument("--verdict", help="path to verdicts/<pid>.json")
    ap.add_argument("--scan-batch", help="batch dir; emit JSON status for every packet")
    args = ap.parse_args()

    if args.scan_batch:
        batch_dir = Path(args.scan_batch)
        if not (batch_dir / "packets").is_dir():
            print(f"ERROR: no packets/ under {batch_dir}", file=sys.stderr)
            return 2
        print(json.dumps(scan_batch(batch_dir)))
        return 0

    if not (args.packet and args.verdict):
        ap.error("--packet and --verdict are both required unless --scan-batch is used")

    packet_path = Path(args.packet)
    if not packet_path.exists():
        print(f"ERROR: packet not found: {packet_path}", file=sys.stderr)
        return 2
    try:
        errs = validate_file(packet_path, Path(args.verdict))
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if errs:
        for e in errs:
            print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
