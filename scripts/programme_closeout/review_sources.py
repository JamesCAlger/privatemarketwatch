"""Materialize explicit development review decisions; never promote gold labels."""
import csv,json,os,threading
from collections import Counter
from pathlib import Path
from scripts.programme_closeout.candidate import atomic_json,sha
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'
PILOT=ROOT/'docs/production_stack/programme_pilot_evidence_2026-09-09'

# Literal amounts below are review pointers, not automatically certified bridges.
NOTES={
 '1508655':'SOI/financial anchor 3,088,987,000; net presentation 3,036,338,000 is a different basis.',
 '1572694':'Primary candidate 3,438,696,000; lot roster and scope bridge still require certification.',
 '1588272':'Industry/category and affiliation totals repeat the main schedule; do not create extra lots.',
 '1634452':'Separate unfunded schedules repeat facilities with different measures; do not double count.',
 '1646614':'Separate cash and affiliated roll-forwards require explicit scope bridges; missing early primary remains unavailable.',
 '1674760':'Investments 485,603,000, MMF 46,467,000, combined 532,070,000; preserve cash basis.',
 '1715933':'Current literal SOI FV 1,155,866,700 in table[30]/tr[16]; comparative 977,829,415 is separate.',
 '1743415':'March primary 524,126,000; June SOI total 522,469,000, not partial affiliation balance 509,719,000.',
 '1792509':'Main SOI has separate origination lots and category subtotals; September 2023 derivatives affect the combined basis.',
 '1837532':'June 2025 investments 19,896,145,000; with cash 20,682,078,000. Printed cost/FV columns require checking against tags.',
 '1859919':'Primary candidate 2,271,398,000; complete lot and consolidation review outstanding.',
 '1860424':'526,177,088 candidate is noncontrolled/nonaffiliated; cannot presume it is the whole portfolio.',
 '1872371':'June 2024 combined FV 4,614,434,000; 4,596,251,000 is cost despite FV tagging. Affiliation subset is not primary.',
 '1885968':'Investments 2,058,550,000 plus cash 51,846,000 = 2,110,396,000 FV; 2,142,616,000 is cost.',
 '1899017':'June complete two-equity development roster; September candidate repeats affiliation evidence. March pre-investment disposition retained.',
 '1902649':'March 2026 investments 2,354,502,240 vs combined cash basis 2,631,922,582.',
 '1905824':'Noncontrolled balances are only candidate anchors; establish whole-portfolio scope before B3 scoring.',
 '1913724':'March 2023 primary candidate 884,633,000; affiliate duplication requires lot review.',
 '1916099':'March 2024 primary candidate 167,278,000; December primary unavailable.',
 '1918712':'Balance 2,577,558,000 vs SOI 2,577,558,100: review source rounding, do not force equality.',
 '1919369':'December 2024 combined FV 539,909,000 vs cost 537,454,000; September 2025 FV 1,185,955,000 vs cost 1,182,918,000.',
 '1920145':'Investments 15,674,510,000; total assets 15,950,297,000 and investment liabilities are separate bases.',
 '1920453':'Primary candidates 531,466,625 (Dec 2023), 2,487,588,823 (Mar 2026); whole roster not certified.',
 '1930087':'Complete named money-market holding, 650,323,000; cash-only does not mean no source positions.',
 '1948368':'June 2023 investments 42,023,000 plus MMF 49,067,000; five original candidates omit literal positions. September 2024 cash 150,000 separate.',
 '1950803':'June 2023 primary candidate 193,103,033; commenced April 3, so eligible.',
 '1950976':'Complete untagged four-lot schedule, signed FV 52,566,000; three Penn facilities must remain distinct.',
 '2006758':'December 2023 is comparative evidence in a later document: retain report-date selection. Missing March primary is not an empty portfolio.',
 '2008748':'September 2024 complete 33-lot development roster; six untagged FV dashes remain unresolved. June 2024 literal portfolio 228,062,000 despite only one tagged candidate.',
}

