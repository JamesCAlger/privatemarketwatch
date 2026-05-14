"""Snapshot deterministic pipeline outputs for refactor parity checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "data" / "output"
FRONTEND_DATA_DIR = ROOT / "frontend" / "public" / "data"
SNAPSHOT_DIR = ROOT / "data" / "snapshots" / "baseline"
MANIFEST_FILE = ROOT / "docs" / "refactoring" / "baseline_manifest.json"

EXCLUDE_NAMES = {
    "pipeline.log": "log file with run-specific timestamps",
}
EXCLUDE_SUFFIXES = {
    ".log": "operator log artifact",
    ".md": "investigation note, not a deterministic data artifact",
    ".txt": "ad-hoc validation text artifact",
}
EXCLUDE_PREFIXES = {
    "llm_": "LLM review output can depend on model/API behavior",
    "gics_label_cache": "GICS classification cache can depend on external model/API behavior",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _artifact_class(path: Path) -> str:
    if path.is_relative_to(OUTPUT_DIR):
        return "data_output"
    if path.parent == FRONTEND_DATA_DIR:
        return "frontend_top_level_json"
    if path.is_relative_to(FRONTEND_DATA_DIR / "fund_details"):
        return "frontend_fund_detail_json"
    return "unknown"


def _exclusion_reason(path: Path) -> str | None:
    name = path.name.lower()
    if name in EXCLUDE_NAMES:
        return EXCLUDE_NAMES[name]
    for prefix, reason in EXCLUDE_PREFIXES.items():
        if name.startswith(prefix):
            return reason
    for suffix, reason in EXCLUDE_SUFFIXES.items():
        if name.endswith(suffix):
            return reason
    return None


def _iter_artifacts() -> list[Path]:
    paths: list[Path] = []
    if OUTPUT_DIR.exists():
        paths.extend(p for p in OUTPUT_DIR.rglob("*") if p.is_file())
    if FRONTEND_DATA_DIR.exists():
        paths.extend(p for p in FRONTEND_DATA_DIR.glob("*.json") if p.is_file())
        fund_details = FRONTEND_DATA_DIR / "fund_details"
        if fund_details.exists():
            paths.extend(p for p in fund_details.rglob("*.json") if p.is_file())
    return sorted(set(paths), key=lambda p: p.relative_to(ROOT).as_posix())


def _capture_generated_sql() -> list[dict[str, str]]:
    sql_dir = SNAPSHOT_DIR / "generated_sql"
    sql_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        ("classification_index.sql", "pipeline.unified_holdings", "_sql_classify_index"),
        ("classification_exposure_type.sql", "pipeline.unified_holdings", "_sql_classify_exposure_type"),
        ("classification_asset_class.sql", "pipeline.unified_holdings", "_sql_classify_asset_class"),
        ("bdc_aggregate.sql", "pipeline.unified_holdings", "_sql_is_bdc_aggregate"),
    ]
    captured: list[dict[str, str]] = []
    for filename, module_name, func_name in specs:
        try:
            module = __import__(module_name, fromlist=[func_name])
            sql = getattr(module, func_name)()
        except Exception as exc:
            captured.append({
                "name": filename,
                "status": "excluded_with_reason",
                "reason": f"could not import/call {module_name}.{func_name}: {exc}",
            })
            continue
        out = sql_dir / filename
        out.write_text(sql, encoding="utf-8", newline="\n")
        captured.append({
            "name": filename,
            "status": "byte_identical",
            "sha256": _sha256(out),
            "size_bytes": out.stat().st_size,
        })
    return captured


def snapshot(clean: bool = False) -> dict:
    if clean and SNAPSHOT_DIR.exists():
        shutil.rmtree(SNAPSHOT_DIR)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)

    artifacts = []
    for path in _iter_artifacts():
        rel = path.relative_to(ROOT).as_posix()
        reason = _exclusion_reason(path)
        entry = {
            "path": rel,
            "artifact_class": _artifact_class(path),
            "size_bytes": path.stat().st_size,
        }
        if reason:
            entry.update({
                "status": "excluded_with_reason",
                "reason": reason,
                "sha256": _sha256(path),
            })
        else:
            dest = SNAPSHOT_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            entry.update({
                "status": "byte_identical",
                "sha256": _sha256(path),
                "snapshot_path": dest.relative_to(ROOT).as_posix(),
            })
        artifacts.append(entry)

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git(["rev-parse", "HEAD"]),
        "git_status_short": _git(["status", "--short"]).splitlines(),
        "snapshot_root": SNAPSHOT_DIR.relative_to(ROOT).as_posix(),
        "artifact_counts": {
            "total": len(artifacts),
            "byte_identical": sum(a["status"] == "byte_identical" for a in artifacts),
            "excluded_with_reason": sum(a["status"] == "excluded_with_reason" for a in artifacts),
        },
        "generated_sql": _capture_generated_sql(),
        "artifacts": artifacts,
    }
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="remove existing baseline snapshot first")
    args = parser.parse_args()
    manifest = snapshot(clean=args.clean)
    counts = manifest["artifact_counts"]
    print(
        "Snapshot complete: "
        f"{counts['byte_identical']} included, "
        f"{counts['excluded_with_reason']} excluded, "
        f"{counts['total']} total"
    )
    print(f"Manifest: {MANIFEST_FILE.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
