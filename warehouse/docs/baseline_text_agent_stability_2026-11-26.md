# Text: stability of a general agent on the 2026-11-19 items (2026-11-26)

The test named in `text_fields_spec_2026-11-19.md` (items 2 and 11) and never run until now: the same 204 items,
Sonnet and Haiku, each twice with the answer options in reversed order. Owner, 2026-11-26: "this seems like an
experiment that needs to be ran".

Agreement is with the 2026-11-19 reference labels, which come from tag counts and production output. It is not
correctness. The items ask for a classification per item; slice R asks an agent for a rule per column, a nearby
but different task.

## Set-up

- Items: the blind files of 2026-11-19 (73 column headers, 100 headings, 31 rate-cell patterns; 144 of the 204 have
  a strong reference label). Context as in that day's rich-context run.
- Four blind runs as subagents, each given only the three files and allowed only to read them and write answers:
  Sonnet forward, Sonnet reversed, Haiku forward, Haiku reversed. No run saw the labels or another run.
- Files: `scratch/2026-11-26_agent_stability/` (answers, `score.txt`); scripts `scripts/text/agent_stability/`.

## Results on the 144 strong-label items

| Run | Agree with label | Headers (50) | Headings (73) | Rates (21) | "Cannot tell" | Confidence 0.9 or more (all agreed with the label) | Tokens | Time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sonnet forward | 139 | 45 | 73 | 21 | 0 | 123 | 166k | 1.5 min |
| Sonnet reversed | 140 | 46 | 73 | 21 | 0 | 114 | 156k | 1.4 min |
| Haiku forward | 138 | 45 | 73 | 20 | 4 | 86 | 268k | 2.7 min |
| Haiku reversed | 140 | 48 | 73 | 19 | 2 | 82 | 328k | 2.8 min |

(2026-11-19, Sonnet once: 139, headers 46, headings 73, rates 20.)

Stability and agreement:

| Comparison | Same answer, all 204 | Same answer, 144 strong | Of those, agree with label |
|---|---:|---:|---:|
| Sonnet forward vs reversed | 196 | 143 | 139 |
| Haiku forward vs reversed | 195 | 139 | 137 |
| Sonnet vs Haiku (four pairings) | 189 to 196 | 135 to 138 | 134 to 137 |
| All four runs | | 134 | 133 |

## What it shows

1. The two models are equally accurate on these items (138 to 140 of 144). Haiku is not cheaper here: it used about
   twice the tokens and time, says "cannot tell" more, and is less sure. Its price per token is lower; cost per run
   was not computed.
2. Reversing the options changes about 4% of answers for either model over all 204 items (8 or 9 items). On the
   strong items Sonnet changed 1 answer, Haiku 5.
3. Headings: 73 of 73 in every run. Rates: Sonnet 21 of 21 twice. Headers are the weak kind: 45 to 48 of 50.
4. "All four agree" accepts 134 of 144 and one of those disagrees with the label: an Apollo column headed "Interest
   Rate" whose cells read "S+450, 0.50% Floor". All four runs call it an interest-rate column; the label says
   reference rate and spread. Agreement between runs does not catch a header that says one thing over cells that
   hold another. A check on the cells does (the pattern under the header, or the tags placed in the column).
5. Three headers Sonnet calls "other" twice where Haiku and the label say fair value: the models disagree with each
   other consistently, so a two-model rule sends them to the owner.

## What follows for slice R (recommendation; owner question 3 of the plan)

- Agreement is a filter, not the acceptor. A rule is accepted by its check (tags under the column; rate
  arithmetic). Where no check exists the owner accepts it, as the 2026-11-19 spec says.
- Run one model twice (options reversed). An item whose answer changes goes to the owner. Sonnet is the default on
  this evidence; Haiku gave no saving. Revisit if the rule-writing task behaves differently.
- A second model adds little on top of the check: it caught three more doubtful headers and missed the same Apollo
  one.

## Not done

- One run per arm; the run-to-run spread with the same option order is not measured.
- No test of the actual slice R task (a rule per column from a bundle built by the page models).
- The reference labels were not re-checked; some "disagreements" may be the label's error.
