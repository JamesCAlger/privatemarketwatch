-- Text slice R phase 3, check 1d (owner item 11), measurement before the model: every number row of a single-number
-- shape with no rate code whose proposed role (either order) is a spread or a fixed rate, against the all-in tag.
-- code_elsewhere: the position has a read code in another column unit (Ares prints its code in "Reference").
with r as (
    select p.*, sr.role_fwd, sr.role_rev
    from int_text_rate_proposed p
    join text_proposed_shape_role sr on sr.unit_key = p.unit_key and sr.shape = p.shape and sr.number_index = p.number_index
    where p.number_index = 1 and length(p.shape) - length(replace(p.shape, '#', '')) = 1
        and regexp_extract(coalesce(p.cell_text, ''), '^([A-Za-z][A-Za-z.]*(?: [A-Za-z][A-Za-z.]*)*?)\s*(?:\+|\(|\d|$)', 1) = ''
        and (sr.role_fwd in ('spread_pct', 'spread_bps', 'fixed_rate_pct') or sr.role_rev in ('spread_pct', 'spread_bps', 'fixed_rate_pct'))
)
, t as (
    select accession, context_id, any_value(value) as t_all_in
    from int_field_normalised
    where field = 'interest_rate' and rate_kind = 'all_in' and status = 'normalised' and value is not null
    group by 1, 2
)
, c as (
    select distinct accession, context_id from int_text_rate_proposed where field = 'reference_rate_code' and status = 'read'
)
select r.cik, r.unit_key, r.shape, r.role_fwd, r.role_rev, any_value(u.column_holds_fwd) as column_holds
    , count(*) as n_rows
    , count(*) filter (where c.accession is not null) as code_elsewhere
    , count(t.t_all_in) as with_all_in_tag
    , count(*) filter (where abs(r.number_value - t.t_all_in) <= 0.005) as equal_all_in
from r
left join t on t.accession = r.accession and t.context_id = r.context_id
left join c on c.accession = r.accession and c.context_id = r.context_id
left join text_proposed_column u on u.unit_key = r.unit_key
group by all
order by 1, 2, 3
