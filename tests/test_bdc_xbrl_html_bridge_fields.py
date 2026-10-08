"""Tests for the HTML-section bridge field extraction + overlay (maturity,
reference rate) added for filers that leave these untagged per-position."""
import json
import pandas as pd

from pipeline.bdc_xbrl_html_bridge import (
    _section_for_row,
    _extract_row_dates,
    _extract_reference_rate,
    _search_terms,
    apply_html_section_bridge_field_overlays,
    BRIDGE_SCHEMA_VERSION,
)


# --- section detection: "(continued)" ---
def test_section_matches_continued():
    assert _section_for_row(["First Lien Debt (continued)"]) == ("debt", "First Lien Debt")
    assert _section_for_row(["First Lien Debt"]) == ("debt", "First Lien Debt")
    assert _section_for_row(["Second Lien Debt (Continued)"]) == ("debt", "Second Lien Debt")


# --- date extraction: maturity = latest date in the row ---
def test_extract_row_dates_orders_and_picks():
    row = ["Atlas CC Acquisition Corp.", "(10)(17)", "SOFR +", "4.25 %", "8.37 %",
           "7/25/2025", "5/25/2029", "$", "41,085"]
    dates = _extract_row_dates(row)
    assert dates[-1].isoformat() == "2029-05-25"   # maturity (latest)
    assert dates[0].isoformat() == "2025-07-25"    # acquisition (earliest)


def test_extract_row_dates_month_only():
    assert _extract_row_dates(["Acme", "due 2/2032"])[-1].isoformat() == "2032-02-29"


def test_extract_row_dates_rejects_implausible():
    assert _extract_row_dates(["Acme", "13/40/2029"]) == []   # invalid month/day


# --- reference rate ---
def test_extract_reference_rate():
    assert _extract_reference_rate(["x", "SOFR +", "4.25 %"]) == "SOFR"
    assert _extract_reference_rate(["x", "P +", "3.00 %"]) == "PRIME"
    assert _extract_reference_rate(["x", "Fixed", "9.0 %"]) == ""


# --- search terms: pipe/affiliation suffix + tranche number stripped ---
def test_search_terms_strip_pipe_affiliation():
    terms = _search_terms({"raw_investment_identifier": "123Dentist, Inc. 1 | Non-Affiliated Issuer"})
    joined = " ".join(terms).lower()
    assert "issuer" not in joined          # affiliation suffix removed
    assert "|" not in joined
    assert any("dentist" in t.lower() for t in terms)


def test_search_terms_plain_identifier_unchanged():
    # HPS-style clean identifier must still work (no pipe)
    terms = _search_terms({"raw_investment_identifier": "720 East CLO V Ltd"})
    assert any("clo v ltd" in t.lower() for t in terms)


