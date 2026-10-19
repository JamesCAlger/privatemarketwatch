"""pipeline.xbrl_instance_xml: one lxml parser for cached XBRL instances (MAI-R1/R2/R4).

libxml2's default parser rejects a text node over 10,000,000 bytes; the helper lifts that
limit and otherwise matches the default parser. A source guard keeps every lxml parse in
pipeline/ on an explicit parser, so no stage silently drops a large filing again.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from lxml import etree

from pipeline.xbrl_instance_xml import instance_parser, parse_instance

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
_HUGE = "x" * 10_500_000

_SMALL = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<!-- filer comment -->\n'
    '<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
    '<context id="c1"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier></entity>'
    '<period><instant>2025-12-31</instant></period></context>'
    '<us-gaap:InvestmentOwnedAtFairValue contextRef="c1" unitRef="usd" decimals="-3">'
    '1000</us-gaap:InvestmentOwnedAtFairValue>'
    '<us-gaap:RiskFactorsTextBlock contextRef="c1">&lt;p&gt;Risk &amp; more&lt;/p&gt;'
    '<![CDATA[<b>raw</b>]]></us-gaap:RiskFactorsTextBlock>'
    '</xbrl>'
)


def test_huge_text_node_parses_where_default_fails(tmp_path):
    p = tmp_path / "big.xml"
    p.write_text(f'<xbrl><text>{_HUGE}</text><v contextRef="c1">5</v></xbrl>', encoding="utf-8")
    with pytest.raises(etree.XMLSyntaxError):
        etree.parse(str(p))
    tree = parse_instance(p)
    assert tree.getroot().find("v").text == "5"
    assert len(tree.getroot().find("text").text) == len(_HUGE)
    root = etree.fromstring(p.read_bytes(), instance_parser())
    assert root.find("v").text == "5"


def test_small_file_parses_identically(tmp_path):
    p = tmp_path / "small.xml"
    p.write_text(_SMALL, encoding="utf-8")
    default = etree.parse(str(p))
    ours = parse_instance(p)
    assert etree.tostring(ours, xml_declaration=True, encoding="utf-8") == \
        etree.tostring(default, xml_declaration=True, encoding="utf-8")
    assert etree.tostring(etree.fromstring(_SMALL.encode(), instance_parser())) == \
        etree.tostring(etree.fromstring(_SMALL.encode()))


def test_malformed_file_still_raises(tmp_path):
    p = tmp_path / "bad.xml"
    p.write_text("<xbrl>", encoding="utf-8")
    with pytest.raises(etree.XMLSyntaxError):
        parse_instance(p)


def _default_parser_calls(path: Path) -> list[int]:
    """Lines calling etree.parse / fromstring / iterparse / XML without a parser argument."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "etree"):
            continue
        name = node.func.attr
        if name in ("parse", "fromstring", "XML"):
            if len(node.args) < 2 and not any(k.arg == "parser" for k in node.keywords):
                bad.append(node.lineno)
        elif name == "iterparse":
            if not any(k.arg == "huge_tree" for k in node.keywords):
                bad.append(node.lineno)
    return bad


def test_no_lxml_default_parser_in_pipeline():
    offenders = {
        p.name: lines for p in sorted(PIPELINE.glob("*.py"))
        if (lines := _default_parser_calls(p))
    }
    assert offenders == {}, (
        "lxml parse with the default parser (fails on >10 MB text nodes); "
        f"use pipeline.xbrl_instance_xml.parse_instance / instance_parser: {offenders}"
    )


def test_guard_detects_a_default_parser_call(tmp_path):
    p = tmp_path / "m.py"
    p.write_text("from lxml import etree\n"
                 "a = etree.parse(x)\n"
                 "b = etree.parse(x, parser)\n"
                 "c = etree.fromstring(blob)\n"
                 "d = etree.fromstring(blob, parser=p)\n", encoding="utf-8")
    assert _default_parser_calls(p) == [2, 4]


@pytest.mark.parametrize("module", [
    "bdc_fund_income", "bdc_fund_highlights", "bdc_sector_breakdown", "bdc_position_pik",
    "bdc_derivatives", "provenance_reverify", "source_reconciliation",
    "bdc_xbrl_html_bridge", "printed_sections",
])
def test_stage_uses_the_shared_helper(module):
    src = (PIPELINE / f"{module}.py").read_text(encoding="utf-8")
    assert "from pipeline.xbrl_instance_xml import" in src
