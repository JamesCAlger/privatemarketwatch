"""Position-ID defect analysis across pipeline output files."""

import duckdb

con = duckdb.connect()
base = r"C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl/data/output"

unified = f"{base}/private_markets_holdings.csv"
matches = f"{base}/position_matches.csv"
returns = f"{base}/position_returns.csv"

# Register as views
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

results = []


def check(label, desc, query, pass_fn):
    try:
        val = con.execute(query).fetchone()[0]
        passed = pass_fn(val)
        status = "PASS" if passed else "FAIL"
        results.append((label, status, desc, val))
        if isinstance(val, (int, float)):
            print(f"  [{status}] {label}: {desc} => {val:,}")
        else:
            print(f"  [{status}] {label}: {desc} => {val}")
    except Exception as e:
        results.append((label, "ERROR", desc, str(e)))
        print(f"  [ERROR] {label}: {desc} => {e}")


def check_table(label, desc, query):
    try:
        rows = con.execute(query).fetchall()
        cols = [d[0] for d in con.description]
        print(f"  {label}: {desc}")
        if not rows:
            print("    (no rows)")
            return
        # Calculate column widths
        str_rows = [[str(c) for c in row] for row in rows]
        widths = [max(len(h), max(len(r[i]) for r in str_rows)) for i, h in enumerate(cols)]
        header = " | ".join(h.ljust(w) for h, w in zip(cols, widths))
        print(f"    {header}")
        print(f"    {'-+-'.join('-' * w for w in widths)}")
        for row in str_rows:
            line = " | ".join(c.ljust(w) for c, w in zip(row, widths))
            print(f"    {line}")
    except Exception as e:
        print(f"  [ERROR] {label}: {desc} => {e}")


print("=" * 80)
print("POSITION_ID DEFECT ANALYSIS")
print("=" * 80)

# ============================================================
print("\n--- A. COMPLETENESS ---")
# ============================================================

check("A1a", "NULL/empty position_id in unified",
      "SELECT COUNT(*) FROM u WHERE position_id IS NULL OR TRIM(position_id) = ''",
      lambda v: v == 0)

check("A1b", "NULL/empty position_id in matches",
      "SELECT COUNT(*) FROM m WHERE position_id IS NULL OR TRIM(position_id) = ''",
      lambda v: v == 0)

check("A1c", "NULL/empty position_id in returns",
      "SELECT COUNT(*) FROM r WHERE position_id IS NULL OR TRIM(position_id) = ''",
      lambda v: v == 0)

check("A2a", "Unique position_ids in unified",
      "SELECT COUNT(DISTINCT position_id) FROM u WHERE position_id IS NOT NULL",
      lambda v: v > 0)

check("A2b", "Unique position_ids in matches",
      "SELECT COUNT(DISTINCT position_id) FROM m WHERE position_id IS NOT NULL",
      lambda v: v > 0)

check("A2c", "Unique position_ids in returns",
      "SELECT COUNT(DISTINCT position_id) FROM r WHERE position_id IS NOT NULL",
      lambda v: v > 0)

# ============================================================
print("\n--- B. FORMAT ---")
# ============================================================

check("B1a", "Non-POS-NNNNNNNN format in unified",
      r"SELECT COUNT(*) FROM u WHERE position_id IS NOT NULL AND NOT regexp_matches(position_id, '^POS-[0-9]{8}$')",
      lambda v: v == 0)

check("B1b", "Non-POS-NNNNNNNN format in matches",
      r"SELECT COUNT(*) FROM m WHERE position_id IS NOT NULL AND NOT regexp_matches(position_id, '^POS-[0-9]{8}$')",
      lambda v: v == 0)

check("B1c", "Non-POS-NNNNNNNN format in returns",
      r"SELECT COUNT(*) FROM r WHERE position_id IS NOT NULL AND NOT regexp_matches(position_id, '^POS-[0-9]{8}$')",
      lambda v: v == 0)

# ============================================================
print("\n--- C. CHAIN STRUCTURE (unified only) ---")
# ============================================================

check("C1", "Max chain length (max distinct report_dates per position_id)",
      """SELECT MAX(cnt) FROM (
           SELECT position_id, COUNT(DISTINCT report_date) AS cnt
           FROM u WHERE position_id IS NOT NULL
           GROUP BY position_id)""",
      lambda v: v <= 25)

check("C2", "Position_ids with chain > 25 (impossible)",
      """SELECT COUNT(*) FROM (
           SELECT position_id, COUNT(DISTINCT report_date) AS cnt
           FROM u WHERE position_id IS NOT NULL
           GROUP BY position_id
           HAVING cnt > 25)""",
      lambda v: v == 0)

