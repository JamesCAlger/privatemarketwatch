"""Detailed follow-up on position_id defect analysis failures."""

import duckdb

con = duckdb.connect()
base = r"C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl/data/output"

unified = f"{base}/private_markets_holdings.csv"
matches = f"{base}/position_matches.csv"
returns = f"{base}/position_returns.csv"

con.execute(f"""
    CREATE VIEW u AS SELECT * FROM read_csv_auto('{unified}',
        sample_size=10000, types={{'position_id': 'VARCHAR', 'cik': 'VARCHAR', 'report_date': 'VARCHAR'}})
""")
con.execute(f"""
    CREATE VIEW m AS SELECT * FROM read_csv_auto('{matches}',
        sample_size=10000, types={{'position_id': 'VARCHAR', 'cik': 'VARCHAR'}})
""")
con.execute(f"""
    CREATE VIEW r AS SELECT * FROM read_csv_auto('{returns}',
        sample_size=10000, types={{'position_id': 'VARCHAR', 'cik': 'VARCHAR'}})
""")


def show(title, query):
    print(f"\n{'='*80}")
    print(title)
    print("=" * 80)
    rows = con.execute(query).fetchall()
    cols = [d[0] for d in con.description]
    if not rows:
        print("  (no rows)")
        return
    str_rows = [[str(c) for c in row] for row in rows]
    widths = [max(len(h), max(len(r[i]) for r in str_rows)) for i, h in enumerate(cols)]
    # Cap widths for readability
    widths = [min(w, 60) for w in widths]
    header = " | ".join(h.ljust(w)[:w] for h, w in zip(cols, widths))
    print(f"  {header}")
    print(f"  {'-+-'.join('-' * w for w in widths)}")
    for row in str_rows:
        line = " | ".join(c.ljust(w)[:w] for c, w in zip(row, widths))
        print(f"  {line}")


# ============================================================
# FAIL A1b/A1c: 22,965 NULL position_ids in matches/returns
# ============================================================

show("A1b DETAIL: NULL position_id in matches -- breakdown by match_method",
     """SELECT match_method, COUNT(*) AS null_pid_rows,
             COUNT(DISTINCT cik) AS ciks,
             MIN(begin_quarter) AS first_q,
             MAX(end_quarter) AS last_q
        FROM m
        WHERE position_id IS NULL OR TRIM(position_id) = ''
        GROUP BY match_method
        ORDER BY null_pid_rows DESC""")

show("A1b DETAIL: NULL position_id in matches -- breakdown by source",
     """SELECT source, COUNT(*) AS null_pid_rows,
             COUNT(DISTINCT cik) AS ciks
        FROM m
        WHERE position_id IS NULL OR TRIM(position_id) = ''
        GROUP BY source
        ORDER BY null_pid_rows DESC""")

show("A1b DETAIL: NULL position_id sample rows (10)",
     """SELECT cik, entity_name, source, match_method, begin_quarter, end_quarter,
             begin_issuer_name, begin_fair_value, position_id
        FROM m
        WHERE position_id IS NULL OR TRIM(position_id) = ''
        LIMIT 10""")

# ============================================================
# FAIL E2a/F1: Fan-out -- 114 pids with rows > dates
# ============================================================

show("E2a DETAIL: Fan-out by CIK (which filers have the problem)",
     """SELECT cik, COUNT(*) AS fanout_pids,
             SUM(row_count - date_count) AS total_excess_rows
        FROM (
            SELECT cik, position_id, COUNT(*) AS row_count, COUNT(DISTINCT report_date) AS date_count
            FROM u WHERE position_id IS NOT NULL
            GROUP BY cik, position_id
            HAVING row_count > date_count
        )
        GROUP BY cik
        ORDER BY total_excess_rows DESC""")

# Deep dive into worst case: POS-00059432
show("E2a DETAIL: POS-00059432 -- all rows (worst fan-out pid)",
     """SELECT report_date, issuer_name, fair_value, cost, principal_amount,
             interest_rate, bdc_investment_identifier
        FROM u
        WHERE position_id = 'POS-00059432'
        ORDER BY report_date, fair_value""")

show("E2a DETAIL: POS-00059432 -- rows per report_date",
     """SELECT report_date, COUNT(*) AS rows, COUNT(DISTINCT fair_value) AS distinct_fvs,
             MIN(fair_value) AS min_fv, MAX(fair_value) AS max_fv,
             COUNT(DISTINCT bdc_investment_identifier) AS distinct_ids
        FROM u
        WHERE position_id = 'POS-00059432'
        GROUP BY report_date
        ORDER BY report_date""")

# Check if these are actually different underlying investments with the same canonical_name
show("E2a DETAIL: POS-00059432 -- distinct entity_id and canonical_name",
     """SELECT DISTINCT entity_id, canonical_name, issuer_name
        FROM u
        WHERE position_id = 'POS-00059432'""")

