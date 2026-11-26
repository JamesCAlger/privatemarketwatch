-- Slice R phase 1 (2026-11-26): the legend entries behind mixed or contradicting map_code rules, per filing. Read-only.
select r.cik, r.parameter, r.state, l.accession, l.report_date, l.code, l.name, l.abbreviation, l.n_footnotes
from int_text_check_legend_rule r
join int_text_check_legend l on l.cik = r.cik and l.code_key = r.code_key
    and (r.valid_from is null or r.valid_from <= l.report_date) and (r.valid_to is null or l.report_date <= r.valid_to)
where r.state in ('mixed', 'contradicts')
  and l.accession in (select l2.accession from int_text_check_legend l2 where l2.cik = r.cik and l2.code_key = r.code_key
                      group by 1 having count(distinct l2.abbreviation_key) > 1)
order by 1, 2, 5, 7
