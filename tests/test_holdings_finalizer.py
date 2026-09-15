"""Final identity writes preserve complete pairs and reject incomplete outputs."""
import os

import duckdb
import pandas as pd
import pytest

from pipeline import holdings_finalizer as finalizer
from pipeline.programme.artifacts import SCHEMAS, verify_pair
from tests.test_position_matching import _make_bdc_raw


def holdings(rows=None):
    base = dict(source="bdc", cik="0000000123", entity_name="Test BDC",
        report_date="2026-03-31", quarter="2026Q1", filing_date="2026-05-01",
        accession_number="accession", issuer_name="Acme Corp", fair_value="-15",
        cost="0", asset_category="LOAN", issuer_category="CORPORATE",
        index_classification="DIRECT_LENDING", exposure_type="DIRECT",
        asset_class="PRIVATE_CREDIT", coupon_type="Floating",
        bdc_investment_identifier="Acme First Lien", row_id="ROW-1",
        row_id_basis="src_anchor", position_id="POS-1")
    return pd.DataFrame([{**dict.fromkeys(SCHEMAS["private_markets_holdings.csv"], ""),
                          **base, **row} for row in (rows or [{}])])


def matches():
    return pd.DataFrame(columns=SCHEMAS["position_matches.csv"])


def ready_holdings(rows=None):
    from pipeline.financial_conventions import prepare
    return prepare(holdings(rows),source_frame=True)[0]


def test_final_pairs_keep_identity_negative_values_and_explicit_zero(tmp_path):
    hp, mp = tmp_path / "private_markets_holdings.csv", tmp_path / "position_matches.csv"
    result, _, metadata = finalizer.write_final_identity(ready_holdings(), matches(), holdings_file=hp, matches_file=mp)
    assert result.iloc[0].position_id == "POS-1"
    assert result.iloc[0].row_id == "ROW-1"
    with duckdb.connect() as con:
        assert verify_pair(hp, con)["typed_multiset_difference"] == 0
        assert verify_pair(mp, con)["rows"] == 0
        assert con.execute("SELECT fair_value,cost FROM read_parquet(?)", [str(hp.with_suffix('.parquet'))]).fetchone() == (-15, 0)
    assert metadata[hp.name]["rows"] == 1


@pytest.mark.parametrize("change,pattern", [
    ({"position_id": ""}, "position IDs"), ({"row_id": ""}, "missing row_id"),
    ({"asset_class": "INVALID"}, "schema violations"),
])
def test_invalid_final_identity_writes_nothing(tmp_path, change, pattern):
    with pytest.raises(ValueError, match=pattern):
        finalizer.write_final_identity(ready_holdings([change]), matches(),
            holdings_file=tmp_path / "private_markets_holdings.csv", matches_file=tmp_path / "position_matches.csv")
    assert not list(tmp_path.iterdir())


def test_last_pair_failure_preserves_all_previous_files(tmp_path, monkeypatch):
    hp, mp = tmp_path / "private_markets_holdings.csv", tmp_path / "position_matches.csv"
    paths = (hp, mp, hp.with_suffix(".parquet"), mp.with_suffix(".parquet"))
    for path in paths:
        path.write_bytes(b"old " + path.name.encode())
    before = {p: p.read_bytes() for p in paths}
    original = finalizer.finalize_pair
    def fail_last(path, con):
        if path.name == mp.name:
            raise ValueError("injected final pair failure")
        return original(path, con)
    monkeypatch.setattr(finalizer, "finalize_pair", fail_last)
    with pytest.raises(ValueError, match="injected"):
        finalizer.write_final_identity(ready_holdings(), matches(), holdings_file=hp, matches_file=mp)
    assert {p: p.read_bytes() for p in paths} == before


