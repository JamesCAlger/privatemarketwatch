"""Candidate ledger rules (v0.5, owner 2026-10-17: build and measure, do NOT switch on).

Five checks that compare a published holdings row with what its filing prints. Nothing in the
build, the ledger, the shadow engines, the quarter pass or the fund gate calls this module; only
``tests/test_candidate_rules.py`` and ``scripts/v05_evidence/measure_candidate_rules.py`` do.

Every rule is DuckDB SQL over a table of published holdings rows that may carry ``printed_row``
(the page reader's cell-by-cell copy of the row, cells joined by `` | ``; see D-156). Build that
table with :func:`load_fund_rows`. A rule returns one pandas row per flagged holdings row, with the
same leading columns: rule, kind, basis, cik, report_date, accession_number, row_id, issuer_name,
instrument_description, fair_value, published, printed, printed_row, member.

``basis`` says what the flag rests on: ``page`` (the printed row), ``member`` (the filer's
identifier text), ``shape`` (a shape-only test on the published value, used where the row could not
be located on the page; weaker, labelled so), or ``coverage`` (rule 4).

Rules
-----
issuer_name_differs_from_page   published issuer is not the company name printed on the row.
unit_count_differs_from_row_text  equity unit count differs from the count printed on the row or in
                                the row's member text.
pik_printed_not_published       the row or member prints a PIK figure and pik_rate is empty (kind
                                ``pik_printed_not_published``) or differs (kind ``pik_value_mismatch``).
industry_not_published          per fund-quarter share of funded rows with no gics_sub_industry (the
                                column the public sector partition reads).
preferred_published_as_common   an equity row classed common whose text says preferred, or which
                                carries a PIK or dividend rate.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

PUBLISHED_WHERE = ("source = 'bdc' AND coalesce(CAST(accounting_record_class AS VARCHAR), '') <> 'underlying_schedule'")

OUTPUT_COLUMNS = ["rule", "kind", "basis", "cik", "report_date", "accession_number", "row_id", "issuer_name",
                  "instrument_description", "fair_value", "published", "printed", "printed_row", "member"]

# Columns a rule may read. A test frame may leave any of them out; they are added as NULL.
INPUT_COLUMNS = {
    "cik": "VARCHAR", "report_date": "VARCHAR", "accession_number": "VARCHAR", "row_id": "VARCHAR",
    "issuer_name": "VARCHAR", "instrument_description": "VARCHAR", "bdc_investment_identifier": "VARCHAR",
    "fair_value": "DOUBLE", "shares_held": "DOUBLE", "shares_held_source": "VARCHAR", "pik_rate": "DOUBLE",
    "interest_rate": "DOUBLE", "basis_spread": "DOUBLE", "asset_category": "VARCHAR",
    "index_classification": "VARCHAR", "extracted_industry": "VARCHAR", "gics_sub_industry": "VARCHAR",
    "gics_sector": "VARCHAR", "printed_row": "VARCHAR",
}

# Rule 4: a fund-quarter with fewer funded rows says nothing (same floor as field_coverage_drop).
INDUSTRY_MIN_ROWS = 20
# Proposed, not owner-set: see docs/investigations/v05_rule_candidates_2026-10-17.md. Measured on the
# accepted sandboxes, the structural gaps (industry column not read, a fund's first quarters) sit below
# 0.66 and funds whose industry comes from the name cache alone sit at 0.75-0.95.
INDUSTRY_COVERAGE_THRESHOLD = 0.80

# A cell that ends the name part of a printed row: an instrument, a rate, a date, a figure or a mark.
_STOP_CELL = (r"(?i)^\s*(first|second|third|1st|2nd|senior|junior|unitranche|term|delayed|ddtl|revolv\w*|"
              r"incremental|tranche|class|series|common|preferred|ordinary|warrants?|units?|lp units?|"
              r"llc units?|membership|partnership|subordinated|mezzanine|unsecured|secured|notes?|bonds?|"
              r"loan|debt|convertible|sofr|libor|euribor|sonia|sterling|prime|n/a|fixed|floating|pik|equity|"
              r"limited partner\w*|member units?|equipment financing|collater\w*)\b"
              # instrument phrases anywhere in the cell (Ares 'Z2 preferred shares', 'Limited partnership interests')
              r"|(?i)\b(term loan|revolving|delayed draw|first lien|second lien|senior secured|preferred (shares|stock|units|equity)|"
              r"common (shares|stock|units|equity)|partnership interests?|partner interests?|membership (units|interests?)|"
              r"lp interests?|llc interests?|units|shares|warrants?|loan obligation|subordinated (debt|notes?|certificates?)|"
              r"asset[- ]backed)\b")
_STOP_SYMBOLS = r"^[\s$()%0-9.,?*#~<>+/\-]*$"
_STOP_RATE = r"(?i)^\s*[SLEP]\s*\+"

# Shape-only fallback (rows not located on the page): section and axis words a company name does
# not begin with, and category-path words a company name does not contain.
_SECTION_START = (r"(?i)^(investments?\b|debt investments?|equity investments?|cash equivalents?|"
                  r"cash and cash equivalents|(senior secured )?(first|second|1st|2nd) lien\b|senior secured\b|"
                  r"unsecured debt|subordinated debt|non-controlled|controlled|affiliated|non-affiliated|"
                  r"portfolio (companies|investments))")
_CATEGORY_WORDS = (r"(?i)(\bfirst lien (debt|loans?|senior)|\bsecond lien (debt|loans?)|\bdebt investments\b|"
                   r"\bequity investments\b|\bnon-controlled\b|\bnon-affiliated\b|investments - )")


def _macros(con: duckdb.DuckDBPyConnection) -> None:
    # lower case, footnote marks out, punctuation to spaces, a leading 'the' dropped
    con.execute(r"""CREATE OR REPLACE MACRO cr_norm(x) AS
        regexp_replace(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(CAST(x AS VARCHAR), '')),
             '\(\s*[^()]{0,6}\s*\)', ' ', 'g'), '[^a-z0-9]+', ' ', 'g'), '\s+', ' ', 'g')), '^the ', '')""")
    # bracketed text is left out of the stop test: 'Talos Energy Inc. (12,138 shares of common stock)' is a name cell
    con.execute(f"""CREATE OR REPLACE MACRO cr_stop(c) AS
        regexp_matches(regexp_replace(c, '\\([^()]*\\)', ' ', 'g'), '{_STOP_CELL}')
        OR regexp_matches(c, '{_STOP_SYMBOLS}') OR regexp_matches(c, '{_STOP_RATE}')""")
    # 'name' starts 'cell' at a word boundary (a footnote digit right after the name is allowed)
    con.execute("""CREATE OR REPLACE MACRO cr_prefix(cell, name) AS
        length(name) > 0 AND starts_with(cell, name)
        AND (length(cell) = length(name) OR substr(cell, length(name) + 1, 1) IN (' ', '0', '1', '2', '3',
             '4', '5', '6', '7', '8', '9'))""")


def prepare(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame, table: str = "cand_rows") -> str:
    """Register a pandas frame as the rule input table, adding absent input columns as NULL."""
    con.register("_cand_frame", frame)
    have = set(frame.columns)
    cols = ", ".join(
        (f"CAST({c} AS {t}) AS {c}" if c in have else f"CAST(NULL AS {t}) AS {c}") for c, t in INPUT_COLUMNS.items())
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT {cols} FROM _cand_frame")
    con.unregister("_cand_frame")
    _macros(con)
    return table


def load_fund_rows(con: duckdb.DuckDBPyConnection, output_dir: Path, cik: str, table: str = "cand_rows") -> str:
    """Published BDC rows of one fund from a sandbox output directory, with the printed row joined.

    The printed row is taken from ``bdc_ixbrl_field_status`` (current period, member printed once),
    keyed by accession and member text: first the identifier, then the dimension path less its axis
    name (Fidelity-style members). Read-only.
    """
    cik = str(cik).zfill(10)
    out = Path(output_dir)
    holdings = (out / "private_markets_holdings.parquet").as_posix()
    status = out / "bdc_ixbrl_field_status.parquet"
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{holdings}')").fetchall()}
    sel = ", ".join(
        (f"CAST(h.{c} AS {t}) AS {c}" if c in have else f"CAST(NULL AS {t}) AS {c}")
        for c, t in INPUT_COLUMNS.items() if c not in ("printed_row", "cik", "report_date"))
    if status.exists():
        status_sql = f"""SELECT accession_number, raw_id_lower, any_value(printed_row) AS printed_row, count(*) AS n
                         FROM read_parquet('{status.as_posix()}')
                         WHERE period_role = 'current' AND lpad(CAST(cik AS VARCHAR), 10, '0') = '{cik}'
                         GROUP BY 1, 2"""
    else:
        status_sql = ("SELECT CAST(NULL AS VARCHAR) AS accession_number, CAST(NULL AS VARCHAR) AS raw_id_lower, "
                      "CAST(NULL AS VARCHAR) AS printed_row, 0 AS n WHERE false")
    con.execute(f"""CREATE OR REPLACE TABLE {table} AS
        WITH h AS (SELECT * FROM read_parquet('{holdings}')
                   WHERE lpad(CAST(cik AS VARCHAR), 10, '0') = '{cik}' AND {PUBLISHED_WHERE}),
        s AS ({status_sql})
        SELECT '{cik}' AS cik, CAST(h.report_date AS VARCHAR)[:10] AS report_date, {sel},
               CAST(CASE WHEN s1.n = 1 AND nullif(trim(s1.printed_row), '') IS NOT NULL THEN s1.printed_row
                         WHEN s2.n = 1 AND nullif(trim(s2.printed_row), '') IS NOT NULL THEN s2.printed_row END
                    AS VARCHAR) AS printed_row
        FROM h
        LEFT JOIN s s1 ON s1.accession_number = h.accession_number
             AND s1.raw_id_lower = lower(trim(CAST(h.bdc_investment_identifier AS VARCHAR)))
        LEFT JOIN s s2 ON s2.accession_number = h.accession_number
             AND s2.raw_id_lower = lower(trim(regexp_replace(regexp_replace(CAST(h.bdc_dimensions_raw AS VARCHAR),
                 '^[^=]*=', ''), '[ ]+', ' ', 'g')))""")
    _macros(con)
    return table


def _select(rule: str, kind_sql: str, basis_sql: str, published_sql: str, printed_sql: str) -> str:
    return f"""'{rule}' AS rule, {kind_sql} AS kind, {basis_sql} AS basis, cik, report_date, accession_number, row_id,
               issuer_name, instrument_description, fair_value, CAST({published_sql} AS VARCHAR) AS published,
               CAST({printed_sql} AS VARCHAR) AS printed, printed_row, bdc_investment_identifier AS member"""


def _fetch(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    df = con.execute(sql).fetchdf()
    return df[OUTPUT_COLUMNS] if not df.empty else pd.DataFrame(columns=OUTPUT_COLUMNS)


# ---------------------------------------------------------------------------------------------
# Rule 1
# ---------------------------------------------------------------------------------------------

def industry_labels(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> list[str]:
    """The fund's own industry labels (normalised, 4+ characters) plus the GICS sub-industry list."""
    from pipeline.oracle_checks import _GICS_SUBINDUSTRY_LABELS
    own = [r[0] for r in con.execute(
        f"SELECT DISTINCT cr_norm(extracted_industry) FROM {table} WHERE length(cr_norm(extracted_industry)) >= 4").fetchall()]
    gics = [r[0] for r in con.execute(
        "SELECT DISTINCT cr_norm(x) FROM (SELECT unnest(?::VARCHAR[]) AS x)", [sorted(_GICS_SUBINDUSTRY_LABELS)]).fetchall()]
    return sorted(set(own) | set(g for g in gics if g))


