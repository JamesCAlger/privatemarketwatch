Pulled 2026-08-21: all_pik_normalization for CIK 0001287750 (promoted from q4b2r4canary).
Reason: semantic no-op -- template set cash_rate 0.0 but omitted set_interest_to_cash,
so apply_all_pik_normalization never wrote interest_rate (only normalized pik_rate
14.000000000000002 -> 14.0). The intended fix (explicit 0.0 cash leg on the PIK-only
15484880 Canada Inc senior subordinated loan, ROW-d9cfbfcb882d5425) was not applied.
Replaced by the re-authored q4b2r4an staging leaf (row_id selector +
set_interest_to_cash: true), B3 gate PASS 2026-08-21 (gate_0001287750.json in the
q4b2r4an batch dir). Session: admin-canary session 2026-08-21.
