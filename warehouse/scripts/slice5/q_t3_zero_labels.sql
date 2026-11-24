-- Slice 5 Task 3 diagnostic: the identifier labels of the zero lines (contexts corrections made positions through their
-- fair value) and the subtotals decided through a fund rule in the same filing whose label shares the zero line's first
-- 12 characters.
select r.report_date, r.context_id, cf.identifier_label
    , (select string_agg(c2.identifier_label || ' [' || s.role || ' ' || s.role_rule || ' ' || coalesce(s.rule_id, '') || ']', ' ;; ')
       from main.int_source_row s
       join main.int_context_feature c2 on c2.accession = s.accession and c2.context_id = s.context_id
       where s.accession = r.accession and s.role = 'aggregate' and s.role_rule = 6
         and left(c2.identifier_label, 12) = left(cf.identifier_label, 12)) as subtotals
from main.int_row_corrected r
join main.int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
where r.row_reason = 'correction_supplies_fair_value'
order by 3, 1
