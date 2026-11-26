-- Text slice R phase 3, check 1d: read spread numbers in cells with no leading code (any shape), with the spread and
-- all-in tags, per unit and shape. Which accepted spread readings are fixed rates the filer also tags as a spread.
with r as (
    select * from int_text_rate_proposed
    where status = 'read' and field = 'spread'
        and regexp_extract(coalesce(cell_text, ''), '^([A-Za-z][A-Za-z.]*(?: [A-Za-z][A-Za-z.]*)*?)\s*(?:\+|\(|\d|$)', 1) = ''
)
, t as (
    select accession, context_id
        , any_value(value) filter (where field = 'interest_rate' and rate_kind = 'all_in') as t_all_in
        , any_value(value) filter (where field = 'spread') as t_spread
    from int_field_normalised
    where field in ('interest_rate', 'spread') and status = 'normalised' and value is not null
    group by 1, 2
)
, c as (
    select distinct accession, context_id from int_text_rate_proposed where field = 'reference_rate_code' and status = 'read'
)
select r.cik, r.unit_key, r.shape, r.number_index, r.role, count(*) n
    , count(*) filter (where c.accession is null) as no_code_on_position
    , count(t.t_all_in) as with_all_in
    , count(*) filter (where abs(r.value - t.t_all_in) <= 0.005) as eq_all_in
    , count(*) filter (where abs(r.value - t.t_spread) <= 0.005) as eq_spread
from r
left join t on t.accession = r.accession and t.context_id = r.context_id
left join c on c.accession = r.accession and c.context_id = r.context_id
group by all
having count(*) filter (where c.accession is null) > 0
order by 1, 2, 3
