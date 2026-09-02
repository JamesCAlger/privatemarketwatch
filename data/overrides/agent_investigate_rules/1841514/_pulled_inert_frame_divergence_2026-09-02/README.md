# Pulled 2026-09-02

rule_id: exclude_equity_subtotal_rows
reason: noop in production: instrument_description IS NULL true on published frame (CSV round-trip null) but false mid-build (staging sets empty string). Reauthored with COALESCE predicate.
Pulled by operator session 2026-09-02 (q1p3 inert-rule reauthor); replacement promoted through run_investigation gate.
