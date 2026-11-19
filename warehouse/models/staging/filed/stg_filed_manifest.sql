-- One row per filing folder and table, from the folder's _manifest.json: the row count the parser recorded.
-- Folder is the manifest's own path. Thin view: no logic beyond turning the nine table entries into rows.
{% set tables = ['filing', 'context', 'context_member', 'unit', 'tagged_fact', 'document_row', 'fact_placement', 'footnote', 'fact_footnote'] %}
{% for t in tables %}
select
    accession
    , cik
    , parser_version
    , filename as manifest_file
    , '{{ t }}' as table_name
    , tables.{{ t }}.rows as manifest_rows
    , tables.{{ t }}.content_hash as manifest_content_hash
from {{ source('filed', 'manifest') }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
