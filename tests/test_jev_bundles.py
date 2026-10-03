"""Evidence failures from the B1 replay must remain visible and cannot clear flags."""
import copy

import pytest

from pipeline import jev_bundles as jb
from scripts.build_jev_bundles import read_inputs


def fact(value, *, scale=3, currency="usd", sign="", fmt=""):
    return f'<ix:nonFraction name="us-gaap:InvestmentOwnedAtCost" contextRef="c-1" unitRef="{currency}" scale="{scale}" sign="{sign}" format="{fmt}">{value}</ix:nonFraction>'


def schedule(rows, *, date="June 30, 2025", units="in thousands", notes="", header="Cost", layout=""):
    return (f'<p>Example BDC Consolidated Schedule of Investments {date} ({units})</p><table {layout}>'
            f'<tr><td>Portfolio Company</td><td>Investment</td><td colspan="3">{header}</td><td colspan="3">Fair Value</td><td>Notes</td></tr>'
            + "".join(f'<tr><td>{name}</td><td>{instrument}</td><td>$</td><td colspan="2">{cost}</td><td>$</td><td colspan="2">{fv}</td><td>{refs}</td></tr>'
                      for name, instrument, cost, fv, refs in
                      [(name, instrument, cost, fv.replace('us-gaap:InvestmentOwnedAtCost', 'us-gaap:InvestmentOwnedAtFairValue'), refs)
                       for name, instrument, cost, fv, refs in rows])
            + f'</table>{notes}')


def parsed(body):
    return jb.parse_source(('<html><body><xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
                            '<xbrli:unit id="cad"><xbrli:measure>iso4217:CAD</xbrli:measure></xbrli:unit>'
                            + body + '</body></html>').encode())


def output(**changes):
    return {"row_id": "ROW-1", "source": "bdc", "cik": "0000000001", "report_date": "2025-06-30",
            "accession_number": "0000000001-25-000001", "issuer_name": "Acme Test LLC",
            "bdc_investment_identifier": "Acme Test LLC Preferred units", "cost": "2000000", "fair_value": "1000",
            "cost_currency": "USD", "fair_value_currency": "USD", **changes}


def bundle(row=None, source=None, rule="X08", **kwargs):
    row = row or output()
    flag = {key: row.get(key) for key in ("row_id", "source", "cik", "report_date", "issuer_name", "bdc_investment_identifier")}
    field = 'fair_value' if rule == 'C104' else 'cost'
    flag.update(rule_id=rule, column=field, value=row[field], row_key="999999")
    return jb.build_bundle(flag, [row], {"holdings_sha256": "h", "flags_sha256": "f"},
                           parsed_source=source, source_metadata={"sha256": "source"}, **kwargs)


def basic_source(**changes):
    return parsed(schedule([("Acme Test LLC", "Preferred units", fact("2,000", **changes), fact("1"), "")]))


def test_full_position_and_both_values_replace_unrelated_sample():
    packet = bundle(source=basic_source())
    assert packet["evidence_status"]["status"] == "ready_for_model"
    assert packet["output_position"]["fair_value"] == "1000"
    candidate = packet["source_candidates"][0]
    assert "Example BDC" in candidate["title_context"]
    assert candidate["comparisons"]["cost"]["source_amount"] == "2000000"
    assert candidate["comparisons"]["fair_value"]["agrees_at_display_precision"] is True
    assert candidate["header_rows"][0]["cells"][1]["text"] == "Investment"
    assert jb.make_request(packet)["questions"]["source_match"]["criteria"]["t0r1"]


def test_sibling_tranches_kept_and_value_matching_does_not_choose_source():
    source = parsed(schedule([
        ("Acme Test LLC", "Common units", fact("2,000"), fact("1"), ""),
        ("Acme Test LLC", "Preferred units", fact("2,000"), fact("1,900"), ""),
        ("Unrelated Borrower", "Preferred units", fact("2,000"), fact("1"), ""),
    ]))
    packet = bundle(source=source)
    candidates = packet["source_candidates"]
    assert [c["evidence_id"] for c in candidates] == ["t0r1", "t0r2"]
    assert candidates[0]["comparisons"]["fair_value"]["agrees_at_display_precision"] is True
    assert candidates[1]["comparisons"]["fair_value"]["agrees_at_display_precision"] is False
    assert packet["evidence_status"]["identity_match_verified"] is False


