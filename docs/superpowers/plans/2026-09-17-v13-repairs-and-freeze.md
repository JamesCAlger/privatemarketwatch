# V13 Repairs and Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the three V12 implementation defects (BCRED scope recognition, bidirectional slot exclusion in tiers B2-leftover/C/D/F, Tier E second-best pairing), add the pre-freeze footprint gate that would have caught them, then freeze, build and evaluate V13 with the never-run checks pulled forward.

**Architecture:** All repairs are global deterministic rules (Layer 1) with focused tests and one shared footprint script that compares two sealed identity bundles. No per-CIK override, no threshold change, no production output change. Candidates stay immutable: V12 and V11b are never edited; V13 is a fresh isolated build from the V12 base with current code.

**Tech Stack:** Python 3.13, DuckDB SQL (RE2 regex, no lookarounds), pandas for fixtures only, pytest, PowerShell 5.1 controllers under `scratch/`.

**Spec:** `scratch/2026-09-17_v12_review/v12_identity_regression_review_v1.md` (root causes, blast radius, required repairs). Policy: `docs/production_stack/01_decisions.md` D08 (retain with explicit scope, never infer ownership) and the 2026-09-14 owner ruling (no unexplained refactor regressions; explained intentional changes are recordable).

## Global Constraints

- No SEC network calls. All builds use cached inputs.
- No writes under `data/output/` or `frontend/public/data/` (pytest guard). Candidate builds write only under `data/programme/candidates/<name>/`.
- No ad-hoc inline Python. Diagnostics go in named files under `scratch/2026-09-17_v13_repairs/` with row limits and timeouts.
- No overlapping heavy jobs. Check `Get-Process python*` and `data/programme/heavy.*.json` before any build, twin or full suite.
- DuckDB regex is RE2: no lookahead, no lookbehind, no backreferences. Express guards as separate `AND NOT regexp_matches(...)` predicates.
- Log messages ASCII only.
- Every task that changes pipeline behaviour appends a dated entry to `docs/agent_changelog.md`. Never edit `AGENTS.md`.
- Commit after each task. Subject line plus 2-4 bullets. Trailer:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01QunrbrHVehZySx4sYr6fqW`.
- Immutable: `data/programme/candidates/production-20260915-v11b/`, `production-20260916-v12/`. Read only.
- Joint-borrower rule (`pipeline/joint_borrowers.py`) is KEPT. Do not widen `compatible_names`.

---

### Task 0: Pull forward the never-run public checks on V12 (parallel, operator step)

The public build and browser census have never run on a real candidate. Run them on V12 now, while Tasks 1-5 proceed, so any machinery failure is fixed inside the V13 freeze instead of costing a V14. This is node/browser work, not a heavy Python job, so it may overlap with focused pytest runs. It must NOT overlap with the full suite (Task 6) or a build.

**Files:**
- Run: `scratch/2026-09-12_programme_e0/verify_architecture_v12_public.ps1`
- Evidence: `scratch/2026-09-12_programme_e0/architecture-v12-public-sequence-v1/`

- [ ] **Step 1: Confirm no heavy job**

Run (PowerShell):
```powershell
Get-Process python*,node* -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime
Get-ChildItem "data\programme\heavy.*.json" | Select-Object Name
```
Expected: no python process; only `heavy.stale-*.json` markers.

- [ ] **Step 2: Launch detached**

```powershell
$s="C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl\scratch\2026-09-12_programme_e0"
Start-Process powershell.exe -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File","`"$s\verify_architecture_v12_public.ps1`"") -WorkingDirectory "C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl" -RedirectStandardOutput "$s\verify_architecture_v12_public-controller-v1.log" -RedirectStandardError "$s\verify_architecture_v12_public-controller-v1.err.log" -WindowStyle Hidden
```
Note: the `-File` path MUST be quoted; the path contains spaces (this bit the V12 launch).

- [ ] **Step 3: Record the result in the changelog when it finishes**

Read `architecture-v12-public-sequence-v1/result.json`. Append to `docs/agent_changelog.md` a dated entry: status, census counts, browser p95, and every failure verbatim. A failure here is a Task 6 prerequisite: fix it in the working tree with its own test before the V13 freeze. Do not proceed to Task 7 with an unexplained public-check failure.

---

### Task 1: Candidate footprint gate

A read-only script that compares two sealed identity bundles on cheap cohort-wide counts and fails on a large ratio change or on any JV-labelled row left in parent scope. This is the pre-freeze check that catches "Tier E grew tenfold" in thirty seconds.

**Files:**
- Create: `scripts/candidate_footprint.py`
- Test: `tests/test_candidate_footprint.py`

**Interfaces:**
- Produces: `compute_footprint(bundle: Path, encodings: dict | None = None) -> dict` and `compare_footprints(current: dict, prior: dict, max_ratio: float = 2.0) -> list[dict]` (each flag: `{metric, prior, current, ratio, reason}`), and a CLI `python scripts/candidate_footprint.py --candidate NAME --prior NAME [--attempt identity-01] [--prior-attempt identity-01] --out PATH.json [--max-ratio 2.0] [--report-only]`. Exit code 1 when flags exist and `--report-only` is absent. Task 7 calls the CLI after the identity stage.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_candidate_footprint.py
"""Footprint gate: cohort-wide counts between two sealed identity bundles."""
from pathlib import Path
import duckdb
import pandas as pd
import pytest

from scripts.candidate_footprint import compute_footprint, compare_footprints

ENC = {'0001803498': {'reporting_entity_suffixes': ['Emerald JV LP'],
                      'reporting_entity_identifier_suffixes': ['Emerald JV LP']}}


def _bundle(tmp_path, name, e_pairs, labelled_parent=0):
    b = tmp_path / name / 'bundle'
    b.mkdir(parents=True)
    with duckdb.connect() as con:
        holdings = pd.DataFrame([
            dict(row_id=f'R{i}', cik='0001803498', issuer_name='Acme LLC', fair_value=100.0,
                 accounting_record_class='parent_schedule', position_id=f'P{i}', entity_id='E1')
            for i in range(10)] + [
            dict(row_id=f'L{i}', cik='0001803498', issuer_name='Beta Co., Emerald JV LP', fair_value=5.0,
                 accounting_record_class='parent_schedule', position_id=f'L{i}', entity_id='E2')
            for i in range(labelled_parent)])
        matches = pd.DataFrame([dict(match_method='E_entity_fingerprint', begin_fair_value=100.0, end_fair_value=100.0)] * e_pairs
                               + [dict(match_method='B1b_position_key', begin_fair_value=100.0, end_fair_value=100.0)] * 100)
        edges = pd.DataFrame([dict(edge_type='match_pair')] * (e_pairs + 100))
        lookup = pd.DataFrame([dict(entity_id='E1', normalized_name='acme'), dict(entity_id='E2', normalized_name='joint:beta co and gamma')])
        for frame, fname in ((holdings, 'private_markets_holdings'), (matches, 'position_matches'),
                             (edges, 'position_id_edges'), (lookup, 'entity_lookup')):
            con.register('f', frame)
            con.execute(f"COPY f TO '{(b / (fname + '.parquet')).as_posix()}' (FORMAT PARQUET)")
            con.unregister('f')
    return b


def test_equal_bundles_raise_no_flags(tmp_path):
    a = compute_footprint(_bundle(tmp_path, 'a', 10), ENC)
    b = compute_footprint(_bundle(tmp_path, 'b', 10), ENC)
    assert compare_footprints(b, a) == []


def test_tenfold_tier_growth_is_flagged(tmp_path):
    prior = compute_footprint(_bundle(tmp_path, 'prior', 100), ENC)
    current = compute_footprint(_bundle(tmp_path, 'current', 1000), ENC)
    flags = compare_footprints(current, prior)
    assert [f['metric'] for f in flags] == ['match_method.E_entity_fingerprint']
    assert flags[0]['ratio'] == pytest.approx(10.0)


def test_small_populations_are_not_flagged_on_ratio(tmp_path):
    prior = compute_footprint(_bundle(tmp_path, 'prior', 3), ENC)
    current = compute_footprint(_bundle(tmp_path, 'current', 30), ENC)
    assert compare_footprints(current, prior) == []


def test_labelled_row_in_parent_scope_is_always_flagged(tmp_path):
    prior = compute_footprint(_bundle(tmp_path, 'prior', 10), ENC)
    current = compute_footprint(_bundle(tmp_path, 'current', 10, labelled_parent=2), ENC)
    flags = compare_footprints(current, prior)
    assert flags == [dict(metric='labelled_parent_rows.0001803498', prior=0, current=2, ratio=None,
                          reason='reporting-entity label in parent scope')]


def test_footprint_reports_joint_entities_and_singletons(tmp_path):
    fp = compute_footprint(_bundle(tmp_path, 'a', 10), ENC)
    assert fp['joint_entities'] == 1
    assert fp['positions'] == 10 and fp['singletons'] == 10
    assert fp['scope_rows']['parent_schedule'] == 10
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_candidate_footprint.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.candidate_footprint'`.

