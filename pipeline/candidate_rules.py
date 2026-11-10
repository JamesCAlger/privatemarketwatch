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
pik_printed_not_published       the printed row prints a PIK figure and pik_rate is empty (kind
                                ``pik_printed_not_published``) or differs (kind ``pik_value_mismatch``);
                                member-text-only evidence is the weaker kind ``pik_member_text_only``.
industry_not_published          per fund-quarter share of funded rows with no gics_sub_industry (the
                                column the public sector partition reads); finding below 0.80, warning
                                below 0.90, exempt funds listed with evidence.

Revised 2026-10-18 after the independent false-alarm review (D-207).
preferred_published_as_common   an equity row classed common whose text says preferred (text only,
                                D-207).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.bdc_xbrl_html_bridge import _BENCHMARK_CODE

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
    "gics_sector": "VARCHAR", "printed_row": "VARCHAR", "src_transforms": "VARCHAR", "src_context_id": "VARCHAR",
}

# Rule 4: a fund-quarter with fewer funded rows says nothing (same floor as field_coverage_drop).
INDUSTRY_MIN_ROWS = 20
# Owner ruling 2026-10-18 (D-207): finding below 0.80, warning below 0.90.
INDUSTRY_COVERAGE_THRESHOLD = 0.80
INDUSTRY_COVERAGE_WARNING = 0.90
# Funds whose filings print no industry at all: no coverage finding, each with its evidence.
INDUSTRY_EXEMPTIONS = {
    "0002049733": {
        "fund": "Blackstone Private Real Estate Credit and Income Fund",
        "evidence": ("Schedule headings are asset types (CMBS, RMBS, mezzanine loans) and loans are named by "
                     "property ('1100 Peachtree', '18200-18250 Flower Hill Way'); the printed rows carry no "
                     "industry cell and extracted_industry is empty on every row of 2025-06-30 to 2026-06-30 "
                     "(sandbox brxb). Read in the cached filings by the 2026-10-18 false-alarm review "
                     "(docs/investigations/v05_rule_candidates_falsealarm_2026-10-18.md, rule 4: 5 of 5 sampled "
                     "fund-quarters print none)."),
        "checked_on": "2026-10-18",
    },
}

# A cell that ends the name part of a printed row: an instrument, a rate, a date, a figure or a mark.
_STOP_CELL = (r"(?i)^\s*(first|second|third|1st|2nd|senior|junior|unitranche|term|delayed|ddtl|revolv\w*|"
              # a class or series designation ('Class E', 'Series C-3'), not a name that starts with the
              # word ('Class Valuation', Kayne Anderson)
              r"incremental|tranche|(class|series) [a-z0-9][a-z0-9-]{0,3}|common|preferred|ordinary|warrants?|units?|lp units?|"
              r"llc units?|membership|partnership|subordinated|mezzanine|unsecured|secured|notes?|bonds?|"
              r"loan|debt|convertible|sofr|libor|euribor|sonia|sterling|prime|n/a|fixed|floating|pik|equity|"
              r"limited partner\w*|member units?|member interests?|equipment financing|collater\w*)\b"
              # a count before a class or series word (Sixth Street Raptor '12,832 Class C'); a name that
              # starts with a number ('1375 Owner LLC', '1988 CLO 2 Ltd.') is not stopped
              r"|(?i)^\s*[0-9][0-9,.]*\s+(class|series)\b"
              # instrument phrases anywhere in the cell (Ares 'Z2 preferred shares', 'Limited partnership interests',
              # Barings 'Structured Secured Note - Class B', Ares 'Member interest (100.00% interest)')
              r"|(?i)\b(term loan|revolving|delayed draw|first lien|second lien|senior secured|preferred (shares|stock|units|equity)|"
              r"common (shares|stock|units|equity)|partnership interests?|partner interests?|member(ship)? (units|interests?)|"
              r"lp interests?|llc interests?|units|shares|warrants?|loan obligation|subordinated (debt|notes?|certificates?)|"
              r"structured( (secured|senior|subordinated|mezzanine))? notes?|notes? - class|"
              r"asset[- ]backed)\b")
# a dash cell of any kind ('-', en dash, em dash, minus) is not a name (owner 2026-11-10: Overland's
# 'U.S. Treasury Bill | &#8212; | 4.27%' read the em dash as the name)
_STOP_SYMBOLS = r"^[\s$()%0-9.,?*#~<>+/\-\x{2013}\x{2014}\x{2212}]*$"
_STOP_RATE = r"(?i)^\s*[SLEP]\s*\+"

# Shape-only fallback (rows not located on the page): section and axis words a company name does
# not begin with, and category-path words a company name does not contain.
_SECTION_START = (r"(?i)^(investments?\b|debt investments?|equity investments?|cash equivalents?|"
                  r"cash and cash equivalents|(senior secured )?(first|second|1st|2nd) lien\b|senior secured\b|"
                  r"unsecured debt|subordinated debt|non-controlled|controlled|affiliated|non-affiliated|"
                  r"portfolio (companies|investments))")
_CATEGORY_WORDS = (r"(?i)(\bfirst lien (debt|loans?|senior)|\bsecond lien (debt|loans?)|\bdebt investments\b|"
                   r"\bequity investments\b|\bnon-controlled\b|\bnon-affiliated\b|investments - )")


_LEGAL_TAIL = (r"(( (llc|l l c|inc|incorporated|ltd|limited|corp|corporation|co|company|lp|l p|llp|lllp|plc|sa|s a|"
               r"sarl|s a r l|s r l|srl|sas|gmbh|bv|b v|nv|ag|ab|pty|ulc|dac))+)$")
# Rule 1: a fund-quarter where this share of rows has no comparable printed name is not tested on
# the page; its page-basis flags are not raised (reviewer 2026-10-18, D-207).
NAME_BLIND_LIMIT = 0.90


