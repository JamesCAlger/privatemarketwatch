{#- True when the fund's wrapper declares that its filed total investments line leaves the schedule's cash rows out
    (fund rule, action filed_total_excludes_cash, in warehouse/wrappers/<cik>.json reading_rules), for the report
    date given. The declaration half of the owner's ruling of 2026-11-04 (check A04; production reads
    source_encodings.investments_total_excludes = ["cash_rows"]). Owner decision D16, 2026-11-23. Read by
    fact_fund_period.sql and macro sum_not_tied_rows. A declared fund is compared without its cash rows in every
    quarter the rule covers; a quarter that then does not tie is listed by the sum check like any other. -#}
{% macro filed_total_excludes_cash_declared(cik, report_date) %}
exists (
    select 1
    from {{ ref('stg_reading_rule') }} declared_rule
    where declared_rule.action = 'filed_total_excludes_cash'
      and declared_rule.cik = {{ cik }}
      and (declared_rule.valid_from is null or {{ report_date }} >= declared_rule.valid_from)
      and (declared_rule.valid_to is null or {{ report_date }} <= declared_rule.valid_to)
)
{% endmacro %}
