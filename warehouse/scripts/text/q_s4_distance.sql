-- Slice R phase 2: distribution of implied base minus the nearest edge of the proposed rate's window (no tolerance),
-- usable rows with a window, per rate and quarter. Read-only.
select proposed_rate, report_date, count(*) n,
  round(avg(case when distance = 0 then 1 else 0 end),3) inside,
  round(quantile_cont(distance, 0.02),2) p02, round(quantile_cont(distance, 0.10),2) p10, round(quantile_cont(distance,0.5),2) p50,
  round(quantile_cont(distance, 0.90),2) p90, round(quantile_cont(distance, 0.98),2) p98,
  round(avg(case when distance between -0.30 and 0.30 then 1 else 0 end),3) w30,
  round(avg(case when distance between -0.30 and 0.56 then 1 else 0 end),3) w30csa,
  round(avg(case when distance between -0.60 and 0.60 then 1 else 0 end),3) w60
from int_text_check_base_level where is_proposed and distance is not null
group by all order by 1,2
