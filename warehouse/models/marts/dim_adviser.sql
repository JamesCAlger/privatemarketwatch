select distinct
    lower(replace(b.manager_brand, ' ', '_')) as adviser_id,
    b.manager_brand
from {{ ref('manager_brand') }} b
where b.cik in (select cik from {{ ref('stg_v05_scope') }})
