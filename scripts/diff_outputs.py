"""Compare current pipeline outputs against the refactor baseline snapshot."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import sys
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MANIFEST_FILE = ROOT / "docs" / "refactoring" / "baseline_manifest.json"
SQL_SPECS = [
    ("classification_index.sql", "pipeline.classification", "_sql_classify_index"),
    ("classification_exposure_type.sql", "pipeline.classification", "_sql_classify_exposure_type"),
    ("classification_asset_class.sql", "pipeline.classification", "_sql_classify_asset_class"),
    ("bdc_aggregate.sql", "pipeline.bdc_identifier", "_sql_is_bdc_aggregate"),
]
SEMANTIC_REPORT_FILE = ROOT / "data" / "output" / "semantic_diff_report.json"
SEMANTIC_ARTIFACTS = {
    "holdings": "data/output/private_markets_holdings.csv",
    "matches": "data/output/position_matches.csv",
    "position_returns": "data/output/position_returns.csv",
    "index_returns": "data/output/index_returns.csv",
    "fund_financials": "data/output/fund_financials.csv",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_csv_diff(left: Path, right: Path) -> str:
    with left.open("r", encoding="utf-8", errors="replace", newline="") as a:
        with right.open("r", encoding="utf-8", errors="replace", newline="") as b:
            for line_no, (la, lb) in enumerate(zip(a, b), start=1):
                if la != lb:
                    return (
                        f"first differing line {line_no}\n"
                        f"  baseline: {la[:240].rstrip()}\n"
                        f"  current:  {lb[:240].rstrip()}"
                    )
            extra_a = a.readline()
            extra_b = b.readline()
            if extra_a:
                return f"current ended before baseline; next baseline line: {extra_a[:240].rstrip()}"
            if extra_b:
                return f"baseline ended before current; next current line: {extra_b[:240].rstrip()}"
    return "no textual row diff found"


def _manifest_entry(manifest: dict, rel_path: str) -> dict | None:
    for entry in manifest.get("artifacts", []):
        if entry.get("path") == rel_path:
            return entry
    return None


def _csv_summary(con: duckdb.DuckDBPyConnection, path: Path, query: str) -> list[dict]:
    safe_path = str(path).replace("\\", "/").replace("'", "''")
    return con.execute(query.format(path=safe_path)).fetchdf().to_dict("records")


def _summary_map(rows: list[dict], key_cols: tuple[str, ...]) -> dict[tuple, dict]:
    result = {}
    for row in rows:
        key = tuple(row.get(col) for col in key_cols)
        result[key] = row
    return result


def _numeric_delta(current: object, baseline: object) -> float | None:
    if current is None and baseline is None:
        return 0.0
    try:
        c = 0.0 if current is None else float(current)
        b = 0.0 if baseline is None else float(baseline)
    except (TypeError, ValueError):
        return None
    return c - b


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
    for key in sorted(set(current) | set(baseline), key=lambda x: tuple("" if v is None else str(v) for v in x)):
        cur = current.get(key, {})
        base = baseline.get(key, {})
        row = {col: key[i] for i, col in enumerate(key_cols)}
        changed = False
        for col in value_cols:
            delta = _numeric_delta(cur.get(col), base.get(col))
            row[f"{col}_current"] = cur.get(col)
            row[f"{col}_baseline"] = base.get(col)
            row[f"{col}_delta"] = delta
            if _is_material_delta(col, delta, cur.get(col), base.get(col)):
                changed = True
        if changed:
            deltas.append(row)
    return deltas


def semantic_diff(manifest: dict) -> int:
    """Write and print semantic deltas for the high-risk refactor artifacts."""
    con = duckdb.connect()
    report: dict[str, object] = {"artifacts": {}}

    queries = {
        "holdings_row_count": (
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
    }

    artifact_queries = {
        "holdings": ["holdings_row_count", "holdings_class_fv"],
        "matches": ["match_method"],
        "position_returns": ["position_return"],
        "index_returns": ["index_return"],
        "fund_financials": ["fund_financial_numeric"],
    }

    for artifact, rel_path in SEMANTIC_ARTIFACTS.items():
        entry = _manifest_entry(manifest, rel_path)
        current = ROOT / rel_path
        baseline = ROOT / entry["snapshot_path"] if entry and entry.get("snapshot_path") else None
        artifact_report = {}
        if not current.exists() or baseline is None or not baseline.exists():
            artifact_report["status"] = "skipped_missing_current_or_baseline"
            report["artifacts"][artifact] = artifact_report
            continue
        if _sha256(current) == entry.get("sha256") and filecmp.cmp(current, baseline, shallow=False):
            for query_name in artifact_queries[artifact]:
                artifact_report[query_name] = []
            report["artifacts"][artifact] = artifact_report
            continue

        for query_name in artifact_queries[artifact]:
            key_cols, value_cols, query = queries[query_name]
            cur_rows = _csv_summary(con, current, query)
            base_rows = _csv_summary(con, baseline, query)
            artifact_report[query_name] = _compare_summary(
                cur_rows,
                base_rows,
                key_cols,
                value_cols,
            )
        report["artifacts"][artifact] = artifact_report

    con.close()
    SEMANTIC_REPORT_FILE.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"Semantic diff report: {SEMANTIC_REPORT_FILE.relative_to(ROOT).as_posix()}")
    for artifact, artifact_report in report["artifacts"].items():
        if artifact_report.get("status"):
            print(f"- {artifact}: {artifact_report['status']}")
            continue
        changed = sum(len(v) for v in artifact_report.values() if isinstance(v, list))
        print(f"- {artifact}: {changed} semantic delta row(s)")
    return 0


def diff(compare_sql: bool = True, semantic: bool = False) -> int:
    if not MANIFEST_FILE.exists():
        print(f"Missing manifest: {MANIFEST_FILE.relative_to(ROOT).as_posix()}")
        return 2
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    failures: list[str] = []
    checked = 0
    skipped = 0

    for entry in manifest.get("artifacts", []):
        if entry.get("status") != "byte_identical":
            skipped += 1
            continue
        rel = entry["path"]
        current = ROOT / rel
        baseline = ROOT / entry["snapshot_path"]
        checked += 1
        if not current.exists():
            failures.append(f"{rel}: current file is missing")
            continue
        if not baseline.exists():
            failures.append(f"{rel}: baseline snapshot is missing")
            continue
        current_sha = _sha256(current)
        if current_sha == entry["sha256"] and filecmp.cmp(current, baseline, shallow=False):
            continue
        detail = ""
        if current.suffix.lower() == ".csv":
            detail = "\n" + _first_csv_diff(baseline, current)
        failures.append(
            f"{rel}: differs from baseline "
            f"(baseline {entry['sha256']}, current {current_sha}){detail}"
        )

    if compare_sql:
        generated = {}
        for filename, module_name, func_name in SQL_SPECS:
            try:
                module = __import__(module_name, fromlist=[func_name])
                generated[filename] = getattr(module, func_name)().encode("utf-8")
            except Exception as exc:
                failures.append(f"generated SQL {filename}: could not import/call {module_name}.{func_name}: {exc}")
        for entry in manifest.get("generated_sql", []):
            if entry.get("status") != "byte_identical":
                continue
            rel = f"data/snapshots/baseline/generated_sql/{entry['name']}"
            path = ROOT / rel
            checked += 1
            if not path.exists():
                failures.append(f"{rel}: SQL snapshot is missing")
                continue
            if _sha256(path) != entry["sha256"]:
                failures.append(f"{rel}: SQL snapshot changed on disk")
                continue
            current_sql = generated.get(entry["name"])
            if current_sql is None:
                continue
            digest = hashlib.sha256(current_sql).hexdigest()
            if digest != entry["sha256"]:
                failures.append(
                    f"generated SQL {entry['name']}: differs from baseline "
                    f"(baseline {entry['sha256']}, current {digest})"
                )

    if semantic:
        semantic_diff(manifest)

    if failures:
        print(f"Diff failed: {len(failures)} divergent artifact(s), {checked} checked, {skipped} skipped")
        for failure in failures[:50]:
            print(f"- {failure}")
        if len(failures) > 50:
            print(f"... {len(failures) - 50} more")
        return 1

    print(f"Diff clean: {checked} checked, {skipped} explicitly skipped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-sql", action="store_true", help="skip generated SQL snapshot checks")
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="also write a semantic delta report for high-risk CSV artifacts",
    )
    args = parser.parse_args()
    return diff(compare_sql=not args.no_sql, semantic=args.semantic)


if __name__ == "__main__":
    raise SystemExit(main())