def test_comparative_schedule_is_not_used_as_current_evidence():
    rows = [("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), "")]
    source = parsed(schedule(rows, date="December 31, 2024") + schedule(rows))
    packet = bundle(source=source)
    assert [c["evidence_id"] for c in packet["source_candidates"]] == ["t1r1"]
    assert packet["retrieval"]["excluded_period_candidates"][0]["report_date"] == "2024-12-31"


def test_negative_cost_is_a_legitimate_source_value():
    source = parsed(schedule([("Acme Test LLC", "Revolver", fact("(149)", sign="-"), fact("(123)", sign="-"), "(9)")],
                             notes="<p>(9) Undrawn commitment fees can result in negative cost.</p>"))
    packet = bundle(row=output(cost="-149000", fair_value="-123000"), source=source, rule="C107")
    assert packet["evidence_status"]["status"] == "ready_for_model"
    candidate = packet["source_candidates"][0]
    assert candidate["comparisons"]["cost"]["output_minus_source"] == "0"
    assert "Undrawn" in candidate["notes"][0]["text"]


@pytest.mark.parametrize('zero', [0, 0.0, '0'])
def test_c104_numeric_and_string_zero_are_equivalent(zero):
    source = parsed(schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('0'), '')]))
    packet = bundle(row=output(fair_value=zero), source=source, rule='C104')
    assert packet['evidence_status']['status'] == 'ready_for_model'
    assert packet['rule']['fields'] == ['fair_value']
    assert packet['source_candidates'][0]['comparisons']['fair_value']['agrees_at_display_precision'] is True


def test_c104_source_positive_value_is_not_cleared_as_zero():
    packet = bundle(row=output(fair_value='0'), source=basic_source(), rule='C104')
    assert packet['evidence_status']['status'] == 'ready_for_model'
    assert packet['source_candidates'][0]['comparisons']['fair_value']['agrees_at_display_precision'] is False


def test_known_inline_concept_cannot_contradict_the_visible_value_column():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    body = body.replace('us-gaap:InvestmentOwnedAtFairValue', 'us-gaap:InvestmentOwnedAtCost')
    packet = bundle(source=parsed(body))
    assert 'fair_value:inline_concept_column_conflict' in packet['source_candidates'][0]['blocking_reasons']


def test_unknown_custom_concept_is_not_mislabelled_as_a_known_conflict():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    body = body.replace('us-gaap:InvestmentOwnedAtFairValue', 'custom:ReportedInvestmentValue')
    packet = bundle(source=parsed(body))
    assert packet['evidence_status']['status'] == 'ready_for_model'


@pytest.mark.parametrize('value', [None, '', False, 'NaN', '1'])
def test_c104_missing_or_nonzero_is_not_a_zero_flag(value):
    packet = bundle(row=output(fair_value=value), source=basic_source(), rule='C104')
    assert 'current_rule_predicate_not_satisfied' in packet['evidence_status']['blocking_reasons']


@pytest.mark.parametrize("change,reason", [
    ({"fair_value": None}, "missing_output:fair_value"),
    ({"fair_value_currency": "CAD"}, "unresolved_or_non_usd_output_currency:fair_value"),
    ({"fair_value": "0"}, "current_rule_predicate_not_satisfied"),
])
def test_missing_comparison_or_invalid_predicate_blocks(change, reason):
    packet = bundle(row=output(**change), source=basic_source())
    assert reason in packet["evidence_status"]["blocking_reasons"]
    with pytest.raises(ValueError, match="Blocked"):
        jb.make_request(packet)


def test_duplicate_join_and_stale_flag_do_not_fall_back_to_row_ordinal():
    row = output()
    flag = {**row, "rule_id": "X08", "column": "cost", "value": "3", "row_key": "0"}
    packet = jb.build_bundle(flag, [row], {"holdings_sha256": "h", "flags_sha256": "f"})
    assert "flag_output_mismatch:cost" in packet["evidence_status"]["blocking_reasons"]
    packet = jb.build_bundle(flag, [row, row], {"holdings_sha256": "h", "flags_sha256": "f"})
    assert "exact_row_join_not_unique" in packet["evidence_status"]["blocking_reasons"]


