-- Slice 5 Task 3 exploration: identifier-keyed corrections with no native position, where production's row sits here.
with ident as (
    select c.correction_id, c.cik, c.accession, c.identifier, c.field, c.value
        , (select count(*) from main.int_context_feature f
            join main.int_source_row s on s.accession = f.accession and s.context_id = f.context_id
            where f.accession = c.accession and f.identifier_label = c.identifier and s.role = 'position') as native_positions
    from main.stg_correction c
    where c.context_id is null and c.identifier is not null
)
select i.cik, i.field, h.src_context_id, s.role, s.role_rule, s.reason, cf.has_term_fact, cf.fair_value_fact_count
    , count(*) over (partition by i.correction_id) as prod_rows, i.identifier, i.value
from ident i
left join main.stg_holdings h on h.accession_number = i.accession and trim(h.bdc_investment_identifier) = i.identifier
left join main.int_source_row s on s.accession = i.accession and s.context_id = h.src_context_id
left join main.int_context_feature cf on cf.accession = i.accession and cf.context_id = h.src_context_id
where i.native_positions = 0
order by 1, 4, 3
