"""Source checks for rows whose tagged fact is defective and whose published value is the printed one.

Owner ruling 2026-11-10 ("fix the check for the 10 of 13"). A corrected value mismatch becomes
non-blocking (``page_verified_correction``) only when the page artifact prints the published
principal, cost and fair value at the filing's printed scale. The correction's claim alone never
clears it, and a row the page does not confirm keeps SRC_BDC03 / blocking_fair_value_*.
"""
from __future__ import annotations

import pandas as pd
import pytest

from pipeline.page_verified_corrections import (PAGE_VERIFIED_MECHANISM, PAGE_VERIFIED_STATUS,
                                                apply_page_verification, figure_matches, load_printed_rows,
                                                printed_figures, printed_scale, tuple_on_row)

CIK = "0000000100"
ACC = "000100-24-000001"


# --- page reading ---------------------------------------------------------------------------------

def test_figures_read_brackets_dashes_and_skip_footnotes_words_dates_percents():
    row = "Acme | First Lien | S + 5.75% | 11/16/2027 | $ | 1,749 | (18 | ) | (70 | ) | (5) (7) (8) | — | 0.6%"
    assert [(v, d) for _c, v, d in printed_figures(row)] == [(1749.0, 0), (-18.0, 0), (-70.0, 0), (0.0, 0)]


def test_figures_keep_cell_order_and_currency_codes_are_not_words():
    cells = printed_figures("Atlas Bidco | Revolver | AUD | — | (3) | (3)")
    assert [v for _c, v, _d in cells] == [0.0, -3.0, -3.0]
    assert [c for c, _v, _d in cells] == sorted(c for c, _v, _d in cells)


def test_figure_match_needs_the_scale_the_sign_and_the_printed_digits():
    assert figure_matches(443000.0, 443.0, 0, 1e3)
    assert not figure_matches(443.0, 443.0, 0, 1e3)          # the unscaled tag is not the printed figure
    assert not figure_matches(7379.0, -7379.0, 0, 1.0)       # sign printed in brackets
    assert not figure_matches(444000.0, 443.0, 0, 1e3)       # another value
    assert figure_matches(0.0, 0.0, 0, 1e3) and not figure_matches(0.0, 923.0, 0, 1e3)


def test_tuple_needs_each_amount_in_its_own_cell_in_par_cost_value_order():
    figures = printed_figures("X | 1,456 | 1,456 | 1,452")
    assert tuple_on_row({"principal_amount": 1456e3, "cost": 1456e3, "fair_value": 1452e3}, figures, 1e3)
    # a fair value set to the cost cannot borrow the par's cell when par is published too
    assert not tuple_on_row({"principal_amount": 1456e3, "cost": 1456e3, "fair_value": 1456e3}, figures, 1e3)
    # fair value printed before cost is not read as this row
    assert not tuple_on_row({"cost": 1452e3, "fair_value": 1456e3}, printed_figures("X | 1,456 | 1,452"), 1e3)


def test_scale_is_the_clear_majority_of_uncontested_rows():
    thousands = [(1_000_000.0, printed_figures("A | 1,000")), (2_500_000.0, printed_figures("B | 2,500")),
                 (3_250_000.0, printed_figures("C | 3,250"))]
    assert printed_scale(thousands) == 1e3
    assert printed_scale(thousands[:2]) is None                      # too few votes
    split = thousands + [(5.0, printed_figures("D | 5")), (6.0, printed_figures("E | 6")),
                         (7.0, printed_figures("F | 7"))]
    assert printed_scale(split) is None                              # no clear majority


def test_loader_drops_members_printed_on_two_rows_and_artifacts_without_printed_row(tmp_path):
    path = tmp_path / "fs.csv"
    pd.DataFrame([
        {"cik": "100", "accession_number": ACC, "period_role": "current", "raw_id_lower": "a", "printed_row": "A | 1"},
        {"cik": "100", "accession_number": ACC, "period_role": "current", "raw_id_lower": "b", "printed_row": "B | 1"},
        {"cik": "100", "accession_number": ACC, "period_role": "current", "raw_id_lower": "b", "printed_row": "B | 2"},
        {"cik": "100", "accession_number": ACC, "period_role": "comparative", "raw_id_lower": "c", "printed_row": "C"},
    ]).to_csv(path, index=False)
    rows = load_printed_rows(path, {"100"})
    assert list(rows["raw_id_lower"]) == ["a"] and rows.iloc[0]["cik"] == CIK
    old = tmp_path / "old.csv"
    pd.DataFrame([{"cik": "100", "accession_number": ACC, "period_role": "current", "raw_id_lower": "a"}]).to_csv(old, index=False)
    assert load_printed_rows(old, {"100"}).empty


