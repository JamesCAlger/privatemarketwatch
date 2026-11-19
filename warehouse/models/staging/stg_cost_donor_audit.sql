select
    a.row_id,
    a.method as cost_method
from {{ source('pipeline', 'cost_donor_audit') }} a
where a.row_id in (select row_id from {{ ref('stg_holdings') }})
