"""Score synchronized identities on exposed regression packets; never call them hold-out."""
import argparse,csv,json,os,threading,time
from pathlib import Path
from collections import Counter
import duckdb,pandas as pd
from pipeline.match_verdict_leaf import validate_match_verdict
from scripts.programme_closeout.candidate import atomic_json,sha,read_bundle
from scripts.programme_closeout.identity import allocate,apply_decisions
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);a=p.parse_args()
    candidate=a.candidate.resolve();attempt=candidate/'attempts/identity-02';bundle=attempt/'bundle'
    inputs=json.loads((attempt/'inputs.json').read_text());read_bundle(bundle,inputs['fingerprint'])
    out=BASE/'identity';out.mkdir(exist_ok=True)
    timer=threading.Timer(600,lambda:os._exit(124));timer.daemon=True;timer.start();start=time.monotonic()
    gold=ROOT/'data/output/match_quality/gold/mg3';work=list(csv.DictReader((gold/'worklist.csv').open()))
    assert len(work)<=600
    pairs=[];entities=[];packets=[];manifest=[];invalid=[];ids=set()
    for w in work:
        pid=w['packet_id'];loaded=[]
        for directory in ('packets','packets_meta','verdicts'):
            path=gold/directory/(pid+'.json')
            if not path.exists():invalid.append(dict(packet=pid,error='missing_'+directory));break
            loaded.append(json.loads(path.read_text(encoding='utf-8-sig')))
            manifest.append(dict(path=str(path.relative_to(ROOT)),sha256=sha(path)))
        if len(loaded)!=3:continue
        packet,meta,verdict=loaded
        errors=validate_match_verdict(verdict,expected_edges=[e['edge_index'] for e in packet.get('edges',[])])
        if verdict.get('packet_id')!=pid or packet.get('packet_id')!=pid:errors.append('packet identity mismatch')
        if errors:invalid.append(dict(packet=pid,errors=errors));continue
        packetrows=packet.get('rows',[])+packet.get('candidate_rows',[]);dates={r.get('row_id'):r.get('report_date','') for r in packetrows}
        ids.update(r['row_id'] for r in packetrows if r.get('row_id'))
        scope=all('2023-03-31'<=r.get('report_date','')<='2026-03-31' for r in packet.get('rows',[]))
        base=dict(packet=pid,stratum=meta.get('stratum'),verdict=verdict['verdict'],required_period_scope=scope)
        if packet['packet_type']=='entity':
            entities.append(dict(base,row_ids=[r.get('row_id') for r in packet.get('rows',[])]))
        edges={e['edge_index']:e for e in packet.get('edges',[])}
        for ev in verdict.get('edge_verdicts',[]):
            edge=edges[ev['edge_index']]
            pairs.append(dict(base,row_a=edge.get('begin_row_id'),row_b=edge.get('end_row_id'),expected=ev['verdict'],kind='position',label_role='observed_edge'))
        for pl in verdict.get('proposed_links',[]) or []:
            pairs.append(dict(base,row_a=pl.get('row_id_a'),row_b=pl.get('row_id_b'),expected='CONFIRMED',kind='entity' if packet['packet_type']=='entity' else 'position',label_role='proposed_continuation'))
        packets.append(dict(base,packet_type=packet['packet_type'],rows=len(packet.get('rows',[])),evidence_entries=len(verdict.get('evidence',[]))))
    assert len(ids)<=10000 and len(pairs)<=10000
    con=duckdb.connect();con.execute('SET threads=2');con.execute("SET memory_limit='3GB'")
    path=bundle/'private_markets_holdings.parquet'
    con.execute("CREATE VIEW h AS SELECT * FROM read_parquet('"+str(path).replace("'","''")+"')")
    selected=con.execute('SELECT row_id,cik,report_date,issuer_name,position_id,entity_id,position_key,fair_value,src_context_id,accession_number FROM h WHERE row_id IN (SELECT unnest(?))',[sorted(ids)]).df().fillna('')
    counts=selected.row_id.value_counts();lookup={r['row_id']:r for r in selected.to_dict('records') if counts[r['row_id']]==1}
    selected.to_csv(out/'reference_row_joins.csv',index=False)
    scored=[]
    for pair in pairs:
        left,right=lookup.get(pair['row_a']),lookup.get(pair['row_b'])
        status='unknown';same=None
        if not pair['required_period_scope']:status='outside_required_period'
        elif not left or not right:status='missing_or_ambiguous_source_row'
        elif pair['expected']=='UNCERTAIN':status='uncertain_reference'
        else:
            key='entity_id' if pair['kind']=='entity' else 'position_id'
            if not left[key] or not right[key]:status='unresolved_candidate_identity'
            else:
                same=left[key]==right[key]
                status='correct' if same==(pair['expected']=='CONFIRMED') else 'missed_same_identity' if pair['expected']=='CONFIRMED' else 'false_merge'
        scored.append(dict(pair,status=status,same_candidate_identity=same))
    entity_results=[]
    for entity in entities:
        rows=[lookup.get(rid) for rid in entity['row_ids']];valid=all(r and r.get('entity_id') for r in rows)
        same=len({r['entity_id'] for r in rows if r})==1 if valid else None
        if not entity['required_period_scope']:status='outside_required_period'
        elif not valid:status='missing_or_ambiguous_or_unresolved_row'
        elif entity['verdict']=='CONFIRMED':status='correct' if same else 'false_split'
        elif entity['verdict']=='WRONG_MERGE':status='false_merge' if same else 'negative_cluster_separated'
        else:status='requires_explicit_pair_adjudication'
        entity_results.append(dict(entity,status=status,candidate_all_same=same,
            limit='Separating a negative multi-entity cluster does not prove every member assigned to the correct company.'))
    pd.DataFrame(scored).to_csv(out/'position_and_proposed_pairs.csv',index=False)
    atomic_json(out/'entity_packet_results.json',entity_results);atomic_json(out/'packet_census.json',packets);atomic_json(out/'invalid_or_missing.json',invalid)
    # Source-reviewed Esdec subchain becomes an explicit durable migration example.
    esdec=['ROW-0664161909bb3724','ROW-bd31b65d09a871db','ROW-bfda4a43b00ac214']
    source_ref='programme_reference_evidence_2026-09-09/development_expectations.json#REF-CASE-03'
    creation=dict(decision_id='DEV-ESDEC-SOURCE-CONTINUATION-20260909',action='create',kind='position',scope='filer:0001837532/parent',evidence=[source_ref])
    durable=allocate('position',creation['decision_id'],creation['scope'])
    assignment=dict(decision_id='DEV-ESDEC-THREE-OBSERVATIONS',action='assign',kind='position',scope=creation['scope'],evidence=[source_ref],identity_id=durable,anchors=esdec)
    registry=apply_decisions({},[creation,assignment]);restored=apply_decisions(json.loads(json.dumps(registry)),[creation,assignment])
    assert registry==restored
    mapping=[dict(row_id=rid,old_snapshot=inputs['fingerprint'],old_position_id=lookup.get(rid,{}).get('position_id'),durable_position_id=durable) for rid in esdec]
    atomic_json(out/'durable_identity_example.json',dict(registry=registry,mapping=mapping,replay_idempotent=True,
        role='Source-reviewed migration example only; no persistent production IDs allocated. Existing pid aliases always include snapshot identity.',
        source_subchain_scope='Three reviewed observations. Other candidate chain members are not certified by this example.'))
    identity_checks=con.execute('''SELECT count(*) n_rows,count(*) filter(where nullif(position_id,'') IS NULL) missing_position_id,
      count(*) filter(where nullif(entity_id,'') IS NULL) missing_entity_id,count(distinct position_id) position_ids,count(distinct entity_id) entity_ids FROM h''').df()
    identity_checks.to_csv(out/'identity_population.csv',index=False)
    duplicate=con.execute('''SELECT position_id,report_date,count(*) n_rows,count(distinct cik) funds FROM h WHERE nullif(position_id,'') IS NOT NULL GROUP BY ALL HAVING count(*)>1''').df()
    duplicate.to_csv(out/'same_period_position_collisions.csv',index=False)
    con.close()
    atomic_json(out/'input_manifest.json',dict(candidate_result_sha256=sha(bundle/'result.json'),holdings_sha256=sha(path),
        reference_files=manifest,validator_sha256=sha(ROOT/'pipeline/match_verdict_leaf.py'),evaluator_sha256=sha(Path(__file__))))
    atomic_json(out/'summary.json',dict(worklist_packets=len(work),valid_packets=len(packets),invalid_or_missing=len(invalid),
        packet_types=dict(Counter(p['packet_type'] for p in packets)),reference_unique_row_ids=len(ids),uniquely_joined_rows=len(lookup),
        pair_outcomes=dict(Counter(r['status'] for r in scored)),pair_kinds=dict(Counter(r['kind'] for r in scored)),
        entity_outcomes=dict(Counter(r['status'] for r in entity_results)),same_period_pid_collision_groups=len(duplicate),
        exposure='mg3 was used to develop/tune matching; regression only, not new hold-out or unbiased cohort precision/recall.',
        legal_entity_limit='Legacy benchmark legal-entity wording and group/name inference require governance review; no full source census.',
        full_chain_completeness='UNASSESSABLE: observed edge/subchain review does not establish complete source-selected life histories.',
        source_selected_esdec_mapping=mapping,elapsed_seconds=time.monotonic()-start))
    print('Identity regression and durable mapping complete',flush=True);timer.cancel()
if __name__=='__main__':main()
