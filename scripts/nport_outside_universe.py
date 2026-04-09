"""
Analyze ~1,855 N-PORT CIKs NOT in the pipeline universe.
"""

import duckdb
import zipfile
import io
import csv
import os
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

con = duckdb.connect()

universe_ciks = con.sql("""
    SELECT DISTINCT CAST(cik AS VARCHAR) as cik 
    FROM read_csv("data/output/combined_universe.csv", auto_detect=true)
""").fetchdf()["cik"].tolist()
universe_set = set(str(int(c)) for c in universe_ciks)
print(f"Universe CIKs: {len(universe_set)}")
