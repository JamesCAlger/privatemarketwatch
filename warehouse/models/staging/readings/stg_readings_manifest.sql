-- The row count the loader recorded for each table, from _manifest.json.
{% set tables = ['reading_rule', 'correction', 'correction_rule', 'not_loaded', 'wrapper_drift', 'rule_label_example'] %}
{% for t in tables %}
select
    loader_version
    , '{{ t }}' as table_name
    , tables.{{ t }}.rows as manifest_rows
from {{ source('readings', 'manifest') }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
