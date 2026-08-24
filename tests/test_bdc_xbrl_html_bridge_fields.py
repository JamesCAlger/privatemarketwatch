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
    data = {"schema_version": BRIDGE_SCHEMA_VERSION, "cik": "0001803498",
            "version": 1, "source": "bdc_xbrl", "bridges": rows}
    (tmp_path / "0001803498.proposed.json").write_text(json.dumps(data), encoding="utf-8")
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
            "schema_version": BRIDGE_SCHEMA_VERSION,
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
