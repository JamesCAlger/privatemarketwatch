{#
  Review of slice 2 Task 6, fix round 1: a position that passed the term-fact cross-check only through a fund concept
  rule (concept_is_term_fact) is a release by that rule, as a label rule's release is. This macro lists such rows that
  production has no row for on the same basis, so a test can fail on them.

  In scope: role 'position' at rule 7 or 9, not cash, whose term fact comes only from a fund concept rule
  (term_fact_source is a rule id: none of principal, shares, rate, spread, PIK rate, maturity or ownership percent is
  tagged with a standard concept). Quarters production lacks (excluded) are out of scope: there is no side to compare.

  rows:     relation with accession, context_id, cik, report_date, role, role_rule, is_cash, is_published,
            term_fact_source
  prod:     relation with accession, context_id, is_published (one row per production row)
  excluded: relation with cik, report_date (fund-quarters left out of the comparison)
  Used by tests/baseline_concept_rule_release_not_in_production.sql (real data) and
  tests/concept_release_unmatched_fixture.sql (invented rows).
#}
{% macro concept_release_unmatched(rows, prod, excluded) %}
select r.accession, r.context_id, r.cik, r.report_date, r.term_fact_source, r.is_published
from {{ rows }} r
where r.role = 'position'
  and r.role_rule in (7, 9)
  and not r.is_cash
  and r.term_fact_source is not null
  and r.term_fact_source <> 'standard'
  and not exists (
      select 1 from {{ excluded }} x where x.cik = r.cik and x.report_date = r.report_date
  )
  and not exists (
      select 1 from {{ prod }} p
      where p.accession = r.accession and p.context_id = r.context_id and p.is_published = r.is_published
  )
{% endmacro %}
