-- Slice 5 Task 3 baseline (spec section 7, the sum check) on the corrected published basis: per fund and report date,
-- the corrected fair value of the positions after corrections (int_row_corrected, int_field_corrected) against the
-- filed total investments, on the basis step 1 uses (macro sum_not_tied_rows, corrected=true). The normalised-basis
-- test (baseline_int_field_normalised_sum_not_tied.sql) stays as it is. Ceiling int_field_corrected_sum_not_tied;
-- tests/int_field_corrected_sum_not_tied_set.sql pins the set.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_corrected_sum_not_tied']) }}
{{ sum_not_tied_rows(corrected=true) }}
