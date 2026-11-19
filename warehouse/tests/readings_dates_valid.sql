-- Every date the loader wrote is a real date, and no rule ends before it starts.
select 'rule' as source, rule_id as id, valid_from_text as text_value
from {{ ref('stg_reading_rule') }}
where (valid_from_text <> '' and valid_from is null)
   or (valid_to_text <> '' and valid_to is null)
   or valid_from > valid_to
union all
select 'correction', correction_id, report_date_text
from {{ ref('stg_correction') }}
where report_date_text <> '' and report_date is null
