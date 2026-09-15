"""Freeze development references and prepare four source-backed remediation packets.

Read-only source inspection. No rule promotion, gold changes or source downloads.
Each document is capped at 120 MB; retained row windows are capped at 1,000 rows.
"""
from __future__ import annotations

import csv
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import threading
import time

from lxml import etree
from pipeline.programme.core import ContractError, atomic_json, record, sha
from pipeline.programme.measurement import validate_reference

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'docs/production_stack/programme_closeout_evidence_2026-09-09'
DEST = ROOT / 'docs/production_stack/programme_tranche_evidence_2026-09-10/references-v1'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


@lru_cache(maxsize=100)
def source_record(relative):
    path = ROOT / relative.replace('\\', '/')
    if path.stat().st_size > 120_000_000:
        raise ContractError('Source exceeds bounded packet size: ' + str(path))
    return record(ROOT, path.relative_to(ROOT).as_posix())


def source_rows(relative, expected_hash, xpaths):
    source = source_record(relative)
    if source['sha256'] != expected_hash:
        raise ContractError('Source document changed: ' + relative)
    tree = etree.parse(str(ROOT / relative.replace('\\', '/')), etree.HTMLParser(no_network=True, recover=True, huge_tree=True))
    results = []
    for xpath in xpaths:
        selected = tree.xpath(xpath)
        if len(selected) != 1:
            raise ContractError('Source locator is not unique: ' + xpath)
        node = selected[0]
        rows = node.xpath('./tr') if node.tag == 'table' else [node]
        if len(rows) > 1000:
            raise ContractError('Extraction exceeds 1,000 review rows')
        for row in rows:
            results.append(dict(xpath=tree.getpath(row), text=' '.join(' '.join(row.itertext()).split())[:6000],
                                cells=[' '.join(' '.join(cell.itertext()).split()) for cell in row.xpath('./td|./th')]))
    return dict(source=source, rows=results)


def freeze():
    if DEST.exists():
        raise ContractError('Reference version already exists; never replace it')
    DEST.mkdir(parents=True)
    with (OLD / 'review/packet_dispositions.csv').open(newline='', encoding='utf-8') as stream:
        dispositions = list(csv.DictReader(stream))
    labels = load(OLD / 'review/legacy_label_decisions.json')
    if len(dispositions) != 61 or len(labels) != 20:
        raise ContractError('Unexpected reference counts; review input version')
    shutil.copy2(OLD / 'review/packet_dispositions.csv', DEST / 'original_packet_dispositions.csv')
    shutil.copy2(OLD / 'review/legacy_label_decisions.json', DEST / 'original_label_proposals.json')
    references = []
    for index, disposition in enumerate(dispositions):
        reference_id = disposition['reference_id']
        payload = DEST / 'payloads' / (reference_id + '.json')
        primary_path = ROOT / disposition['evidence_path'].replace('\\', '/')
        if sha(primary_path) != disposition['evidence_sha256']:
            raise ContractError('Previous packet evidence changed')
        primary = load(primary_path)
        sources = [source_record(primary_path.relative_to(ROOT).as_posix())]
        if primary.get('path') and (ROOT / primary['path']).is_file():
            actual = source_record(primary['path'])
            if primary.get('sha256') and primary['sha256'] != actual['sha256']:
                raise ContractError('Primary source changed since review')
            sources.append(actual)
        atomic_json(payload, dict(original_disposition=disposition, primary_packet=primary,
                    review_request='Independently establish source eligibility, complete lot boundaries, accounting scope, dates, units and unknowns.'))
        reference = dict(schema_version=1, reference_id=reference_id, version='development-v1',
            author='Codex source preparation 2026-09-09', reviewer=None,
            review_status='source_unavailable' if disposition['disposition'] == 'primary_source_unavailable' else 'awaiting_independent_review',
            exposure='development_outputs_seen', scope=dict(unit='fund-quarter', population=disposition['cik'], quarter=disposition['report_date']),
            sources=sources, payload=record(ROOT, payload.relative_to(ROOT).as_posix()), disagreements=[], review_attestation=None)
        validate_reference(reference, ROOT)
        references.append(reference)
        if index % 10 == 0:
            print('Frozen schedule references: ' + str(index + 1), flush=True)
    for label in labels:
        reference_id = 'LABEL-' + str(label['case']).zfill(2)
        payload = DEST / 'payloads' / (reference_id + '.json')
        atomic_json(payload, label)
        source = source_record(label['source_path'])
        if source['sha256'] != label['source_sha256']:
            raise ContractError('Label source changed')
        reference = dict(schema_version=1, reference_id=reference_id, version='development-v1',
            author='Codex source preparation 2026-09-09', reviewer=None, review_status='awaiting_independent_review',
            exposure='development_outputs_seen', scope=dict(unit='source-observation', population=label['original_label']['cik'], quarter=label['original_label']['report_date']),
            sources=[source], payload=record(ROOT, payload.relative_to(ROOT).as_posix()),
            disagreements=[label['reason']] if 'wrong' in label['status'] or 'unresolved' in label['status'] else [], review_attestation=None)
        validate_reference(reference, ROOT)
        references.append(reference)
    atomic_json(DEST / 'registry.json', dict(schema_version=1, version='development-v1',
        author='Codex first-tranche controller', independent_review_authority=None,
        schedule_dispositions=61, label_proposals=20, complete_development_schedules=4,
        independently_reviewed=0, held_out=0, references=references))
    return labels


