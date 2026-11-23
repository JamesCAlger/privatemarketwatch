-- Slice 4 Task 3: rows the unbuilt procedure pik_margin_reading whole_coupon would touch, per fund and quarter
-- (production: pipeline/whole_coupon_pik.py apply/parse). Funds from stg_reading_not_loaded. Approximation of the
-- printed form: the printed row of the position's fair-value fact reads '<benchmark> + <margin> [%] ... PIK' once and
-- does not name toggle, incl or cash; and the row carries a PIK tag. Production's grammar is narrower (a coupon after
-- PIK, margin below the coupon by at most 8); its exceptions ("not ACCESSION CONTEXT") are counted apart.
with fund as (
    select distinct cik from stg_reading_not_loaded where wrapper_key = 'pik_margin_reading'
)
, pos as (
    select r.cik, r.report_date, r.accession, r.context_id, r.fact_id
    from int_field_read r semi join fund f on f.cik = r.cik
    where r.field = 'fair_value' and r.status = 'read'
)
, printed as (
    select p.*, array_to_string(dr.cells, ' | ') as row_text
    from pos p
    join stg_filed_fact_placement pl on pl.accession = p.accession and pl.fact_id = p.fact_id
    join stg_filed_document_row dr on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
    qualify row_number() over (partition by p.accession, p.context_id order by dr.row_index) = 1
)
, tags as (
    select accession, context_id
        , bool_or(field = 'pik_rate' and status = 'read' and not is_nil) as has_pik
        , bool_or(field = 'interest_rate_tag' and status = 'read' and not is_nil) as has_rate
    from int_field_read group by 1, 2
)
, exc as (
    select accession, context_id from stg_correction where store = 'wrapper:pik_margin_reading'
)
select p.cik, p.report_date
    , count(*) filter (where regexp_matches(p.row_text, '(?i)(^|[^A-Za-z])(TERMSOFR|TSOFR|EURIBOR|SONIA|CORRA|PRIME|SOFR|SF|SN|S|E|L|P|C)[\s|]*(\([A-Za-z0-9]{1,3}\)[\s|]*)?\+[\s|]*[0-9.]+\s*%?[^|]{0,30}[\s|]*PIK')
                         and not regexp_matches(p.row_text, '(?i)toggle|incl|(^|[^a-z])cash([^a-z]|$)') and t.has_pik) as candidates
    , count(*) filter (where regexp_matches(p.row_text, '(?i)(^|[^A-Za-z])(TERMSOFR|TSOFR|EURIBOR|SONIA|CORRA|PRIME|SOFR|SF|SN|S|E|L|P|C)[\s|]*(\([A-Za-z0-9]{1,3}\)[\s|]*)?\+[\s|]*[0-9.]+\s*%?[^|]{0,30}[\s|]*PIK')
                         and not regexp_matches(p.row_text, '(?i)toggle|incl|(^|[^a-z])cash([^a-z]|$)') and t.has_pik and t.has_rate) as with_rate_tag
    , count(*) filter (where e.context_id is not null) as listed_exceptions
from printed p
join tags t on t.accession = p.accession and t.context_id = p.context_id
left join exc e on e.accession = p.accession and e.context_id = p.context_id
group by all
order by 1, 2