# --- overlay: blank-only, exact-keyed, no clobber ---
def _write_bridge(tmp_path, rows):
    data = {"schema_version": BRIDGE_SCHEMA_VERSION, "admission_status": "promoted", "cik": "0001803498",
            "version": 1, "source": "bdc_xbrl", "bridges": rows}
    (tmp_path / "0001803498.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def test_field_overlay_fills_blank_only(tmp_path):
    _write_bridge(tmp_path, [{
        "accession_number": "0001803498-26-000014", "report_date": "2025-12-31",
        "raw_id_lower": "acme corp 1 | non-affiliated issuer", "family": "debt",
        "maturity_date": "2030-05-25", "reference_rate_type": "SOFR",
    }])
    df = pd.DataFrame([
        # blank maturity -> should be filled
        {"cik": "0001803498", "accession_number": "0001803498-26-000014",
         "report_date": "2025-12-31",
         "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
         "maturity_date": "", "reference_rate_type": "", "reference_rate_source": ""},
        # already-populated maturity -> must NOT be clobbered
        {"cik": "0001803498", "accession_number": "0001803498-26-000014",
         "report_date": "2025-12-31",
         "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
         "maturity_date": "2099-01-01", "reference_rate_type": "LIBOR",
         "reference_rate_source": "identifier_text"},
    ])
    out = apply_html_section_bridge_field_overlays(df, identifier_col="bdc_investment_identifier", bridge_dir=tmp_path)
    assert out.iloc[0]["maturity_date"] == "2030-05-25"
    assert out.iloc[0]["reference_rate_type"] == "SOFR"
    assert out.iloc[0]["reference_rate_source"] == "html_section_bridge"
    # no clobber
    assert out.iloc[1]["maturity_date"] == "2099-01-01"
    assert out.iloc[1]["reference_rate_type"] == "LIBOR"


def test_field_overlay_no_match_is_noop(tmp_path):
    _write_bridge(tmp_path, [{
        "accession_number": "DIFFERENT-ACC", "report_date": "2025-12-31",
        "raw_id_lower": "acme corp 1 | non-affiliated issuer", "family": "debt",
        "maturity_date": "2030-05-25",
    }])
    df = pd.DataFrame([{
        "cik": "0001803498", "accession_number": "0001803498-26-000014",
        "report_date": "2025-12-31",
        "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
        "maturity_date": "", "reference_rate_type": "", "reference_rate_source": ""}])
    # bridge_dir has no matching accession -> no overlay
    out = apply_html_section_bridge_field_overlays(df, identifier_col="bdc_investment_identifier", bridge_dir=tmp_path)
    assert out.iloc[0]["maturity_date"] == ""


def test_overlay_records_src_field_override_ref(tmp_path):
    """Overlaying a bridge value must record coordinate refs in src_field_overrides."""
    _write_bridge(tmp_path, [{
        "accession_number": "0001803498-26-000014", "report_date": "2025-12-31",
        "raw_id_lower": "acme corp 1 | non-affiliated issuer", "family": "debt",
        "maturity_date": "2030-05-25", "reference_rate_type": "SOFR",
        "html_sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "table_index": 2, "row_index": 15,
    }])
    df = pd.DataFrame([{
        "cik": "0001803498", "accession_number": "0001803498-26-000014",
        "report_date": "2025-12-31",
        "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
        "maturity_date": "", "reference_rate_type": "", "reference_rate_source": "",
    }])
    out = apply_html_section_bridge_field_overlays(
        df, identifier_col="bdc_investment_identifier", bridge_dir=tmp_path)
    ref = out.iloc[0]["src_field_overrides"]
    assert "maturity_date=bridge:a1b2c3d4:t2:r15" in ref
    assert "reference_rate_type=bridge:a1b2c3d4:t2:r15" in ref
    # both refs present, joined by semicolons
    parts = ref.split(";")
    assert len(parts) == 2


def test_overlay_degraded_bridge_ref_missing_sha(tmp_path):
    """A bridge record with a missing html_sha256 must produce a degraded ref (empty sha8)
    rather than crashing. Expected format: field=bridge::t<T>:r<R>."""
    _write_bridge(tmp_path, [{
        "accession_number": "0001803498-26-000014", "report_date": "2025-12-31",
        "raw_id_lower": "acme corp 1 | non-affiliated issuer", "family": "debt",
        "maturity_date": "2030-05-25", "reference_rate_type": "SOFR",
        # html_sha256 intentionally absent (missing key)
        "table_index": 3, "row_index": 9,
    }])
    df = pd.DataFrame([{
        "cik": "0001803498", "accession_number": "0001803498-26-000014",
        "report_date": "2025-12-31",
        "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
        "maturity_date": "", "reference_rate_type": "", "reference_rate_source": "",
    }])
    out = apply_html_section_bridge_field_overlays(
        df, identifier_col="bdc_investment_identifier", bridge_dir=tmp_path)
    ref = out.iloc[0]["src_field_overrides"]
    # degraded ref: sha8 is empty string -> "bridge::t3:r9"
    assert "maturity_date=bridge::t3:r9" in ref
    assert "reference_rate_type=bridge::t3:r9" in ref


def test_overlay_src_field_overrides_appends_to_existing(tmp_path):
    """If src_field_overrides already has a value, the bridge ref is appended with ';'."""
    _write_bridge(tmp_path, [{
        "accession_number": "0001803498-26-000014", "report_date": "2025-12-31",
        "raw_id_lower": "acme corp 1 | non-affiliated issuer", "family": "debt",
        "maturity_date": "2030-05-25", "reference_rate_type": "",
        "html_sha256": "ffffffff000000001111111122222222ffffffff000000001111111122222222",
        "table_index": 0, "row_index": 7,
    }])
    df = pd.DataFrame([{
        "cik": "0001803498", "accession_number": "0001803498-26-000014",
        "report_date": "2025-12-31",
        "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
        "maturity_date": "", "reference_rate_type": "", "reference_rate_source": "",
        "src_field_overrides": "some_prior_ref=xbrl:ctx123",
    }])
    out = apply_html_section_bridge_field_overlays(
        df, identifier_col="bdc_investment_identifier", bridge_dir=tmp_path)
    ref = out.iloc[0]["src_field_overrides"]
    assert ref.startswith("some_prior_ref=xbrl:ctx123;")
    assert "maturity_date=bridge:ffffffff:t0:r7" in ref


# --- iXBRL contextRef-anchored field bridge ---
_IX_NS = (
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2024"'
)


def _ix_context(cid, ident, instant="2025-12-31"):
    seg = ""
    if ident is not None:
        seg = (f'<xbrldi:typedMember dimension="us-gaap:InvestmentIdentifierAxis">'
               f'<x>{ident}</x></xbrldi:typedMember>')
    return (f'<xbrli:context id="{cid}"><xbrli:entity>'
            f'<xbrli:identifier scheme="s">1</xbrli:identifier><xbrli:segment>{seg}</xbrli:segment>'
            f'</xbrli:entity><xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period>'
            f'</xbrli:context>')


def _ix_row(cref, cells, fv):
    tds = "".join(f"<td>{c}</td>" for c in cells)
    tds += (f'<td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" '
            f'contextRef="{cref}">{fv}</ix:nonFraction></td>')
    return f"<tr>{tds}</tr>"


def _write_ixbrl(tmp_path, contexts, rows):
    body = "".join(contexts) + "<table>" + "".join(rows) + "</table>"
    xml = f"<xbrli:xbrl {_IX_NS}>{body}</xbrli:xbrl>"
    p = tmp_path / "000ACC.html"
    p.write_text(xml, encoding="utf-8")
    return p


def test_ixbrl_anchor_extracts_maturity_per_tranche(tmp_path):
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    ctxs = [_ix_context("c1", "Atlas CC Acquisition Corp. 1 | Non-Affiliated Issuer"),
            _ix_context("c2", "Atlas CC Acquisition Corp. 2 | Non-Affiliated Issuer")]
    rows = [_ix_row("c1", ["Atlas CC", "SOFR +", "4.25 %", "7/25/2025", "5/25/2029"], "41085"),
            _ix_row("c2", ["Atlas CC", "P +", "3.00 %", "7/25/2025", "8/15/2031"], "5963")]
    p = _write_ixbrl(tmp_path, ctxs, rows)
    out = propose_field_bridges_from_ixbrl(
        cik="0001803498", accession_number="0001803498-26-000014",
        report_date="2025-12-31", html_path=p)
    by_id = {b["raw_id_lower"]: b for b in out["bridges"]}
    assert len(by_id) == 2  # exact per-tranche, no ambiguity
    a1 = by_id["atlas cc acquisition corp. 1 | non-affiliated issuer"]
    assert a1["maturity_date"] == "2029-05-25" and a1["reference_rate_type"] == "SOFR"
    a2 = by_id["atlas cc acquisition corp. 2 | non-affiliated issuer"]
    assert a2["maturity_date"] == "2031-08-15" and a2["reference_rate_type"] == "PRIME"


def test_ixbrl_anchor_skips_subtotal_context(tmp_path):
    # a context with no InvestmentIdentifierAxis (a subtotal) must be ignored
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    ctxs = [_ix_context("sub", None)]  # no identifier
    rows = [_ix_row("sub", ["First Lien Debt", "", "", "", "1/1/2030"], "999999")]
    p = _write_ixbrl(tmp_path, ctxs, rows)
    out = propose_field_bridges_from_ixbrl(
        cik="0001803498", accession_number="A", report_date="2025-12-31", html_path=p)
    assert out["bridges"] == []


# --- column-aware status enum ---
def test_detect_header_map():
    from pipeline.bdc_xbrl_html_bridge import _detect_header_map
    hdr = _detect_header_map(["Company", "Reference Rate and Spread", "Maturity", "Fair Value"])
    assert hdr and any("maturity" in v.lower() for v in hdr.values())
    # a data row (has numbers) is not a header
    assert _detect_header_map(["Acme Corp", "SOFR +", "4.25%", "5/25/2029", "41,085"]) is None


def test_field_status_value_when_header_matches():
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid = ["Acme", "SOFR + 4.25%", "7/25/2025", "5/25/2029", "41,085"]
    header = {0: "Company", 1: "Reference Rate and Spread", 2: "Acquisition Date", 3: "Maturity", 4: "Fair Value"}
    r = field_status("maturity_date", grid, header)
    assert r["status"] == "value" and r["value"] == "2029-05-25" and "Maturity" in r["source_column"]


def test_field_status_blank_when_column_empty():
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid = ["Acme", "SOFR +", "7/25/2025", "", "41,085"]
    header = {3: "Maturity"}
    assert field_status("maturity_date", grid, header)["status"] == "blank"


def test_field_status_validation_needed_when_no_header():
    # no header map -> heuristic value -> validation_needed (column unconfirmed)
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid = ["Acme", "7/25/2025", "5/25/2029", "41,085"]
    r = field_status("maturity_date", grid, {})
    assert r["status"] == "validation_needed" and r["value"] == "2029-05-25"


def test_field_status_validation_needed_when_cell_unparsable():
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid = ["Acme", "Perpetual"]
    header = {1: "Maturity"}
    assert field_status("maturity_date", grid, header)["status"] == "validation_needed"


# --- reference_rate: target the benchmark/Index column, not the Spread column ---
def test_reference_rate_reads_index_column_not_spread():
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid = ["Acme", "SF", "5.50%", "10.80%"]   # Index="SF" (SOFR), Spread=number
    header = {0: "Company", 1: "Index", 2: "Spread", 3: "Interest Rate"}
    r = field_status("reference_rate_type", grid, header)
    assert r["status"] == "value" and r["value"] == "SOFR" and r["source_column"] == "Index"


def test_reference_rate_numeric_spread_is_not_false_value():
    from pipeline.bdc_xbrl_html_bridge import field_status
    # a pure numeric spread cell must NOT yield a false benchmark value
    for label in ("Spread", "Spread Above Index", "SpreadAboveIndex", "Basis Spread"):
        r = field_status("reference_rate_type", ["Acme", "5.50%"], {1: label})
        assert r["status"] != "value"


def test_reference_rate_prefers_index_over_spread_when_both_match():
    from pipeline.bdc_xbrl_html_bridge import field_status
    # combined-style spread column has a number; dedicated Index has the code
    grid = ["Acme", "5.50%", "SF"]
    header = {1: "Spread", 2: "Index"}
    r = field_status("reference_rate_type", grid, header)
    assert r["status"] == "value" and r["value"] == "SOFR" and r["source_column"] == "Index"


def test_reference_rate_from_interest_rate_column():
    from pipeline.bdc_xbrl_html_bridge import field_status
    # benchmark living in an "Interest Rate" column ("Prime plus", spread split out)
    r = field_status("reference_rate_type", ["Acme", "Prime plus", "2.75%"],
                     {1: "Interest Rate"})
    assert r["status"] == "value" and r["value"] == "PRIME"
    # a purely numeric all-in rate must NOT become a false value
    r2 = field_status("reference_rate_type", ["Acme", "10.50%"], {1: "Interest Rate"})
    assert r2["status"] != "value"


def test_reference_rate_combined_column_still_matches():
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid = ["Acme", "SOFR + 5.50%"]
    r = field_status("reference_rate_type", grid, {1: "Reference Rate and Spread"})
    assert r["status"] == "value" and r["value"] == "SOFR"


def test_benchmark_from_code_bare_codes():
    from pipeline.bdc_xbrl_html_bridge import _parse_field_value
    assert _parse_field_value("reference_rate_type", "SF") == "SOFR"
    assert _parse_field_value("reference_rate_type", "L") == "LIBOR"
    assert _parse_field_value("reference_rate_type", "Term SOFR") == "SOFR"
    assert _parse_field_value("reference_rate_type", "5.50%") == ""   # a number is not a benchmark


# --- flat->inline join: not_found for unanchored flat positions ---
def test_join_assigns_not_found_for_unanchored():
    from pipeline.bdc_xbrl_html_bridge import join_flat_positions_to_inline_status
    flat = [
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer"},
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "investment_identifier": "Ghost Co 9 | Non-Affiliated Issuer"},  # not in iXBRL
    ]
    bridges = [{
        "raw_id_lower": "acme corp 1 | non-affiliated issuer",
        "maturity_date": "2029-05-25", "maturity_status": "value",
        "maturity_source_column": "Maturity Date",
        "reference_rate_type": "SOFR", "reference_rate_status": "value",
        "lien_position": "First Lien", "gics_sector": "Software",
    }]
    out = {r["investment_identifier"]: r for r in join_flat_positions_to_inline_status(flat, bridges)}
    a = out["Acme Corp 1 | Non-Affiliated Issuer"]
    assert a["anchored"] and a["maturity_date_status"] == "value" and a["maturity_date"] == "2029-05-25"
    assert a["lien_position_status"] == "value"   # derived: populated
    g = out["Ghost Co 9 | Non-Affiliated Issuer"]
    assert not g["anchored"]
    assert all(g[f"{f}_status"] == "not_found"
               for f in ("maturity_date", "reference_rate_type", "lien_position", "gics_sector"))


def test_join_derives_blank_for_empty_lien_when_anchored():
    from pipeline.bdc_xbrl_html_bridge import join_flat_positions_to_inline_status
    flat = [{"cik": "1", "accession_number": "A", "report_date": "2025-12-31",
             "investment_identifier": "Equity Co 1"}]
    bridges = [{"raw_id_lower": "equity co 1", "maturity_date": "", "maturity_status": "blank",
                "lien_position": "", "gics_sector": "Software"}]
    r = join_flat_positions_to_inline_status(flat, bridges)[0]
    assert r["lien_position_status"] == "blank"      # anchored but empty
    assert r["gics_sector_status"] == "value"


def test_field_status_mmyy_date_in_confirmed_column():
    # Main Street uses abbreviated MM/YY ("04/28") in the Maturity column
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid = ["Acme", "First Lien", "04/28", "1,000"]
    header = {2: "Maturity Date"}
    r = field_status("maturity_date", grid, header)
    assert r["status"] == "value" and r["value"] == "2028-04-30"


def test_maturity_signature_flags_past_dated():
    from pipeline.bdc_xbrl_html_bridge import apply_maturity_signature
    # future-dated maturity stays value
    assert apply_maturity_signature({"value":"2029-05-25","status":"value"}, "2025-12-31")["status"]=="value"
    # past-dated "maturity" (likely a misread acquisition date) -> validation_needed
    assert apply_maturity_signature({"value":"2024-03-01","status":"value"}, "2025-12-31")["status"]=="validation_needed"
    # blank/validation_needed untouched
    assert apply_maturity_signature({"value":"","status":"blank"}, "2025-12-31")["status"]=="blank"


