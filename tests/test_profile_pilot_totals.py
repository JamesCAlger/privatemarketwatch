"""Task 3: independent_totals contract kind as pure functions.

Two whole-filing criteria that cannot abstain on a pure scale flip: the census current-period
FV sum on the census published basis (census-published.v1, SP3 Task 0) against the fund's filed investments_at_fair_value,
and the pct-of-net-assets sum. See scripts/profile_pilot/contracts_totals.py.
"""
import pytest

from tests.test_profile_pilot_contracts import mk_doc, debt, val
from scripts.profile_pilot import contracts_totals as ct
from scripts.profile_pilot.paths import PathError

BAND = dict(fv_residual_pct=5.0, pct_sum_min=50, pct_sum_max=250, pct_sum_shift_pp=15, min_positions=5)
FIN = dict(cik="0000000001", report_date="2026-03-31", investments_at_fair_value=80_000_000.0,
           net_assets=60_000_000.0, total_assets=90_000_000.0)


def book(n=80, fv="1000000", pct="1.25"):
    # census-shaped fields (status, fact_indices, facts) so the book also runs through learn_contracts,
    # the derived profile and the seed perturbations (Task 4), not only the pure totals functions
    return mk_doc([debt(i, extra=dict(fair_value=val(fv, "usd", decimals="0"), pct_of_net_assets=val(pct)))
                   for i in range(n)])


def test_observe_sums_current_period_positions_and_computes_residual():
    obs = ct.observe_totals(book(), financials=FIN, cik="0000000001")
    assert obs["n_positions"] == 80 and obs["fv_filled"] == 80
    assert obs["fv_sum"] == 80_000_000 and obs["fv_residual_pct"] == 0
    assert obs["pct_sum"] == 100 and obs["anchor_source"] == "fund_financials.investments_at_fair_value"


def test_observe_without_financials_has_no_anchor():
    obs = ct.observe_totals(book(), financials=None, cik="0000000001")
    assert obs["fv_anchor"] is None and obs["fv_residual_pct"] is None


def test_learn_then_holds_on_an_unchanged_book():
    q1 = book()
    contracts = ct.learn_totals("0000000001", "standard", BAND, q1, financials_q1=FIN)
    assert [c["field"] for c in contracts] == ["fair_value", "pct_of_net_assets"]
    assert all(c["learn_status"] == "learned" and c["status_basis"] == "provisional" for c in contracts)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    res = [ct.evaluate_totals(c, q2, book(), financials_q2=FIN, band=BAND) for c in contracts]
    assert [r["status"] for r in res] == ["holds", "holds"]


