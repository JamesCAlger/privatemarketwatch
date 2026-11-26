-- Slice R phase 1 measurement (2026-11-26): map_code rules against the legend, and codes printed in rate-candidate
-- columns with their rule/legend state and rows. Read-only.
select 'rule' as block, cik, parameter as what, state, agree_filings || '/' || contradict_filings || '/' || unclear_filings as a_c_u
    , legend_abbreviations as detail, null::bigint as rows, null::bigint as positions
from int_text_check_legend_rule
union all
select 'code', cik, code_key || ' [' || printed_codes || ']', state, cast(legend_filings as varchar), legend_abbreviations, rows, positions
from int_text_check_legend_code
order by 1, 2, 4, 3