# --- (a) reconciliation gate ---
def test_reconcile_to_subtotals_pass_and_fail():
    from pipeline.bdc_xbrl_html_bridge import reconcile_to_subtotals
    ok = reconcile_to_subtotals([("First Lien", 90e6), ("First Lien", 10e6), ("Second Lien", 5e6)],
                                {"First Lien": 100e6, "Second Lien": 5e6})
    assert ok["reconciled"] and ok["tiers"]["First Lien"]["ok"]
    bad = reconcile_to_subtotals([("First Lien", 50e6)], {"First Lien": 100e6})
    assert not bad["reconciled"] and not bad["tiers"]["First Lien"]["ok"]


# --- (b) value-status overlay ---
def test_ixbrl_overlay_applies_value_only_blank_only(tmp_path):
    import pandas as pd
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    df = pd.DataFrame([
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
         "maturity_date": "", "reference_rate_type": "", "lien_position": "", "reference_rate_source": ""},
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "bdc_investment_identifier": "Beta Co 1 | Non-Affiliated Issuer",
         "maturity_date": "2099-01-01", "reference_rate_type": "", "lien_position": "", "reference_rate_source": ""},
    ])
    status = [
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "raw_id_lower": "acme corp 1 | non-affiliated issuer",
         "maturity_date": "2029-05-25", "maturity_status": "value",
         "lien_position": "First Lien", "lien_status": "value",
         "reference_rate_type": "SOFR", "reference_rate_status": "validation_needed"},  # ref NOT value
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "raw_id_lower": "beta co 1 | non-affiliated issuer",
         "maturity_date": "2030-01-01", "maturity_status": "value"},  # but df already populated
    ]
    out = apply_ixbrl_field_status_overlay(df, status)
    assert out.iloc[0]["maturity_date"] == "2029-05-25"          # value applied to blank
    assert out.iloc[0]["lien_position"] == "First Lien"           # value applied
    assert out.iloc[0]["reference_rate_type"] == ""               # validation_needed NOT applied
    assert out.iloc[1]["maturity_date"] == "2099-01-01"           # not clobbered


def test_ixbrl_overlay_keys_on_full_member_via_dims():
    """Flattened filer: bdc_investment_identifier is STRIPPED of the affiliation
    suffix, but bdc_dimensions_raw preserves the full XBRL member (= the artifact's
    raw_id_lower). The overlay must key on the dims member; keying on the stripped
    identifier strands the captured lien/maturity (the production bug fixed here)."""
    import pandas as pd
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    df = pd.DataFrame([
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "bdc_investment_identifier": "Gannett Fleming, Inc.",   # STRIPPED, no suffix
         "bdc_dimensions_raw": "investmentidentifieraxis=Gannett Fleming, Inc. | Non-Affiliated Issuer",
         "maturity_date": "", "reference_rate_type": "", "lien_position": "", "reference_rate_source": ""},
    ])
    status = [
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "raw_id_lower": "gannett fleming, inc. | non-affiliated issuer",
         "lien_position": "First Lien", "lien_status": "value",
         "maturity_date": "2029-03-09", "maturity_status": "value"},
    ]
    out = apply_ixbrl_field_status_overlay(df, status)
    assert out.iloc[0]["lien_position"] == "First Lien"     # recovered via the dims member
    assert out.iloc[0]["maturity_date"] == "2029-03-09"
    # control: without dims (stripped identifier only) the join misses -> stays blank
    out_old = apply_ixbrl_field_status_overlay(df.drop(columns=["bdc_dimensions_raw"]), status)
    assert out_old.iloc[0]["lien_position"] == ""          # the bug, reproduced


# --- producer core: join (not_found) + reconcile gate (a) ---
def test_build_field_status_rows_reconcile_gate_and_not_found():
    from pipeline.bdc_xbrl_html_bridge import build_field_status_rows
    bridges = [
        {"investment_identifier": "Acme 1", "maturity_date": "2029-05-25",
         "maturity_status": "value", "lien_position": "First Lien"},
    ]
    flat = [
        {"cik": "X", "accession_number": "A", "report_date": "2025-12-31",
         "investment_identifier": "Acme 1", "fair_value": 100e6},
        {"cik": "X", "accession_number": "A", "report_date": "2025-12-31",
         "investment_identifier": "Ghost 9", "fair_value": 5e6},  # no bridge -> not_found
    ]
    rows = build_field_status_rows(bridges, flat, {"First Lien": 100e6})
    by_id = {r["raw_id_lower"]: r for r in rows}
    assert by_id["acme 1"]["lien_status"] == "value"         # reconciles -> stays value
    assert by_id["acme 1"]["maturity_status"] == "value"
    assert by_id["ghost 9"]["lien_status"] == "not_found"     # row absent from inline
    assert by_id["ghost 9"]["maturity_status"] == "not_found"

    rows2 = build_field_status_rows(bridges, flat, {"First Lien": 999e6})
    by_id2 = {r["raw_id_lower"]: r for r in rows2}
    assert by_id2["acme 1"]["lien_status"] == "validation_needed"  # rollup fails -> downgrade
    assert by_id2["acme 1"]["maturity_status"] == "value"          # maturity unaffected by lien gate


# --- benign classification: separate unfunded/zero-FV from genuine misses ---
def test_build_field_status_rows_benign_classification():
    from pipeline.bdc_xbrl_html_bridge import build_field_status_rows
    bridges = [{"investment_identifier": "Funded 1", "maturity_date": "2029-01-01",
                "maturity_status": "value", "lien_position": "First Lien"}]
    common = {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "period": "2025-12-31"}
    flat = [
        {**common, "investment_identifier": "Funded 1", "fair_value": 100e6},      # anchored
        {**common, "investment_identifier": "Revolver 1", "fair_value": -50000},   # tagged, no FV
        {**common, "investment_identifier": "ExitedZero 1", "fair_value": 0},      # zero FV
        {**common, "investment_identifier": "Missing 1", "fair_value": 7e6},       # material miss
    ]
    rows = build_field_status_rows(bridges, flat, {}, commitment_ids=["revolver 1"])
    by = {r["raw_id_lower"]: r for r in rows}
    assert by["funded 1"]["anchor_class"] == "anchored" and by["funded 1"]["maturity_status"] == "value"
    assert by["revolver 1"]["anchor_class"] == "unfunded_commitment"
    assert by["revolver 1"]["maturity_status"] == "unfunded_commitment"   # not reviewed
    assert by["exitedzero 1"]["anchor_class"] == "zero_fv"
    assert by["exitedzero 1"]["lien_status"] == "zero_fv"
    assert by["missing 1"]["anchor_class"] == "missing"
    assert by["missing 1"]["maturity_status"] == "not_found"              # genuine review item


# --- period scoping: comparative-period unanchored is benign, not a review item ---
def test_join_comparative_period_unanchored_is_benign():
    from pipeline.bdc_xbrl_html_bridge import join_flat_positions_to_inline_status
    flat = [
        {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "period": "2025-12-31",
         "investment_identifier": "Ghost Cur"},     # current-period miss -> not_found (review)
        {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "period": "2024-12-31",
         "investment_identifier": "Ghost Prior"},   # comparative-period -> comparative (benign)
    ]
    out = {r["investment_identifier"]: r for r in join_flat_positions_to_inline_status(flat, [])}
    assert out["Ghost Cur"]["period_role"] == "current"
    assert out["Ghost Cur"]["maturity_date_status"] == "not_found"
    assert out["Ghost Prior"]["period_role"] == "comparative"
    assert out["Ghost Prior"]["maturity_date_status"] == "comparative"


def test_reconcile_uses_current_period_fv_only():
    # A still-held position also appears as a comparative row with the same id;
    # the comparative FV must NOT be summed into the lien reconciliation.
    from pipeline.bdc_xbrl_html_bridge import build_field_status_rows
    bridges = [{"investment_identifier": "Held 1", "lien_position": "First Lien"}]
    flat = [
        {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "period": "2025-12-31",
         "investment_identifier": "Held 1", "fair_value": 100e6},
        {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "period": "2024-12-31",
         "investment_identifier": "Held 1", "fair_value": 90e6},   # comparative, same position
    ]
    rows = build_field_status_rows(bridges, flat, {"First Lien": 100e6})
    cur = [r for r in rows if r["period_role"] == "current"][0]
    assert cur["lien_status"] == "value"   # reconciles to 100M; comparative 90M excluded


# --- S15: load_html_section_bridge_rows dedup is order-invariant ---
def _bridge_record(family, sha, table_index, row_index):
    """A bridge record colliding on the dedup key (cik/accession/report_date/
    raw_id_lower) with the others; only family + source-location keys differ."""
    return {
        "accession_number": "0000000000-26-000001",
        "report_date": "2026-03-31",
        "raw_id_lower": "acme corp",
        "issuer_name": "Acme Corp",
        "instrument_description": "First Lien Debt",
        "family": family,
        "html_sha256": sha,
        "table_index": table_index,
        "section_row_index": 4,
        "row_index": row_index,
        "cell_indices": [0, 4, 5],
        "section_label": "First Lien Debt",
    }


def _write_bridge_file(path, records):
    path.write_text(
        json.dumps({
            "schema_version": BRIDGE_SCHEMA_VERSION, "admission_status": "promoted",
            "cik": "0000000123",
            "version": 1,
            "source": "bdc_xbrl",
            "bridges": records,
        }),
        encoding="utf-8",
    )


