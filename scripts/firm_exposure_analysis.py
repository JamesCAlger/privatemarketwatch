"""
Firm-level exposure breakdown analysis for private markets index data.
Ad-hoc research script -- not part of the pipeline.
"""
import duckdb

DATA_PATH = r"C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl\data\output\private_markets_holdings.csv"

con = duckdb.connect()

# Load the data
con.execute(f"""
    CREATE TABLE holdings AS
    SELECT * FROM read_csv_auto('{DATA_PATH}', sample_size=100000)
""")

# ============================================================
# 0. Find the latest REAL quarter (quarter-end with significant data)
# ============================================================
print("=" * 80)
print("SECTION 0: DATA OVERVIEW")
print("=" * 80)

# Find the quarter-end date with the most data
qtr_stats = con.execute("""
    SELECT
        report_date,
        COUNT(*) as n_rows,
        SUM(ABS(fair_value)) / 1e9 as fv_bn,
        COUNT(DISTINCT cik) as n_ciks
    FROM holdings
    WHERE index_classification IN ('DIRECT_LENDING', 'DIRECT_EQUITY')
      AND EXTRACT(MONTH FROM report_date::DATE) IN (3,6,9,12)
      AND EXTRACT(DAY FROM report_date::DATE) >= 28
    GROUP BY report_date
    HAVING COUNT(*) > 1000
    ORDER BY report_date DESC
    LIMIT 10
""").fetchall()

print("Recent quarter-end dates with substantial data:")
print(f"{'Date':<14} {'Rows':>8} {'FV ($B)':>8} {'CIKs':>6}")
print("-" * 40)
for r in qtr_stats:
    print(f"{str(r[0]):<14} {r[1]:>8,} {r[2]:>8.1f} {r[3]:>6}")

latest_q = qtr_stats[0][0]
print(f"\nUsing latest quarter-end: {latest_q}")

# Overall stats
result = con.execute("""
    SELECT
        COUNT(*) as total_rows,
        COUNT(DISTINCT cik) as unique_ciks,
        COUNT(DISTINCT entity_name) as unique_entities
    FROM holdings
""").fetchone()
print(f"Total rows: {result[0]:,}")
print(f"Unique CIKs: {result[1]:,}")
print(f"Unique entities: {result[2]:,}")

print(f"\nRows and FV by index_classification (quarter: {latest_q}):")
rows = con.execute(f"""
    SELECT
        index_classification,
        COUNT(*) as positions,
        SUM(ABS(fair_value)) / 1e9 as total_fv_bn,
        SUM(fair_value) / 1e9 as net_fv_bn,
        COUNT(DISTINCT cik) as firms
    FROM holdings
    WHERE report_date = '{latest_q}'
    GROUP BY index_classification
    ORDER BY total_fv_bn DESC
""").fetchall()
print(f"{'Index':<25} {'Positions':>10} {'|FV| ($B)':>10} {'Net FV($B)':>11} {'Firms':>6}")
print("-" * 65)
for r in rows:
    print(f"{r[0]:<25} {r[1]:>10,} {r[2]:>10.1f} {r[3]:>11.1f} {r[4]:>6}")

# ============================================================
# 1. Top 20 firms by total FV for DIRECT_LENDING and DIRECT_EQUITY
# ============================================================
for index_name in ['DIRECT_LENDING', 'DIRECT_EQUITY']:
    print("\n" + "=" * 80)
    print(f"SECTION 1: TOP 20 FIRMS BY FAIR VALUE - {index_name} (quarter: {latest_q})")
    print("=" * 80)

    rows = con.execute(f"""
        WITH latest AS (
            SELECT entity_name, cik, fair_value
            FROM holdings
            WHERE report_date = '{latest_q}'
              AND index_classification = '{index_name}'
        ),
        totals AS (
            SELECT SUM(ABS(fair_value)) as total_index_fv
            FROM latest
        ),
        by_firm AS (
            SELECT
                entity_name,
                LPAD(CAST(cik AS VARCHAR), 10, '0') as cik,
                COUNT(*) as position_count,
                SUM(ABS(fair_value)) / 1e9 as firm_fv_bn,
                SUM(fair_value) / 1e9 as firm_fv_net_bn
            FROM latest
            GROUP BY entity_name, cik
        )
        SELECT
            bf.entity_name,
            bf.cik,
            bf.position_count,
            bf.firm_fv_bn,
            bf.firm_fv_net_bn,
            bf.firm_fv_bn / t.total_index_fv * 1e9 * 100 as pct_of_total
        FROM by_firm bf, totals t
        ORDER BY bf.firm_fv_bn DESC
        LIMIT 20
    """).fetchall()

    total_pct = 0
    print(f"{'#':>3} {'Entity Name':<55} {'CIK':<12} {'Pos':>6} {'FV($B)':>8} {'Net FV($B)':>10} {'% Total':>8}")
    print("-" * 107)
    for i, r in enumerate(rows, 1):
        total_pct += r[5]
        print(f"{i:>3} {r[0][:54]:<55} {r[1]:<12} {r[2]:>6,} {r[3]:>8.2f} {r[4]:>10.2f} {r[5]:>7.1f}%")
    print(f"\n    Top 20 cumulative: {total_pct:.1f}%")