print()
check_table("C3", "Top 10 longest chains",
            """SELECT position_id,
                      COUNT(DISTINCT report_date) AS chain_len,
                      MIN(report_date) AS first_date,
                      MAX(report_date) AS last_date,
                      COUNT(*) AS total_rows
               FROM u WHERE position_id IS NOT NULL
               GROUP BY position_id
               ORDER BY chain_len DESC
               LIMIT 10""")

# ============================================================
print("\n--- D. CROSS-FILE CONSISTENCY ---")
# ============================================================

check("D1", "Position_ids in matches but NOT in unified (orphans)",
      """SELECT COUNT(DISTINCT m.position_id)
         FROM m
         LEFT JOIN (SELECT DISTINCT position_id FROM u) u2 ON m.position_id = u2.position_id
         WHERE u2.position_id IS NULL AND m.position_id IS NOT NULL""",
      lambda v: v == 0)

check("D2", "Position_ids in unified but NOT in matches (singletons - expected)",
      """SELECT COUNT(DISTINCT u.position_id)
         FROM u
         LEFT JOIN (SELECT DISTINCT position_id FROM m) m2 ON u.position_id = m2.position_id
         WHERE m2.position_id IS NULL AND u.position_id IS NOT NULL""",
      lambda v: True)  # singletons are expected

check("D1b", "Position_ids in returns but NOT in unified (orphans)",
      """SELECT COUNT(DISTINCT r.position_id)
         FROM r
         LEFT JOIN (SELECT DISTINCT position_id FROM u) u2 ON r.position_id = u2.position_id
         WHERE u2.position_id IS NULL AND r.position_id IS NOT NULL""",
      lambda v: v == 0)

# D3: orphan breakdown by match_method
orphan_count = con.execute("""
    SELECT COUNT(DISTINCT m.position_id)
    FROM m
    LEFT JOIN (SELECT DISTINCT position_id FROM u) u2 ON m.position_id = u2.position_id
    WHERE u2.position_id IS NULL AND m.position_id IS NOT NULL
""").fetchone()[0]

print()
if orphan_count > 0:
    check_table("D3", "Orphan position_ids by match_method",
                """SELECT m.match_method,
                          COUNT(DISTINCT m.position_id) AS orphan_pids,
                          COUNT(*) AS orphan_rows
                   FROM m
                   LEFT JOIN (SELECT DISTINCT position_id FROM u) u2 ON m.position_id = u2.position_id
                   WHERE u2.position_id IS NULL AND m.position_id IS NOT NULL
                   GROUP BY m.match_method
                   ORDER BY orphan_pids DESC""")
else:
    print("  D3: No orphans found, skipping breakdown.")

# ============================================================
print("\n--- E. ENTITY INTEGRITY ---")
# ============================================================

check("E1", "Position_ids spanning multiple CIKs (should be 0)",
      """SELECT COUNT(*) FROM (
           SELECT position_id, COUNT(DISTINCT cik) AS cik_count
           FROM u WHERE position_id IS NOT NULL
           GROUP BY position_id
           HAVING cik_count > 1)""",
      lambda v: v == 0)

# E2: fan-out analysis
check("E2a", "Position_ids with fan-out (rows > distinct dates for same cik+pid)",
      """SELECT COUNT(*) FROM (
           SELECT cik, position_id, COUNT(*) AS row_count, COUNT(DISTINCT report_date) AS date_count
           FROM u WHERE position_id IS NOT NULL
           GROUP BY cik, position_id
           HAVING row_count > date_count)""",
      lambda v: v == 0)

print()
check_table("E2b", "Top 10 fan-out position_ids",
            """SELECT cik, position_id,
                      COUNT(*) AS row_count,
                      COUNT(DISTINCT report_date) AS date_count,
                      (COUNT(*) - COUNT(DISTINCT report_date)) AS fan_out,
                      MIN(report_date) AS first_date,
                      MAX(report_date) AS last_date
               FROM u WHERE position_id IS NOT NULL
               GROUP BY cik, position_id
               HAVING row_count > date_count
               ORDER BY fan_out DESC
               LIMIT 10""")

# ============================================================
print("\n--- F. DUPLICATE CHECK ---")
# ============================================================

check("F1", "Duplicate (cik, report_date, position_id) combos in unified",
      """SELECT COUNT(*) FROM (
           SELECT cik, report_date, position_id, COUNT(*) AS cnt
           FROM u WHERE position_id IS NOT NULL
           GROUP BY cik, report_date, position_id
           HAVING cnt > 1)""",
      lambda v: v == 0)

dup_count = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT cik, report_date, position_id, COUNT(*) AS cnt
        FROM u WHERE position_id IS NOT NULL
        GROUP BY cik, report_date, position_id
        HAVING cnt > 1)