- [ ] **Step 3: Implement the script**

```python
# scripts/candidate_footprint.py
"""Read-only footprint comparison of two sealed identity bundles.

Counts only. A large ratio change on any populated count, or any reporting-entity
label left in parent scope, blocks a freeze until it is explained.
"""
import argparse
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MIN_POPULATION = 100


def _label_regex(label):
    # RE2: no lookaround. Label as a comma-separated leading or trailing segment,
    # optionally followed by an ordinal. Parent LP interests start with the fund prefix.
    lab = ' '.join(label.lower().split()).replace('.', '\\.')
    return '(^|, )' + lab + '(,| [0-9]+$|$)'


def compute_footprint(bundle, encodings=None):
    bundle = Path(bundle)
    if encodings is None:
        from pipeline.source_encodings import load_encodings
        encodings = load_encodings()
    out = {}
    with duckdb.connect(config={'threads': 2}) as con:
        h = str(bundle / 'private_markets_holdings.parquet')
        m = str(bundle / 'position_matches.parquet')
        e = str(bundle / 'position_id_edges.parquet')
        l = str(bundle / 'entity_lookup.parquet')
        out['match_method'] = dict(con.execute(
            "SELECT match_method, count(*) FROM read_parquet(?) GROUP BY 1", [m]).fetchall())
        out['edge_type'] = dict(con.execute(
            "SELECT edge_type, count(*) FROM read_parquet(?) GROUP BY 1", [e]).fetchall())
        out['e_fv_outliers'] = con.execute("""SELECT count(*) FILTER (WHERE begin_fair_value > 0 AND end_fair_value > 0
            AND (end_fair_value / begin_fair_value < 0.5 OR end_fair_value / begin_fair_value > 2))
            FROM read_parquet(?) WHERE match_method LIKE 'E_%'""", [m]).fetchone()[0]
        positions, singletons = con.execute("""WITH c AS (SELECT position_id, count(*) n FROM read_parquet(?)
            WHERE position_id IS NOT NULL GROUP BY 1) SELECT count(*), count(*) FILTER (WHERE n = 1) FROM c""", [h]).fetchone()
        out['positions'], out['singletons'] = positions, singletons
        out['scope_rows'] = dict(con.execute(
            "SELECT accounting_record_class, count(*) FROM read_parquet(?) GROUP BY 1", [h]).fetchall())
        out['scope_fv'] = {k: float(v) for k, v in con.execute(
            "SELECT accounting_record_class, coalesce(sum(fair_value), 0) FROM read_parquet(?) GROUP BY 1", [h]).fetchall()}
        out['joint_entities'] = con.execute(
            "SELECT count(DISTINCT entity_id) FROM read_parquet(?) WHERE normalized_name LIKE 'joint:%'", [l]).fetchone()[0]
        labelled = {}
        for cik, enc in sorted(encodings.items()):
            labels = list(enc.get('reporting_entity_suffixes', [])) + list(enc.get('reporting_entity_identifier_suffixes', []))
            if not labels:
                continue
            pattern = '|'.join('(' + _label_regex(x) + ')' for x in sorted(set(labels)))
            labelled[cik] = con.execute("""SELECT count(*) FROM read_parquet(?)
                WHERE cik = ? AND accounting_record_class = 'parent_schedule'
                AND regexp_matches(lower(trim(issuer_name)), ?)
                AND NOT regexp_matches(lower(trim(issuer_name)), '^[a-z]+ (emerald|verdelite) jv lp$')""",
                [h, cik, pattern]).fetchone()[0]
        out['labelled_parent_rows'] = labelled
    return out


def _flat(fp):
    flat = {}
    for group in ('match_method', 'edge_type', 'scope_rows'):
        for k, v in fp.get(group, {}).items():
            flat[group + '.' + k] = v
    for k in ('positions', 'singletons', 'joint_entities', 'e_fv_outliers'):
        flat[k] = fp.get(k, 0)
    return flat


def compare_footprints(current, prior, max_ratio=2.0):
    flags = []
    cur, pri = _flat(current), _flat(prior)
    for metric in sorted(set(cur) | set(pri)):
        c, p = cur.get(metric, 0), pri.get(metric, 0)
        if max(c, p) < MIN_POPULATION:
            continue
        ratio = (c / p) if p else float('inf')
        if ratio > max_ratio or ratio < 1 / max_ratio:
            flags.append(dict(metric=metric, prior=p, current=c, ratio=ratio, reason='count ratio outside band'))
    for cik, n in sorted(current.get('labelled_parent_rows', {}).items()):
        if n:
            flags.append(dict(metric='labelled_parent_rows.' + cik, prior=prior.get('labelled_parent_rows', {}).get(cik, 0),
                              current=n, ratio=None, reason='reporting-entity label in parent scope'))
    return flags


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--prior', required=True)
    parser.add_argument('--attempt', default='identity-01')
    parser.add_argument('--prior-attempt', default='identity-01')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--max-ratio', type=float, default=2.0)
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    from pipeline.programme.runner import candidate_path
    current = compute_footprint(candidate_path(args.candidate) / 'attempts' / args.attempt / 'bundle')
    prior = compute_footprint(candidate_path(args.prior) / 'attempts' / args.prior_attempt / 'bundle')
    flags = compare_footprints(current, prior, args.max_ratio)
    result = dict(candidate=args.candidate, prior=args.prior, current=current, prior_footprint=prior,
                  flags=flags, status='PASS' if not flags else 'FLAGGED')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    print(result['status'], len(flags), 'flags')
    for f in flags:
        print('  ', f['metric'], f['prior'], '->', f['current'], f['reason'])
    if flags and not args.report_only:
        sys.exit(1)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_candidate_footprint.py -q`
Expected: 5 passed.

- [ ] **Step 5: Run it on V12 vs V11b and keep the report**

Run: `python scripts/candidate_footprint.py --candidate production-20260916-v12 --prior production-20260915-v11b --out scratch/2026-09-17_v13_repairs/footprint-v12-vs-v11b.json --report-only`
Expected output includes `match_method.E_entity_fingerprint 5329 -> 54435` and `labelled_parent_rows.0001803498 ... -> 791` (exact V12 numbers may differ by a few rows depending on regex; record what it prints).

- [ ] **Step 6: Changelog and commit**

Append to `docs/agent_changelog.md` a dated entry "Candidate footprint gate added" with the V12-vs-V11b flags it reports.

