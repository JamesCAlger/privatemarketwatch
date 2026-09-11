"""Freeze source-backed proposals for 20 legacy review cases; leave gold unchanged."""
import json
from pathlib import Path
from scripts.programme_closeout.candidate import atomic_json,sha
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'

def main():
    packets=json.loads((BASE/'labels/packets.json').read_text())
    assert len(packets)==20
    decisions=[
      ('reference_and_candidate_semantics_wrong','Operating asset-management business equity; neither PE-fund nor credit-fund classification is supported. Leaf rights need review.','/html/body/div[2390]/table/tr[17]',{'cost_usd':1700500000,'fair_value_usd':1903400000,'instrument':'Member interest','asset_role':'operating_company_equity'}),
      ('candidate_semantics_wrong','Co-investment vehicle subordinated certificates; preserve credit-vehicle interest rather than ordinary direct borrower loan.','/html/body/div[2504]/table/tr[20]',{'investment_vehicle':'credit_joint_venture','instrument':'Subordinated certificates'}),
      ('legacy_parent_label_compatible_leaf_supported','Series A preferred stock explicitly printed; candidate preferred leaf supported. PIK coupon describes terms, not current PIK income or distress.','/html/body/div[2402]/table/tr[27]',{'classification':'PREFERRED_EQUITY','pik_terms_rate_pp':10.75,'pik_current_status':'unknown','bad_pik':'unproven'}),
      ('candidate_semantics_wrong','Narrative identifies senior-secured loan JV with pension investor; LP interest is private-credit vehicle exposure.','/html/body/div[1208]/table/tr[15]',{'classification':'PRIVATE_CREDIT_FUND','fair_value_usd':1678745000}),
      ('leaf_unresolved','Class B units pay 7.60% PIK; equity is supported but common versus preferred rights cannot be inferred from units alone.','/html/body/div[1205]/table/tr[20]',{'classification_parent':'DIRECT_EQUITY','leaf':'unresolved','pik_terms_rate_pp':7.6}),
      ('candidate_semantics_wrong','Investee-fund table explicitly says real estate credit and income; common shares are a fund interest, not directly held property.','/html/body/div[1205]/table/tr[26]',{'classification':'REAL_ESTATE_FUND','strategy_evidence_xpath':'/html/body/div[1271]/ix:footnote/table/tr[3]','fair_value_usd':430975000}),
      ('leaf_unresolved','LLC interest is disclosed; operating-company versus pooled-vehicle nature and precise leaf need business/rights evidence.','/html/body/div[1205]/table/tr[27]',{'classification_parent':'DIRECT_EQUITY','leaf':'unresolved'}),
      ('source_present_join_requires_cash_scope','Current Premier class exists with FV/cost 305.986m; do not substitute prior-year 291.131m or other share classes.','/html/body/div[1208]/table/tr[29]',{'classification':'CASH','cost_usd':305986000,'fair_value_usd':305986000}),
      ('legacy_parent_label_compatible_leaf_supported','Current SOI common-equity category supports the common leaf; issuer contains JV but its name alone does not define a fund instrument.','/html/body/div[2331]/table/tr[21]',{'classification':'COMMON_EQUITY'}),
      ('legacy_parent_label_compatible_leaf_supported','Current SOI common-equity category supports the common leaf.','/html/body/div[2331]/table/tr[23]',{'classification':'COMMON_EQUITY'}),
      ('legacy_parent_label_compatible_leaf_supported','Current SOI common-equity category supports the common leaf.','/html/body/div[2331]/table/tr[20]',{'classification':'COMMON_EQUITY'}),
      ('candidate_leaf_not_supported','Current schedule places Denali above Total other equity, separately from common equity. Prior Class A units do not establish current common rights.','/html/body/div[2331]/table/tr[15]',{'classification':'OTHER_EQUITY','leaf_rights':'not established'}),
      ('candidate_semantics_wrong','Narrative describes unitranche loan JV with Capital One; LLC interest is credit-vehicle exposure.','/html/body/div[2115]/table/tr[10]',{'classification':'PRIVATE_CREDIT_FUND','fair_value_usd':416244000}),
      ('reference_scope_and_instrument_wrong','Legacy gold used a JV delayed-draw negative mark for a parent first-lien term position. Source scopes and facilities must differ.',None,{'parent_fair_value_usd':254664000,'parent_cost_usd':255050000,'legacy_jv_fair_value_usd':-188000,'legacy_jv_cost_usd':-190000}),
      ('reference_currency_wrong','Legacy reference copied EUR FV into USD comparison; USD FV 385.453m is source-supported. Currency belongs to each field.',None,{'fair_value_usd':385453000,'legacy_fair_value_eur':328199000}),
      ('reference_identity_alias_and_cost_wrong','Duplicate issuer-only label should map to the same source observation as the instrument label. Prior FV 223.274m was misread as cost.','/html/body/div[1451]/table/tr[20]',{'cost_usd':310978000,'fair_value_usd':344960000,'alias_of_case':16}),
      ('leaf_unresolved_and_cost_reference_wrong','Specialty finance equity supports broad equity; does not by itself establish common rights. Current cost is 310.978m.','/html/body/div[1451]/table/tr[20]',{'cost_usd':310978000,'fair_value_usd':344960000,'leaf':'unresolved'}),
      ('reference_join_scope_ambiguous','Two matches must be separated by physical scope: current SOI equity versus unfunded commitment. Same name is insufficient.','/html/body/div[1451]/table/tr[28]',{'cost_usd':296883000,'fair_value_usd':321093000,'unfunded_table_xpath':'/html/body/ix:continuation[52]/div[1]/table/tr[42]'}),
      ('reference_amounts_wrong_and_identity_join_unresolved','Cited current SOI has cost 137.069m and FV 136.815m; old 304.4m/303.9m values are unsupported by this row.','/html/body/div[1451]/table/tr[17]',{'cost_usd':137069000,'fair_value_usd':136815000}),
      ('reference_cost_wrong_and_alias_supported','Explicit fka alias identifies the LLC; cost 314.808m, FV 280.331m. Legacy cost copied FV.','/html/body/div[1451]/table/tr[23]',{'cost_usd':314808000,'fair_value_usd':280331000,'alias':'Blue Owl Credit Income Senior Loan Fund LLC'})
    ]
    results=[]
    for i,(p,d) in enumerate(zip(packets,decisions)):
        status,reason,xpath,proposal=d
        matches=p['matches'] if xpath is None else [m for m in p['matches'] if m['xpath']==xpath]
        if xpath is not None and not matches:raise ValueError(f'Missing physical review row {i}: {xpath}')
        results.append(dict(case=i,key=p['key'],status=status,reason=reason,proposal=proposal,
            source_path=p['path'],source_sha256=p['source_sha256'],row_xpath=xpath,
            selected_literal_evidence=matches if xpath else [],
            supplementary_evidence='programme_pilot_evidence_2026-09-09/review_case_sources.json' if xpath is None else None,
            narrative_review_packet='labels/packets.json',original_label=p['label'],
            original_comparison=p['flagged_fields'],exposure='development; prior outputs seen; not hold-out',
            promotion_status='proposal_only; original gold unchanged'))
    atomic_json(BASE/'review/legacy_label_decisions.json',results)
    # Source-grounded boundary examples, not independent accuracy gold.
    examples=[dict(id='PIK-ATHENA',case=2,expectation='terms true; current accrual unknown; distress unproven; preferred rate not loan yield'),
      dict(id='PARTIAL-ATHENA',case=2,expectation='02/2022 is acquisition month, not maturity; empty maturity must stay missing'),
      dict(id='ENTITY-OCIC-ALIAS',case=19,expectation='explicit former name supports legal-name alias within the same filer and disclosed LLC interest'),
      dict(id='SCOPE-LSI',case=17,expectation='same issuer does not merge main equity and unfunded commitment into one disclosure observation'),
      dict(id='SCOPE-SENTINEL',case=13,expectation='parent loan and JV delayed draw are separate position scopes'),
      dict(id='FACILITIES-PENN',reference='review/new_development_rosters.json',expectation='same legal company, three distinct term/DD/revolver positions'),
      dict(id='ZERO-CFCO',source_path=packets[6]['path'],source_sha256=packets[6]['source_sha256'],
        row_xpath='/html/body/div[1205]/table/tr[30]',expectation='Explicit printed numeric 0 cost and 0 FV; preserve reported zero, no proxy donor',cost=0,fair_value=0),
      dict(id='CHAIN-ESDEC',reference='programme_reference_evidence_2026-09-09/development_expectations.json#REF-CASE-03',expectation='Three source-selected quarterly observations and two continuation edges; no full-population chain claim')]
    cfco=next(m for m in packets[6]['matches'] if m['xpath']=='/html/body/div[1205]/table/tr[30]')
    examples[6]['literal_evidence']=cfco
    atomic_json(BASE/'review/boundary_examples.json',examples)
    print('20 label dispositions; 8 source-grounded boundary examples; original gold preserved',flush=True)
if __name__=='__main__':main()
