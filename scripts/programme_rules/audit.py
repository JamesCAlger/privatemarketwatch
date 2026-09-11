"""Bounded PREP-01 rule-authority audit; no production changes or network.

Usage: python scripts/programme_rules/audit.py --output scratch/<session>/run1
Outputs: static authority register, asset inventory, code sites, runtime probes.
Max 240 seconds, 1 GB/two threads per in-memory DuckDB connection, <=20 fixture
rows per replay, <=10,000 inventory rows. Not a full rebuild or acceptance test.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from collections import Counter, defaultdict
from contextlib import ExitStack
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
OUT = None
INPUTS = {}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def pin(path):
    path = Path(path).resolve()
    if path.is_file() and path not in INPUTS:
        stat = path.stat()
        INPUTS[path] = dict(path=path.relative_to(ROOT).as_posix(),
                            size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                            sha256=digest(path))


def emit(name, value):
    path = OUT / name
    if path.suffix == '.csv':
        if len(value) > 10000:
            raise RuntimeError('Inventory bound exceeded: ' + name)
        with path.open('w', newline='', encoding='utf-8') as stream:
            if value:
                writer = csv.DictWriter(stream, fieldnames=list(value[0]))
                writer.writeheader()
                writer.writerows(value)
    else:
        path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding='utf-8')


def protected_stats():
    result = {}
    # The full historical output tree has >237K files. Guard every Python write
    # and native COPY below, but bound metadata verification to current top-level
    # outputs plus all frontend data. This is not a full historical-tree scan.
    for base in (ROOT / 'data/output', ROOT / 'frontend/public/data'):
        paths = base.iterdir() if base.name == 'output' else base.rglob('*')
        for path in paths:
            if path.is_file():
                stat = path.stat()
                result[path.relative_to(ROOT).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return result


def static_inventory():
    definitions = Path(__file__).with_name('families.tsv')
    pin(definitions)
    families = list(csv.DictReader(definitions.open(encoding='utf-8'), delimiter='\t'))
    sites, gaps, source_trees = [], [], {}
    for family in families:
        source = ROOT / 'pipeline' / (family['module'] + '.py')
        pin(source)
        if source not in source_trees:
            text = source.read_text(encoding='utf-8-sig')
            tree = ast.parse(text)
            source_trees[source] = (text, tree)
            lines = text.splitlines()
            functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for n in ast.walk(tree):
                if not isinstance(n, ast.If):
                    continue
                parent = min((f for f in functions if f.lineno <= n.lineno <= f.end_lineno),
                             key=lambda f: f.end_lineno-f.lineno, default=None)
                sites.append(dict(path=source.relative_to(ROOT).as_posix(), line=n.lineno,
                                  kind='python_if_candidate', function=parent.name if parent else '<module>',
                                  expression=ast.unparse(n.test),
                                  interpretation='source branch; not a separately certified business rule'))
            for line_no, line in enumerate(lines, 1):
                if re.search(r'\bWHEN\b|\b[A-Za-z_]+ AS \(', line) and not line.lstrip().startswith('#'):
                    sites.append(dict(path=source.relative_to(ROOT).as_posix(), line=line_no,
                                      kind='sql_site_candidate', function='', expression=line.strip(),
                                      interpretation='SQL source site; review full surrounding CASE/CTE'))
        text, tree = source_trees[source]
        function = family['function']
        node = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function), None)
        if function and node is None:
            gaps.append(family['family_id'] + ': missing function ' + function)
        family.update(source_path=source.relative_to(ROOT).as_posix(),
                      source_sha256=INPUTS[source]['sha256'],
                      start_line=node.lineno if node else 1,
                      end_line=node.end_lineno if node else len(text.splitlines()),
                      evidence_level='code_path; runtime probe separately named',
                      full_population_application='not_measured',
                      unit_contract='current implementation in source; target programme_target_contract.md')
    emit('rule_authority_register.csv', families)
    emit('embedded_code_sites.csv', sites)
    return families, gaps


def asset_inventory(ap, bw, sb, bridge, correction_leaf, agent_rule):
    previous = ROOT / 'docs/reference/architecture_rule_assets.csv'
    pin(previous)
    old = {r['path']: r for r in csv.DictReader(previous.open(encoding='utf-8'))}
    rows, sections = [], []
    known_paths = set(old)
    known_paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'data/overrides').rglob('*.json'))
    known_paths.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'data/raw/filing_templates').glob('*.json'))
    for rel in sorted(known_paths):
        path = ROOT / rel
        prior = old.get(rel, {})
        if not path.is_file():
            rows.append(dict(path=rel, family=prior.get('family',''), sha256='', prior_hash_equal=False,
                             runtime_role='missing', cik='', rule_id='', scope='', selector='', writes='',
                             schema_errors='', eligibility='missing', source_evidence='', version=''))
            continue
        pin(path)
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig')) if path.suffix == '.json' else {}
        except (ValueError, OSError):
            payload = {}
        obj = payload if isinstance(payload, dict) else {}
        family = prior.get('family', path.parent.name)
        if path.parent == ROOT / 'data/raw/filing_templates':
            family = 'html_templates'
        scope = obj.get('scope', {'target_quarter': obj.get('target_quarter','')})
        template = obj.get('template') or {}
        errors, eligibility, role = [], 'control_asset_not_application_claim', 'reference/control'
        writes = template.get('field') or obj.get('field') or ''
        if family == 'agent_b2_corrections':
            role = 'B2 candidate mutation or wrapper/grammar proposal'
            eligible = path.parent.parent == ROOT / 'data/overrides/agent_b2_corrections' and path.suffix == '.json' and isinstance(payload, dict)
            eligibility = 'loader_eligible_unvalidated' if eligible else 'outside_loader_pattern'
            if obj.get('fix_class'):
                errors = correction_leaf.validate_correction(obj).errors
                writes = writes or ('row_population' if correction_leaf.stage_for(obj['fix_class']) == 1 else obj['fix_class'])
        elif family == 'agent_investigate_rules':
            role = 'Layer C mutation'
            eligible = path.parent.parent == ROOT / 'data/overrides/agent_investigate_rules' and not path.parent.name.startswith('_') and path.suffix == '.json'
            eligibility = 'loader_eligible_applier_validates' if eligible else 'outside_loader_pattern_or_pulled'
            if obj.get('rule_type'):
                errors = agent_rule.validate_rule(obj)
                writes = writes or 'row_population'
        elif family == 'agent_anchor':
            role = 'independent anchor input; not holding amount writer'
            eligible = (path.parent.parent == ROOT / 'data/overrides/agent_anchor' and
                        isinstance(obj.get('grand_total'), (int,float)) and
                        obj.get('basis') in ('published_rows','investments_ex_cash'))
            eligibility = 'loader_eligible_basis_present' if eligible else 'not_eligible_shape_or_basis'
        elif family == 'bdc_xbrl_wrappers':
            role = 'production staging + wrapper classifier + reconciliation'
            eligibility = 'v3_sections_conditional' if obj.get('schema_version') == 'bdc-xbrl-wrapper.v3' else 'not_v3'
            for section in ('dispatch','staging','identifier_parser','identifier_format','invariants','archetypes'):
                if section in obj:
                    data = obj[section]
                    entries = data.items() if isinstance(data,dict) else enumerate(data) if isinstance(data,list) else [('',data)]
                    for key, value in entries:
                        sections.append(dict(path=rel, cik=obj.get('cik',''), json_pointer=f'/{section}/{key}',
                                             section=section, content=json.dumps(value,sort_keys=True),
                                             authority=('staging loaders' if section in ('staging','identifier_parser','identifier_format') else
                                                        'wrapper runtime dispatch' if section=='dispatch' else 'oracle/spec metadata; consumer-specific'),
                                             application='not_measured'))
        elif family in ('identifier_rate_grammars','identifier_anchors'):
            role = 'Agent A diagnostic/proposal input; no generic production merge'
            eligibility = 'per_CIK_requested_loader'
        elif family == 'bdc_xbrl_html_section_bridges':
            role = 'production source/field bridge'
            eligibility = 'loader_schema_eligible_including_proposed_name' if obj.get('schema_version') == bridge.BRIDGE_SCHEMA_VERSION else 'schema_not_eligible'
        elif family == 'rate_convention':
            role = 'convention diagnostic/return input; not staging coupon writer'
        elif family == 'html_templates':
            role = 'cached HTML extraction configuration; no new extraction invoked'
            eligibility = 'requested_CIK_version_eligible' if obj.get('version') == '3.0' else 'wrong_template_version'
        elif family == 'conservation_scope' and '_retired' in path.parts:
            role = 'retired historical numerator carve-out; not current authority'
            eligibility = 'retired_no_current_consumer_found'
        rows.append(dict(path=rel, family=family, sha256=INPUTS[path.resolve()]['sha256'],
                         prior_hash_equal=prior.get('sha256') == INPUTS[path.resolve()]['sha256'],
                         runtime_role=role, cik=obj.get('cik', prior.get('cik','')),
                         rule_id=obj.get('rule_id',obj.get('fix_class',prior.get('rule_id',''))),
                         scope=json.dumps(scope,sort_keys=True),
                         selector=json.dumps(template.get('row_selector',obj.get('predicate_sql',template)),sort_keys=True),
                         writes=writes, schema_errors=json.dumps(errors,sort_keys=True,default=str), eligibility=eligibility,
                         source_evidence=json.dumps(obj.get('evidence_citations',obj.get('evidence',obj.get('source',{}))),sort_keys=True),
                         version=obj.get('schema_version',obj.get('version',''))))
    emit('rule_assets.csv', rows)
    emit('wrapper_sections.csv', sections)
    loaded = dict(b2_leaves=len(ap.load_promoted_corrections()),
                  layer_c_leaves=sum(map(len,ap.load_promoted_rules().values())),
                  anchor_records=len(ap.load_anchor_overrides()), wrapper_specs=len(bw.supported_wrapper_ciks()),
                  staging_configs=len(sb._load_staging_configs()), identifier_parsers=len(sb._load_identifier_parsers()),
                  comma_delimited_ciks=len(sb._get_comma_delimited_ciks()), prefix_rule_ciks=len(sb._get_prefix_rules_data()),
                  issuer_bridge_rows=len(sb._load_issuer_bridges_from_json()), html_bridge_rows=len(bridge.load_html_section_bridge_rows()))
    emit('loader_results.json', loaded)
    return rows, loaded


def control_inventory(duckdb):
    """Count configured lookup/control inputs, not production holding rows."""
    from pipeline import config, fund_highlights_wrapper
    names = (
        'ROW_CORRECTIONS_FILE', 'AGGREGATE_HEADER_FLAGS_FILE',
        'FUND_STRATEGY_REFERENCE_FILE', 'FUND_STRATEGY_CORRECTION_CANDIDATES_FILE',
        'FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE', 'FUND_STRATEGY_OVERRIDES_FILE',
        'COMPANY_GICS_CACHE_FILE', 'GICS_LABEL_CACHE_FILE', 'LIEN_CACHE_FILE',
        'UNCLASSIFIED_REVIEW_CACHE_FILE', 'ENTITY_LOOKUP_FILE', 'ENTITY_OVERRIDES_FILE',
        'IDENTIFIER_EXTRACTION_LOOKUP_FILE', 'FX_RATES_FILE',
    )
    rows = []
    con = duckdb.connect()
    try:
        for name in names:
            path = Path(getattr(config, name))
            row = dict(config_name=name, path=path.relative_to(ROOT).as_posix(),
                       exists=path.is_file(), bytes='', sha256='', rows='', columns='',
                       inspection='missing', application='not_measured')
            if path.is_file():
                pin(path)
                row.update(bytes=path.stat().st_size, sha256=INPUTS[path.resolve()]['sha256'])
                if path.stat().st_size > 64 * 1024 * 1024:
                    row['inspection'] = 'metadata_only_over_64MiB_bound'
                elif path.suffix == '.csv':
                    sqlpath = path.as_posix().replace("'", "''")
                    try:
                        con.execute(f"CREATE OR REPLACE TEMP VIEW control_input AS SELECT * FROM read_csv('{sqlpath}', header=true, all_varchar=true)")
                        row.update(rows=con.execute('SELECT count(*) FROM control_input').fetchone()[0],
                                   columns=json.dumps([r[0] for r in con.execute('DESCRIBE control_input').fetchall()]),
                                   inspection='DuckDB count/schema only; no selector application')
                    except Exception as exc:
                        row['inspection'] = 'unreadable: ' + str(exc)[:500]
                else:
                    obj = json.loads(path.read_text(encoding='utf-8-sig'))
                    row.update(columns=json.dumps(sorted(obj) if isinstance(obj,dict) else []),
                               inspection='JSON shape only; not admission verification')
            rows.append(row)
    finally:
        con.close()
    emit('control_inputs.csv', rows)
    emit('control_constants.json', dict(
        fund_financials_scale_overrides=config.FUND_FINANCIALS_SCALE_OVERRIDES,
        nport_exclude_ciks=sorted(config.NPORT_EXCLUDE_CIKS),
        display_end_quarter=config.INDEX_DISPLAY_END_QUARTER,
        loaded_fund_highlights_wrappers=len(fund_highlights_wrapper.get_all_highlights_wrappers()),
        interpretation='Pinned current code values; not owner-approved changes or runtime exposure'))
    return rows


def runtime_probes(pd, ap, ab, cl, bw, sb, bridge, uh, utils):
    fixture = OUT / 'fixtures'
    fixture.mkdir()
    results = []
    def save(name, obj):
        path = fixture / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj,indent=2),encoding='utf-8')
        return path
    def record(name, observed, **extra):
        results.append(dict(probe=name, basis='synthetic <=20-row isolated replay; not source accuracy', observed=observed, **extra))
        emit('runtime_probes.json', results)
        print('Completed probe: ' + name, flush=True)
    def leaf(fc, template):
        return dict(cik='0000000123',mechanism='fixture',fix_class=fc,template=template,
                    scope={'quarters':['2025-12-31']},source_review_ids=['FIXTURE'],
                    evidence_citations=[{'quoted_text':'Synthetic fixture, not SEC evidence','table_index':1,'row_index':1}],confidence=0.9)

    target = pd.DataFrame([dict(cik='0000000123',source='bdc',report_date='2025-12-31',issuer_name='Same Borrower',
                                fair_value=100.0,interest_rate=10.0,index_classification=category)
                           for category in ('DIRECT_LENDING','STRUCTURED_CREDIT')])
    classification = leaf('classification_fix',dict(field='index_classification',value='DIRECT_LENDING'))
    dedup = leaf('dedup',dict(match_fields=['issuer_name','index_classification'],keep='first'))
    ordered = [classification,dedup]
    save('order_leaves.json',ordered)
    validation = [cl.validate_correction(c).errors for c in ordered]
    if any(validation):
        raise RuntimeError('Ordering fixtures invalid: ' + str(validation))
    prod, pa = ap.apply_promoted_stage2_corrections(target.copy(), ordered)
    trial, ta = ab.run_corrections(target.copy(), ordered)
    record('B2_order', dict(production_rows=len(prod),verifier_rows=len(trial),
                            production_order=[a['rule_id'] for a in pa],verifier_order=[a['fix_class'] for a in ta],
                            production_fv=float(prod.fair_value.sum()),verifier_fv=float(trial.fair_value.sum())),
           input_rows=target.to_dict('records'), valid_leaf_schema=True)

    controls = pd.concat([target.iloc[:1], target.iloc[:1].assign(cik='0000000456'),
                          target.iloc[:1].assign(source='nport'),target.iloc[:1].assign(report_date='2025-09-30')],ignore_index=True)
    rate = leaf('rate_rescale',dict(field='interest_rate',factor=0.1))
    scoped, audits = ap.apply_promoted_stage2_corrections(controls.copy(),[rate])
    record('B2_scope_counterexamples',scoped[['cik','source','report_date','interest_rate']].to_dict('records'), audits=audits)
    unadmitted = dict(cik='0000000123',fix_class='rate_rescale',template={'field':'interest_rate','factor':0.1})
    save('b2/0000000123/rate_rescale.proposed.json',unadmitted)
    loaded = ap.load_promoted_corrections(fixture/'b2')
    changed, audits = ap.apply_promoted_stage2_corrections(controls.copy(),loaded)
    record('B2_unadmitted_proposed',dict(loaded=len(loaded),schema_errors=cl.validate_correction(unadmitted).errors,
                                        rates=changed.interest_rate.tolist()), audits=audits)

    bridge_leaf = dict(schema_version=bridge.BRIDGE_SCHEMA_VERSION,cik='123',bridges=[dict(
        accession_number='fixture-accession',report_date='2025-12-31',raw_id_lower='fixture loan',
        family='debt',issuer_name='Fixture',html_sha256='f'*64,table_index=1,row_index=2)])
    save('bridges/123.proposed.json',bridge_leaf)
    bridge_rows = bridge.load_html_section_bridge_rows(fixture/'bridges')
    record('HTML_proposed_admission',dict(rows_loaded=len(bridge_rows),source_hash_verified_by_loader=False))

    wrapper = dict(schema_version='bdc-xbrl-wrapper.v3',cik='0000000123',version=1,
                   dispatch={'rule_prefix':'FIXTURE','prefix_rules':{'debt':'debt'}},
                   staging={'strategy':'fixture_trial_only'})
    save('wrappers/0000000123.json',wrapper)
    prior_specs = bw.WRAPPER_SPECS
    try:
        bw.reload_wrapper_specs(fixture/'wrappers')
        record('wrapper_trial_resolvers',dict(dispatch_overlay_loaded=bw.get_wrapper_spec('123') is not None,
                                              trial_staging_loaded='0000000123' in sb._load_staging_configs(),
                                              staging_dir=str(sb._WRAPPER_DEFINITIONS_DIR.relative_to(ROOT))))
    finally:
        bw.WRAPPER_SPECS = prior_specs

    from pipeline.gics_classification import _apply_gics_to_holdings, _normalize_company_name
    gics = pd.DataFrame([dict(issuer_name='Known Corp',canonical_name='',gics_sub_industry='Application Software'),
                         dict(issuer_name='Uncached Corp',canonical_name='',gics_sub_industry='Health Care Equipment')])
    cache = {_normalize_company_name('Known Corp'):('Systems Software','high','fixture')}
    gout = _apply_gics_to_holdings(gics.copy(),cache)
    record('GICS_cache_replacement',dict(before=gics.gics_sub_industry.tolist(),after=gout.gics_sub_industry.tolist()))

    empty_path = fixture/'empty'/'private_markets_holdings.csv'
    empty_result = uh.build_unified_holdings(bdc_df=pd.DataFrame(),nport_df=pd.DataFrame(),
                        output_file=empty_path,orphan_file=fixture/'empty'/'orphan.csv',
                        b2_corrections_dir=fixture/'none',agent_rules_dir=fixture/'none')
    record('empty_unified_bundle',dict(rows=len(empty_result),csv=empty_path.exists(),parquet=empty_path.with_suffix('.parquet').exists()))

    wrong = fixture/'strict'/'private_markets_holdings.csv'
    wrong.parent.mkdir()
    wrong.write_text('wrong_column\nvalue\n',encoding='utf-8')
    companion = utils.write_parquet_companion(wrong)
    strict_error = ''
    try:
        utils.write_parquet_companion(wrong,strict=True)
    except Exception as exc:
        strict_error = type(exc).__name__
    record('isolated_companion_strictness',dict(default_created=companion is not None,explicit_strict_error=strict_error))

    # Exercise real finalizer control flow with pre-staged one-row data. External
    # lookups/caches and staging are replaced explicitly: this is not a full build.
    staged = {c:'' for c in uh.UNIFIED_COLUMNS}
    staged.update(cik='0000000123',source='bdc',report_date='2025-12-31',filing_date='2026-02-01',
                  accession_number='fixture',entity_name='Fixture BDC',issuer_name='Fixture Borrower',
                  instrument_description='First Lien Term Loan',asset_category='LOAN',issuer_category='CORPORATE',
                  fair_value=100.0,cost=90.0,principal_amount=100.0,principal_amount_usd=100.0,
                  interest_rate=10.0,basis_spread=5.0,pik_rate=0.0,shares_held=0.0,pct_of_net_assets=1.0,
                  bdc_investment_identifier='Fixture Borrower First Lien Term Loan',is_subsidiary=0)
    noop_names = ['_apply_universe_gate','_stabilize_classification','_restore_deterministic_classification_rules',
                  '_correct_pct_of_net_assets','_apply_row_corrections','_apply_fund_strategy_corrections',
                  '_apply_fund_strategy_asset_class_override','_apply_gics_cache','_apply_lien_cache',
                  '_apply_unclassified_cache','_apply_wrapper_position_keys','_apply_re_fund_gics_overrides']
    for case, correction in [('b2_only',rate),('b2_error',leaf('rate_rescale',dict(field='interest_rate',factor=0.1,row_selector={'missing_column':'x'})))]:
        base = fixture/case
        save(f'{case}/b2/0000000123/rate_rescale.json',correction)
        captured = []
        original_apply = ap.apply_promoted_stage2_corrections
        def capture(frame, leaves):
            output, audit = original_apply(frame,leaves)
            captured.extend(audit)
            return output,audit
        with ExitStack() as stack:
            stack.enter_context(patch.object(sb,'_prepare_bdc',return_value=pd.DataFrame([staged])))
            stack.enter_context(patch.object(uh.staging_nport,'_prepare_nport',return_value=pd.DataFrame(columns=uh.UNIFIED_COLUMNS)))
            for name in noop_names:
                stack.enter_context(patch.object(uh,name,side_effect=lambda frame,*a,**kw: frame))
            for name in ('ENTITY_LOOKUP_FILE','IDENTIFIER_EXTRACTION_LOOKUP_FILE'):
                stack.enter_context(patch.object(uh,name,fixture/'absent.csv'))
            stack.enter_context(patch.object(ap,'apply_promoted_stage2_corrections',side_effect=capture))
            result = uh.build_unified_holdings(bdc_df=pd.DataFrame(),nport_df=pd.DataFrame(),
                        output_file=base/'private_markets_holdings.csv',orphan_file=base/'orphan.csv',
                        b2_corrections_dir=base/'b2',agent_rules_dir=fixture/'none')
        record(case+'_finalizer',dict(rows=len(result),interest_rate=result.interest_rate.tolist(),
                                     output_written=(base/'private_markets_holdings.csv').exists(),
                                     audit_file_written=(base/'agent_fix_application_audit.csv').exists(),audits=captured),
               boundary='real finalizer/B2/writer; source staging and unrelated late helpers stubbed',stubbed=noop_names)
    return results


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    OUT = (ROOT/args.output).resolve()
    if not OUT.is_relative_to(ROOT/'scratch') and not OUT.is_relative_to(ROOT/'docs/production_stack/programme_rule_evidence_2026-09-09'):
        raise ValueError('Output must be session scratch or the named rule evidence directory')
    if OUT.exists():
        raise ValueError('Use a new output directory; evidence is immutable')
    OUT.mkdir(parents=True)
    started = datetime.now(timezone.utc).isoformat()
    timer = threading.Timer(240,lambda: os._exit(124))
    timer.daemon=True
    timer.start()
    print('Snapshot protected artifact metadata',flush=True)
    before = protected_stats()
    real_open, real_io_open = builtins.open, io.open
    def guarded(original):
        def op(file,mode='r',*args,**kwargs):
            if isinstance(file,(str,bytes,os.PathLike)) and any(c in str(mode) for c in 'wax+'):
                if not Path(file).resolve().is_relative_to(OUT):
                    raise PermissionError('Audit write outside isolated output: '+str(file))
            return original(file,mode,*args,**kwargs)
        return op
    def no_network(*args,**kwargs):
        raise RuntimeError('Network disabled for programme rule audit')
    summary = dict(started_utc=started,status='running',production_rebuild=False,source_accuracy_measured=False)
    try:
        with ExitStack() as guard:
            guard.enter_context(patch('builtins.open',guarded(real_open)))
            guard.enter_context(patch('io.open',guarded(real_io_open)))
            guard.enter_context(patch.object(socket.socket,'connect',no_network))
            guard.enter_context(patch.object(socket,'create_connection',no_network))
            logstream = (OUT/'runtime.log').open('w',encoding='ascii',errors='backslashreplace')
            guard.callback(logstream.close)
            logging.basicConfig(stream=logstream,level=logging.WARNING,force=True)
            import duckdb
            import pandas as pd
            original_connect=duckdb.connect
            class GuardedConnection:
                def __init__(self, con): self.con=con
                def check(self, query):
                    if re.search(r'(?i)\b(COPY|EXPORT|ATTACH|INSTALL|LOAD)\b',str(query)):
                        target=re.search(r"(?i)\bCOPY\b[\s\S]*?\bTO\s+'([^']+)'",str(query))
                        if not target or not Path(target.group(1)).resolve().is_relative_to(OUT):
                            raise PermissionError('Native SQL IO outside isolated output')
                def execute(self, query, *args, **kwargs):
                    self.check(query)
                    self.con.execute(query,*args,**kwargs)
                    return self
                def sql(self, query, *args, **kwargs):
                    self.check(query)
                    return self.con.sql(query,*args,**kwargs)
                def __getattr__(self, name): return getattr(self.con,name)
            def limited_connect(*args,**kwargs):
                if args and str(args[0]) not in ('',':memory:'):
                    raise RuntimeError('Only in-memory DuckDB permitted')
                con=original_connect(*args,**kwargs)
                con.execute("SET threads=2")
                con.execute("SET memory_limit='1GB'")
                con.execute("SET temp_directory=''")
                return GuardedConnection(con)
            guard.enter_context(patch.object(duckdb,'connect',limited_connect))
            from pipeline import agent_promoted as ap, agent_b2_appliers as ab, correction_leaf as cl
            from pipeline import bdc_xbrl_wrapper as bw, staging_bdc as sb, bdc_xbrl_html_bridge as bridge
            from pipeline import unified_holdings as uh, utils, agent_rule
            for path in (ROOT/'pipeline').rglob('*.py'):
                pin(path)
            for path in Path(__file__).parent.glob('*'):
                if path.is_file(): pin(path)
            for name in ('rebuild_unified_cik_trial.py','rebuild_outputs.py','run_quarter_pass.py'):
                pin(ROOT/'scripts'/name)
            print('Build rule families and source-site inventory',flush=True)
            families,gaps=static_inventory()
            print('Read live loader surfaces and validate leaves without applying to holdings',flush=True)
            assets,loaders=asset_inventory(ap,bw,sb,bridge,cl,agent_rule)
            print('Count bounded control and lookup inputs',flush=True)
            controls=control_inventory(duckdb)
            print('Replay isolated control and precedence cases',flush=True)
            probes=runtime_probes(pd,ap,ab,cl,bw,sb,bridge,uh,utils)
            summary.update(status='complete',families=len(families),assets=len(assets),loaders=loaders,
                           unresolved_function_names=gaps,probes=len(probes),
                           control_inputs=len(controls),
                           assets_by_family=dict(Counter(a['family'] for a in assets)),
                           schema_error_assets=[a['path'] for a in assets if a['schema_errors'] not in ('','[]')],
                           versions={'python':sys.version.split()[0],'duckdb':duckdb.__version__,'pandas':pd.__version__})
    except Exception as exc:
        summary.update(status='incomplete',error=type(exc).__name__+': '+str(exc))
        import traceback
        summary['traceback']=traceback.format_exc()
    finally:
        print('Verify protected artifacts and pinned input identity',flush=True)
        after=protected_stats()
        drift=[p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)]
        input_drift=[v['path'] for p,v in INPUTS.items() if not p.exists() or (p.stat().st_size,p.stat().st_mtime_ns)!=(v['size'],v['mtime_ns'])]
        summary.update(finished_utc=datetime.now(timezone.utc).isoformat(),protected_files=len(before),
                       metadata_scope='top-level data/output files plus recursive frontend/public/data; not historical output tree',
                       protected_artifact_drift=drift,pinned_input_drift=input_drift,
                       head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        emit('input_manifest.csv',list(INPUTS.values()))
        emit('run_summary.json',summary)
        emit('worktree.json',subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).splitlines())
        timer.cancel()
    print(json.dumps({k:summary[k] for k in ('status','protected_files','protected_artifact_drift','pinned_input_drift')},sort_keys=True),flush=True)
    if summary['status']!='complete' or drift or input_drift or summary.get('unresolved_function_names'):
        print(summary.get('error') or str(summary.get('unresolved_function_names')),flush=True)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