```bash
git add scripts/candidate_footprint.py tests/test_candidate_footprint.py docs/agent_changelog.md
git commit -m "Add candidate footprint gate for pre-freeze checks" -m "- Compares two sealed identity bundles on tier, edge, scope, singleton and joint-entity counts" -m "- Flags any populated count moving more than 2x and any reporting-entity label left in parent scope" -m "- Reports the V12 Tier E growth and BCRED parent-scope residue that the review found by hand" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01QunrbrHVehZySx4sYr6fqW"
```

---

### Task 2: BCRED reporting-portfolio recognition covers every reviewed form

Replace the legal-suffix requirement in the legacy identifier rule with a separator rule: the label is a comma-separated terminal segment, a space-ordinal-space terminal segment, or a comma-separated leading segment. Guards stay explicit: the fund's own LP interest (`bcred ...`) and joint "and" forms remain parent.

**Files:**
- Modify: `pipeline/source_encodings.py:78-88` (legacy branch of `reporting_suffix_expression`)
- Modify: `data/overrides/bdc_xbrl_wrappers/0001803498.json` (description of quirk `bcred_legacy_typed_reporting_portfolio`, evidence contexts)
- Test: `tests/test_source_encodings.py`

**Interfaces:**
- `reporting_suffix_expression(cik, dimensions, encodings=None) -> str` unchanged signature. Output unchanged: `'reporting_entity=<label>'` members joined with `|`.

- [ ] **Step 1: Add the failing parametrize cases**

In `tests/test_source_encodings.py`, extend the list of `test_reporting_suffix_does_not_turn_borrower_names_into_subsidiaries` with these cases (append after the existing `('investmentidentifieraxis=Acme IncEmerald JV LP', 'parent')`):

```python
    # Reviewed 2026-09-17 (V12 review): prefix form, unlisted legal suffixes, ordinal-space form.
    ('investmentidentifieraxis=Emerald JV LP, 2U, Inc.', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Freeport LNG Investments, LLLP, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=AlixPartners, LLP, Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=Monk Holding Co., Emerald JV LP 1', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Auris Luxembourg III S.a r.l., Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Tangerine Bidco S.p.A, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Confine Visual Bidco, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=Symphony Technology Group 1 Verdelite JV LP', 'reporting_entity=verdelite jv lp'),
    ('investmentidentifieraxis=Air Canada, Emerald JV LP', 'reporting_entity=emerald jv lp'),
    ('investmentidentifieraxis=TRC Companies, Inc (fka Bolt Infrastructure Merger Sub, Inc.), Emerald JV LP', 'reporting_entity=emerald jv lp'),
    # Still parent: bare label, fund's own interest, joint "and", label inside a longer name.
    ('investmentidentifieraxis=Emerald JV LP', 'parent'),
    ('investmentidentifieraxis=BCRED Verdelite JV LP 2', 'parent'),
    ('investmentidentifieraxis=Emerald JV LP, and Acme LLC', 'parent'),
    ('investmentidentifieraxis=Acme LLC and Emerald JV LP 1', 'parent'),
    ('investmentidentifieraxis=Emerald JV LP Holdings, Acme LLC', 'parent'),
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_source_encodings.py -q -k reporting_suffix`
Expected: the ten positive cases FAIL (actual `0001803498|parent`); the negatives pass.

- [ ] **Step 3: Replace the legacy branch**

In `pipeline/source_encodings.py`, replace lines 78-87 (the `if legacy:` block) with:

```python
        if legacy:
            # Reviewed legacy InvestmentIdentifierAxis forms (BCRED wrapper quirk
            # bcred_legacy_typed_reporting_portfolio): the portfolio label is its
            # own segment, separated from a non-empty borrower by a comma or by a
            # space-ordinal-space, at the end or (2023-03-31 only) at the start.
            # RE2 has no lookaround, so the fund's own LP interest and joint "and"
            # forms are excluded by separate predicates. Borrower legal-form words
            # are NOT required: LLLP, LLP, Co., S.a r.l., S.p.A, bare Bidco and
            # plain names all appear in reviewed contexts.
            member=_normal("split_part(CAST("+dimensions+" AS VARCHAR),'|',1)")
            for label in legacy:
                label=' '.join(label.lower().split())
                lab=re.escape(label)
                terminal=r'^investmentidentifieraxis=.+?(?:,\s*|,?\s+[0-9]+\s+)'+lab+r'(?: [0-9]+)?$'
                leading=r'^investmentidentifieraxis='+lab+r',\s*.+$'
                own_interest=r'^investmentidentifieraxis=[a-z]+ '+lab+r'(?: [0-9]+)?$'
                joint=r'(?:^investmentidentifieraxis='+lab+r',\s*and\b)|(?:\band,?\s+'+lab+r'(?: [0-9]+)?$)'
                matched.append('CASE WHEN (regexp_matches('+member+','+_literal(terminal)+') OR regexp_matches('+member+','+_literal(leading)+'))'
                    ' AND NOT regexp_matches('+member+','+_literal(own_interest)+')'
                    ' AND NOT regexp_matches('+member+','+_literal(joint)+')'
                    ' THEN ['+_literal(label)+'] ELSE []::VARCHAR[] END')
```

Keep the `legal=` line out entirely; it is no longer used.

- [ ] **Step 4: Run the file**

Run: `python -m pytest tests/test_source_encodings.py -q`
Expected: all pass, including the pre-existing `MH Sub I, LLC 1 Verdelite JV LP` and `ADCS Clinics, LLC, Emerald JV LP 3` cases.

- [ ] **Step 5: Record the source evidence in the wrapper**

Edit `data/overrides/bdc_xbrl_wrappers/0001803498.json`, quirk `bcred_legacy_typed_reporting_portfolio`, replace its `description` with:

```
Earlier InvestmentIdentifierAxis members carry the reporting portfolio as its own comma- or ordinal-separated segment, trailing or (2023-03-31) leading. Reviewed contexts: MH Sub I c-4761 in 0001803498-24-000007 and c-4323 in 0001803498-24-000022 (Verdelite JV LP after a legal name); 2U, Inc. ie581ddde7a204a18ab795e21c813585b_I20230331 in 0001803498-23-000012 (leading Emerald JV LP); Freeport LNG Investments, LLLP c-3470, Monk Holding Co. c-3527, Confine Visual Bidco c-3506 and Symphony Technology Group c-3548 in 0001803498-23-000017; AlixPartners, LLP c-4526 in 0001803498-23-000021; Auris Luxembourg III S.a r.l. c-3820 and Tangerine Bidco S.p.A c-3997 in 0001803498-24-000044. Borrower legal-form words are not required. The fund's own BCRED Emerald/Verdelite JV LP interests and joint "and" forms remain parent records. This scope interpretation does not strip the ordinal from the position identifier.
```

Run: `python -m pytest tests/test_bdc_xbrl_wrapper.py -q`
Expected: pass (description is free text under wrapper_v3).

- [ ] **Step 6: Run the scope consumers**

Run: `python -m pytest tests/test_source_encodings.py tests/test_refactor_staging.py tests/test_unified_holdings.py -q -x --durations=10`
Expected: all pass. If a `test_unified_holdings.py` fixture asserts a BCRED row is parent because of the old rule, the fixture is wrong under D08: update it and cite this task in the test comment.

- [ ] **Step 7: Backstop, changelog, commit**

Run: `python scripts/diff_outputs.py --semantic`
Expected: only the known baseline differences (the 2026-09-10 divergence report); zero new material differences. Nothing under `data/output/` was written.

Append to `docs/agent_changelog.md`: forms added, the count expectation (V12 had 791 parent-scoped labelled rows; V13 must show 0 in the footprint), and that this changes BCRED 2023 conservation sums.

