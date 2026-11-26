-- Owner addition B (2026-11-26): every code mapping in the wrapper rules (int_text_rate_rule action rate_code) names a
-- rate of seed reference_rate, and every rate the read model gives a position is one. A mapping to a name not in the
-- table fails. Returns the offending rows.
select 'rate_code rule' as what, rule_id as key, rate
from {{ ref('int_text_rate_rule') }} r
where action = 'rate_code' and not exists (select 1 from {{ ref('reference_rate') }} t where t.rate_name = r.rate)
union all
select 'read cell', accession || '|' || context_id, reference_rate
from {{ ref('int_text_rate_read_cell') }} c
where reference_rate is not null
  and not exists (select 1 from {{ ref('reference_rate') }} t where t.rate_name = c.reference_rate)
union all
select 'legend rate', key, rate
from (select cik || '|' || accession || '|' || code_key as key, unnest(rates) as rate
      from {{ ref('int_text_legend_rate') }}) l
where not exists (select 1 from {{ ref('reference_rate') }} t where t.rate_name = l.rate)
