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

## Rerun through the API, to measure cost (owner request, 2026-11-26)

The subagent runs above cannot price a model: their token totals include the tool round trips of reading files.
This rerun sends one request per item (the production shape: one bundle, one call) and reads the tokens billed
from each response. Script `scripts/text/agent_stability/run_api.py`; outputs `scratch/2026-11-26_agent_stability_api/`.
Models `claude-haiku-5-5` and `claude-sonnet-5-5`, both at effort `low`, same prompt, options forward and reversed:
816 requests, no errors, no refusals. Paid from the owner's API credits: about 1.31 USD in all, plus about 0.03 for
a nine-item trial.

Prices used (per million tokens, from the Claude API price list cached 2026-11-03): Haiku 5.5 0.10 input, 0.50
output; Sonnet 5.5 2.00 input, 10.00 output.

| Run | Input tokens | Output tokens | Cost (USD) | Cost per item | Wall time | Agree with label (144) | Headers (50) | Headings (73) | Rates (21) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Haiku forward | 247,424 | 8,097 | 0.029 | 0.00014 | 24 s | 140 | 47 | 73 | 20 |
| Haiku reversed | 247,424 | 8,880 | 0.029 | 0.00014 | 24 s | 132 | 45 | 72 | 15 |
| Sonnet forward | 247,424 | 13,488 | 0.630 | 0.0031 | 44 s | 143 | 49 | 73 | 21 |
| Sonnet reversed | 247,424 | 12,498 | 0.620 | 0.0030 | 46 s | 143 | 49 | 73 | 21 |

Stability on the 144 strong items: Sonnet gave the same answer in both orders on 144 (202 of all 204); Haiku on 134
(187 of 204). Haiku's reversed run returned 3 unusable replies and dropped to 15 of 21 on rate cells.

What it shows:

1. Haiku is about 21 times cheaper per item. Both are cheap in absolute terms: the whole first pass for the five
   funds is on the order of 1,500 units (about 66 header formats, about 1,100 distinct heading texts, a few dozen
   rate shapes), so roughly 5 USD on Sonnet or 0.25 USD on Haiku. After that, only new or changed units each quarter.
2. Sonnet is more accurate (143 against 132 to 140) and stable under option order (144 of 144 against 134).
3. "Haiku twice, accept where both orders agree" accepts 134 of 144, 132 of them agreeing with the label, for 0.06
   USD. "Sonnet once" gives 143 for 0.63 USD. Money does not decide this; the errors do. A wrong rule is wrong on
   every row it reads, and each item sent to the owner costs the owner's time.
4. The one item every run gets "wrong" is the same as before: Apollo's "Interest Rate" header over "S+525, 0.00%
   Floor" cells. It needs the check on the cells, not a better model.

Recommendation: Sonnet, run twice with the options reversed, plus the check. Haiku is not worth the saving at this
volume. Revisit if the volume grows by orders of magnitude (it would not at 61 funds: about 60 USD on Sonnet, once).

Limits: both at effort `low`, one prompt; not tuned for either model. The subagent runs above used default
settings and a different shape (one agent reading all items), so the two tables are not the same test.