```bash
git add pipeline/source_encodings.py tests/test_source_encodings.py data/overrides/bdc_xbrl_wrappers/0001803498.json docs/agent_changelog.md
git commit -m "Recognise every reviewed BCRED reporting-portfolio identifier form" -m "- Label is its own comma- or ordinal-separated segment, trailing or leading; legal-form words no longer required" -m "- Fund LP interests and joint 'and' forms stay parent via explicit RE2 guards" -m "- V12 left 791 rows / USD 10.5B of JV-labelled holdings in parent scope, 513 of them at 2023-03-31" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01QunrbrHVehZySx4sYr6fqW"
```

---

### Task 3: Directional slot availability in tiers B2-leftover, C, D and F

The V12 repair gave tier E independent begin and end slots. Tiers B2-leftover, C, D and F still exclude a row used in EITHER direction by an earlier tier, so a correct new BEGIN claim (Resideo Q3->Q4 via B1b) makes the row's END slot unusable (Q2->Q3 via C/D). Extract one helper and apply it to all four.

**Files:**
- Modify: `pipeline/position_matching.py` (new helper near line 300; `_match_exact_name_leftover_rounds` ~1195; `_match_normalized_name` ~1297; `_match_fuzzy` ~1447; `_match_gap_quarter` ~1876)
- Test: `tests/test_matching_direction.py` (helper test), `tests/test_position_matching.py` (Resideo shape)

**Interfaces:**
- Produces: `_slot_availability_ctes(prior_tiers: tuple[str, ...]) -> str` returning two CTE bodies `used_begin AS (...), used_end AS (...)` where `used_end` always includes `tier_a_unified_ids` and `used_begin` never does. Tier E's inline `used_begin`/`used_end` CTEs (lines 1647-1657) are replaced by a call to the same helper with `('tier_b','tier_c','tier_d')`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching_direction.py`:

```python
from pipeline.position_matching import _slot_availability_ctes


def test_slot_helper_claims_tier_a_on_end_side_only():
    with duckdb.connect() as con:
        con.execute('CREATE TABLE tier_a_unified_ids(_row_id BIGINT)')
        con.execute('INSERT INTO tier_a_unified_ids VALUES (7)')
        con.execute('CREATE TABLE tier_b(_begin_row_id BIGINT,_end_row_id BIGINT)')
        con.execute('INSERT INTO tier_b VALUES (1,2)')
        con.execute('CREATE TABLE tier_c(_begin_row_id BIGINT,_end_row_id BIGINT)')
        con.execute('INSERT INTO tier_c VALUES (3,4)')
        sql = 'WITH ' + _slot_availability_ctes(('tier_b', 'tier_c'))
        begins = {r[0] for r in con.execute(sql + ' SELECT _row_id FROM used_begin').fetchall()}
        ends = {r[0] for r in con.execute(sql + ' SELECT _row_id FROM used_end').fetchall()}
    assert begins == {1, 3}
    assert ends == {2, 4, 7}


def test_slot_helper_with_no_prior_tiers_only_claims_tier_a_ends():
    with duckdb.connect() as con:
        con.execute('CREATE TABLE tier_a_unified_ids(_row_id BIGINT)')
        con.execute('INSERT INTO tier_a_unified_ids VALUES (9)')
        sql = 'WITH ' + _slot_availability_ctes(())
        assert con.execute(sql + ' SELECT count(*) FROM used_begin').fetchone()[0] == 0
        assert con.execute(sql + ' SELECT _row_id FROM used_end').fetchall() == [(9,)]
```

