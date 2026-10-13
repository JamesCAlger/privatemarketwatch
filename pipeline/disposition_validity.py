"""Validity checks that let a standing disposition reach a quarter nobody reviewed.

A disposition names the fund-quarters that were looked at (``pipeline.finding_dispositions``). An
entry may also carry::

    "carry_forward": {"from": "2026-06-30", "check": "<kind>", "params": {...}}

It then covers a quarter on or after ``from`` only when the named check passes on that
fund-quarter's own build outputs. The check restates the disposition's reason as a test of every
flagged row, so a quarter where the reason has stopped fitting stays open and the result names the
rows that broke it. No result for a fund-quarter means no cover (fail closed).

Kinds:

``values_as_filed``          params ``fields``. Every row the rule flags publishes each field as
                             the filed fact (provenance re-verifier reason ``verified``).
``no_rate_in_source``        Every row the rule flags has no rate or spread fact in the filing and
                             is explained: undrawn (fair value at or below zero, or a negative
                             cost), on non-accrual, or a PIK rate is published.
``missing_source_rows_known`` params ``patterns`` (regexes), ``tolerance_m`` (default 0.5). Every
                             blocking source row with no published position matches a listed
                             pattern, and published fair value excluding cash equals the filed
                             investments total within the tolerance.

``no_principal_in_source``   params ``requires_count`` (default true). Every flagged row is published,
                             has no principal fact among its filed facts and publishes no principal;
                             with ``requires_count`` it also carries a unit count (the filer reports
                             the position in units). A row that gains a principal tag fails.

Read-only on the build outputs. Results: one row per (disposition, fund, quarter).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import duckdb

KINDS = ("values_as_filed", "no_rate_in_source", "missing_source_rows_known", "no_principal_in_source")
RESULT_COLUMNS = ["disposition_id", "cik", "report_date", "check", "passed", "rows_tested", "rows_failing",
                  "failing_fair_value_m", "detail"]
_FIELDS = ("fair_value", "cost", "principal_amount", "shares_held", "interest_rate", "basis_spread", "pik_rate")
_MAX_NAMED = 5


def validate_carry_forward(spec) -> list[str]:
    """Problems with one ``carry_forward`` object; empty when it is valid."""
    if not isinstance(spec, dict):
        return ["carry_forward must be an object"]
    errs = []
    start = str(spec.get("from") or "")
    if len(start) != 10 or start[4] != "-" or start[7] != "-":
        errs.append("carry_forward.from must be YYYY-MM-DD")
    kind = spec.get("check")
    if kind not in KINDS:
        errs.append("carry_forward.check must be one of " + ", ".join(KINDS))
    params = spec.get("params", {})
    if not isinstance(params, dict):
        errs.append("carry_forward.params must be an object")
        return errs
    if kind == "values_as_filed":
        fields = params.get("fields")
        if not isinstance(fields, list) or not fields or not all(f in _FIELDS for f in fields):
            errs.append("values_as_filed needs params.fields from " + ", ".join(_FIELDS))
    if kind == "no_principal_in_source" and not isinstance(params.get("requires_count", True), bool):
        errs.append("no_principal_in_source: params.requires_count must be true or false")
    if kind == "missing_source_rows_known":
        patterns = params.get("patterns")
        if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p.strip() for p in patterns):
            errs.append("missing_source_rows_known needs params.patterns")
    return errs


def _sql_list(values) -> str:
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _issues_sql(output: Path, rule: str, ciks) -> str:
    return f"""SELECT DISTINCT lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') AS cik, report_date[:10] AS q, row_id,
               bdc_investment_identifier AS id
        FROM read_csv('{(output / 'row_validation_issues.csv').as_posix()}', header=true, all_varchar=true, sample_size=-1)
        WHERE rule_id = '{rule}' AND lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') IN ({_sql_list(ciks)})"""


def _holdings_sql(output: Path) -> str:
    return f"read_parquet('{(output / 'private_markets_holdings.parquet').as_posix()}')"


def _values_as_filed(con, output: Path, rule: str, ciks, params) -> list[tuple]:
    fields = list(params["fields"])
    return con.execute(f"""
        WITH i AS ({_issues_sql(output, rule, ciks)}),
        p AS (SELECT row_id, count(*) FILTER (WHERE reason_code = 'verified') AS ok
              FROM read_csv('{(output / 'provenance_ledger.csv').as_posix()}', header=true, all_varchar=true, sample_size=-1)
              WHERE field IN ({_sql_list(fields)}) GROUP BY 1),
        h AS (SELECT CAST(row_id AS VARCHAR) AS row_id, TRY_CAST(fair_value AS DOUBLE) AS fv FROM {_holdings_sql(output)}),
        t AS (SELECT i.cik, i.q, i.id, coalesce(p.ok, 0) = {len(fields)} AS good, coalesce(h.fv, 0) AS fv
              FROM i LEFT JOIN p USING (row_id) LEFT JOIN h USING (row_id))
        SELECT cik, q, count(*), count(*) FILTER (WHERE NOT good), coalesce(sum(abs(fv)) FILTER (WHERE NOT good), 0) / 1e6,
               list(id ORDER BY abs(fv) DESC) FILTER (WHERE NOT good)
        FROM t GROUP BY 1, 2""").fetchall()


