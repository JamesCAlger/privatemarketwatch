-- Owner question 2026-11-25: what "unread" covers. Published rate fields left empty for reason text_not_read, by fund
-- and field, and how production holds the same field (cmp_rate outcome). Read-only.
select c.cik, c.field, c.outcome, count(*) as n
from cmp_rate c
join int_field_corrected f on f.accession = c.accession and f.context_id = c.context_id and f.field = c.field
where f.reason = 'text_not_read' and c.is_published
group by all order by 1, 2, 3
