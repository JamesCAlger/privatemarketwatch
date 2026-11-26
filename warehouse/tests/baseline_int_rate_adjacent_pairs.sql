-- Slice 5 Task 4 baseline: pairs int_rate_adjacent finds (a taker position takes the rate facts of its neighbouring
-- rate-only context), against a ceiling set to the measured count (baseline_max.int_rate_adjacent_pairs). Measured
-- 2026-11-24: 7, all of the one fund whose wrapper declares the rule (2023-12-31 1, 2025-03-31 1, 2025-06-30 3,
-- 2025-09-30 2). A new pair, or a pair of another fund, fails the build until it is looked at.
{{ config(tags=['baseline_ceiling'], severity='error', warn_if='>0',
          error_if='>' ~ var('baseline_max')['int_rate_adjacent_pairs']) }}
select * from {{ ref('int_rate_adjacent') }}