# Check a second fan-out pid
show("E2a DETAIL: POS-00071230 -- rows per report_date",
     """SELECT report_date, COUNT(*) AS rows, COUNT(DISTINCT fair_value) AS distinct_fvs,
             MIN(fair_value) AS min_fv, MAX(fair_value) AS max_fv
        FROM u
        WHERE position_id = 'POS-00071230'
        GROUP BY report_date
        ORDER BY report_date""")

show("E2a DETAIL: POS-00071230 -- sample rows showing identifier differences",
     """SELECT report_date, issuer_name, fair_value, bdc_investment_identifier
        FROM u
        WHERE position_id = 'POS-00071230' AND report_date = '2024-12-31'
        ORDER BY fair_value""")

# ============================================================
# FAIL G2: 47,001 singletons in unified that appear in matches
# ============================================================

show("G2 DETAIL: Singleton-in-matches breakdown by match_method",
     """WITH singles AS (
            SELECT position_id FROM u WHERE position_id IS NOT NULL
            GROUP BY position_id HAVING COUNT(*) = 1
        )
        SELECT m.match_method, COUNT(DISTINCT m.position_id) AS singleton_pids
        FROM m
        JOIN singles s ON m.position_id = s.position_id
        GROUP BY m.match_method
        ORDER BY singleton_pids DESC""")

show("G2 DETAIL: Do singletons appear as begin or end side in matches?",
     """WITH singles AS (
            SELECT position_id, MIN(report_date) AS the_date FROM u WHERE position_id IS NOT NULL
            GROUP BY position_id HAVING COUNT(*) = 1
        ),
        matched AS (
            SELECT m.position_id, m.begin_report_date, m.end_report_date, s.the_date
            FROM m
            JOIN singles s ON m.position_id = s.position_id
        )
        SELECT
            CASE
                WHEN the_date = begin_report_date AND the_date = end_report_date THEN 'both'
                WHEN the_date = begin_report_date THEN 'begin_only'
                WHEN the_date = end_report_date THEN 'end_only'
                ELSE 'neither'
            END AS role,
            COUNT(*) AS rows
        FROM matched
        GROUP BY role
        ORDER BY rows DESC""")

show("G2 DETAIL: How many singleton pids are in matches >1 time?",
     """WITH singles AS (
            SELECT position_id FROM u WHERE position_id IS NOT NULL
            GROUP BY position_id HAVING COUNT(*) = 1
        ),
        match_counts AS (
            SELECT m.position_id, COUNT(*) AS appearances
            FROM m
            JOIN singles s ON m.position_id = s.position_id
            GROUP BY m.position_id
        )
        SELECT appearances, COUNT(*) AS num_pids
        FROM match_counts
        GROUP BY appearances
        ORDER BY appearances""")

# Key question: are the 47K singletons actually begin-of-chain or end-of-chain positions?
show("G2 DETAIL: Singleton sample -- are they chain endpoints?",
     """WITH singles AS (
            SELECT position_id, MIN(report_date) AS the_date
            FROM u WHERE position_id IS NOT NULL
            GROUP BY position_id HAVING COUNT(*) = 1
        )
        SELECT s.position_id, s.the_date, u.cik, u.issuer_name, u.source,
               m.match_method, m.begin_report_date, m.end_report_date,
               m.begin_issuer_name, m.end_issuer_name
        FROM singles s
        JOIN u ON s.position_id = u.position_id
        JOIN m ON s.position_id = m.position_id
        LIMIT 15""")

# ============================================================
# Summary statistics
# ============================================================

show("OVERALL: Row counts and position_id coverage",
     """SELECT 'unified' AS file, COUNT(*) AS total_rows,
             SUM(CASE WHEN position_id IS NOT NULL AND TRIM(position_id) != '' THEN 1 ELSE 0 END) AS has_pid,
             COUNT(DISTINCT position_id) AS unique_pids
        FROM u
        UNION ALL
        SELECT 'matches', COUNT(*),
             SUM(CASE WHEN position_id IS NOT NULL AND TRIM(position_id) != '' THEN 1 ELSE 0 END),
             COUNT(DISTINCT position_id)
        FROM m
        UNION ALL
        SELECT 'returns', COUNT(*),
             SUM(CASE WHEN position_id IS NOT NULL AND TRIM(position_id) != '' THEN 1 ELSE 0 END),
             COUNT(DISTINCT position_id)
        FROM r""")

show("OVERALL: Matches NULL pid vs total by index_classification",
     """SELECT index_classification,
             COUNT(*) AS total,
             SUM(CASE WHEN position_id IS NULL OR TRIM(position_id) = '' THEN 1 ELSE 0 END) AS null_pid,
             ROUND(100.0 * SUM(CASE WHEN position_id IS NULL OR TRIM(position_id) = '' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_null
        FROM m
        GROUP BY index_classification
        ORDER BY total DESC""")

con.close()
