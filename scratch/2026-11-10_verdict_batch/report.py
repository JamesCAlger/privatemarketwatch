"""Counts and owner lists from results.csv. Writes still_live.csv and unclear.csv here."""
from pathlib import Path
import pandas as pd
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 200)
HERE = Path(__file__).resolve().parent
r = pd.read_csv(HERE / "results.csv", dtype=str).fillna("")
r["grp"] = r.v05.map({"True": "v0.5", "False": "rest"})
r["q"] = r.report_date.where(r.report_date.isin(["2026-03-31", "2025-12-31"]), "other")
print(r.groupby(["grp", "q", "status"]).size().unstack(fill_value=0).to_string())
print("total", r.status.value_counts().to_dict())
cols = ["review_id", "cik", "report_date", "rule", "family", "reason", "priority"]
r[r.status.eq("FAIL")].sort_values(["priority", "cik", "report_date"])[cols].to_csv(HERE / "still_live.csv", index=False)
r[r.status.eq("UNCLEAR")].sort_values(["priority", "cik", "report_date"])[cols].to_csv(HERE / "unclear.csv", index=False)
top = r[r.priority.astype(int) <= 2]
print("\n== v0.5 2026-03-31 / 2025-12-31")
print(top.sort_values(["report_date", "status"], ascending=[False, True])[["report_date", "cik", "rule", "status", "reason"]].to_string(index=False))
print("\n== FAIL p3 by reason class")
f3 = r[r.status.eq("FAIL") & r.priority.eq("3")]
print(f3[["cik", "report_date", "rule", "reason"]].to_string(index=False))
print("\n== UNCLEAR p3 by reason class")
u3 = r[r.status.eq("UNCLEAR") & r.priority.eq("3")]
print(u3.reason.str.replace(r"[0-9][0-9,.%]*", "#", regex=True).str[:70].value_counts().head(25).to_string())
