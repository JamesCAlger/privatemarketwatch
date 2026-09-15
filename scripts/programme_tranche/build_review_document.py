"""Create a bounded source-review request and an offline, commentable briefing."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import threading
from urllib.parse import quote

from lxml import etree

from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha, verify_records

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/production_stack'
EVIDENCE = DOCS / 'programme_tranche_evidence_2026-09-10'
REFERENCES = EVIDENCE / 'references-v1'
REVIEW = EVIDENCE / 'source-review-v1'
OLD = DOCS / 'programme_closeout_evidence_2026-09-09'
PILOT = DOCS / 'programme_pilot_evidence_2026-09-09'


def text(value):
    return html.escape(str(value if value is not None else 'Unresolved / unavailable'))


def money(value):
    return 'Unresolved' if value is None else '${:,.0f}'.format(float(value))


def link(path, title):
    relative = os.path.relpath(path, DOCS).replace('\\', '/')
    return '<a href="' + quote(relative, safe='/.-_') + '">' + text(title) + '</a>'


def source_tree(relative, expected):
    path = ROOT / relative.replace('\\', '/')
    if path.stat().st_size > 120_000_000 or sha(path) != expected:
        raise ContractError('Source size or identity invalid: ' + relative)
    return etree.parse(str(path), etree.HTMLParser(no_network=True, recover=True, huge_tree=True))


def literal_row(tree, xpath):
    nodes = tree.xpath(xpath)
    if len(nodes) != 1:
        raise ContractError('Non-unique source row: ' + xpath)
    node = nodes[0]
    return dict(xpath=xpath, cells=[' '.join(' '.join(cell.itertext()).split())
                                  for cell in node.xpath('./td|./th')],
                text=' '.join(' '.join(node.itertext()).split()),
                facts=[dict(concept=f.get('name'), context=f.get('contextref'), unit=f.get('unitref'),
                            scale=f.get('scale'), sign=f.get('sign'), value=' '.join(f.itertext()))
                       for f in node.xpath('.//*[@contextref and @name]')])


def freeze_request():
    if REVIEW.exists():
        verify_records(REVIEW, read_json(REVIEW / 'complete.json')['artifacts'])
        return read_json(REVIEW / 'requests.json')
    verify_records(REFERENCES, read_json(REFERENCES / 'freeze_manifest.json')['files'], exact=True,
                   ignored_prefixes=('freeze_manifest.json',))
    registry = read_json(REFERENCES / 'registry.json')
    by_id = {reference['reference_id']: reference for reference in registry['references']}
    rosters = read_json(OLD / 'review/new_development_rosters.json')
    lord = read_json(PILOT / 'lord_reviewed_roster.json')
    bain_id = 'REF-0001899017-2023-06-30'
    bain_packet = read_json(ROOT / by_id[bain_id]['payload']['path'])['primary_packet']
    specs = [dict(reference_id=bain_id, name='Bain Capital Private Credit', quarter='2023-06-30',
                  path=bain_packet['path'], sha256=bain_packet['sha256'], table_paths=['/html/body/table[11]'],
                  context_values={'C_dc09c8b1-abd8-43ad-a596-2a8476dee264': 71250,
                                  'C_5caaf08f-afab-4d3d-bbe2-2d33a4944164': 575000},
                  note='Two distinct equity positions. Repeated totals and affiliation summaries are not extra holdings.')]
    for roster in rosters:
        is_north = '1950976' in roster['reference_id']
        specs.append(dict(reference_id=roster['reference_id'], name='26North' if is_north else 'Golub Capital Private Credit Fund',
            quarter='2023-12-31' if is_north else '2023-06-30', path=roster['source_path'], sha256=roster['source_sha256'],
            rows=roster['rows'], table_paths=sorted({row['key'].rsplit('/tr[', 1)[0] for row in roster['rows']}),
            note='Preserve the four distinct facilities and negative revolver.' if is_north else
                 'One named Treasury Portfolio holding. Do not add its repeated schedule total or invent a security from aggregate cash.'))
    specs.append(dict(reference_id='REF-0002008748-2024-09-30', name='Lord Abbett Private Credit Fund',
        quarter='2024-09-30', path=lord['source_path'], sha256=lord['source_sha256'], rows=lord['roster'],
        table_paths=['/html/body/table[13]', '/html/body/table[14]'],
        note='33 distinct loans/facilities; 27 known FV amounts and six displayed dashes. Those dashes remain unresolved, not zero.'))
    if len(specs) != 4:
        raise ContractError('Expected exactly four complete development schedules')
    schedules = []
    for spec in specs:
        tree = source_tree(spec['path'], spec['sha256'])
        print('Source review: ' + spec['name'], flush=True)
        declared = spec.get('rows', [])
        if 'context_values' in spec:
            for context, amount in spec['context_values'].items():
                nodes = tree.xpath('//*[@contextref=$context and @name="us-gaap:InvestmentOwnedAtFairValue"]', context=context)
                positions = {tree.getpath(node.xpath('ancestor::tr[1]')[0]) for node in nodes}
                # Restrict to this schedule; other presentations can repeat the context.
                positions = {path for path in positions if path.startswith('/html/body/table[11]/')}
                if len(positions) != 1:
                    raise ContractError('Bain source row needs explicit re-adjudication')
                declared.append(dict(key=positions.pop(), fair_value=amount, context_id=context))
        if len(declared) > 1000:
            raise ContractError('Review exceeds 1,000 selected rows')
        rows = []
        for row in declared:
            literal = literal_row(tree, row['key'])
            rows.append(dict(proposal=row, literal=literal))
        table_rows = []
        for xpath in spec['table_paths']:
            selected = tree.xpath(xpath)
            if len(selected) != 1:
                raise ContractError('Review table locator not unique')
            physical = selected[0].xpath('./tr')
            if len(physical) > 1000:
                raise ContractError('Review exceeds 1,000 table rows')
            table_rows.extend(literal_row(tree, tree.getpath(row)) for row in physical)
        source = record(ROOT, spec['path'].replace('\\', '/'))
        schedules.append(dict(reference_id=spec['reference_id'], title=spec['name'], quarter=spec['quarter'],
            source=source, proposed_rows=rows, complete_table_rows=table_rows, note=spec['note'],
            reviewer=None, review_status='pending_independent_review', exposure='development_outputs_seen'))
        del tree
    labels = read_json(REFERENCES / 'original_label_proposals.json')
    result = dict(schema_version=1, version='source-review-v1', author='Codex first-tranche controller',
        authority=None, review_status='pending_independent_review', independent_approvals=0,
        schedules=schedules, label_proposals=labels,
        instructions='Review the literal source independently. Record disagreements, full row boundaries, units, zero/dash meaning and accounting scope. Notes do not automatically approve or promote a reference.',
        inputs=[record(ROOT, p.relative_to(ROOT).as_posix()) for p in (
            REFERENCES / 'freeze_manifest.json', REFERENCES / 'registry.json',
            OLD / 'review/new_development_rosters.json', PILOT / 'lord_reviewed_roster.json',
            ROOT / 'scripts/programme_reference/measure_pilot.py')])
    REVIEW.mkdir(parents=True, exist_ok=False)
    atomic_json(REVIEW / 'requests.json', result)
    atomic_json(REVIEW / 'complete.json', dict(artifacts=[record(REVIEW, 'requests.json')],
        status='complete_review_request; no independent approval'))
    return result


CSS = '''
:root{color-scheme:light;--ink:#172b35;--muted:#536873;--line:#d8e1e6;--paper:#f2f5f4;--accent:#126b65;--warn:#875b10}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1040px;margin:auto;padding:42px 26px 100px}header{margin-bottom:34px}h1{font-size:clamp(32px,5vw,54px);line-height:1.12;letter-spacing:-.035em;max-width:800px}h2{font-size:29px;line-height:1.25}h3{line-height:1.35}p{max-width:80ch}.eyebrow{color:var(--accent);font-size:13px;text-transform:uppercase;letter-spacing:.12em;font-weight:750}.lede{font-size:20px;color:var(--muted)}section{background:white;border:1px solid var(--line);border-radius:18px;padding:28px;margin:24px 0;scroll-margin-top:20px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}.card{background:#f2f6f5;padding:18px;border-radius:12px}.number{font-size:30px;font-weight:750}.muted,.hint{color:var(--muted)}.hint{font-size:14px}.badge{display:inline-block;padding:4px 10px;border-radius:6px;background:#fff2d8;color:#705016;font-size:13px;font-weight:700}.status-pass{background:#e0f3e7;color:#195632}.status-fail{background:#fbe7e5;color:#8e3026}a{color:var(--accent);text-underline-offset:3px}.toolbar{display:flex;flex-wrap:wrap;gap:10px}button{font:inherit;border:1px solid var(--line);border-radius:9px;padding:9px 14px;background:white;cursor:pointer}button:focus-visible,a:focus-visible,summary:focus-visible,textarea:focus-visible{outline:3px solid #23938b;outline-offset:3px}details{border-top:1px solid var(--line);padding:14px 0}summary{cursor:pointer;font-weight:650}.detail{padding:8px 3px}.literal{background:#f4f6f7;border-left:3px solid #94aaa9;padding:14px;overflow-wrap:anywhere;font-size:15px}.row{padding:12px 0;border-bottom:1px solid var(--line)}.row strong{display:block}code{font-size:13px;overflow-wrap:anywhere}textarea{width:100%;min-height:100px;padding:12px;font:inherit;border:1px solid #a6b9be;border-radius:8px}.comment{background:#f8faf9;padding:14px;margin-top:22px;border-radius:10px}.comment label{display:block;font-size:14px;font-weight:650;margin-bottom:6px}.metric{display:flex;justify-content:space-between;gap:20px;padding:9px 0;border-bottom:1px solid var(--line)}.metric span:last-child{text-align:right;max-width:55%}.wide{overflow-x:auto}nav a{display:inline-block;margin:4px 15px 4px 0}ol,ul{padding-left:24px}li{margin:7px 0}.screen-only{display:block}.print-comment{display:none;white-space:pre-wrap}footer{font-size:14px;color:var(--muted)}
@media(max-width:600px){main{padding:22px 14px 70px}section{padding:20px}.metric{display:block}.metric span{display:block}.metric span:last-child{text-align:left;max-width:100%}}
@media print{body{background:white;font-size:11pt}main{max-width:none;padding:0}section{break-inside:avoid;padding:16px;margin:12px 0}button,nav,.screen-only,textarea,.comment label{display:none!important}.print-comment{display:block}details{display:block}a{color:inherit}.comment{padding:4px}.literal{font-size:10pt}}
'''

JS = r'''
const storageKey='programme-tranche-review-20260910:'+location.pathname;
let draft={},stored=true;try{draft=JSON.parse(localStorage.getItem(storageKey)||'{}');if(!draft||typeof draft!=='object'||Array.isArray(draft))draft={};}catch(_){stored=false;}
const notes=Array.from(document.querySelectorAll('[data-review]')).map(host=>{
 const key=host.dataset.review,title=host.dataset.title||host.querySelector('h2,h3,summary')?.textContent||key;
 const panel=document.createElement('div');panel.className='comment';
 const label=document.createElement('label');label.textContent='Your comments on '+title;label.htmlFor='note-'+key;
 const input=document.createElement('textarea');input.id=label.htmlFor;input.placeholder='[Your comment or question]';input.value=typeof draft[key]==='string'?draft[key]:'';
 const print=document.createElement('div');print.className='print-comment';print.textContent=input.value;
 input.addEventListener('input',()=>{draft[key]=input.value;print.textContent=input.value;try{localStorage.setItem(storageKey,JSON.stringify(draft));stored=true;}catch(_){stored=false;}status.textContent=stored?'Draft saved in this browser. Save a review file for Codex to read.':'Browser storage unavailable. Save or copy your comments before closing.';});
 panel.append(label,input,print);host.append(panel);return {key,title,input};
});
const status=document.getElementById('save-status');
if(!stored)status.textContent='Browser storage unavailable. Save or copy your comments before closing.';
document.getElementById('save').addEventListener('click',async()=>{
 const lines=['# First tranche review comments','','Briefing: programme_tranche_review.html','Saved: '+new Date().toISOString(),'','These comments are review notes; they do not automatically approve a reference or release.',''];
 notes.forEach(note=>{if(note.input.value.trim())lines.push('## '+note.title+' ['+note.key+']','',note.input.value.trim(),'');});
 const content=lines.join('\n'),filename='programme_tranche_review_comments.md';
 try{if('showSaveFilePicker'in window){const handle=await showSaveFilePicker({suggestedName:filename,types:[{description:'Markdown comments',accept:{'text/markdown':['.md']}}]});const writable=await handle.createWritable();await writable.write(content);await writable.close();status.textContent='Saved '+handle.name+'. Later edits need another save.';}
 else{const url=URL.createObjectURL(new Blob([content],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);status.textContent='Download requested. Place '+filename+' beside this briefing for Codex to read.';}}
 catch(error){status.textContent=error.name==='AbortError'?'Save cancelled; comments remain in the page.':'Save failed; copy your comments before closing.';}
});
document.getElementById('expand').addEventListener('click',()=>{const all=Array.from(document.querySelectorAll('details'));const open=!all.every(d=>d.open);all.forEach(d=>d.open=open);});
document.getElementById('print').addEventListener('click',()=>window.print());
let printState=[];addEventListener('beforeprint',()=>{printState=Array.from(document.querySelectorAll('details')).map(d=>d.open);document.querySelectorAll('details').forEach(d=>d.open=true);});addEventListener('afterprint',()=>document.querySelectorAll('details').forEach((d,i)=>d.open=printState[i]||false));
'''


def render(request, evaluation=None, verification=None, investigation=None):
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="color-scheme" content="light"><title>First programme tranche - review</title><style>', CSS, '</style></head><body><main>',
        '<header><p class="eyebrow">Private markets data programme / 10 September 2026</p><h1>The first implementation tranche.</h1>',
        '<p class="lede">A controlled way to run, measure and resume the pipeline, with source-backed work ready for review.</p>',
        '<div class="toolbar"><button id="save">Save review file</button><button id="expand">Show / hide supporting detail</button><button id="print">Print / save PDF</button></div>',
        '<p id="save-status" class="hint screen-only">Use [brackets] or plain text in any comment box. Browser drafts stay local; save the review file for Codex.</p>',
        '<nav><a href="#result">Result</a><a href="#changes">What changed</a><a href="#queue">Four next fixes</a><a href="#source-review">Source review</a><a href="#criteria">Acceptance criteria</a></nav></header>']
    stopped = evaluation and evaluation.get('stopped')
    boundary_stop = verification and verification.get('execution_status') == 'stopped_protected_output'
    status = ('Verification stopped: protected test-cache writes' if boundary_stop else
        'Run stopped: dependency manifest incomplete' if stopped else
        'Evaluation pending' if not evaluation else evaluation['criteria']['verdict'].replace('_', ' ').title())
    parts += ['<section id="result" data-review="result"><p class="eyebrow">01 / Outcome</p><h2>'+text(status)+'</h2>']
    if verification and verification.get('execution_status') == 'verification_incomplete':
        parts += ['<p id="engineering-status"><strong>Engineering verification is incomplete.</strong> '
                  + text(verification['summary']) + '</p>']
    if boundary_stop:
        parts += ['<p id="engineering-status"><strong>The three candidate stages completed. Engineering verification is incomplete.</strong></p>',
            '<p>The revised dependency inventory covered 247,333 files. The full holdings, matching and PIK stages then completed, with all 11 CSV/Parquet pairs agreeing.</p>',
            '<div class="cards"><div class="card"><div class="number">780,425</div>Candidate holdings rows</div>',
            '<div class="card"><div class="number">497,451</div>Assigned position matches</div>',
            '<div class="card"><div class="number">68</div>Focused tests passed before the full suite</div></div>',
            '<p>The full test suite reached its time limit, with <strong>four failure markers</strong> and no final traceback. The earlier handoff incorrectly counted one. Its outer guard found <strong>six new empty query-cache files</strong> in a protected output folder. The agreed stop rule therefore applies. All 237,621 pre-existing protected files retained their size and modification time; that is not a full content-hash proof.</p>',
            '<p>A test fixture redirected one output directory but missed a separate DuckDB cache. A fix now sends those caches to temporary test folders and gives orchestration tests synthetic query sources. '
            + ('The subsequent bounded investigation verified these repairs; see its results below.' if investigation else '<strong>At the original stop, this fix was untested.</strong>') + '</p>',
            '<p>Integrated financial measurements and the actual recovery drill did not run. All 50 programme metrics below remain UNMEASURED. Stage row counts and matching file formats do not establish financial accuracy.</p>',
            '<p>The six files total 9,580 bytes and remain in place. Automatic approval review rejected their removal as "blocked by policy"; no further reason was supplied. Forensic copies and hashes are preserved.</p>',
            '<p>'+link(DOCS/'programme_tranche_handoff_2026-09-10.md','Read the handoff and preservation limits')+' / '+link(DOCS/'programme_tranche_resume_proposal_2026-09-10.md','Read the revised proposal and outcome')+'</p>']
        if investigation:
            parts += ['<h3>What the subsequent investigation found</h3>',
                '<p>All four failures reproduced: three tests expected outdated wrapper versions, and one validator checked DuckDB regexes using Python syntax. The stale expectations and test-cache isolation are repaired. The production regex validator still needs its correction.</p>',
                '<p><strong>'+text(str(investigation['repaired_outcomes']['passed']))+' targeted tests passed; one known validator test still failed.</strong> Four representative staging/integration cases were checked. The broader 59-case class did not fit the diagnostic budget and was stopped with its completed results retained. No protected-output files changed during these diagnostic jobs. The full suite has not been rerun.</p>',
                '<p>The slow fixtures repeatedly processed a large production overlay. The two profiled examples improved from about 170 seconds each to '
                + text(' and '.join(str(round(item['after_seconds'],1))+' seconds' for item in investigation['slow_test_comparison']))
                + '. Staging still has substantial processing cost. These are instrumented diagnostic timings, not a prediction of total suite runtime.</p>',
                '<p>The diagnostic controller now saves failures immediately and checks the worker result and JUnit, because launcher success alone proved unreliable.</p>',
                '<p>'+link(DOCS/'programme_verification_investigation_2026-09-10.md','Read the investigation, evidence and remaining work')+'</p>']
    elif stopped:
        parts += ['<p>The holdings worker finished, but the controller refused to certify its result because one installed package metadata file had no pre-run hash. The agreed stop rule and retry limit have been reached.</p>',
            '<p><strong>The integrated candidate is incomplete.</strong> Matching, PIK generation, final measurements and the recovery drill did not run. All 28 acceptance criteria are recorded below with unmeasured results.</p>',
            '<p>The retained worker output contains 780,425 rows. It is an unsealed development artifact, not a release. A narrow metadata-inventory fix has been prepared for a separately authorized fresh attempt.</p>',
            '<p>'+link(DOCS/'programme_tranche_resume_proposal_2026-09-10.md','Read the concrete correction and retry proposal')+' / '+link(DOCS/'programme_tranche_handoff_2026-09-10.md','Read the concise handoff')+'</p>']
    elif evaluation:
        measurements = evaluation['measurements']; history = measurements['history']; obligations = measurements['obligations']
        parts += ['<p>The candidate has a complete recorded result. Its execution result and financial acceptance verdict are separate. No production release has been adopted.</p><div class="cards">',
            '<div class="card"><div class="number">'+text(f"{history['rows']:,}")+'</div>Holdings in required history</div>',
            '<div class="card"><div class="number">'+text(obligations['missing'])+'</div>Eligible fund-quarters without holdings</div>',
            '<div class="card"><div class="number">'+text(f"{100*history['sector_abs_fv']/history['absolute_fv']:.2f}%")+'</div>Known FV with a mapped sector</div></div>',
            '<p class="hint">History: Q1 2023 through Q1 2026, 70-fund cohort. Sector availability covers holdings already present; it is not sector accuracy or missing-position coverage.</p>',
            '<p>Semantic differences against the frozen starting holdings: <strong>'+text(measurements['comparisons']['unified_vs_starting'])+'</strong>. Identity-stage differences: <strong>'+text(measurements['comparisons']['identity_vs_starting'])+'</strong>. PIK parent mismatches: <strong>'+text(measurements['comparisons']['pik_parent_mismatches'])+'</strong>.</p>']
    else:
        parts += ['<p>The integrated build and final verification are in progress. The source packets below are prepared; this document does not claim that the full run has passed.</p>']
    parts += ['<p><strong>Independent source review is still pending.</strong> No reviewer has been appointed and none of the development labels has been promoted to acceptance evidence.</p></section>',
        '<section id="changes" data-review="changes"><p class="eyebrow">02 / Implementation</p><h2>Completed work can be verified and reused.</h2>',
        '<ul><li>The candidate runner freezes inputs and dependencies, isolates writes, and verifies each holdings, identity and PIK stage before marking it complete.</li>',
        '<li>CSV and Parquet companions must agree, including duplicate counts. Failed or incomplete stages cannot be mistaken for usable results.</li>',
        '<li>The evaluator records all 28 criteria against versioned working targets. Missing evidence stays visibly unassessed.</li>',
        '<li>Target amendments retain old and proposed results on the same candidate. Original gold and live thresholds stay under their existing authority.</li></ul>',
        '<p>This tranche establishes controls. The schema, rate, persistent-identity and dbt migrations remain subsequent implementation packages.</p>',
        '<details><summary>Execution and verification evidence</summary><div class="detail">']
    if verification:
        if verification.get('summary'):
            parts += ['<p>'+text(verification['summary'])+'</p>']
        parts += ['<pre class="literal">'+text(json.dumps(verification, indent=2))+'</pre>']
    else:
        parts += ['<p>See the live work record for completed tests and running jobs. Final verification has not yet been attached.</p>']
    parts += [link(DOCS / 'programme_runner.md', 'Runner and recovery guide')+' / '+link(DOCS / 'programme_tranche_2026-09-10_work_record.md', 'Execution record'), '</div></details></section>',
        '<section id="queue"><p class="eyebrow">03 / Prioritized work</p><h2>Four bounded fixes, with explicit counterexamples.</h2><p>These are implementation proposals. Their expected changes have not been applied to the candidate.</p>']
    for packet in read_json(REFERENCES / 'remediation_packets.json'):
        parts += ['<details data-review="'+text(packet['packet_id'])+'" data-title="'+text(packet['title'])+'"><summary>'+text(packet['title'])+'</summary><div class="detail">',
            '<p>'+text(packet['mechanism'])+'</p><p><strong>Positive case:</strong> '+text(packet['positive'])+'</p>',
            '<p><strong>Counterexample:</strong> '+text(packet['false_positive'])+'</p>',
            '<p><strong>Expected change:</strong> '+text('; '.join(key.replace('_',' ')+': '+str(value) for key,value in packet['expected_changes'].items()))+'</p>',
            '<p><strong>Must remain true:</strong> '+text(packet['unchanged_validation'])+'</p>',
            '<p><strong>Rule location:</strong> '+text(packet['rule_home'])+'</p>',
            '<p><strong>Unresolved:</strong> '+text(packet['residual_risk'])+'</p></div></details>']
    parts += ['</section><section id="source-review" data-review="review-authority"><p class="eyebrow">04 / Independent review</p><h2>Four schedules and 20 label proposals.</h2>',
        '<p>Check the literal filing passages, position boundaries, currencies, units and unknown values. The proposed interpretations are shown for review. Comments do not automatically approve, relabel or publish anything.</p>',
        '<p>All examples have been exposed during development. Even after review, this set cannot certify an unbiased sampled accuracy estimate for the whole portfolio.</p>']
    for schedule in request['schedules']:
        parts += ['<details data-review="'+text(schedule['reference_id'])+'" data-title="'+text(schedule['title']+' '+schedule['quarter'])+'"><summary>'+text(schedule['title']+' / '+schedule['quarter'])+' / '+text(len(schedule['proposed_rows']))+' proposed holdings</summary><div class="detail">',
            '<p>'+text(schedule['note'])+'</p><p>'+link(ROOT / schedule['source']['path'], 'Open the cached source filing')+'</p>',
            '<p class="hint">Source SHA-256: <code>'+text(schedule['source']['sha256'])+'</code></p>']
        for index,row in enumerate(schedule['proposed_rows'],1):
            proposal=row['proposal']; name=proposal.get('issuer_instrument') or proposal.get('issuer') or next((c for c in row['literal']['cells'] if c),'Position')
            parts += ['<div class="row"><strong>'+text(str(index)+'. '+name)+'</strong><p>Proposed fair value: '+text(money(proposal.get('fair_value')))+'</p>',
                '<p class="literal">'+text(row['literal']['text'])+'</p><p class="hint"><code>'+text(row['literal']['xpath'])+'</code></p></div>']
        parts += ['<details><summary>Whole schedule: headers, totals and excluded rows</summary>']
        for row in schedule['complete_table_rows']:
            parts += ['<p class="literal">'+text(row['text'])+'<br><code>'+text(row['xpath'])+'</code></p>']
        parts += ['</details></div></details>']
    for proposal in request['label_proposals']:
        key='LABEL-'+str(proposal['case']).zfill(2); original=proposal['original_label']
        title=original.get('source_identifier',proposal['key'])
        parts += ['<details data-review="'+text(key)+'" data-title="'+text(title)+'"><summary>'+text(key+' / '+title)+'</summary><div class="detail">',
            '<p><span class="badge">'+text(proposal['status'].replace('_',' '))+'</span></p><p>'+text(proposal['reason'])+'</p>',
            '<p><strong>Original label:</strong> '+text(original.get('true_classification'))+'</p>',
            '<p><strong>Proposed interpretation:</strong> '+text(json.dumps(proposal.get('proposal'), ensure_ascii=False))+'</p>',
            '<p>'+link(ROOT / proposal['source_path'].replace('\\','/'), 'Open the cached source filing')+'</p>']
        for passage in proposal.get('selected_literal_evidence',[]):
            parts += ['<p class="literal">'+text(' | '.join(cell for cell in passage.get('cells',[]) if cell))+'</p>',
                '<p class="hint"><code>'+text(passage.get('xpath'))+'</code></p>']
        if proposal.get('supplementary_evidence'):
            parts += ['<details><summary>Supplementary source context</summary><pre class="literal">'+text(json.dumps(proposal['supplementary_evidence'],indent=2,ensure_ascii=False))+'</pre></details>']
        parts += ['</div></details>']
    parts += ['</section><section id="criteria" data-review="criteria"><p class="eyebrow">05 / Acceptance</p><h2>Every criterion keeps a result.</h2>']
    if evaluation:
        for criterion in evaluation['criteria']['criteria']:
            parts += ['<details><summary>'+text(criterion['criterion_id']+' / '+criterion['title'])+' <span class="badge status-'+criterion['status'].lower()+'">'+text(criterion['status'])+'</span></summary><div class="detail">']
            for metric in criterion['results']:
                value=metric.get('comparison_value',metric.get('subset_value','Not measured'))
                parts += ['<div class="metric"><span>'+text(metric['metric_id'].replace('_',' '))+'</span><span>'+text(str(value)+' / '+metric['status'])+'</span></div><p class="hint">'+text(metric['reason'])+'</p>']
            parts += ['</div></details>']
    else:
        parts += ['<p>The final measured inventory will appear here after the integrated run. The complete definitions and current working targets are already versioned.</p>']
    parts += ['<p>'+link(DOCS / 'programme_measurement_register.md', 'Measurement definitions')+' / '+link(ROOT / 'pipeline/programme/contracts/working-v1.json', 'Working targets')+'</p></section>',
        '<footer><p>This briefing is a review companion, not a production dashboard or a source-citation product. Source amounts and label proposals retain their development status. The execution record and hashed artifacts are the detailed evidence.</p><p>'+link(REVIEW / 'requests.json','Full source review request')+' / '+link(REFERENCES / 'registry.json','Reference registry')+' / '+link(DOCS / 'programme_execution_tranche_2026-09-09.md','Approved tranche scope')+'</p></footer>',
        '</main><script>',JS,'</script></body></html>']
    (DOCS / 'programme_tranche_review.html').write_text(''.join(parts),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation')
    parser.add_argument('--verification',type=Path)
    parser.add_argument('--investigation',type=Path)
    args=parser.parse_args()
    
    request=freeze_request()
    evaluation=None
    if args.evaluation:
        directory=EVIDENCE / args.evaluation
        verify_records(directory,read_json(directory / 'evaluation_manifest.json')['files'])
        execution=read_json(directory / 'execution.json') if (directory / 'execution.json').exists() else {}
        evaluation=dict(measurements=read_json(directory / 'measurements.json') if (directory / 'measurements.json').exists() else None,
            criteria=read_json(directory / 'criterion_results.json'),stopped=execution.get('status') in ('blocked', 'stopped_protected_output'))
    render(request,evaluation,read_json(args.verification) if args.verification else None,
           read_json(args.investigation) if args.investigation else None)
    
    print('Commentable review document written; no reference approval granted',flush=True)


if __name__=='__main__':
    main()
