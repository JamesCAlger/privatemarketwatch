-- The v0.5 funds. The acceptance thresholds file is the single place this list is kept.
select unnest(findings_scope.ciks) as cik
from read_json('{{ var("thresholds_file") }}')