# --- the reconciliation -------------------------------------------------------------------------

# Three uncontested rows printed in thousands: they set the filing's printed scale.
VOTERS = [("Voter A Term Loan", 1_000_000, 990_000, 1_000_000), ("Voter B Term Loan", 2_500_000, 2_480_000, 2_510_000),
          ("Voter C Term Loan", 3_250_000, 3_200_000, 3_300_000)]


def _k(n):
    return f"{n / 1000:,.0f}"


def _case(target_tag, target_pub, printed_target, corrected="fair_value", voters_dollars=False, extra=()):
    """(source, output, printed rows) for one defective target row beside three uncontested voters.

    target_tag / target_pub: dicts of fair_value / cost / principal_amount (None = not tagged / published)."""
    from tests.test_validate_holdings import _make_bdc_output, _make_bdc_source
    src, out, printed = [], [], []
    for i, (name, par, cost, fv) in enumerate(VOTERS):
        dims = "investmentidentifier=" + name
        src.append({"context_id": f"v{i}", "investment_identifier": name, "dimensions_raw": dims,
                    "fair_value": str(fv), "cost": str(cost), "principal_amount": str(par)})
        out.append({"bdc_investment_identifier": name, "bdc_dimensions_raw": dims, "issuer_name": name.split(" Term")[0],
                    "fair_value": str(fv), "cost": str(cost), "principal_amount": str(par), "row_id": f"ROW-v{i}"})
        cells = [f"{par:,}", f"{cost:,}", f"{fv:,}"] if voters_dollars else [_k(par), _k(cost), _k(fv)]
        printed.append({"cik": CIK, "accession_number": ACC, "raw_id_lower": name.lower(),
                        "printed_row": " | ".join([name, "S + 5.00%"] + cells)})
    for name, tag, pub, line, corr in [("Target Co Term Loan", target_tag, target_pub, printed_target, corrected), *extra]:
        dims = "investmentidentifier=" + name
        src.append({"context_id": "t-" + name, "investment_identifier": name, "dimensions_raw": dims,
                    **{f: ("" if tag.get(f) is None else str(tag[f])) for f in ("fair_value", "cost", "principal_amount")}})
        out.append({"bdc_investment_identifier": name, "bdc_dimensions_raw": dims, "issuer_name": "Target Co",
                    **{f: ("" if pub.get(f) is None else str(pub[f])) for f in ("fair_value", "cost", "principal_amount")},
                    "row_id": "ROW-" + name, "corrected_fields": corr})
        if line is not None:
            printed.append({"cik": CIK, "accession_number": ACC, "raw_id_lower": name.lower(), "printed_row": line})
    return _make_bdc_source(src), _make_bdc_output(out), pd.DataFrame(printed)


def _reconcile(source, output, printed):
    from pipeline.source_reconciliation import reconcile_bdc_source_to_holdings
    from tests.test_validate_holdings import _no_rescales
    return reconcile_bdc_source_to_holdings(source, output, audited_value_rescales=_no_rescales(), printed_rows=printed)


def _target(detail, name="Target Co Term Loan"):
    return detail[detail["raw_investment_identifier"] == name].iloc[0]


def _verified(detail, name="Target Co Term Loan"):
    row = _target(detail, name)
    assert row["status"] == "value_mismatch"
    return row["calibrated_status"] == PAGE_VERIFIED_STATUS and not bool(row["blocking_issue"])


