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
select
    rule_id
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
from {{ ref('stg_reading_rule') }}
where target = 'rate_text'
