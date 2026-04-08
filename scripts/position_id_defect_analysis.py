"""
Comprehensive DuckDB-based defect analysis on position_id across:
  1. private_markets_holdings.csv (unified)
  2. position_matches.csv (match pairs)
  3. position_returns.csv (position returns)
"""
import duckdb
import time

DATA = "data/output"
UNIFIED = DATA + "/private_markets_holdings.csv"
MATCHES = DATA + "/position_matches.csv"
RETURNS = DATA + "/position_returns.csv"


def banner(t):
    print()
    print("=" * 80)
    print("  " + t)
    print("=" * 80)


def sub(t):
    print()
    print("--- " + t + " ---")
