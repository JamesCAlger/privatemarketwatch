"""Bind primary anchors to independent typed fund totals and exact leaf bytes.

An override's directory or narrative dollar sign does not establish currency
or independence. Compare its declared basis with the frozen companyfacts
producer's explicitly USD columns; preserve disagreements in the audit.
"""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from pipeline.programme.core import ContractError, sha


def collect_overrides(con, anchor_dir, financials):
    from pipeline.extract_companyfacts import _BALANCE_SHEET_CONCEPTS, _PORTFOLIO_CONCEPTS
    if (_BALANCE_SHEET_CONCEPTS['investments_at_fair_value']['unit']!='USD' or
        _PORTFOLIO_CONCEPTS['cash_equivalents_at_fair_value']['unit']!='USD'):
        raise ContractError('Independent fund-total currency contract changed')
    financials=Path(financials)
    financial_sha=sha(financials)
    con.execute('CREATE TEMP TABLE anchor_financials AS SELECT * FROM read_csv(?,all_varchar=true)',[str(financials)])
    columns={r[0] for r in con.execute('DESCRIBE anchor_financials').fetchall()}
    cash='cash_equivalents_at_fair_value' if 'cash_equivalents_at_fair_value' in columns else 'NULL'
    records=con.execute("""SELECT lpad(cik,10,'0'),substr(report_date,1,10),
      count(DISTINCT TRY_CAST(investments_at_fair_value AS DECIMAL(38,12))),
      min(TRY_CAST(investments_at_fair_value AS DECIMAL(38,12))),
      count(DISTINCT TRY_CAST("""+cash+""" AS DECIMAL(38,12))),
      min(TRY_CAST("""+cash+""" AS DECIMAL(38,12))) FROM anchor_financials
      WHERE source='companyfacts' GROUP BY 1,2""").fetchall()
    totals={(c,q):(n,v,cn,cv) for c,q,n,v,cn,cv in records}
    result=[]
    for path in sorted(Path(anchor_dir).glob('*/*.json')):
        if path.name.startswith('_') or '.proposed.' in path.name.lower():
            continue
        leaf_sha=sha(path)
        leaf=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(leaf,dict):
            continue
        cik=str(leaf.get('cik',path.parent.name)).zfill(10)
        quarter=str(leaf.get('target_quarter',path.stem))
        basis=leaf.get('basis')
        row=dict(cik=cik,quarter=quarter,leaf_sha256=leaf_sha,leaf_path=str(path),
            currency='',source_evidence=str(path)+'#sha256='+leaf_sha,
            independent_value=None,independent_kind='unverified_override',
            evidence_status='independent_total_unavailable',override_agrees=None)
        n,value,cn,cv=totals.get((cik,quarter),(0,None,0,None))
        ready=n==1 and value is not None
        if basis=='published_rows':
            ready=ready and cn==1 and cv is not None
            target=value+cv if ready else None
            kind='fund_financials_plus_cash'
            expression='investments_at_fair_value+cash_equivalents_at_fair_value'
        elif basis=='investments_ex_cash':
            target=value if ready else None
            kind='fund_financials'
            expression='investments_at_fair_value'
        else:
            ready=False
            target=None
            row['evidence_status']='override_basis_unresolved'
        if ready:
            try:
                claimed=Decimal(str(leaf.get('grand_total')))
                agrees=claimed.is_finite() and claimed==target
            except ArithmeticError:
                agrees=False
            row.update(currency='USD',independent_value=str(target),independent_kind=kind,
                override_agrees=agrees,evidence_status='independent_total_agrees' if agrees else 'override_disagrees_with_independent_total',
                source_evidence=row['source_evidence']+';'+str(financials)+'#sha256='+financial_sha+
                    ';source=companyfacts;cik='+cik+';quarter='+quarter+';expression='+expression)
        elif n>1 or (basis=='published_rows' and cn>1):
            row['evidence_status']='conflicting_independent_totals'
        if sha(path)!=leaf_sha:
            raise ContractError('Anchor leaf changed during evidence collection')
        result.append(row)
    if len({(r['cik'],r['quarter']) for r in result})!=len(result):
        raise ContractError('Multiple override leaves name one fund-quarter')
    if sha(financials)!=financial_sha:
        raise ContractError('Independent financial source changed during evidence collection')
    return result
