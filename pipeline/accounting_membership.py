"""Release-bound anchor membership, separate from public holdings membership."""
from pipeline.programme.core import ContractError


def build(con, *, release_id, holdings, anchors):
    """Materialize accounting_membership and accounting_anchor_summaries.

    No holdings are removed or rewritten. Parent investment anchors exclude
    underlying schedules and cash; published_rows anchors declare the whole
    retained population. A missing source, unsupported basis or currency
    mismatch stays explicit. A comparison to the public total is valid only
    when every public row belongs to the anchor on that same basis.
    """
    if not release_id:
        raise ContractError('Accounting membership requires a release identity')
    con.execute('CREATE TEMP TABLE membership_holdings AS SELECT * FROM read_csv(?,all_varchar=true)',[str(holdings)])
    con.execute('CREATE TEMP TABLE membership_anchors AS SELECT * FROM read_csv(?,all_varchar=true)',[str(anchors)])
    columns={r[0] for r in con.execute('DESCRIBE membership_holdings').fetchall()}
    required={'row_id','cik','report_date','accounting_scope_id','accounting_record_class',
              'fair_value','fair_value_currency','index_classification'}
    if required-columns:
        raise ContractError('Missing accounting membership columns: '+repr(sorted(required-columns)))
    if con.execute("""SELECT count(*) FROM (
      SELECT row_id FROM membership_holdings GROUP BY row_id
      HAVING count(*)>1 OR nullif(trim(row_id),'') IS NULL)""").fetchone()[0]:
        raise ContractError('Accounting membership requires unique observation identities')
    if con.execute("""SELECT count(*) FROM (
      SELECT lpad(cik,10,'0'),quarter FROM membership_anchors GROUP BY 1,2 HAVING count(*)>1)""").fetchone()[0]:
        raise ContractError('Accounting membership requires one primary anchor per fund-quarter')
    con.execute("""CREATE TEMP TABLE accounting_membership AS WITH joined AS (
      SELECT ? AS release_id,
        'anchor:'||sha256(CAST(to_json(struct_pack(cik:=lpad(a.cik,10,'0'),quarter:=a.quarter,
          basis:=a.anchor_basis,kind:=a.anchor_kind,
          sources:=list_sort(regexp_extract_all(a.source_evidence,'sha256=([a-f0-9]{64})',1)))) AS VARCHAR)) AS anchor_id,
        h.row_id,lpad(h.cik,10,'0') AS cik,substr(h.report_date,1,10) AS report_date,
        h.accounting_scope_id,h.accounting_record_class,
        a.anchor_basis,a.currency AS anchor_currency,a.quarter AS anchor_date,a.source_evidence,
        h.fair_value_currency,h.index_classification,TRY_CAST(h.fair_value AS DECIMAL(38,12)) AS fair_value,
        CASE
          WHEN coalesce(a.anchor_kind,'') NOT IN ('verified_override','fund_financials','fund_financials_plus_cash','companyfacts_concept')
            OR nullif(a.source_evidence,'') IS NULL THEN 'anchor_evidence_unavailable'
          WHEN coalesce(a.anchor_basis,'') NOT IN ('published_rows','investments_ex_cash') THEN 'anchor_basis_unresolved'
          WHEN a.anchor_basis='investments_ex_cash' AND h.accounting_record_class IN
            ('underlying_schedule','unresolved_underlying_schedule') THEN 'outside_parent_anchor'
          WHEN a.anchor_basis='investments_ex_cash' AND h.index_classification='CASH' THEN 'outside_investments_anchor'
          WHEN nullif(h.accounting_scope_id,'') IS NULL OR coalesce(h.accounting_record_class,'') NOT IN
            ('parent_schedule','underlying_schedule','unresolved_underlying_schedule') THEN 'holding_scope_unresolved'
          WHEN nullif(a.currency,'') IS NULL OR h.fair_value_currency IS DISTINCT FROM a.currency
            THEN 'currency_not_comparable'
          WHEN TRY_CAST(h.fair_value AS DECIMAL(38,12)) IS NULL THEN 'holding_value_unavailable'
          ELSE 'declared_anchor_population' END AS reason
      FROM membership_holdings h JOIN membership_anchors a ON lpad(h.cik,10,'0')=lpad(a.cik,10,'0')
        AND substr(h.report_date,1,10)=a.quarter)
      SELECT release_id,anchor_id,row_id,cik,report_date,accounting_scope_id,
        CASE WHEN reason='declared_anchor_population' THEN 'included'
             WHEN reason IN ('outside_parent_anchor','outside_investments_anchor') THEN 'excluded'
             ELSE 'unknown' END AS membership,reason,anchor_basis,anchor_currency,anchor_date,
        source_evidence,fair_value FROM joined ORDER BY anchor_id,row_id""",[release_id])
    con.execute("""CREATE TEMP TABLE accounting_anchor_summaries AS SELECT release_id,anchor_id,cik,
      anchor_date,anchor_basis,anchor_currency,count(*) AS retained_rows,
      count(*) FILTER(WHERE membership='included') AS included_rows,
      count(*) FILTER(WHERE membership='excluded') AS excluded_rows,
      count(*) FILTER(WHERE membership='unknown') AS unknown_rows,
      sum(fair_value) AS retained_fair_value,
      sum(fair_value) FILTER(WHERE membership='included') AS included_fair_value,
      sum(fair_value) FILTER(WHERE membership='excluded') AS excluded_fair_value,
      sum(abs(fair_value)) FILTER(WHERE membership='unknown') AS unknown_absolute_fair_value
      FROM accounting_membership GROUP BY ALL ORDER BY anchor_id""")
