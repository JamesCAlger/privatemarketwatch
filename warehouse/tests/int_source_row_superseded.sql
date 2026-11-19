-- A context is superseded (rule 0) exactly when its filing is not the one selected for its fund and quarter, including
-- a refused quarter.
select r.accession, r.context_id, r.role, r.role_rule, s.accession as selected_accession
from {{ ref('int_source_row') }} r
join {{ ref('int_filing_candidate') }} c on c.accession = r.accession
join {{ ref('int_filing_selected') }} s on s.cik = c.cik and s.report_date = c.report_date
where (s.accession is distinct from r.accession) <> (r.role = 'superseded' and r.role_rule = 0)