""").fetchone()[0]

print()
if dup_count > 0:
    check_table("F2", "Example duplicate (cik, report_date, position_id) rows (top 5 combos)",
                """WITH dups AS (
                       SELECT cik, report_date, position_id, COUNT(*) AS cnt
                       FROM u WHERE position_id IS NOT NULL
                       GROUP BY cik, report_date, position_id
                       HAVING cnt > 1
                       ORDER BY cnt DESC
                       LIMIT 5
                   )
                   SELECT u.cik, u.report_date, u.position_id, u.issuer_name,
                          u.fair_value, u.source, u.asset_category
                   FROM u
                   JOIN dups d ON u.cik = d.cik AND u.report_date = d.report_date
                                  AND u.position_id = d.position_id
                   ORDER BY u.cik, u.report_date, u.position_id""")
else:
    print("  F2: No duplicates found.")

# ============================================================
print("\n--- G. SINGLETON ANALYSIS ---")
# ============================================================

check("G1", "Singletons in unified (position_ids appearing exactly once)",
      """SELECT COUNT(*) FROM (
           SELECT position_id, COUNT(*) AS cnt
           FROM u WHERE position_id IS NOT NULL
           GROUP BY position_id
           HAVING cnt = 1)""",
      lambda v: True)  # informational

check("G2", "Singletons in unified that also appear in matches (should be 0 ideally)",
      """SELECT COUNT(*) FROM (
           SELECT position_id FROM u WHERE position_id IS NOT NULL
           GROUP BY position_id HAVING COUNT(*) = 1
       ) singles
       JOIN (SELECT DISTINCT position_id FROM m) m2 ON singles.position_id = m2.position_id""",
      lambda v: v == 0)

# Additional context for G2 if failures
g2_val = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT position_id FROM u WHERE position_id IS NOT NULL
        GROUP BY position_id HAVING COUNT(*) = 1
    ) singles
    JOIN (SELECT DISTINCT position_id FROM m) m2 ON singles.position_id = m2.position_id
""").fetchone()[0]

if g2_val > 0:
    print()
    check_table("G2b", "Sample singleton-in-matches (first 10)",
                """WITH singles AS (
                       SELECT position_id FROM u WHERE position_id IS NOT NULL
                       GROUP BY position_id HAVING COUNT(*) = 1
                   ),
                   in_matches AS (
                       SELECT DISTINCT m.position_id, m.match_method
                       FROM m
                       JOIN singles s ON m.position_id = s.position_id
                   )
                   SELECT im.position_id, im.match_method,
                          u.cik, u.report_date, u.issuer_name, u.source
                   FROM in_matches im
                   JOIN u ON im.position_id = u.position_id
                   ORDER BY im.position_id
                   LIMIT 10""")

# ============================================================
# Extra: match count distribution in matches file per position_id
# ============================================================
print("\n--- H. BONUS: MATCH FILE DISTRIBUTION ---")

check_table("H1", "How many times each position_id appears in matches",
            """SELECT appearances, COUNT(*) AS num_pids
               FROM (
                   SELECT position_id, COUNT(*) AS appearances
                   FROM m WHERE position_id IS NOT NULL
                   GROUP BY position_id
               )
               GROUP BY appearances
               ORDER BY appearances""")

check_table("H2", "Position_ids appearing most in matches (top 10)",
            """SELECT position_id, COUNT(*) AS appearances,
                      COUNT(DISTINCT match_method) AS methods_used,
                      MIN(begin_quarter) AS first_q,
                      MAX(end_quarter) AS last_q
               FROM m WHERE position_id IS NOT NULL
               GROUP BY position_id
               ORDER BY appearances DESC
               LIMIT 10""")

# ============================================================
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

passes = sum(1 for _, s, _, _ in results if s == "PASS")
fails = sum(1 for _, s, _, _ in results if s == "FAIL")
errors = sum(1 for _, s, _, _ in results if s == "ERROR")
print(f"PASS: {passes}  |  FAIL: {fails}  |  ERROR: {errors}  |  TOTAL: {len(results)}")
print()

if fails > 0:
    print("FAILURES:")
    for label, status, desc, val in results:
        if status == "FAIL":
            if isinstance(val, (int, float)):
                print(f"  {label}: {desc} => {val:,}")
            else:
                print(f"  {label}: {desc} => {val}")
    print()

if errors > 0:
    print("ERRORS:")
    for label, status, desc, val in results:
        if status == "ERROR":
            print(f"  {label}: {desc} => {val}")
    print()

if fails == 0 and errors == 0:
    print("All checks passed.")

con.close()