# ============================================================
# 2. Concentration analysis
# ============================================================
print("\n" + "=" * 80)
print(f"SECTION 2: CONCENTRATION ANALYSIS (quarter: {latest_q})")
print("=" * 80)

for index_name in ['DIRECT_LENDING', 'DIRECT_EQUITY', 'PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND']:
    rows = con.execute(f"""
        WITH latest AS (
            SELECT entity_name, cik, fair_value
            FROM holdings
            WHERE report_date = '{latest_q}'
              AND index_classification = '{index_name}'
        ),
        total AS (
            SELECT SUM(ABS(fair_value)) as total_fv FROM latest
        ),
        by_firm AS (
            SELECT
                cik,
                SUM(ABS(fair_value)) as firm_fv
            FROM latest
            GROUP BY cik
            ORDER BY firm_fv DESC
        ),
        ranked AS (
            SELECT
                firm_fv,
                ROW_NUMBER() OVER (ORDER BY firm_fv DESC) as rn
            FROM by_firm
        )
        SELECT
            (SELECT SUM(firm_fv) FROM ranked WHERE rn <= 5) / t.total_fv * 100 as top5_pct,
            (SELECT SUM(firm_fv) FROM ranked WHERE rn <= 10) / t.total_fv * 100 as top10_pct,
            (SELECT SUM(firm_fv) FROM ranked WHERE rn <= 20) / t.total_fv * 100 as top20_pct,
            (SELECT COUNT(*) FROM by_firm) as total_firms,
            t.total_fv / 1e9 as total_fv_bn
        FROM total t
    """).fetchone()

    if rows[4] and rows[4] > 0:
        print(f"\n{index_name}:")
        print(f"  Total firms: {rows[3]}, Total FV: ${rows[4]:.1f}B")
        t5 = rows[0] if rows[0] else 0
        t10 = rows[1] if rows[1] else 0
        t20 = rows[2] if rows[2] else 0
        print(f"  Top  5 firms: {t5:.1f}%")
        print(f"  Top 10 firms: {t10:.1f}%")
        print(f"  Top 20 firms: {t20:.1f}%")

# ============================================================
# 3. Parent-subsidiary / brand analysis
# ============================================================
print("\n" + "=" * 80)
print("SECTION 3: PARENT-SUBSIDIARY / BRAND ANALYSIS")
print("=" * 80)

BRAND_PATTERNS = [
    ('Ares', ['ares']),
    ('Blackstone', ['blackstone', 'bxsl', 'bxcr']),
    ('Blue Owl / Owl Rock', ['blue owl', 'owl rock']),
    ('FS KKR', ['fs kkr', 'fs investment']),
    ('Golub', ['golub']),
    ('Apollo', ['apollo']),
    ('Goldman Sachs', ['goldman sachs', 'gs ']),
    ('Morgan Stanley', ['morgan stanley']),
    ('Main Street', ['main street']),
    ('Prospect Capital', ['prospect capital']),
    ('Hercules', ['hercules']),
    ('Gladstone', ['gladstone']),
    ('New Mountain', ['new mountain']),
    ('Carlyle', ['carlyle']),
    ('Oaktree', ['oaktree']),
    ('KKR', ['kkr']),
    ('Bain', ['bain']),
    ('TPG', ['tpg']),
    ('Sixth Street', ['sixth street']),
    ('Trinity Capital', ['trinity capital']),
    ('Barings', ['barings']),
    ('BlackRock', ['blackrock']),
    ('Benefit Street', ['benefit street']),
    ('Varagon', ['varagon']),
    ('Monroe Capital', ['monroe capital']),
    ('Crescent Capital', ['crescent capital']),
    ('SLR', ['slr ']),
    ('Saratoga', ['saratoga']),
    ('Nuveen Churchill', ['nuveen churchill', 'churchill']),
    ('Kayne Anderson', ['kayne anderson']),
    ('Pantheon', ['pantheon']),
    ('HPS', ['hps ']),
    ('Cliffwater', ['cliffwater']),
    ('Invesco', ['invesco']),
    ('Fidus', ['fidus']),
    ('Runway Growth', ['runway growth']),
    ('PennantPark', ['pennantpark']),
    ('Horizon Technology', ['horizon technology']),
    ('Owl Rock (standalone)', ['owl rock']),
    ('White Oak', ['white oak']),
]