def _macros(con: duckdb.DuckDBPyConnection) -> None:
    # lower case, footnote marks out, punctuation to spaces, a leading 'the' dropped
    con.execute(r"""CREATE OR REPLACE MACRO cr_norm(x) AS
        regexp_replace(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(CAST(x AS VARCHAR), '')),
             '\(\s*[^()]{0,6}\s*\)', ' ', 'g'), '[^a-z0-9]+', ' ', 'g'), '\s+', ' ', 'g')), '^the ', '')""")
    # bracketed text is left out of the stop test: 'Talos Energy Inc. (12,138 shares of common stock)' is a name cell
    con.execute(f"""CREATE OR REPLACE MACRO cr_stop(c) AS
        regexp_matches(regexp_replace(c, '\\([^()]*\\)', ' ', 'g'), '{_STOP_CELL}')
        OR regexp_matches(c, '{_STOP_SYMBOLS}') OR regexp_matches(c, '{_STOP_RATE}')""")
    # the normalised name less trailing legal forms ('IMA Financial Group LLC' ~ 'IMA Financial Group')
    con.execute(f"""CREATE OR REPLACE MACRO cr_key(x) AS
        trim(regexp_replace(cr_norm(x), '{_LEGAL_TAIL}', ''))""")
    # two keys are near spellings: spaces ignored, at most 2 edits or 10 pct of the longer
    con.execute("""CREATE OR REPLACE MACRO cr_near(a, b) AS
        length(a) > 0 AND length(b) > 0
        AND levenshtein(replace(a, ' ', ''), replace(b, ' ', ''))
            <= greatest(2, floor(0.1 * greatest(length(replace(a, ' ', '')), length(replace(b, ' ', '')))))""")
    # 'cell' is 'name' with some of its spaces dropped (owner 2026-11-10: the page reader joins the lines
    # of a cell, 'Penn TRGRP HoldingsLLC (2)' for 'Penn TRGRP Holdings LLC'): every other character as
    # published, case included, and nothing after it but footnote marks ('(2)', '(~~)'). The reader can drop
    # a space but not add one, so a page that prints a space the published name lacks ('Garda World' for
    # 'GardaWorld') is not covered. Not covered either: "O'Brien" for 'OBrien', 'WH Borrower, LLC (WHP)' for
    # the cut 'WH Borrower, LLC (WHP', and a published name that spells letters apart ('L V F Holdings',
    # '..., L L C' for the printed 'LVF', 'LLC': a build defect, not a reader join).
    con.execute(r"""CREATE OR REPLACE MACRO cr_ws_join(cell, name) AS
        length(trim(coalesce(name, ''))) > 0
        AND NOT regexp_matches(name, '(^|[^A-Za-z0-9])[A-Za-z][\s\x{00a0}]+[A-Za-z]([^A-Za-z0-9]|$)')
        AND regexp_full_match(trim(coalesce(cell, '')),
              array_to_string(list_transform(string_split_regex(trim(name), '[\s\x{00a0}]+'),
                                             t -> regexp_replace(t, '([.^$*+?()\[\]{}|\\-])', '\\\1', 'g')),
                              '[\s\x{00a0}]?')
              || '[\s\x{00a0}]*(\([^()]{1,4}\)[\s\x{00a0}]*)*')""")
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
    out = Path(output_dir)
    status = out / "bdc_ixbrl_field_status.parquet"
    return _load(con, f"read_parquet('{(out / 'private_markets_holdings.parquet').as_posix()}')",
                 f"read_parquet('{status.as_posix()}')" if status.exists() else None, cik, table)


