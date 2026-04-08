import pandas as pd
import re

CSV = r"data/output/position_returns.csv"

print("=" * 90)
print("LOADING position_returns.csv ...")
df = pd.read_csv(CSV, low_memory=False)
print("Total rows: {:,}".format(len(df)))
print("Index classifications:")
print(df["index_classification"].value_counts().to_string())
print()

# 1. Filter: DIRECT_LENDING with null or zero income_rate
dl = df[df["index_classification"] == "DIRECT_LENDING"].copy()
print("DIRECT_LENDING rows: {:,}".format(len(dl)))

no_rate = dl[dl["income_rate"].isna() | (dl["income_rate"] <= 0)].copy()
print("DIRECT_LENDING with income_rate NULL or <= 0: {:,}  ({:.1f}% of DL)".format(
    len(no_rate), len(no_rate)/len(dl)*100))
print("  begin_fair_value sum: ${:,.0f}".format(no_rate["begin_fair_value"].sum()))
print()

# 2. Equity / co-invest / JV patterns in no-rate DL
# Use case-insensitive flag at the start, not inline per-alternative
EQUITY_PATTERNS = [
    (r"\bJV\b", "JV (word)", False),         # case-sensitive
    (r"joint\s+venture", "Joint Venture", True),
    (r"\bequity\b", "equity", True),
    (r"\bcommon\b", "common", True),
    (r"\bpreferred\b", "preferred", True),
    (r"\bwarrant", "warrant", True),
    (r"\bclass\s+[a-c]\b", "Class A/B/C", True),
    (r"\blp\s+interest", "LP Interest", True),
    (r"\bmembership\s+interest", "membership interest", True),
    (r"\bpartnership\s+interest", "partnership interest", True),
    (r"\bco[\-\s]?invest", "co-invest", True),
    (r"\bcoinvest", "coinvest", True),
]

# Build a single combined case-insensitive pattern
# JV needs special handling since it's case-sensitive
combined_ci = "|".join(p for p, _, ci in EQUITY_PATTERNS if ci)
combined_cs = "|".join(p for p, _, ci in EQUITY_PATTERNS if not ci)

no_rate["eq_ci"] = no_rate["issuer_name"].str.contains(combined_ci, regex=True, na=False, case=False)
no_rate["eq_cs"] = no_rate["issuer_name"].str.contains(combined_cs, regex=True, na=False)
no_rate["equity_flag"] = no_rate["eq_ci"] | no_rate["eq_cs"]

eq_hits = no_rate[no_rate["equity_flag"]]
print("-" * 90)
print("2. EQUITY / CO-INVEST / JV patterns in no-rate DIRECT_LENDING")
print("-" * 90)
print("Matched rows: {:,}  ({:.1f}% of no-rate DL)".format(len(eq_hits), len(eq_hits)/max(len(no_rate),1)*100))
print("begin_fair_value sum: ${:,.0f}".format(eq_hits["begin_fair_value"].sum()))
print()
for pat, label, ci in EQUITY_PATTERNS:
    mask = no_rate["issuer_name"].str.contains(pat, regex=True, na=False, case=not ci)
    n = mask.sum()
    fv = no_rate.loc[mask, "begin_fair_value"].sum()
    if n > 0:
        print("  {:30s}  {:>6,} rows   ${:>15,.0f} FV".format(label, n, fv))
print()
print("Sample issuer names (first 40):")
for i, name in enumerate(eq_hits["issuer_name"].drop_duplicates().head(40)):
    print("  {:3d}. {}".format(i+1, str(name)[:120]))
print()

# 3. asset_category and index_classification for equity-patterned no-rate DL
print("-" * 90)
print("3. ASSET_CATEGORY & INDEX_CLASSIFICATION for equity-patterned no-rate DL")
print("-" * 90)
print()
print("asset_category breakdown:")
print(eq_hits["asset_category"].value_counts(dropna=False).head(20).to_string())
print()
print("index_classification breakdown (should all be DIRECT_LENDING):")
print(eq_hits["index_classification"].value_counts(dropna=False).head(10).to_string())
print()

# 4. JV entities specifically
jv_cs = r"\bJV\b"
jv_ci = r"joint\s+venture|partners\s+jv"
jv_mask = (no_rate["issuer_name"].str.contains(jv_cs, regex=True, na=False) | 
           no_rate["issuer_name"].str.contains(jv_ci, regex=True, na=False, case=False))
