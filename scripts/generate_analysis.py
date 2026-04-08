import pathlib

SCRIPT = """
import duckdb
import time

DATA = "data/output"
UNIFIED = DATA + "/private_markets_holdings.csv"
MATCHES = DATA + "/position_matches.csv"
RETURNS = DATA + "/position_returns.csv"
""".strip()

pathlib.Path("scripts/position_id_defect_analysis.py").write_text(SCRIPT, encoding="utf-8")