# Remove duplicate/overlapping patterns - keep one per brand
# The "Owl Rock (standalone)" duplicates Blue Owl / Owl Rock -- remove it
BRAND_PATTERNS = [bp for bp in BRAND_PATTERNS if bp[0] != 'Owl Rock (standalone)']

print("\nBrand groups found in latest quarter data (DL + DE):")
print(f"{'Brand':<30} {'CIKs':>5} {'Positions':>8} {'|FV| ($B)':>10} {'% DL+DE':>8} {'Entities'}")
print("-" * 130)

dl_de_total = con.execute(f"""
    SELECT SUM(ABS(fair_value)) / 1e9 FROM holdings
    WHERE report_date = '{latest_q}' AND index_classification IN ('DIRECT_LENDING', 'DIRECT_EQUITY')
""").fetchone()[0]

brand_results = []
for brand, patterns in BRAND_PATTERNS:
    conditions = " OR ".join([f"LOWER(entity_name) LIKE '%{p}%'" for p in patterns])
    rows = con.execute(f"""
        SELECT
            COUNT(DISTINCT cik) as n_ciks,
            COUNT(*) as positions,
            SUM(ABS(fair_value)) / 1e9 as fv_bn,
            STRING_AGG(DISTINCT entity_name, ' | ' ORDER BY entity_name) as entities
        FROM holdings
        WHERE report_date = '{latest_q}'
          AND index_classification IN ('DIRECT_LENDING', 'DIRECT_EQUITY')
          AND ({conditions})
    """).fetchone()

    if rows[0] and rows[0] > 0 and rows[2] and rows[2] > 0:
        pct = rows[2] / dl_de_total * 100 if dl_de_total else 0
        entities = rows[3] if rows[3] else ''
        if len(entities) > 55:
            entities = entities[:52] + "..."
        brand_results.append((brand, rows[0], rows[1], rows[2], pct, entities))

# Sort by FV descending
brand_results.sort(key=lambda x: -x[3])
for br in brand_results:
    print(f"{br[0]:<30} {br[1]:>5} {br[2]:>8,} {br[3]:>10.2f} {br[4]:>7.1f}% {br[5]}")

# Show detailed CIK breakdown for brands with multiple CIKs
print("\n\nDetailed CIK breakdown for multi-CIK brands:")
print("-" * 110)

for brand, patterns in BRAND_PATTERNS:
    conditions = " OR ".join([f"LOWER(entity_name) LIKE '%{p}%'" for p in patterns])
    cik_count = con.execute(f"""
        SELECT COUNT(DISTINCT cik) FROM holdings
        WHERE report_date = '{latest_q}'
          AND index_classification IN ('DIRECT_LENDING', 'DIRECT_EQUITY', 'PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND')
          AND ({conditions})
    """).fetchone()[0]

    if cik_count and cik_count > 1:
        print(f"\n{brand} ({cik_count} CIKs):")
        rows = con.execute(f"""
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') as cik,
                entity_name,
                COUNT(*) as positions,
                SUM(ABS(fair_value)) / 1e9 as fv_bn,
                STRING_AGG(DISTINCT index_classification, ', ') as indices
            FROM holdings
            WHERE report_date = '{latest_q}'
              AND ({conditions})
            GROUP BY cik, entity_name
            ORDER BY fv_bn DESC
        """).fetchall()
        for r in rows:
            print(f"  CIK {r[0]}  {r[1][:55]:<56} {r[2]:>6} pos  ${r[3]:.3f}B  [{r[4]}]")

