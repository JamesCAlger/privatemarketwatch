select
    report_date,
    year(report_date)                                                        as year,
    quarter(report_date)                                                     as quarter,
    strftime(report_date, '%Y') || 'q' || cast(quarter(report_date) as varchar) as quarter_label
from (select distinct report_date from {{ ref('stg_holdings') }})
