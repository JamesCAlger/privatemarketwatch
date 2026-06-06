import json
from pathlib import Path

import pandas as pd
import jsonschema

from pipeline.bdc_xbrl_html_bridge import (
    BRIDGE_SCHEMA_VERSION,
    _parse_inline_instrument_type,
    _section_for_row,
    apply_html_section_bridge_wrapper_columns,
    load_html_section_bridge_rows,
    propose_html_section_bridges,
)


def test_load_html_section_bridge_rows_normalizes_exact_keys(tmp_path):
    bridge_dir = tmp_path / "bridges"
    bridge_dir.mkdir()
    (bridge_dir / "0000000123.json").write_text(
        json.dumps(
            {
                "schema_version": BRIDGE_SCHEMA_VERSION,
                "cik": "0000000123",
                "version": 1,
                "source": "bdc_xbrl",
                "bridges": [
                    {
                        "accession_number": "0000000000-26-000001",
                        "report_date": "2026-03-31",
                        "raw_id_lower": "acme corp",
                        "issuer_name": "Acme Corp",
                        "instrument_description": "First Lien Debt",
                        "family": "debt",
                        "html_sha256": "a" * 64,
                        "table_index": 2,
                        "section_row_index": 4,
                        "row_index": 5,
                        "cell_indices": [0, 4, 5],
                        "section_label": "First Lien Debt",
                        "match_evidence": {"matched_terms": ["acme corp"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rows = load_html_section_bridge_rows(bridge_dir)

    assert rows.to_dict("records")[0]["cik"] == "0000000123"
    assert rows.to_dict("records")[0]["disposition"] == "debt_position_leaf"
    assert rows.to_dict("records")[0]["raw_id_lower"] == "acme corp"


def test_bridge_schema_accepts_valid_instance():
    schema = json.loads(
        Path("schemas/bdc_xbrl_html_section_bridge/bridge_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    instance = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "cik": "0000000123",
        "version": 1,
        "source": "bdc_xbrl",
        "bridges": [
            {
                "accession_number": "0000000000-26-000001",
                "report_date": "2026-03-31",
                "raw_id_lower": "acme corp",
                "issuer_name": "Acme Corp",
                "instrument_description": "First Lien Debt",
                "family": "debt",
                "html_sha256": "a" * 64,
                "table_index": 1,
                "section_row_index": 2,
                "row_index": 3,
                "cell_indices": [0, 1, 2],
                "section_label": "First Lien Debt",
                "match_evidence": {
                    "matched_terms": ["acme corp"],
                    "fair_value_matched": True,
                },
            }
        ],
    }

    jsonschema.validate(instance=instance, schema=schema)


def test_apply_html_section_bridge_wrapper_columns_is_accession_scoped(tmp_path):
    bridge_dir = tmp_path / "bridges"
    bridge_dir.mkdir()
    (bridge_dir / "0000000123.json").write_text(
        json.dumps(
            {
                "schema_version": BRIDGE_SCHEMA_VERSION,
                "cik": "0000000123",
                "version": 1,
                "source": "bdc_xbrl",
                "bridges": [
                    {
                        "accession_number": "0000000000-26-000001",
                        "report_date": "2026-03-31",
                        "raw_id_lower": "acme corp",
                        "issuer_name": "Acme Corp",
                        "instrument_description": "Common Equity",
                        "family": "equity",
                        "html_sha256": "b" * 64,
                        "table_index": 1,
                        "section_row_index": 2,
                        "row_index": 3,
                        "cell_indices": [0, 3, 4],
                        "section_label": "Common Equity",
                        "match_evidence": {"matched_terms": ["acme corp"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    df = pd.DataFrame(
        [
            {
                "cik": "123",
                "accession_number": "0000000000-26-000001",
                "report_date": "2026-03-31",
                "investment_identifier": "Acme Corp",
                "wrapper_family": "",
                "wrapper_disposition": "",
                "wrapper_rule_id": "",
                "wrapper_parent_key": "",
                "wrapper_position_key": "",
                "wrapper_signature_status": "",
            },
            {
                "cik": "123",
                "accession_number": "0000000000-26-000002",
                "report_date": "2026-03-31",
                "investment_identifier": "Acme Corp",
                "wrapper_family": "",
                "wrapper_disposition": "",
                "wrapper_rule_id": "",
                "wrapper_parent_key": "",
                "wrapper_position_key": "",
                "wrapper_signature_status": "",
            },
        ]
    )

    out = apply_html_section_bridge_wrapper_columns(
        df,
        identifier_col="investment_identifier",
        bridge_dir=bridge_dir,
    )

    assert out.loc[0, "wrapper_family"] == "equity"
    assert out.loc[0, "wrapper_disposition"] == "equity_position_leaf"
    assert out.loc[1, "wrapper_family"] == ""
    assert out.loc[1, "wrapper_disposition"] == ""


def test_propose_html_section_bridges_uses_active_section_headers(tmp_path):
    html_path = tmp_path / "filing.html"
    html_path.write_text(
        """
        <html><body><table>
          <tr><td>Company</td><td>Cost</td><td>Fair Value</td></tr>
          <tr><td>First Lien Debt</td></tr>
          <tr><td>Acme Corp</td><td>1,000</td><td>2,000</td></tr>
          <tr><td>Common Equity</td></tr>
          <tr><td>Beta Holdings LLC</td><td>3,000</td><td>4,000</td></tr>
        </table></body></html>
        """,
        encoding="utf-8",
    )

    proposal = propose_html_section_bridges(
        cik="123",
        accession_number="0000000000-26-000001",
        report_date="2026-03-31",
        html_path=html_path,
        source_rows=[
            {
                "investment_identifier": "Investments Acme Corp",
                "fair_value": "2000",
            },
            {
                "investment_identifier": "Investments Beta Holdings LLC",
                "fair_value": "4000",
            },
        ],
    )

    families = {row["raw_id_lower"]: row["family"] for row in proposal["bridges"]}
    instruments = {
        row["raw_id_lower"]: row["instrument_description"]
        for row in proposal["bridges"]
    }
    assert families["investments acme corp"] == "debt"
    assert instruments["investments acme corp"] == "First Lien Debt"
    assert families["investments beta holdings llc"] == "equity"
    assert instruments["investments beta holdings llc"] == "Common Equity"


# --- Section pattern tests ---


def test_section_for_row_equity_investments():
    assert _section_for_row(["Equity Investments"]) == ("equity", "Equity Investments")


def test_section_for_row_new_patterns():
    assert _section_for_row(["Other Secured Debt"]) == ("debt", "Other Secured Debt")
    assert _section_for_row(["Structured Finance"]) == ("debt", "Structured Finance")
    assert _section_for_row(["Structured Finance Investments"]) == ("debt", "Structured Finance")
    assert _section_for_row(["Investments in Joint Ventures"]) == ("equity", "Joint Ventures")
    assert _section_for_row(["Investment in Joint Venture"]) == ("equity", "Joint Ventures")


# --- Inline instrument type parser tests ---


def test_parse_inline_instrument_type_preferred_stock():
    assert _parse_inline_instrument_type("CG Parent Intermediate Holdings, Inc. (4)(22) - Preferred Stock") == "Preferred Stock"


def test_parse_inline_instrument_type_class_units():
    assert _parse_inline_instrument_type("Eating Recovery Center TopCo, LLC - Class A Common Units") == "Class A Common Units"


def test_parse_inline_instrument_type_warrants():
    assert _parse_inline_instrument_type("Eagle LNG Partners Jacksonville II LLC - Warrants") == "Warrants"


def test_parse_inline_instrument_type_none_for_bare_name():
    assert _parse_inline_instrument_type("Acme Corp") is None


def test_parse_inline_instrument_type_none_for_affiliation():
    """Affiliation labels like 'Controlled/Affiliated' must not match."""
    assert _parse_inline_instrument_type("Some Entity - Controlled/Affiliated") is None


# --- Integration test: equity section with inline types ---


def test_propose_bridges_equity_section_with_inline_types(tmp_path):
    html_path = tmp_path / "filing.html"
    html_path.write_text(
        """
        <html><body><table>
          <tr><td>Company</td><td>Cost</td><td>Fair Value</td></tr>
          <tr><td>Equity Investments</td></tr>
          <tr><td>Alpha Corp (4)(22) - Preferred Stock</td><td>5,000</td><td>6,000</td></tr>
          <tr><td>Bravo LLC - Warrants</td><td>1,000</td><td>1,500</td></tr>
        </table></body></html>
        """,
        encoding="utf-8",
    )

    proposal = propose_html_section_bridges(
        cik="999",
        accession_number="0000000000-26-000099",
        report_date="2026-03-31",
        html_path=html_path,
        source_rows=[
            {
                "investment_identifier": "Alpha Corp Preferred Stock",
                "fair_value": "6000",
            },
            {
                "investment_identifier": "Bravo LLC Warrants",
                "fair_value": "1500",
            },
        ],
    )

    families = {row["raw_id_lower"]: row["family"] for row in proposal["bridges"]}
    instruments = {
        row["raw_id_lower"]: row["instrument_description"]
        for row in proposal["bridges"]
    }
    inline_types = {
        row["raw_id_lower"]: row.get("inline_instrument_type")
        for row in proposal["bridges"]
    }

    assert families["alpha corp preferred stock"] == "equity"
    assert instruments["alpha corp preferred stock"] == "Preferred Stock"
    assert inline_types["alpha corp preferred stock"] == "Preferred Stock"

    assert families["bravo llc warrants"] == "equity"
    assert instruments["bravo llc warrants"] == "Warrants"
    assert inline_types["bravo llc warrants"] == "Warrants"
