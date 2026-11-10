"""The rows a finding flags, as keys a disposition's ``rows`` list can name.

A disposition accepted after the owner's ruling of 2026-11-10 (D-253) names the rows it covers.
The findings ledger closes a finding with such an entry only when every row the finding flags is
among the named rows, so a recurrence of the same rule on other rows of the same fund-quarter stays
open. This module answers "which rows does this finding flag" from the build's own outputs.

Keys (strings, compared exactly):
  ``row_id:<ROW-...>``                 a published holdings row (hash of accession + context; stable
                                       across rebuilds of the same filing)
  ``source_identifier:<identifier>``   a source row with no published row (SRC_* rules), by its raw
                                       investment identifier, whitespace folded and case folded
  ``fund_level``                       the rule tests a fund-quarter fact, not rows

Resolved engines:
  row_validation        ``row_validation_issues.parquet`` (or .csv): row_id; else, for SRC_* rules,
                        the source identifier; else (a fund-quarter rule) ``fund_level``
  provenance_reverify   ``provenance_ledger.parquet``: row_id where reason_code = rule name
  FUND_LEVEL_ENGINES    always ``fund_level``

Any other engine, a missing artifact, or a finding with no flagged row in the artifact returns None:
the rows cannot be resolved, and a row-scoped disposition then does not close the finding (fail
closed). Read-only.
"""
from __future__ import annotations

import re
from pathlib import Path

FUND_LEVEL = "fund_level"
FUND_LEVEL_ENGINES = frozenset({"fund_financials", "gav_recon", "fund_strategy", "conservation"})
RESOLVED_ENGINES = frozenset({"row_validation", "provenance_reverify"}) | FUND_LEVEL_ENGINES


def norm_identifier(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def descriptor_key(row: dict) -> str | None:
    """The key one ``rows`` descriptor names, or None when it names none."""
    if not isinstance(row, dict):
        return None
    if row.get("fund_level") is True:
        return FUND_LEVEL
    if str(row.get("row_id") or "").strip():
        return "row_id:" + str(row["row_id"]).strip()
    if str(row.get("source_identifier") or "").strip():
        return "source_identifier:" + norm_identifier(row["source_identifier"])
    return None


def _sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


class FlaggedRows:
    """Callable ``(cik, engine, rule_name, quarter) -> frozenset[str] | None`` over one output dir.

    Queries are made per (engine, cik) on first use and cached, so a ledger with no row-scoped
    disposition reads nothing."""

    def __init__(self, output_dir: Path | None):
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self._cache: dict[tuple[str, str], dict[tuple[str, str], set[str]]] = {}

    def _artifact(self, stem: str) -> Path | None:
        if self.output_dir is None:
            return None
        for suffix in (".parquet", ".csv"):
            path = self.output_dir / (stem + suffix)
            if path.exists():
                return path
        return None

    @staticmethod
    def _relation(path: Path) -> str:
        if path.suffix == ".parquet":
            return "read_parquet('%s')" % _sql_path(path)
        return "read_csv_auto('%s', all_varchar=true, sample_size=-1)" % _sql_path(path)

    def _load(self, engine: str, cik: str) -> dict[tuple[str, str], set[str]]:
        import duckdb
        found: dict[tuple[str, str], set[str]] = {}
        con = duckdb.connect()
        try:
            if engine == "row_validation":
                path = self._artifact("row_validation_issues")
                if path is None:
                    return found
                rows = con.execute(
                    "SELECT rule_id, substr(CAST(report_date AS VARCHAR), 1, 10), row_id, value "
                    "FROM %s WHERE lpad(CAST(cik AS VARCHAR), 10, '0') = ?" % self._relation(path), [cik]).fetchall()
                for rule, quarter, row_id, value in rows:
                    if str(row_id or "").strip():
                        key = "row_id:" + str(row_id).strip()
                    elif str(rule or "").startswith("SRC_") and str(value or "").strip():
                        key = "source_identifier:" + norm_identifier(value)
                    else:
                        key = FUND_LEVEL
                    found.setdefault((str(rule), str(quarter)), set()).add(key)
            elif engine == "provenance_reverify":
                path = self._artifact("provenance_ledger")
                if path is None:
                    return found
                rows = con.execute(
                    "SELECT DISTINCT reason_code, substr(CAST(report_date AS VARCHAR), 1, 10), row_id "
                    "FROM %s WHERE lpad(CAST(cik AS VARCHAR), 10, '0') = ? AND row_id IS NOT NULL "
                    "AND reason_code NOT IN ('verified', 'unchecked_trivial')" % self._relation(path), [cik]).fetchall()
                for rule, quarter, row_id in rows:
                    found.setdefault((str(rule), str(quarter)), set()).add("row_id:" + str(row_id).strip())
        finally:
            con.close()
        return found

    def __call__(self, cik, engine, rule_name, quarter) -> frozenset[str] | None:
        engine = str(engine or "")
        if engine in FUND_LEVEL_ENGINES:
            return frozenset({FUND_LEVEL})
        if engine not in RESOLVED_ENGINES:
            return None
        cik = str(cik or "").zfill(10)
        if (engine, cik) not in self._cache:
            self._cache[(engine, cik)] = self._load(engine, cik)
        keys = self._cache[(engine, cik)].get((str(rule_name or ""), str(quarter or "")[:10]))
        return frozenset(keys) if keys else None
