-- 2026-11-26 (owner request): what production holds on the rows behind the test items the agents missed, to see
-- where the reference label or production itself is wrong. Read-only.
with ap as (
    select s.report_date, cf.identifier_label as label, h.interest_rate, h.interest_rate_cash, h.pik_rate
        , h.interest_rate_kind, h.basis_spread, h.reference_rate_type, coalesce(h.corrected_fields, '') as corrected
    from cmp_row_set s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where s.cik = '0001837532' and s.basis = 'published' and s.side = 'both'
)
select 'a cash plus PIK' as k, regexp_extract(label, '(Interest Rate.*?)(Maturity|$)', 1) as txt
    , cast(interest_rate as varchar) as rate, cast(interest_rate_cash as varchar) as cash, cast(pik_rate as varchar) as pik
    , interest_rate_kind as kind_or_ref, count(*) as n
from ap where label ilike '%cash plus%pik%' and interest_rate is not null group by all
union all
select 'b code ' || regexp_extract(label, 'Interest Rate\s+([A-Z]+)\s*\+', 1), null, null, null, null
    , coalesce(reference_rate_type, '(none)') || case when corrected like '%reference_rate_type%' then ' (corrected)' else '' end, count(*)
from ap where regexp_matches(label, 'Interest Rate\s+(K|N|T|C|P|L|E|SARON|STIBOR|BBSW)\s*\+') group by all
order by 1, 7 desc