Append to `tests/test_position_matching.py` (uses the module's `_make_unified`, `_make_bdc_raw`, autouse redirect fixture and `match_positions`):

```python
class TestDirectionalSlots:
    def test_begin_claim_by_exact_name_leaves_end_slot_open_for_later_tiers(self):
        """Resideo shape (V12 review): Q3 row is the BEGIN of a B2 pair to Q4 and
        must still be the END of a C/D pair from Q2."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "300", "entity_name": "BDC3", "report_date": "2025-06-30",
             "issuer_name": "Resideo Funding, Inc.", "fair_value": "545000",
             "index_classification": "DIRECT_LENDING", "maturity_date": "2031-06-13"},
            {"source": "bdc", "cik": "300", "entity_name": "BDC3", "report_date": "2025-09-30",
             "issuer_name": "Resideo Funding, Inc. 1", "fair_value": "545000",
             "index_classification": "DIRECT_LENDING", "maturity_date": "2031-06-13"},
            {"source": "bdc", "cik": "300", "entity_name": "BDC3", "report_date": "2025-12-31",
             "issuer_name": "Resideo Funding, Inc. 1", "fair_value": "544000",
             "index_classification": "DIRECT_LENDING", "maturity_date": "2031-06-13"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        spans = set(zip(result["begin_report_date"].astype(str), result["end_report_date"].astype(str)))
        assert ("2025-09-30", "2025-12-31") in spans
        assert ("2025-06-30", "2025-09-30") in spans
        later = result[(result["begin_report_date"].astype(str) == "2025-06-30")]
        assert later["match_method"].iloc[0] in ("C_normalized_name", "D_fuzzy")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_matching_direction.py tests/test_position_matching.py::TestDirectionalSlots -q`
Expected: helper tests FAIL with ImportError; the Resideo test FAILS on the second assertion (no Q2->Q3 pair).

- [ ] **Step 3: Add the helper**

In `pipeline/position_matching.py`, directly above `def _maturity_gap_sql` (line 304), add:

```python
def _slot_availability_ctes(prior_tiers: tuple[str, ...]) -> str:
    """CTE text ``used_begin AS (...), used_end AS (...)`` for cascade exclusion.

    A row has independent incoming (end) and outgoing (begin) continuity
    slots. A tier may claim a row's END slot without removing its BEGIN slot
    and vice versa. Tier A contributes only its mapped current-period END
    slot (see ``_map_tier_a_end_side_ids``). Introduced for Tier E in the
    V12 repair; extended to B2-leftover, C, D and F after the Resideo review
    (docs/investigations/position_matching.md, 2026-09-17).
    """
    begins = " UNION ".join(f"SELECT _begin_row_id AS _row_id FROM {t}" for t in prior_tiers)
    ends = " UNION ".join(["SELECT _row_id FROM tier_a_unified_ids"] +
                          [f"SELECT _end_row_id AS _row_id FROM {t}" for t in prior_tiers])
    if not begins:
        begins = "SELECT CAST(NULL AS BIGINT) AS _row_id WHERE FALSE"
    return f"used_begin AS ({begins}), used_end AS ({ends})"
```

- [ ] **Step 4: Apply to tier C**

In `_match_normalized_name` replace the CTE block from `all_used AS (` through the `remaining AS (...)` and `norm_name_counts` CTEs with:

```sql
    {_slot_availability_ctes(('tier_b',))},
    remaining AS (
        SELECT u.*,
            {norm_sql} AS _norm_name,
            u._row_id NOT IN (SELECT _row_id FROM used_begin) AS _begin_available,
            u._row_id NOT IN (SELECT _row_id FROM used_end) AS _end_available
        FROM unified_base u
    ),
    -- Normalized-name multiplicity cap, counted per direction
    norm_name_counts AS (
        SELECT cik, quarter, _norm_name,
            COUNT(*) FILTER (WHERE _begin_available) AS n_begin,
            COUNT(*) FILTER (WHERE _end_available) AS n_end
        FROM remaining
        WHERE _norm_name IS NOT NULL AND _norm_name != ''
        GROUP BY cik, quarter, _norm_name
    ),
```

Then, in the same function, every later reference: the pair join gets `AND b._begin_available AND e._end_available`; every predicate on `norm_name_counts` (or its derived `high_mult` CTE) that is joined to the begin alias uses `n_begin`, and to the end alias uses `n_end`, in place of `n`. Locate them with `grep -n "\.n \|\.n<\|\.n>\|n <= \|n > " pipeline/position_matching.py` inside lines 1282-1435. Tier E (lines 1660-1780) is the worked example of the same edit.

- [ ] **Step 5: Apply to tier D**

In `_match_fuzzy` replace `all_used AS (...)`, `remaining AS (...)` and `d_norm_counts` exactly as in Step 4 but with `_slot_availability_ctes(('tier_b','tier_c'))`; `d_norm_counts` gains `n_begin`/`n_end`; the `d_high_mult_norm` CTE and the pair join follow the same alias rule; add `AND b._begin_available AND e._end_available` to the pair join.

- [ ] **Step 6: Apply to B2-leftover and F**

In `_match_exact_name_leftover_rounds`, replace `used AS (...)` with `{_slot_availability_ctes(('tier_b',))}` and `remaining` with the flagged form; `name_counts` becomes `n_begin`/`n_end` per direction; join gets the two availability predicates. In `_match_gap_quarter`, replace `all_used AS (...)` with `{_slot_availability_ctes(('tier_b','tier_c','tier_d','tier_e'))}` and the same flagged `remaining`; join gets the two predicates.

- [ ] **Step 7: Route tier E through the helper**

In `_match_entity_fingerprint` replace the inline `used_begin AS (...), used_end AS (...)` (lines 1647-1657) with `{_slot_availability_ctes(('tier_b','tier_c','tier_d'))},`. Behaviour unchanged; one definition.

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_matching_direction.py tests/test_position_matching.py -q --durations=10`
Expected: all pass, including every pre-existing tier B/C/D test. If a pre-existing test now finds an ADDITIONAL pair, read it: a test that asserted "no pair" because the row was consumed in the wrong direction is asserting the defect. Update the expectation and say so in the test docstring. A test that asserted a specific WRONG pair is a real regression: stop and report.

- [ ] **Step 9: Changelog and commit**

```bash
git add pipeline/position_matching.py tests/test_matching_direction.py tests/test_position_matching.py docs/agent_changelog.md
git commit -m "Give tiers B2-leftover, C, D and F independent begin and end slots" -m "- One helper builds used_begin/used_end; tier A claims only its current-period end slot" -m "- A correct new BEGIN claim no longer blocks the same row's END link (Resideo Q2->Q3 after Q3->Q4)" -m "- Tier E now uses the same helper; behaviour unchanged there" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01QunrbrHVehZySx4sYr6fqW"
```

---

### Task 4: Tier E never settles for second best

Tier E generated the Metropolis pair (480K/17.50%/2034 -> 362K/12.00%/no maturity) because the correct sibling (480K, same maturity) was end-unavailable and E counted "single position" on what was left. Fix: classify single/multi on the FILED population, rank each begin against ALL filed same-entity candidates, and emit a pair only when the best candidate on both sides is also available. If the best is taken, emit nothing and leave the row to supplementary contested assignment, which is what V11b did correctly.

**Files:**
- Modify: `pipeline/position_matching.py:1645-1845` (`_match_entity_fingerprint` candidates and dedup)
- Test: `tests/test_matching_direction.py`

**Interfaces:**
- `_match_entity_fingerprint(con) -> "tier_e"` unchanged. `tier_e_candidates` gains columns `_begin_available BOOLEAN`, `_end_available BOOLEAN`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matching_direction.py`:

```python
def run_tier_e_rows(rows, claims=(), tier_a=()):
    """rows: (uid, quarter, date, fv, maturity_or_None). One entity, PREFERRED_EQUITY, no principal."""
    with duckdb.connect(config={'threads': 1, 'memory_limit': '256MB'}) as con:
        con.execute('''CREATE TABLE unified_base(_row_id BIGINT, cik VARCHAR,
            source VARCHAR,entity_name VARCHAR,issuer_name VARCHAR,quarter VARCHAR,
            report_date DATE,entity_id VARCHAR,index_classification VARCHAR,
            _accounting_scope VARCHAR,_inst_subtype VARCHAR,_mat_low DATE,_mat_high DATE,
            fv DOUBLE,pa DOUBLE,cost_val DOUBLE,ir DOUBLE,bs DOUBLE,sh DOUBLE)''')
        con.executemany('INSERT INTO unified_base VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', [
            (uid, '100', 'bdc', 'Fund', 'Metropolis Technologies, Inc.', q, d, 'entity-1',
             'PREFERRED_EQUITY', '100|parent', 'PREFERRED', mat, mat, fv, None, fv, None, None, None)
            for uid, q, d, fv, mat in rows])
        for table in ('tier_b', 'tier_c', 'tier_d'):
            con.execute('CREATE TABLE ' + table + '(_begin_row_id BIGINT,_end_row_id BIGINT)')
        if claims:
            con.executemany('INSERT INTO tier_b VALUES (?,?)', claims)
        con.execute('CREATE TABLE tier_a_unified_ids(_row_id BIGINT)')
        if tier_a:
            con.executemany('INSERT INTO tier_a_unified_ids VALUES (?)', [(i,) for i in tier_a])
        _match_entity_fingerprint(con)
        return set(con.execute('SELECT _begin_row_id,_end_row_id FROM tier_e').fetchall())


METROPOLIS = [(1, '2025q3', '2025-09-30', 480000.0, '2034-05-16'),
              (2, '2025q4', '2025-12-31', 480000.0, '2034-05-16'),
              (3, '2025q4', '2025-12-31', 362000.0, None)]


def test_tier_e_pairs_the_best_filed_candidate_when_it_is_free():
    assert run_tier_e_rows(METROPOLIS) == {(1, 2)}


@pytest.mark.parametrize('taken', [dict(tier_a=(2,)), dict(claims=[(0, 2)])])
def test_tier_e_emits_nothing_when_the_best_filed_candidate_is_taken(taken):
    # V12 paired 1->3 (17.50%/2034 pref with a 12.00%/no-maturity pref) because
    # the true sibling 2 was end-unavailable. Second best is not a match.
    assert run_tier_e_rows(METROPOLIS, **taken) == set()


def test_tier_e_symmetric_best_on_the_begin_side():
    rows = [(1, '2025q3', '2025-09-30', 480000.0, '2034-05-16'),
            (4, '2025q3', '2025-09-30', 362000.0, None),
            (2, '2025q4', '2025-12-31', 480000.0, '2034-05-16')]
    # Begin 1 is the best begin for end 2; if 1's begin slot is taken, 4 must not inherit 2.
    assert run_tier_e_rows(rows, claims=[(1, 0)]) == set()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_matching_direction.py -q`
Expected: `test_tier_e_emits_nothing_when_the_best_filed_candidate_is_taken` FAILS with `{(1, 3)}`; symmetric test FAILS with `{(4, 2)}`; the others pass.

- [ ] **Step 3: Change candidate generation**

In `_match_entity_fingerprint`:

1. `entity_counts`: count the FILED population, not availability:
```sql
    entity_counts AS (
        SELECT cik, source, quarter, _entity_id, _accounting_scope,
            CAST(index_classification AS VARCHAR) AS _ic,
            COUNT(*) AS n
        FROM remaining
        GROUP BY cik, source, quarter, _entity_id, _accounting_scope,
            CAST(index_classification AS VARCHAR)
    ),
```
and change `bc.n_begin = 1` / `ec.n_end = 1` back to `bc.n = 1` / `ec.n = 1` in `pairs_single`, and `bc.n_begin > 1 OR ec.n_end > 1` back to `bc.n > 1 OR ec.n > 1` in `pairs_multi`.

2. In BOTH `pairs_single` and `pairs_multi` remove `AND b._begin_available AND e._end_available` from the join and instead add to the SELECT list:
```sql
            b._begin_available AS _begin_available,
            e._end_available AS _end_available,
```

3. Update the docstring comment block above `sql_candidates` to:
```python
    # Independent begin/end slots (see _slot_availability_ctes). Single/multi
    # classification uses the FILED population so a claimed sibling still
    # counts. Candidates are ranked against every filed same-entity row, and a
    # pair is emitted only if each side is the other's best AND both slots are
    # free. If the best is taken, nothing is emitted: second best is not a
    # match (Metropolis, V12 review 2026-09-17).
```

- [ ] **Step 4: Change the dedup**

Replace the final SELECT of `sql_dedup` so availability is applied AFTER ranking:

```sql
    SELECT cik, entity_name, source,
        begin_quarter, begin_report_date, begin_issuer_name,
        begin_fair_value, begin_cost, begin_principal_amount,
        begin_interest_rate, begin_basis_spread, begin_shares_held,
        end_quarter, end_report_date, end_issuer_name,
        end_fair_value, end_cost, end_principal_amount,
        end_interest_rate, end_basis_spread, end_shares_held,
        match_method, match_key, match_score, span_months,
        _begin_row_id, _end_row_id
    FROM rn_end WHERE rn_e = 1 AND _begin_available AND _end_available
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_matching_direction.py tests/test_position_matching.py -q`
Expected: all pass. The five pre-existing `test_incoming_and_outgoing_continuity_are_independent_slots` cases must still pass unchanged (walk them: with one row per quarter, filed count is 1, ranking is trivial, availability filter reproduces the same sets).

- [ ] **Step 6: Changelog and commit**

```bash
git add pipeline/position_matching.py tests/test_matching_direction.py docs/agent_changelog.md
git commit -m "Tier E ranks against filed candidates and never settles for second best" -m "- Single/multi classification counts the filed population, not what earlier tiers left" -m "- A pair is emitted only when each side is the other's best and both slots are free" -m "- V12 paired Metropolis 480K/17.5%/2034 with 362K/12%/null because the true sibling was taken" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01QunrbrHVehZySx4sYr6fqW"
```

---

### Task 5: Record the joint-borrower decision and the two gold disagreements

**Files:**
- Modify: `docs/production_stack/01_decisions.md` (section 3, owner rulings; append one paragraph, do not touch D01-D13 bytes)
- Modify: `docs/investigations/position_matching.md` (append)

- [ ] **Step 1: Append the decision paragraph**

Append to section 3 of `docs/production_stack/01_decisions.md`:

```
**Joint-borrower identity is precision over recall (2026-09-17).** A source-disclosed co-borrower list ("A, B and C") is its own entity key and never fuzzy-merges with a single member or with another co-borrower list. This removed 10 of 14 entity false merges in the mg3 gold set at the cost of two disagreements retained as open gold packets: IRI Holdings -> Circana rename (MGP-5625e98fbdb8, same instrument by units and cost) and Truck-Lite single vs co-borrower cluster with a "Clarity"/"Clarience" typo variant (MGP-3fb3d33c5cb2). Recovery of these is later operational work (position-level exact shares+cost continuation; typo-tolerant merge between two joint keys sharing the first legal member), not a refactor gate.
```

- [ ] **Step 2: Append the investigation note and reindex**

Append to `docs/investigations/position_matching.md` a dated heading "2026-09-17 - Joint-borrower rule recorded as intentional" with the same two packet ids and the counts (647 joint entities, 14,634 rows, USD 231.75B). Run `python scripts/split_investigations.py --reindex`.

- [ ] **Step 3: Commit**

```bash
git add docs/production_stack/01_decisions.md docs/investigations/position_matching.md docs/investigations/INDEX.md
git commit -m "Record joint-borrower rule as intentional precision-over-recall" -m "- Two mg3 gold disagreements retained by packet id as later operational work" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01QunrbrHVehZySx4sYr6fqW"
```

---

### Task 6: Prebuild verification and V13 source seal

Position matching and accounting scope are shared contracts, so the full suite is required before the freeze. Reuse the V12 controllers with new evidence names so V12 evidence is never overwritten.

**Files:**
- Create: `scratch/2026-09-12_programme_e0/verify_refactor_prebuild_tests_v3.ps1` (copy of `_v2.ps1`)
- Create: `scratch/2026-09-16_refactor_continuation/seal_v13_source.py` (copy of `seal_v12_source.py`)
- Create: `scratch/2026-09-16_refactor_continuation/v13-reviewed-overlay-v1.json` via `prepare_v12_snapshot_review.py` (or its v13 copy if it hardcodes v12 names)

- [ ] **Step 1: Focused verification first**

Run: `python -m pytest tests/test_candidate_footprint.py tests/test_source_encodings.py tests/test_refactor_staging.py tests/test_matching_direction.py tests/test_position_matching.py tests/test_unified_holdings.py tests/test_joint_borrowers.py tests/test_bdc_xbrl_wrapper.py -q --durations=20 --durations-min=0.5`
Expected: all pass. Then `python scripts/diff_outputs.py --semantic` shows zero new material differences.

- [ ] **Step 2: Copy the full-suite controller with v3 evidence names**

```bash
cd scratch/2026-09-12_programme_e0
sed -e 's/refactor-prebuild-full-suite-v2/refactor-prebuild-full-suite-v3/g' \
    -e 's/refactor-prebuild-full-backstop-v2/refactor-prebuild-full-backstop-v3/g' \
    -e 's/refactor-prebuild-test-sequence-v2/refactor-prebuild-test-sequence-v3/g' \
    -e 's/postgres-prebuild-tests-v2/postgres-prebuild-tests-v3/g' \
    verify_refactor_prebuild_tests_v2.ps1 > verify_refactor_prebuild_tests_v3.ps1
grep -c "v3" verify_refactor_prebuild_tests_v3.ps1
```
Expected: the grep count is at least 4 and `grep -n "v2" verify_refactor_prebuild_tests_v3.ps1` shows no remaining evidence-name references (source-before/after JSON names in `scratch/2026-09-16_refactor_continuation/` must also become `refactor-prebuild-full-v3-source-before.json` / `-after.json`; sed those too if present).

- [ ] **Step 3: Run the full suite (no other heavy job)**

Confirm no python process and no live heavy lock, then launch detached with the quoted `-File` path as in Task 0 Step 2, output to `verify_refactor_prebuild_tests_v3-controller.log`. Expected duration about 3.1 h plus a 16 min backstop. Expected: `refactor-prebuild-test-sequence-v3/result.json` status PASS, 237,624 protected files unchanged, 799 pinned source files changed ONLY in the files committed by Tasks 1-5 (the source-before/after diff must list exactly `pipeline/position_matching.py`, `pipeline/source_encodings.py`, `scripts/candidate_footprint.py`, the four test files, the wrapper JSON and docs). Any other changed file blocks the freeze.

- [ ] **Step 4: Seal V13 readiness**

```bash
cd scratch/2026-09-16_refactor_continuation
sed -e 's/v12-/v13-/g' -e 's/reviewed-repairs-v4/refactor-prebuild-full-v3/g' -e 's/refactor-prebuild-full-v2/refactor-prebuild-full-v3/g' -e 's/refactor-prebuild-test-sequence-v2/refactor-prebuild-test-sequence-v3/g' -e 's/refactor-prebuild-full-backstop-v2/refactor-prebuild-full-backstop-v3/g' seal_v12_source.py > seal_v13_source.py
grep -n "v12\|v2\b\|v4\b" seal_v13_source.py
```
Fix any remaining v12/v2/v4 evidence path by hand so every pinned path exists on disk. Generate the overlay review the same way `v12-reviewed-overlay-v1.json` was generated (run `prepare_v12_snapshot_review.py --help` and pass `--base production-20260916-v12 --candidate production-20260917-v13 --name v13-reviewed-overlay-v1` or copy it to a v13 variant if names are hardcoded). Then `python seal_v13_source.py` writes `v13-source-ready-v1.json` with status PASS.

- [ ] **Step 5: Changelog and commit**

Append the full-suite counts and the seal. Commit the two new scratch scripts are git-ignored; commit only the changelog.

---

### Task 7: Build V13 with the footprint and packet gates after the identity stage

**Files:**
- Create: `scratch/2026-09-16_refactor_continuation/build_v13.ps1` (from `build_v12.ps1`)

- [ ] **Step 1: Copy and re-point**

```bash
cd scratch/2026-09-16_refactor_continuation
sed -e "s/production-20260916-v12/production-20260917-v13/g" \
    -e "s/\$base='production-20260915-v11b'/\$base='production-20260916-v12'/" \
    -e "s/v12-reviewed-overlay-v1.json/v13-reviewed-overlay-v1.json/" \
    -e "s/v12-source-ready-v1.json/v13-source-ready-v1.json/" \
    -e "s/architecture-v12-sequence-v1/architecture-v13-sequence-v1/" \
    -e "s/v12-compressed-snapshot-v1/v13-compressed-snapshot-v1/" \
    -e "s/v12-overlay-review-v1/v13-overlay-review-v1/" \
    -e "s/'v12-preflight-archive-v1'/'v13-preflight-archive-v1'/" \
    -e "s/\"v12-\$stage-archive-v1\"/\"v13-\$stage-archive-v1\"/" \
    -e "s/identity-v12-versus-/identity-v13-versus-/g" \
    build_v12.ps1 > build_v13.ps1
grep -n "v12" build_v13.ps1
```
Expected: the only remaining `v12` strings are the base candidate name and the prior list entry.

- [ ] **Step 2: Change the prior list and insert the gates**

In `build_v13.ps1` the final comparison loop must compare against V12 and V11b:
```powershell
    foreach($prior in @(@{candidate=$base;name='v12'},@{candidate='production-20260915-v11b';name='v11b'})){
```
Inside the stage loop, immediately after `Invoke-Step "build-$stage" ...` add, guarded to run only when `$stage -eq 'identity'`:
```powershell
        if($stage -eq 'identity'){
            Invoke-Step 'footprint-vs-v12' @('scripts/candidate_footprint.py','--candidate',$Candidate,'--prior',$base,
                '--out',(Join-Path $sequence 'footprint-vs-v12.json'))
            Invoke-Step 'packets-vs-v12' @((Join-Path $e0 'compare_candidate_identity.py'),
                '--candidate',$Candidate,'--prior',$base,'--name','identity-v13-early-versus-v12-v1')
            $early=Get-Content -LiteralPath (Join-Path $e0 'identity-v13-early-versus-v12-v1/result.json') -Raw | ConvertFrom-Json
            $regressions=@($early.all_packet_regression.transitions.regressions)
            if($regressions.Count -gt 0){throw ('Identity regressions vs V12 after identity stage: '+$regressions.Count+'; evidence preserved; stop before evidence stage')}
        }
```
`Invoke-Step` throws on a non-zero exit, so a FLAGGED footprint stops the build before the evidence stage with the report on disk. Note `compare_candidate_identity.py` takes the heavy lock on the candidate; it runs after the stage releases it.

- [ ] **Step 3: Launch (no other heavy job) and monitor**

Launch detached with the quoted `-File` path. Expected timeline: snapshot 35 min, canary 8, preflight 25, unified about 2.5 h, gates 5 min, identity 55 min, evidence 35, returns 30, frontend 60, comparisons 2. Monitor `architecture-v13-sequence-v1/` and `build_v13-controller-v1.log`.

Expected gate outcomes: footprint `labelled_parent_rows.0001803498` = 0 (measured, not assumed: `scratch/2026-09-17_v13_repairs/predict_v13_labelled_parent_v1.py` evaluates the repaired `pipeline.accounting_scope.scope_expression` against the immutable V12 bundle and then applies the gate's own `_label_regex`/`_own_interest_exclusion_pattern` predicate to the rows that remain parent-scoped; predicted value 0 -- the 14 rows that still match the label regex are the fund's own correctly-parent BCRED Emerald/Verdelite JV LP interests, all excluded by the gate's own-interest pattern, and no other row matches the label regex at all). `match_method.E_entity_fingerprint` within 2x of V12's 54,435 is NOT the target, the target is that Tier E is back near the V11b level plus genuine directional recoveries.

TWO ratio flags are expected on this run, not one, and both are expected consequences of the named repairs -- not defects:
1. Tier E contracting more than 2x from V12's 54,435 (Task 4: Tier E no longer settles for second best).
2. `match_method.B2_leftover_round` growing more than 2x, because the Task 3 directional-slot repair releases tier-A-claimed end rows to B2-leftover's begin side.

If the ratio flag fires on either or both of these two metrics for exactly the reasons above, that is the intended correction. Handle it like this, in order:

1. Read the written JSON report at `footprint-vs-v12.json` (or the `--out` path used).
2. Confirm `labelled_parent_rows.0001803498` equals the value finding 3 measured (0). Any other value is a stop: do not resume the build. A nonzero value means the repaired scope rule left a JV-labelled row in parent scope that the gate's own predicate also catches, which is exactly the zero-tolerance scope defect this gate exists to catch -- investigate the mechanism before touching the build again.
3. Confirm every OTHER flag present is one of the two named ratio flags above (tier E contraction, `B2_leftover_round` growth) and, if any additional metric is flagged, treat that as a stop and investigate it on its own terms rather than folding it into the expected pair.
4. Only after both checks pass, resume the build from the next stage by re-invoking the controller (write a resume controller that skips completed stages; do not edit the sealed attempts).

Do NOT use `--report-only` to get past a flagged run. `--report-only` suppresses the exit code for every metric at once, including the zero-tolerance scope check (`labelled_parent_rows`), so using it to wave through an expected ratio flag would also silently wave through a real scope regression if one happened to land on the same run. Read the JSON report and reason about each flag by name instead; never disarm the whole gate to get past one metric.

Zero packet regressions vs V12 required. Packets vs V11b may still show IRI and Truck-Lite (recorded in Task 5) and nothing else.

- [ ] **Step 4: Record**

Append the stage timings, footprint numbers and both comparison summaries to `docs/agent_changelog.md`.

---

### Task 8: Evaluate V13 end to end, then twin, public, recovery, final suite

Run in this order. Each is a copy of the V12 controller with names re-pointed; the interfaces are known.

- [ ] **Step 1: Financial and collector sequence**

```bash
cd scratch/2026-09-16_refactor_continuation
sed -e "s/production-20260916-v12/production-20260917-v13/g" -e "s/v11b/v12/g" -e "s/v12-evaluation-sequence-v1/v13-evaluation-sequence-v1/" evaluate_v12.ps1 > evaluate_v13.ps1
grep -n "prior\|--name" evaluate_v13.ps1
```
Check every `--prior` is `production-20260916-v12` for the first comparison and `production-20260915-v11b` for the second (restore the v11b literal where the sed turned it into v12 by mistake), and every `--name` ends in `-v13-...-v1`. Launch detached. Expected: `v13-evaluation-sequence-v1/result.json` status `collectors_complete_p4_review_required`; `financial-vs-v12` deltas explained by exactly three mechanisms (BCRED scope moves USD ~10.5B from parent to underlying; tier slot recoveries; Tier E contraction). Delivery collector must PASS on its calculated-evidence checks (it failed on V11b; its repair is first exercised here).

- [ ] **Step 2: 13-quarter gate and re-attestation**

```bash
sed -e "s/production-20260916-v12/production-20260917-v13/g" -e "s/v12-evaluation-sequence-v1/v13-evaluation-sequence-v1/" -e "s/v12-acceptance-sequence-v1/v13-acceptance-sequence-v1/" -e "s/v11b/v12/g" evaluate_v12_acceptance.ps1 > evaluate_v13_acceptance.ps1
```
Launch. Expected: all 13 quarters evaluated under unchanged thresholds; per-quarter deltas vs V12 listed. BCRED 2023 conservation should IMPROVE (underlying rows now excluded from parent sums). Any quarter that flips PASS->FAIL needs a source-attributed mechanism recorded before continuing. Re-attestation against signed-off quarters: a regression is a stop-and-report event.

- [ ] **Step 3: Cold twin**

```bash
cd scratch/2026-09-12_programme_e0
sed -e "s/production-20260916-v12/production-20260917-v13/g" -e "s/architecture-v12-twin-sequence-v1/architecture-v13-twin-sequence-v1/" verify_architecture_v12_twin.ps1 > verify_architecture_v13_twin.ps1
```
Confirm at least 35 GiB free (archive V13 raw copies with the same `archive_completed_workspace.py` pattern if not). Launch. About 5 h. Expected: `mode: twin`, `typed_observation_difference: 0`, every `artifact_differences` value 0, `release_manifest_equal: true`, status PASS. Any nonzero difference is a determinism defect and blocks closeout.

- [ ] **Step 4: Public build and browser checks on V13**

```bash
sed -e "s/production-20260916-v12/production-20260917-v13/g" -e "s/architecture-v12-public-sequence-v1/architecture-v13-public-sequence-v1/" -e "s/production-v12-v1/production-v13-v1/" -e "s/public-scope-v12-v1/public-scope-v13-v1/" verify_architecture_v12_public.ps1 > verify_architecture_v13_public.ps1
```
Launch after Step 3 finishes (both use the candidate lock). Expected: offline font replay 41 files, `npm run build` exit 0 with no external connections, scope check PASS, delivery census zero metadata errors and zero misleading links, browser scenarios pass including the Golub Q2-2023 cash-only wording, local p95 recorded.

- [ ] **Step 5: Recovery and cancellation drill**

Create `scratch/2026-09-16_refactor_continuation/recovery_drill_v13.ps1`:

```powershell
param([string]$Candidate='production-20260917-v13-drill')
$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python='C:\Users\alger\miniconda3\python.exe'
$base='production-20260917-v13'
$review=Join-Path $PSScriptRoot 'v13-reviewed-overlay-v1.json'
$sequence=Join-Path $PSScriptRoot 'recovery-drill-v13-v1'
if(Test-Path -LiteralPath $sequence){throw 'Preserve drill evidence'}
New-Item -ItemType Directory -Path $sequence | Out-Null
Set-Location -LiteralPath $repo
function Hash([string]$p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash}
$registry=Join-Path $repo "data/programme/candidates/$base/attempts/identity-01/bundle/identity_registry.duckdb"
$before=@{registry=Hash $registry;base_snapshot=Hash (Join-Path $repo "data/programme/candidates/$base/snapshot.json")}
& $python (Join-Path $PSScriptRoot 'snapshot_repaired_candidate.py') --candidate $Candidate --base $base --current-code --name 'v13-drill-snapshot-v1' *> (Join-Path $sequence 'snapshot.log')
if($LASTEXITCODE -ne 0){throw 'drill snapshot failed'}
& $python -m pipeline.programme.runner preflight --candidate $Candidate *> (Join-Path $sequence 'preflight.log')
if($LASTEXITCODE -ne 0){throw 'drill preflight failed'}
# Interrupt: start the unified stage, kill the worker after 20 minutes, mid-build.
$p=Start-Process -FilePath $python -ArgumentList @('-m','pipeline.programme.runner','run','--candidate',$Candidate,'--stage','unified') -WorkingDirectory $repo -PassThru -RedirectStandardOutput (Join-Path $sequence 'unified-interrupted.log') -RedirectStandardError (Join-Path $sequence 'unified-interrupted.err.log') -WindowStyle Hidden
Start-Sleep -Seconds 1200
Stop-Process -Id $p.Id -Force
Start-Sleep -Seconds 10
$attempts=Get-ChildItem -LiteralPath (Join-Path $repo "data/programme/candidates/$Candidate/attempts") -Directory | Where-Object {$_.Name -like 'unified-*'}
if($attempts.Count -ne 1){throw 'expected exactly one interrupted unified attempt'}
$interrupted=$attempts[0].FullName
if(Test-Path -LiteralPath (Join-Path $interrupted 'complete.json')){throw 'interrupted attempt must not be sealed'}
# Resume: the runner must refuse to reuse the broken attempt and open unified-02.
& $python -m pipeline.programme.runner run --candidate $Candidate --stage unified *> (Join-Path $sequence 'unified-resumed.log')
$code=$LASTEXITCODE
$after=@{registry=Hash $registry;base_snapshot=Hash (Join-Path $repo "data/programme/candidates/$base/snapshot.json")}
$attempts2=@(Get-ChildItem -LiteralPath (Join-Path $repo "data/programme/candidates/$Candidate/attempts") -Directory | Where-Object {$_.Name -like 'unified-*'})
$result=@{status=(if($code -eq 0 -and $attempts2.Count -eq 2 -and (Test-Path (Join-Path $interrupted 'process.log')) -and $before.registry -eq $after.registry -and $before.base_snapshot -eq $after.base_snapshot){'PASS'}else{'FAIL'});
  resume_exit=$code;attempts=@($attempts2.Name);interrupted_preserved=(Test-Path $interrupted);base_registry_unchanged=($before.registry -eq $after.registry);base_snapshot_unchanged=($before.base_snapshot -eq $after.base_snapshot)}
[IO.File]::WriteAllText((Join-Path $sequence 'result.json'),($result|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
if($result.status -ne 'PASS'){throw 'recovery drill failed; evidence preserved'}
```
Launch after Step 4 (needs the lock and about 3 h). Expected: PASS. The drill candidate is then archived and released like any completed raw copy; its sealed unified-02 is evidence, not a product.

- [ ] **Step 6: Final suite on the frozen V13 source**

Copy `verify_architecture_v12_final_tests.ps1` to a v13 variant with re-pointed evidence names (same sed pattern as above) and run with no other heavy job. Expected: pass counts equal to Task 6 Step 3 (the source has not changed since the seal; if it has, the seal is void and Task 6 restarts).

- [ ] **Step 7: Closeout record**

Append to `docs/production_stack/2026-09-16_refactor_status.md` a dated checkpoint listing, per package P1-P8, the V13 evidence path that satisfies it, and an explicit residual list (at minimum: the two joint-borrower gold disagreements; any quarter still failing the gate with its source-attributed mechanism; the unresolved economic correctness of BCRED/Bain/T.Rowe currency tags). Append the changelog entry. Commit docs. Do NOT adopt, publish or refresh the baseline; those are owner decisions.

---

## Self-review

- Spec coverage: scope completeness plus cross-quarter consistency (Task 2 rule, Task 1 `labelled_parent_rows` metric, Task 7 gate); directional slots in B2-leftover/C/D (Task 3, F included for the same construct); Tier E discipline (Task 4, structural rather than a rate veto because `interest_rate` is NULL on the Metropolis rows and the rates live only in identifier text); joint rule kept and recorded (Task 5); pre-freeze footprint (Task 1, wired in Task 7); never-run checks pulled forward (Task 0 on V12; Task 8 on V13); recovery drill controller written (Task 8 Step 5).
- Placeholder scan: Task 3 Steps 4-6 give the CTE replacement code and a mechanical alias rule for the join predicates rather than every line of tier C/D, because those functions were not fully read during planning; tier E in the same file is the completed template of the identical edit. Task 6 Step 4 depends on `prepare_v12_snapshot_review.py` argument names that must be read at execution.
- Type consistency: `_slot_availability_ctes(prior_tiers: tuple[str, ...]) -> str` is used identically in Tasks 3 and 4; `compute_footprint(bundle, encodings=None) -> dict` and `compare_footprints(current, prior, max_ratio=2.0) -> list[dict]` match between the tests, the script and the Task 7 CLI call.
