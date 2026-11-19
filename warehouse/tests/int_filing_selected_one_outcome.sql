-- Each quarter is either selected (accession and selection_rule, no refusal) or refused (refusal_reason, no accession).
select cik, report_date, accession, selection_rule, refusal_reason
from {{ ref('int_filing_selected') }}
where not (
    (accession is not null and selection_rule is not null and refusal_reason is null)
    or (accession is null and selection_rule is null and refusal_reason is not null)
)
