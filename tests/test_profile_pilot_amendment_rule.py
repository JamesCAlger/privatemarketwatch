"""Filer-profile pilot: one authoritative instance per fund-quarter when an amendment exists.

Owner ruling 2026-10-04: prioritise the amendment unless it only carries the amended
datapoints. Synthetic instances only; the three real cases are proven in the real census.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.profile_pilot import cohort
from tests.test_profile_pilot_paths import fake_paths, held_lease, index_row, put_instance

CIK = "0001588272"
Q = "2025-12-31"
ORIGINAL = "0001193125-26-134282"
AMENDMENT = "0001193125-26-145482"
SECOND_AMENDMENT = "0001193125-26-150000"

HEAD = ('<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:dei="http://xbrl.sec.gov/dei/2025" '
        'xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">')
ENTITY = '<entity><identifier scheme="http://www.sec.gov/CIK">0001588272</identifier>{segment}</entity>'


def _context(cid, *, instant=None, end=None, identifier=None):
    segment = ""
    if identifier:
        segment = ('<segment><xbrldi:typedMember dimension="us-gaap:InvestmentIdentifierAxis">'
                   '<x>' + identifier + '</x></xbrldi:typedMember></segment>')
    period = ("<instant>" + instant + "</instant>" if instant
              else "<startDate>2025-01-01</startDate><endDate>" + end + "</endDate>")
    return ('<context id="' + cid + '">' + ENTITY.format(segment=segment)
            + "<period>" + period + "</period></context>")


def instance(*, positions=0, numeric=0, quarter=Q, period_end=None, amendment_flag="false",
             public_float_at=None, comparative_positions=0) -> str:
    """A small standalone instance: cover facts, optional schedule, optional plain numerics."""
    parts = [HEAD, _context("d", end=quarter), _context("i", instant=quarter),
             '<unit id="usd"><measure>iso4217:USD</measure></unit>',
             '<dei:DocumentPeriodEndDate contextRef="d">' + (period_end or quarter)
             + "</dei:DocumentPeriodEndDate>",
             '<dei:AmendmentFlag contextRef="d">' + amendment_flag + "</dei:AmendmentFlag>",
             '<dei:DocumentType contextRef="d">10-K</dei:DocumentType>']
    if public_float_at:
        parts += [_context("pf", instant=public_float_at),
                  '<dei:EntityPublicFloat contextRef="pf" unitRef="usd" decimals="0">0</dei:EntityPublicFloat>']
    for n in range(positions):
        cid = "p" + str(n)
        parts += [_context(cid, instant=quarter, identifier="Borrower " + str(n) + " Term Loan"),
                  '<us-gaap:InvestmentOwnedAtFairValue contextRef="' + cid
                  + '" unitRef="usd" decimals="0">' + str(1000 + n) + "</us-gaap:InvestmentOwnedAtFairValue>"]
    for n in range(comparative_positions):
        cid = "c" + str(n)
        parts += [_context(cid, instant="2024-12-31", identifier="Borrower " + str(n) + " Term Loan"),
                  '<us-gaap:InvestmentOwnedAtFairValue contextRef="' + cid
                  + '" unitRef="usd" decimals="0">5</us-gaap:InvestmentOwnedAtFairValue>']
    for n in range(numeric):
        parts.append('<us-gaap:Assets contextRef="i" unitRef="usd" decimals="0">' + str(n) + "</us-gaap:Assets>")
    parts.append("</xbrl>")
    return "".join(parts)


def select(tmp_path, filings, *, cik=CIK, quarter=Q):
    """filings: (accession, form, filing_date, xml text or None for an uncached candidate)."""
    from scripts.profile_pilot import instance_select
    rows = [index_row(str(int(cik)), acc, form, filed, quarter) for acc, form, filed, _ in filings]
    paths = fake_paths(tmp_path, index_rows=rows)
    for acc, _, _, text in filings:
        if text is not None:
            put_instance(paths.main_repo_root, str(int(cik)), acc, text)
    candidates = cohort.load_index_candidates(paths, ciks=[cik], quarters=[quarter])
    with held_lease(paths) as lease:
        return cohort.select_accession(paths, cik, quarter, candidates,
                                       scanner=instance_select.measure_instance, lease=lease)


def _by_accession(result):
    return {r["accession"]: r for r in result["source_selection"]}


# ---------------------------------------------------------------- measurement

def test_measure_counts_identifier_axis_fair_value_facts_at_the_report_date_only(tmp_path):
    from scripts.profile_pilot import instance_select
    path = tmp_path / "a.xml"
    path.write_text(instance(positions=3, numeric=4, comparative_positions=7, public_float_at=Q),
                    encoding="utf-8")
    got = instance_select.measure_instance(path, CIK, Q)
    assert got["source_complete"] is True and got["errors"] == []
    assert got["position_facts"] == 3  # comparative-period schedule rows are not counted
    assert got["numeric_facts"] == 7  # 3 schedule + 4 balance-sheet; the dei public float is not
    assert got["document_period_ends"] == [Q]
    assert got["amendment_flag"] == ["false"]
    assert got["target_instant_contexts"] == 5  # i, pf and three schedule contexts
    assert len(got["sha256"]) == 64 and got["bytes"] == path.stat().st_size


def test_measure_reports_a_missing_or_malformed_file_instead_of_raising(tmp_path):
    from scripts.profile_pilot import instance_select
    missing = instance_select.measure_instance(tmp_path / "none.xml", CIK, Q)
    assert missing["source_complete"] is False and missing["errors"]
    bad = tmp_path / "bad.xml"
    bad.write_text("<xbrl", encoding="utf-8")
    assert instance_select.measure_instance(bad, CIK, Q)["source_complete"] is False


# ---------------------------------------------------------------- the rule through select_accession

def test_cover_only_amendment_with_a_dei_instant_at_the_period_end_selects_the_original(tmp_path):
    # The NexPoint / TCW shape: the 10-K/A is a cover page whose dei:EntityPublicFloat sits on an
    # instant context dated at the period end, so "no target instant context" is false for it.
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=27, numeric=600)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(public_float_at=Q, amendment_flag="true"))])
    assert result["status"] == "selected"
    assert result["accession_number"] == ORIGINAL and result["form_type"] == "10-K"
    assert result["selection"] == "original_after_cover_only_amendment"
    rows = _by_accession(result)
    assert rows[AMENDMENT]["disposition"] == "cover_only_amendment"
    assert rows[AMENDMENT]["target_instant_contexts"] == 2 and rows[AMENDMENT]["numeric_facts"] == 0
    assert rows[ORIGINAL]["disposition"] == "selected" and rows[ORIGINAL]["count"] == 27
    assert rows[AMENDMENT]["ratio"] == 0.0 and rows[ORIGINAL]["ratio"] == 1.0


def test_every_candidate_is_recorded_with_form_date_counts_ratio_and_reason(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=27, numeric=600)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(public_float_at=Q))])
    rule = result["selection_rule"]
    assert rule["decision"] == "selected" and rule["reason"] == "original_after_cover_only_amendment"
    assert rule["measure"] == "identifier_axis_fair_value_facts" and rule["largest_count"] == 27
    assert rule["full_candidate_min_pct"] == 90 and rule["rule_version"] == "amendment-rule.v1"
    assert [r["accession"] for r in result["source_selection"]] == [AMENDMENT, ORIGINAL]  # latest first
    for row in result["source_selection"]:
        assert {"accession", "form_type", "filing_date", "position_facts", "numeric_facts", "count",
                "ratio", "full", "disposition", "sha256", "bytes"} <= set(row)
    assert [r["form_type"] for r in result["source_selection"]] == ["10-K/A", "10-K"]
    assert [r["filing_date"] for r in result["source_selection"]] == ["2026-04-06", "2026-03-27"]


def test_full_amendment_is_selected_over_the_original(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=100, numeric=50)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(positions=98, numeric=50))])
    assert result["status"] == "selected"
    assert result["accession_number"] == AMENDMENT and result["form_type"] == "10-K/A"
    assert result["selection"] == "latest_full_amendment"
    rows = _by_accession(result)
    assert rows[ORIGINAL]["disposition"] == "full_superseded_by_later_filing"
    assert rows[AMENDMENT]["ratio"] == 0.98


def test_the_latest_of_two_full_amendments_is_selected(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=20)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(positions=20)),
        (SECOND_AMENDMENT, "10-K/A", "2026-05-01", instance(positions=20))])
    assert result["accession_number"] == SECOND_AMENDMENT


def test_amendment_that_is_the_only_schedule_is_selected(tmp_path):
    # The CIK 1571329 2022-12-31 shape: the original has no target-quarter facts at all.
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance()),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(positions=40, numeric=10))])
    assert result["status"] == "selected" and result["accession_number"] == AMENDMENT
    assert _by_accession(result)[ORIGINAL]["disposition"] == "original_without_target_facts"


def test_partial_amendment_is_refused_and_neither_candidate_is_picked(tmp_path):
    # False-positive guard: 40% is neither cover-only nor full. The rule must not choose.
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=100)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(positions=40))])
    assert result["status"] == "unavailable"
    assert result["reason"] == "partial_amendment_needs_review"
    assert "accession_number" not in result and "source_path" not in result
    rows = _by_accession(result)
    assert rows[AMENDMENT]["disposition"] == "partial" and rows[AMENDMENT]["ratio"] == 0.4
    assert result["selection_rule"]["decision"] == "refused"


def test_amendment_with_financial_facts_but_no_schedule_is_refused_not_skipped(tmp_path):
    # It carries amended datapoints (non-dei numeric facts), so it is not cover-only.
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=100)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(numeric=5))])
    assert result["status"] == "unavailable"
    assert result["reason"] == "partial_amendment_needs_review"


@pytest.mark.parametrize("amended, expected", [(90, "selected"), (89, "unavailable")])
def test_boundary_exactly_ninety_percent_is_full_and_just_under_is_refused(tmp_path, amended, expected):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=100)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(positions=amended))])
    assert result["status"] == expected
    if expected == "selected":
        assert result["accession_number"] == AMENDMENT
    else:
        assert result["reason"] == "partial_amendment_needs_review"


def test_boundary_uses_integer_arithmetic_on_an_awkward_denominator():
    from scripts.profile_pilot import instance_select

    def cand(acc, form, filed, count):
        return dict(accession_number=acc, form_type=form, filing_date=filed, source_complete=True,
                    document_period_ends=[Q], position_facts=count, numeric_facts=count)

    # 27 of 30 is exactly 90%; 26 of 30 is 86.7%.
    full = instance_select.decide(Q, [cand("a", "10-K", "2026-03-01", 30), cand("b", "10-K/A", "2026-04-01", 27)])
    assert full["status"] == "selected" and full["accession_number"] == "b"
    under = instance_select.decide(Q, [cand("a", "10-K", "2026-03-01", 30), cand("b", "10-K/A", "2026-04-01", 26)])
    assert under["status"] == "unavailable" and under["reason"] == "partial_amendment_needs_review"
    assert instance_select.FULL_CANDIDATE_MIN_PCT == 90


def test_two_originals_are_refused_even_with_identical_schedules(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=20)),
        (SECOND_AMENDMENT, "10-K", "2026-03-30", instance(positions=20))])
    assert result["status"] == "unavailable" and result["reason"] == "two_originals_same_quarter"
    assert len(result["source_selection"]) == 2


def test_no_candidate_with_any_position_or_numeric_fact_is_refused(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance()),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(public_float_at=Q))])
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_candidate_with_position_facts"


def test_filer_without_an_identifier_axis_uses_the_numeric_fact_fallback(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(numeric=200)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(public_float_at=Q))])
    assert result["status"] == "selected" and result["accession_number"] == ORIGINAL
    assert result["selection_rule"]["measure"] == "non_dei_numeric_facts"
    assert result["selection_rule"]["largest_count"] == 200


def test_numeric_fallback_still_refuses_a_partial_amendment(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(numeric=200)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(numeric=80))])
    assert result["status"] == "unavailable" and result["reason"] == "partial_amendment_needs_review"


@pytest.mark.parametrize("flag", ["false", "true"])
def test_amendment_flag_does_not_change_the_outcome(tmp_path, flag):
    # dei:AmendmentFlag is false on real 10-K/As (Ares, TCW): the index form type decides.
    cover = select(tmp_path / "cover", [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=27, amendment_flag=flag)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(public_float_at=Q, amendment_flag=flag))])
    assert cover["accession_number"] == ORIGINAL
    assert _by_accession(cover)[AMENDMENT]["amendment_flag_recorded_not_used"] == [flag]
    full = select(tmp_path / "full", [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=27, amendment_flag=flag)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(positions=27, amendment_flag=flag))])
    assert full["accession_number"] == AMENDMENT


def test_candidate_for_another_period_end_is_refused(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=27)),
        (AMENDMENT, "10-K/A", "2026-04-06", instance(positions=27, period_end="2025-09-30"))])
    assert result["status"] == "unavailable" and result["reason"] == "candidate_period_end_mismatch"


def test_uncached_candidate_is_refused_without_guessing(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=27)),
        (AMENDMENT, "10-K/A", "2026-04-06", None)])
    assert result["status"] == "unavailable" and result["reason"] == "candidate_not_measurable"
    assert _by_accession(result)[AMENDMENT]["disposition"] == "not_measurable"


def test_amendment_of_another_form_family_is_refused(tmp_path):
    result = select(tmp_path, [
        (ORIGINAL, "10-K", "2026-03-27", instance(positions=27)),
        (AMENDMENT, "10-Q/A", "2026-04-06", instance(positions=27))])
    assert result["status"] == "unavailable" and result["reason"] == "mixed_form_family"


def test_selection_is_reproducible_and_the_policy_pins_the_rule(tmp_path):
    filings = [(ORIGINAL, "10-K", "2026-03-27", instance(positions=27, numeric=600)),
               (AMENDMENT, "10-K/A", "2026-04-06", instance(public_float_at=Q))]
    first, second = select(tmp_path / "a", filings), select(tmp_path / "b", filings)
    strip = lambda rows: [{k: v for k, v in r.items() if k != "path"} for r in rows]
    assert strip(first["source_selection"]) == strip(second["source_selection"])
    assert first["selection_rule"] == second["selection_rule"]
    paths = fake_paths(tmp_path / "policy")
    policy = cohort._selection_policy(paths)
    rule = policy["amendment_rule"]
    assert rule["module"] == "scripts/profile_pilot/instance_select.py" and len(rule["git_blob"]) == 40
    assert rule["rule_version"] == "amendment-rule.v1" and rule["full_candidate_min_pct"] == 90
    assert Path(paths.code_root, rule["module"]).is_file()
