-- Slice R phase 2: base-level summary per fund and proposed rate: quarters with >= 10 tested rows, confirmed,
-- discriminating, contradicted; rows tested / admissible / floor binding / outside; alternatives admissible (> 0.5)
-- in how many tested quarters. Read-only.
with q as (select * from int_text_check_base_level_quarter),
alt as (select cik, proposed_rate, unnest(string_split(alt_admissible_rates, ',')) r from q where tested >= 10 and alt_admissible_rates is not null),
altc as (select cik, proposed_rate, string_agg(r || ':' || n, ' ' order by n desc, r) alts from (select cik, proposed_rate, r, count(*) n from alt group by all) group by all)
select q.cik, q.proposed_rate, count(*) filter (where tested>=10) as q10, count(*) filter (where confirmed) as conf,
  count(*) filter (where discriminating) as disc, count(*) filter (where contradicted) as contra,
  sum(tested) tested, sum(admissible) adm, sum(floor_binding) fb, sum(outside) outside, sum(not_tested) not_tested, sum(no_series) no_series,
  any_value(a.alts) alts
from q left join altc a using (cik, proposed_rate) group by all order by 1, tested desc
