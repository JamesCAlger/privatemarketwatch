-- Slice 5 Task 2 inventory (re-measures appendix A4): how many contexts each correction key finds today, without
-- applying anything. Context keys: the context's role in int_source_row. Identifier keys (row_corrections): positions
-- here with the same accession and identifier label (int_context_feature.identifier_label), and production rows with
-- the same accession and identifier (stg_holdings), the route of the production_bridge (decision 2, Task 3).
with ident as (
    select c.correction_id, c.cik, c.accession, c.identifier
        , (select count(*) from main.int_context_feature f
            join main.int_source_row s on s.accession = f.accession and s.context_id = f.context_id
            where f.accession = c.accession and f.identifier_label = c.identifier and s.role = 'position') as native_positions
        , (select count(*) from main.stg_holdings h
            where h.accession_number = c.accession and trim(h.bdc_investment_identifier) = c.identifier) as production_rows
    from main.stg_correction c
    where c.context_id is null and c.identifier is not null
)
select 'identifier' as key_kind, cik
    , case when native_positions = 0 then 'native none' when native_positions = 1 then 'native one' else 'native several' end
        as native
    , case when production_rows = 0 then 'production none' when production_rows = 1 then 'production one'
        else 'production several' end as production
    , count(*) as corrections
from ident group by all
union all
select 'context:' || c.kind, c.cik, coalesce(s.role, 'no context row'), case when c.store like 'wrapper:%' then 'wrapper'
        else c.store end, count(*)
from main.stg_correction c
left join main.int_source_row s on s.accession = c.accession and s.context_id = c.context_id
where c.context_id is not null
group by all
order by 1, 2, 3, 4