@pytest.mark.parametrize("changes,reason", [
    ({"scale": 0}, "title_inline_scale_conflict"),
    ({"currency": "cad"}, "unresolved_or_non_usd_source_currency"),
])
def test_source_units_are_independent_of_output(changes, reason):
    packet = bundle(source=basic_source(**changes))
    assert packet["evidence_status"]["status"] == "blocked"
    assert reason in packet["source_candidates"][0]["source_values"]["cost"]["blocking_reasons"]


def test_missing_note_is_not_filled_from_comparative_period():
    rows = [("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), "(9)")]
    source = parsed(schedule(rows) + schedule(rows, date="December 31, 2024", notes="<p>(9) This note applies to the prior schedule only.</p>"))
    packet = bundle(source=source)
    assert packet["source_candidates"][0]["missing_note_markers"] == ["9"]
    assert packet["evidence_status"]["status"] == "blocked"


def test_blank_name_continuation_retained():
    source = parsed(schedule([
        ("Acme Test LLC", "Term loan", fact("2,000"), fact("1,950"), ""),
        ("", "Preferred units", fact("2,000"), fact("1"), ""),
    ]))
    assert [c["row_index"] for c in bundle(source=source)["source_candidates"]] == [1, 2]


def test_unnamed_subtotal_is_context_not_a_position_candidate():
    source = parsed(schedule([
        ("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), ""),
        ("", "", fact("2,000"), fact("1"), ""),
    ]))
    packet = bundle(source=source)
    assert [c["row_index"] for c in packet["source_candidates"]] == [1]
    assert 2 in [r["row_index"] for r in packet["source_candidates"][0]["context_rows"]]


def test_div_notes_and_deduplication_preserve_context():
    source = parsed(schedule([
        ("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), "(9)"),
        ("Acme Test LLC", "Common units", fact("1"), fact("2,000"), "(9)"),
    ], notes="<div><span>(9)</span> <span>Source explanation shared by both tranches.</span></div>"))
    packet = bundle(source=source)
    assert packet["evidence_status"]["status"] == "ready_for_model"
    state = jb.make_request(packet)["state"]
    assert len(state["source_notes"]) == 1
    assert len(state["source_tables"]) == 1
    assert len(state["source_tables"][0]["rows"]) == 3


def test_supplemental_table_does_not_disconnect_soi_notes():
    body = schedule([("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), "(9)")])
    body += '<table><tr><td>Derivative commitments</td></tr></table>'
    body += '<div>(9) This note follows a supplemental schedule.</div>'
    packet = bundle(source=parsed(body))
    assert packet["evidence_status"]["status"] == "ready_for_model"


def test_statement_heading_ends_soi_note_scope():
    body = schedule([("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), "(9)")])
    body += '<div>Notes to Consolidated Financial Statements</div><div>(9) This is an unrelated accounting note.</div>'
    packet = bundle(source=parsed(body))
    assert packet["source_candidates"][0]["missing_note_markers"] == ["9"]


def test_missing_cached_source_blocks_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(jb, "_html_path", lambda *args: tmp_path / "absent.html")
    packet = bundle()
    assert packet["evidence_status"]["blocking_reasons"] == ["missing_cached_source"]


def test_dashes_require_explicit_source_zero_transform():
    row = output(cost="-1000")
    untagged = parsed(schedule([("Acme Test LLC", "Revolver", "-", fact("1"), "")]))
    assert bundle(row=row, source=untagged, rule="C107")["evidence_status"]["status"] == "blocked"
    tagged = parsed(schedule([("Acme Test LLC", "Revolver", fact("-", fmt="ixt:fixed-zero"), fact("1"), "")]))
    packet = bundle(row=row, source=tagged, rule="C107")
    assert packet["source_candidates"][0]["comparisons"]["cost"]["agrees_at_display_precision"] is False


@pytest.mark.parametrize('fmt', ['ixt:not-fixed-zero', 'ixt:zero-dash-placeholder', 'ixt:zeroXdash'])
def test_zero_transform_substring_does_not_turn_an_unknown_dash_into_zero(fmt):
    source = parsed(schedule([('Acme Test LLC', 'Preferred units', fact('2000'), fact('-', fmt=fmt), '')]))
    packet = bundle(row=output(fair_value=0), source=source, rule='C104')
    assert packet['evidence_status']['status'] == 'blocked'


def test_rounding_uses_display_decimal_places():
    source = parsed(schedule([("Acme Test LLC", "Preferred units", fact("2,000.25"), fact("1"), "")]))
    packet = bundle(row=output(cost="2000000"), source=source)
    comparison = packet["source_candidates"][0]["comparisons"]["cost"]
    assert comparison["rounding_half_unit"] == "5.00"
    assert comparison["agrees_at_display_precision"] is False


def test_candidate_truncation_is_explicit():
    source = basic_source()
    source["tables"][0]["rows"].extend(copy.deepcopy(source["tables"][0]["rows"][1:]) * 3)
    candidates, status = jb.retrieve_candidates(source, output(), "X08", max_candidates=2)
    assert len(candidates) == 2
    assert status["blocking_reasons"] == ["candidate_limit"]


def test_source_row_budget_is_enforced():
    with pytest.raises(ValueError, match="source_row_limit"):
        jb.parse_source(b"<table><tr><td>1</td></tr><tr><td>2</td></tr></table>", max_rows=1)


def test_rowspan_layout_remains_unresolved():
    body = schedule([("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), "")])
    body = body.replace('<td>Acme Test LLC</td>', '<td rowspan="2">Acme Test LLC</td>')
    packet = bundle(source=parsed(body))
    assert "unsupported_table_layout" in packet["source_candidates"][0]["blocking_reasons"]


def test_conflicting_notes_for_same_period_are_not_silently_selected():
    body = schedule([("Acme Test LLC", "Preferred units", fact("2,000"), fact("1"), "(9)")],
                    notes='<p>(9) First explanation of the position.</p><p>(9) Different explanation with unresolved scope.</p>')
    packet = bundle(source=parsed(body))
    assert "conflicting_referenced_notes" in packet["source_candidates"][0]["blocking_reasons"]


def test_reader_rejects_missing_row_id_without_ordinal_fallback(tmp_path):
    flags = tmp_path / "flags.csv"
    holdings = tmp_path / "holdings.csv"
    flags.write_text("source,cik,report_date,rule_id,row_id,row_key\nbdc,0000000001,2025-06-30,C107,,0\n")
    holdings.write_text("row_id,cik,cost\nROW-1,0000000001,-149000\n")
    rows, matches = read_inputs(flags, holdings, rules=["C107"], ciks=[], quarter=None, row_ids=[], limit=1)
    assert len(rows) == 1
    assert not matches


def context(identifier='Preferred units', date='2025-06-30'):
    return ('<xbrli:context id="c-1"><xbrli:entity><xbrli:identifier>0000000001</xbrli:identifier>'
            '<xbrli:segment><xbrldi:typedMember dimension="InvestmentIdentifierAxis">'
            f'<value>Acme Test LLC {identifier}</value></xbrldi:typedMember></xbrli:segment>'
            f'</xbrli:entity><xbrli:period><xbrli:instant>{date}</xbrli:instant>'
            '</xbrli:period></xbrli:context>')


def test_conflicting_duplicate_context_id_blocks_instead_of_last_wins():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    first, second = context(), context(identifier='Common units')
    for definitions in (first + second, second + first):
        packet = bundle(source=parsed(definitions + body))
        assert packet['evidence_status']['status'] == 'blocked'
        candidate = packet['source_candidates'][0]
        assert 'conflicting_source_context_definition' in candidate['identity_evidence']['blocking_reasons']
        assert candidate['identity_evidence']['contexts']['c-1']['conflicting_definitions']


def test_identical_repeated_context_definition_is_not_a_false_conflict():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    packet = bundle(source=parsed(context() + context() + body))
    assert packet['evidence_status']['status'] == 'ready_for_model'


@pytest.mark.parametrize('measures', ['iso4217:AUD', 'iso4217:USD'])
def test_duplicate_currency_unit_requires_consistent_definitions(measures):
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    extra = f'<xbrli:unit id="usd"><xbrli:measure>{measures}</xbrli:measure></xbrli:unit>'
    packet = bundle(source=parsed(extra + body))
    assert (packet['evidence_status']['status'] == 'ready_for_model') is (measures == 'iso4217:USD')


def test_later_unit_cannot_restore_an_ambiguous_currency_id():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    extra = ''.join(f'<xbrli:unit id="usd"><xbrli:measure>iso4217:{c}</xbrli:measure></xbrli:unit>'
                    for c in ['AUD', 'USD', 'USD'])
    assert bundle(source=parsed(extra + body))['evidence_status']['status'] == 'blocked'


def test_undisclosed_units_with_conflicting_column_scales_block_tcw_failure():
    source = parsed(schedule([('Acme Test LLC', 'Term loan', fact('22,130,144'),
                               fact('21,218,503', scale=0), '')], units=''))
    packet = bundle(source=source)
    candidate = packet['source_candidates'][0]
    assert packet['evidence_status']['status'] == 'blocked'
    assert 'cross_column_inline_scale_conflict' in candidate['blocking_reasons']
    assert candidate['source_values']['cost']['amount'] is None


def test_consistent_explicit_dollar_values_remain_available():
    source = parsed(schedule([('Acme Test LLC', 'Preferred units', fact('2,000,000', scale=0),
                               fact('1,000', scale=0), '')], units='in dollars'))
    assert bundle(source=source)['evidence_status']['status'] == 'ready_for_model'


def test_visible_share_class_conflict_with_own_context_blocks_even_matching_amounts():
    source = parsed(context('Class A units') + schedule([
        ('Acme Test LLC', 'Class C units', fact('2,000'), fact('1'), '')]))
    row = output(bdc_investment_identifier='Acme Test LLC Class A units', src_context_id='c-1')
    packet = bundle(row=row, source=source)
    candidate = packet['source_candidates'][0]
    assert 'visible_context_share_class_conflict' in candidate['blocking_reasons']
    assert candidate['comparisons']['cost']['agrees_at_display_precision'] is True
    assert candidate['identity_evidence']['visible_classes'] == ['c']
    assert candidate['identity_evidence']['context_classes'] == ['a']


def test_agreeing_share_class_is_not_blocked_as_a_conflict():
    source = parsed(context('Class A units') + schedule([
        ('Acme Test LLC', 'Class A units', fact('2,000'), fact('1'), '')]))
    packet = bundle(row=output(bdc_investment_identifier='Acme Test LLC Class A units'), source=source)
    assert packet['evidence_status']['status'] == 'ready_for_model'


@pytest.mark.parametrize('source_class', ['ClassAUnitsMember', 'custom:ClassACommonUnitsMember', 'ClassAMember'])
def test_camel_case_dimension_class_agrees_with_visible_class(source_class):
    source = parsed(context(source_class) + schedule([
        ('Acme Test LLC', 'Class A units', fact('2,000'), fact('1'), '')]))
    packet = bundle(row=output(bdc_investment_identifier='Acme Test LLC Class A units'), source=source)
    assert packet['source_candidates'][0]['identity_evidence']['context_classes'] == ['a']
    assert packet['evidence_status']['status'] == 'ready_for_model'


def test_camel_case_dimension_still_blocks_a_different_visible_class():
    source = parsed(context('custom:ClassCUnitsMember') + schedule([
        ('Acme Test LLC', 'Class A units', fact('2,000'), fact('1'), '')]))
    packet = bundle(row=output(bdc_investment_identifier='Acme Test LLC Class A units'), source=source)
    assert 'visible_context_share_class_conflict' in packet['source_candidates'][0]['blocking_reasons']


def test_continuation_period_can_be_established_by_monetary_instant_contexts():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    body = body[body.index('<table'):]
    source = parsed(context() + body)
    packet = bundle(source=source)
    assert packet['evidence_status']['status'] == 'ready_for_model'
    assert packet['source_candidates'][0]['period_evidence']['basis'] == 'inline_instant_contexts'


def test_title_and_monetary_context_period_conflict_cannot_clear():
    source = parsed(context(date='2024-12-31') + schedule([
        ('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')]))
    packet = bundle(source=source)
    assert packet['evidence_status']['status'] == 'blocked'
    assert 'title_context_period_conflict' in packet['source_candidates'][0]['blocking_reasons']


def test_undated_continuation_without_context_stays_blocked():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    source = parsed(body[body.index('<table'):])
    assert bundle(source=source)['evidence_status']['status'] == 'blocked'


def test_nested_marker_and_inline_footnote_text_stay_one_scoped_note():
    notes = ('<div><div><span>(9)</span></div><div><ix:footnote id="n9">'
             '<span>Undrawn commitment fees explain the negative cost.</span>'
             '</ix:footnote></div></div>')
    source = parsed(schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'),
                               fact('(123)', sign='-'), '(9)')], notes=notes))
    packet = bundle(row=output(cost='-149000', fair_value='-123000'), source=source, rule='C107')
    assert packet['evidence_status']['status'] == 'ready_for_model'
    assert len(packet['source_candidates'][0]['notes']) == 1


def test_nested_notes_do_not_merge_two_numbered_definitions():
    notes = ('<div><div><span>(9)</span></div><div>Undrawn commitment fees explain negative cost.</div></div>'
             '<div><div><span>(10)</span></div><div>Unrelated explanation for another numbered note.</div></div>')
    source = parsed(schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'),
                               fact('(123)', sign='-'), '(9)')], notes='<div>' + notes + '</div>'))
    packet = bundle(row=output(cost='-149000', fair_value='-123000'), source=source, rule='C107')
    selected = packet['source_candidates'][0]['notes']
    assert len(selected) == 1
    assert 'Unrelated' not in selected[0]['text']


def test_affiliation_qualified_investments_header_identifies_issuer_column():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    body = body.replace('Portfolio Company', 'Investments\u2014non-controlled/non-affiliated (1)')
    body += '<p>(1) These investments are non-controlled and non-affiliated.</p>'
    packet = bundle(source=parsed(body))
    assert packet['evidence_status']['status'] == 'ready_for_model'
    assert packet['source_candidates'][0]['headers']['issuer']['column'] == 0


def test_generic_investments_total_is_not_an_issuer_header():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    body = body.replace('Portfolio Company', 'Investments Total')
    packet = bundle(source=parsed(body))
    assert 'unresolved_identity_column' in packet['source_candidates'][0]['blocking_reasons']


@pytest.mark.parametrize('marker', ['(e)', '^', '#', '+', '*'])
def test_non_numeric_required_notes_cannot_silently_disappear(marker):
    body = schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'),
                      fact('(123)', sign='-'), marker)])
    row = output(cost='-149000', fair_value='-123000')
    absent = bundle(row=row, source=parsed(body), rule='C107')
    assert absent['evidence_status']['status'] == 'blocked'
    present = bundle(row=row, source=parsed(body + f'<p>{marker} Commitment fees explain negative cost.</p>'), rule='C107')
    assert present['evidence_status']['status'] == 'ready_for_model'
    assert len(present['source_candidates'][0]['notes']) == 1


def test_interest_formula_plus_is_not_a_source_note():
    assert jb._note_markers('SOFR + 5.00 %') == set()
    assert jb._note_markers('S + 500 , 75 Floor') == set()
    assert jb._note_markers('Issuer annotation ^#') == {'^', '#'}


def test_repeated_symbol_note_is_distinct_and_header_notes_are_retained():
    assert jb._note_markers('Amortized Cost (++)') == {'(++)'}
    assert jb._note_markers('Company # +') == {'#', '+'}
    body = schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'), fact('0'), '')])
    body = body.replace('Portfolio Company', 'Company # +').replace('>Cost<', '>Amortized Cost (++)<')
    body += '<p># Portfolio affiliation note applies to listed investments.</p><p>+ Other issuer qualification for these investments.</p>'
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(body), rule='C104')
    assert 'missing_referenced_notes' in packet['source_candidates'][0]['blocking_reasons']
    body += '<p>(++) Cost includes unamortized discount on the investment.</p>'
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(body), rule='C104')
    assert packet['evidence_status']['status'] == 'ready_for_model'
    assert {n['marker'] for n in packet['source_candidates'][0]['notes']} == {'#', '+', '(++)'}


def test_parenthesized_symbol_is_not_interchangeable_with_bare_symbol():
    body = schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'), fact('0'), '+')])
    body += '<p>(+) Controlled investments have a different accounting scope.</p>'
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(body), rule='C104')
    assert 'missing_referenced_notes' in packet['source_candidates'][0]['blocking_reasons']


def test_notes_do_not_leak_between_same_period_schedules():
    first = schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'), fact('0'), '(2)')],
                     notes='<p>(2) This investment has an unfunded commitment.</p>')
    second = schedule([('Other Entity LLC', 'Revolver', fact('200'), fact('100'), '(2)')],
                      notes='<p>(2) Loan includes an interest rate floor feature.</p>')
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(first + second), rule='C104')
    notes = packet['source_candidates'][0]['notes']
    assert len(notes) == 1
    assert 'unfunded' in notes[0]['text']


