-- Slice 5 Task 3: int_field_reread runs the conversion chain's macros again on a few rows. On a filed position (one
-- re-read because it carries a correction at step filed) its run raw must give exactly the row of int_field_normalised,
-- or the second run is not the same chain. Compares every column of int_field_normalised, both ways.
with reread as (
    select * exclude (run, read_unit)
    from {{ ref('int_field_reread') }} rr
    where rr.run = 'raw'
      and exists (
          select 1 from {{ ref('int_source_row') }} s
          where s.accession = rr.accession and s.context_id = rr.context_id and s.role = 'position'
      )
)

, normalised as (
    select n.*
    from {{ ref('int_field_normalised') }} n
    semi join (select distinct accession, context_id from reread) r on r.accession = n.accession and r.context_id = n.context_id
)

select 'only in reread' as side, * from (select * from reread except all select * from normalised)
union all
select 'only in normalised', * from (select * from normalised except all select * from reread)