def test_load_bridge_rows_dedup_survivor_is_order_invariant(tmp_path):
    """S15: two bridge records collide on (cik, accession, report_date,
    raw_id_lower) with different payloads + source-location keys. keep='last'
    must select the same survivor regardless of the physical record order,
    because we stable-sort on the dedup subset plus html_sha256/table_index/
    row_index first."""
    from pipeline.bdc_xbrl_html_bridge import load_html_section_bridge_rows

    # rec_hi has the larger source-location tuple (sha 'bbb...' > 'aaa...') so it
    # is the deterministic keep='last' survivor. Its family is the pinned value.
    rec_lo = _bridge_record("debt", "a" * 64, 1, 3)
    rec_hi = _bridge_record("equity", "b" * 64, 2, 9)

    def _run(records):
        bridge_dir = tmp_path / "bridges"
        if bridge_dir.exists():
            for p in bridge_dir.glob("*.json"):
                p.unlink()
        else:
            bridge_dir.mkdir()
        _write_bridge_file(bridge_dir / "0000000123.json", records)
        rows = load_html_section_bridge_rows(bridge_dir)
        assert len(rows) == 1                      # collapsed to one survivor
        return rows.iloc[0]["family"]

    fam_forward = _run([rec_lo, rec_hi])
    fam_reversed = _run([rec_hi, rec_lo])
    assert fam_forward == "equity"                 # rec_hi wins (largest tuple)
    assert fam_reversed == "equity"                # same survivor, order flipped


# --- S16: apply_ixbrl_field_status_overlay dedup is order-invariant ---
def test_ixbrl_overlay_status_dedup_is_order_invariant():
    """S16: two status rows collide on the overlay key with different payloads.
    The applied value must be the deterministic keep='last' survivor regardless
    of the caller's row order (stable-sort on the payload before dedup)."""
    import pandas as pd
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay

    df = pd.DataFrame([
        {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
         "bdc_investment_identifier": "Acme Corp 1 | Non-Affiliated Issuer",
         "maturity_date": "", "reference_rate_type": "", "lien_position": "",
         "reference_rate_source": ""},
    ])
    # Same overlay key, disagreeing maturity_date. keep='last' after a stable
    # payload sort selects the lexicographically larger date deterministically.
    row_lo = {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
              "raw_id_lower": "acme corp 1 | non-affiliated issuer",
              "maturity_date": "2029-01-01", "maturity_status": "value"}
    row_hi = {"cik": "0001803498", "accession_number": "A", "report_date": "2025-12-31",
              "raw_id_lower": "acme corp 1 | non-affiliated issuer",
              "maturity_date": "2030-12-31", "maturity_status": "value"}

    out_forward = apply_ixbrl_field_status_overlay(df.copy(), [row_lo, row_hi])
    out_reversed = apply_ixbrl_field_status_overlay(df.copy(), [row_hi, row_lo])
    assert out_forward.iloc[0]["maturity_date"] == "2030-12-31"
    assert out_reversed.iloc[0]["maturity_date"] == "2030-12-31"


def test_overlay_key_ignores_the_pipeline_derived_detached_schedule_label(monkeypatch):
    """The detached-schedule label is appended to bdc_dimensions_raw by staging; it is
    not part of the filed member. Found by the 2026-10-05 trial build: 85 HPS
    joint-venture rows lost their captured maturity and lien when it leaked into the key."""
    import pandas as pd
    from pipeline import source_encodings
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    monkeypatch.setattr(source_encodings, "load_encodings", lambda *a, **k: {
        "0001838126": {"detached_schedule_labels": ["joint venture schedule"]}})
    base = {"cik": "0001838126", "accession_number": "A", "report_date": "2026-03-31",
            "maturity_date": "", "reference_rate_type": "", "lien_position": "",
            "reference_rate_source": ""}
    df = pd.DataFrame([
        dict(base, bdc_investment_identifier="Bright Light Buyer, Inc. 1",
             bdc_dimensions_raw="investmentidentifieraxis=Bright Light Buyer, Inc. 1 | joint venture schedule"),
        # a filed member that merely ends with similar words keeps its full key
        dict(base, bdc_investment_identifier="Acme JV",
             bdc_dimensions_raw="investmentidentifieraxis=Acme | joint venture schedule holdings"),
    ])
    status = [
        dict(cik="0001838126", accession_number="A", report_date="2026-03-31",
             raw_id_lower="bright light buyer, inc. 1", lien_position="First Lien",
             lien_status="value", maturity_date="2031-06-21", maturity_status="value"),
        dict(cik="0001838126", accession_number="A", report_date="2026-03-31",
             raw_id_lower="acme", lien_position="Second Lien", lien_status="value",
             maturity_date="2030-01-01", maturity_status="value"),
    ]
    out = apply_ixbrl_field_status_overlay(df, status)
    assert out.iloc[0]["lien_position"] == "First Lien"
    assert out.iloc[0]["maturity_date"] == "2031-06-21"
    assert out.iloc[1]["lien_position"] == ""      # not stripped: different member
    assert out.iloc[0]["bdc_dimensions_raw"].endswith("joint venture schedule")   # label kept


# --- a filer's own reference-rate column (wrapper: reference_rate_columns / reference_rate_codes) ---
OWL_READING = {"columns": frozenset({"interest", "ref. rate"}), "codes": {"SR": "SOFR", "SA": "SONIA"}}


def test_filer_named_column_reads_its_reference_rate_code():
    from pipeline.bdc_xbrl_html_bridge import field_status
    # Blue Owl to 2025-09-30: 'Interest' spans the code cell and the rate cell
    old = field_status("reference_rate_type", ["Hg Genesis", "Unsecured facility", "SR +", "7.00% PIK"],
                       {0: "Company", 1: "Investment", 2: "Interest"}, OWL_READING)
    assert old == {"value": "SOFR", "status": "value", "source_column": "Interest"}
    # from 2025-12-31: 'Ref. Rate | Cash | PIK'
    new = field_status("reference_rate_type", ["Inovalon", "Second lien", "S+", "", "8.50%"],
                       {0: "Company", 1: "Investment", 2: "Ref. Rate", 3: "Cash", 4: "PIK"}, OWL_READING)
    assert new["status"] == "value" and new["value"] == "SOFR" and new["source_column"] == "Ref. Rate"


def test_filer_named_column_does_not_invent_a_reference_rate():
    from pipeline.bdc_xbrl_html_bridge import field_status
    header = {0: "Company", 1: "Investment", 2: "Ref. Rate", 3: "Cash", 4: "PIK"}
    # a fixed coupon: 'N/A', or an empty cell, is the filer saying there is no reference rate
    assert field_status("reference_rate_type", ["Associations Finance", "Unsecured notes", "N/A", "", "14.25%"],
                        header, OWL_READING) == {"value": "", "status": "not_applicable", "source_column": "Ref. Rate"}
    assert field_status("reference_rate_type", ["Associations Finance", "Unsecured notes", "", "14.25% PIK"],
                        {2: "Interest"}, OWL_READING) == {"value": "", "status": "not_applicable", "source_column": "Interest"}
    # a code the wrapper does not define is neither a value nor 'not applicable': the row stays unread
    assert field_status("reference_rate_type", ["Acme", "First lien", "C +", "5.00%"],
                        {2: "Interest"}, OWL_READING) == {"value": "", "status": "validation_needed", "source_column": "Interest"}
    # an empty cell on a row that names a benchmark elsewhere (a shifted cell) is not 'not applicable'
    for grid in (["Acme", "First lien", "", "SR +", "5.00%"], ["Acme", "First lien", "", "SOFR + 5.00%"]):
        assert field_status("reference_rate_type", grid, {2: "Interest"}, OWL_READING)["status"] == "blank"
    # a fund that names no column never gets the status
    assert field_status("reference_rate_type", ["Acme", "Notes", "N/A", "14.25%"], {2: "Reference Rate"})["status"] == "validation_needed"


def test_a_code_whose_meaning_changed_is_read_by_report_date(tmp_path):
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    encodings = {"0001812554": {"reference_rate_columns": ["Interest"],
                                "reference_rate_codes": ["C=CDOR to 2024-03-31", "C=CORRA from 2024-06-30"]}}
    read = {}
    for day in ("2024-03-31", "2024-06-30"):
        folder = tmp_path / day
        folder.mkdir()
        p = _write_ixbrl(folder, [_ix_context("c1", "Maple Co | First lien | Non-Affiliated Issuer", instant=day)],
                         ["<tr><td>Company</td><td>Investment</td><td>Interest</td><td></td><td>Maturity Date</td><td>Fair Value</td></tr>",
                          _ix_row("c1", ["Maple Co", "First lien", "C +", "5.00%", "3/2029"], "100")])
        read[day] = propose_field_bridges_from_ixbrl(cik="0001812554", accession_number="A", report_date=day,
                                                     html_path=p, encodings=encodings)["bridges"][0]["reference_rate_type"]
    assert read == {"2024-03-31": "CDOR", "2024-06-30": "CORRA"}


def _status_row(status, value=""):
    return {"cik": "0001812554", "accession_number": "A", "report_date": "2025-12-31",
            "raw_id_lower": "acme | notes | non-affiliated issuer", "reference_rate_type": value, "reference_rate_status": status}


def _staged(**changes):
    row = {"cik": "0001812554", "accession_number": "A", "report_date": "2025-12-31",
           "bdc_investment_identifier": "Acme | Notes", "bdc_dimensions_raw": "investmentidentifieraxis=Acme | Notes | Non-Affiliated Issuer",
           "maturity_date": "", "lien_position": "", "reference_rate_type": "", "reference_rate_source": "",
           "coupon_type": "", "interest_rate": "", "pik_rate": "14.25", "asset_category": "LOAN",
           "basis_spread": "", "src_transforms": ""}
    return pd.DataFrame([dict(row, **changes)])


def test_printed_not_applicable_marks_a_rated_row_as_fixed():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    out = apply_ixbrl_field_status_overlay(_staged(), [_status_row("not_applicable")])
    assert out.iloc[0]["coupon_type"] == "Fixed" and out.iloc[0]["reference_rate_type"] == ""


