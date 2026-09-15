"""Reported-cost, date-precision and accounting-scope inputs to continuity."""
from __future__ import annotations

from pipeline.financial_conventions import maturity_interval_sql
from pipeline.accounting_scope import scope_expression


def scope_sql(columns, *, alias='', row_id='row_id'):
    """Scope comes from the reporting entity axis, never a borrower/JV flag.

    An unresolved subsidiary scope is isolated by observation. A bare Y flag
    cannot establish which joint venture reported a look-through position.
    """
    prefix=alias+'.' if alias else ''
    subsidiary=prefix+'is_subsidiary' if 'is_subsidiary' in columns else "'0'"
    dimensions=prefix+'bdc_dimensions_raw' if 'bdc_dimensions_raw' in columns else "''"
    return scope_expression(prefix+'cik', dimensions, subsidiary, prefix+row_id)


def interval_rank_sql(low_b,high_b,low_e,high_e):
    return (f'CASE WHEN {low_b} IS NULL OR {low_e} IS NULL THEN 1 '
        f'WHEN {low_b}<={high_e} AND {low_e}<={high_b} THEN 0 ELSE 2 END')


def interval_gap_sql(low_b,high_b,low_e,high_e):
    return (f'CASE WHEN {low_b} IS NULL OR {low_e} IS NULL THEN NULL '
        f"ELSE greatest(0,date_diff('day',{high_b},{low_e}),date_diff('day',{high_e},{low_b})) END")


def bounds_sql(columns,date='maturity_date',precision='maturity_precision'):
    # Legacy fixtures and historical replay have exact dates but no precision
    # column. Migrated production rows always carry explicit precision.
    return maturity_interval_sql(date,precision if precision in columns else "'day'")
