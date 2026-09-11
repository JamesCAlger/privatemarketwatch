"""Agent data-query tool: the B2 agent's READ-ONLY, CIK-SCOPED window into the EXTRACTED data.

The keystone the investigative loop hangs on. The Saratoga FV mismatch was root-caused with
arbitrary DuckDB aggregations over unified holdings + raw staging + companyfacts + the
conservation residual. This gives the (blinded) agent the SAME power, SAFELY:
  - read-only: agent SQL is validated to a single SELECT/WITH; no DDL/DML/PRAGMA/multi-stmt;
  - cik-scoped: each source is materialized PRE-FILTERED to one cik, so the agent literally
    cannot see another filer (no cross-cik haystacking);
  - cached-only + no file/network: after setup, external access is disabled, so agent SQL
    cannot read_parquet/read_csv/ATTACH arbitrary paths even if it tried;
  - bounded: results are row-capped.

Exposed tables (each pre-filtered to the cik):
  holdings        -- unified private_markets_holdings (what the conservation gate sums)
  staging         -- raw bdc_holdings (carries `period` + the `dimensions_raw` hierarchy)
  fund_financials -- companyfacts balance-sheet anchors (investments_at_fair_value, ...)
  conservation    -- conservation_gate_results (the residual to drive to zero -- the SCORE)

The FILING-source analog is scripts/review_agent/evidence_cli.py; this is the EXTRACTED-data
analog. The agent uses BOTH: read the filing (truth) + query the extraction (what we pulled).
ASCII-only.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import duckdb
import pandas as pd

from pipeline import config

# Per-CIK slice cache: the global holdings/staging parquets are ~1.1M/670K rows and the cik
# filter blocks predicate pushdown, so a fresh full scan per query is minutes each. Materialize
# each (cik, source) slice to a tiny parquet ONCE and read that. Keyed by source mtime so a
# refreshed global file invalidates the cache automatically.
_CACHE_DIR = config.OUTPUT_DIR / "agent_investigate" / "_qcache"


def _ensure_cik_cache(name: str, path, cik: str) -> Path:
    cik_n = str(cik).lstrip("0")
    d = _CACHE_DIR / cik_n
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{name}.{int(os.path.getmtime(path))}.parquet"
    if out.exists():
        return out
    p = str(path).replace("\\", "/")
    frm = (f"read_parquet('{p}')" if p.lower().endswith(".parquet")
           else f"read_csv_auto('{p}', sample_size=-1)")
    con = duckdb.connect()
    try:
        con.execute(f"COPY (SELECT * FROM {frm} WHERE ltrim(CAST(cik AS VARCHAR), '0') = '{cik_n}') "
                    f"TO '{out.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    return out

# A single read-only SELECT/WITH only. Forbid DDL/DML, config/PRAGMA, file/attach functions,
# multi-statement (`;`), and comments (which could smuggle the above). Word-boundary anchored
# so column names like `created_at`/`offset` are unaffected.
_FORBIDDEN = re.compile(
    r"(?i)\b(attach|detach|copy|install|load|pragma|set|reset|create|insert|update|delete|"
    r"drop|alter|truncate|export|import|call|read_csv|read_csv_auto|read_parquet|read_json|"
    r"read_text|parquet_scan|csv_scan|glob|system)\b|;|--|/\*|\*/")

SOURCE_NAMES = ("holdings", "staging", "fund_financials", "conservation")


def default_sources() -> dict[str, object]:
    """Map each exposed table to its cached parquet (preferred) or csv on disk."""
    def pick(parq, csv):
        return parq if Path(parq).exists() else csv
    return {
        "holdings": pick(config.UNIFIED_HOLDINGS_PARQUET_FILE, config.UNIFIED_HOLDINGS_FILE),
        "staging": pick(config.BDC_HOLDINGS_PARQUET_FILE, config.BDC_HOLDINGS_FILE),
        "fund_financials": config.FUND_FINANCIALS_FILE,
        "conservation": config.OUTPUT_DIR / "shadow" / "conservation_gate_results.csv",
    }


def validate_sql(sql: str) -> list[str]:
    """Return a list of reasons the query is not an allowed single read-only SELECT."""
    s = (sql or "").strip()
    errs: list[str] = []
    if not s:
        return ["empty query"]
    if not re.match(r"(?i)^\s*(select|with)\b", s):
        errs.append("query must start with SELECT or WITH (read-only)")
    if _FORBIDDEN.search(s):
        errs.append("query contains a forbidden token (DDL/DML/PRAGMA/file-access/comment/`;`)")
    return errs


def _from_clause(conn: duckdb.DuckDBPyConnection, name: str, src) -> str:
    if isinstance(src, pd.DataFrame):
        conn.register(f"_src_{name}", src)
        return f"_src_{name}"
    p = str(src).replace("\\", "/")
    return (f"read_parquet('{p}')" if p.lower().endswith(".parquet")
            else f"read_csv_auto('{p}', sample_size=-1)")


def _materialize(conn: duckdb.DuckDBPyConnection, name: str, src, cik: str) -> bool:
    """Create a TEMP TABLE `name` holding ONLY this cik's rows. Returns True on success."""
    if isinstance(src, (str, Path)):
        if not Path(src).exists():
            return False
        try:
            src = _ensure_cik_cache(name, src, cik)   # tiny per-cik slice, scanned once
        except Exception:
            pass                                       # fall back to scanning the source directly
    frm = _from_clause(conn, name, src)
    cik_norm = str(cik).lstrip("0")
    try:
        conn.execute(
            f"CREATE TEMP TABLE {name} AS SELECT * FROM {frm} "
            f"WHERE ltrim(CAST(cik AS VARCHAR), '0') = '{cik_norm}'")
        return True
    except Exception:
        # source has no `cik` column (shouldn't happen for the four sources) -> skip it
        try:
            conn.execute(f"DROP TABLE IF EXISTS {name}")
        except Exception:
            pass
        return False
    finally:
        if isinstance(src, pd.DataFrame):
            try:
                conn.unregister(f"_src_{name}")
            except Exception:
                pass


