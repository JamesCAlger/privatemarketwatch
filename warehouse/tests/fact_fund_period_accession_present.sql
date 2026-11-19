-- A fund-quarter with positions names the filing they came from.
select cik, report_date
from {{ ref('fact_fund_period') }}
where has_positions and accession_number is null