def test_printed_not_applicable_changes_nothing_else():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    # no rate on the row, a preferred stake with a PIK dividend, a coupon type already set, or a reference rate already known
    for changes in (dict(pik_rate=""), dict(asset_category="EQUITY_PREFERRED"), dict(coupon_type="Floating"), dict(reference_rate_type="SOFR")):
        out = apply_ixbrl_field_status_overlay(_staged(**changes), [_status_row("not_applicable")])
        assert out.iloc[0]["coupon_type"] == changes.get("coupon_type", "")
    # an unread cell is not evidence of a fixed coupon
    for status in ("validation_needed", "blank", "not_found"):
        assert apply_ixbrl_field_status_overlay(_staged(), [_status_row(status)]).iloc[0]["coupon_type"] == ""
    # a confirmed reference rate fills the rate and leaves the coupon type alone
    out = apply_ixbrl_field_status_overlay(_staged(), [_status_row("value", "SOFR")])
    assert out.iloc[0]["reference_rate_type"] == "SOFR" and out.iloc[0]["coupon_type"] == ""


def test_a_fund_without_the_setting_reads_as_before():
    from pipeline.bdc_xbrl_html_bridge import field_status
    grid, header = ["Hg Genesis", "Unsecured facility", "SR +", "7.00% PIK"], {0: "Company", 1: "Investment", 2: "Interest"}
    assert field_status("reference_rate_type", grid, header)["status"] != "value"
    assert field_status("reference_rate_type", grid, header, None)["status"] != "value"
    # the setting names columns for the reference rate only
    assert field_status("maturity_date", ["Acme", "5/25/2029"], {1: "Maturity"}, OWL_READING)["value"] == "2029-05-25"


def test_ixbrl_rows_take_the_filer_reading_from_the_wrapper(tmp_path):
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    ctxs = [_ix_context("c1", "Hg Genesis 9 SumoCo Limited | Unsecured facility | Non-Affiliated Issuer"),
            _ix_context("c2", "Associations Finance, Inc. | Unsecured notes | Non-Affiliated Issuer")]
    rows = ["<tr><td>Company</td><td>Investment</td><td>Interest</td><td></td><td>Maturity Date</td><td>Fair Value</td></tr>",
            _ix_row("c1", ["Hg Genesis 9 SumoCo Limited", "Unsecured facility", "SR +", "7.00% PIK", "3/2029"], "148366"),
            _ix_row("c2", ["Associations Finance, Inc.", "Unsecured notes", "", "14.25% PIK", "5/2030"], "164538")]
    p = _write_ixbrl(tmp_path, ctxs, rows)
    encodings = {"0001812554": {"reference_rate_columns": ["Interest", "Ref. Rate"], "reference_rate_codes": ["SR=SOFR"]}}
    kwargs = dict(accession_number="A", report_date="2025-12-31", html_path=p)
    by_id = {b["issuer_name"][:10]: b for b in propose_field_bridges_from_ixbrl(cik="0001812554", encodings=encodings, **kwargs)["bridges"]}
    assert (by_id["Hg Genesis"]["reference_rate_type"], by_id["Hg Genesis"]["reference_rate_status"]) == ("SOFR", "value")
    assert (by_id["Associatio"]["reference_rate_type"], by_id["Associatio"]["reference_rate_status"]) == ("", "not_applicable")
    # another fund reading the same page gets no confirmed value
    other = propose_field_bridges_from_ixbrl(cik="0001838126", encodings=encodings, **kwargs)["bridges"]
    assert all(b["reference_rate_status"] != "value" for b in other)


# --- the margin printed on the row, and a spread tag that holds only the cash part ---
def test_printed_margin_reads_the_three_forms_blue_owl_prints():
    from pipeline.bdc_xbrl_html_bridge import printed_margin
    old = {0: "Company", 1: "Investment", 2: "Interest", 5: "Maturity Date"}
    new = {0: "Company", 1: "Investment", 2: "Ref. Rate", 3: "Cash", 4: "PIK", 5: "Maturity Date"}
    # 10-Q 2024-09-30, Inovalon first lien: a total of 6.25 of which 2.75 is PIK
    assert printed_margin(["Inovalon", "First lien", "SR +", "6.25% (2.75% PIK)", "", "11/2028"], old, OWL_READING) == "6.25"
    assert printed_margin(["Inovalon", "First lien", "SR +", "6.25%", "(2.75% PIK)", "11/2028"], old, OWL_READING) == "6.25"
    # 10-K 2025-12-31, the same loan: cash 2.75 and PIK 2.75 in separate cells
    assert float(printed_margin(["Inovalon", "First lien", "S+", "2.75%", "2.75%", "11/2028"], new, OWL_READING)) == 5.5
    assert float(printed_margin(["Inovalon", "First lien", "S+", "2.75%", "2.75%", "11/2028"], old, OWL_READING)) == 5.5
    # one figure: a cash margin, or a PIK-only margin
    assert printed_margin(["DIRECTV", "First lien", "S+", "5.25%", "", "8/2029"], new, OWL_READING) == "5.25"
    assert printed_margin(["Inovalon", "Second lien", "S+", "", "8.50%", "11/2033"], new, OWL_READING) == "8.50"


def test_printed_margin_is_not_read_from_anything_else():
    from pipeline.bdc_xbrl_html_bridge import printed_margin
    old = {0: "Company", 1: "Investment", 2: "Interest", 5: "Maturity Date"}
    # three figures, or a second figure in one cell that is not marked PIK: not understood, so not read
    assert printed_margin(["Acme", "First lien", "SR +", "6.25%", "2.75%", "1.00%"], {2: "Interest"}, OWL_READING) == ""
    assert printed_margin(["Acme", "First lien", "SR +", "6.25% (1.00% floor)", "", "1/2029"], old, OWL_READING) == ""
    # figures after the next header column (percent of net assets) are outside the span
    assert printed_margin(["Acme", "First lien", "SR +", "5.75%", "", "1/2029", "0.6%"], old, OWL_READING) == "5.75"
    # a fund that names no column, and a table without the named column
    assert printed_margin(["Acme", "First lien", "SR +", "5.75%"], old, None) == ""
    assert printed_margin(["Acme", "Revolver", "1/2029", "5.75%"], {0: "Portfolio Company", 1: "Commitment Type"}, OWL_READING) == ""


def test_a_printed_reference_rate_replaces_one_inferred_from_the_date():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    # Blue Owl 2023-06-30, Anaplan: printed 'SR +', published LIBOR because the report date is before July 2023
    staged = _staged(reference_rate_type="LIBOR", reference_rate_source="inferred_pre_libor")
    out = apply_ixbrl_field_status_overlay(staged, [_status_row("value", "SOFR")])
    assert (out.iloc[0]["reference_rate_type"], out.iloc[0]["reference_rate_source"]) == ("SOFR", "ixbrl_field_status")


def test_a_printed_reference_rate_replaces_nothing_else():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    cases = [
        (dict(reference_rate_source="xbrl_field"), _status_row("value", "SOFR")),            # a tagged rate stands
        (dict(reference_rate_source="inferred_pre_libor"), _status_row("validation_needed", "SOFR")),
        (dict(reference_rate_source="inferred_pre_libor"), _status_row("not_applicable")),
        # a fund that names no reference-rate column
        (dict(reference_rate_source="inferred_pre_libor", cik="0001655888"), dict(_status_row("value", "SOFR"), cik="0001655888")),
        (dict(reference_rate_source="identifier_text", cik="0001655888"), dict(_status_row("value", "SOFR"), cik="0001655888")),
    ]
    for changes, status in cases:
        if status["reference_rate_status"] == "not_applicable":
            continue    # withdrawn, not replaced: tested below
        out = apply_ixbrl_field_status_overlay(_staged(reference_rate_type="LIBOR", **changes), [status])
        assert (out.iloc[0]["reference_rate_type"], out.iloc[0]["reference_rate_source"]) == ("LIBOR", changes["reference_rate_source"])
    # the same benchmark: the inferred label is kept, nothing was replaced
    same = apply_ixbrl_field_status_overlay(_staged(reference_rate_type="SOFR", reference_rate_source="inferred_post_libor"),
                                            [_status_row("value", "SOFR")])
    assert same.iloc[0]["reference_rate_source"] == "inferred_post_libor"


def _margin_status(margin):
    return dict(_status_row("value", "SOFR"), printed_margin=margin)


def test_a_cash_spread_printed_apart_from_its_pik_becomes_the_total_margin():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    # Inovalon first lien, 2025-12-31: spread tag 2.75, PIK tag 2.75, printed 'S+ | 2.75% | 2.75%'
    staged = _staged(basis_spread=2.75, pik_rate=2.75, reference_rate_type="SOFR", src_transforms="basis_spread:rate_x100")
    out = apply_ixbrl_field_status_overlay(staged, [_margin_status("5.5")])
    assert out.iloc[0]["basis_spread"] == 5.5 and float(out.iloc[0]["pik_rate"]) == 2.75
    assert out.iloc[0]["src_transforms"] == "basis_spread:rate_x100;basis_spread:cash_plus_pik_margin"


def test_the_spread_is_left_alone_unless_the_page_prints_the_sum():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    cases = [
        # 2024-09-30: 'SR + 6.25% (2.75% PIK)', spread tag 6.25 is already the total
        (dict(basis_spread=6.25, pik_rate=2.75), "6.25"),
        # the page agrees with neither reading: a finding for the rule, not a change
        (dict(basis_spread=6.25, pik_rate=2.75), "7.0"),
        (dict(basis_spread=2.75, pik_rate=2.75), ""),                                   # margin not read
        (dict(basis_spread=2.75, pik_rate=""), "5.5"),                                  # no PIK tag
        (dict(basis_spread=2.75, pik_rate=2.75, asset_category="EQUITY_PREFERRED"), "5.5"),
        (dict(basis_spread=2.75, pik_rate=2.75, cik="0001838126"), "5.5"),              # a fund without the setting
    ]
    for changes, margin in cases:
        staged = _staged(src_transforms="", **changes)
        status = dict(_margin_status(margin), cik=changes.get("cik", "0001812554"))
        out = apply_ixbrl_field_status_overlay(staged, [status])
        assert float(out.iloc[0]["basis_spread"]) == changes["basis_spread"] and out.iloc[0]["src_transforms"] == ""


