import json

import pandas as pd
import pytest

from pipeline import rule_admission as admission
from pipeline.programme.core import sha


def test_actual_loader_distinguishes_legacy_proposal_and_hash_bound_promotion(tmp_path):
    base=tmp_path/'rules';folder=base/'123';folder.mkdir(parents=True)
    live=folder/'fix.json';live.write_text('{}')
    proposed=folder/'fix.proposed.json';proposed.write_text('{}')
    @admission.capture_inputs(lambda:tmp_path/'audit')
    def run():
        assert admission.admitted(live,base)
        assert not admission.admitted(proposed,base)
        admission.register_promotion(base,live,evidence={'verdict':'PASS','evaluation_sha256':'pinned'})
        assert admission.admitted(live,base)
        live.write_text('{"changed":true}')
        with pytest.raises(ValueError,match='no longer matches'): admission.admitted(live,base)
        return pd.DataFrame()
    run()
    audit=pd.read_csv(tmp_path/'audit/input_admission_audit.csv')
    assert list(audit.admission_status)==['legacy_unverified','proposed_or_retired','promoted','promoted']
    assert list(audit.loaded)==[True,False,True,False]


def test_manifest_presence_excludes_unlisted_leaf(tmp_path):
    base=tmp_path/'rules';base.mkdir()
    first=base/'first.json';first.write_text('{}')
    admission.register_promotion(base,first,evidence={'verdict':'PASS'})
    other=base/'other.json';other.write_text('{}')
    assert admission.admitted(first,base)
    assert not admission.admitted(other,base)


def test_partial_manifest_cannot_silently_retire_existing_rules(tmp_path):
    first=tmp_path/'first.json';first.write_text('{}')
    other=tmp_path/'other.json';other.write_text('{}')
    with pytest.raises(ValueError,match='partial manifest'):
        admission.register_promotion(tmp_path,first,evidence={'verdict':'PASS'})
    assert not (tmp_path/'admission_manifest.json').exists()


def test_spread_audit_checks_final_value_and_retains_missing_obligation(tmp_path):
    @admission.capture_inputs(lambda:tmp_path)
    def run():
        admission.record_spreads([dict(cik='123',report_date='2026-03-31',identifier=name,agentA_value_pct='5.25') for name in ['A','B']])
        return pd.DataFrame([dict(row_id='R1',cik='0000000123',report_date='2026-03-31',bdc_investment_identifier='A',basis_spread=.0525)])
    run()
    audit=pd.read_csv(tmp_path/'spread_unit_audit.csv').set_index('identifier')
    assert audit.loc['A','actual_pct']==.0525 and audit.loc['A','expected_pct']==5.25
    assert pd.isna(audit.loc['B','actual_pct'])


def test_failed_custom_output_still_audits_only_the_requested_directory(tmp_path):
    default = tmp_path / 'default'
    custom = tmp_path / 'trial' / 'holdings.csv'
    leaf = tmp_path / 'rule.json'
    leaf.write_text('{}')

    @admission.capture_inputs(lambda: default, output_parameter='output_file')
    def run(*, output_file=None):
        admission.record(leaf, 'legacy_unverified', True, 'Synthetic failed build')
        raise ValueError('Build failed')

    with pytest.raises(ValueError, match='Build failed'):
        run(output_file=custom)
    assert not default.exists()
    audit = pd.read_csv(custom.parent / 'input_admission_audit.csv')
    assert list(audit.path) == [str(leaf)]
    assert (custom.parent / 'spread_unit_audit.csv').exists()
