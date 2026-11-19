-- Every selected accession is a parsed filing of the same fund with the same period end.
select s.cik, s.report_date, s.accession
from {{ ref('int_filing_selected') }} s
left join {{ ref('stg_filed_filing') }} f
    on f.accession = s.accession and f.cik = s.cik and f.document_period_end_date = s.report_date
where s.accession is not null
  and f.accession is null
