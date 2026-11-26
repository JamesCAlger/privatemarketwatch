-- Owner item 3 (2026-11-26; slice R phase 3 fix round 1): each filing's own legend (int_text_legend_rate) against the
-- fund's dated code table (int_text_rate_rule action rate_code with dates). Returns, for a dated rule whose
-- [first_filing_date, last_filing_date] covers the filing's report date, a filing whose own legend gives that code
-- another rate alone (one_rate, other rate) or two rates (two_rates: the code is undecided inside a rule's span). A
-- disagreement fails the build until someone looks at it: the table is generated from the same legends, so a new
-- filing that disagrees must not be absorbed (the generator, scripts/text/accepted_rules_to_wrappers.py, also refuses to
-- write over a contradicted entry). Fix round 2: undated rules (owner items 4 and 13) hold at every date and are tested at
-- every filing. Measured 2026-11-26: 0.
select l.cik, l.accession, l.report_date, l.code_key, l.verdict, l.rates, r.rule_id, r.rate as table_rate
    , r.first_filing_date, r.last_filing_date
from {{ ref('int_text_legend_rate') }} l
join {{ ref('int_text_rate_rule') }} r
    on r.action = 'rate_code' and r.cik = l.cik and r.code_key = l.code_key
    and (r.first_filing_date is null or l.report_date between r.first_filing_date and r.last_filing_date)
where (l.verdict = 'one_rate' and l.rates[1] <> r.rate) or l.verdict = 'two_rates'
