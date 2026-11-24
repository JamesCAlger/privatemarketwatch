-- Slice 5 Task 3, a stop condition of the brief made a rule: a context corrections make a position must have the role
-- its row reason allows. correction_supplies_fair_value: not_schedule by rule 3; correction_supplies_term: unresolved
-- by rule 7 or 9; correction_adds_row: not a position, by rule 1 (the issuer-axis context with no investment
-- identifier member, as measured for the 8 row_add positions; any other rule fails until it is looked at).
-- Also fails on a promoted row that is not published (scope other than fund).
select accession, context_id, cik, report_date, row_reason, role_filed, role_rule_filed, scope
from {{ ref('int_row_corrected') }}
where row_reason <> 'filed'
  and (
    not case row_reason
        when 'correction_supplies_fair_value' then role_filed = 'not_schedule' and role_rule_filed = 3
        when 'correction_supplies_term' then role_filed = 'unresolved' and role_rule_filed in (7, 9)
        when 'correction_adds_row' then role_filed = 'not_schedule' and role_rule_filed = 1
        else false
      end
    or not is_published
  )