def test_missing_note_is_not_filled_from_later_note_block():
    first = schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'), fact('0'), '(2)')],
                     notes='<p>(1) Percentages in this schedule are based on net assets.</p>')
    second = schedule([('Other Entity LLC', 'Revolver', fact('200'), fact('100'), '(2)')],
                      notes='<p>(2) Loan includes an interest rate floor feature.</p>')
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(first + second), rule='C104')
    assert 'missing_referenced_notes' in packet['source_candidates'][0]['blocking_reasons']


@pytest.mark.parametrize('marker', ['9', '9)', '(9)', '9, 10'])
def test_explicit_note_column_requires_bare_or_partial_markers(marker):
    body = schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'), fact('0'), marker)])
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(body), rule='C107')
    assert 'missing_referenced_notes' in packet['source_candidates'][0]['blocking_reasons']
    body += '<p>(9) Discount on an unfunded commitment explains negative cost.</p>'
    body += '<p>(10) Additional loan commitment information is disclosed here.</p>'
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(body), rule='C107')
    assert packet['evidence_status']['status'] == 'ready_for_model'


def test_numeric_instrument_text_is_not_a_bare_note_reference():
    body = schedule([('Acme Test LLC', 'Series 9', fact('(149)', sign='-'), fact('0'), '')])
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(body), rule='C107')
    assert packet['evidence_status']['status'] == 'ready_for_model'