def test_ixbrl_rows_carry_the_printed_margin_only_over_a_confirmed_reference_rate(tmp_path):
    from pipeline.bdc_xbrl_html_bridge import build_field_status_rows, propose_field_bridges_from_ixbrl
    ctxs = [_ix_context("c1", "Inovalon | First lien | Non-Affiliated Issuer"),
            _ix_context("c2", "Associations Finance | Notes | Non-Affiliated Issuer")]
    rows = ["<tr><td>Company</td><td>Investment</td><td>Ref. Rate</td><td>Cash</td><td>PIK</td><td>Maturity Date</td><td>Fair Value</td></tr>",
            _ix_row("c1", ["Inovalon", "First lien", "S+", "2.75%", "2.75%", "11/2028"], "303221"),
            _ix_row("c2", ["Associations Finance", "Notes", "N/A", "", "14.25%", "5/2030"], "189630")]
    encodings = {"0001812554": {"reference_rate_columns": ["Ref. Rate"]}}
    bridges = propose_field_bridges_from_ixbrl(cik="0001812554", accession_number="A", report_date="2025-12-31",
                                               html_path=_write_ixbrl(tmp_path, ctxs, rows), encodings=encodings)["bridges"]
    assert [b["printed_margin"] for b in bridges] == ["5.5", ""]
    flat = [{"cik": "0001812554", "accession_number": "A", "report_date": "2025-12-31", "period": "2025-12-31",
             "investment_identifier": b["issuer_name"], "fair_value": 1.0} for b in bridges]
    assert [r["printed_margin"] for r in build_field_status_rows(bridges, flat, {})] == ["5.5", ""]


# --- the same reading for the other printed layouts (BCRED and HPS, Ares, Apollo) ---
def test_a_code_printed_with_its_reset_period_or_ahead_of_the_margin_is_read():
    from pipeline.bdc_xbrl_html_bridge import field_status
    ares = {"columns": frozenset({"reference"}), "codes": {"CDOR": "CDOR"}}
    header = {0: "Company", 3: "Coupon", 4: "Reference", 5: "Spread", 6: "Acquisition Date"}
    # Ares 10-Q 2024-06-30: 'SOFR (Q)', and a benchmark the shared table lacks
    assert field_status("reference_rate_type", ["Actfy", "x", "First lien", "10.58%", "SOFR (Q)", "5.25%", "05/2024"], header, ares)["value"] == "SOFR"
    assert field_status("reference_rate_type", ["Acme", "x", "First lien", "9.10%", "CDOR (Q)", "5.00%", "05/2024"], header, ares)["value"] == "CDOR"
    # an undefined name stays unread, and the reset period alone is not a code
    assert field_status("reference_rate_type", ["Acme", "x", "First lien", "9.10%", "Base Rate (Q)", "4.50%", "05/2024"], header, ares)["status"] == "validation_needed"
    apollo = {"columns": frozenset({"interest rate"}), "codes": {"C": "CORRA"}}
    cell = {0: "Industry/Company", 1: "Investment Type", 2: "Interest Rate", 3: "Maturity Date"}
    assert field_status("reference_rate_type", ["Acme", "First Lien", "C+525, 0.75% Floor", "1/1/2030"], cell, apollo)["value"] == "CORRA"
    # a fixed coupon in that column is not a code
    assert field_status("reference_rate_type", ["Acme", "First Lien", "8.50%", "1/1/2030"], cell, apollo)["status"] == "validation_needed"
    # without the filer's codes neither form is read from the shared table
    from pipeline.bdc_xbrl_html_bridge import _benchmark_from_code
    assert _benchmark_from_code("CDOR (Q)") == "" and _benchmark_from_code("C+525, 0.75% Floor") == ""
    assert _benchmark_from_code("S (Q)", {"X": "SOFR"}) == ""


def test_printed_margin_reads_the_forms_the_other_four_funds_print():
    from pipeline.bdc_xbrl_html_bridge import printed_margin
    shared = {"columns": frozenset({"reference rate and spread"}), "codes": {"SF": "SOFR"}}
    header = {0: "Company", 1: "Reference Rate and Spread", 4: "Interest Rate", 5: "Maturity Date"}
    # HPS 10-Q 2023-03-31, Captive Resources: 'SF + | 5.75% (incl 3.13% PIK) | 10.56%'
    assert printed_margin(["Captive", "SF +", "", "5.75% (incl 3.13% PIK)", "10.56%", "7/2/2029"], header, shared) == "5.75"
    # BCRED: the PIK note sits in the rate column, outside the span
    assert printed_margin(["Acme", "SOFR +", "", "6.50%", "11.83% (incl. 2.00% PIK)", "5/3/2027"], header, shared) == "6.50"
    assert printed_margin(["Acme", "SF +", "", "7.00% PIK", "", "5/3/2027"], header, shared) == "7.00"
    # Ares: the margin has its own 'Spread' column after the reference
    ares = {"columns": frozenset({"reference"}), "codes": {}}
    split = {0: "Company", 3: "Coupon", 4: "Reference", 5: "Spread", 6: "Acquisition Date", 7: "Maturity Date"}
    assert printed_margin(["2U", "x", "First lien", "8.87%", "LIBOR (M)", "5.75%", "6/2021", "12/2024"], split, ares) == "5.75"
    # Apollo: basis points after the code, in the named cell
    apollo = {"columns": frozenset({"interest rate"}), "codes": {}}
    cell = {0: "Industry/Company", 1: "Investment Type", 2: "Interest Rate", 3: "Maturity Date"}
    assert float(printed_margin(["MRO", "First Lien", "L+625, 0.50% Floor", "12/18/2028"], cell, apollo)) == 6.25
    assert float(printed_margin(["Bellis", "First Lien", "SONIA+603, 0.00% Floor", "10/22/2029"], cell, apollo)) == 6.03
    assert float(printed_margin(["Acme", "First Lien", "S+325 Cash plus 3.00% PIK, 0.75% Floor", "1/1/2030"], cell, apollo)) == 6.25


def test_printed_margin_still_refuses_what_it_does_not_understand():
    from pipeline.bdc_xbrl_html_bridge import printed_margin
    apollo = {"columns": frozenset({"interest rate"}), "codes": {}}
    cell = {0: "Industry/Company", 1: "Investment Type", 2: "Interest Rate", 3: "Maturity Date"}
    # a fixed coupon, a percent margin in the cell, and a floor with no margin are not basis points after a code
    for text in ("8.50%", "S+6.25%", "0.50% Floor", "N/A", "S+625 or P+525"):
        assert printed_margin(["Acme", "First Lien", text, "1/1/2030"], cell, apollo) == ""
    # the maturity column is outside the span even though the named cell holds no margin
    assert printed_margin(["Acme", "First Lien", "SOFR", "5.00%"], cell, apollo) == ""
    # 'incl' does not turn a floor note into a PIK total
    shared = {"columns": frozenset({"reference rate and spread"}), "codes": {}}
    header = {0: "Company", 1: "Reference Rate and Spread", 4: "Interest Rate"}
    assert printed_margin(["Acme", "SF +", "", "5.75% (incl 1.00% floor)", "10.56%"], header, shared) == ""


def test_a_printed_code_replaces_a_reference_rate_read_from_the_identifier_text():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    # BCRED: 'Prime Security Services Borrower, LLC' was read as PRIME from the borrower's name; the page prints 'SOFR +'.
    # Apollo 10-Q 2023-03-31, Garda World: the member still reads 'L+425', the page prints 'S+ 425'.
    staged = _staged(reference_rate_type="PRIME", reference_rate_source="identifier_text")
    out = apply_ixbrl_field_status_overlay(staged, [_status_row("value", "SOFR")])
    assert (out.iloc[0]["reference_rate_type"], out.iloc[0]["reference_rate_source"]) == ("SOFR", "ixbrl_field_status")
    # agreeing text keeps its label
    same = apply_ixbrl_field_status_overlay(_staged(reference_rate_type="SOFR", reference_rate_source="identifier_text"),
                                            [_status_row("value", "SOFR")])
    assert same.iloc[0]["reference_rate_source"] == "identifier_text"


def test_a_guessed_reference_rate_is_withdrawn_where_the_page_prints_none():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    # BCRED 2022-09-30, Camelot Return Merger: '8.75% | 8.75%' under an empty code cell; the spread tag made it LIBOR, Floating
    staged = _staged(reference_rate_type="LIBOR", reference_rate_source="inferred_pre_libor", coupon_type="Floating",
                     interest_rate="8.75", basis_spread="8.75", pik_rate="")
    out = apply_ixbrl_field_status_overlay(staged, [_status_row("not_applicable")])
    row = out.iloc[0]
    assert (row["reference_rate_type"], row["reference_rate_source"], row["coupon_type"]) == ("", "", "Fixed")
    # the spread tag repeated the coupon: it is not published as a spread, and the rate stands
    assert pd.isna(row["basis_spread"]) and float(row["interest_rate"]) == 8.75
    assert row["src_transforms"] == "basis_spread:fixed_coupon"
    # not withdrawn: a tagged rate, one read from the identifier, an unread cell, or a fund that names no column
    for changes, status in (
            (dict(reference_rate_source="xbrl_field"), _status_row("not_applicable")),
            (dict(reference_rate_source="identifier_text"), _status_row("not_applicable")),
            (dict(reference_rate_source="inferred_pre_libor"), _status_row("validation_needed")),
            (dict(reference_rate_source="inferred_pre_libor"), _status_row("blank")),
            (dict(reference_rate_source="inferred_pre_libor", cik="0001655888"), dict(_status_row("not_applicable"), cik="0001655888"))):
        out = apply_ixbrl_field_status_overlay(_staged(reference_rate_type="LIBOR", coupon_type="Floating", interest_rate="8.75", **changes), [status])
        assert (out.iloc[0]["reference_rate_type"], out.iloc[0]["coupon_type"]) == ("LIBOR", "Floating")
    # a preferred stake loses the guess but is not marked as a fixed loan
    out = apply_ixbrl_field_status_overlay(_staged(reference_rate_type="SOFR", reference_rate_source="inferred_post_libor",
                                                   coupon_type="Floating", asset_category="EQUITY_PREFERRED"), [_status_row("not_applicable")])
    assert (out.iloc[0]["reference_rate_type"], out.iloc[0]["coupon_type"]) == ("", "Floating")


