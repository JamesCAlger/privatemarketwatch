"""Round-4 retirement-campaign checks (scripts/v05_evidence/campaign_round4_check.py): which rows a verdict
names, which claims are not holdings claims, and the per-row value tests failing on their plants."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v05_evidence"))

import campaign_round4_check as c4  # noqa: E402


def test_named_rows_by_quoted_row_id_or_issuer():
    rows = [{"row_id": "ROW-41542ef30353d2b0", "issuer_name": "BlackRock T-Fund"},
            {"row_id": "ROW-0000000000000001", "issuer_name": "Acme Widgets LLC"}]
    assert [r["row_id"] for r in c4.named_rows(rows, {"row_ids": ["ROW-41542ef30353d2b0"]})] == ["ROW-41542ef30353d2b0"]
    hit = c4.named_rows(rows, {"vtext": "the Acme Widgets revolver row shows cost as a dash"})
    assert [r["issuer_name"] for r in hit] == ["Acme Widgets LLC"]


def test_gav_denominator_claim_is_not_a_holdings_claim():
    spec = c4.make_spec("GAV_BDC02", {"mechanism": "extraction_gap", "observed_value": "no_comparison",
                                      "rationale": "the platform recorded comparison_source=None/no_comparison"})
    assert "untestable" in spec
    res = c4.check("GAV_BDC02", spec, None, "", "0000000001", "2026-03-31", rows=[])
    assert not res["ok"]


def test_c006_spec_reads_the_filing_accession():
    spec = c4.make_spec("C006", {"anchor_value": "0001193125-26-115988", "rationale": "x"})
    assert spec["accession"] == "0001193125-26-115988"


def test_fund_level_rules_are_not_testable():
    for rule in ("F10", "income_identity", "F28"):
        assert not c4.check(rule, {}, None, "", "0000000001", "2026-03-31", rows=[])["ok"]
