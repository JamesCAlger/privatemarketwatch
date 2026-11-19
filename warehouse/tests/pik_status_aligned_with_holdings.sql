-- The PIK status file is written by a separate pipeline stage. Every holding must find its row there,
-- and that row must describe the same filing and value. A stale file would fail here.
select h.row_id, h.accession_number, p.accession_number as pik_accession_number,
       h.fair_value, p.fair_value as pik_fair_value
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_position_pik_status') }} p
       on p.cik = h.cik and p.report_date = h.report_date and p.position_id = h.position_id
where p.position_id is null
   or p.accession_number is distinct from h.accession_number
   or abs(coalesce(p.fair_value, 0) - coalesce(h.fair_value, 0)) > 0.005