def write_csv(path,rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    
    out=BASE/'review';out.mkdir(exist_ok=True)
    index=json.loads((BASE/'packets/index.json').read_text());totals={r['reference_id']:r for r in csv.DictReader((PILOT/'pilot_candidate_totals.csv').open())}
    records=[]
    complete={'REF-0001899017-2023-06-30','REF-0002008748-2024-09-30','REF-0001930087-2023-06-30','REF-0001950976-2023-12-31'}
    for item in index:
        ref=item['reference_id'];cik=str(int(ref.split('-')[1]));date=ref[-10:]
        path=BASE/'primary'/f'{ref}.json';primary=json.loads(path.read_text())
        missing=item['source_status']=='no_primary_html_candidate'
        state='primary_source_unavailable' if missing else ('complete_development_roster' if ref in complete else 'source_packet_reviewed_roster_not_certified')
        if ref=='REF-0001899017-2023-03-31':state='pre_investment_evidenced'
        note=NOTES.get(cik,'Primary source missing from allowed cache; cannot certify absence, fields, lots or accounting basis.')
        records.append(dict(reference_id=ref,cik=cik,report_date=date,disposition=state,
            evidence_path=str(path.relative_to(ROOT)),evidence_sha256=sha(path),
            source_candidate_rows=item['source_rows'],saved_candidate_rows=totals[ref]['candidate_rows'],
            anchor_status='development_basis_only' if ref in complete else 'unavailable' if missing else 'candidate_not_basis_certified',
            held_out=False,review_note=note,
            next_action='none_for_development_roster' if ref in complete else 'obtain_primary_under_separate_authority' if missing else 'review_full_lot_boundaries_and_primary_scope',
            acceptance_eligible=False))
    write_csv(out/'packet_dispositions.csv',records)
    n=json.loads((BASE/'literal/roster_1950976_20231231.json').read_text())
    g=json.loads((BASE/'literal/roster_1930087_20230630.json').read_text())
    prefix='/html/body/document/type/sequence/filename/description/text/center[109]/div/table[1]/tr'
    lots=[dict(key=prefix+'[4]',issuer='Penn TRGRP Holdings, LLC',instrument='First lien term loan',principal=25225000,cost=24737000,fair_value=24720000,rate_all_in_pp=13.098,maturity='2030-09-27'),
          dict(key=prefix+'[5]',issuer='Penn TRGRP Holdings, LLC',instrument='First lien delayed draw term loan',principal=294000,cost=294000,fair_value=264000,rate_all_in_pp=12.098,maturity='2030-09-27'),
          dict(key=prefix+'[6]',issuer='Penn TRGRP Holdings, LLC',instrument='First lien revolver',principal=None,principal_state='printed_dash_unresolved',cost=-75000,fair_value=-78000,rate_all_in_pp=None,maturity='2030-09-27'),
          dict(key=prefix+'[7]',issuer='Serrano Parent, LLC',instrument='First lien term loan',principal=28297000,cost=27672000,fair_value=27660000,rate_all_in_pp=11.880,maturity='2030-05-12')]
    golub=[dict(key='/html/body/div[71]/table/tr[4]',issuer='Morgan Stanley Institutional Liquidity Funds',instrument='Treasury Portfolio',cusip='61747C582',cost=650323000,fair_value=650323000,yield_pp=5.0,classification='CASH',scope='named_cash_instrument')]
    rosters=[]
    for doc,rows,total in ((n,lots,52566000),(g,golub,650323000)):
        assert sum(r['fair_value'] for r in rows)==total
        assert sha(ROOT/doc['source_path'])==doc['source_sha256']
        physical={r['xpath']:r for r in doc['rows']}
        for r in rows:
            assert r['key'] in physical
            r['literal_cells']=physical[r['key']]['cells'];r['rounding_bound_usd']=500
        rosters.append(dict(reference_id=doc['reference_id'],source_path=doc['source_path'],source_sha256=doc['source_sha256'],
            display_scale=1000,currency='USD',source_headers=doc['tables'],complete_schedule=True,
            total_fv=total,rows=rows,reviewer='Codex source review 2026-09-09',exposure='development; not independent hold-out',
            missingness_policy='Printed dash remains unresolved, never automatically zero.'))
    atomic_json(out/'new_development_rosters.json',rosters)
    atomic_json(out/'source_review_summary.json',dict(packets=len(records),dispositions=dict(Counter(r['disposition'] for r in records)),
        complete_development_rosters=4,new_roster_rows=5,held_out_rosters=0,
        cohort_source_accuracy='NOT_ASSESSABLE',unknown_FV_dashes=6,
        unresolved_dash_action='Obtain explicit convention/source evidence; preserve unresolved and fail assessability meanwhile. No guessed numeric value.',
        primary_scope_coverage='Not yet certified across cohort; packet review is not a portfolio accuracy claim.'))
    print(json.dumps(dict(packets=len(records),states=dict(Counter(r['disposition'] for r in records)),new_rosters=2)),flush=True);
if __name__=='__main__':main()
