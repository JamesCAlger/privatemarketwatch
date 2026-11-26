-- Slice R phase 2: every failing leg identity row with its printed cells. Read-only.
select l.cik, l.report_date, l.identity, round(l.lhs,3) lhs, round(l.rhs,3) rhs, l.detail, l.sources,
  (select string_agg(distinct r.cell_text, ' | ') from int_text_rate_proposed r where r.accession=l.accession and r.context_id=l.context_id) cells,
  p.t_all_in, p.t_spread, p.t_pik, p.t_cash
from int_text_check_leg_arithmetic l
join int_text_rate_proposed_position p using (accession, context_id)
where l.verdict='fail' order by 1,2,3
