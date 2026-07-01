# Gold set — source-adjudicated ground truth (v1 BDC cohort)

This directory holds the **held-out, source-adjudicated gold set** for the v1 BDC
enforcement panel. It is the only place in the repo where a value is asserted to be
**true** on the authority of a human reading the cached source filing — not the
pipeline output.

It exists to (a) measure per-rule precision so the enforcement registry can widen
past its deterministic floor, (b) bound the false-negative rate of suppressed
flags, and (c) clear false positives on single-anchor BDC CIK-quarters.

## Firewall rules (non-negotiable)

1. **Source, never output.** Every label is adjudicated from the cached filing
   (`data/raw/filings/bdc_html/{cik}/{accession}.html` — inline XBRL — and the
   financial statements therein). A label MUST NOT be copied from
   `private_markets_holdings.csv` or any pipeline artifact. Output-adjudicated
   labels measure nothing.
2. **Held out.** Gates and the fix-proposing agent MUST NOT tune against these
   labels. A gold-found error may motivate a rule; that rule's precision is then
   measured on a **fresh draw**, never the draw that surfaced it. Draws are frozen
   and seeded (see `samples/*_manifest.json`).
3. **Labeler independent of fixer.** The labeler agent reads the raw filing and is
   blind to the parsed pipeline row. The fixer reads the parsed output. Different
   inputs is the independence axis. Candidate labels carry
   `adjudicator: agent:*`; only human-confirmed records carry `adjudicator:
   human:*` and `label_status: human_confirmed`.
4. **`ambiguous` is first-class.** Genuinely indeterminate source (rate scale,
   affiliation axis, lien with no filer subtotal) is labeled `ambiguous`, not
   forced.
5. **Version-stamped.** Every record carries the `pipeline_version` (git SHA) it
   was labeled against, so a label can be retired if the parse it judged changed.

## Layout

```
data/gold/
  README.md                       # this file
  labeler_protocol.md             # how the agent reads source + cites; calibration + estimators
  schema/
    gold_label_schema_v1.json     # JSON Schema for every record (versioned)
  samples/
    sample_frame_<draw_id>.jsonl  # frozen list of units to label (one row per unit)
    sample_manifest_<draw_id>.json# draw params: seed, thresholds, strata sizes, pipeline_version, inclusion probs
  candidates/
    candidates_<draw_id>.jsonl    # labeler-agent pre-filled candidates (blind to pipeline)
  labels/
    position_labels.jsonl         # append-only human-confirmed position labels
    cik_quarter_labels.jsonl      # append-only human-confirmed CIK-quarter labels
```

`labels/*.jsonl` and `samples/*` are **append-only and committed**. Never rewrite a
label in place; correct by appending a superseding record (same key, later
`labeled_date`, `supersedes` set).

## Workflow

```
# 1. Draw / redraw the frozen stratified sample (read-only on outputs)
python scripts/gold/draw_gold_sample.py            # --k-tail 200 --n-pps 100 ...

# 2. Labeler agent pre-fills candidates from the cached filings (blind to pipeline)
python scripts/gold/labeler_agent.py --draw batch1

# 3. Human adjudication harness (confirm / correct / ambiguous, glance-and-click)
python scripts/gold/review_harness.py --who <you>  # -> http://127.0.0.1:5057

# 4. Estimates once labels accrue (Wilson + Horvitz-Thompson)
python scripts/gold/estimate_gold.py --draw batch1
```

`scripts/gold/tail_coverage_probe.py` is a read-only diagnostic for tuning the tail
threshold (FV concentration, all-history vs as-of snapshot).

## Status

Apparatus complete: schema + draw (snapshot-tuned) + labeler agent + harness +
protocol + estimators, all verified end-to-end. batch1 frame = **562 units**, FV
strata as-of **2025-12-31 (Q4 2025)**, candidates pre-filled. **No human labels
recorded yet** — ready for the first labeling session.