def _load(con: duckdb.DuckDBPyConnection, holdings_sql: str, status_src: str | None, cik: str, table: str) -> str:
    cik = str(cik).zfill(10)
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {holdings_sql}").fetchall()}
    sel = ", ".join(
        (f"CAST(h.{c} AS {t}) AS {c}" if c in have else f"CAST(NULL AS {t}) AS {c}")
        for c, t in INPUT_COLUMNS.items() if c not in ("printed_row", "cik", "report_date"))
    dims = "h.bdc_dimensions_raw" if "bdc_dimensions_raw" in have else "CAST(NULL AS VARCHAR)"
    if status_src:
        status_sql = f"""SELECT CAST(accession_number AS VARCHAR) AS accession_number, CAST(raw_id_lower AS VARCHAR) AS raw_id_lower,
                                any_value(CAST(printed_row AS VARCHAR)) AS printed_row, count(*) AS n
                         FROM {status_src}
                         WHERE period_role = 'current' AND lpad(CAST(cik AS VARCHAR), 10, '0') = '{cik}'
                         GROUP BY 1, 2"""
    else:
        status_sql = ("SELECT CAST(NULL AS VARCHAR) AS accession_number, CAST(NULL AS VARCHAR) AS raw_id_lower, "
                      "CAST(NULL AS VARCHAR) AS printed_row, 0 AS n WHERE false")
    con.execute(f"""CREATE OR REPLACE TABLE {table} AS
        WITH h AS (SELECT * FROM {holdings_sql}
                   WHERE lpad(CAST(cik AS VARCHAR), 10, '0') = '{cik}' AND {PUBLISHED_WHERE}),
        s AS ({status_sql})
        SELECT '{cik}' AS cik, CAST(h.report_date AS VARCHAR)[:10] AS report_date, {sel},
               CAST(CASE WHEN s1.n = 1 AND nullif(trim(s1.printed_row), '') IS NOT NULL THEN s1.printed_row
                         WHEN s2.n = 1 AND nullif(trim(s2.printed_row), '') IS NOT NULL THEN s2.printed_row END
                    AS VARCHAR) AS printed_row
        FROM h
        LEFT JOIN s s1 ON s1.accession_number = CAST(h.accession_number AS VARCHAR)
             AND s1.raw_id_lower = lower(trim(CAST(h.bdc_investment_identifier AS VARCHAR)))
        LEFT JOIN s s2 ON s2.accession_number = CAST(h.accession_number AS VARCHAR)
             AND s2.raw_id_lower = lower(trim(regexp_replace(regexp_replace(CAST({dims} AS VARCHAR),
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
    (a heading column), are not name cells. Names are also compared less trailing legal forms
    (LLC, Inc., Ltd. ...). A published name the fund prints as a name somewhere in its filings passes
    when this row prints a near spelling of it (same issuer spelt two ways); a different group entity
    printed on the row still flags (MidCap Wildcat, 2026-10-19 re-sample). In a fund-quarter where NAME_BLIND_LIMIT or more of the rows have no comparable
    printed name, page-basis flags are not raised; ``result.attrs['blind_spots']`` lists every
    fund-quarter's untested share (D-207).

    Shape test (basis ``shape``, fallback for rows not comparable): the name equals an industry
    label, begins with a section or axis word, begins with the row's own industry heading, or
    holds category-path words. Any row whose name equals an industry label is flagged on either
    basis (kind ``equals_industry_label``).

    Owner ruling 2026-11-10 (check repair): a printed name that is the published one with spaces dropped
    (the page reader joined the lines of a cell at a <br/> or block element: 'Penn TRGRP HoldingsLLC') is kind
    ``whitespace_only``, informational, not a finding (macro cr_ws_join). Any other difference still flags:
    a character, a space the page prints and the name lacks, a cut name, letters spelt apart ('L V F');
    ``spacing_only`` keeps those the folded comparison cannot see (a lost apostrophe). A dash cell is not a
    name cell. A cash row whose name is the heading the fund prints over its cash rows ('U.S. Treasury
    Bill') is not flagged as equal to an industry label.
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
               list_bool_or(list_transform(coalesce(name_cells, []),
                   c -> cr_prefix(cr_norm(c), nname) OR cr_prefix(cr_key(c), cr_key(issuer_name)))) AS direct_ok,
               -- the same letters with spaces ignored ('Circus Trix' / 'CircusTrix', 'CLO4' / 'CLO 4')
               list_bool_or(list_transform(coalesce(name_cells, []),
                   c -> starts_with(replace(cr_norm(c), ' ', ''), replace(nname, ' ', '')))) AS spacing_ok,
               -- the printed name is the published one with spaces dropped (reader join; owner 2026-11-10)
               list_bool_or(list_transform(coalesce(name_cells, []), c -> cr_ws_join(c, issuer_name))) AS whitespace_ok,
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
    # every name cell the fund's filings print, by key. A published name passes when the fund prints
    # it as a name somewhere (any quarter) AND this row's printed name is a near spelling of it: the
    # same issuer spelt two ways (26North 'Ascend Partner' / 'Ascend Partners', Antares 'Clear Capital'
    # / 'ClearCapital'). A different entity of the group printed on this row (MidCap 'Wildcat Parent
    # LP' on the equity row of 'Wildcat BuyerCo, Inc.') is not a near spelling and still flags.
    con.execute("""CREATE OR REPLACE TEMP TABLE _cr_fund_names AS
        SELECT DISTINCT cik, cr_key(c) AS key
        FROM (SELECT cik, unnest(name_cells) AS c FROM _cr_names WHERE comparable)
        WHERE length(cr_key(c)) > 0""")
    # the headings the fund prints over its cash rows (Overland 'U.S. Treasury Bill'): a cash row named
    # after its own section heading is named as printed (owner 2026-11-10); GICS labels are not included
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _cr_cash_heads AS
        SELECT DISTINCT cik, cr_norm(extracted_industry) AS label FROM {table}
        WHERE (asset_category = 'CASH' OR index_classification = 'CASH') AND length(cr_norm(extracted_industry)) >= 4
          AND cr_norm(extracted_industry) NOT IN (SELECT label FROM _cr_gics)""")
    # per fund-quarter: how much of it the page test can see
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _cr_blind AS
        SELECT cik, report_date, count(*) AS n_rows,
               count(*) FILTER (WHERE printed_row IS NULL) AS n_no_printed_row,
               count(*) FILTER (WHERE printed_row IS NOT NULL AND NOT comparable) AS n_no_name_cell,
               1.0 * count(*) FILTER (WHERE NOT comparable) / count(*) AS blind_share_rows,
               coalesce(sum(abs(fair_value)) FILTER (WHERE NOT comparable) / nullif(sum(abs(fair_value)), 0), 0) AS blind_share_fv,
               1.0 * count(*) FILTER (WHERE NOT comparable) / count(*) >= {NAME_BLIND_LIMIT} AS page_test_suppressed
        FROM _cr_names GROUP BY 1, 2""")
    sql = f"""
        WITH x AS (
            -- a GICS label as the name is flagged even when the page prints it (New Mountain 'Software'); a
            -- fund's own label only when the page does not print it as the name (Overland 'U.S. Treasury Bill')
            SELECT n.*, (nname IN (SELECT label FROM _cr_gics)
                         OR (nname IN (SELECT label FROM _cr_labels) AND NOT lead_ok
                             AND NOT ((coalesce(n.asset_category, '') = 'CASH' OR coalesce(n.index_classification, '') = 'CASH')
                                      AND EXISTS (SELECT 1 FROM _cr_cash_heads ch
                                                  WHERE ch.cik = n.cik AND ch.label = n.nname)))) AS is_label,
                   (a.row_id IS NOT NULL) AS after_label_ok,
                   regexp_matches(issuer_name, '{_SECTION_START}') AS section_start,
                   -- the row's own industry heading at the front of its name ('Software Zendesk ...');
                   -- a company merely named after another industry word is not caught
                   (length(cr_norm(extracted_industry)) >= 4
                    AND starts_with(nname, cr_norm(extracted_industry) || ' ')) AS own_label_start,
                   regexp_matches(issuer_name, '{_CATEGORY_WORDS}') AS category_words,
                   (f.key IS NOT NULL AND coalesce(list_bool_or(list_transform(coalesce(n.name_cells, []),
                        c -> cr_near(cr_key(c), cr_key(n.issuer_name)))), false)) AS elsewhere_ok,
                   coalesce(bl.page_test_suppressed, false) AS suppressed
            FROM _cr_names n LEFT JOIN _cr_after_label a ON a.row_id = n.row_id AND a.accession_number = n.accession_number
            LEFT JOIN _cr_fund_names f ON f.cik = n.cik AND f.key = cr_key(n.issuer_name)
            LEFT JOIN _cr_blind bl ON bl.cik = n.cik AND bl.report_date = n.report_date),
        k AS (
            SELECT *, CASE
                WHEN is_label THEN 'equals_industry_label'
                WHEN comparable AND (suppressed OR elsewhere_ok) THEN NULL
                WHEN comparable AND NOT coalesce(direct_ok, false) AND NOT after_label_ok AND coalesce(whitespace_ok, false)
                     THEN 'whitespace_only'
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
    out = _fetch(con, sql)
    out.attrs["blind_spots"] = issuer_name_blind_spots(con)
    return out


def issuer_name_blind_spots(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Per fund-quarter, the rows rule 1 could not test on the page (no printed row, or a printed row
    with no name cell), and whether its page test was suppressed. Read after the rule has run; the
    rule also returns it as ``result.attrs['blind_spots']``. A clean result on a suppressed or mostly
    blind fund-quarter means 'not looked at', not 'names right'."""
    return con.execute("SELECT * FROM _cr_blind ORDER BY cik, report_date").fetchdf()


# ---------------------------------------------------------------------------------------------
# Rule 2
# ---------------------------------------------------------------------------------------------

# A count with its unit word: '( 1,824 units)', '878 shares of common stock', '8,642,579 preferred interests'.
_LABELLED_COUNT = (r"(?i)(?:^|[\s(])([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s+"
                   r"(?:(?:preferred|common|ordinary|voting|non-voting|restricted|lp|llc|partnership|membership|"
                   r"class [a-z0-9-]+|series [a-z0-9-]+)\s+){0,3}(?:units?|shares?|interests?)\b")
# '.50' is 0.5, not 50 (a figure printed with no leading zero; same reading as rule 3's _PIK_NUMBER)
_ANY_NUMBER = r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?|\.[0-9]+"
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

    Passes (D-207): the printed row shows the published count, whatever the member says (Ares PFL
    'up to 3,280,444 shares' in the member, 3,223,122 printed and published). The issuer name is taken
    out of the text first ('VCI Asset Holdings 1 LLC Class B Interests' is not a count of 1). kind
    ``units_scale_unclear``: the published count is exactly 1,000 times a figure on the printed row
    (HPS 'Par Amount/Units' 6,312 published 6,312,000; Bain '4' in an in-thousands schedule): the
    schedule does not say whether units are in thousands, so it is not an error until ruled. Only
    where the row prints no unit word: a labelled count published x1000 ('Common Stock (36,533
    shares)', 36,532,680 published) stays ``labelled_count_differs``.
    """
    tol = "greatest(1e-4 * abs(c), CASE WHEN abs(c) >= 100 THEN 0.51 ELSE 0.006 END)"

    def clean(expr: str) -> str:
        # issuer name out, then dates out (Trinity's member reads '... June 30, 2022 Shares ...')
        return (f"regexp_replace(regexp_replace(replace(lower(coalesce({expr}, '')), "
                f"lower(coalesce(nullif(trim(issuer_name), ''), '\x01')), ' '), "
                f"'{_DATE_WORDS}', ' DATE ', 'g'), '[0-9]{{1,2}}/[0-9]{{1,2}}/[0-9]{{2,4}}', ' DATE ', 'g')")

    def numbers(expr: str) -> str:
        return (f"list_filter(list_transform(regexp_extract_all({expr}, '{_ANY_NUMBER}'), "
                f"x -> TRY_CAST(replace(x, ',', '') AS DOUBLE)), x -> x IS NOT NULL)")
    sql = f"""
        WITH b AS (
            SELECT *, {clean('printed_row')} || ' || ' || {clean('bdc_investment_identifier')} AS txt,
                   {clean('printed_row')} AS page_txt
            FROM {table} WHERE asset_category LIKE 'EQUITY%'),
        c AS (
            SELECT *, list_filter(list_transform(regexp_extract_all(txt, '{_LABELLED_COUNT}', 1),
                                                 x -> TRY_CAST(replace(x, ',', '') AS DOUBLE)), x -> x IS NOT NULL AND x > 0) AS labelled,
                      {numbers('txt')} AS figures, {numbers('page_txt')} AS page_figures
            FROM b),
        d AS (
            SELECT *, shares_held IS NOT NULL AND printed_row IS NOT NULL
                      AND coalesce(list_bool_or(list_transform(page_figures, c -> abs(shares_held - c) <= {tol})), false) AS on_row,
                      shares_held IS NOT NULL AND printed_row IS NOT NULL
                      AND coalesce(list_bool_or(list_transform(page_figures,
                          c -> c > 0 AND abs(shares_held - 1000 * c) <= greatest(1e-4 * 1000 * c, 0.51))), false) AS times_1000
            FROM c),
        k AS (
            SELECT *, CASE
                WHEN on_row THEN NULL
                -- only where the row prints no unit word: '(36,533 shares)' published 36,532,680 is an error
                WHEN times_1000 AND len(labelled) = 0 AND shares_held_source = 'derived_proxy' THEN 'units_scale_unclear'
                WHEN len(labelled) > 0 AND shares_held IS NULL THEN 'labelled_count_not_published'
                WHEN len(labelled) > 0 AND NOT list_bool_or(list_transform(labelled, c -> abs(shares_held - c) <= {tol}))
                     THEN 'labelled_count_differs'
                WHEN len(labelled) = 0 AND shares_held_source = 'derived_proxy' AND printed_row IS NOT NULL
                     AND shares_held IS NOT NULL
                     AND NOT coalesce(list_bool_or(list_transform(figures, c -> abs(shares_held - c) <= {tol})), false)
                     THEN 'proxy_count_not_on_row'
              END AS kind_
            FROM d)
        SELECT {_select('unit_count_differs_from_row_text', 'kind_',
                        "CASE WHEN kind_ IN ('proxy_count_not_on_row', 'units_scale_unclear') THEN 'page' "
                        "WHEN printed_row IS NOT NULL AND regexp_matches(printed_row, '" + _LABELLED_COUNT + "') THEN 'page' "
                        "ELSE 'member' END",
                        "coalesce(CAST(shares_held AS VARCHAR), '') || ' (' || coalesce(shares_held_source, 'tagged') || ')'",
                        "CASE WHEN len(labelled) > 0 THEN array_to_string(labelled, '; ') ELSE 'figures: ' || array_to_string(figures, '; ') END")}
        FROM k WHERE kind_ IS NOT NULL ORDER BY report_date, issuer_name"""
    return _fetch(con, sql)


# ---------------------------------------------------------------------------------------------
# Rule 3
# ---------------------------------------------------------------------------------------------

# A figure may be printed with no leading zero: Varagon '( .50 % PIK)' is 0.50, not 50. The
# leading-dot alternative matches first at the dot, so the digits after it are never read alone.
_PIK_NUMBER = r"([0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
_PIK_PERCENT = r"(?i)" + _PIK_NUMBER + r"\s*%\s*\)?\s*PIK\b"
# a figure without a percent sign: basis points from 25 up ('including 75 PIK', '1350 PIK', 'S+450 PIK')
_PIK_BARE = r"(?i)(?:^|[^a-z0-9.%,])" + _PIK_NUMBER + r"\s*\)?\s*PIK\b"
_PIK_NOT_A_FIGURE = r"(?i)\b(class|series|tranche|notes?)\s+[0-9]+"
# D-232: whole-coupon PIK printed '<benchmark> [(tenor)] + m % PIK <coupon> %'. Benchmark codes are the
# ones the HTML bridge reads from an Index column (pipeline/bdc_xbrl_html_bridge._BENCHMARK_CODE).
_BENCH_CODES = "|".join(sorted(_BENCHMARK_CODE, key=lambda c: (-len(c), c)))
# The page reader joins cells with ' | ' ('S + | 6.25% PIK | 11.35%').
_BENCH_PLUS = r"(?i)(?:^|[^a-z0-9])(?:" + _BENCH_CODES + r")[\s|]*(?:\(\s*[a-z0-9]{1,3}\s*\)[\s|]*)?\+[\s|]*"
_PIK_AFTER_BENCHMARK = _BENCH_PLUS + _PIK_NUMBER + r"\s*%\s*PIK\b"
# REQ-rfcr-1 / REQ-rfbn-1 (owner 2026-11-04): the margin in basis points ('S + 1075 PIK', 'E + 1000 PIK (100
# Floor)'; read as percent below 25, as _PIK_BARE), and a benchmark printed in a cell of its own with the
# PIK margin in a later cell and no '+' ('EURIBOR | 10.00% PIK | 13.25%', 'SONIA | - | 10.00% PIK'). A
# cell between them may hold only a dash. Continental Battery ('First Lien Debt | 7.00% PIK') has no
# benchmark on the row and is not read.
_PIK_BPS_AFTER_BENCHMARK = _BENCH_PLUS + r"([0-9]+(?:\.[0-9]+)?)\s*PIK\b"
_PIK_AFTER_BENCHMARK_CELL = (r"(?i)(?:^|\|)\s*(?:" + _BENCH_CODES + r")\s*(?:\|\s*[-\x{2013}\x{2014}]*\s*)*\|\s*"
                             + _PIK_NUMBER + r"\s*%\s*PIK\b")
# REQ-rfbn-1 floating PIK leg (D-218, VardimanBlack): '<benchmark> + a % PIK + f % [Fixed] R %': the PIK
# leg floats at benchmark + a, the cash leg is the fixed f, so pik_rate = R - f. Captures f.
_PIK_LEG_FIXED = _BENCH_PLUS + r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\s*%\s*PIK[\s|]*\+[\s|]*" + _PIK_NUMBER + r"\s*%"
_PERCENT_FIGURE = _PIK_NUMBER + r"\s*%"


@lru_cache(maxsize=1)
def _disk_whole_coupon() -> tuple[frozenset, frozenset]:
    from pipeline.source_encodings import load_encodings, whole_coupon_pik_exclusions, whole_coupon_pik_funds
    enc = load_encodings()
    return frozenset(whole_coupon_pik_funds(enc)), frozenset(whole_coupon_pik_exclusions(enc))


def _whole_coupon_config(funds=None, exclusions=None) -> tuple[set, set]:
    """({cik10} declaring the whole-coupon PIK reading, {(cik10, accession, context)} listed against it);
    either defaults to the wrappers on disk (read once per process)."""
    if funds is None or exclusions is None:
        disk_funds, disk_exclusions = _disk_whole_coupon()
        funds = disk_funds if funds is None else funds
        exclusions = disk_exclusions if exclusions is None else exclusions
    return set(funds), set(exclusions)


# A benchmark is at most this far below the coupon (same bound as pipeline.whole_coupon_pik.MAX_BENCHMARK).
WHOLE_COUPON_MAX_BENCHMARK = 8.0


def pik_printed_not_published(con: duckdb.DuckDBPyConnection, table: str = "cand_rows",
                              whole_coupon_funds=None, whole_coupon_exclusions=None) -> pd.DataFrame:
    """The row or its member text prints a PIK figure and the published pik_rate is empty or differs.

    Figures: 'N % PIK' (percent), and a bare 'N PIK' / '(including N PIK)' / 'plus N PIK' read as basis
    points from 25 up and as percent below. 'Class 2 PIK', '0.00 % PIK' and a PIK word without a
    figure ('PIK toggle, not elected') are not figures. '100 % PIK' means the whole coupon is PIK: it
    counts as printed but is not compared. kind ``pik_value_mismatch``: a pik_rate is published and
    matches no figure (nor their sum) to 0.011; often the page prints the PIK margin and pik_rate holds
    the all-in PIK coupon, so read these before treating them as errors.

    Only the printed row raises those two kinds (D-207). A figure that only the member text carries
    goes to the weaker kind ``pik_member_text_only`` (basis ``member`` when no printed row is joined,
    ``member_page_silent`` when the printed row prints none): the page has been seen to disagree with
    the member (AB American Physician, Diameter BVI). A published tag that is the printed figure
    rounded to fewer decimals (3.8 for 3.83) passes. D-232 (owner 2026-10-25): a whole-coupon PIK row printed
    '<benchmark> [(tenor)] + m % PIK <coupon> %' passes when pik_rate is a printed percent figure on that row,
    not a PIK figure and above m (the coupon); without the benchmark code ('7.00 % PIK 11.29 %') it does not.
    Owner 2026-11-04 (REQ-rfcr-1 / REQ-rfbn-1): m may be printed in basis points ('S + 1075 PIK 15.66 %') or
    after a benchmark printed in its own cell ('EURIBOR | 10.00% PIK | 13.25%'); a floating PIK leg with a
    fixed cash leg ('SOFR + 2.00 % PIK + 5.00 % Fixed 12.30 %', D-218) passes when pik_rate = R - f (7.30),
    and is not treated as a whole coupon (12.30 still flags).

    Owner ruling 2026-11-10 (check repair): where the build applies the whole-coupon convention (the fund
    declares ``source_encodings.pik_margin_reading: ["whole_coupon"]`` and the row is not listed as
    "not ACCESSION CONTEXT", or the row carries ``pik_rate:whole_coupon_printed``), pik_rate may be the
    printed coupon with no benchmark on the row (Continental Battery 2025-09-30 '7.00 % PIK | 11.29 %'): a
    printed percent that is not a PIK figure, above the largest PIK figure and at most
    WHOLE_COUPON_MAX_BENCHMARK above it. Outside the convention the comparison is unchanged; a pik_rate
    equal to neither the margin nor the coupon still flags. ``whole_coupon_funds`` / ``whole_coupon_exclusions``
    default to the wrappers on disk.
    """
    funds, excluded = _whole_coupon_config(whole_coupon_funds, whole_coupon_exclusions)
    funds_sql = ", ".join("'%s'" % c for c in sorted(funds)) or "''"
    excluded_sql = ", ".join("'%s'" % "|".join(e).replace("'", "''") for e in sorted(excluded)) or "''"

    def clean(expr: str) -> str:
        return (f"regexp_replace(regexp_replace(coalesce({expr}, ''), '([0-9]) \\| %', '\\1 %', 'g'), "
                f"'{_PIK_NOT_A_FIGURE}', '\\1 X', 'g')")

    def figures(expr: str) -> str:
        txt = clean(expr)
        return f"""list_sort(list_distinct(list_filter(list_concat(
                       list_transform(regexp_extract_all({txt}, '{_PIK_PERCENT}', 1), x -> TRY_CAST(x AS DOUBLE)),
                       list_transform(regexp_extract_all({txt}, '{_PIK_BARE}', 1),
                                      x -> CASE WHEN TRY_CAST(x AS DOUBLE) >= 25 THEN TRY_CAST(x AS DOUBLE) / 100.0
                                                ELSE TRY_CAST(x AS DOUBLE) END)), x -> x IS NOT NULL AND x > 0)))"""

    # does a published pik_rate agree with these figures: to 0.011, as their sum, as the whole coupon
    # ('100 % PIK'), or as a figure rounded to one decimal or fewer
    agrees = ("(list_contains({f}, 100.0) OR list_bool_or(list_transform({f}, x -> abs(pik_rate - x) <= 0.011)) "
              "OR abs(pik_rate - list_sum({f})) <= 0.011 "
              "OR (abs(pik_rate * 10 - round(pik_rate * 10)) < 1e-6 "
              "    AND list_bool_or(list_transform({f}, x -> abs(pik_rate - x) < 0.1))))")
    sql = f"""
        WITH b AS (
            SELECT * FROM {table}
            WHERE regexp_matches(coalesce(printed_row, '') || ' || ' || coalesce(bdc_investment_identifier, ''),
                                 '(?i)[0-9]\\s*%?\\s*\\)?\\s*PIK\\b')),
        g0 AS (SELECT *, {figures('printed_row')} AS page_figs, {figures('bdc_investment_identifier')} AS member_figs,
                      -- D-232: m in '<benchmark> + m % PIK', and every percent figure on the printed row
                      -- (percent, basis points, or a benchmark cell of its own; REQ-rfcr-1 / REQ-rfbn-1)
                      list_max(list_concat(
                          list_transform(regexp_extract_all({clean('printed_row')}, '{_PIK_AFTER_BENCHMARK}', 1),
                                         x -> TRY_CAST(x AS DOUBLE)),
                          list_transform(regexp_extract_all({clean('printed_row')}, '{_PIK_BPS_AFTER_BENCHMARK}', 1),
                                         x -> CASE WHEN TRY_CAST(x AS DOUBLE) >= 25 THEN TRY_CAST(x AS DOUBLE) / 100.0
                                                   ELSE TRY_CAST(x AS DOUBLE) END),
                          list_transform(regexp_extract_all({clean('printed_row')}, '{_PIK_AFTER_BENCHMARK_CELL}', 1),
                                         x -> TRY_CAST(x AS DOUBLE)))) AS bench_pik,
                      -- f in '<benchmark> + a % PIK + f %' (floating PIK leg, fixed cash leg f)
                      list_max(list_transform(regexp_extract_all({clean('printed_row')}, '{_PIK_LEG_FIXED}', 1),
                                              x -> TRY_CAST(x AS DOUBLE))) AS pik_leg_fixed,
                      list_filter(list_transform(regexp_extract_all({clean('printed_row')}, '{_PERCENT_FIGURE}', 1),
                                                 x -> TRY_CAST(x AS DOUBLE)), x -> x IS NOT NULL) AS page_pcts
               FROM b),
        g AS (SELECT *,
                     -- whole coupon: pik_rate is a printed percent above m that is not itself a PIK figure.
                     -- Not when a fixed cash leg follows the PIK margin: that coupon is not all PIK.
                     (bench_pik IS NOT NULL AND pik_leg_fixed IS NULL AND pik_rate > bench_pik
                        AND coalesce(list_bool_or(list_transform(page_pcts,
                                c -> c > bench_pik AND abs(pik_rate - c) <= 0.011
                                     AND NOT coalesce(list_bool_or(list_transform(page_figs, p -> abs(c - p) <= 0.011)), false))), false))
                     -- floating PIK leg: pik_rate is a printed rate R above a + f, less the fixed cash leg f
                     OR (bench_pik IS NOT NULL AND pik_leg_fixed IS NOT NULL
                        AND coalesce(list_bool_or(list_transform(page_pcts,
                                c -> c > bench_pik + pik_leg_fixed AND abs(pik_rate - (c - pik_leg_fixed)) <= 0.011)), false))
                        AS whole_coupon_pik,
                     -- the build's whole-coupon convention applies to this row (owner 2026-11-10)
                     ((cik IN ({funds_sql})
                       AND (cik || '|' || coalesce(accession_number, '') || '|' || coalesce(src_context_id, ''))
                           NOT IN ({excluded_sql}))
                      OR contains(coalesce(src_transforms, ''), 'pik_rate:whole_coupon_printed'))
                     AND pik_leg_fixed IS NULL AND len(page_figs) > 0 AND NOT list_contains(page_figs, 100.0)
                     AND coalesce(list_bool_or(list_transform(page_pcts,
                             c -> abs(pik_rate - c) <= 0.011 AND c > list_max(page_figs)
                                  AND c - list_max(page_figs) <= {WHOLE_COUPON_MAX_BENCHMARK}
                                  AND NOT coalesce(list_bool_or(list_transform(page_figs, p -> abs(c - p) <= 0.011)), false))), false)
                        AS convention_coupon
              FROM g0),
        k AS (
            SELECT *, CASE
                WHEN len(page_figs) > 0 AND coalesce(pik_rate, 0) = 0 THEN 'pik_printed_not_published'
                WHEN len(page_figs) > 0 AND {agrees.format(f='page_figs')} THEN NULL
                WHEN len(page_figs) > 0 AND whole_coupon_pik THEN NULL
                WHEN len(page_figs) > 0 AND convention_coupon THEN NULL
                WHEN len(page_figs) > 0 THEN 'pik_value_mismatch'
                WHEN len(member_figs) > 0 AND coalesce(pik_rate, 0) = 0 THEN 'pik_member_text_only'
                WHEN len(member_figs) > 0 AND NOT {agrees.format(f='member_figs')} THEN 'pik_member_text_only'
              END AS kind_
            FROM g)
        SELECT {_select('pik_printed_not_published', 'kind_',
                        "CASE WHEN len(page_figs) > 0 THEN 'page' "
                        "WHEN printed_row IS NOT NULL THEN 'member_page_silent' ELSE 'member' END",
                        "coalesce(CAST(pik_rate AS VARCHAR), '')",
                        "array_to_string(CASE WHEN len(page_figs) > 0 THEN page_figs ELSE member_figs END, '; ')")}
        FROM k WHERE kind_ IS NOT NULL ORDER BY report_date, issuer_name"""
    return _fetch(con, sql)


# ---------------------------------------------------------------------------------------------
# Rule 4
# ---------------------------------------------------------------------------------------------

_FUNDED = ("fair_value > 0 AND coalesce(asset_category, '') <> 'CASH' AND coalesce(index_classification, '') <> 'CASH'")


def _exempt_sql(exemptions: dict | None) -> str:
    ciks = sorted((INDUSTRY_EXEMPTIONS if exemptions is None else exemptions).keys())
    return ", ".join("'%s'" % c for c in ciks) or "''"


def industry_coverage(con: duckdb.DuckDBPyConnection, table: str = "cand_rows",
                      threshold: float = INDUSTRY_COVERAGE_THRESHOLD, warning: float = INDUSTRY_COVERAGE_WARNING,
                      min_rows: int = INDUSTRY_MIN_ROWS, exemptions: dict | None = None) -> pd.DataFrame:
    """Per fund and quarter: funded rows, the share carrying gics_sub_industry (published) and
    extracted_industry (filer's printed heading), and ``level``: finding (below ``threshold``),
    warning (below ``warning``), ok, too_few_rows, or exempt (fund in INDUSTRY_EXEMPTIONS)."""
    return con.execute(f"""
        WITH c AS (
            SELECT cik, report_date, count(*) AS n_funded,
                   count(*) FILTER (WHERE nullif(trim(gics_sub_industry), '') IS NULL) AS n_no_gics,
                   sum(fair_value) FILTER (WHERE nullif(trim(gics_sub_industry), '') IS NULL) AS fv_no_gics,
                   1.0 - count(*) FILTER (WHERE nullif(trim(gics_sub_industry), '') IS NULL) / count(*) AS gics_coverage,
                   1.0 - count(*) FILTER (WHERE nullif(trim(extracted_industry), '') IS NULL) / count(*) AS extracted_coverage,
                   sum(fair_value) AS fv_funded
            FROM {table} WHERE {_FUNDED} GROUP BY 1, 2)
        SELECT *, CASE WHEN cik IN ({_exempt_sql(exemptions)}) THEN 'exempt'
                       WHEN n_funded < {int(min_rows)} THEN 'too_few_rows'
                       WHEN gics_coverage < {float(threshold)} THEN 'finding'
                       WHEN gics_coverage < {float(warning)} THEN 'warning'
                       ELSE 'ok' END AS level
        FROM c ORDER BY 1, 2""").fetchdf()


def industry_not_published(con: duckdb.DuckDBPyConnection, table: str = "cand_rows",
                           threshold: float = INDUSTRY_COVERAGE_THRESHOLD,
                           min_rows: int = INDUSTRY_MIN_ROWS, exemptions: dict | None = None) -> pd.DataFrame:
    """Funded rows with no published industry (gics_sub_industry), in fund-quarters whose coverage is
    below ``threshold`` and that have at least ``min_rows`` funded rows; funds in INDUSTRY_EXEMPTIONS
    (their filings print no industry) are left out. kind says whether the filer's own industry
    (extracted_industry) is also missing. Warning-level fund-quarters are in ``industry_coverage``."""
    sql = f"""
        WITH q AS (
            SELECT cik, report_date FROM {table} WHERE {_FUNDED} AND cik NOT IN ({_exempt_sql(exemptions)}) GROUP BY 1, 2
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
# A section heading that names a class for a whole block: a geography before 'preferred stock', or
# 'preferred stock/equity' followed by its percent of net assets (written out or as a figure).
_PREFERRED_HEADING = (r"(?i)(\b(u\.?\s?s\.?|non-u\.?\s?s\.?|us)\s*preferred\s+(stock|equity)"
                      r"(\s*-\s*[0-9.]+\s*%|\s+at\s+[a-z ]*percentage)?"
                      r"|\bpreferred\s+(stock|equity)\s*-\s*[0-9.]+\s*%)")


def preferred_published_as_common(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> pd.DataFrame:
    """An equity row classed common (asset_category EQUITY_COMMON or index_classification
    COMMON_EQUITY) whose instrument, member or printed row says preferred. kind ``text_and_rate``
    when it also carries a PIK or dividend rate.

    A rate alone is not evidence (owner ruling 2026-10-18, D-207: PIK-dividend units are not preferred
    unless the filer calls them preferred), so the former kind ``rate_on_common`` is gone.

    The issuer's own name is removed from the text first ('Preferred Freezer Services'). Warrants
    are left out (a warrant to buy preferred is not preferred), and so is text that also says common.

    kind ``preferred_heading_only`` (weaker, not a finding; ruling 2026-10-19 under D-207): the only
    'preferred' is a section heading carried in the member ('U.S. Preferred Stock - 1.30 %', 'U.s.preferred
    Stock At Two Point Zero Three Percentage'), while the instrument and the printed row do not say it
    (AB 'Avant NewCo Holdings, L.P. / Class A Units', 'Swyft Parent Holdings LP / LP Interests').
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
                   -- the same text with section headings taken out
                   regexp_matches(regexp_replace(txt, '{_PREFERRED_HEADING}', ' ', 'g'), '{_PREFERRED_WORD}') AS row_says_pref,
                   coalesce(pik_rate, 0) > 0 OR coalesce(interest_rate, 0) > 0 AS has_rate,
                   regexp_matches(txt, '(?i)\\bwarrants?\\b') AS warrant
            FROM b),
        z AS (
            SELECT *, CASE WHEN warrant THEN NULL
                           WHEN says_pref AND NOT row_says_pref THEN 'preferred_heading_only'
                           WHEN says_pref AND has_rate THEN 'text_and_rate'
                           WHEN says_pref THEN 'text_says_preferred'
                      END AS kind_
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


# ---------------------------------------------------------------------------------------------
# Ledger wiring (2026-10-19, D-207): stable rule names, finding kinds, tested rows
# ---------------------------------------------------------------------------------------------

# The ledger rule_name of each rule (scripts/shadow_identity_engine.py).
LEDGER_NAMES = {
    "issuer_name_differs_from_page": "issuer_name_printed",
    "unit_count_differs_from_row_text": "units_printed",
    "pik_printed_not_published": "pik_printed",
    "industry_not_published": "industry_coverage",
    "preferred_published_as_common": "preferred_printed",
}
# Kinds that are findings; every other kind a rule emits is weaker evidence and goes to the
# informational artifact only (re-sample 2026-10-19: the weaker kinds were about half right).
FINDING_KINDS = {
    "issuer_name_differs_from_page": {"not_the_printed_name", "spacing_only", "equals_industry_label",
                                      "begins_with_section_word", "begins_with_industry_label",
                                      "holds_category_path"},
    "unit_count_differs_from_row_text": {"proxy_count_not_on_row", "labelled_count_differs",
                                         "labelled_count_not_published"},
    "pik_printed_not_published": {"pik_printed_not_published", "pik_value_mismatch"},
    "industry_not_published": {"no_industry_at_all", "filer_industry_not_mapped"},
    "preferred_published_as_common": {"text_says_preferred", "text_and_rate"},
}


def tested_rows_sql(rule: str, table: str = "cand_rows") -> str:
    """The rows a rule can test: the denominator of its ledger result. A fund-quarter with no tested
    row gets no ledger result, so a rule never fires (or passes) where it cannot look.

    issuer_name_printed: rows with an issuer name in fund-quarters below NAME_BLIND_LIMIT untested
                         (needs the rule to have run: reads _cr_blind).
    units_printed:       equity rows with a printed row or a member that labels a count.
    pik_printed:         rows with a printed row (findings are raised on the page only).
    industry_coverage:   funded rows of non-exempt fund-quarters with INDUSTRY_MIN_ROWS or more.
    preferred_printed:   rows classed common equity with any instrument, member or printed text.
    """
    if rule == "issuer_name_differs_from_page":
        return f"""SELECT t.cik, t.report_date, t.row_id FROM {table} t
                   JOIN _cr_blind bl ON bl.cik = t.cik AND bl.report_date = t.report_date
                   WHERE nullif(trim(t.issuer_name), '') IS NOT NULL AND NOT bl.page_test_suppressed"""
    if rule == "unit_count_differs_from_row_text":
        return f"""SELECT cik, report_date, row_id FROM {table}
                   WHERE asset_category LIKE 'EQUITY%'
                     AND (printed_row IS NOT NULL OR regexp_matches(coalesce(bdc_investment_identifier, ''), '{_LABELLED_COUNT}'))"""
    if rule == "pik_printed_not_published":
        return f"SELECT cik, report_date, row_id FROM {table} WHERE printed_row IS NOT NULL"
    if rule == "industry_not_published":
        return f"""SELECT cik, report_date, row_id FROM {table}
                   WHERE {_FUNDED} AND cik NOT IN ({_exempt_sql(None)})
                     AND (cik, report_date) IN (SELECT cik, report_date FROM {table} WHERE {_FUNDED}
                                                GROUP BY 1, 2 HAVING count(*) >= {INDUSTRY_MIN_ROWS})"""
    if rule == "preferred_published_as_common":
        return f"""SELECT cik, report_date, row_id FROM {table}
                   WHERE (asset_category = 'EQUITY_COMMON' OR index_classification = 'COMMON_EQUITY')
                     AND coalesce(instrument_description, bdc_investment_identifier, printed_row) IS NOT NULL"""
    raise KeyError(rule)


LEDGER_ROW_COLUMNS = ["rule_name", "cik", "report_date", "row_id", "finding", "kind"]


def ledger_rows(con: duckdb.DuckDBPyConnection, table: str = "cand_rows") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the five rules on ``table`` and return (tested, informational, blind_spots).

    tested: one row per tested row and rule (LEDGER_ROW_COLUMNS), ``finding`` 1.0 when a finding kind
    flags it, else 0.0. A finding outside the tested rows is dropped to informational (it cannot
    happen by construction; kept as a guard). informational: every flagged row of a weaker kind, plus
    rule-1 flags in fund-quarters it does not test (OUTPUT_COLUMNS + rule_name). blind_spots: rule 1's
    per fund-quarter table.
    """
    tested_parts, info_parts = [], []
    blind = pd.DataFrame()
    for rule, fn in RULES.items():
        flagged = fn(con, table)
        if rule == "issuer_name_differs_from_page":
            blind = flagged.attrs.get("blind_spots", pd.DataFrame())
        flagged.attrs.clear()  # a frame in attrs breaks pd.concat
        key =["cik", "report_date", "row_id"]
        tested = con.execute(tested_rows_sql(rule, table)).fetchdf().astype("string").drop_duplicates(key)
        flagged = flagged.astype({c: "string" for c in key})
        flagged = flagged.merge(tested.assign(_tested=True), on=key, how="left")
        is_finding = flagged["kind"].isin(FINDING_KINDS[rule]) & flagged["_tested"].eq(True)
        info = flagged[~is_finding].drop(columns="_tested")
        info["rule_name"] = LEDGER_NAMES[rule]
        info_parts.append(info)
        findings = flagged.loc[is_finding, key + ["kind"]].drop_duplicates(key)
        out = tested.merge(findings, on=key, how="left")
        out["finding"] = out["kind"].notna().astype(float)
        out["rule_name"] = LEDGER_NAMES[rule]
        tested_parts.append(out[LEDGER_ROW_COLUMNS])
    tested_all = pd.concat(tested_parts, ignore_index=True) if tested_parts else pd.DataFrame(columns=LEDGER_ROW_COLUMNS)
    info_parts = [p for p in info_parts if not p.empty]
    info_all = pd.concat(info_parts, ignore_index=True) if info_parts else pd.DataFrame(columns=OUTPUT_COLUMNS + ["rule_name"])
    return tested_all, info_all, blind


def load_rows(con: duckdb.DuckDBPyConnection, holdings_path: Path, status_path: Path | None, cik: str,
              table: str = "cand_rows") -> str:
    """load_fund_rows for explicit files: unified holdings (parquet or csv) and the page reader's
    field status (parquet or csv, may be absent). Used by the shadow identity engine on production."""
    def src(p: Path) -> str:
        p = Path(p)
        return (f"read_parquet('{p.as_posix()}')" if p.suffix == ".parquet"
                else f"read_csv('{p.as_posix()}', header=true, all_varchar=true, sample_size=-1)")
    return _load(con, src(holdings_path), src(status_path) if status_path and Path(status_path).exists() else None,
                 cik, table)
