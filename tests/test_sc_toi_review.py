import csv
import json
from pathlib import Path

from pipeline import sc_toi_review as review


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _html(body: str, checkbox: str = "&#9744;") -> str:
    return f"""
    <html><body>
    <p>Check the following box if the filing is a final amendment reporting
    the results of the tender offer: {checkbox}</p>
    {body}
    </body></html>
    """


def _index_row(tmp_path: Path, *, accession: str, html: str, cik: str = "1", form_type: str = "SC TO-I/A") -> dict[str, str]:
    html_path = tmp_path / f"{accession}.html"
    html_path.write_text(html, encoding="utf-8")
    return {
        "accession_number": accession,
        "cik": cik,
        "entity_name": "Fund A",
        "form_type": form_type,
        "filing_date": "2025-01-31",
        "primary_document": f"{accession}.htm",
        "html_local_path": str(html_path),
    }


def _tag(accession: str, evidence_ref: str = "filing_1", role: str = "issuer_self_tender") -> dict[str, object]:
    return {
        "accession_number": accession,
        "offer_role_tag": role,
        "confidence": "HIGH",
        "evidence_refs": [evidence_ref],
        "subject_company": "",
        "offeror": "",
        "notes": "Test tag.",
    }


def test_checkbox_state_detects_common_checked_and_unchecked_encodings():
    assert review.checkbox_state(_html("", "&#9746;")) == "checked"
    assert review.checkbox_state(_html("", "[x]")) == "checked"
    assert review.checkbox_state(_html("", "&#9633;")) == "unchecked"
    assert review.checkbox_state(_html("", "[__]")) == "unchecked"
    assert review.checkbox_state("<html>No checkbox here</html>") == "absent"


def test_offer_role_hints_detect_checked_schedule_to_options():
    third_party_html = """
    <p>&#9746; third-party tender offer subject to Rule 14d-1.</p>
    <p>&#9744; issuer tender offer subject to Rule 13e-4.</p>
    """
    issuer_html = """
    <p>&#9744; third-party tender offer subject to Rule 14d-1.</p>
    <p>&#9746; issuer tender offer subject to Rule 13e-4.</p>
    """
    conflict_html = """
    <p>&#9746; third-party tender offer subject to Rule 14d-1.</p>
    <p>&#9746; issuer tender offer subject to Rule 13e-4.</p>
    """

    assert review.classify_offer_role(third_party_html, "SC TO-T/A")["offer_role_hint"] == "third_party_tender"
    assert review.classify_offer_role(issuer_html, "SC TO-I/A")["offer_role_hint"] == "issuer_self_tender"
    assert review.classify_offer_role(conflict_html, "SC TO-I/A")["offer_role_hint"] == "unknown_role"


def test_offer_role_falls_back_to_form_type_without_checked_options():
    assert review.classify_offer_role("<p>No role checkbox text.</p>", "SC TO-T/A")["offer_role_hint"] == "third_party_tender"
    assert review.classify_offer_role("<p>No role checkbox text.</p>", "SC TO-I/A")["offer_role_hint"] == "issuer_self_tender"


def test_no_data_triage_separates_checked_final_from_unchecked_original():
    final_html = _html(
        "<p>FINAL AMENDMENT TO TENDER OFFER STATEMENT</p>"
        "<p>1,000 Shares were validly tendered and not withdrawn. "
        "The Fund purchased all 1,000 Shares.</p>",
        "&#9746;",
    )
    original_html = _html("<p>The Fund offers to purchase shares.</p>", "&#9744;")

    final_info = review.classify_no_data_filing(final_html)
    original_info = review.classify_no_data_filing(original_html)

    assert final_info["category"] == "likely_final_results_missed"
    assert final_info["checkbox_state"] == "checked"
    assert original_info["category"] == "unchecked_original_or_intermediate"
    assert original_info["checkbox_state"] == "unchecked"