# ============================================================
# 3b. Consolidated brand-level top 20 (DL)
# ============================================================
print("\n" + "=" * 80)
print(f"SECTION 3b: TOP 20 BRANDS BY FV IN DIRECT_LENDING (consolidated, quarter: {latest_q})")
print("=" * 80)

# Build a brand mapping SQL CASE statement
case_clauses = []
for brand, patterns in BRAND_PATTERNS:
    conditions = " OR ".join([f"LOWER(entity_name) LIKE '%{p}%'" for p in patterns])
    case_clauses.append(f"WHEN {conditions} THEN '{brand}'")
case_sql = "CASE " + " ".join(case_clauses) + " ELSE entity_name END"

rows = con.execute(f"""
    WITH latest AS (
        SELECT {case_sql} as brand, fair_value, cik
        FROM holdings
        WHERE report_date = '{latest_q}'
          AND index_classification = 'DIRECT_LENDING'
    ),
    total AS (SELECT SUM(ABS(fair_value)) as t FROM latest),
    by_brand AS (
        SELECT
            brand,
            COUNT(DISTINCT cik) as n_ciks,
            COUNT(*) as positions,
            SUM(ABS(fair_value)) / 1e9 as fv_bn
        FROM latest
        GROUP BY brand
    )
    SELECT
        bb.brand,
        bb.n_ciks,
        bb.positions,
        bb.fv_bn,
        bb.fv_bn / t.t * 1e9 * 100 as pct
    FROM by_brand bb, total t
    ORDER BY bb.fv_bn DESC
    LIMIT 20
""").fetchall()

cum = 0
print(f"{'#':>3} {'Brand':<45} {'CIKs':>5} {'Pos':>7} {'FV($B)':>8} {'%Total':>7} {'Cum%':>6}")
print("-" * 85)
for i, r in enumerate(rows, 1):
    cum += r[4]
    print(f"{i:>3} {r[0][:44]:<45} {r[1]:>5} {r[2]:>7,} {r[3]:>8.2f} {r[4]:>6.1f}% {cum:>5.1f}%")

# ============================================================
# 4. PRIVATE_CREDIT_FUND and PRIVATE_EQUITY_FUND top firms
# ============================================================
for index_name in ['PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND']:
    print("\n" + "=" * 80)
    print(f"SECTION 4: TOP FIRMS - {index_name} (quarter: {latest_q})")
    print("=" * 80)

    rows = con.execute(f"""
        WITH latest AS (
            SELECT entity_name, cik, fair_value
            FROM holdings
            WHERE report_date = '{latest_q}'
              AND index_classification = '{index_name}'
        ),
        total AS (SELECT SUM(ABS(fair_value)) as t FROM latest),
        by_firm AS (
            SELECT
                entity_name,
                LPAD(CAST(cik AS VARCHAR), 10, '0') as cik,
                COUNT(*) as positions,
                SUM(ABS(fair_value)) / 1e9 as fv_bn,
                SUM(fair_value) / 1e9 as net_fv_bn
            FROM latest
            GROUP BY entity_name, cik
        )
        SELECT
            bf.entity_name,
            bf.cik,
            bf.positions,
            bf.fv_bn,
            bf.net_fv_bn,
            bf.fv_bn / t.t * 1e9 * 100 as pct
        FROM by_firm bf, total t
        ORDER BY bf.fv_bn DESC
        LIMIT 15
    """).fetchall()

    if not rows:
        print("  No data for this index in this quarter.")
        continue

    cum = 0
    print(f"{'#':>3} {'Entity Name':<55} {'CIK':<12} {'Pos':>5} {'FV($B)':>8} {'%Total':>7}")
    print("-" * 95)
    for i, r in enumerate(rows, 1):
        cum += r[5]
        print(f"{i:>3} {r[0][:54]:<55} {r[1]:<12} {r[2]:>5} {r[3]:>8.3f} {r[5]:>6.1f}%")
    print(f"    Top {len(rows)} cumulative: {cum:.1f}%")

# ============================================================
# 5. Time series: top 5 brands' share of DIRECT_LENDING across quarters
# ============================================================
print("\n" + "=" * 80)
print("SECTION 5: TIME SERIES - TOP 5 BRANDS SHARE OF DIRECT_LENDING (quarterly)")
print("=" * 80)

