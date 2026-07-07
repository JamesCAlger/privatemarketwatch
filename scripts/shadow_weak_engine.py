"""Parametric field-validity WEAK gate engine (read-only shadow).

The weak counterpart to the three tight engines. Covers the simple field-validity
families from the validation inventory (column_validation C/X/FX-series, oracle
F-series): range / sign / enum / format / date / fill. These are NOT tight checks
-- they are plausibility flags, not reconciliations -- so they emit status `warn`
(never `fail`) and enforcement `flag` (never blocking). A weak warn is a signal
and a quality-tier input; it must never gate.

A check is data: a WeakRule names the table, kind, column(s), gate (rows to
evaluate) and the OK predicate (or fill threshold). The engine rolls up per
(cik, report_date) to status pass|warn.

Read-only; writes only to data/output/shadow/.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

from pipeline.config import (
    OUTPUT_DIR,
    OVERRIDES_DIR,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shadow_weak_engine")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
_CIK_RE = re.compile(r"^\d{10}$")


@dataclass(frozen=True)
class WeakRule:
    name: str
    kind: str            # 'row' (per-row predicate, rolled up) | 'fill' (coverage)
    gate_sql: str        # which rows to evaluate (e.g. "interest_rate IS NOT NULL")
    # row kind: holds_sql is the OK predicate. fill kind: present_sql + threshold.
    holds_sql: str = "TRUE"
    present_sql: str = "TRUE"
    threshold: float = 0.0
    min_n: int = 1
    note: str = ""
    tier: str = "weak"
    enforcement: str = "flag"


# ---------------------------------------------------------------------------
# Per-column FORMAT/TYPE contract -- the single declarative source of each
# column's expected format (consolidates the scattered C-series checks +
# ENUM_VALUES). type in {decimal, enum, string_len, string_exact, pattern, date}.
# Enum values mirror pipeline/column_validation.ENUM_VALUES.
# ---------------------------------------------------------------------------
COLUMN_FORMAT_CONTRACT: dict[str, dict] = {
    "source":              {"type": "enum", "values": ["bdc", "nport", "html"]},
    "cik":                 {"type": "pattern", "regex": "^[0-9]{10}$"},
    "report_date":         {"type": "date"},
    "entity_name":         {"type": "string_len", "min": 1, "max": 200},
    "issuer_name":         {"type": "string_len", "min": 3, "max": 300},
    "cusip":               {"type": "string_exact", "len": 9},
    "isin":                {"type": "string_exact", "len": 12},
    "fair_value":          {"type": "decimal", "min": -1e9, "max": 3e9},   # FV may be negative (shorts); cap $3B/row
    # cost min widened 2026-07-05: negative amortized cost on unfunded-
    # commitment marks is filer presentation (ens2: fmt_cost 72% FP, and 100%
    # of its firings duplicated C107's negative-cost rows). Negative-cost
    # review signal lives in column_validation C107.
    "cost":                {"type": "decimal", "min": -3e9, "max": 3e9},
    "principal_amount":    {"type": "decimal", "min": 0,    "max": 1e11},
    "principal_amount_usd":{"type": "decimal", "min": 0,    "max": 1e11},
    "shares_held":         {"type": "decimal", "min": 0,    "max": 1e12},
    "interest_rate":       {"type": "decimal", "min": 0,    "max": 25},
    "basis_spread":        {"type": "decimal", "min": 0,    "max": 15},
    "pik_rate":            {"type": "decimal", "min": 0,    "max": 20},
    # pct min widened 2026-07-05: negative pct is filer presentation on
    # negative-FV rows / negative-NAV quarters (ens2: 86% FP; all firings
    # duplicated C404). >100 stays flagged here and as X09 in the strong lane.
    "pct_of_net_assets":   {"type": "decimal", "min": -100, "max": 100},   # per-row contract; concentration is a separate semantic rule
    "exposure_type":       {"type": "enum", "values": ["DIRECT", "FUND", "LIQUID"]},
    "asset_class":         {"type": "enum", "values": ["CASH", "HEDGE_FUND", "OTHER",
                            "PRIVATE_CREDIT", "PRIVATE_EQUITY", "REAL_ESTATE", "STRUCTURED_CREDIT"]},
    "index_classification":{"type": "enum", "values": ["CASH", "COMMON_EQUITY", "DIRECT_LENDING",
                            "DIRECT_REAL_ESTATE", "HEDGE_FUND", "PREFERRED_EQUITY", "PRIVATE_CREDIT_FUND",
                            "PRIVATE_EQUITY_FUND", "REAL_ESTATE_FUND", "STRUCTURED_CREDIT", "UNCLASSIFIED"]},
    "coupon_type":         {"type": "enum", "values": ["Fixed", "Floating", "Variable"]},
    "maturity_date":       {"type": "date", "sentinel": "9999-12-31"},
}


def _present(col: str) -> str:
    return f"{col} IS NOT NULL AND trim(CAST({col} AS VARCHAR)) <> ''"


def _contract_rules() -> list[WeakRule]:
    """Generate one format/type WeakRule per column from the contract."""
    out: list[WeakRule] = []
    for col, spec in COLUMN_FORMAT_CONTRACT.items():
        t = spec["type"]
        if t == "decimal":
            holds = (f"TRY_CAST({col} AS DOUBLE) IS NOT NULL "
                     f"AND TRY_CAST({col} AS DOUBLE) BETWEEN {spec['min']:g} AND {spec['max']:g}")
            note = f"numeric in [{spec['min']:g},{spec['max']:g}]"
        elif t == "enum":
            vals = ", ".join(f"'{v}'" for v in spec["values"])
            holds = f"CAST({col} AS VARCHAR) IN ({vals})"
            note = f"enum ({len(spec['values'])} values)"
        elif t == "string_len":
            holds = f"length(CAST({col} AS VARCHAR)) BETWEEN {spec['min']} AND {spec['max']}"
            note = f"length [{spec['min']},{spec['max']}]"
        elif t == "string_exact":
            holds = f"length(CAST({col} AS VARCHAR)) = {spec['len']}"
            note = f"length = {spec['len']}"
        elif t == "pattern":
            holds = f"regexp_matches(CAST({col} AS VARCHAR), '{spec['regex']}')"
            note = f"matches {spec['regex']}"
        elif t == "date":
            holds = f"TRY_CAST({col} AS DATE) IS NOT NULL"
            if spec.get("sentinel"):
                holds += f" OR CAST({col} AS VARCHAR) = '{spec['sentinel']}'"
            note = "parses as date" + (" (or sentinel)" if spec.get("sentinel") else "")
        else:
            continue
        out.append(WeakRule(f"fmt_{col}", "row", _present(col), holds_sql=holds, note=note))
    return out


# Semantic weak rules (beyond pure column format).
SEMANTIC_RULES: list[WeakRule] = [
    # Gate restricted to non-negative pct 2026-07-05: the 0-25 band made this
    # rule fire on every negative-pct row too (6,737 of its 6,821 firings were
    # duplicates of the negative-pct family; ens2 FP 73%). Only genuine >25%
    # concentration remains (84 rows).
    WeakRule("pct_position_concentration", "row",
             "pct_of_net_assets IS NOT NULL AND TRY_CAST(pct_of_net_assets AS DOUBLE) >= 0",
             holds_sql="TRY_CAST(pct_of_net_assets AS DOUBLE) <= 25",
             note="per-position pct <= 25% (concentration flag)"),
    WeakRule("maturity_not_past", "row",
             "index_classification = 'DIRECT_LENDING' AND maturity_date IS NOT NULL "
             "AND TRY_CAST(maturity_date AS DATE) IS NOT NULL "
             "AND CAST(maturity_date AS VARCHAR) <> '9999-12-31'",
             holds_sql="TRY_CAST(maturity_date AS DATE) >= TRY_CAST(report_date AS DATE)",
             note="DL maturity >= report_date"),
    WeakRule("dl_rate_fill", "fill", "index_classification = 'DIRECT_LENDING'",
             present_sql="interest_rate IS NOT NULL OR basis_spread IS NOT NULL",
             threshold=0.80, min_n=10, note="DL rows with rate/spread >= 80%"),
]

RULES: list[WeakRule] = _contract_rules() + SEMANTIC_RULES


def _unified() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem))


def ensure_base(con: duckdb.DuckDBPyConnection) -> None:
    if con.execute("SELECT count(*) FROM information_schema.tables "
                   "WHERE table_name='weak_base'").fetchone()[0]:
        return
    # cik + report_date are the keys (cast to VARCHAR); every other contract
    # column is selected RAW (the generated holds do their own TRY_CAST).
    extra = [c for c in COLUMN_FORMAT_CONTRACT if c not in ("cik", "report_date")]
    select = ("CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date, "
              + ", ".join(extra))
    con.execute(
        f"""
        CREATE TABLE weak_base AS
        SELECT {select}
        FROM {_unified()}
        WHERE bdc_dimensions_raw IS NOT NULL
          AND CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)
        """
    )


def run_rule(con: duckdb.DuckDBPyConnection, rule: WeakRule) -> None:
    if rule.kind == "row":
        con.execute(
            f"""
            CREATE OR REPLACE TABLE result_{rule.name} AS
            WITH e AS (
                SELECT cik, report_date, ({rule.holds_sql}) AS holds
                FROM weak_base WHERE ({rule.gate_sql})
            )
            SELECT '{rule.name}' AS rule_name, '{rule.tier}' AS tier,
                   '{rule.enforcement}' AS enforcement, cik, report_date,
                   count(*) AS n_units,
                   sum(CASE WHEN NOT holds THEN 1 ELSE 0 END) AS n_violate,
                   CASE WHEN sum(CASE WHEN NOT holds THEN 1 ELSE 0 END) > 0 THEN 'warn' ELSE 'pass' END AS status,
                   round(100.0*sum(CASE WHEN NOT holds THEN 1 ELSE 0 END)/count(*), 2) AS metric
            FROM e GROUP BY cik, report_date
            """
        )
    elif rule.kind == "fill":
        con.execute(
            f"""
            CREATE OR REPLACE TABLE result_{rule.name} AS
            WITH e AS (
                SELECT cik, report_date, ({rule.present_sql}) AS present
                FROM weak_base WHERE ({rule.gate_sql})
            )
            SELECT '{rule.name}' AS rule_name, '{rule.tier}' AS tier,
                   '{rule.enforcement}' AS enforcement, cik, report_date,
                   count(*) AS n_units,
                   sum(CASE WHEN NOT present THEN 1 ELSE 0 END) AS n_violate,
                   CASE WHEN avg(CASE WHEN present THEN 1.0 ELSE 0 END) < {rule.threshold} THEN 'warn' ELSE 'pass' END AS status,
                   round(100.0*avg(CASE WHEN present THEN 1.0 ELSE 0 END), 1) AS metric
            FROM e GROUP BY cik, report_date HAVING count(*) >= {rule.min_n}
            """
        )
    else:
        raise ValueError(f"unknown weak kind {rule.kind}")


def main(argv: list[str] | None = None) -> int:
    ciks = wrapped_ciks()
    if not ciks:
        logger.error("no wrapper CIK configs in %s", WRAPPER_DIR)
        return 1
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])
    ensure_base(con)
    logger.info("weak engine: cohort %d CIKs, %d rules", len(ciks), len(RULES))

    for r in RULES:
        run_rule(con, r)

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out = SHADOW_DIR / "weak_gate_results.csv"
    union = " UNION ALL ".join(
        f"SELECT rule_name, tier, enforcement, cik, report_date, status, metric, n_units, n_violate "
        f"FROM result_{r.name}" for r in RULES
    )
    con.execute(
        f"COPY (SELECT * FROM ({union}) ORDER BY rule_name, status DESC, metric DESC) "
        f"TO '{out.as_posix()}' (HEADER, DELIMITER ',')"
    )
    logger.info("wrote %s", out)

    logger.info("weak field-validity gate (per CIK-quarter; status pass|warn):")
    for r in RULES:
        row = con.execute(
            f"SELECT count(*), sum(CASE WHEN status='warn' THEN 1 ELSE 0 END), "
            f"sum(n_violate), sum(n_units) FROM result_{r.name}"
        ).fetchone()
        n_cq, n_warn, n_viol, n_units = (row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0)
        rate = (100.0 * n_warn / n_cq) if n_cq else 0.0
        logger.info("  %-28s cik-qtrs=%4d  warn=%4d (%.1f%%)  rows=%7d viol=%6d   [%s]",
                    r.name, n_cq, n_warn, rate, n_units, n_viol, r.note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
