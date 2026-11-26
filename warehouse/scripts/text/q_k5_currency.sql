-- K5 measurement (2026-11-26): the currency of the reference rate read from the page against the currency of the
-- position's principal tag. Independent of the filer's rate tags. Read-only. A mismatch is a row to look at, not an
-- error shown: a loan in one currency can price off another's benchmark, and 671 principal currencies are taken as USD.
with p as (
    select accession, context_id, currency as principal_currency
    from int_field_normalised where field = 'principal_amount' and currency is not null
)
select r.cik, r.reference_rate, rr.currency as rate_currency, p.principal_currency
    , count(*) as positions
    , min(r.report_date) as first_date, max(r.report_date) as last_date
    , string_agg(distinct r.code_printed, ',') as codes_printed
    , string_agg(distinct r.reference_rate_grade, ',') as grades
from int_text_rate_read r
join reference_rate rr on rr.rate_name = r.reference_rate
join p using (accession, context_id)
where rr.currency is not null and rr.currency <> p.principal_currency
group by 1, 2, 3, 4
order by positions desc