def _no_rate_in_source(con, output: Path, rule: str, ciks, params) -> list[tuple]:
    return con.execute(f"""
        WITH i AS ({_issues_sql(output, rule, ciks)}),
        h AS (SELECT CAST(row_id AS VARCHAR) AS row_id, TRY_CAST(fair_value AS DOUBLE) AS fv,
                     -- an unfunded line carried net of fees: HPS prints par, a negative cost, a small
                     -- positive value and no rate ("7/22/2031 43,333 ( 202 ) 433")
                     coalesce(TRY_CAST(cost AS DOUBLE), 0) < 0 AS unfunded,
                     coalesce(TRY_CAST(pik_rate AS DOUBLE), 0) > 0 AS pik,
                     coalesce(CAST(nonaccrual_status AS VARCHAR), '') = 'nonaccrual' AS nonaccrual,
                     coalesce(CAST(src_facts AS VARCHAR), '') AS facts
              FROM {_holdings_sql(output)}),
        t AS (SELECT i.cik, i.q, i.id, coalesce(h.fv, 0) AS fv,
                     h.row_id IS NOT NULL AND NOT (h.facts LIKE '%"interest_rate"%' OR h.facts LIKE '%"basis_spread"%')
                     AND (coalesce(h.fv, 0) <= 0 OR h.unfunded OR h.nonaccrual OR h.pik) AS good
              FROM i LEFT JOIN h USING (row_id))
        SELECT cik, q, count(*), count(*) FILTER (WHERE NOT good), coalesce(sum(abs(fv)) FILTER (WHERE NOT good), 0) / 1e6,
               list(id ORDER BY abs(fv) DESC) FILTER (WHERE NOT good)
        FROM t GROUP BY 1, 2""").fetchall()


def _no_principal_in_source(con, output: Path, rule: str, ciks, params) -> list[tuple]:
    count_needed = "TRUE" if params.get("requires_count", True) else "FALSE"
    return con.execute(f"""
        WITH i AS ({_issues_sql(output, rule, ciks)}),
        h AS (SELECT CAST(row_id AS VARCHAR) AS row_id, TRY_CAST(fair_value AS DOUBLE) AS fv,
                     TRY_CAST(principal_amount AS DOUBLE) IS NOT NULL AS has_principal,
                     TRY_CAST(shares_held AS DOUBLE) IS NOT NULL AS has_count,
                     -- the extractor records a tagged principal's unit; an empty object means no such fact
                     coalesce(CAST(src_facts AS VARCHAR), '') LIKE '%"principal_amount":{{"unit_ref"%' AS principal_tagged
              FROM {_holdings_sql(output)}),
        t AS (SELECT i.cik, i.q, i.id, coalesce(h.fv, 0) AS fv,
                     h.row_id IS NOT NULL AND NOT h.has_principal AND NOT h.principal_tagged
                     AND (h.has_count OR NOT {count_needed}) AS good
              FROM i LEFT JOIN h USING (row_id))
        SELECT cik, q, count(*), count(*) FILTER (WHERE NOT good), coalesce(sum(abs(fv)) FILTER (WHERE NOT good), 0) / 1e6,
               list(id ORDER BY abs(fv) DESC) FILTER (WHERE NOT good)
        FROM t GROUP BY 1, 2""").fetchall()


