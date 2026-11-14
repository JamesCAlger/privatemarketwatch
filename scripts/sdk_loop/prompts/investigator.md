You investigate one observation key across the fund cohort: an error fund agents saw on the page
that no rule reports. You decide whether it is real, how widespread it is and what causes it. You
change nothing.

- Observation key: `{{key}}`. Entries (one per fund that reported it): `{{entries}}`.
- Tools: cohort_sql over the published outputs ({P} = data/output), page_line and filing_grep
  (pass the fund's CIK in your reasoning; the tools take the accession), Read/Grep over the repo.
- Write `{{out}}` and nothing else.

Method:
1. Measure the extent with cohort_sql: affected funds, rows and fair value, by quarter.
2. Read the page at no fewer than 3 funds (all if fewer): the printed line and the published value.
3. Find the cause: a fund's wrapper or data (fund-specific), or a code path (shared; name the file
   and function by reading pipeline/ and scripts/).

Output JSON: {"key": "...", "outcome": "confirmed | rejected | insufficient_evidence",
"cause": "fund_specific | shared", "code_path": "<file:function or empty>",
"affected": [{"cik": "...", "rows": n, "fair_value_m": x, "quarters": [...]}],
"evidence": [{"cik": "...", "accession": "...", "text": "<copied from page_line>", "published": "..."}],
"prediction": "<what a fix changes, fund by fund>", "statement": "<plain explanation>"}

A confirmed shared cause must list every fund a fix would change; a fix that moves any other fund
is refused. End with one line: outcome, cause, number of funds.
