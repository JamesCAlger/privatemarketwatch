"""Snapshot and compare current-cache outputs for Phase 6 parity.

This intentionally does not update the official refactor baseline.  It answers
one narrower question: did the Phase 6 code changes alter outputs when both
sides are rebuilt from the same cached inputs?
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SNAPSHOT_DIR = ROOT / "data" / "snapshots" / "current_cache_pre_phase6"
REPORT_FILE = ROOT / "data" / "output" / "current_cache_phase6_diff_report.json"

UPSTREAM_ARTIFACTS = [
    "data/output/private_markets_holdings.csv",
    "data/output/fund_financials.csv",
    "data/output/position_matches.csv",
    "data/output/position_returns.csv",
    "data/output/index_returns.csv",
]

SQL_SPECS = [
    (
        "classification_index.sql",
        [
            ("pipeline.unified_holdings", "_sql_classify_index"),
            ("pipeline.classification", "_sql_classify_index"),
        ],
    ),
    (
        "classification_exposure_type.sql",
        [
            ("pipeline.unified_holdings", "_sql_classify_exposure_type"),
            ("pipeline.classification", "_sql_classify_exposure_type"),
        ],
    ),
    (
        "classification_asset_class.sql",
        [
            ("pipeline.unified_holdings", "_sql_classify_asset_class"),
            ("pipeline.classification", "_sql_classify_asset_class"),
        ],
    ),
    (
        "bdc_aggregate.sql",
        [
            ("pipeline.unified_holdings", "_sql_is_bdc_aggregate"),
            ("pipeline.bdc_identifier", "_sql_is_bdc_aggregate"),
        ],
    ),
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_path(snapshot_dir: Path, rel_path: str) -> Path:
    return snapshot_dir / "files" / rel_path


def _safe_clean_dir(path: Path) -> None:
    resolved = path.resolve()
    allowed = (ROOT / "data" / "snapshots").resolve()
    if allowed not in resolved.parents and resolved != allowed:
        raise ValueError(f"Refusing to clean outside data/snapshots: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _frontend_artifacts() -> list[str]:
    frontend_data = ROOT / "frontend" / "public" / "data"
    if not frontend_data.exists():
        return []
    return [
        path.relative_to(ROOT).as_posix()
        for path in sorted(frontend_data.rglob("*.json"))
        if path.is_file()
    ]


def _iter_artifacts() -> list[str]:
    return sorted(set(UPSTREAM_ARTIFACTS + _frontend_artifacts()))


def _first_text_diff(left: Path, right: Path) -> str:
    with left.open("r", encoding="utf-8", errors="replace", newline="") as a:
        with right.open("r", encoding="utf-8", errors="replace", newline="") as b:
            for line_no, (left_line, right_line) in enumerate(zip(a, b), start=1):
                if left_line != right_line:
                    return (
                        f"first differing line {line_no}: "
                        f"baseline={left_line[:220].rstrip()} "
                        f"current={right_line[:220].rstrip()}"
                    )
            extra_left = a.readline()
            extra_right = b.readline()
            if extra_left:
                return f"current ended before baseline: {extra_left[:220].rstrip()}"
            if extra_right:
                return f"baseline ended before current: {extra_right[:220].rstrip()}"
    return "no textual diff found"


def _capture_sql(snapshot_dir: Path | None = None) -> list[dict]:
    captured = []
    sql_dir = snapshot_dir / "generated_sql" if snapshot_dir else None
    if sql_dir:
        sql_dir.mkdir(parents=True, exist_ok=True)

    for filename, candidates in SQL_SPECS:
        errors = []
        sql = None
        source = None
        for module_name, func_name in candidates:
            try:
                module = __import__(module_name, fromlist=[func_name])
                sql = getattr(module, func_name)()
                source = f"{module_name}.{func_name}"
                break
            except Exception as exc:
                errors.append(f"{module_name}.{func_name}: {exc}")
        if sql is None:
            captured.append({
                "name": filename,
                "status": "missing",
                "errors": errors,
            })
            continue

        raw = sql.encode("utf-8")
        entry = {
            "name": filename,
            "status": "byte_identical",
            "source": source,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        if sql_dir:
            out = sql_dir / filename
            out.write_bytes(raw)
            entry["snapshot_path"] = out.relative_to(ROOT).as_posix()
        captured.append(entry)
    return captured


def snapshot(snapshot_dir: Path, clean: bool) -> int:
    if not snapshot_dir.is_absolute():
        snapshot_dir = ROOT / snapshot_dir
    if clean:
        _safe_clean_dir(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    artifacts = []
    missing = []
    for rel_path in _iter_artifacts():
        current = ROOT / rel_path
        if not current.exists():
            missing.append(rel_path)
            continue
        dest = _snapshot_path(snapshot_dir, rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current, dest)
        artifacts.append({
            "path": rel_path,
            "snapshot_path": dest.relative_to(ROOT).as_posix(),
            "sha256": _sha256(current),
            "size_bytes": current.stat().st_size,
            "class": "upstream" if rel_path in UPSTREAM_ARTIFACTS else "frontend_json",
        })

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "current-cache pre-Phase-6 parity baseline",
        "snapshot_root": snapshot_dir.relative_to(ROOT).as_posix(),
        "artifact_counts": {
            "snapshotted": len(artifacts),
            "missing": len(missing),
        },
        "missing_artifacts": missing,
        "generated_sql": _capture_sql(snapshot_dir),
        "artifacts": artifacts,
    }
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Snapshot complete: {len(artifacts)} artifacts, "
        f"{len(missing)} missing, manifest {manifest_path.relative_to(ROOT).as_posix()}"
    )
    return 1 if missing else 0


def _csv_summary(con: duckdb.DuckDBPyConnection, path: Path, query: str) -> list[dict]:
    safe_path = str(path).replace("\\", "/").replace("'", "''")
    return con.execute(query.format(path=safe_path)).fetchdf().to_dict("records")


def _summary_map(rows: list[dict], key_cols: tuple[str, ...]) -> dict[tuple, dict]:
    return {tuple(row.get(col) for col in key_cols): row for row in rows}


def _numeric_delta(current: object, baseline: object) -> float | None:
    if current is None and baseline is None:
        return 0.0
    try:
        return (0.0 if current is None else float(current)) - (
            0.0 if baseline is None else float(baseline)
        )
    except (TypeError, ValueError):
        return None


def _is_material_delta(col: str, delta: float | None, current: object, baseline: object) -> bool:
    """Return True for semantic changes that exceed numeric noise."""
    if delta is None:
        return current != baseline
    if col == "row_count" or col.endswith("_count"):
        return delta != 0

    current_f = 0.0 if current is None else float(current)
    baseline_f = 0.0 if baseline is None else float(baseline)
    scale = max(abs(current_f), abs(baseline_f), 1.0)
    return abs(delta) > max(1e-6, scale * 1e-12)


def _compare_summary(
    current_rows: list[dict],
    baseline_rows: list[dict],
    key_cols: tuple[str, ...],
    value_cols: tuple[str, ...],
) -> list[dict]:
    current = _summary_map(current_rows, key_cols)
    baseline = _summary_map(baseline_rows, key_cols)
    deltas = []
    for key in sorted(set(current) | set(baseline), key=lambda x: tuple(str(v) for v in x)):
        current_row = current.get(key, {})
        baseline_row = baseline.get(key, {})
        row = {col: key[idx] for idx, col in enumerate(key_cols)}
        changed = False
        for col in value_cols:
            delta = _numeric_delta(current_row.get(col), baseline_row.get(col))
            row[f"{col}_current"] = current_row.get(col)
            row[f"{col}_baseline"] = baseline_row.get(col)
            row[f"{col}_delta"] = delta
            if _is_material_delta(
                col, delta, current_row.get(col), baseline_row.get(col)
            ):
                changed = True
        if changed:
            deltas.append(row)
    return deltas


def _semantic_report(manifest: dict, snapshot_dir: Path) -> dict:
    queries = {
        "row_count": (
            (),
            ("row_count",),
            "SELECT COUNT(*) AS row_count FROM read_csv('{path}', header=true, all_varchar=true)",
        ),
        "holdings_class_fv": (
            ("index_classification",),
            ("row_count", "fair_value_sum"),
            """
            SELECT COALESCE(index_classification, '') AS index_classification,
                   COUNT(*) AS row_count,
                   SUM(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0)) AS fair_value_sum
            FROM read_csv('{path}', header=true, all_varchar=true)
            GROUP BY 1
            """,
        ),
        "fund_financial_numeric": (
            ("vehicle_type", "source"),
            ("row_count", "net_assets_sum", "nav_sum", "total_return_sum"),
            """
            SELECT COALESCE(vehicle_type, '') AS vehicle_type,
                   COALESCE(source, '') AS source,
                   COUNT(*) AS row_count,
                   SUM(COALESCE(TRY_CAST(net_assets AS DOUBLE), 0)) AS net_assets_sum,
                   SUM(COALESCE(TRY_CAST(nav_per_share AS DOUBLE), 0)) AS nav_sum,
                   SUM(COALESCE(TRY_CAST(total_return_pct AS DOUBLE), 0)) AS total_return_sum
            FROM read_csv('{path}', header=true, all_varchar=true)
            GROUP BY 1, 2
            """,
        ),
        "match_method": (
            ("match_method",),
            ("row_count",),
            """
            SELECT COALESCE(match_method, '') AS match_method,
                   COUNT(*) AS row_count
            FROM read_csv('{path}', header=true, all_varchar=true)
            GROUP BY 1
            """,
        ),
        "position_return": (
            ("index_classification",),
            ("row_count", "begin_fv_sum", "total_return_sum"),
            """
            SELECT COALESCE(index_classification, '') AS index_classification,
                   COUNT(*) AS row_count,
                   SUM(COALESCE(TRY_CAST(begin_fair_value AS DOUBLE), 0)) AS begin_fv_sum,
                   SUM(COALESCE(TRY_CAST(total_return AS DOUBLE), 0)) AS total_return_sum
            FROM read_csv('{path}', header=true, all_varchar=true)
            GROUP BY 1
            """,
        ),
        "index_return": (
            ("index_classification",),
            ("row_count", "constituent_count_sum", "total_begin_fv_sum", "fv_weighted_return_sum"),
            """
            SELECT COALESCE(index_classification, '') AS index_classification,
                   COUNT(*) AS row_count,
                   SUM(COALESCE(TRY_CAST(constituent_count AS DOUBLE), 0)) AS constituent_count_sum,
                   SUM(COALESCE(TRY_CAST(total_begin_fv AS DOUBLE), 0)) AS total_begin_fv_sum,
                   SUM(COALESCE(TRY_CAST(fv_weighted_return AS DOUBLE), 0)) AS fv_weighted_return_sum
            FROM read_csv('{path}', header=true, all_varchar=true)
            GROUP BY 1
            """,
        ),
    }
    artifact_queries = {
        "data/output/private_markets_holdings.csv": ["row_count", "holdings_class_fv"],
        "data/output/fund_financials.csv": ["row_count", "fund_financial_numeric"],
        "data/output/position_matches.csv": ["row_count", "match_method"],
        "data/output/position_returns.csv": ["row_count", "position_return"],
        "data/output/index_returns.csv": ["row_count", "index_return"],
    }
    entries = {entry["path"]: entry for entry in manifest["artifacts"]}
    report: dict[str, object] = {"artifacts": {}}
    con = duckdb.connect()
    try:
        for rel_path, query_names in artifact_queries.items():
            entry = entries.get(rel_path)
            current = ROOT / rel_path
            baseline = ROOT / entry["snapshot_path"] if entry else _snapshot_path(snapshot_dir, rel_path)
            artifact_report = {}
            if not current.exists() or not baseline.exists():
                artifact_report["status"] = "skipped_missing_current_or_baseline"
                report["artifacts"][rel_path] = artifact_report
                continue
            current_sha = _sha256(current)
            if current_sha == entry.get("sha256") and filecmp.cmp(current, baseline, shallow=False):
                for query_name in query_names:
                    artifact_report[query_name] = []
                report["artifacts"][rel_path] = artifact_report
                continue
            for query_name in query_names:
                key_cols, value_cols, query = queries[query_name]
                artifact_report[query_name] = _compare_summary(
                    _csv_summary(con, current, query),
                    _csv_summary(con, baseline, query),
                    key_cols,
                    value_cols,
                )
            report["artifacts"][rel_path] = artifact_report
    finally:
        con.close()
    return report


def diff(snapshot_dir: Path, semantic: bool) -> int:
    if not snapshot_dir.is_absolute():
        snapshot_dir = ROOT / snapshot_dir
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path.relative_to(ROOT).as_posix()}")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    checked = 0

    entries = sorted(
        manifest["artifacts"],
        key=lambda entry: (0 if entry["path"] in UPSTREAM_ARTIFACTS else 1, entry["path"]),
    )
    for entry in entries:
        rel_path = entry["path"]
        current = ROOT / rel_path
        baseline = ROOT / entry["snapshot_path"]
        checked += 1
        if not current.exists():
            failures.append(f"{rel_path}: current file is missing")
            continue
        if not baseline.exists():
            failures.append(f"{rel_path}: snapshot file is missing")
            continue
        current_sha = _sha256(current)
        if current_sha == entry["sha256"] and filecmp.cmp(current, baseline, shallow=False):
            continue
        detail = ""
        if current.suffix.lower() in {".csv", ".json", ".sql"}:
            detail = " (" + _first_text_diff(baseline, current) + ")"
        failures.append(
            f"{rel_path}: differs from current-cache pre-Phase-6 snapshot "
            f"(baseline {entry['sha256']}, current {current_sha}){detail}"
        )

    current_sql = {entry["name"]: entry for entry in _capture_sql(None)}
    for entry in manifest.get("generated_sql", []):
        if entry.get("status") != "byte_identical":
            failures.append(f"generated SQL {entry.get('name')}: missing in snapshot")
            continue
        checked += 1
        current_entry = current_sql.get(entry["name"])
        if not current_entry or current_entry.get("status") != "byte_identical":
            failures.append(f"generated SQL {entry['name']}: missing in current code")
            continue
        if current_entry["sha256"] != entry["sha256"]:
            failures.append(
                f"generated SQL {entry['name']}: differs from snapshot "
                f"(baseline {entry['sha256']}, current {current_entry['sha256']})"
            )

    semantic_deltas = 0
    if semantic:
        report = _semantic_report(manifest, snapshot_dir)
        REPORT_FILE.write_text(
            json.dumps(report, indent=2, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        for artifact_report in report["artifacts"].values():
            if isinstance(artifact_report, dict):
                semantic_deltas += sum(
                    len(rows) for rows in artifact_report.values() if isinstance(rows, list)
                )
        print(f"Semantic report: {REPORT_FILE.relative_to(ROOT).as_posix()}")
        print(f"Semantic delta rows: {semantic_deltas}")

    if failures:
        print(f"Diff failed: {len(failures)} divergent artifact(s), {checked} checked")
        for failure in failures[:80]:
            print(f"- {failure}")
        if len(failures) > 80:
            print(f"... {len(failures) - 80} more")
        return 1

    print(f"Diff clean: {checked} checked")
    return 0 if semantic_deltas == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    snapshot_parser.add_argument("--clean", action="store_true")

    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    diff_parser.add_argument("--semantic", action="store_true")

    args = parser.parse_args()
    if args.command == "snapshot":
        return snapshot(args.snapshot_dir, clean=args.clean)
    if args.command == "diff":
        return diff(args.snapshot_dir, semantic=args.semantic)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
