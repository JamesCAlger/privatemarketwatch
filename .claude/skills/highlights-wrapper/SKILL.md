---
description: Create or validate a fund highlights wrapper JSON for a CIK
argument-hint: [CIK|next] [profile|create|validate]
allowed-tools: Bash Read Write Edit Grep Glob
---

# Fund Highlights Wrapper Skill

Build, validate, or update per-CIK wrapper JSON files that control how the pipeline maps XBRL concepts to fund-level highlights fields and recognizes share class members.

**Usage:** `/highlights-wrapper [CIK|next] [mode]`

Modes: `profile` (default), `create`, `validate`

If the user does not specify a CIK, choose the next unprocessed CIK from the worklist.

---

## Architecture Context

A **highlights wrapper** is a deterministic JSON config that fixes per-CIK concept-to-field mapping gaps and share class recognition failures. The two-speed split:

- **Hot path (extraction):** deterministic concept overrides + share class aliases. No LLM.
- **Cold path (authoring):** agent profiles XBRL concepts, authors wrapper, validates with oracle.

Wrappers live at `data/overrides/fund_highlights_wrappers/{CIK}.json` and conform to `schemas/fund_highlights_wrapper/wrapper_v1.schema.json`.

### Success contract

- Schema validation passes (correct JSON structure)
- Trial rebuild shows improved or unchanged identity pass rates
- No new oracle failures introduced
- Notes document why the wrapper exists and what evidence supports it

---

## Priority Queue

```bash
python scripts/fund_highlights_wrapper_worklist.py --next
python scripts/fund_highlights_wrapper_worklist.py --list
python scripts/fund_highlights_wrapper_worklist.py --stats
```

---

## Mode Dispatch

Read the mode-specific doc for detailed instructions:

- **profile** (default): Read and follow `docs/highlights_wrapper/HIGHLIGHTS_WRAPPER_PROFILE.md`
- **create**: Read profile doc first, then `docs/highlights_wrapper/HIGHLIGHTS_WRAPPER_CREATE.md`
- **validate**: Read and follow `docs/highlights_wrapper/HIGHLIGHTS_WRAPPER_VALIDATE.md`

---

## Guardrails

- **Do not author a wrapper without profiling first.** Understand what's failing before writing overrides.
- **concept_overrides are substring matches.** Be specific to avoid unintended matches.
- **Override order matters.** First match wins -- put more specific substrings before general ones.
- **oracle_tolerances are capped at 20%.** Tolerances above this indicate a data problem, not a rounding issue.
- **Run the trial rebuild to verify.** Visual plausibility is not evidence.
- **Do not hide failed oracle status.** Residual issues are valid outcomes.