def test_existing_holdings_complete_real_entity_and_position_writers(tmp_path):
    hp = tmp_path / "private_markets_holdings.csv"
    # Separate tranches survive as separate singletons even with one issuer.
    frame = holdings([
        {"position_id": "", "fair_value": "100", "principal_amount": "100", "cost": "90"},
        {"position_id": "", "row_id": "ROW-2", "fair_value": "200", "principal_amount": "200",
         "cost": "180", "bdc_investment_identifier": "Acme Second Lien"},
    ])
    frame.to_csv(hp, index=False)
    output, paired = finalizer.finalize_existing_holdings(
        holdings_file=hp, rebuild_entities=True, bdc_raw_df=_make_bdc_raw([]))
    assert len(output) == 2
    assert output.position_id.nunique() == 2
    assert output.entity_id.fillna("").ne("").all()
    assert set(output.row_id) == {"ROW-1", "ROW-2"}
    assert paired.empty
    with duckdb.connect() as con:
        for name in ("private_markets_holdings.csv", "position_matches.csv", "position_id_edges.csv",
                     "entity_lookup.csv", "entity_resolution_stats.csv"):
            assert verify_pair(tmp_path / name, con)["typed_multiset_difference"] == 0


def test_default_rebuild_uses_finalizer_before_replacing_holdings(tmp_path, monkeypatch):
    from pipeline import config, unified_holdings
    hp = tmp_path / "private_markets_holdings.csv"
    hp.write_bytes(b"previous completed holdings")
    monkeypatch.setattr(config, "UNIFIED_HOLDINGS_FILE", hp)
    def build(bdc_df, nport_df, *, output_file, orphan_file, **kwargs):
        assert output_file != hp
        assert output_file.parent == orphan_file.parent
        assert hp.read_bytes() == b"previous completed holdings"
        frame = holdings([{"position_id": ""}])
        frame.to_csv(output_file, index=False)
        return frame
    monkeypatch.setattr(unified_holdings, "build_unified_holdings", build)
    output, _ = finalizer.build_final_holdings(bdc_df=_make_bdc_raw([]))
    assert output.position_id.str.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}').all()
    assert pd.read_csv(hp).position_id.notna().all()


@pytest.mark.parametrize("stale", [False, True])
def test_export_uses_actual_ri07_without_writing_validation_outputs(tmp_path, stale):
    hp, rp = tmp_path / "private_markets_holdings.csv", tmp_path / "position_returns.csv"
    ready_holdings().to_csv(hp, index=False)
    pd.DataFrame(columns=["position_id", "quarter"]).to_csv(rp, index=False)
    os.utime(rp, (1000, 1000))
    os.utime(hp, (2000 if stale else 1000, 2000 if stale else 1000))
    if stale:
        with pytest.raises(ValueError, match="RI07"):
            finalizer.require_exportable_identity(holdings_file=hp, returns_file=rp)
    else:
        finalizer.require_exportable_identity(holdings_file=hp, returns_file=rp)
    assert {p.name for p in tmp_path.iterdir()} == {hp.name, rp.name}


def test_export_guard_runs_before_first_json_write(monkeypatch):
    from pipeline import export_frontend
    def rejected():
        raise ValueError("incomplete identity")
    monkeypatch.setattr(finalizer, "require_exportable_identity", rejected)
    with pytest.raises(ValueError, match="incomplete identity"):
        export_frontend.export_all()


def test_enrichment_writes_csv_and_parquet_through_final_identity(tmp_path,monkeypatch):
    from pipeline import position_matching
    raw=tmp_path/"bdc_raw.csv"
    _make_bdc_raw([]).to_csv(raw,index=False)
    monkeypatch.setattr(position_matching,"BDC_HOLDINGS_FILE",raw)
    hp=tmp_path/"private_markets_holdings.csv"
    output,_=finalizer.finalize_enriched_holdings(holdings([{"gics_sub_industry":"Application Software"}]),holdings_file=hp)
    assert output.iloc[0].gics_sub_industry=="Application Software"
    with duckdb.connect() as con:
        assert verify_pair(hp,con)["rows"]==1
