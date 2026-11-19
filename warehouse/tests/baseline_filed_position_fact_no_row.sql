-- Baseline: facts placed on a context with a investment-identifier axis member (axis local name InvestmentIdentifierAxis, any prefix) that sit in no kept table row and are not in ix:hidden.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['filed_position_fact_no_row']) }}
select p.accession, p.fact_id, p.concept, p.context_id
from {{ ref('stg_filed_fact_placement') }} p
where p.row_index is null
  and not coalesce(p.in_hidden, false)
  and exists (
      select 1 from {{ ref('stg_filed_context_member') }} m
      where m.accession = p.accession and m.context_id = p.context_id and m.axis like '%:InvestmentIdentifierAxis'
  )
