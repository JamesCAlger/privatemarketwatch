-- Slice 4 Task 3: three example rows per fund and rate rule (or conflict / feature_missing group), latest quarter
-- first, with the tagged values and the printed text of the same facts, and the stored result.
with u as (
    select u.cik, u.accession, u.context_id, u.report_date, u.field, u.resolution
        , coalesce(r.action, u.resolution) as rule_label
        , row_number() over (partition by u.cik, u.field, coalesce(r.action, u.resolution) order by u.report_date desc, u.context_id) as k
    from int_field_rule u
    left join stg_reading_rule r on r.rule_id = u.rule_id
    where u.field in ('interest_rate', 'spread') and (r.cik is not null or u.resolution in ('rule_conflict', 'feature_missing'))
)
select u.cik, u.rule_label, u.field, u.report_date, u.accession, u.context_id
    , (select string_agg(f.field || '=' || cast(f.value_filed as varchar) || ' [' || coalesce(f.printed_text, '') || ']', '; ' order by f.field)
       from int_field_read f where f.accession = u.accession and f.context_id = u.context_id
         and f.field in ('interest_rate_tag', 'pik_rate', 'spread') and f.status = 'read' and not f.is_nil) as tagged
    , (select string_agg(n.field || '=' || coalesce(cast(round(n.value, 4) as varchar), n.status || ':' || n.reason), '; ' order by n.field)
       from int_field_normalised n where n.accession = u.accession and n.context_id = u.context_id
         and n.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')) as stored
from u where k <= 3
order by 1, 2, 3, 4 desc