jv_rows = no_rate[jv_mask]
print("-" * 90)
print("4. JV ENTITIES in no-rate DIRECT_LENDING: {:,} rows".format(len(jv_rows)))
print("-" * 90)
cols = ["cik", "entity_name", "source", "issuer_name", "asset_category",
        "index_classification", "begin_fair_value", "income_rate",
        "begin_quarter", "end_quarter"]
if len(jv_rows) > 0:
    pd.set_option("display.max_colwidth", 80)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 100)
    print(jv_rows[cols].sort_values("begin_fair_value", ascending=False).head(60).to_string(index=False))
jv_all_mask = (dl["issuer_name"].str.contains(jv_cs, regex=True, na=False) |
               dl["issuer_name"].str.contains(jv_ci, regex=True, na=False, case=False))
jv_all_dl = dl[jv_all_mask]
print()
print("JV entities in ALL DIRECT_LENDING (incl. with rate): {:,}".format(len(jv_all_dl)))
print("  begin_fair_value sum: ${:,.0f}".format(jv_all_dl["begin_fair_value"].sum()))
print()

# 5. Broader: ALL DIRECT_LENDING positions that look non-debt
print("=" * 90)
print("5. ALL DIRECT_LENDING positions (with or without rate) with non-debt names")
print("=" * 90)
NON_DEBT_PATTERNS = [
    (r"\bJV\b", False, "JV (case-sensitive)"),
    (r"joint\s+venture", True, "Joint Venture"),
    (r"\bequity\b", True, "equity (word)"),
    (r"\bcommon\s+(stock|unit|share|equity)", True, "common stock/unit"),
    (r"\bpreferred\s+(stock|unit|share|equity)", True, "preferred stock/unit"),
    (r"\bwarrant", True, "warrant"),
    (r"\bclass\s+[a-c]\s+(unit|share|interest|member)", True, "Class A/B/C units"),
    (r"\blp\s+(interest|unit|interests)", True, "LP Interest/Unit"),
    (r"\bmembership\s+(interest|unit)", True, "membership interest"),
    (r"\bpartnership\s+(interest|unit)", True, "partnership interest"),
    (r"\bco[\-\s]?invest", True, "co-invest"),
    (r"\bcoinvest", True, "coinvest"),
]
# Build combined
nd_ci = "|".join(p for p, ci, _ in NON_DEBT_PATTERNS if ci)
nd_cs = "|".join(p for p, ci, _ in NON_DEBT_PATTERNS if not ci)
dl["non_debt_flag"] = (dl["issuer_name"].str.contains(nd_ci, regex=True, na=False, case=False) |
                       dl["issuer_name"].str.contains(nd_cs, regex=True, na=False))
non_debt = dl[dl["non_debt_flag"]]
print()
print("DIRECT_LENDING rows with non-debt issuer names: {:,}  ({:.1f}% of DL)".format(
    len(non_debt), len(non_debt)/len(dl)*100))
print("begin_fair_value sum: ${:,.0f}".format(non_debt["begin_fair_value"].sum()))
print()
print("Pattern breakdown (rows may overlap):")
for pat, ci, label in NON_DEBT_PATTERNS:
    mask = dl["issuer_name"].str.contains(pat, regex=True, na=False, case=not ci)
    n = mask.sum()
    fv = dl.loc[mask, "begin_fair_value"].sum()
    if n > 0:
        has_rate = dl.loc[mask, "income_rate"].notna() & (dl.loc[mask, "income_rate"] > 0)
        print("  {:30s}  {:>6,} rows  ${:>16,.0f} FV  ({:,} with rate, {:,} without)".format(
            label, n, fv, has_rate.sum(), n - has_rate.sum()))
print()
print("asset_category for non-debt DIRECT_LENDING:")
print(non_debt["asset_category"].value_counts(dropna=False).head(15).to_string())
print()
print("Top 20 entities by non-debt DIRECT_LENDING rows:")
top_ent = (non_debt.groupby(["cik", "entity_name"])
           .agg(rows=("issuer_name", "size"), fv=("begin_fair_value", "sum"))
           .sort_values("rows", ascending=False).head(20))
print(top_ent.to_string())
print()
non_equity_non_debt = non_debt[~non_debt["issuer_name"].str.contains(r"\bequity\b", regex=True, na=False, case=False)]
print("Non-debt DL names NOT containing 'equity' ({:,} rows):".format(len(non_equity_non_debt)))
print("Sample unique names (first 30):")
for i, name in enumerate(non_equity_non_debt["issuer_name"].drop_duplicates().head(30)):
    print("  {:3d}. {}".format(i+1, str(name)[:130]))
print()
print("=" * 90)
print("DONE")