def test_one_member_on_two_position_rows_confirms_only_what_both_rows_print(tmp_path):
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    # BCRED 10-Q 2022-09-30: 'Cloudera, Inc.' first lien L + 3.75% and second lien L + 6.00% under one member
    ctxs = [_ix_context("c1", "Cloudera, Inc."), _ix_context("c2", "Cloudera, Inc."), _ix_context("c3", "Acme, Inc.")]
    rows = ["<tr><td>Investments</td><td>Reference Rate and Spread</td><td></td><td>Interest Rate</td><td>Maturity Date</td><td>Fair Value</td></tr>",
            _ix_row("c1", ["Cloudera, Inc.", "L +", "3.75%", "6.87%", "10/8/2028"], "53700"),
            _ix_row("c2", ["Cloudera, Inc.", "L +", "6.00%", "9.12%", "10/8/2029"], "56700"),
            _ix_row("c3", ["Acme, Inc.", "L +", "5.00%", "8.12%", "1/1/2029"], "100")]
    page = _write_ixbrl(tmp_path, ctxs, rows)
    named = {"0001803498": {"reference_rate_columns": ["Reference Rate and Spread"]}}
    kwargs = dict(cik="0001803498", accession_number="A", report_date="2025-12-31", html_path=page)
    by_id = {b["issuer_name"]: b for b in propose_field_bridges_from_ixbrl(encodings=named, **kwargs)["bridges"]}
    cloudera = by_id["Cloudera, Inc."]
    # both rows print 'L +': the reference rate is confirmed; margin and maturity differ, so neither is
    assert (cloudera["reference_rate_type"], cloudera["reference_rate_status"]) == ("LIBOR", "value")
    assert (cloudera["maturity_status"], cloudera["printed_margin"]) == ("validation_needed", "")
    assert (by_id["Acme, Inc."]["reference_rate_status"], by_id["Acme, Inc."]["printed_margin"]) == ("value", "5.00")
    # a fund that names no column reads as before: the first row stands
    plain = {b["issuer_name"]: b for b in propose_field_bridges_from_ixbrl(encodings={}, **kwargs)["bridges"]}
    assert plain["Cloudera, Inc."]["maturity_status"] == "value"
    # Blue Owl 10-Q 2023-06-30: two rows of one member that print the same line keep every reading
    same = ["<tr><td>Investments</td><td>Reference Rate and Spread</td><td></td><td>Interest Rate</td><td>Maturity Date</td><td>Fair Value</td></tr>",
            _ix_row("c1", ["Cloudera, Inc.", "SOFR +", "5.75%", "10.99%", "10/8/2028"], "53700"),
            _ix_row("c2", ["Cloudera, Inc.", "SOFR +", "5.75%", "10.99%", "10/8/2028"], "1200")]
    folder = tmp_path / "same"
    folder.mkdir()
    both = propose_field_bridges_from_ixbrl(encodings=named, **dict(kwargs, html_path=_write_ixbrl(folder, ctxs[:2], same)))["bridges"][0]
    assert (both["reference_rate_type"], both["reference_rate_status"], both["printed_margin"], both["maturity_status"]) == (
        "SOFR", "value", "5.75", "value")


def test_two_members_that_differ_only_in_case_are_one_key(tmp_path):
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    # BCRED 10-K 2022-12-31: 'athenahealth, Inc.' first lien 'SOFR + 3.50%' and 'Athenahealth, Inc.' notes '6.50% | 6.50%'
    ctxs = [_ix_context("c1", "athenahealth, Inc."), _ix_context("c2", "Athenahealth, Inc.")]
    rows = ["<tr><td>Investments</td><td>Reference Rate and Spread</td><td></td><td>Interest Rate</td><td>Maturity Date</td><td>Fair Value</td></tr>",
            _ix_row("c1", ["athenahealth, Inc.", "SOFR +", "3.50%", "7.82%", "2/15/2029"], "33015"),
            _ix_row("c2", ["Athenahealth, Inc.", "", "6.50%", "6.50%", "2/15/2030"], "2436")]
    named = {"0001803498": {"reference_rate_columns": ["Reference Rate and Spread"]}}
    bridges = propose_field_bridges_from_ixbrl(cik="0001803498", accession_number="A", report_date="2025-12-31",
                                               html_path=_write_ixbrl(tmp_path, ctxs, rows), encodings=named)["bridges"]
    assert len(bridges) == 2 and {b["reference_rate_status"] for b in bridges} == {"validation_needed"}
    assert {b["printed_margin"] for b in bridges} == {""}


def _fixed(**changes):
    row = dict(reference_rate_type="SOFR", reference_rate_source="inferred_post_libor", coupon_type="Floating",
               interest_rate="", pik_rate="", basis_spread="", cik="0001803498", src_transforms="basis_spread:rate_x100")
    return _staged(**dict(row, **changes))


def _no_reference(cik):
    return [dict(_status_row("not_applicable"), cik=cik)]


def test_a_spread_tag_that_is_the_only_rate_figure_on_a_fixed_row_is_published_as_the_rate():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    # no rate and no PIK: the spread tag is the coupon
    out = apply_ixbrl_field_status_overlay(_fixed(basis_spread="11.5"), _no_reference("0001803498")).iloc[0]
    assert float(out["interest_rate"]) == 11.5 and pd.isna(out["basis_spread"]) and out["coupon_type"] == "Fixed"
    assert out["src_transforms"] == "basis_spread:rate_x100;interest_rate:from_spread_tag;basis_spread:fixed_coupon"
    assert out["reference_rate_type"] == ""
    # BCRED 10-Q 2023-03-31, AI Altius Bidco: '9.75% | 9.75% PIK', spread 9.75, PIK 9.75, no rate; BCRED files all-in rates
    out = apply_ixbrl_field_status_overlay(_fixed(basis_spread="9.75", pik_rate="9.75"), _no_reference("0001803498")).iloc[0]
    assert float(out["interest_rate"]) == 9.75 and float(out["pik_rate"]) == 9.75 and pd.isna(out["basis_spread"])
    # HPS 10-Q 2024-06-30, Eagle LNG: '13.50% (incl 6.35% PIK)', spread 13.5, PIK 6.35, no rate; HPS files all-in rates
    out = apply_ixbrl_field_status_overlay(_fixed(basis_spread="13.5", pik_rate="6.35", cik="0001838126"),
                                           _no_reference("0001838126")).iloc[0]
    assert float(out["interest_rate"]) == 13.5 and pd.isna(out["basis_spread"])


def test_the_spread_tag_is_left_where_it_cannot_be_read_as_the_coupon(monkeypatch):
    from pipeline import financial_conventions
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    # Blue Owl, Aptive Environmental '12.00% (6.00% PIK)', spread 12, PIK 6, no rate: the coupon is 12
    out = apply_ixbrl_field_status_overlay(_fixed(basis_spread="12", pik_rate="6", cik="0001812554"), _no_reference("0001812554")).iloc[0]
    assert float(out["interest_rate"]) == 12 and pd.isna(out["basis_spread"]) and float(out["pik_rate"]) == 6
    # were the fund's filed rate read as the cash leg, the PIK would be added to that 12 again: the figures stay as filed
    # (the guessed reference rate is still withdrawn)
    monkeypatch.setattr(financial_conventions, "filed_rate_readings", lambda encodings=None: {"0001812554": "cash_leg"})
    out = apply_ixbrl_field_status_overlay(_fixed(basis_spread="12", pik_rate="6", cik="0001812554"), _no_reference("0001812554")).iloc[0]
    assert float(out["basis_spread"]) == 12 and out["interest_rate"] == "" and out["reference_rate_type"] == ""
    monkeypatch.undo()
    # a spread below the PIK rate cannot be an all-in coupon
    out = apply_ixbrl_field_status_overlay(_fixed(basis_spread="3", pik_rate="6"), _no_reference("0001803498")).iloc[0]
    assert float(out["basis_spread"]) == 3 and out["interest_rate"] == ""
    # BCRED 10-K 2022-12-31, athenahealth: rate 7.82 and spread 3.5 say the loan floats; tags and page disagree, nothing changes
    out = apply_ixbrl_field_status_overlay(_fixed(basis_spread="3.5", interest_rate="7.82"), _no_reference("0001803498")).iloc[0]
    assert (float(out["basis_spread"]), float(out["interest_rate"]), out["reference_rate_type"], out["coupon_type"]) == (3.5, 7.82, "SOFR", "Floating")
    # a preferred stake, a row whose reference rate the page confirms, and a fund that names no column
    for staged, status in ((_fixed(basis_spread="9", interest_rate="9", asset_category="EQUITY_PREFERRED"), _no_reference("0001803498")),
                           (_fixed(basis_spread="9", interest_rate="9"), [dict(_status_row("value", "SOFR"), cik="0001803498")]),
                           (_fixed(basis_spread="9", interest_rate="9", cik="0001655888"), _no_reference("0001655888"))):
        out = apply_ixbrl_field_status_overlay(staged, status).iloc[0]
        assert float(out["basis_spread"]) == 9 and out["src_transforms"] == "basis_spread:rate_x100"