def test_unrecognized_note_column_syntax_blocks_instead_of_partial_parsing():
    body = schedule([('Acme Test LLC', 'Revolver', fact('(149)', sign='-'), fact('0'), '1-3')])
    packet = bundle(row=output(cost='-149000', fair_value='0'), source=parsed(body), rule='C107')
    assert 'unparsed_note_column_reference' in packet['source_candidates'][0]['blocking_reasons']


def test_symbol_stripping_does_not_accept_unrelated_header_text():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    body = body.replace('Portfolio Company', 'Company total #')
    packet = bundle(source=parsed(body))
    assert 'unresolved_identity_column' in packet['source_candidates'][0]['blocking_reasons']


def test_investment_industry_header_is_resolved_without_relabelling_instrument():
    body = schedule([('Acme Test LLC', 'Business Services', fact('2,000'), fact('1'), '')])
    body = body.replace('<td>Investment</td>', '<td>Industry</td>').replace('Portfolio Company', 'Investment (1) (2)')
    body += '<p>(1) Issuer identity follows the portfolio schedule.</p><p>(2) Values reflect disclosed investment holdings.</p>'
    packet = bundle(source=parsed(body))
    assert packet['source_candidates'][0]['headers']['issuer']['column'] == 0
    ordinary = bundle(source=basic_source())
    assert ordinary['source_candidates'][0]['headers']['instrument']['column'] == 1


def test_compound_company_header_retains_instrument_column():
    body = schedule([('Acme Test LLC', 'Preferred units', fact('2,000'), fact('1'), '')])
    body = body.replace('Portfolio Company', 'Country/Security/Industry/Company')
    assert bundle(source=parsed(body))['evidence_status']['status'] == 'ready_for_model'


def test_split_parenthesis_just_outside_header_span_preserves_negative_cost():
    cells = [{'column': 0, 'span': 1, 'text': '( 1', 'inline_facts': [
        {'currency': 'USD', 'scale': '3', 'text': '1', 'sign': '-', 'format': None}]},
             {'column': 1, 'span': 1, 'text': ')'},
             {'column': 2, 'span': 1, 'text': '700'}]
    result = jb._money(cells, {'column': 0, 'span': 1}, 1000)
    assert result['amount'] == '-1000'
    assert len(result['cells']) == 2
    cells[1]['text'] = '700'
    unresolved = jb._money(cells, {'column': 0, 'span': 1}, 1000)
    assert unresolved['amount'] is None
