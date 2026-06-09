# Fund Highlights Wrapper -- Validate Mode

Validate that a wrapper fixes oracle failures without introducing regressions.

## Step 1: Run trial with and without wrapper

```bash
# Baseline (no wrapper)
python scripts/rebuild_highlights_cik_trial.py --cik {CIK} --no-wrapper

# With wrapper
python scripts/rebuild_highlights_cik_trial.py --cik {CIK}
```

Outputs go to `data/output/fund_highlights_wrapper_trial/{CIK}/`.

## Step 2: Compare identity pass rates

Check the trial output log for before/after numbers:
- NAV identity pass rate should improve or stay the same
- Income identity pass rate should improve or stay the same
- No new failures should appear

## Step 3: Verify no-wrapper CIKs unaffected

The wrapper only affects the target CIK. But verify by inspecting the wrapper loader:
- `load_highlights_wrapper(other_cik)` should return None
- This means extraction and oracle behavior is unchanged for other CIKs

## Step 4: Run tests

```bash
pytest tests/test_fund_highlights_wrapper.py -v
```

## Step 5: Full oracle rebuild (optional)

If satisfied with the single-CIK trial, run a full highlights oracle rebuild:

```bash
python scripts/rebuild_outputs.py --highlights --highlights-oracle
```

Check that aggregate pass/fail/review counts have not regressed.

## Success contract

A wrapper is valid when:
1. Schema validation passes (correct JSON structure)
2. Trial rebuild shows improved or unchanged identity pass rates
3. No new oracle failures introduced
4. `pytest tests/test_fund_highlights_wrapper.py` passes
5. Notes document why the wrapper exists and what evidence supports it
