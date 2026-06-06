# SC TO-I Review Instructions

You are reviewing SC TO-I tender-offer extraction residuals. Your job is to
classify the bundle and produce a schema-valid verdict JSON. Do not edit
production outputs.

You must tag every filing in the bundle using `filing_tags`. Use the bundle's
deterministic role hints as evidence, but your manual tag is the review result.

Allowed filing tags:

- `issuer_self_tender`: the issuer/fund is buying its own securities.
- `third_party_tender`: an outside purchaser is buying another issuer's
  securities.
- `not_final_or_no_results`: the filing does not report final results.
- `unknown_role`: the offer role cannot be determined safely.
- `missing_html`: the cached filing HTML is unavailable.

Allowed verdicts:

- `NO_RESULTS_EXPECTED`: the filing is an original/intermediate offer or does
  not report final tender offer results.
- `PARSER_PATTERN_PROPOSED`: the filing reports results and the parser missed a
  general language pattern. Cite evidence snippets and affected fields.
- `STRUCTURE_UNSUPPORTED`: the filing reports results, but the structure needs a
  new parser mechanism rather than a regex extension.
- `OUT_OF_SCOPE_THIRD_PARTY`: all filings in the packet are third-party tender
  offers. Tag them, but do not propose repurchase-result extraction.
- `INSUFFICIENT_EVIDENCE`: the bundle does not contain enough evidence to decide.
- `ESCALATE`: the issue is ambiguous, high risk, or needs human judgment.

Rules:

- Cite bundle evidence IDs, not raw assertions.
- Propose only general patterns that could apply across filers.
- Do not propose CIK-specific regexes.
- Do not edit or recommend editing generated CSV/JSON outputs by hand.
- Cite filing-specific evidence for each `filing_tags` entry.
- Do not propose parser patterns for filings tagged `third_party_tender`.
- Issuer debt tender offers, including tenders for notes or other debt
  securities reported in aggregate principal amount, do not affect share
  repurchase caps. Tag the filing role normally, but do not propose
  share-repurchase parser patterns for those filings; treat them as out of
  scope for repurchase-cap outputs.
- If proposing a parser pattern, include false-positive risk and a test plan.