def packets(labels):
    rosters = load(OLD / 'review/new_development_rosters.json')
    north = next(r for r in rosters if '1950976' in r['reference_id'])
    golub = next(r for r in rosters if '1930087' in r['reference_id'])
    lord = load(ROOT / 'docs/production_stack/programme_pilot_evidence_2026-09-09/lord_reviewed_roster.json')
    ivy, emerald = labels[0], labels[3]
    rows = []
    for key, roster, xpaths in (
        ('26north', north, [r['key'] for r in north['rows']] + [north['rows'][0]['key'].rsplit('/tr[', 1)[0]]),
        ('golub', golub, [golub['rows'][0]['key'], '/html/body/div[71]/table']),
        ('lord_abbett', lord, [lord['roster'][0]['key'], lord['roster'][1]['key'], '/html/body/table[14]/tr[15]']),
        ('ivy_hill', ivy, [ivy['row_xpath'], '/html/body/div[2390]/table/tr[16]']),
        ('emerald_counterexample', emerald, [emerald['row_xpath']])):
        evidence = source_rows(roster['source_path'], roster['source_sha256'], xpaths)
        atomic_json(DEST / 'source_cases' / (key + '.json'), evidence)
        rows.append((key, evidence))
    packets = [
        dict(packet_id='T1-P01', title='26North: untagged four-position schedule', criteria=['A1', 'A2', 'A5', 'B2', 'C3'],
             scope=dict(cik='0001950976', quarter='2023-12-31', source_sha256=north['source_sha256']),
             mechanism='Source schedule is present as literal HTML while candidate has zero rows. Add governed per-CIK extraction for this accession and table; do not synthesize missing XBRL facts.',
             rule_home='Per-CIK HTML extraction/staging configuration; shared parser only for a demonstrated general mechanism.',
             positive='Penn first-lien term loan: FV 24,720,000 USD; separate delayed-draw FV 264,000 and revolver FV -78,000.',
             false_positive='The table total repeats the four-lot sum and is not a fifth position. Three Penn facilities are not one borrower position.',
             expected_changes=dict(rows=4, signed_fv_usd=52566000, absolute_fv_usd=52722000, known_cost_usd=52628000),
             unchanged_validation='Other CIK/quarter row multisets and values unchanged; four unique source rows; preserve the negative revolver; source total and independent lot count both reconcile.',
             confidence='High for source roster/amounts; integration mechanism still needs implementation and independent review.',
             residual_risk='Principal dash does not automatically mean zero. Required-quarter coverage beyond this accession remains unproved.',
             source_cases=['26north']),
        dict(packet_id='T1-P02', title='Golub: retain a named money-market holding', criteria=['A1', 'A2', 'A5', 'B2', 'B4'],
             scope=dict(cik='0001930087', quarter='2023-06-30', source_sha256=golub['source_sha256']),
             mechanism='A named Treasury Portfolio instrument is a position even though it is cash-like. Existing staging/reconciliation has intentional money-market exclusions; the accepted target requires a scoped contract change, not a fund-total overlay.',
             rule_home='Per-CIK cash-instrument extraction plus explicit global retain-named-instrument contract; review existing add_2025q4_money_market_rows mechanism before generalizing.',
             positive='Morgan Stanley Institutional Liquidity Funds Treasury Portfolio, CUSIP 61747C582, FV/cost 650,323,000 USD.',
             false_positive='Do not add the repeated schedule total as a second position, or turn an undifferentiated cash balance into an invented security. Do not apply this amount to another quarter.',
             expected_changes=dict(rows=1, signed_fv_usd=650323000, cost_usd=650323000, classification='named money-market fund / cash equivalent'),
             unchanged_validation='Same one holding contributes once to each public partition. Primary investment anchor uses an explicit cash bridge; other quarters and ordinary cash balances unchanged.',
             confidence='High for the named holding/amount; live reconciliation disposition must be updated with the extraction contract.',
             residual_risk='An investment-only primary anchor may exclude cash equivalents; adding the holding without a scope bridge would create a misleading reconciliation error.', source_cases=['golub']),
        dict(packet_id='T1-P03', title='Lord Abbett: recover schedule while preserving unresolved dashes', criteria=['A2', 'B1', 'B2', 'B3'],
             scope=dict(cik='0002008748', quarter='2024-09-30', source_sha256=lord['source_sha256']),
             mechanism='The source has a complete 33-position/facility schedule and candidate has zero rows. Extract the reviewed schedule; six FV dashes retain unknown numeric meaning until separately resolved.',
             rule_home='Per-CIK wrapper/HTML staging configuration; shared availability-state contract for displayed dashes.',
             positive='RJW funded position has reported FV 2,880,000 USD. The separately disclosed RJW revolver has an FV dash and remains a separate observation.',
             false_positive='Do not convert six dashes to six zero-FV facts because the 27 known amounts happen to sum to the printed total. Do not include the total row as a holding.',
             expected_changes=dict(rows=33, known_fv_rows=27, unresolved_fv_rows=6, known_signed_fv_usd=313562000, known_absolute_fv_usd=314430000, monetary_recall='unassessable until missing weights are resolved'),
             unchanged_validation='Keep negative facilities; source roster count 33; all 27 known FV values match; all six dashes remain unresolved; no fabricated zero and no claimed full FV recall.',
             confidence='High for row boundaries and reported amounts; dash interpretation explicitly unresolved.',
             residual_risk='Equal aggregate totals cannot prove each omitted value is zero; broader historical schedule extraction remains separate.', source_cases=['lord_abbett']),
        dict(packet_id='T1-P04', title='Ivy Hill: distinguish operating-company equity from a credit fund', criteria=['B1', 'B2', 'D3'],
             scope=dict(cik='0001287750', quarter='2025-12-31', source_sha256=ivy['source_sha256'], row_id='ROW-60b2948e98dd3861'),
             priority_basis='Largest source-supported classification residual among the 20 reviewed label proposals: 1,903,400,000 USD. Not claimed as a ranking of all unresolved portfolio entities.',
             mechanism='Member interest is equity in an operating asset-management business. Current PRIVATE_CREDIT_FUND and legacy PRIVATE_EQUITY_FUND labels both miss that business role; legal form alone does not identify a pooled fund.',
             rule_home='Evidence-backed per-investee business-role decision scoped to filer/source observation; then governed instrument/asset classification. No global LP/LLC/member-interest keyword override.',
             positive='Ivy Hill member interest: source cost 1,700,500,000 and FV 1,903,400,000 USD, context c-413.',
             false_positive='BCRED Emerald JV LP is a disclosed senior-secured lending joint venture (FV 1,678,745,000 USD); its LP interest must remain a credit-vehicle exposure.',
             expected_changes=dict(rows=0, total_fv_usd=0, reclassified_fv_usd=1903400000, from_role='private_credit_fund', to_role='operating_company_equity', precise_equity_leaf='unresolved pending rights evidence'),
             unchanged_validation='FV/cost/source identity unchanged; public total unchanged; classification partition shift equals 1,903,400,000; Emerald and other genuine credit vehicles unchanged.',
             confidence='High for operating-company versus credit-vehicle distinction; equity-rights leaf requires further source evidence.',
             residual_risk='Do not turn business-role evidence into an unsupported GICS leaf or common/preferred rights claim.', source_cases=['ivy_hill', 'emerald_counterexample']),
    ]
    for packet in packets:
        packet.update(status='prepared_not_implemented', independent_review='pending', attempts_allowed=2,
                      unchanged_production=True, no_source_downloads=True)
    atomic_json(DEST / 'remediation_packets.json', packets)
    atomic_json(DEST / 'classification_priority.json', [dict(case=label['case'], status=label['status'],
        source_supported_fv=label.get('proposal', {}).get('fair_value_usd'), original_reference_fv=label['original_label'].get('true_fair_value')) for label in labels])


def main():
    
    
    started = time.monotonic()
    labels = freeze()
    packets(labels)
    atomic_json(DEST / 'freeze_manifest.json', dict(schema_version=1, role='development references; no acceptance promotion',
        files=[record(DEST, p.relative_to(DEST).as_posix()) for p in sorted(DEST.rglob('*')) if p.is_file()],
        elapsed_seconds=time.monotonic() - started))
    
    print('Frozen 61 schedule dispositions, 20 label proposals and four remediation packets', flush=True)


if __name__ == '__main__':
    main()
