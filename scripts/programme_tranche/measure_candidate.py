"""Read-only measurements of one verified supported candidate, all 28 criteria."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
import re
import threading
import time

import duckdb

from pipeline.programme.artifacts import literal, STAGE_CSVS, required
from pipeline.programme.catalog import CRITERIA, METRIC_UNITS
from pipeline.programme.core import ContractError, atomic_json, digest, read_json, read_stage, record, sha, verify_records
from pipeline.programme.measurement import CONTRACTS, evaluate, compare_amendment, validate_reference
from pipeline.programme.runner import candidate_path, latest, verify_snapshot

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'docs/production_stack/programme_closeout_evidence_2026-09-09'
OUT_ROOT = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10'
STARTING_RESULTS = {
    'unified-01': 'c350c650e1aee8cda8d1b2d8444708c4fc341024cabb29008a05d6790159a825',
    'identity-02': 'a111eafc4535a7ac81aabfa05608c40793facc742a2350dae53d10172be497fb',
}
GAPS = {
    'A2': 'The four complete development schedules lack independent approval; the cohort roster frame remains incomplete.',
    'A3': 'The target source-selection plan has not been compiled and checked across the required history.',
    'A4': 'A complete candidate-bound supplemental-source disposition ledger is not implemented.',
    'A5': 'Independent accounting bridges for cash, parent interests and underlying schedules remain incomplete.',
    'B1': 'The target field/schema migration is a later package; this candidate deliberately preserves legacy semantics.',
    'B2': 'Independent field references, eligibility and source-specific tolerances are not complete.',
    'B3': 'Primary anchors and comparable accounting scopes have not been independently certified across the required history.',
    'B4': 'The production frontend export and contributor-ID partition checks are outside this compatibility run.',
    'B5': 'Legacy cash-leg storage is retained. The atomic all-in-rate and income-formula migration remains required.',
    'C1': 'Stable entity-identifier lifecycle acceptance scenarios are not implemented.',
    'C2': 'Development entity regression is reported separately; independent precision/recall sampling is unavailable.',
    'C3': 'Development pair regression is reported separately; independent full-chain and continuation references remain incomplete.',
    'C4': 'The registry remains opt-in and production-compatible IDs can renumber; target lifecycle scenarios are not implemented.',
    'D1': 'Target field-level reported/calculated/inferred/default/proxy evidence contracts are not fully implemented.',
    'D2': 'The complete enrichment decision and replay ledger is a later implementation package.',
    'D3': 'Independent sector-assignment review is unavailable; populated codes establish availability only.',
    'D4': 'The production PDF/source-citation viewer is not implemented by the local review briefing.',
    'D5': 'Released numerical displays are not yet instrumented for a complete source-highlight/evidence-path census.',
    'E1': 'The complete target holdings product interface has not been rebuilt and checked on this candidate.',
    'E2': 'Target analytic definitions and denominator displays have not been evaluated on a candidate-bound public export.',
    'E3': 'No fresh benchmark of the target public citation/holdings product was run; local review-page tests are separate.',
    'F1': 'The target authoritative-writer graph and dbt execution are subsequent migration work.',
    'F2': 'Strict parity and starting-result comparisons cover the three compatibility stages; whole target-release repeatability remains unmeasured.',
    'F3': 'Candidate failure isolation is tested separately; the complete production adoption transaction is not implemented.',
    'F4': 'Candidate stage recovery is tested separately; the entire future release workflow is not covered.',
    'F5': 'Worker protection is tested separately; independent reference-review authority and final acceptance controls remain incomplete.',
    'F6': 'No production migration or new signed-quarter attestation is performed in this tranche. Semantic preservation is reported separately.',
}


def write_query(connection, query, path):
    connection.execute('COPY (' + query + ') TO ' + literal(path.as_posix()) + ' (HEADER)')


def difference(connection, left, right, columns):
    cols = ','.join('"' + column.replace('"', '""') + '"' for column in columns)
    a = 'SELECT ' + cols + ' FROM ' + left
    b = 'SELECT ' + cols + ' FROM ' + right
    return connection.execute('SELECT count(*) FROM ((' + a + ' EXCEPT ALL ' + b +
                              ') UNION ALL (' + b + ' EXCEPT ALL ' + a + '))').fetchone()[0]


def partition_difference(connection, field):
    """Compare observation memberships; generated IDs are not cross-rebuild keys."""
    for source, name in (('h', 'new_partition'), ('old_identity', 'old_partition')):
        if connection.execute("SELECT count(*) FROM " + source + " WHERE nullif(row_id,'') IS NULL").fetchone()[0]:
            raise ContractError('Identity partition comparison needs recorded observation keys')
        connection.execute('CREATE OR REPLACE TEMP TABLE ' + name + ' AS SELECT '
            "nullif(CAST(" + field + " AS VARCHAR),'') IS NOT NULL assigned,"
            'sha256(to_json(list(row_id ORDER BY row_id))) membership,count(*) member_count FROM ' + source +
            " GROUP BY nullif(CAST(" + field + " AS VARCHAR),'')")
    return difference(connection, 'new_partition', 'old_partition', ['assigned','membership','member_count'])


def identity_regression(connection, out):
    previous = read_json(OLD / 'identity/input_manifest.json')
    for item in previous['reference_files']:
        if sha(ROOT / item['path'].replace('\\', '/')) != item['sha256']:
            raise ContractError('Previously exposed identity reference changed')
    connection.execute('CREATE TEMP TABLE pairs AS SELECT * FROM read_csv(' +
        literal((OLD / 'identity/position_and_proposed_pairs.csv').as_posix()) + ',header=true,all_varchar=true)')
    connection.execute('CREATE TEMP TABLE unique_rows AS SELECT row_id,first(position_id) position_id,first(entity_id) entity_id FROM h GROUP BY row_id HAVING count(*)=1')
    scored_query = '''SELECT p.* EXCLUDE(status,same_candidate_identity),
        CASE WHEN required_period_scope <> 'True' THEN 'outside_required_period'
             WHEN a.row_id IS NULL OR b.row_id IS NULL THEN 'missing_or_ambiguous_source_row'
             WHEN expected='UNCERTAIN' THEN 'uncertain_reference'
             WHEN nullif(a.position_id,'') IS NULL OR nullif(b.position_id,'') IS NULL THEN 'unresolved_candidate_identity'
             WHEN (a.position_id=b.position_id)=(expected='CONFIRMED') THEN 'correct'
             WHEN expected='CONFIRMED' THEN 'missed_same_identity' ELSE 'false_merge' END status,
        a.position_id=b.position_id same_candidate_identity
        FROM pairs p LEFT JOIN unique_rows a ON p.row_a=a.row_id LEFT JOIN unique_rows b ON p.row_b=b.row_id'''
    if connection.execute("SELECT count(*) FROM pairs WHERE kind<>'position'").fetchone()[0]:
        raise ContractError('Identity regression pair kinds changed; revise scorer explicitly')
    write_query(connection, scored_query, out / 'position_pair_regression.csv')
    counts = dict(connection.execute('SELECT status,count(*) FROM (' + scored_query + ') GROUP BY status').fetchall())
    entities = read_json(OLD / 'identity/entity_packet_results.json')
    ids = sorted({row for entity in entities for row in entity['row_ids']})
    if len(ids) > 10000:
        raise ContractError('Entity regression exceeds bounded development frame')
    lookup = dict(connection.execute('SELECT row_id,entity_id FROM unique_rows WHERE row_id IN (SELECT unnest(?))', [ids]).fetchall())
    results = []
    for entity in entities:
        values = [lookup.get(row) for row in entity['row_ids']]
        valid = all(values)
        same = len(set(values)) == 1 if valid else None
        if not entity['required_period_scope']:
            status = 'outside_required_period'
        elif not valid:
            status = 'missing_or_ambiguous_or_unresolved_row'
        elif entity['verdict'] == 'CONFIRMED':
            status = 'correct' if same else 'false_split'
        elif entity['verdict'] == 'WRONG_MERGE':
            status = 'false_merge' if same else 'negative_cluster_separated'
        else:
            status = 'requires_explicit_pair_adjudication'
        results.append(dict(entity, status=status, candidate_all_same=same))
    atomic_json(out / 'entity_regression.json', results)
    return dict(position=counts, entity=dict(Counter(item['status'] for item in results)),
                exposure='Previously used development regression; no independent cohort accuracy claim',
                reference_manifest_sha256=sha(OLD / 'identity/input_manifest.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--evaluation', default='evaluation-v1')
    args = parser.parse_args()
    if any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for char in args.evaluation):
        raise ContractError('Invalid evaluation name')
    timer = threading.Timer(1200, lambda: os._exit(124)); timer.daemon = True; timer.start()
    started = time.monotonic()
    candidate = candidate_path(args.candidate)
    manifest = verify_snapshot(candidate)
    stages = {stage: latest(candidate, stage, manifest) for stage in STAGE_CSVS}
    out = OUT_ROOT / args.evaluation
    out.mkdir(parents=True, exist_ok=False)
    identities = {stage: sha(attempt / 'result.json') for stage, attempt in stages.items()}
    candidate_fingerprint = digest(dict(snapshot=manifest['input_fingerprint'], stages=identities))
    prior = candidate_path('spec-close-20260909-v2')
    obligations_path = ROOT / 'docs/production_stack/programme_pilot_evidence_2026-09-09/obligations_v2.csv'
    taxonomy_path = candidate / 'frozen/data/reference/gics_hierarchy.json'
    registry_path = OUT_ROOT / 'references-v1/registry.json'
    source_inputs = [obligations_path, taxonomy_path, registry_path,
        OLD / 'identity/input_manifest.json', OLD / 'identity/position_and_proposed_pairs.csv',
        OLD / 'identity/entity_packet_results.json', Path(__file__),
        *sorted(CONTRACTS.glob('*.json')),
        *(ROOT / 'pipeline/programme' / name for name in ('measurement.py','catalog.py','core.py','runner.py','native.py','artifacts.py'))]
    pinned_inputs = [record(ROOT,path.relative_to(ROOT).as_posix()) for path in source_inputs]
    for name, expected_hash in STARTING_RESULTS.items():
        bundle = prior / 'attempts' / name / 'bundle'
        marker, previous = read_json(bundle / 'complete.json'), read_json(bundle / 'result.json')
        if sha(bundle / 'result.json') != expected_hash or marker['result_sha256'] != expected_hash or previous['execution'] != 'complete':
            raise ContractError('Frozen starting result identity changed')
        if marker['input_fingerprint'] != previous['input_fingerprint']:
            raise ContractError('Starting comparison has mixed dependencies')
        verify_records(bundle,previous['artifacts'])
        pinned_inputs.extend(record(ROOT,(bundle / filename).relative_to(ROOT).as_posix())
                             for filename in ('complete.json','result.json','private_markets_holdings.parquet'))
    atomic_json(out / 'inputs.json',dict(candidate_fingerprint=candidate_fingerprint,
        files=pinned_inputs, starting_results=STARTING_RESULTS, stage_results=identities))
    registry = read_json(registry_path)
    references = {reference['reference_id']: reference for reference in registry['references']}
    for reference in references.values():
        validate_reference(reference, ROOT)
    connection = duckdb.connect()
    connection.execute('SET threads=2'); connection.execute("SET memory_limit='4GB'")
    temporary = ROOT / 'scratch/2026-09-10_programme_tranche' / args.evaluation
    temporary.mkdir(exist_ok=True)
    connection.execute('SET temp_directory=' + literal(temporary.as_posix()))
    for name, path in (
        ('h', stages['identity'] / 'bundle/private_markets_holdings.parquet'),
        ('unified', stages['unified'] / 'bundle/private_markets_holdings.parquet'),
        ('old_unified', prior / 'attempts/unified-01/bundle/private_markets_holdings.parquet'),
        ('old_identity', prior / 'attempts/identity-02/bundle/private_markets_holdings.parquet')):
        connection.execute('CREATE VIEW ' + name + ' AS SELECT * FROM read_parquet(' + literal(path.as_posix()) + ')')
    connection.execute('CREATE VIEW obligations AS SELECT * FROM read_csv(' + literal(obligations_path.as_posix()) + ',header=true,all_varchar=true)')
    taxonomy = read_json(taxonomy_path)
    connection.execute('CREATE TABLE sectors(subindustry VARCHAR, sector VARCHAR)')
    connection.executemany('INSERT INTO sectors VALUES (?,?)', [(key, value['sector']) for key, value in taxonomy.items()])
    connection.execute('''CREATE VIEW selected AS SELECT h.*,s.sector gics_sector FROM h
        JOIN obligations o ON lpad(CAST(h.cik AS VARCHAR),10,'0')=o.cik AND CAST(h.report_date AS VARCHAR)=o.report_date
        LEFT JOIN sectors s ON h.gics_sub_industry=s.subindustry''')
    connection.execute('''CREATE VIEW obligation_result AS WITH counts AS (
        SELECT lpad(CAST(cik AS VARCHAR),10,'0') cik,CAST(report_date AS VARCHAR) report_date,count(*) n_rows FROM h GROUP BY ALL)
        SELECT o.*,coalesce(c.n_rows,0) candidate_rows FROM obligations o LEFT JOIN counts c USING(cik,report_date)''')
    write_query(connection, 'SELECT * FROM obligation_result ORDER BY cik,report_date', out / 'obligations.csv')
    quarter_query = '''SELECT report_date,count(*) AS "rows",count(distinct cik) funds,sum(fair_value) signed_fv,
        sum(abs(fair_value)) absolute_fv,count(*) FILTER(WHERE fair_value IS NULL) missing_fv,
        count(*) FILTER(WHERE nullif(gics_sector,'') IS NOT NULL) gics_rows,
        sum(abs(fair_value)) FILTER(WHERE nullif(gics_sector,'') IS NOT NULL) gics_abs_fv,
        count(*) FILTER(WHERE nullif(entity_id,'') IS NULL) missing_entity_id,
        count(*) FILTER(WHERE nullif(position_id,'') IS NULL) missing_position_id
        FROM selected GROUP BY report_date ORDER BY report_date'''
    write_query(connection, quarter_query, out / 'quarter_measurements.csv')
    population = connection.execute('''SELECT count(*),sum(abs(fair_value)),count(*) FILTER(WHERE fair_value IS NULL),
        count(*) FILTER(WHERE nullif(gics_sector,'') IS NOT NULL),sum(abs(fair_value)) FILTER(WHERE nullif(gics_sector,'') IS NOT NULL)
        FROM selected''').fetchone()
    obligations = connection.execute('''SELECT count(*),count(*) FILTER(WHERE eligibility_status LIKE 'eligible%'),
        count(*) FILTER(WHERE eligibility_status LIKE 'eligible%' AND candidate_rows>0),
        count(*) FILTER(WHERE eligibility_status NOT IN ('eligible_source_investments','eligible_operating_interval','not_yet_investment_operating'))
        FROM obligation_result''').fetchone()
    if obligations[0] != 910:
        raise ContractError('Required obligation inventory changed')
    columns = [row[0] for row in connection.execute('DESCRIBE h').fetchall()]
    non_identity = [column for column in columns if column not in ('entity_id', 'position_id', 'canonical_name')]
    token_changes = difference(connection, 'h', 'old_identity', columns)
    identity_values = difference(connection, 'h', 'old_identity',
                                 [column for column in columns if column not in ('entity_id','position_id')])
    position_memberships = partition_difference(connection, 'position_id')
    entity_memberships = partition_difference(connection, 'entity_id')
    comparisons = dict(unified_vs_starting=difference(connection, 'unified', 'old_unified', columns),
                       identity_vs_starting=identity_values + position_memberships + entity_memberships,
                       identity_value_changes=identity_values,
                       position_membership_changes=position_memberships,
                       entity_membership_changes=entity_memberships,
                       identity_nonidentity_change=difference(connection, 'h', 'unified', non_identity))
    # PIK row IDs refer to the exact consumed CSV order and lexical values, not Parquet date formatting.
    connection.execute('CREATE TABLE consumed AS SELECT row_number() OVER()-1 ordinal,* FROM read_csv(' +
        literal((stages['identity'] / 'bundle/private_markets_holdings.csv').as_posix()) + ',header=true,all_varchar=true,parallel=false)')
    connection.execute('CREATE VIEW pik AS SELECT * FROM read_csv(' + literal((stages['evidence'] / 'bundle/position_pik_status.csv').as_posix()) + ',header=true,all_varchar=true,parallel=false)')
    comparisons['pik_parent_mismatches'] = connection.execute('''SELECT count(*) FROM consumed h FULL JOIN pik p ON h.ordinal=CAST(p.holding_row_id AS BIGINT)
        WHERE h.ordinal IS NULL OR p.holding_row_id IS NULL OR h.position_id IS DISTINCT FROM p.position_id
        OR h.cik IS DISTINCT FROM p.cik OR h.source IS DISTINCT FROM p.source
        OR h.report_date IS DISTINCT FROM p.report_date OR h.fair_value IS DISTINCT FROM p.fair_value''').fetchone()[0]
    if any(comparisons.values()):
        atomic_json(out / 'unexplained_stage_changes.json', comparisons)
        raise ContractError('Unexplained financial or stage composition changes; evaluation stopped')
    regression = identity_regression(connection, out)
    log_path = stages['unified'] / 'process.log'
    if log_path.stat().st_size > 5_000_000:
        raise ContractError('Legacy diagnostic log exceeds review allowance')
    warnings = [dict(check=check, rows=int(count)) for check,count in re.findall(
        r'WARNING\s+FAIL ([a-z0-9_]+): (\d+) rows', log_path.read_text(encoding='utf-8',errors='replace'))]
    diagnostics = dict(legacy_column_flags=warnings,
        log=record(ROOT,log_path.relative_to(ROOT).as_posix()),
        meaning='Legacy whole-cache flags, potentially before final overlays. Retained as diagnostics; not independent target-schema acceptance and not limited to the 70-fund cohort.')
    atomic_json(out / 'legacy_diagnostics.json', diagnostics)
    atomic_json(out / 'measurements.json', dict(candidate_fingerprint=candidate_fingerprint, candidate=args.candidate,
        obligations=dict(required=obligations[0], eligible=obligations[1], with_rows=obligations[2], missing=obligations[1]-obligations[2], unknown_status=obligations[3]),
        history=dict(rows=population[0], absolute_fv=population[1], missing_fv_rows=population[2], sector_rows=population[3], sector_abs_fv=population[4]),
        comparisons=comparisons, development_identity_regression=regression,
        generated_identity_token_multiset_difference=token_changes,
        identity_comparison='Row values plus entity/position membership multisets over source row IDs. Generated ID tokens are reported separately, never used as cross-rebuild keys. Duplicate observation keys remain an accuracy limitation; multiplicity is retained.',
        legacy_diagnostics=diagnostics,
        references=dict(development_schedules=61, label_proposals=20, independently_reviewed=0),
        warning='FV availability measures existing holdings only; it does not measure missing source positions or sector accuracy.'))
    evidence = [record(ROOT, (out / 'measurements.json').relative_to(ROOT).as_posix())]
    def observation(metric, value, eligible, *, missing=0, denominator_known=True, formula='', numerator=None, denominator=None):
        return dict(schema_version=1, metric_id=metric, metric_version=1, candidate_fingerprint=candidate_fingerprint,
            scope='cohort_70_required_history', quarter=None, design='census', denominator_known=denominator_known,
            eligible=eligible, assessed=eligible, missing_weight=missing, value=value, unit='fraction' if metric.endswith('coverage') else 'count',
            formula=formula, evidence=evidence, references=[], reason='', numerator=numerator, denominator=denominator)
    observations = {
        'obligation_coverage': observation('obligation_coverage', obligations[2]/obligations[1], obligations[1],
             formula='eligible fund-quarter obligations with holdings / all eligible fund-quarter obligations', numerator=obligations[2], denominator=obligations[1]),
        'unknown_lifecycle_count': observation('unknown_lifecycle_count', obligations[3], obligations[0], formula='unclassified obligation statuses'),
        'sector_row_coverage': observation('sector_row_coverage', population[3]/population[0], population[0],
             formula='existing candidate holdings with mapped GICS sector / all existing candidate holdings', numerator=population[3], denominator=population[0]),
        'sector_fv_coverage': observation('sector_fv_coverage', population[4]/population[1], population[0], missing=population[2],
             formula='absolute FV with mapped GICS sector / total absolute FV of existing candidate holdings', numerator=population[4], denominator=population[1]),
    }
    for criterion, (_, metrics) in CRITERIA.items():
        for metric in metrics:
            if metric not in observations:
                observations[metric] = dict(schema_version=1, metric_id=metric, metric_version=1,
                    candidate_fingerprint=candidate_fingerprint, scope='cohort_70_required_history', quarter=None,
                    design='unmeasured', denominator_known=False, eligible=0, assessed=0, missing_weight=0,
                    value=None, unit=METRIC_UNITS[metric], formula='Not executed; see criterion dependency',
                    evidence=[], references=[], reason=GAPS[criterion])
    # Shared release/identity/rate/UI scenarios are not made to pass by testing
    # only this tranche's subset. Their required missing metrics remain explicit.
    atomic_json(out / 'observations.json', observations)
    contract = read_json(CONTRACTS / 'working-v1.json')
    result = evaluate(contract, observations, candidate_fingerprint, ROOT, references)
    atomic_json(out / 'criterion_results.json', result)
    with (out / 'criterion_inventory.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['criterion_id', 'title', 'status', 'measured_metrics', 'missing_metrics'])
        writer.writeheader()
        for criterion in result['criteria']:
            writer.writerow(dict(criterion_id=criterion['criterion_id'], title=criterion['title'], status=criterion['status'],
                measured_metrics=';'.join(r['metric_id'] for r in criterion['results'] if r['status'] in ('PASS','FAIL')),
                missing_metrics=';'.join(r['metric_id'] for r in criterion['results'] if r['status'] not in ('PASS','FAIL'))))
    verify_records(ROOT,pinned_inputs)
    for stage,attempt in stages.items():
        if sha(attempt / 'result.json') != identities[stage]:
            raise ContractError('Candidate stage changed during evaluation')
        read_stage(attempt,read_json(attempt / 'result.json')['identity'],required(stage))
    atomic_json(out / 'evaluation_manifest.json', dict(schema_version=1, candidate_fingerprint=candidate_fingerprint,
        snapshot=manifest['input_fingerprint'], stages=identities, contract_sha256=digest(contract),
        cohort_obligations=record(ROOT, obligations_path.relative_to(ROOT).as_posix()),
        taxonomy=record(ROOT, taxonomy_path.relative_to(ROOT).as_posix()),
        reference_registry=record(ROOT, registry_path.relative_to(ROOT).as_posix()),
        evaluator=record(ROOT, Path(__file__).relative_to(ROOT).as_posix()),
        files=[record(out, p.relative_to(out).as_posix()) for p in sorted(out.iterdir()) if p.is_file()],
        elapsed_seconds=time.monotonic()-started))
    connection.close(); timer.cancel()
    print('Integrated evaluation: ' + result['verdict'] + '; all 28 criteria recorded', flush=True)


if __name__ == '__main__':
    main()