def _missing_source_rows_known(con, output: Path, rule: str, ciks, params) -> list[tuple]:
    pattern = "|".join("(?:%s)" % p for p in params["patterns"]).replace("'", "''")
    tolerance = float(params.get("tolerance_m", 0.5))
    return con.execute(f"""
        WITH s AS (SELECT lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') AS cik, report_date[:10] AS q,
                          raw_investment_identifier AS id, coalesce(TRY_CAST(source_fair_value AS DOUBLE), 0) AS fv
                   FROM read_csv('{(output / 'source_reconciliation_source_only_detail.csv').as_posix()}', header=true, all_varchar=true, sample_size=-1)
                   WHERE lower(is_blocking) IN ('true', '1', 'yes')
                     AND lpad(regexp_replace(cik, '[^0-9]', '', 'g'), 10, '0') IN ({_sql_list(ciks)})),
        t AS (SELECT cik, q, id, fv, regexp_matches(id, '{pattern}') AS good FROM s),
        pub AS (SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik, CAST(report_date AS VARCHAR)[:10] AS q,
                       sum(TRY_CAST(fair_value AS DOUBLE)) / 1e6 AS fv
                FROM {_holdings_sql(output)}
                WHERE coalesce(index_classification, '') <> 'CASH' AND coalesce(accounting_record_class, '') <> 'underlying_schedule'
                GROUP BY 1, 2),
        filed AS (SELECT lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik, CAST(report_date AS VARCHAR)[:10] AS q,
                         max(TRY_CAST(investments_at_fair_value AS DOUBLE)) / 1e6 AS fv
                  FROM read_csv('{(output / 'fund_financials.csv').as_posix()}', header=true, all_varchar=true, sample_size=-1)
                  GROUP BY 1, 2),
        g AS (SELECT cik, q, count(*) AS n, count(*) FILTER (WHERE NOT good) AS bad,
                     coalesce(sum(abs(fv)) FILTER (WHERE NOT good), 0) / 1e6 AS bad_fv,
                     list(id ORDER BY abs(fv) DESC) FILTER (WHERE NOT good) AS names
              FROM t GROUP BY 1, 2)
        SELECT g.cik, g.q, g.n,
               g.bad + CASE WHEN pub.fv IS NULL OR filed.fv IS NULL OR abs(pub.fv - filed.fv) > {tolerance} THEN 1 ELSE 0 END,
               g.bad_fv,
               CASE WHEN pub.fv IS NULL OR filed.fv IS NULL THEN list_append(coalesce(g.names, []), 'no filed total to compare')
                    WHEN abs(pub.fv - filed.fv) > {tolerance}
                    THEN list_append(coalesce(g.names, []), 'published differs from filed by ' || CAST(round(pub.fv - filed.fv, 1) AS VARCHAR) || 'M')
                    ELSE g.names END
        FROM g LEFT JOIN pub USING (cik, q) LEFT JOIN filed USING (cik, q)""").fetchall()


_RUNNERS = {"values_as_filed": _values_as_filed, "no_rate_in_source": _no_rate_in_source,
            "missing_source_rows_known": _missing_source_rows_known,
            "no_principal_in_source": _no_principal_in_source}


def evaluate(entries: list[dict], output_dir: Path) -> list[dict]:
    """One result row per (entry with a carry_forward, fund, quarter in which its rule has rows).

    Every quarter is tested, including the ones the entry lists: the listed ones are not reopened by
    a failure, but the result shows how well the check describes what was accepted."""
    output = Path(output_dir)
    results = []
    con = duckdb.connect()
    con.execute("SET memory_limit='3GB'")
    try:
        for entry in entries:
            spec = entry.get("carry_forward")
            if not spec:
                continue
            ciks = [str(c).zfill(10) for c in entry["ciks"] if c != "*"]
            if not ciks:
                continue
            rows = _RUNNERS[spec["check"]](con, output, entry["rule_name"], ciks, spec.get("params", {}))
            for cik, quarter, tested, failing, failing_fv, names in sorted(rows):
                names = [str(n) for n in (names or []) if n]
                detail = "; ".join(names[:_MAX_NAMED]) + (" (+%d more)" % (len(names) - _MAX_NAMED) if len(names) > _MAX_NAMED else "")
                results.append({"disposition_id": entry["disposition_id"], "cik": cik, "report_date": quarter,
                                "check": spec["check"], "passed": bool(tested and not failing), "rows_tested": int(tested),
                                "rows_failing": int(failing), "failing_fair_value_m": round(float(failing_fv or 0), 2),
                                "detail": detail.encode("ascii", "replace").decode("ascii")})
    finally:
        con.close()
    return results


def write(results: list[dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(results)


def load_passes(path: Path | None) -> set[tuple[str, str, str]]:
    """(disposition_id, cik, quarter) that passed. A missing file gives an empty set."""
    if path is None or not Path(path).exists():
        return set()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return {(r["disposition_id"], str(r["cik"]).zfill(10), r["report_date"][:10])
                for r in csv.DictReader(handle) if str(r.get("passed")).lower() == "true"}


def main(argv=None) -> int:
    import argparse

    from pipeline import config, finding_dispositions
    parser = argparse.ArgumentParser(description="Evaluate carry-forward checks of the standing dispositions.")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dispositions-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    results = evaluate(finding_dispositions.load(args.dispositions_dir), args.output_dir)
    write(results, args.out)
    print(json.dumps({"results": len(results), "passed": sum(r["passed"] for r in results), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
