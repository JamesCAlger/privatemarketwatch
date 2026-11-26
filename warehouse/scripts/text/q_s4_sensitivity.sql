-- Slice R phase 2: tolerance sensitivity of the base-level check. For tolerance scale m (0, 0.5, 1, 2 times the
-- published/proxy tolerance; the SOFR adjustment kept), per (proposal, quarter) with >= 10 tested rows: confirmed and
-- discriminating counts, and tested-row share admissible. Floor binding ignored. Read-only.
with l as (
  select *, upper(replace(code,' ','')) code_key from int_text_check_base_level
  where input_state='usable' and distance is not null
), m as (select unnest([0.0, 0.5, 1.0, 2.0]) as m),
adm as (
  select m.m, l.code_unit_key, l.code_key, l.report_date, l.accession, l.context_id, l.candidate_rate, l.is_proposed,
    l.distance between -l.tolerance*m.m and l.tolerance*m.m + l.upper_extra as ok
  from l cross join m
), prop as (
  select m, code_unit_key, code_key, report_date, count(*) tested, avg(ok::int) as share
  from adm where is_proposed group by all
), alt as (
  select a.m, a.code_unit_key, a.code_key, a.report_date, a.candidate_rate, avg(a.ok::int) as share
  from adm a join adm p on p.m=a.m and p.accession=a.accession and p.context_id=a.context_id and p.is_proposed
  where not a.is_proposed group by all
), q as (
  select p.m, p.code_unit_key, p.code_key, p.report_date, p.tested, p.share, max(a.share) as best_alt
  from prop p left join alt a using (m, code_unit_key, code_key, report_date) group by all
)
select m, count(*) filter (where tested>=10) as quarters, count(*) filter (where tested>=10 and share>=0.9) as confirmed,
  count(*) filter (where tested>=10 and share>=0.9 and coalesce(best_alt,0)<=0.5) as discriminating,
  round(sum(share*tested)/sum(tested),4) as row_share_admissible
from q group by 1 order by 1