def test_build_worklist_excludes_unchecked_original_and_groups_reviewable_rows(tmp_path):
    index_path = tmp_path / "sc_toi_filings_index.csv"
    progress_path = tmp_path / "sc_toi_parse_progress.csv"
    results_path = tmp_path / "sc_toi_repurchase_results.csv"
    out = tmp_path / "sc_toi_review"

    checked = _index_row(
        tmp_path,
        accession="0001",
        html=_html(
            "<p>FINAL AMENDMENT TO TENDER OFFER STATEMENT</p>"
            "<p>1,000 Shares were validly tendered and not withdrawn.</p>",
            "&#9746;",
        ),
    )
    unchecked = _index_row(
        tmp_path,
        accession="0002",
        html=_html("<p>The Fund offers to purchase shares.</p>", "&#9744;"),
    )
    partial = _index_row(
        tmp_path,
        accession="0003",
        html=_html("<p>500 Shares were validly tendered.</p>", "&#9746;"),
    )
    _write_csv(index_path, [checked, unchecked, partial])
    _write_csv(
        progress_path,
        [
            {"accession_number": "0001", "status": "no_data", "count": "0"},
            {"accession_number": "0002", "status": "no_data", "count": "0"},
            {"accession_number": "0003", "status": "partial", "count": "1"},
        ],
    )
    _write_csv(
        results_path,
        [
            {
                "accession_number": "0003",
                "cik": "0000000001",
                "entity_name": "Fund A",
                "form_type": "SC TO-I/A",
                "filing_date": "2025-01-31",
                "shares_tendered": "500",
                "shares_accepted": "",
                "repurchase_price_per_share": "",
                "offer_expiration_date": "2025-01-01",
            }
        ],
    )

    stats = review.build_worklist(
        filings_index_path=index_path,
        progress_path=progress_path,
        results_path=results_path,
        output_dir=out,
    )

    assert stats["triage_counts"]["unchecked_original_or_intermediate"] == 1
    assert stats["worklist_count"] == 3
    worklist = _read_csv(out / "worklist.csv")
    categories = {row["category"] for row in worklist}
    assert "unchecked_original_or_intermediate" not in categories
    assert {"likely_final_results_missed", "partial_parse", "result_missing_fields"} == categories


def test_mixed_to_t_and_to_i_rows_split_by_offer_role_and_bundle_all_accessions(tmp_path):
    index_path = tmp_path / "sc_toi_filings_index.csv"
    progress_path = tmp_path / "sc_toi_parse_progress.csv"
    results_path = tmp_path / "sc_toi_repurchase_results.csv"
    out = tmp_path / "sc_toi_review"

    third_party = _index_row(
        tmp_path,
        accession="0001",
        form_type="SC TO-T/A",
        html=_html(
            "<p>&#9746; third-party tender offer subject to Rule 14d-1.</p>"
            "<p>&#9744; issuer tender offer subject to Rule 13e-4.</p>"
            "<p>The Offer resulted in acceptance for payment by the Purchasers of 100 Shares.</p>",
            "&#9746;",
        ),
    )
    issuer = _index_row(
        tmp_path,
        accession="0002",
        form_type="SC TO-I/A",
        html=_html(
            "<p>&#9744; third-party tender offer subject to Rule 14d-1.</p>"
            "<p>&#9746; issuer tender offer subject to Rule 13e-4.</p>"
            "<p>The Company has received and accepted a total of 200 Shares.</p>",
            "&#9746;",
        ),
    )
    _write_csv(index_path, [third_party, issuer])
    _write_csv(
        progress_path,
        [
            {"accession_number": "0001", "status": "no_data", "count": "0"},
            {"accession_number": "0002", "status": "no_data", "count": "0"},
        ],
    )
    _write_csv(results_path, [])

    stats = review.build_worklist(
        filings_index_path=index_path,
        progress_path=progress_path,
        results_path=results_path,
        output_dir=out,
    )
    assert stats["worklist_count"] == 2
    worklist = _read_csv(out / "worklist.csv")
    assert {row["offer_role_hint"] for row in worklist} == {"third_party_tender", "issuer_self_tender"}

    manifest = review.build_bundles(output_dir=out, overwrite=True)
    for item in manifest:
        bundle = json.loads((out / "bundles" / f"{item['review_id']}.json").read_text(encoding="utf-8"))
        assert len(bundle["packet_accessions"]) == 1
        filing_evidence = [e for e in bundle["evidence_items"] if e["kind"] == "filing_snippet"]
        assert len(filing_evidence) == 1


