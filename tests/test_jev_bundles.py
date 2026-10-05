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
                      for name, instrument, cost, fv, refs in rows)
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
    flag.update(rule_id=rule, column="cost", value=row["cost"], row_key="999999")
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
