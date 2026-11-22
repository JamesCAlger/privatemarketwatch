-- Slice 3 Task 5: the units the parser wrote for the CI fixture filings (to see how a pure unit is spelled). Diagnostic.
select accession, unit_id, numerator, denominator
from main.stg_filed_unit
order by accession, unit_id
limit 50