def test_build_bundles_and_validate_parser_pattern_verdict(tmp_path):
    index_path = tmp_path / "sc_toi_filings_index.csv"
    progress_path = tmp_path / "sc_toi_parse_progress.csv"
    results_path = tmp_path / "sc_toi_repurchase_results.csv"
    out = tmp_path / "sc_toi_review"
    schema = Path("schemas/sc_toi_review/verdict.schema.json")
    idx = _index_row(
        tmp_path,
        accession="0001",
        html=_html(
            "<p>FINAL AMENDMENT TO TENDER OFFER STATEMENT</p>"
            "<p>1,000 Shares were validly tendered and not withdrawn.</p>",
            "[x]",
        ),
    )
    _write_csv(index_path, [idx])
    _write_csv(progress_path, [{"accession_number": "0001", "status": "no_data", "count": "0"}])
    _write_csv(results_path, [])
    review.build_worklist(
        filings_index_path=index_path,
        progress_path=progress_path,
        results_path=results_path,
        output_dir=out,
    )
    manifest = review.build_bundles(output_dir=out, overwrite=True)
    assert len(manifest) == 1
    bundle = json.loads((out / "bundles" / f"{manifest[0]['review_id']}.json").read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "sc-toi-review-bundle.v1"
    assert {item["evidence_id"] for item in bundle["evidence_items"]} >= {"worklist_row", "filing_1"}

    verdict = {
        "review_id": bundle["review_id"],
        "cik": bundle["cik"],
        "category": bundle["category"],
        "verdict": "PARSER_PATTERN_PROPOSED",
        "confidence": "HIGH",
        "primary_justification": "The filing reports final results but parser emitted no row.",
        "evidence_refs": ["filing_1"],
        "filing_tags": [_tag("0001")],
        "affected_fields": ["shares_tendered"],
        "parser_gap_mechanism": "The result wording is not matched by the current tendered-share regex.",
        "proposed_pattern": "Capture shares validly tendered and not withdrawn.",
        "false_positive_risk": "Restrict to checked final amendments or final-heading context.",
        "changed_files": [],
        "tests_validation_plan": "Add regex positive and original-offer false-positive tests.",
        "requires_human_merge": True,
        "missing_evidence": "",
        "residual_risk": "Only one sample in this bundle.",
        "reviewer_notes": "Schema-valid parser proposal.",
    }
    verdict_path = out / "verdicts" / f"{bundle['review_id']}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    assert review.validate_verdict_file(verdict_path, out, schema) == []

    verdict["evidence_refs"] = ["unknown_ref"]
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    errors = review.validate_verdict_file(verdict_path, out, schema)
    assert any("unknown evidence_ref" in error for error in errors)


def test_out_of_scope_third_party_requires_all_third_party_tags(tmp_path):
    out = tmp_path / "sc_toi_review"
    (out / "bundles").mkdir(parents=True)
    (out / "verdicts").mkdir(parents=True)
    review_id = "SCTOI_0000000001_LIKELY_FINAL_RESULTS_MISSED_abc"
    _write_csv(
        out / "worklist.csv",
        [{"review_id": review_id, "cik": "0000000001", "category": "likely_final_results_missed"}],
    )
    (out / "bundles" / f"{review_id}.json").write_text(
        json.dumps(
            {
                "review_id": review_id,
                "cik": "0000000001",
                "category": "likely_final_results_missed",
                "evidence_items": [
                    {"evidence_id": "worklist_row", "data": {}},
                    {"evidence_id": "filing_1", "data": {"accession_number": "0001"}},
                ],
            }
        ),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "category": "likely_final_results_missed",
        "verdict": "OUT_OF_SCOPE_THIRD_PARTY",
        "confidence": "HIGH",
        "primary_justification": "Only third-party tender-offer results are present.",
        "evidence_refs": ["filing_1"],
        "filing_tags": [_tag("0001", "filing_1", "third_party_tender")],
        "affected_fields": [],
        "parser_gap_mechanism": "",
        "proposed_pattern": "",
        "false_positive_risk": "Should not enter issuer repurchase output.",
        "changed_files": [],
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "",
        "residual_risk": "One filing reviewed.",
        "reviewer_notes": "Third-party-only packet.",
    }
    verdict_path = out / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    assert review.validate_verdict_file(verdict_path, out, Path("schemas/sc_toi_review/verdict.schema.json")) == []

    verdict["filing_tags"][0]["offer_role_tag"] = "issuer_self_tender"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    errors = review.validate_verdict_file(verdict_path, out, Path("schemas/sc_toi_review/verdict.schema.json"))
    assert any("all filing_tags to be third_party_tender" in error for error in errors)


def test_validate_verdict_blocks_protected_output_edits(tmp_path):
    out = tmp_path / "sc_toi_review"
    (out / "bundles").mkdir(parents=True)
    (out / "verdicts").mkdir(parents=True)
    review_id = "SCTOI_0000000001_LIKELY_FINAL_RESULTS_MISSED_abc"
    _write_csv(
        out / "worklist.csv",
        [{"review_id": review_id, "cik": "0000000001", "category": "likely_final_results_missed"}],
    )
    (out / "bundles" / f"{review_id}.json").write_text(
        json.dumps(
            {
                "review_id": review_id,
                "cik": "0000000001",
                "category": "likely_final_results_missed",
                "evidence_items": [{"evidence_id": "filing_1"}],
            }
        ),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "category": "likely_final_results_missed",
        "verdict": "NO_RESULTS_EXPECTED",
        "confidence": "LOW",
        "primary_justification": "No final result fields found.",
        "evidence_refs": ["filing_1"],
        "filing_tags": [_tag(review_id, role="unknown_role")],
        "affected_fields": [],
        "parser_gap_mechanism": "",
        "proposed_pattern": "",
        "false_positive_risk": "",
        "changed_files": ["data/output/sc_toi_repurchase_results.csv"],
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "",
        "residual_risk": "Manual output edits are not allowed.",
        "reviewer_notes": "Should fail protected edit validation.",
    }
    verdict_path = out / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = review.validate_verdict_file(verdict_path, out, Path("schemas/sc_toi_review/verdict.schema.json"))
    assert any("protected generated-output edit" in error for error in errors)


def test_validate_all_verdicts_can_allow_incremental_batches(tmp_path):
    out = tmp_path / "sc_toi_review"
    (out / "bundles").mkdir(parents=True)
    (out / "verdicts").mkdir(parents=True)
    review_id = "SCTOI_0000000001_NO_FINAL_CHECKBOX_LANGUAGE_abc"
    missing_review_id = "SCTOI_0000000002_NO_FINAL_CHECKBOX_LANGUAGE_def"
    _write_csv(
        out / "worklist.csv",
        [
            {"review_id": review_id, "cik": "0000000001", "category": "no_final_checkbox_language"},
            {"review_id": missing_review_id, "cik": "0000000002", "category": "no_final_checkbox_language"},
        ],
    )
    (out / "bundles" / f"{review_id}.json").write_text(
        json.dumps(
            {
                "review_id": review_id,
                "cik": "0000000001",
                "category": "no_final_checkbox_language",
                "evidence_items": [{"evidence_id": "worklist_row"}],
            }
        ),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "category": "no_final_checkbox_language",
        "verdict": "NO_RESULTS_EXPECTED",
        "confidence": "MEDIUM",
        "primary_justification": "The sample does not include final amendment language.",
        "evidence_refs": ["worklist_row"],
        "filing_tags": [_tag(review_id, "worklist_row", "not_final_or_no_results")],
        "affected_fields": [],
        "parser_gap_mechanism": "",
        "proposed_pattern": "",
        "false_positive_risk": "",
        "changed_files": [],
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "",
        "residual_risk": "Only one packet has been reviewed.",
        "reviewer_notes": "Incremental review verdict.",
    }
    (out / "verdicts" / f"{review_id}.json").write_text(json.dumps(verdict), encoding="utf-8")

    strict_errors = review.validate_all_verdicts(out, Path("schemas/sc_toi_review/verdict.schema.json"))
    incremental_errors = review.validate_all_verdicts(
        out,
        Path("schemas/sc_toi_review/verdict.schema.json"),
        require_complete=False,
    )

    assert any("Missing verdict" in error["error"] for error in strict_errors)
    assert incremental_errors == []
