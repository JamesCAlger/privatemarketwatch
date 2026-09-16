"""Accounting scope expressions for observation deduplication and identity.

Reporting-entity axes distinguish parent and underlying portfolios. A bare
subsidiary flag does not identify a portfolio; unresolved scope stays isolated
by the source observation. No borrower aggregation or ownership inference.
"""

import duckdb
from pipeline.source_encodings import reporting_suffix_expression


OUTPUT_COLUMNS = ('accounting_scope_id', 'accounting_record_class')


def scope_expression(cik,dimensions,subsidiary,observation):
    """Return SQL using caller-supplied expressions from governed code.

    This preserves the existing continuity scope representation exactly. It
    can also be evaluated on raw staging columns before duplicate removal.
    """
    members=("array_to_string(list_sort(list_filter(string_split(lower(coalesce(CAST("+dimensions+
        " AS VARCHAR),'')),'|'),x -> regexp_matches(split_part(x,'=',1),"
        "'nonconsolidatedsubsidiar|equitymethodinvestmentequitymethodinvesteenameaxis') "
        "AND contains(x,'=') AND trim(split_part(x,'=',2))<>'')),'|')")
    suffix = reporting_suffix_expression(cik, dimensions)
    underlying = "(coalesce(TRY_CAST("+subsidiary+" AS BOOLEAN),false) OR "+suffix+"<>'')"
    return ("lpad(CAST("+cik+" AS VARCHAR),10,'0')||'|'||CASE WHEN "+underlying+
        " THEN coalesce(nullif("+members+",''),nullif("+suffix+",''),'unresolved:'||CAST("+observation+
        " AS VARCHAR)) ELSE 'parent' END")


def annotate(frame):
    """Expose governed scope after observation IDs exist; preserve row order.

    Recompute after corrections so stale derived labels cannot survive a
    source-dimension or subsidiary-flag change. Identity validates the same
    expression independently before assigning durable IDs.
    """
    if 'row_id' not in frame:
        raise ValueError('Accounting scope requires observation identities')
    base = frame.drop(columns=[c for c in OUTPUT_COLUMNS if c in frame])
    dimensions = 'bdc_dimensions_raw' if 'bdc_dimensions_raw' in base else "''"
    subsidiary = 'is_subsidiary' if 'is_subsidiary' in base else 'false'
    expression = scope_expression('cik', dimensions, subsidiary, 'row_id')
    with duckdb.connect(config={'threads': 2, 'memory_limit': '-1'}) as con:
        con.register('observations', base)
        return con.execute('''WITH scoped AS (
            SELECT *, ''' + expression + ''' AS accounting_scope_id
            FROM observations)
            SELECT * ''' + ("EXCLUDE (is_subsidiary), CASE WHEN ends_with(accounting_scope_id,'|parent') THEN 0 ELSE 1 END AS is_subsidiary" if 'is_subsidiary' in base else '') + ''',
                CASE WHEN ends_with(accounting_scope_id,'|parent')
                    THEN 'parent_schedule'
                WHEN contains(accounting_scope_id,'|unresolved:')
                    THEN 'unresolved_underlying_schedule'
                ELSE 'underlying_schedule' END AS accounting_record_class
            FROM scoped''').fetchdf()