# Use only true quarter-end dates with significant data
major_quarters = con.execute("""
    SELECT report_date, COUNT(*) as n, SUM(ABS(fair_value))/1e9 as fv
    FROM holdings
    WHERE index_classification = 'DIRECT_LENDING'
      AND EXTRACT(MONTH FROM report_date::DATE) IN (3,6,9,12)
      AND EXTRACT(DAY FROM report_date::DATE) >= 28
    GROUP BY report_date
    HAVING COUNT(*) > 500
    ORDER BY report_date
""").fetchall()
major_q_dates = [r[0] for r in major_quarters]

# Identify top 5 brands by latest major quarter FV
top5_brands = con.execute(f"""
    WITH latest AS (
        SELECT {case_sql} as brand, fair_value
        FROM holdings
        WHERE report_date = '{latest_q}'
          AND index_classification = 'DIRECT_LENDING'
    )
    SELECT brand, SUM(ABS(fair_value)) as fv
    FROM latest
    GROUP BY brand
    ORDER BY fv DESC
    LIMIT 5
""").fetchall()

top5_names = [r[0] for r in top5_brands]
print(f"Top 5 brands (by latest quarter FV): {', '.join(top5_names)}")

# For each major quarter, compute brand shares
print(f"\n{'Quarter':<12}", end="")
for b in top5_names:
    short = b[:14]
    print(f" {short:>14}", end="")
print(f" {'Top5 Tot':>9} {'Index$B':>8} {'Firms':>6}")
print("-" * (12 + 15 * len(top5_names) + 25))

for q in major_q_dates:
    total_fv = con.execute(f"""
        SELECT SUM(ABS(fair_value)) / 1e9 FROM holdings
        WHERE report_date = '{q}' AND index_classification = 'DIRECT_LENDING'
    """).fetchone()[0]

    n_firms = con.execute(f"""
        SELECT COUNT(DISTINCT cik) FROM holdings
        WHERE report_date = '{q}' AND index_classification = 'DIRECT_LENDING'
    """).fetchone()[0]

    if not total_fv or total_fv < 0.1:
        continue

    brand_pcts = []
    print(f"{str(q):<12}", end="")
    for brand in top5_names:
        patterns = None
        for b, p in BRAND_PATTERNS:
            if b == brand:
                patterns = p
                break

        if patterns:
            conditions = " OR ".join([f"LOWER(entity_name) LIKE '%{p}%'" for p in patterns])
            brand_fv = con.execute(f"""
                SELECT COALESCE(SUM(ABS(fair_value)) / 1e9, 0) FROM holdings
                WHERE report_date = '{q}'
                  AND index_classification = 'DIRECT_LENDING'
                  AND ({conditions})
            """).fetchone()[0]
        else:
            brand_fv = con.execute(f"""
                SELECT COALESCE(SUM(ABS(fair_value)) / 1e9, 0) FROM holdings
                WHERE report_date = '{q}'
                  AND index_classification = 'DIRECT_LENDING'
                  AND entity_name = '{brand.replace("'", "''")}'
            """).fetchone()[0]

        pct = brand_fv / total_fv * 100
        brand_pcts.append(pct)
        print(f" {pct:>13.1f}%", end="")

    top5_total = sum(brand_pcts)
    print(f" {top5_total:>8.1f}% {total_fv:>8.1f} {n_firms:>6}")

# ============================================================
# 5b. HHI over time (major quarters only)
# ============================================================
print("\n" + "=" * 80)
print("SECTION 5b: HHI OVER TIME (DIRECT_LENDING, quarterly)")
print("=" * 80)
print("(HHI: <1500 unconcentrated, 1500-2500 moderate, >2500 highly concentrated)")

# Convert list to SQL-friendly
q_list = ",".join([f"'{q}'" for q in major_q_dates])

rows = con.execute(f"""
    WITH by_firm_qtr AS (
        SELECT
            report_date,
            {case_sql} as brand,
            SUM(ABS(fair_value)) as firm_fv
        FROM holdings
        WHERE index_classification = 'DIRECT_LENDING'
          AND report_date IN ({q_list})
        GROUP BY report_date, brand
    ),
    totals AS (
        SELECT report_date, SUM(firm_fv) as total_fv
        FROM by_firm_qtr
        GROUP BY report_date
    ),
    shares AS (
        SELECT
            b.report_date,
            b.brand,
            (b.firm_fv / t.total_fv * 100) as share_pct
        FROM by_firm_qtr b
        JOIN totals t ON b.report_date = t.report_date
    )
    SELECT
        report_date,
        SUM(share_pct * share_pct) as hhi,
        COUNT(*) as n_brands,
        MAX(share_pct) as max_share,
        (SELECT brand FROM shares s2 WHERE s2.report_date = shares.report_date ORDER BY share_pct DESC LIMIT 1) as top_brand
    FROM shares
    GROUP BY report_date
    ORDER BY report_date
""").fetchall()

