-- Slice R phase 2 fix round 1, item 6: per fund and proposed rate, quarters with >= 10 tested rows that are confirmed,
-- discriminating, separate the currency bloc; and the other-currency rates admissible (> 0.5) with their quarter
-- counts. Read-only.
with q as (select * from int_text_check_base_level_quarter where tested >= 10),
o as (select cik, proposed_rate, unnest(string_split(other_currency_admissible_rates, ',')) r, report_date from q where other_currency_admissible_rates is not null),
oc as (select cik, proposed_rate, string_agg(r || ':' || n || ' (' || mn || '..' || mx || ')', ' ' order by n desc, r) as other from
       (select cik, proposed_rate, r, count(*) n, min(report_date) mn, max(report_date) mx from o group by all) group by all)
select q.cik, q.proposed_rate, count(*) as quarters, count(*) filter (where confirmed) as conf, count(*) filter (where discriminating) as disc,
  count(*) filter (where separates_currency_bloc) as bloc, any_value(oc.other) as other_currency_admissible
from q left join oc using (cik, proposed_rate) group by all order by 1, 3 desc
