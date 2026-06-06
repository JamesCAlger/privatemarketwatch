# Testing Workflow

Use proportional verification. Do not run the full suite as the default inner loop.

## Fast Development Loop

Run the smallest relevant test first:

```powershell
python -m pytest tests/test_unified_holdings.py::TestBuildUnifiedHoldings::test_load_from_disk -vv --tb=short
```

Then run affected subsystem files:

```powershell
python -m pytest tests/test_unified_holdings.py tests/test_validate_holdings.py --tb=short
python -m pytest tests/test_interval_source_review.py tests/test_html_soi_evidence.py --tb=short
python -m pytest tests/test_position_matching.py tests/test_index_returns.py --tb=short
```

After `slow` markers are in place, this is the normal broad fast check:

```powershell
python -m pytest tests/ -m "not slow" --ignore=tests/test_column_validation.py --tb=short
```

## Data-Semantics Changes

For unified holdings or validation logic that can change public artifacts, tests are only the first gate:

```powershell
python -m pytest tests/test_unified_holdings.py tests/test_validate_holdings.py --tb=short
python scripts/rebuild_outputs.py --unified
python scripts/diff_outputs.py --semantic
```

Use the relevant rebuild/export command for other artifacts.

## Full-Suite Gate

Run the full suite before merge/handoff, after broad refactors, or when shared contracts change:

```powershell
python -m pytest tests/ --ignore=tests/test_column_validation.py --tb=short --durations=50 --durations-min=0.5
```

Before starting a long run, check for existing pytest processes. Do not run overlapping full suites from multiple agents.