print(f"\n{'Quarter':<12} {'HHI':>7} {'Brands':>7} {'Max Share':>10} {'Top Brand'}")
print("-" * 70)
for r in rows:
    label = "UNCONC" if r[1] < 1500 else ("MODERATE" if r[1] < 2500 else "HIGH")
    print(f"{str(r[0]):<12} {r[1]:>7.0f} {r[2]:>7} {r[3]:>9.1f}% {r[4][:30] if r[4] else ''} [{label}]")

# ============================================================
# 6. Distribution stats
# ============================================================
print("\n" + "=" * 80)
print(f"SECTION 6: DISTRIBUTION STATISTICS (quarter: {latest_q})")
print("=" * 80)

for idx in ['DIRECT_LENDING', 'DIRECT_EQUITY']:
    stats = con.execute(f"""
        WITH latest AS (
            SELECT {case_sql} as brand, cik, SUM(ABS(fair_value)) / 1e9 as fv
            FROM holdings
            WHERE report_date = '{latest_q}' AND index_classification = '{idx}'
            GROUP BY brand, cik
        ),
        brand_agg AS (
            SELECT brand, SUM(fv) as fv FROM latest GROUP BY brand
        )
        SELECT
            COUNT(*) as firms,
            SUM(fv) as total_fv,
            AVG(fv) as avg_fv,
            MEDIAN(fv) as med_fv,
            MAX(fv) as max_fv,
            MIN(fv) as min_fv,
            STDDEV(fv) as std_fv,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY fv) as p25,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY fv) as p75
        FROM brand_agg
    """).fetchone()
    print(f"\n{idx}:")
    print(f"  Brands/Firms: {stats[0]}")
    print(f"  Total FV: ${stats[1]:.1f}B")
    print(f"  Per-brand distribution ($B): avg={stats[2]:.2f}, median={stats[3]:.3f}, p25={stats[7]:.3f}, p75={stats[8]:.3f}")
    print(f"  Max: ${stats[4]:.2f}B, Min: ${stats[5]:.4f}B, StdDev: ${stats[6]:.2f}B")

# ============================================================
# 7. Source breakdown per brand (BDC vs N-PORT)
# ============================================================
print("\n" + "=" * 80)
print(f"SECTION 7: SOURCE BREAKDOWN FOR TOP BRANDS (quarter: {latest_q})")
print("=" * 80)

rows = con.execute(f"""
    WITH latest AS (
        SELECT
            {case_sql} as brand,
            source,
            fair_value
        FROM holdings
        WHERE report_date = '{latest_q}'
          AND index_classification IN ('DIRECT_LENDING', 'DIRECT_EQUITY')
    ),
    by_brand_source AS (
        SELECT
            brand,
            source,
            COUNT(*) as positions,
            SUM(ABS(fair_value)) / 1e9 as fv_bn
        FROM latest
        GROUP BY brand, source
    ),
    totals AS (
        SELECT brand, SUM(fv_bn) as total_fv FROM by_brand_source GROUP BY brand
    )
    SELECT
        t.brand,
        t.total_fv,
        COALESCE(bdc.positions, 0) as bdc_pos,
        COALESCE(bdc.fv_bn, 0) as bdc_fv,
        COALESCE(nport.positions, 0) as nport_pos,
        COALESCE(nport.fv_bn, 0) as nport_fv
    FROM totals t
    LEFT JOIN by_brand_source bdc ON t.brand = bdc.brand AND bdc.source = 'bdc'
    LEFT JOIN by_brand_source nport ON t.brand = nport.brand AND nport.source = 'nport'
    ORDER BY t.total_fv DESC
    LIMIT 20
""").fetchall()

print(f"{'Brand':<40} {'Total$B':>8} {'BDC pos':>8} {'BDC $B':>8} {'NPORT pos':>9} {'NPORT $B':>9}")
print("-" * 85)
for r in rows:
    print(f"{r[0][:39]:<40} {r[1]:>8.2f} {r[2]:>8,} {r[3]:>8.2f} {r[4]:>9,} {r[5]:>9.2f}")

con.close()
print("\nAnalysis complete.")
