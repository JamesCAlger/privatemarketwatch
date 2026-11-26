-- Decides what each filing's own legend says a rate code means, as rates of seed reference_rate (text slice R phase 3,
-- 2026-11-26; owner items 2 and 3: "the filing's own legend first; a filing that gives two names decides nothing").
-- One row per (cik, accession, code_key) with a legend entry (int_text_check_legend).
--
-- Each entry's rates, by exact lookup (no substring; owner addition B): the entry's name upper-cased, and its
-- abbreviation (upper case, spaces removed), each looked up in seed reference_rate_name (printed_name) and in seed
-- reference_rate (rate_name, upper case, spaces removed). An entry whose name and abbreviation resolve to two rates
-- ("Norwegian Overnight Weighted Average Rate ("NIBOR")": NOWA and NIBOR) gives both.
-- rates: the distinct rates of the filing's entries for the code, sorted; n_rates; unresolved_entries: entries with
-- neither part resolved (a name the tables do not list, e.g. "Japan Unsecured Overnight Call Rate Expected").
-- verdict: one_rate (n_rates = 1), two_rates (the filing decides nothing for the code), unresolved (n_rates = 0).
with entry as (
    select l.cik, l.accession, l.report_date, l.code_key, l.name, l.abbreviation
        , coalesce(rn.rate_name, rr.rate_name) as name_rate
        , coalesce(an.rate_name, ar.rate_name) as abbreviation_rate
    from {{ ref('int_text_check_legend') }} l
    left join {{ ref('reference_rate_name') }} rn on rn.printed_name = upper(trim(l.name))
    left join {{ ref('reference_rate') }} rr on upper(replace(rr.rate_name, ' ', '')) = upper(replace(l.name, ' ', ''))
    left join {{ ref('reference_rate_name') }} an on an.printed_name = l.abbreviation_key
    left join {{ ref('reference_rate') }} ar on upper(replace(ar.rate_name, ' ', '')) = l.abbreviation_key
)

, entry_rate as (
    select cik, accession, report_date, code_key, name_rate as rate from entry where name_rate is not null
    union
    select cik, accession, report_date, code_key, abbreviation_rate from entry where abbreviation_rate is not null
)

, filing_code as (
    select cik, accession, min(report_date) as report_date, code_key
        , count(*) filter (where name_rate is null and abbreviation_rate is null) as unresolved_entries
        , count(*) as entries
    from entry
    group by 1, 2, 4
)

select
    f.cik
    , f.accession
    , f.report_date
    , f.code_key
    , f.entries
    , f.unresolved_entries
    , coalesce(list_sort(list_distinct(list(r.rate) filter (where r.rate is not null))), []::varchar[]) as rates
    , count(distinct r.rate) as n_rates
    , case when count(distinct r.rate) = 1 then 'one_rate' when count(distinct r.rate) > 1 then 'two_rates'
           else 'unresolved' end as verdict
from filing_code f
left join entry_rate r on r.accession = f.accession and r.cik = f.cik and r.code_key = f.code_key
group by f.cik, f.accession, f.report_date, f.code_key, f.entries, f.unresolved_entries
