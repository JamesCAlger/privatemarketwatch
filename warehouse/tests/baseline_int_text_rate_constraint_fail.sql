-- Owner addition A, constraints 4 and 5 (2026-11-26): positions whose rule-read fields fail the legs identity (c4) or
-- the base-rate level (c5), listed row by row with the rules involved, against a ceiling set to the measured count
-- (baseline_max.int_text_rate_constraint_fail). These compare with another source (tags, public rate series); some
-- failures are the filer's faulty tags or term-rate limits of the series, already known. Counts by fund and rate:
-- docs/baseline_text_rates_phase3_2026-11-26.md section 6. The ceiling stops growth; it does not hide the rows, which
-- this test returns.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_text_rate_constraint_fail']) }}
select cik, report_date, accession, context_id, constraint_name, reference_rate, lhs, rhs, implied_base, range_min
    , range_max, all_in_source, rule_ids
from {{ ref('int_text_rate_constraint') }}
where verdict = 'fail'
