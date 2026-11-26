-- Slice P, 2026-11-26: the concept and read rule of the fair-value fact of published positions, for the fund whose
-- 2,270 positions the P0 query (which matched the standard concept name) found unplaced. Read-only.
select p.cik, f.concept, fr.read_rule_id, p.report_date, count(*) as n
from int_page_position p
join int_field_read fr on fr.accession = p.accession and fr.context_id = p.context_id and fr.field = 'fair_value'
join stg_filed_fact f on f.accession = fr.accession and f.fact_id = fr.fact_id
where p.is_published and p.cik = '0001812554'
group by all
order by 1, 2, 4
