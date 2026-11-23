-- Rate ruling B: int_rate_scale per fund, filing, field and outcome, with the rule's printed reading. Run with
-- scripts/slice2/run_sql.py.
select cik, accession, report_date, field, coalesce(printed_reading, '-') as printed_reading, outcome, printed_form
    , count(*) as n, min(value_filed) as min_filed, max(value_filed) as max_filed
from int_rate_scale
group by all
order by cik, report_date, field, outcome
