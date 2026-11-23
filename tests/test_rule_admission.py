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


# --- content identity across platforms -------------------------------------------------
# Git checks a text file out with CRLF line ends on Windows and LF on Linux. The hash
# recorded at admission is of the bytes on the admitting machine, so the gate must accept
# the other platform's form of the same content, and nothing else.

_WINDOWS=b'{\r\n"rate": 1.25,\r\n"note": "a b"\r\n}\r\n'
_LINUX=_WINDOWS.replace(b'\r\n',b'\n')


def _promoted(tmp_path,recorded_bytes):
    base=tmp_path/'rules';base.mkdir()
    leaf=base/'fix.json';leaf.write_bytes(recorded_bytes)
    admission.register_promotion(base,leaf,evidence={'verdict':'PASS'})
    return base,leaf


@pytest.mark.parametrize('recorded,checked_out',[(_WINDOWS,_LINUX),(_LINUX,_WINDOWS),
    (_WINDOWS,_WINDOWS),(_LINUX,_LINUX)])
def test_same_content_is_admitted_under_either_line_ending(tmp_path,recorded,checked_out):
    base,leaf=_promoted(tmp_path,recorded)
    leaf.write_bytes(checked_out)
    assert admission.admitted(leaf,base)


@pytest.mark.parametrize('recorded',[_WINDOWS,_LINUX])
@pytest.mark.parametrize('label,edit',[
    ('one digit',lambda b:b.replace(b'1.25',b'1.26')),
    ('space inside a value',lambda b:b.replace(b'a b',b'a  b')),
    ('trailing space',lambda b:b.replace(b'1.25,',b'1.25, ')),
    ('blank line added',lambda b:b+(b'\r\n' if b'\r\n' in b else b'\n')),
    ('last line end removed',lambda b:b.rstrip(b'\r\n')),
    ('carriage return inside a line',lambda b:b.replace(b'"rate":',b'"rate":\r')),
    ('byte-order mark',lambda b:b'\xef\xbb\xbf'+b),
    ('key renamed',lambda b:b.replace(b'"rate": 1.25,',b'"rat": 1.25,')),
])
def test_any_other_change_is_still_refused_under_either_line_ending(tmp_path,recorded,label,edit):
    base,leaf=_promoted(tmp_path,recorded)
    for form in (recorded,recorded.replace(b'\r\n',b'\n'),
                 recorded.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')):
        changed=edit(form)
        assert changed!=form,label
        leaf.write_bytes(changed)
        with pytest.raises(ValueError,match='no longer matches'):
            admission.admitted(leaf,base)


def test_inventoried_legacy_rule_tolerates_line_endings_but_not_an_edit(tmp_path):
    base=tmp_path/'rules';base.mkdir()
    leaf=base/'fix.json';leaf.write_bytes(_WINDOWS)
    (base/'admission_manifest.json').write_text(json.dumps(dict(format_version=2,entries={
        'fix.json':dict(admission_status='legacy_unverified',sha256=sha(leaf))})))
    leaf.write_bytes(_LINUX)
    assert admission.admitted(leaf,base)
    leaf.write_bytes(_LINUX.replace(b'1.25',b'1.26'))
    with pytest.raises(ValueError,match='changed after admission inventory'):
        admission.admitted(leaf,base)


def test_line_ending_tolerance_is_limited_to_json(tmp_path):
    leaf=tmp_path/'fix.csv';leaf.write_bytes(_WINDOWS)
    recorded=sha(leaf)
    assert admission.content_matches(leaf,recorded)
    leaf.write_bytes(_LINUX)
    assert not admission.content_matches(leaf,recorded)
    assert not admission.content_matches(leaf,'')
    assert not admission.content_matches(leaf,None)


def test_tracked_fx_quotes_are_admitted_on_this_platform():
    """The checked-in FX package must pass its own manifest on Windows and on Linux CI."""
    from pipeline import config
    package=config.PROJECT_ROOT/'data'/'reference'/'monetary_conversion'
    assert admission.admitted(package/'quotes.json',package,allow_legacy=False)


def test_mixed_line_endings_count_as_the_same_content(tmp_path):
    """A checkout that leaves some lines CRLF and some LF is still only a line-ending change."""
    base,leaf=_promoted(tmp_path,_WINDOWS)
    leaf.write_bytes(_WINDOWS.replace(b'1.25,\r\n',b'1.25,\n'))
    assert admission.admitted(leaf,base)
