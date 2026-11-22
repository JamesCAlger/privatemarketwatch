-- Baseline (spec section 7, the sum check): per fund and report date, the published positions' normalised fair value
-- against the filed total investments, on the basis step 1 uses (macro sum_not_tied_rows, which holds the rule and
-- the controller ruling). Both differences are listed. Ceiling int_field_normalised_sum_not_tied. The count does not
-- see a swap (one quarter starts tying while another stops); tests/int_field_normalised_sum_not_tied_set.sql pins the
-- set by key (final fix wave F5).
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_normalised_sum_not_tied']) }}
{{ sum_not_tied_rows() }}