def test_x100_scale_flip_on_fair_value_breaches_fv_and_pct_flip_breaches_pct():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    fv_flip = book(fv="100000000")          # x100 on every row
    r = ct.evaluate_totals(contracts[0], q2, fv_flip, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach" and r["cause"] == "fv_residual_outside_band"
    pct_flip = book(pct="125")              # x100 on every row
    r = ct.evaluate_totals(contracts[1], q2, pct_flip, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach" and r["cause"] == "pct_sum_outside_band"


def test_partial_flip_at_twenty_percent_of_rows_is_detected():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    doc = book()
    for p in doc["positions"][:16]:      # 20% of 80 rows x100
        p["fields"]["fair_value"] = val("100000000", unit="USD")
    r = ct.evaluate_totals(contracts[0], q2, doc, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach"


def test_missing_anchor_in_q2_abstains_with_cause_no_anchor():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    r = ct.evaluate_totals(contracts[0], q2, book(), financials_q2=None, band=BAND)
    assert r["status"] == "insufficient_evidence" and r["cause"] == "no_anchor"


def test_pct_sum_shift_within_band_holds_and_beyond_band_breaches():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    assert ct.evaluate_totals(contracts[1], q2, book(pct="1.40"), financials_q2=FIN, band=BAND)["status"] == "holds"   # 112
    r = ct.evaluate_totals(contracts[1], q2, book(pct="1.50"), financials_q2=FIN, band=BAND)                          # 120
    assert r["status"] == "breach" and r["cause"] == "pct_sum_shifted"


def test_too_few_positions_never_learns():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(n=3), financials_q1=FIN)
    assert all(c["learn_status"] == "insufficient_evidence" for c in contracts)
    assert contracts[0]["learn_cause"] == "too_few_positions"


def test_shrunken_q2_book_abstains_both_fields_with_too_few_positions():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    res = [ct.evaluate_totals(c, q2, book(n=3), financials_q2=FIN, band=BAND) for c in contracts]
    assert [r["status"] for r in res] == ["insufficient_evidence", "insufficient_evidence"]
    assert [r["cause"] for r in res] == ["too_few_positions", "too_few_positions"]


def test_large_book_with_unfilled_pct_abstains_pct_not_filled():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    doc = book()
    for p in doc["positions"][3:]:
        p["fields"]["pct_of_net_assets"] = val(None)
    r_fv = ct.evaluate_totals(contracts[0], q2, doc, financials_q2=FIN, band=BAND)
    assert r_fv["status"] == "holds"
    r_pct = ct.evaluate_totals(contracts[1], q2, doc, financials_q2=FIN, band=BAND)
    assert r_pct["status"] == "insufficient_evidence" and r_pct["cause"] == "pct_not_filled"


# ---------------------------------------------------------------- Task 4: wiring (tolerances v4, contracts, seed)

# Brief-vs-code: the brief builds v3 as semantic_tolerances(tolerances()), but tolerances() already IS the
# frozen v3 content (tolerance_content()), semantic_tolerances() accepts only v2, and without bands= it yields
# None candidate bands (calibration mode). The frozen v3 is used directly.
from tests.test_profile_pilot_contracts import learn, evaluate, pick, tolerances as tol_v3  # noqa: E402


def test_v4_tolerances_carry_v3_verbatim_and_the_totals_bands():
    from scripts.profile_pilot import contracts
    v3 = tol_v3()
    v4 = contracts.tolerance_content_v4(v3)
    assert v4["version"] == 4 and v4["v3_verbatim"] == v3
    assert v4["bands"]["standard"]["independent_totals"] == dict(fv_residual_pct=5.0, pct_sum_min=50, pct_sum_max=250,
                                                               pct_sum_shift_pp=15, min_positions=5)
    assert v4["bands"]["low_history"]["independent_totals"]["fv_residual_pct"] == 10.0
    assert v4["provisional_kinds"] == ["independent_totals"]
    assert contracts.band_for(v4, "standard", "independent_totals") == v4["bands"]["standard"]["independent_totals"]


def test_learn_and_evaluate_route_the_totals_kind_whole_filing():
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(tol_v3())
    q1 = book()
    block = learn(q1, tol=v4, financials_q1=FIN)
    ids = {c["contract_id"] for c in block["contracts"] if c["kind"] == "independent_totals"}
    assert len(ids) == 2
    res = evaluate(block, book(fv="100000000"), tol=v4, financials_q2=FIN)
    assert pick(res, "independent_totals", "fair_value")["status"] == "breach"
    assert pick(res, "independent_totals", "pct_of_net_assets")["status"] == "holds"
    assert all(r.get("status_basis") == "provisional" for r in res if r["kind"] == "independent_totals")


def test_m2_denominator_counts_two_totals_contracts_per_cik():
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(tol_v3())
    block = learn(book(), tol=v4, financials_q1=FIN)
    assert sum(1 for c in block["contracts"] if c["kind"] == "independent_totals") == 2


def test_v4_digests_and_supersedes_record_v3_and_v2_stays_verbatim():
    from scripts.profile_pilot import contracts, manifest, m2_seed
    v3 = tol_v3()
    v4 = contracts.tolerance_content_v4(v3)
    assert v4["v3_content_sha256"] == manifest.digest(v3) == v4["supersedes"]["superseded_v4"]
    assert manifest.digest(v4["v3_verbatim"]["v2_verbatim"]) == m2_seed.TOLERANCES_V2_SHA256
    assert v4["calibration"]["v4_quarters_seen"] == []
    assert v3 == tol_v3()          # the v3 input is not mutated


def test_v2_and_v3_tolerances_learn_no_totals_contracts():
    from scripts.profile_pilot import contracts
    v3 = tol_v3()
    for tol in (contracts.tolerance_content_v2(), v3):
        block = learn(book(), tol=tol, financials_q1=FIN)
        assert not any(c["kind"] == "independent_totals" for c in block["contracts"])


def test_totals_contracts_do_not_abstain_on_an_ambiguous_partition_overlap(monkeypatch):
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(tol_v3())
    block = learn(book(), tol=v4, financials_q1=FIN)
    frame = contracts._q2_frame
    monkeypatch.setattr(contracts, "_q2_frame",
                        lambda *a, **k: dict(frame(*a, **k), ambiguous={"whole_filing": ["c0"]}))
    res = evaluate(block, book(), tol=v4, financials_q2=FIN)
    assert pick(res, "fill_rate", "interest_rate")["cause"] == "ambiguous_partition_overlap"
    assert [pick(res, "independent_totals", f)["status"] for f in ct.FIELDS] == ["holds", "holds"]


def test_totals_field_constants_agree_with_the_backtest():
    from scripts.profile_pilot import m2_backtest as bt
    assert bt.TOTALS_FIELD == ct.TOTALS_FIELD and bt.PCT_FIELD == ct.PCT_FIELD
    assert bt.SUITE["independent_totals"] == (ct.TOTALS_FIELD, ct.PCT_FIELD)
    assert "independent_totals" in bt.KNOWN_KINDS


# ---------------------------------------------------------------- Task 4: pinned fund_financials slice

def _fake_financials(tmp_path, rows):
    from tests.test_profile_pilot_paths import fake_paths
    paths = fake_paths(tmp_path, run_id="stageb-contracts-t4")
    header = "cik,entity_name,report_date,total_assets,net_assets,investments_at_fair_value,investments_at_cost\n"
    body = "".join(",".join(str(v) for v in r) + "\n" for r in rows)
    (paths.output_root / "fund_financials.csv").write_text(header + body, encoding="ascii")
    return paths


def test_financials_slice_keeps_the_eight_ciks_padded_and_load_returns_one_row(tmp_path):
    from scripts.profile_pilot import cohort, contracts_run
    pilot = cohort.PILOT_CIKS[0]
    paths = _fake_financials(tmp_path, [
        (str(int(pilot)), "Pilot", "2026-03-31", 90, 60, 80, 79),
        (pilot, "Pilot", "2025-12-31", 91, 61, 81, 80),
        ("0000000009", "Other", "2026-03-31", 1, 1, 1, 1)])
    record = contracts_run.materialise_financials_slice(paths)
    assert record["label"] == "run/" + contracts_run.FINANCIALS_SLICE and record["rows_by_cik"] == {pilot: 2}
    assert record["source"]["label"] == "output/fund_financials.csv"
    row = contracts_run.load_financials(paths, pilot, "2026-03-31")
    assert row == dict(cik=pilot, report_date="2026-03-31", investments_at_fair_value=80.0, net_assets=60.0,
                       total_assets=90.0)
    assert contracts_run.load_financials(paths, pilot, "2024-03-31") is None
    assert contracts_run.load_financials(paths, "0000000009", "2026-03-31") is None
    with pytest.raises(PathError):
        contracts_run.materialise_financials_slice(paths)                 # write-once


def test_load_financials_refuses_two_rows_for_one_quarter(tmp_path):
    from scripts.profile_pilot import cohort, contracts, contracts_run
    pilot = cohort.PILOT_CIKS[0]
    paths = _fake_financials(tmp_path, [(pilot, "A", "2026-03-31", 1, 1, 1, 1), (pilot, "B", "2026-03-31", 2, 2, 2, 2)])
    contracts_run.materialise_financials_slice(paths)
    with pytest.raises(contracts.ContractError):
        contracts_run.load_financials(paths, pilot, "2026-03-31")


def test_strict_reading_exempts_totals_like_the_yield_when_the_identifier_format_is_unresolved():
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(tol_v3())
    block = learn(book(), tol=v4, financials_q1=FIN)
    res = [dict(r, identifier_format_unresolved=True)
           for r in evaluate(block, book(fv="100000000"), tol=v4, financials_q2=FIN)]
    strict = {r["contract_id"]: r for r in contracts.strict_results(res)}
    totals = [r for r in res if r["kind"] == "independent_totals"]
    assert [r["status"] for r in totals] == ["breach", "holds"]
    assert all(strict[r["contract_id"]]["status"] == r["status"] and strict[r["contract_id"]]["cause"] == r["cause"]
               for r in totals)
    fill = pick(res, "fill_rate", "interest_rate")
    assert fill["status"] == "holds" and strict[fill["contract_id"]]["cause"] == "identifier_format_unresolved"


# ---------------------------------------------------------------- sp1 Task 6a: --tolerances-version wiring

def test_tolerances_for_version_three_is_the_v3_content_untouched():
    from scripts.profile_pilot import contracts, contracts_run
    content = contracts_run._tolerances_for_version(3)
    assert content == contracts.tolerance_content()
    assert "independent_totals" not in content["bands"]["standard"]


def test_tolerances_for_version_four_carries_the_pre_registered_totals_bands():
    from scripts.profile_pilot import contracts, contracts_run
    content = contracts_run._tolerances_for_version(4)
    assert content == contracts.tolerance_content_v4(contracts.tolerance_content())
    standard = content["bands"]["standard"]["independent_totals"]
    low = content["bands"]["low_history"]["independent_totals"]
    assert standard["fv_residual_pct"] == 5.0 and standard["pct_sum_shift_pp"] == 15
    assert low["fv_residual_pct"] == 10.0 and low["pct_sum_shift_pp"] == 25


def test_kinds_for_version_excludes_independent_totals_under_three_only():
    from scripts.profile_pilot import contracts, contracts_run
    assert contracts_run._kinds_for_version(3) == [k for k in contracts.ALL_KINDS if k != contracts.TOTALS_KIND]
    assert contracts.TOTALS_KIND not in contracts_run._kinds_for_version(3)
    assert contracts_run._kinds_for_version(4) == list(contracts.ALL_KINDS)
    assert contracts.TOTALS_KIND in contracts_run._kinds_for_version(4)


# ---------------------------------------------------------------- sp1 Task 6a: status_basis on the shared _result path

def test_not_learned_totals_results_carry_provisional_status_basis_but_fill_rate_does_not():
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(tol_v3())
    block = learn(book(n=3), tol=v4, financials_q1=None)
    totals_contracts = [c for c in block["contracts"] if c["kind"] == "independent_totals"]
    assert len(totals_contracts) == 2 and all(c["learn_status"] != "learned" for c in totals_contracts)
    res = evaluate(block, book(n=3), tol=v4, financials_q2=FIN)
    totals = [r for r in res if r["kind"] == "independent_totals"]
    assert len(totals) == 2
    assert all(r["cause"].startswith("not_learned_in_q1") for r in totals)
    assert all(r.get("status_basis") == "provisional" for r in totals)
    fill = pick(res, "fill_rate", "interest_rate")
    assert "status_basis" not in fill


def test_q2_unavailable_totals_results_carry_provisional_status_basis_but_fill_rate_does_not():
    from scripts.profile_pilot import contracts
    v4 = contracts.tolerance_content_v4(tol_v3())
    block = learn(book(), tol=v4, financials_q1=FIN)
    res = evaluate(block, None, tol=v4, financials_q2=FIN)
    assert res and all(r["cause"] == "q2_census_unavailable" for r in res)
    totals = [r for r in res if r["kind"] == "independent_totals"]
    assert len(totals) == 2 and all(r.get("status_basis") == "provisional" for r in totals)
    fill = pick(res, "fill_rate", "interest_rate")
    assert "status_basis" not in fill


# ---------------------------------------------------------------- SP3 Task 0 / Task 2: census published basis

BCRED = "0001803498"
FIN600 = dict(FIN, investments_at_fair_value=600.0)


def bcred_doc():
    def fv_row(ctx, ident, fv):
        return dict(ctx=ctx, ident=ident, fields=dict(fair_value=val(fv, "usd", decimals="0"),
                                                      pct_of_net_assets=val("1.0")))
    return mk_doc([fv_row("p1", "Alpha Co | First Lien Term Loan", "100"),
                   fv_row("p2", "Beta Co | Second Lien Term Loan", "200"),
                   fv_row("p3", "Gamma Co | Common Equity", "300"),
                   fv_row("e1", "Delta Co Senior Loan | Emerald JV LP", "50"),
                   fv_row("e2", "Epsilon Co Term Loan | Emerald JV LP", "60"),
                   fv_row("t1", "Total Investments", "600"),
                   fv_row("k1", "Cash and cash equivalents", "10")])


def test_observe_sums_the_census_published_basis_and_reports_removed_by_rule():
    from scripts.profile_pilot import census_published as cp
    doc = bcred_doc()
    obs = ct.observe_totals(doc, financials=FIN600, cik=BCRED)
    assert obs["fv_sum"] == 600 and obs["n_positions"] == 3 and obs["fv_filled"] == 3
    assert obs["fv_sum"] == float(cp.published_fv_sum(doc, cik=BCRED))
    assert obs["pct_sum"] == 3.0 and obs["pct_filled"] == 3 and obs["fv_residual_pct"] == 0
    assert obs["published_version"] == cp.CENSUS_PUBLISHED_VERSION
    removed = obs["removed_by_rule"]
    assert removed["R3_label_or_heading"] == dict(n=1, fv=600.0)
    assert removed["R4_generic_cash_bucket"] == dict(n=1, fv=10.0)
    assert removed["R6_reporting_entity_lookthrough"] == dict(n=2, fv=110.0)
    assert all(removed[r] == dict(n=0, fv=0.0) for r in ("R1_own_period_instant", "R2_fv_not_reported",
                                                          "R5_issuer_rollup_fv_only"))


def test_published_basis_fair_value_contract_holds_at_anchor_600_and_carries_the_partition_version():
    from scripts.profile_pilot import census_published as cp
    band = dict(BAND, min_positions=3)
    contracts = ct.learn_totals(BCRED, "standard", band, bcred_doc(), financials_q1=FIN600)
    assert contracts[0]["learn_status"] == "learned"
    assert all(c["applies_to"] == {"whole_filing": True, "census_published": cp.CENSUS_PUBLISHED_VERSION}
               and c["partition_id"] == "whole_filing" for c in contracts)
    assert contracts[0]["contract_id"] == BCRED + ":independent_totals:fair_value:whole_filing"
    assert contracts[0]["evidence"]["removed_by_rule"]["R6_reporting_entity_lookthrough"]["n"] == 2
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    r = ct.evaluate_totals(contracts[0], q2, bcred_doc(), financials_q2=FIN600, band=band)
    assert r["status"] == "holds" and r["observed"]["fv_sum"] == 600
    assert r["applies_to"]["census_published"] == cp.CENSUS_PUBLISHED_VERSION


def test_other_filer_keeps_the_emerald_rows_published():
    obs = ct.observe_totals(bcred_doc(), financials=FIN600, cik="0000000001")
    assert obs["n_positions"] == 5 and obs["fv_sum"] == 710
    assert obs["removed_by_rule"]["R6_reporting_entity_lookthrough"]["n"] == 0


def test_book_rows_remove_nothing():
    obs = ct.observe_totals(book(), financials=FIN, cik="0000000001")
    assert obs["n_positions"] == 80 and all(v["n"] == 0 for v in obs["removed_by_rule"].values())


def test_one_evaluate_call_classifies_the_q2_doc_once_and_the_cache_changes_nothing(monkeypatch):
    from scripts.profile_pilot import contracts, census_published as cp
    v4 = contracts.tolerance_content_v4(tol_v3())
    block = learn(book(), tol=v4, financials_q1=FIN)
    q2_doc = book(fv="100000000")
    plain = evaluate(block, q2_doc, tol=v4, financials_q2=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    totals = [c for c in block["contracts"] if c["kind"] == "independent_totals"]
    uncached = [ct.evaluate_totals(c, q2, q2_doc, financials_q2=FIN, band=c["band"]) for c in totals]
    real, calls = cp.classify, []

    def counting(doc, *, cik):
        calls.append(cik)
        return real(doc, cik=cik)
    monkeypatch.setattr(cp, "classify", counting)
    cached = evaluate(block, q2_doc, tol=v4, financials_q2=FIN)
    assert len(calls) == 1
    assert cached == plain
    shared = {}
    calls.clear()
    with_cache = [ct.evaluate_totals(c, q2, q2_doc, financials_q2=FIN, band=c["band"], cache=shared) for c in totals]
    assert len(calls) == 1 and with_cache == uncached
