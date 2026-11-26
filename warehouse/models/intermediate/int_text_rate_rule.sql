-- The rate-text rules the owner accepted (text slice R phase 3, 2026-11-26), as typed columns: the wrapper copies'
-- `reading_rules` entries with target rate_text (written by scripts/text/accepted_rules_to_wrappers.py, loaded by the
-- readings loader as stg_reading_rule rows whose parameter is canonical JSON). One row per rule: rule_id.
--
-- action (seed reading_action):
--   rate_column           a column the read model reads: table_signature, header_signature (as int_text_column_unit),
--                         header_text, column_holds.
--   rate_role             one number of one shape in such a column: shape (exact spelling, macro text_shape),
--                         number_index (k-th number), role (spread_bps, spread_pct, floor_pct, all_in_rate_pct,
--                         cash_rate_pct, pik_rate_pct, pik_spread_pct, fixed_rate_pct).
--   rate_code             one row of the fund's dated code table: code as printed, code_key (upper case, spaces
--                         removed), rate (a rate_name of seed reference_rate), first/last_filing_date (report dates of
--                         the filings whose own legend gives the code that rate alone; null for an undated entry),
--                         evidence_accession.
--   rate_text_not_a_code  a printed word that is not a rate code (code, code_key).
--   rate_printed_wins     in one filing (sel_accession), table table_index, printed rows first_row to last_row, the
--                         printed value of field wins over the filer's tag.
-- source_grade: checked (accepted by a check), matches_few_rows (owner item 7: every tagged row matches, under the
-- 5-row bar), untested (no check possible: floors, rare shapes with no tagged row, fixed rates of a filer with no all-in tag), owner (the
-- owner accepted it: items 1 to 4, 8 to 10, 13, the 2022-09-30 shifted-tag finding). grade_rank: checked 1, matches_few_rows
-- 2, owner 3, untested 4 (the read model keeps the strongest when two rules give one value).
-- rule_key (fix round 2): a stable key of what the rule reads, for finding ids. rule_id is the loader's content hash over
-- every column, evidence and dated parameters included, so it changes when evidence wording, a count or a date changes.
-- rule_key hashes only: fund, action, table and header signature, shape, number index, role, the condition column and
-- text (rate_role); code and rate (rate_code, rate_text_not_a_code); field, table index and printed rows (rate_printed_wins,
-- with its filing, the rule's scope). Never evidence, counts, filing dates or the evidence filing.
with r as (
    select *, json_extract_string(parameter, '$.table_signature') as p_table_signature
        , json_extract_string(parameter, '$.header_signature') as p_header_signature
        , json_extract_string(parameter, '$.shape') as p_shape
        , json_extract_string(parameter, '$.number_index') as p_number_index
        , json_extract_string(parameter, '$.role') as p_role
        , json_extract_string(parameter, '$.condition_header_signature') as p_cond_header
        , json_extract_string(parameter, '$.condition_text') as p_cond_text
        , upper(replace(json_extract_string(parameter, '$.code'), ' ', '')) as p_code_key
        , json_extract_string(parameter, '$.rate') as p_rate
        , json_extract_string(parameter, '$.field') as p_field
        , json_extract_string(parameter, '$.table_index') as p_table_index
        , json_extract_string(parameter, '$.first_row') as p_first_row
        , json_extract_string(parameter, '$.last_row') as p_last_row
    from {{ ref('stg_reading_rule') }}
    where target = 'rate_text'
)

select
    rule_id
    , left(md5(concat_ws('|', cik, action, coalesce(p_table_signature, ''), coalesce(p_header_signature, ''),
                         coalesce(p_shape, ''), coalesce(p_number_index, ''), coalesce(p_role, ''),
                         coalesce(p_cond_header, ''), coalesce(p_cond_text, ''), coalesce(p_code_key, ''),
                         coalesce(p_rate, ''), coalesce(p_field, ''), coalesce(p_table_index, ''),
                         coalesce(p_first_row, ''), coalesce(p_last_row, ''),
                         case when action = 'rate_printed_wins' then coalesce(sel_accession, '') else '' end)), 16)
        as rule_key
    , cik
    , action
    , sel_accession as accession
    , json_extract_string(parameter, '$.source_grade') as source_grade
    , case json_extract_string(parameter, '$.source_grade')
        when 'checked' then 1 when 'matches_few_rows' then 2 when 'owner' then 3 when 'untested' then 4 end as grade_rank
    , json_extract_string(parameter, '$.table_signature') as table_signature
    , json_extract_string(parameter, '$.header_signature') as header_signature
    , json_extract_string(parameter, '$.header_text') as header_text
    , json_extract_string(parameter, '$.column_holds') as column_holds
    , json_extract_string(parameter, '$.shape') as shape
    , try_cast(json_extract_string(parameter, '$.number_index') as integer) as number_index
    , json_extract_string(parameter, '$.role') as role
    -- fix round 1: whole_coupon (a PIK-only number in an all-in column is also the all-in rate, owner item 9);
    -- condition_header_signature / condition_text (the role applies only where the same row's cell in that column of
    -- the same table prints that text, upper case and trimmed: a "Ref. Rate" cell printing N/A, owner item 11)
    , coalesce(try_cast(json_extract_string(parameter, '$.whole_coupon') as boolean), false) as whole_coupon
    , json_extract_string(parameter, '$.condition_header_signature') as condition_header_signature
    , json_extract_string(parameter, '$.condition_text') as condition_text
    , json_extract_string(parameter, '$.code') as code
    , upper(replace(json_extract_string(parameter, '$.code'), ' ', '')) as code_key
    , json_extract_string(parameter, '$.rate') as rate
    , try_cast(json_extract_string(parameter, '$.first_filing_date') as date) as first_filing_date
    , try_cast(json_extract_string(parameter, '$.last_filing_date') as date) as last_filing_date
    , json_extract_string(parameter, '$.evidence_accession') as evidence_accession
    , json_extract_string(parameter, '$.field') as field
    , try_cast(json_extract_string(parameter, '$.table_index') as integer) as table_index
    , try_cast(json_extract_string(parameter, '$.first_row') as integer) as first_row
    , try_cast(json_extract_string(parameter, '$.last_row') as integer) as last_row
    , evidence
from r