def issuer_name_differs_from_page(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> pd.DataFrame:
    """A published issuer name that is not the company printed on the row.

    Page test (basis ``page``), for rows whose printed row is known: the cells before the first
    instrument, rate, date or figure cell are the row's name cells. The row passes when one name
    cell, footnote marks and punctuation folded, begins with the published name, either directly or
    after one of the fund's industry labels. A row whose first cell is already an instrument (a later
    tranche printed without its company) is not comparable. Lead cells that are industry labels, or
    that the same filing prints in front of issuers with three or more different first words
    (a heading column), are not name cells.

    Shape test (basis ``shape``, fallback for rows not comparable): the name equals an industry
    label, begins with a section or axis word, begins with the row's own industry heading, or
    holds category-path words. Any row whose name equals an industry label is flagged on either
    basis (kind ``equals_industry_label``).
    """
    labels = industry_labels(con, table)
    own = [r[0] for r in con.execute(
        f"SELECT DISTINCT cr_norm(extracted_industry) FROM {table} WHERE length(cr_norm(extracted_industry)) >= 4").fetchall()]
    con.execute("CREATE OR REPLACE TEMP TABLE _cr_labels AS SELECT unnest(?::VARCHAR[]) AS label", [labels])
    con.execute("CREATE OR REPLACE TEMP TABLE _cr_own AS SELECT unnest(?::VARCHAR[]) AS label", [own or [""]])
    from pipeline.oracle_checks import _GICS_SUBINDUSTRY_LABELS
    con.execute("CREATE OR REPLACE TEMP TABLE _cr_gics AS SELECT DISTINCT cr_norm(x) AS label FROM (SELECT unnest(?::VARCHAR[]) AS x)",
                [sorted(_GICS_SUBINDUSTRY_LABELS)])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _cr_names AS
        WITH b AS (
            SELECT *, cr_norm(issuer_name) AS nname,
                   CASE WHEN printed_row IS NOT NULL THEN string_split(printed_row, ' | ') END AS cells
            FROM {table} WHERE nullif(trim(issuer_name), '') IS NOT NULL),
        labs AS (SELECT coalesce(list(label), []) AS L FROM _cr_labels),
        r0 AS (
            SELECT *, CASE WHEN cells IS NULL THEN NULL
                           ELSE cells[1:coalesce(nullif(list_position(list_transform(cells, c -> cr_stop(c)), true), 0),
                                                 len(cells) + 1) - 1] END AS lead_cells
            FROM b),
        -- an industry heading printed in the row's first cell is not a name (New Mountain prints
        -- 'Business Services | First Lien ...' with the company on a row above)
        r1 AS (SELECT r0.*, list_filter(lead_cells, c -> NOT list_contains(labs.L, cr_norm(c))) AS label_free
               FROM r0, labs),
        -- a lead cell shared, in one filing, by issuers with three or more different first words is a
        -- heading the page reader kept, not a company (New Mountain's industry column, which the
        -- build does not read into extracted_industry)
        cells_used AS (
            SELECT accession_number, cr_norm(c) AS cell, count(DISTINCT split_part(nname, ' ', 1)) AS n_first
            FROM (SELECT accession_number, nname, unnest(label_free) AS c FROM r1) GROUP BY 1, 2),
        heads AS (SELECT accession_number, list(cell) AS H FROM cells_used WHERE n_first >= 3 GROUP BY 1),
        r AS (SELECT r1.*, list_filter(label_free, c -> NOT list_contains(coalesce(heads.H, []), cr_norm(c))) AS name_cells
              FROM r1 LEFT JOIN heads USING (accession_number))
        SELECT *, len(coalesce(name_cells, [])) > 0 AS comparable,
               list_bool_or(list_transform(coalesce(name_cells, []), c -> cr_prefix(cr_norm(c), nname))) AS direct_ok,
               -- the same letters with spaces ignored ('Circus Trix' / 'CircusTrix', 'CLO4' / 'CLO 4')
               list_bool_or(list_transform(coalesce(name_cells, []),
                   c -> starts_with(replace(cr_norm(c), ' ', ''), replace(nname, ' ', '')))) AS spacing_ok,
               -- printed in the lead cells at all, before label and heading cells are set aside
               coalesce(list_bool_or(list_transform(coalesce(lead_cells, []), c -> cr_prefix(cr_norm(c), nname))), false) AS lead_ok
        FROM r""")
    # second chance for a name cell that starts with an industry label ('Healthcare ... Cyan Investors LP')
    con.execute("""CREATE OR REPLACE TEMP TABLE _cr_after_label AS
        SELECT DISTINCT n.row_id, n.accession_number FROM
            (SELECT row_id, accession_number, nname, unnest(name_cells) AS cell FROM _cr_names
             WHERE comparable AND NOT coalesce(direct_ok, false)) n
        JOIN _cr_own l ON length(l.label) > 0 AND starts_with(cr_norm(n.cell), l.label || ' ')
        WHERE cr_prefix(substr(cr_norm(n.cell), length(l.label) + 2), n.nname)""")
    sql = f"""
        WITH x AS (
            -- a GICS label as the name is flagged even when the page prints it (New Mountain 'Software'); a
            -- fund's own label only when the page does not print it as the name (Overland 'U.S. Treasury Bill')
            SELECT n.*, (nname IN (SELECT label FROM _cr_gics)
                         OR (nname IN (SELECT label FROM _cr_labels) AND NOT lead_ok)) AS is_label,
                   (a.row_id IS NOT NULL) AS after_label_ok,
                   regexp_matches(issuer_name, '{_SECTION_START}') AS section_start,
                   -- the row's own industry heading at the front of its name ('Software Zendesk ...');
                   -- a company merely named after another industry word is not caught
                   (length(cr_norm(extracted_industry)) >= 4
                    AND starts_with(nname, cr_norm(extracted_industry) || ' ')) AS own_label_start,
                   regexp_matches(issuer_name, '{_CATEGORY_WORDS}') AS category_words
            FROM _cr_names n LEFT JOIN _cr_after_label a ON a.row_id = n.row_id AND a.accession_number = n.accession_number),
        k AS (
            SELECT *, CASE
                WHEN is_label THEN 'equals_industry_label'
                WHEN comparable AND NOT coalesce(direct_ok, false) AND NOT after_label_ok AND coalesce(spacing_ok, false)
                     THEN 'spacing_only'
                WHEN comparable AND NOT coalesce(direct_ok, false) AND NOT after_label_ok THEN 'not_the_printed_name'
                WHEN NOT comparable AND section_start THEN 'begins_with_section_word'
                WHEN NOT comparable AND own_label_start THEN 'begins_with_industry_label'
                WHEN NOT comparable AND category_words THEN 'holds_category_path'
              END AS kind_
            FROM x)
        SELECT {_select('issuer_name_differs_from_page', 'kind_',
                        "CASE WHEN comparable AND kind_ <> 'equals_industry_label' THEN 'page' ELSE 'shape' END",
                        'issuer_name', "array_to_string(name_cells, ' | ')")}
        FROM k WHERE kind_ IS NOT NULL ORDER BY report_date, issuer_name"""
    return _fetch(con, sql)


# ---------------------------------------------------------------------------------------------
# Rule 2
# ---------------------------------------------------------------------------------------------

# A count with its unit word: '( 1,824 units)', '878 shares of common stock', '8,642,579 preferred interests'.
_LABELLED_COUNT = (r"(?i)(?:^|[\s(])([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s+"
                   r"(?:(?:preferred|common|ordinary|voting|non-voting|restricted|lp|llc|partnership|membership|"
                   r"class [a-z0-9-]+|series [a-z0-9-]+)\s+){0,3}(?:units?|shares?|interests?)\b")
_ANY_NUMBER = r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?"
_DATE_WORDS = (r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|"
               r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+[0-9]{1,2},?\s+[0-9]{4}")


def unit_count_differs_from_row_text(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> pd.DataFrame:
    """An equity row whose published unit count is not the count printed on its own row or member.

    kind ``labelled_count_differs``: the row or member prints a count with its unit word ('( 1,824
    units)') and the published count equals none of them. kind ``labelled_count_not_published``: same,
    with no count published. kind ``proxy_count_not_on_row``: the count came from the shared
    normaliser (shares_held_source 'derived_proxy'), the printed row is known, and the count is not
    among the figures printed on it or in the member. Rounding: within 0.01 pct, or half a unit for
    counts of 100 or more (0.006 below).
    """
    tol = "greatest(1e-4 * abs(c), CASE WHEN abs(c) >= 100 THEN 0.51 ELSE 0.006 END)"
    sql = f"""
        WITH b AS (
            -- dates out first: Trinity's member reads '... June 30, 2022 Shares ...'
            SELECT *, regexp_replace(regexp_replace(
                       coalesce(printed_row, '') || ' || ' || coalesce(bdc_investment_identifier, ''),
                       '{_DATE_WORDS}', ' DATE ', 'g'), '[0-9]{{1,2}}/[0-9]{{1,2}}/[0-9]{{2,4}}', ' DATE ', 'g') AS txt
            FROM {table} WHERE asset_category LIKE 'EQUITY%'),
        c AS (
            SELECT *, list_filter(list_transform(regexp_extract_all(txt, '{_LABELLED_COUNT}', 1),
                                                 x -> TRY_CAST(replace(x, ',', '') AS DOUBLE)), x -> x IS NOT NULL AND x > 0) AS labelled,
                      list_filter(list_transform(regexp_extract_all(txt, '{_ANY_NUMBER}'),
                                                 x -> TRY_CAST(replace(x, ',', '') AS DOUBLE)), x -> x IS NOT NULL) AS figures
            FROM b),
        k AS (
            SELECT *, CASE
                WHEN len(labelled) > 0 AND shares_held IS NULL THEN 'labelled_count_not_published'
                WHEN len(labelled) > 0 AND NOT list_bool_or(list_transform(labelled, c -> abs(shares_held - c) <= {tol}))
                     THEN 'labelled_count_differs'
                WHEN len(labelled) = 0 AND shares_held_source = 'derived_proxy' AND printed_row IS NOT NULL
                     AND shares_held IS NOT NULL
                     AND NOT coalesce(list_bool_or(list_transform(figures, c -> abs(shares_held - c) <= {tol})), false)
                     THEN 'proxy_count_not_on_row'
              END AS kind_
            FROM c)
        SELECT {_select('unit_count_differs_from_row_text', 'kind_',
                        "CASE WHEN kind_ = 'proxy_count_not_on_row' THEN 'page' "
                        "WHEN printed_row IS NOT NULL AND regexp_matches(printed_row, '" + _LABELLED_COUNT + "') THEN 'page' "
                        "ELSE 'member' END",
                        "coalesce(CAST(shares_held AS VARCHAR), '') || ' (' || coalesce(shares_held_source, 'tagged') || ')'",
                        "CASE WHEN len(labelled) > 0 THEN array_to_string(labelled, '; ') ELSE 'figures: ' || array_to_string(figures, '; ') END")}
        FROM k WHERE kind_ IS NOT NULL ORDER BY report_date, issuer_name"""
    return _fetch(con, sql)


# ---------------------------------------------------------------------------------------------
# Rule 3
# ---------------------------------------------------------------------------------------------

_PIK_PERCENT = r"(?i)([0-9]+(?:\.[0-9]+)?)\s*%\s*\)?\s*PIK\b"
# a figure without a percent sign: basis points from 25 up ('including 75 PIK', '1350 PIK', 'S+450 PIK')
_PIK_BARE = r"(?i)(?:^|[^a-z0-9.%,])([0-9]+(?:\.[0-9]+)?)\s*\)?\s*PIK\b"
_PIK_NOT_A_FIGURE = r"(?i)\b(class|series|tranche|notes?)\s+[0-9]+"


def pik_printed_not_published(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> pd.DataFrame:
    """The row or its member text prints a PIK figure and the published pik_rate is empty or differs.

    Figures: 'N % PIK' (percent), and a bare 'N PIK' / '(including N PIK)' / 'plus N PIK' read as basis
    points from 25 up and as percent below. 'Class 2 PIK', '0.00 % PIK' and a PIK word without a
    figure ('PIK toggle, not elected') are not figures. '100 % PIK' means the whole coupon is PIK: it
    counts as printed but is not compared. kind ``pik_value_mismatch``: a pik_rate is published and
    matches no figure (nor their sum) to 0.011; often the page prints the PIK margin and pik_rate holds
    the all-in PIK coupon, so read these before treating them as errors. kind ``pik_value_rounding``: off
    by more than 0.011 but within 0.06 (a tag rounded to one decimal). basis ``member_page_silent``:
    only the member prints the figure while the joined printed row prints none (weaker).
    """
    sql = f"""
        WITH b AS (
            SELECT *, regexp_replace(regexp_replace(
                       coalesce(printed_row, '') || ' || ' || coalesce(bdc_investment_identifier, ''),
                       '([0-9]) \\| %', '\\1 %', 'g'), '{_PIK_NOT_A_FIGURE}', '\\1 X', 'g') AS txt
            FROM {table}),
        f AS (
            SELECT *, list_concat(
                       list_transform(regexp_extract_all(txt, '{_PIK_PERCENT}', 1), x -> TRY_CAST(x AS DOUBLE)),
                       list_transform(regexp_extract_all(txt, '{_PIK_BARE}', 1),
                                      x -> CASE WHEN TRY_CAST(x AS DOUBLE) >= 25 THEN TRY_CAST(x AS DOUBLE) / 100.0
                                                ELSE TRY_CAST(x AS DOUBLE) END)) AS raw_figs
            FROM b WHERE regexp_matches(txt, '(?i)[0-9]\\s*%?\\s*\\)?\\s*PIK\\b')),
        g AS (SELECT *, list_sort(list_distinct(list_filter(raw_figs, x -> x IS NOT NULL AND x > 0))) AS figs FROM f),
        k AS (
            SELECT *, CASE
                WHEN len(figs) = 0 THEN NULL
                WHEN coalesce(pik_rate, 0) = 0 THEN 'pik_printed_not_published'
                WHEN list_contains(figs, 100.0) THEN NULL
                WHEN list_bool_or(list_transform(figs, x -> abs(pik_rate - x) <= 0.011))
                     OR abs(pik_rate - list_sum(figs)) <= 0.011 THEN NULL
                -- a tag rounded to one decimal ('2.2' for the printed '2.25')
                WHEN list_bool_or(list_transform(figs, x -> abs(pik_rate - x) <= 0.06)) THEN 'pik_value_rounding'
                ELSE 'pik_value_mismatch'
              END AS kind_
            FROM g)
        SELECT {_select('pik_printed_not_published', 'kind_',
                        "CASE WHEN printed_row IS NOT NULL AND regexp_matches(printed_row, '(?i)[0-9]\\s*%?\\s*\\)?\\s*PIK\\b') THEN 'page' "
                        "WHEN printed_row IS NOT NULL THEN 'member_page_silent' ELSE 'member' END",
                        "coalesce(CAST(pik_rate AS VARCHAR), '')",
                        "array_to_string(figs, '; ')")}
        FROM k WHERE kind_ IS NOT NULL ORDER BY report_date, issuer_name"""
    return _fetch(con, sql)


# ---------------------------------------------------------------------------------------------
# Rule 4
# ---------------------------------------------------------------------------------------------

_FUNDED = ("fair_value > 0 AND coalesce(asset_category, '') <> 'CASH' AND coalesce(index_classification, '') <> 'CASH'")


def industry_coverage(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> pd.DataFrame:
    """Per fund and quarter: funded rows, and the share carrying gics_sub_industry (published) and
    extracted_industry (filer's printed heading)."""
    return con.execute(f"""
        SELECT cik, report_date, count(*) AS n_funded,
               count(*) FILTER (WHERE nullif(trim(gics_sub_industry), '') IS NULL) AS n_no_gics,
               sum(fair_value) FILTER (WHERE nullif(trim(gics_sub_industry), '') IS NULL) AS fv_no_gics,
               1.0 - count(*) FILTER (WHERE nullif(trim(gics_sub_industry), '') IS NULL) / count(*) AS gics_coverage,
               1.0 - count(*) FILTER (WHERE nullif(trim(extracted_industry), '') IS NULL) / count(*) AS extracted_coverage,
               sum(fair_value) AS fv_funded
        FROM {table} WHERE {_FUNDED} GROUP BY 1, 2 ORDER BY 1, 2""").fetchdf()


def industry_not_published(con: duckdb.DuckDBPyConnection, table: str = "cand_rows",
                           threshold: float = INDUSTRY_COVERAGE_THRESHOLD,
                           min_rows: int = INDUSTRY_MIN_ROWS) -> pd.DataFrame:
    """Funded rows with no published industry (gics_sub_industry), in fund-quarters whose coverage is
    below ``threshold`` and that have at least ``min_rows`` funded rows. kind says whether the
    filer's own industry (extracted_industry) is also missing."""
    sql = f"""
        WITH q AS (
            SELECT cik, report_date FROM {table} WHERE {_FUNDED} GROUP BY 1, 2
            HAVING count(*) >= {int(min_rows)}
               AND 1.0 - count(*) FILTER (WHERE nullif(trim(gics_sub_industry), '') IS NULL) / count(*) < {float(threshold)})
        SELECT {_select('industry_not_published',
                        "CASE WHEN nullif(trim(extracted_industry), '') IS NULL THEN 'no_industry_at_all' "
                        "ELSE 'filer_industry_not_mapped' END",
                        "'coverage'", "coalesce(gics_sub_industry, '')", "coalesce(extracted_industry, '')")}
        FROM {table} t JOIN q USING (cik, report_date)
        WHERE {_FUNDED} AND nullif(trim(gics_sub_industry), '') IS NULL
        ORDER BY report_date, issuer_name"""
    return _fetch(con, sql)


# ---------------------------------------------------------------------------------------------
# Rule 5
# ---------------------------------------------------------------------------------------------

_PREFERRED_WORD = r"(?i)\b(pref|pref\.|preferred|prefered|preffered|preference)\b"


def preferred_published_as_common(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> pd.DataFrame:
    """An equity row classed common (asset_category EQUITY_COMMON or index_classification
    COMMON_EQUITY) whose instrument, member or printed row says preferred, or that carries a PIK or
    dividend rate.

    The issuer's own name is removed from the text first ('Preferred Freezer Services'). Warrants
    are left out (a warrant to buy preferred is not preferred), and so is text that also says common.
    """
    sql = f"""
        WITH b AS (
            SELECT *, replace(lower(coalesce(instrument_description, '') || ' || ' || coalesce(bdc_investment_identifier, '')
                                    || ' || ' || coalesce(printed_row, '')),
                              lower(coalesce(nullif(trim(issuer_name), ''), '\x01')), ' ') AS txt
            FROM {table}
            WHERE (asset_category = 'EQUITY_COMMON' OR index_classification = 'COMMON_EQUITY')),
        k AS (
            SELECT *, regexp_matches(txt, '{_PREFERRED_WORD}') AND NOT regexp_matches(txt, '(?i)\\bcommon\\b') AS says_pref,
                   coalesce(pik_rate, 0) > 0 OR coalesce(interest_rate, 0) > 0 AS has_rate,
                   regexp_matches(txt, '(?i)\\bwarrants?\\b') AS warrant
            FROM b),
        z AS (
            SELECT *, CASE WHEN warrant THEN NULL
                           WHEN says_pref AND has_rate THEN 'text_and_rate'
                           WHEN says_pref THEN 'text_says_preferred'
                           WHEN has_rate THEN 'rate_on_common' END AS kind_
            FROM k)
        SELECT {_select('preferred_published_as_common', 'kind_',
                        "CASE WHEN says_pref AND printed_row IS NOT NULL AND regexp_matches(printed_row, '" + _PREFERRED_WORD + "') THEN 'page' "
                        "WHEN says_pref THEN 'member' ELSE 'shape' END",
                        "coalesce(asset_category, '') || '/' || coalesce(index_classification, '') "
                        "|| ' pik=' || coalesce(CAST(pik_rate AS VARCHAR), '') || ' rate=' || coalesce(CAST(interest_rate AS VARCHAR), '')",
                        "coalesce(instrument_description, '')")}
        FROM z WHERE kind_ IS NOT NULL ORDER BY report_date, issuer_name"""
    return _fetch(con, sql)


RULES = {
    "issuer_name_differs_from_page": issuer_name_differs_from_page,
    "unit_count_differs_from_row_text": unit_count_differs_from_row_text,
    "pik_printed_not_published": pik_printed_not_published,
    "industry_not_published": industry_not_published,
    "preferred_published_as_common": preferred_published_as_common,
}
