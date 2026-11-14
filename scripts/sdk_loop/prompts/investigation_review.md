You independently review one cross-fund investigation of an observation (an error fund agents
saw that no rule reports). You did not do the investigation and you change nothing.

- Observation key: `{{key}}`. Investigation: `{{investigation}}`.
- Write `{{review}}` and nothing else.

Check, with your own reads (cohort_sql is not available to you; use Read/Grep over the repo and
page_line / filing_grep on the cited filings):
1. Every evidence quote is on the page and shows what the investigation says.
2. The cause: is the named code path or fund setting really what produces the value?
3. The extent: does the affected list look complete for the cause (other funds using the same
   code path or filer format)?
4. For a shared cause: is the prediction specific enough that a fix moving any other fund would be
   caught?

Output JSON: {"key": "...", "outcome": "supported | rejected", "route": "not_real | fund_specific |
shared", "rationale": "...", "evidence": [{"cik": "...", "accession": "...", "text": "..."}]}.
`route` is your reading of where it should go; use not_real only when the observation is wrong.
End with one line: outcome and route.