# --- lien sections end at their own total; the page's totals feed the gate (2026-10-08) ---
def _ix_total(label, cref, value, scale="3"):
    return (f'<tr><td>{label}</td><td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" '
            f'contextRef="{cref}" scale="{scale}">{value}</ix:nonFraction></td></tr>')


def _heading(text):
    return f"<tr><td>{text}</td></tr>"


def test_a_lien_section_ends_at_its_total_and_is_not_inherited(tmp_path):
    """BCRED prints 'Structured Finance Obligations' and 'Equity and other' after its debt
    sections; their rows read as the last lien section while those headings were unknown."""
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    ctxs = [_ix_context("c1", "Acme Co"), _ix_context("c2", "Beta Co"), _ix_context("c3", "522 Funding CLO - Class ER"),
            _ix_context("c4", "AGI Group - Common Units"), _ix_context("c5", "Odd Co"), _ix_context("t", None),
            _ix_context("p1", "Acme Co", "2024-12-31"), _ix_context("tp", None, "2024-12-31")]
    rows = [_heading("Second Lien Debt"), _ix_row("c1", ["Acme Co", "SOFR +", "6.00 %"], "100"),
            _heading("Second Lien Debt - controlled/affiliated"), _ix_row("c2", ["Beta Co", "SOFR +", "7.00 %"], "50"),
            _ix_total("Total Second Lien Debt - controlled/affiliated", "t", "50"),
            _ix_total("Total Second Lien Debt", "t", "150"),
            _heading("Structured Finance Obligations"), _ix_row("c3", ["522 Funding CLO - Class ER", "Subordinated Notes"], "30"),
            _heading("Equity and other"), _ix_row("c4", ["AGI Group - Common Units"], "20"),
            _heading("A Heading Nobody Listed"), _ix_row("c5", ["Odd Co"], "10"),
            # the prior year's schedule: its total is not this period's
            _heading("Second Lien Debt"), _ix_row("p1", ["Acme Co", "SOFR +", "6.00 %"], "90"),
            _ix_total("Total Second Lien Debt", "tp", "90")]
    out = propose_field_bridges_from_ixbrl(cik="0001803498", accession_number="A", report_date="2025-12-31",
                                           html_path=_write_ixbrl(tmp_path, ctxs, rows))
    lien = {b["raw_id_lower"]: b["lien_position"] for b in out["bridges"]}
    assert lien["acme co"] == "Second Lien" and lien["beta co"] == "Second Lien"   # a part total does not close it
    assert lien["522 funding clo - class er"] == "" and lien["agi group - common units"] == ""
    assert lien["odd co"] == ""                                                    # closed by the total, not by the heading
    assert out["printed_lien_totals"] == {"Second Lien": 150000.0}                 # scale 3; prior period ignored


def test_filed_lien_subtotals_take_one_grain_per_fund_quarter_and_count_copies_once():
    import pandas as pd
    from pipeline.bdc_xbrl_html_bridge import filed_lien_subtotals
    row = lambda cik, quarter, tier, grain, fv: {"cik": cik, "report_date": quarter, "lien_tier": tier, "grain": grain,
                                                 "fair_value": fv}
    frame = pd.DataFrame([
        # BCRED 2023-12-31, read under both spellings of its CIK: a stray lien_only tier beside the full set
        row("0001803498", "2023-12-31", "Unsecured", "lien_only", 36.3e6),
        row("0001803498", "2023-12-31", "Unsecured", "lien_only", 36.3e6),
        row("0001803498", "2023-12-31", "First Lien", "lien_sector_sum", 45132.5e6),
        row("0001803498", "2023-12-31", "First Lien", "lien_sector_sum", 45132.5e6),
        row("0001803498", "2023-12-31", "Second Lien", "lien_sector_sum", 1355.2e6),
        # another fund has only the other grain; a file-wide choice of lien_only left it with nothing
        row("0001838126", "2023-12-31", "First Lien", "lien_sector_sum", 9000e6),
        row("0001287750", "2023-12-31", "First Lien", "lien_only", 15748e6),
    ])
    out = filed_lien_subtotals(frame)
    assert out[("0001803498", "2023-12-31")] == {"First Lien": 45132.5e6, "Second Lien": 1355.2e6}
    assert out[("0001838126", "2023-12-31")] == {"First Lien": 9000e6}
    assert out[("0001287750", "2023-12-31")] == {"First Lien": 15748e6}


def test_a_schedule_without_lien_sections_still_reads_the_tier_from_the_row(tmp_path):
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    ctxs = [_ix_context("c1", "Acme Co")]
    rows = [_heading("Software"), _ix_row("c1", ["Acme Co", "Second lien senior secured loan", "SOFR +", "6.00 %"], "100")]
    out = propose_field_bridges_from_ixbrl(cik="0001287750", accession_number="A", report_date="2025-12-31",
                                           html_path=_write_ixbrl(tmp_path, ctxs, rows))
    assert out["bridges"][0]["lien_position"] == "Second Lien" and out["printed_lien_totals"] == {}


def test_the_lien_gate_withholds_the_tier_that_fails_and_keeps_the_tier_that_ties():
    from pipeline.bdc_xbrl_html_bridge import build_field_status_rows
    bridges = [{"investment_identifier": "Senior 1", "lien_position": "First Lien"},
               {"investment_identifier": "Junior 1", "lien_position": "Second Lien"}]
    common = {"cik": "1", "accession_number": "A", "report_date": "2025-12-31", "period": "2025-12-31"}
    flat = [{**common, "investment_identifier": "Senior 1", "fair_value": 24_152e6},
            {**common, "investment_identifier": "Junior 1", "fair_value": 1.9e6}]
    rows = {r["raw_id_lower"]: r for r in build_field_status_rows(bridges, flat, {"First Lien": 24_171e6, "Second Lien": 27.1e6})}
    assert rows["senior 1"]["lien_status"] == "value" and rows["senior 1"]["lien_reconciled"] is True
    assert rows["junior 1"]["lien_status"] == "validation_needed" and rows["junior 1"]["lien_reconciled"] is False


def test_section_headings_with_an_affiliation_suffix_or_without_the_word_debt():
    from pipeline.bdc_xbrl_html_bridge import _closed_section, _section_for_row
    assert _section_for_row(["First Lien"]) == ("debt", "First Lien Debt")                     # BCRED 10-Q 2025-03-31
    assert _section_for_row(["Second Lien Debt - non-controlled/non-affiliated (continued)"]) == ("debt", "Second Lien Debt")
    assert _section_for_row(["Equity - controlled/affiliated (excluding Investments in Joint Ventures)"]) == ("equity", "Equity Investments")
    assert _section_for_row(["First Lien Capital Partners - Term Loan"]) is None              # a borrower, not a heading
    assert _closed_section(["Total First Lien Debt", "62,860,907"]) == "First Lien Debt"
    assert _closed_section(["Total First Lien Debt - controlled/affiliated", "391,920"]) is None   # a part of the section
    assert _closed_section(["Total Investment Portfolio", "69,784,151"]) is None


# --- a label that names no single benchmark (Ares 'Base Rate', owner ruling 2026-10-08) ---
ARES_READING = {"columns": frozenset({"reference"}), "codes": {}, "unspecified": frozenset({"base rate"})}


def test_an_unspecified_reference_label_is_read_as_unspecified():
    from pipeline.bdc_xbrl_html_bridge import field_status
    header = {0: "Company", 1: "Investment", 2: "Coupon", 3: "Reference", 4: "Spread"}
    grid = ["Acme", "First lien senior secured revolving loan", "10.50 %", "Base Rate (Q)", "3.00 %"]
    assert field_status("reference_rate_type", grid, header, ARES_READING) == {
        "value": "", "status": "unspecified", "source_column": "Reference"}
    # a named benchmark in the same column is still read; a fund without the label reads as before
    assert field_status("reference_rate_type", grid[:3] + ["SOFR (Q)", "3.00 %"], header, ARES_READING)["value"] == "SOFR"
    plain = {"columns": frozenset({"reference"}), "codes": {}}
    assert field_status("reference_rate_type", grid, header, plain)["status"] != "unspecified"


def test_an_unspecified_reference_withdraws_a_guess_and_nothing_else():
    from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
    guessed = dict(reference_rate_type="SOFR", reference_rate_source="inferred_post_libor", coupon_type="Floating",
                   interest_rate="10.5", basis_spread="3.0", pik_rate="")
    out = apply_ixbrl_field_status_overlay(_staged(**guessed), [_status_row("unspecified")]).iloc[0]
    assert out["reference_rate_type"] == "" and out["reference_rate_source"] == ""
    assert out["coupon_type"] == "Floating" and str(out["basis_spread"]) == "3.0" and str(out["interest_rate"]) == "10.5"
    # one read from the identifier text goes too ('Prime Buyer, L.L.C.' printed with 'Base Rate', Ares 2022-09-30)
    named = dict(guessed, reference_rate_type="PRIME", reference_rate_source="identifier_text")
    assert apply_ixbrl_field_status_overlay(_staged(**named), [_status_row("unspecified")]).iloc[0]["reference_rate_type"] == ""
    # a reference rate the filer tagged is not a guess and stays
    tagged = dict(guessed, reference_rate_source="xbrl_field")
    assert apply_ixbrl_field_status_overlay(_staged(**tagged), [_status_row("unspecified")]).iloc[0]["reference_rate_type"] == "SOFR"