def open_session(cik: str, sources: dict | None = None):
    """Build a DuckDB connection with the four cik-scoped temp tables, then LOCK DOWN external
    access. Returns (conn, created_table_names)."""
    sources = sources or default_sources()
    conn = duckdb.connect()
    created = [name for name, src in sources.items() if _materialize(conn, name, src, cik)]
    conn.execute("SET enable_external_access=false")   # one-way: agent SQL cannot touch files
    return conn, created


def _execute(conn: duckdb.DuckDBPyConnection, sql: str, row_cap: int) -> dict:
    errs = validate_sql(sql)
    if errs:
        return {"ok": False, "errors": errs}
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(row_cap + 1)
    except Exception as exc:
        return {"ok": False, "errors": [f"query error: {exc}"]}
    truncated = len(rows) > row_cap
    return {"ok": True, "columns": cols, "rows": [list(r) for r in rows[:row_cap]],
            "row_count": min(len(rows), row_cap), "truncated": truncated}


def query(sql: str, *, cik: str, sources: dict | None = None, row_cap: int = 500) -> dict:
    """Run ONE validated, cik-scoped, read-only SELECT and return capped rows."""
    conn, _ = open_session(cik, sources)
    try:
        return _execute(conn, sql, row_cap)
    finally:
        conn.close()


def describe(*, cik: str, sources: dict | None = None) -> dict:
    """The agent's starting context: available tables + columns, and the conservation residual
    for this cik (the score to drive to zero)."""
    conn, created = open_session(cik, sources)
    try:
        tables = {}
        for t in created:
            try:
                tables[t] = [r[0] for r in conn.execute(f"DESCRIBE {t}").fetchall()]
            except Exception:
                tables[t] = []
        ctx = {}
        if "conservation" in created:
            ctx = _execute(conn, "SELECT rule_name, report_date, value_sum, anchor_value, "
                                 "residual_pct, status FROM conservation "
                                 "ORDER BY rule_name, report_date", row_cap=200)
        return {"cik": str(cik), "tables": tables, "conservation_context": ctx}
    finally:
        conn.close()
