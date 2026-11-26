-- Slice R phase 2: proposed code mappings against the per-filing legend, by fund. Read-only.
select cik, verdict, count(*) filings_units, sum(positions) positions, string_agg(distinct code_key || '=' || proposed_rate || coalesce('/' || legend_rates, ''), ' ') filter (where verdict in ('mixed','contradicts','unclear')) detail
from int_text_check_code_legend group by all order by 1,2