# Each defect shape the owner accepted (2026-11-10): the tag disagrees with the printed line and an
# audited correction published the printed value.
SHAPES = {
    "unscaled_tag_published_in_thousands": (  # Chartwell 2023-12-31
        {"principal_amount": 450_000, "cost": 432, "fair_value": 443},
        {"principal_amount": 450_000, "cost": 432_000, "fair_value": 443_000},
        "Target Co | First Lien | S + 5.75% | 11/16/2027 | 450 | 432 | 443 | 7", "cost;fair_value"),
    "value_tagged_in_thousands_with_sign": (  # Goldman 2023-09-30 GHA Buyer
        {"principal_amount": 1749, "cost": 18, "fair_value": -70},
        {"principal_amount": 1_749_000, "cost": -18_000, "fair_value": -70_000},
        "Target Co | S + 8.25% | 06/24/26 | 1,749 | (18 | ) | (70 | ) | (5) (7) (8)",
        "cost;fair_value;principal_amount"),
    "digit_split": (  # Goldman 2023-12-31 BSI3 Menu Buyer: tag -13 thousand for a printed (135)
        {"principal_amount": 1_924_000, "cost": 23_000, "fair_value": -13_000},
        {"principal_amount": 1_924_000, "cost": -23_000, "fair_value": -135_000},
        "Target Co | S + 6.00% | 01/25/28 | 1,924 | (23 | ) | (135 | ) | (7) (8) (9)", "cost;fair_value"),
    "sign_dropped_brackets": (  # Sumo Logic revolver: tag +7,379 for a printed (7,379)
        {"cost": -10_048_000, "fair_value": 7_379_000},
        {"cost": -10_048_000, "fair_value": -7_379_000},
        "Target Co | First Lien Revolver | $ | — | (10,048 | ) | (7,379 | ) | — | D/E", "fair_value"),
    "fv_sign_on_undrawn_revolver": (  # Atlas Bidco 2026-06-30: printed (3) / (3), fair value tagged 3000
        {"cost": -3000, "fair_value": 3000},
        {"cost": -3000, "fair_value": -3000},
        "Target Co | Revolver | — | 6/20/2033 | AUD | — | (3) | (3)", "fair_value"),
    "leading_digit_in_its_own_cell": (  # Empower Financial: tagged 4,495 / 4,511 / 4,511
        {"principal_amount": 4_495_000, "cost": 4_511_000, "fair_value": 4_511_000},
        {"principal_amount": 14_495_000, "cost": 14_511_000, "fair_value": 14_511_000},
        "Target Co | Secured Loan | May 15, 2024 | 14,495 | 14,511 | 14,511 | (8)(19)",
        "cost;principal_amount;fair_value"),
    "fixed_zero_format": (  # tag reads 0 whatever the text; cost printed as a dash
        {"cost": 0, "fair_value": 0},
        {"cost": 0, "fair_value": 134_113_000},
        "Target Co (3) (5) (6) | Class A LP Interests | 159,658 | — | 134,113", "fair_value"),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_corrected_row_the_page_confirms_is_not_blocking(shape):
    tag, pub, line, corrected = SHAPES[shape]
    detail, metrics = _reconcile(*_case(tag, pub, line, corrected))
    assert _verified(detail)
    assert int(metrics.iloc[0]["blocking_issue_count"]) == 0
    assert _target(detail)["evidence"].startswith("printed_row: Target Co")


def test_page_scale_in_dollars_comes_from_the_filing_not_the_correction():
    tag = {"cost": -10_048, "fair_value": 7_379}
    pub = {"cost": -10_048, "fair_value": -7_379}
    line = "Target Co | Revolver | (10,048 | ) | (7,379 | )"
    detail, _ = _reconcile(*_case(tag, pub, line, voters_dollars=True))
    assert _verified(detail)
    # the same published value on a filing printed in thousands is 1,000 times too small
    detail, _ = _reconcile(*_case(tag, pub, line, voters_dollars=False))
    assert not _verified(detail)


def test_cross_tagged_values_are_read_from_the_line_that_prints_the_whole_tuple():
    # AI Titan 2026-03-31: each line's fair value is tagged on the other line's member.
    one = ("Target Co Term Loan One", {"principal_amount": 7_167_000, "cost": 7_108_000, "fair_value": 294_000},
           {"principal_amount": 7_167_000, "cost": 7_108_000, "fair_value": 7_024_000},
           "Target Co | Software | 1,433 | 315 | 294 | (7) (8) (10)", "fair_value")
    detail, metrics = _reconcile(*_case(
        {"principal_amount": 1_433_000, "cost": 315_000, "fair_value": 7_024_000},
        {"principal_amount": 1_433_000, "cost": 315_000, "fair_value": 294_000},
        "Target Co | Software | 7,167 | 7,108 | 7,024 | (7) (8)", extra=[one]))
    assert _verified(detail) and _verified(detail, "Target Co Term Loan One")
    assert "another member" in _target(detail)["calibration_reason"]
    assert int(metrics.iloc[0]["blocking_issue_count"]) == 0


def test_another_members_line_needs_three_non_zero_amounts():
    # with no published par the tuple (cost, fair value) is too short to be matched across the filing
    one = ("Target Co Term Loan One", {"cost": 7_108_000, "fair_value": 294_000},
           {"cost": 7_108_000, "fair_value": 7_024_000}, "Target Co | 315 | 294", "fair_value")
    detail, _ = _reconcile(*_case({"cost": 315_000, "fair_value": 7_024_000}, {"cost": 315_000, "fair_value": 294_000},
                                  "Target Co | 7,108 | 7,024", extra=[one]))
    assert not _verified(detail) and not _verified(detail, "Target Co Term Loan One")


# --- real errors still fire ---------------------------------------------------------------------

BASE_TAG = {"principal_amount": 450_000, "cost": 432_000, "fair_value": 443}
BASE_PUB = {"principal_amount": 450_000, "cost": 432_000, "fair_value": 443_000}
BASE_LINE = "Target Co | First Lien | 450 | 432 | 443"


def _still_fires(detail, metrics):
    from pipeline.column_validation import adapt_validation_reports
    from pipeline.source_reconciliation import build_source_reconciliation_residual_classification
    row = _target(detail)
    assert row["status"] == "value_mismatch" and bool(row["blocking_issue"])
    assert row["calibrated_status"] == "blocking_fair_value_mismatch"
    assert int(metrics.iloc[0]["blocking_issue_count"]) == 1
    issues = adapt_validation_reports({"source_reconciliation_detail": detail})
    assert len(issues[issues["rule_id"] == "SRC_BDC03"]) == 1
    assert issues[issues["rule_id"] == "SRC_BDC03P"].empty
    classified = build_source_reconciliation_residual_classification(detail)
    assert set(classified.loc[classified["blocking_issue"].astype(bool), "mechanism"]) <= {
        "blocking_fair_value_scale_or_unit_candidate", "blocking_fair_value_disagreement"}
    assert PAGE_VERIFIED_MECHANISM not in set(classified["mechanism"])


def test_no_correction_keeps_the_mismatch_blocking_even_when_the_page_agrees():
    _still_fires(*_reconcile(*_case(BASE_TAG, BASE_PUB, BASE_LINE, corrected="")))


def test_correction_whose_value_the_page_does_not_print_still_fires():
    _still_fires(*_reconcile(*_case(BASE_TAG, {**BASE_PUB, "fair_value": 444_000}, BASE_LINE)))


def test_published_value_equal_to_neither_tag_nor_page_still_fires():
    _still_fires(*_reconcile(*_case(BASE_TAG, {**BASE_PUB, "fair_value": 443_000_000}, BASE_LINE)))


def test_correction_with_the_wrong_sign_still_fires():
    tag, _pub, line, corrected = SHAPES["sign_dropped_brackets"]
    _still_fires(*_reconcile(*_case(tag, {"cost": -10_048_000, "fair_value": 7_379_000 + 2_000}, line, corrected)))


def test_mismatched_field_the_correction_did_not_set_still_fires():
    # fair value and cost both differ from their tags, the correction set only the fair value
    tag = {"principal_amount": 450_000, "cost": 432, "fair_value": 443}
    _still_fires(*_reconcile(*_case(tag, BASE_PUB, BASE_LINE, corrected="fair_value")))


def test_other_published_amount_not_on_the_line_still_fires():
    # the corrected fair value is printed, but the published par is not this line's par
    _still_fires(*_reconcile(*_case(BASE_TAG, {**BASE_PUB, "principal_amount": 460_000}, BASE_LINE)))


def test_row_the_page_reader_did_not_keep_still_fires():
    _still_fires(*_reconcile(*_case(BASE_TAG, BASE_PUB, None)))


def test_neighbour_context_line_keyed_to_the_neighbour_still_fires():
    # D&D Buyer revolver: its fair value fact sits on Alorica's line, so its own printed row is Alorica's
    tag = {"principal_amount": 1_153_606, "cost": 1_153_606, "fair_value": 33_046_946}
    pub = {"principal_amount": 1_153_606, "cost": 1_153_606, "fair_value": 1_130_534}
    line = "Alorica Inc. | Term Loan | 33,686,999 | 03/02/27 | 33,285,743 | 33,046,946"
    _still_fires(*_reconcile(*_case(tag, pub, line, voters_dollars=True)))


def test_netted_commitment_is_not_a_printed_value_and_still_fires():
    tag = {"principal_amount": 923_000, "cost": 923_000, "fair_value": 923_000}
    pub = {"principal_amount": 923_000, "cost": 0, "fair_value": 0}
    _still_fires(*_reconcile(*_case(tag, pub, "Florida Food Products LLC, Revolver | $ | 923 | 923 | 923",
                                    corrected="cost;fair_value")))


def test_no_clear_printed_scale_still_fires():
    source, output, printed = _case(BASE_TAG, BASE_PUB, BASE_LINE)
    printed = printed[printed["raw_id_lower"] == "target co term loan"]
    _still_fires(*_reconcile(source, output, printed))


def test_without_printed_rows_the_comparison_is_unchanged():
    from pipeline.source_reconciliation import reconcile_bdc_source_to_holdings
    from tests.test_validate_holdings import _no_rescales
    source, output, _printed = _case(BASE_TAG, BASE_PUB, BASE_LINE)
    _still_fires(*reconcile_bdc_source_to_holdings(source, output, audited_value_rescales=_no_rescales()))


# --- what the checks report ----------------------------------------------------------------------

def test_verified_row_is_tracked_as_src_bdc03p_and_documented_in_the_residuals():
    from pipeline.column_validation import adapt_validation_reports
    from pipeline.source_reconciliation import build_source_reconciliation_residual_classification
    tag, pub, line, corrected = SHAPES["unscaled_tag_published_in_thousands"]
    detail, _ = _reconcile(*_case(tag, pub, line, corrected))
    issues = adapt_validation_reports({"source_reconciliation_detail": detail})
    assert issues[issues["rule_id"] == "SRC_BDC03"].empty
    tracked = issues[issues["rule_id"] == "SRC_BDC03P"]
    assert len(tracked) == 1
    assert (tracked.iloc[0]["severity"], tracked.iloc[0]["action"]) == ("INFO", "TRACK_ONLY")
    assert "printed_row: Target Co" in tracked.iloc[0]["evidence"]
    classified = build_source_reconciliation_residual_classification(detail)
    row = classified[classified["mechanism"] == PAGE_VERIFIED_MECHANISM]
    assert len(row) == 1 and not bool(row.iloc[0]["blocking_issue"])
    assert not classified["mechanism"].isin(["blocking_fair_value_scale_or_unit_candidate",
                                             "blocking_fair_value_disagreement"]).any()


def test_a_change_to_a_funds_printed_rows_changes_only_that_funds_cache_hash():
    from pipeline.source_reconciliation import _fold_printed_row_hashes
    hashes = pd.DataFrame({"cik": ["0000000100", "0000000200"], "holdings_hash": ["h1", "h2"],
                           "holdings_row_count": [1, 1]})
    printed = pd.DataFrame([{"cik": "0000000100", "accession_number": ACC, "raw_id_lower": "a", "printed_row": "A | 1"}])
    first = _fold_printed_row_hashes(hashes, printed)
    changed = _fold_printed_row_hashes(hashes, printed.assign(printed_row="A | 2"))
    assert first.iloc[0]["holdings_hash"] not in ("h1", changed.iloc[0]["holdings_hash"])
    assert list(first["holdings_hash"])[1] == list(changed["holdings_hash"])[1] == "h2"
    assert _fold_printed_row_hashes(hashes, printed.iloc[0:0]).equals(hashes)


def test_apply_leaves_text_indicator_columns_in_their_representation():
    tag, pub, line, corrected = SHAPES["unscaled_tag_published_in_thousands"]
    source, output, printed = _case(tag, pub, line, corrected)
    from pipeline.source_reconciliation import reconcile_bdc_source_to_holdings
    from tests.test_validate_holdings import _no_rescales
    detail, _ = reconcile_bdc_source_to_holdings(source, output, audited_value_rescales=_no_rescales())
    as_text = detail.astype(str)
    as_text["blocking_issue"] = as_text["blocking_issue"].map({"True": "1", "False": "0"})
    out = apply_page_verification(as_text, output, printed)
    assert _target(out)["blocking_issue"] == "0" and _target(out)["calibrated_status"] == PAGE_VERIFIED_STATUS
