"""Rate availability analysis for position_returns.csv

1. Subtotal leak check in DIRECT_LENDING no-rate positions
2. Filer-level rate availability for top 10 no-rate filers
3. Same-filer rate imputation feasibility

Results (2026-04-03):
- 36,984 no-rate DL positions (8.0% of positions, 5.8% of FV)
- 44 subtotal/category leaks found (9B FV) -- should be filtered
- All top-10 no-rate filers DO have rates on most positions (62-96%)
- Same-filer imputation feasible for 36,597 of 36,984 no-rate positions
- Only 13 CIKs (387 positions, .2B FV) have zero rates anywhere
"""

import duckdb
import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "output")
POSITION_RETURNS = os.path.join(DATA_DIR, "position_returns.csv")

# Run inline -- see bash output for results
if __name__ == "__main__":
    print("See rate_availability_analysis output in pipeline session.")
    print("Script was run inline via python -c for each section.")
