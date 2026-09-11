"""Verify stage compatibility, preserve original inputs, and archive preparation evidence."""
import argparse,gzip,hashlib,json,os,shutil,threading,time
from pathlib import Path
import duckdb
from scripts.programme_closeout.candidate import atomic_json,sha,read_bundle,verify_files
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);a=p.parse_args();candidate=a.candidate.resolve()
    timer=threading.Timer(600,lambda:os._exit(124));timer.daemon=True;timer.start();start=time.monotonic()
    snap=json.loads((candidate/'snapshot.json').read_text());stages={};bundles={}
    for name in ('unified-01','identity-02','evidence-01'):
        attempt=candidate/'attempts'/name;bundle=attempt/'bundle';inp=attempt/'inputs.json'
        fp=json.loads(inp.read_text())['fingerprint'] if inp.exists() else snap['input_fingerprint']
        stages[name]=read_bundle(bundle,fp);bundles[name]=bundle
    expected_parent=sha(bundles['unified-01']/'private_markets_holdings.csv')
    identity_summary=json.loads((bundles['identity-02']/'summary.json').read_text())
    assert identity_summary['parent_holdings_sha256']==expected_parent
    evidence_summary=json.loads((bundles['evidence-01']/'summary.json').read_text())
    assert evidence_summary['parent_holdings_sha256']==sha(bundles['identity-02']/'private_markets_holdings.csv')
    con=duckdb.connect();con.execute('SET threads=2');con.execute("SET memory_limit='4GB'")
    temp=ROOT/'scratch/2026-09-09_programme_closeout/finalize_temp';temp.mkdir(exist_ok=True)
    literal=lambda p:"'"+str(p).replace("'","''")+"'"
    con.execute('SET temp_directory='+literal(temp))
    for view,name in (('u','unified-01'),('h','identity-02')):
        con.execute(f'CREATE VIEW {view} AS SELECT * FROM read_parquet({literal(bundles[name]/"private_markets_holdings.parquet")})')
    cols=[r[0] for r in con.execute('DESCRIBE u').fetchall()]
    identity_cols=[c for c in ('position_id','entity_id','canonical_name') if c in cols]
    selected=','.join('"'+c+'"' for c in cols if c not in identity_cols)
    count=con.execute(f'''SELECT count(*) FROM ((SELECT {selected} FROM u EXCEPT ALL SELECT {selected} FROM h)
         UNION ALL (SELECT {selected} FROM h EXCEPT ALL SELECT {selected} FROM u))''').fetchone()[0]
    if count:raise ValueError('Identity stage changed unexpected non-identity rows: '+str(count))
    print('Non-identity multiset preserved',flush=True)
    # holding_row_id is the ordinal of the actual CSV consumed by pandas.
    # Parquet normalizes date spellings, so comparing its VARCHAR dates to
    # untouched CSV tokens incorrectly treats those spellings as row drift.
    con.execute(f'CREATE VIEW numbered AS SELECT row_number() over()-1 holding_row_id,* FROM read_csv({literal(bundles["identity-02"]/"private_markets_holdings.csv")},all_varchar=true,parallel=false)')
    con.execute(f'CREATE VIEW p AS SELECT * FROM read_csv({literal(bundles["evidence-01"]/"position_pik_status.csv")},all_varchar=true)')
    integrity=con.execute('''SELECT count(*) total_status_rows,count(*) filter(where h.holding_row_id IS NULL OR p.position_id IS DISTINCT FROM h.position_id
      OR p.cik IS DISTINCT FROM h.cik OR p.source IS DISTINCT FROM h.source OR p.fair_value IS DISTINCT FROM h.fair_value
      OR p.report_date IS DISTINCT FROM h.report_date) mismatches
      FROM p LEFT JOIN numbered h ON try_cast(p.holding_row_id AS BIGINT)=h.holding_row_id''').fetchone()
    if integrity[1] or integrity[0]!=780425:raise ValueError('PIK/holdings identity mismatch: '+str(integrity))
    distinct_ids=con.execute('SELECT count(distinct holding_row_id) FROM p').fetchone()[0]
    if distinct_ids!=integrity[0]:raise ValueError('PIK holding row IDs are not unique')
    con.close()
    # This native companion was made by the same evidence worker. Retain it as a
    # separately hashed compatibility artifact rather than editing its sealed bundle.
    companion=candidate/'attempts/evidence-01/workspace/data/output/position_pik_status.parquet'
    if not companion.is_file():raise ValueError('Missing evidence typed companion')
    compatibility=dict(non_identity_row_differences=count,identity_columns_allowed=identity_cols,
       pik_status_rows=integrity[0],pik_parent_mismatches=integrity[1],
       pik_parent_comparison='Exact CSV tokens for position_id, cik, source, fair_value and report_date, joined by unique zero-based ordinal of the consumed CSV.',
       pik_typed_companion=dict(path=str(companion.relative_to(ROOT)),sha256=sha(companion)),
       stages={n:dict(result_sha256=sha(bundles[n]/'result.json'),input_fingerprint=stages[n]['input_fingerprint']) for n in stages},
       quality='FAIL_WITH_UNASSESSED_ITEMS',production_eligible=False,
       role='Preparation candidate composition. No release adoption, target-schema migration or complete product acceptance.')
    atomic_json(BASE/'stage_compatibility.json',compatibility)
    original=[r for r in snap['artifacts'] if r['path'].startswith(('pipeline/','data/','frontend/')) or r['path']=='AGENTS.md']
    verify_files(ROOT,original)
    identity_manifest=json.loads((BASE/'identity/input_manifest.json').read_text())
    for r in identity_manifest['reference_files']:
        if sha(ROOT/r['path'])!=r['sha256']:raise ValueError('Original reference changed: '+r['path'])
    position_gold=ROOT/'data/gold/labels/position_labels.jsonl'
    expected_gold='924f0b4096aaec355ae9e8fbede857ed616260155123538d89b11d48b7bdd3c7'
    if sha(position_gold)!=expected_gold:raise ValueError('Original position labels changed')
    atomic_json(BASE/'original_input_preservation.json',dict(result='pass',snapshot_files_checked=len(original),
       original_match_reference_files_checked=len(identity_manifest['reference_files']),
       original_position_labels_sha256=expected_gold,
       scope='All frozen pipeline code, data inputs/outputs/controls and AGENTS.md; all used mg3 packet/meta/verdict inputs. New programme scripts/docs intentionally changed.',
       excluded='Full historical output tree outside the snapshot not freshly hashed; targeted pytest and semantic backstop provide separate evidence.'))
    archives=[]
    for rel in ('units/unit_exceptions.csv','unit_resolution/resolved_exceptions.csv'):
        raw=BASE/rel;packed=raw.with_suffix('.csv.gz')
        with raw.open('rb') as src,packed.open('wb') as dst,gzip.GzipFile(filename='',mode='wb',fileobj=dst,mtime=0) as gz:
            shutil.copyfileobj(src,gz,1024*1024)
        with gzip.open(packed,'rb') as f:expanded=hashlib.file_digest(f,'sha256').hexdigest()
        if expanded!=sha(raw):raise ValueError('Compressed evidence roundtrip failed')
        archives.append(dict(raw_path=rel,archive_path=packed.relative_to(BASE).as_posix(),raw_bytes=raw.stat().st_size,
            compressed_bytes=packed.stat().st_size,raw_sha256=expanded,archive_sha256=sha(packed),
            restore='Decompress beside the .gz to the exact raw_path before rerunning consumers of the original manifest.'))
    raw_ignored={r['raw_path'] for r in archives};renditions={p.relative_to(BASE).as_posix() for p in (BASE/'viewer').glob('000*.html')}
    records=[]
    for path in sorted(BASE.rglob('*')):
        if not path.is_file() or path.name=='artifact_manifest.json':continue
        rel=path.relative_to(BASE).as_posix()
        records.append(dict(path=rel,bytes=path.stat().st_size,sha256=sha(path),
            storage='local_reproducible' if rel in raw_ignored or rel in renditions else 'retained_evidence'))
    atomic_json(BASE/'artifact_manifest.json',dict(format_version=1,artifacts=records,compressed_assets=archives,
        source_renditions=dict(builder='scripts/programme_closeout/citation_viewer.py',builder_sha256=sha(ROOT/'scripts/programme_closeout/citation_viewer.py'),
            regenerate='python -m scripts.programme_closeout.citation_viewer',original_sources='viewer/build.json'),
        elapsed_seconds=time.monotonic()-start,role='Specification preparation evidence, not production acceptance'))
    print(json.dumps(dict(compatibility='pass',original_files=len(original),reference_files=len(identity_manifest['reference_files']),evidence_files=len(records),seconds=time.monotonic()-start)),flush=True);timer.cancel()
if __name__=='__main__':main()
