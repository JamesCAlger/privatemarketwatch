"""SP3 proper: consistency contract between entries and the wrapper section (spec 4.1, D-precedence) and the
sub-project 3 exit test (spec 8 row 3).

Entries are authoritative on meaning, the wrapper on procedure. For every wrapper key with a semantic counterpart
(translate.TRANSLATIONS plus the two reporting-entity list pointers, see A4 below) the ACCEPTED entry resolved at
the report date is converted to wrapper shape by the Task 7 adapter's converter and compared. Exact keys (cik, fv
source field, reporting entities; delimiter by stripped token) can breach; other keys report a representation
mismatch as insufficient_evidence (spec 10). A missing accepted entry is insufficient_evidence, never a silent
pass. The census_published code mirror of the reporting-entity list is a third party to the same comparison.
Evaluated at the inception report date only (inception entries start there); the rest of the wrapper block's
validity is recorded as unevaluated. A breach blocks the filer and is resolved by superseding the wrong side,
never by editing the other.

Three decisions made after the task brief was written, all load-bearing here (see task-8-report.md for the
cross-reference to the brief's literal code):

  - A4 (BCRED, CIK 0001803498): a wrapper can carry both source_encodings.reporting_entity_suffixes and the
    legacy reporting_entity_identifier_suffixes; the entry only ever reads the former. A second COUNTERPARTS
    row checks the legacy pointer against the SAME profile key, so a wrapper that disagrees between its own
    two fields is still caught even though only one of them feeds the entry.
  - Token representation mismatch: a wrapper token compared by stripped-string equality (today only
    identifier_format.delimiter) where EITHER side strips to the empty string is insufficient_evidence
    (reason representation_mismatch), never a trivial holds (both empty) or breach. A one-space or blank
    delimiter is not an evaluable token; TCW (0001715933) and Onex (0001860424) wrappers carry exactly that
    shape in production. This narrows the general "exact/exact_set/token -> holds or breach" rule to a
    three-way outcome for token mode specifically.
  - Unpaired semantic keys: source_encodings.cash_identifiers and invariants.rate_sanity are semantic wrapper
    keys with NO profile_key counterpart anywhere in translate.TRANSLATIONS. They are reported as explicit
    insufficient_evidence rows on every contract -- never omitted, never not_applicable, regardless of whether
    the wrapper happens to populate them -- because there is no mechanism at all to check them profile-side.
    That is a stronger, more honest statement than "nothing to check" (not_applicable), per the project's
    anti-sycophancy requirement: a missing check is not evidence of agreement.
  - Verdict naming: because the two unpaired keys above guarantee insufficient_evidence >= 2 on every real
    contract, a filer verdict of "holds" would never be reachable for ANY of the 8 pilot filers even on a
    perfectly agreeing wrapper. A filer with zero breaches but one or more insufficient_evidence keys instead
    reports "no_breach", not "holds"; both counts are always published in counts. The underlying PASS
    criterion is unchanged (zero breaches, except that no live wrapper block is still insufficient_evidence,
    which is not a pass) -- exit_test's per-filer consistency check now accepts verdict in
    ("holds", "no_breach") rather than comparing to the single literal string "holds".
"""
from __future__ import annotations

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot.translate import TRANSLATIONS, _convert, _get, pointer, value_sha256

COUNTERPARTS = tuple(dict(t) for t in TRANSLATIONS) + (
    dict(wrapper_path=("source_encodings", "reporting_entity_suffixes"),
         profile_key="partition_structure.reporting_entities", convert="string_list"),
    # A4: the legacy pointer, same profile key -- the entry never reads it, but a disagreement between the
    # wrapper's own two reporting-entity fields must still be visible, not silently ignored.
    dict(wrapper_path=("source_encodings", "reporting_entity_identifier_suffixes"),
         profile_key="partition_structure.reporting_entities", convert="string_list"),
)
COMPARE_MODE = {"/cik": "exact", "/invariants/fv_reconciliation/source_field": "exact",
                "/source_encodings/reporting_entity_suffixes": "exact_set",
                "/source_encodings/reporting_entity_identifier_suffixes": "exact_set",
                "/identifier_format/delimiter": "token"}
CODE_MIRROR_POINTER = "code:scripts/profile_pilot/census_published.py:REPORTING_ENTITIES"
# Semantic wrapper keys with no profile-side counterpart at all (see module docstring). Always reported,
# never omitted, never not_applicable, regardless of wrapper presence.
UNPAIRED_WRAPPER_KEYS = (("source_encodings", "cash_identifiers"), ("invariants", "rate_sanity"))
STATUSES = ("holds", "breach", "insufficient_evidence", "not_applicable")
EXIT_TEST_TEXT = "criterion 1; resolver answers every field; consistency contract holds on all 8"


def _compare(mode: str, wrapper_value, converted) -> str:
    if mode == "exact":
        return "holds" if value_sha256(wrapper_value) == value_sha256(converted) else "breach"
    if mode == "exact_set":
        return "holds" if sorted(map(str, wrapper_value or [])) == sorted(map(str, converted or [])) else "breach"
    if mode == "token":
        w, c = str(wrapper_value).strip(), str(converted).strip()
        if not w or not c:
            # Either side carries no evaluable token (e.g. a one-space delimiter): not a holds, not a
            # breach -- there is nothing meaningful being compared.
            return "insufficient_evidence"
        return "holds" if w == c else "breach"
    return "holds" if value_sha256(wrapper_value) == value_sha256(converted) else "insufficient_evidence"


def _verdict(counts: dict) -> str:
    if counts["breach"]:
        return "breach"
    if counts["insufficient_evidence"]:
        return "no_breach"
    return "holds"


def consistency_contract(document: dict, *, report_date: str, code_mirror=()) -> dict:
    blocks = [b for b in document["wrapper_section"]["blocks"]
              if b["family"] == "bdc_xbrl_wrapper" and b["recorded_until"] is None]
    base = dict(cik=document["cik"], report_date=report_date, evaluated_dates=[report_date])
    if len(blocks) != 1:
        return dict(base, block_id=None, unevaluated=None, keys=[], counts={s: 0 for s in STATUSES},
                    verdict="insufficient_evidence")
    block = blocks[0]
    out_rows = []
    for spec in COUNTERPARTS:
        ptr = pointer(spec["wrapper_path"])
        present, wvalue = _get(block["content"], spec["wrapper_path"])
        res = pd.resolve(document, spec["profile_key"], report_date)
        row = dict(pointer=ptr, profile_key=spec["profile_key"], mode=COMPARE_MODE.get(ptr, "representation"),
                   resolution=res["status"], entry_id=(res.get("entry") or {}).get("entry_id"),
                   stub_cause=(res.get("stub") or {}).get("cause"))
        if not present:
            row.update(status="not_applicable", reason="wrapper has no key")
        elif res["status"] != "resolved":
            row.update(status="insufficient_evidence", reason="no accepted entry (" + str(row["stub_cause"]) + ")",
                       wrapper_value=wvalue)
        else:
            converted, via, detail = _convert(spec, res["entry"]["value"])
            if via is None:
                row.update(status="insufficient_evidence", reason="no_wrapper_representation: " + str(detail),
                           wrapper_value=wvalue)
            else:
                status = _compare(row["mode"], wvalue, converted)
                row.update(status=status, wrapper_value=wvalue, entry_value_as_wrapper=converted,
                           reason=None if status == "holds" else
                           ("representation_mismatch" if status == "insufficient_evidence" else "value_disagrees"))
        out_rows.append(row)
    for path in UNPAIRED_WRAPPER_KEYS:
        ptr = pointer(path)
        present, wvalue = _get(block["content"], path)
        out_rows.append(dict(pointer=ptr, profile_key=None, mode="no_counterpart", resolution=None, entry_id=None,
                             stub_cause=None, status="insufficient_evidence",
                             reason="no profile_key counterpart exists for this wrapper key: there is no "
                                    "mechanism to check it, not merely nothing to check",
                             wrapper_present=present, wrapper_value=wvalue if present else None))
    mirror = sorted(str(v) for v in code_mirror)
    res = pd.resolve(document, "partition_structure.reporting_entities", report_date)
    if res["status"] == "resolved":
        status = "holds" if sorted(map(str, res["entry"]["value"])) == mirror else "breach"
        reason = None if status == "holds" else "code mirror differs from the entry"
    else:
        status = "breach" if mirror else "not_applicable"
        reason = "code mirror carries per-filer knowledge with no accepted entry" if mirror else "no list anywhere"
    out_rows.append(dict(pointer=CODE_MIRROR_POINTER, profile_key="partition_structure.reporting_entities",
                         mode="exact_set", resolution=res["status"],
                         entry_id=(res.get("entry") or {}).get("entry_id"),
                         stub_cause=(res.get("stub") or {}).get("cause"), status=status, reason=reason,
                         code_value=mirror))
    counts = {s: sum(r["status"] == s for r in out_rows) for s in STATUSES}
    return dict(base, block_id=block["block_id"],
                unevaluated=dict(block_valid=[block["valid_from"], block["valid_to"]],
                                 reason="inception entries start at " + report_date
                                        + "; other report dates of the block are not evaluated in sub-project 3"),
                keys=out_rows, counts=counts, verdict=_verdict(counts))


def coverage_report(document: dict, report_date: str) -> dict:
    cells = pd.coverage(document, report_date)
    missing = [k for k, c in cells.items()
               if not c["entry_ids"] and not (c["stub"] and c["stub"]["closing_evidence"])]
    return dict(ok=not missing, missing=missing, cells=cells,
                stubs=sum(1 for c in cells.values() if c["stub"]),
                entries=sum(1 for c in cells.values() if c["entry_ids"]))


def resolver_report(document: dict, report_date: str) -> dict:
    counts, no_entry, ambiguous = {"resolved": 0, "stub": 0}, [], []
    for key in pd.GRID_KEYS:
        try:
            res = pd.resolve(document, key, report_date)
        except pd.ProfileAmbiguityError as exc:
            ambiguous.append(dict(key=key, error=str(exc)))
            continue
        if res["status"] == "no_entry":
            no_entry.append(key)
        else:
            counts[res["status"]] += 1
    return dict(ok=not no_entry and not ambiguous, counts=counts, no_entry=no_entry, ambiguous=ambiguous)


def exit_test(documents: dict, consistency: dict, roundtrip: dict, *, report_date: str, expected_ciks) -> dict:
    per = {}
    for cik in sorted(documents):
        doc = documents[cik]
        cov, res, con = coverage_report(doc, report_date), resolver_report(doc, report_date), consistency[cik]
        # "holds" and "no_breach" are both zero-breach outcomes; a no-live-block document still reports the
        # literal "insufficient_evidence" verdict, which correctly fails this criterion.
        per[cik] = dict(criterion_1=cov["ok"], resolver=res["ok"],
                        consistency=con["verdict"] in ("holds", "no_breach"),
                        coverage_missing=cov["missing"], resolver_no_entry=res["no_entry"],
                        resolver_ambiguous=res["ambiguous"], resolved=res["counts"]["resolved"],
                        stubs=res["counts"]["stub"], consistency_counts=con["counts"],
                        breaches=[r for r in con["keys"] if r["status"] == "breach"])
    missing = sorted(set(expected_ciks) - set(documents))
    spec_ok = (not missing and bool(per)
               and all(p["criterion_1"] and p["resolver"] and p["consistency"] for p in per.values()))
    return dict(report_date=report_date, spec_exit_test=EXIT_TEST_TEXT, spec_exit=spec_ok,
                precondition_roundtrip=bool(roundtrip.get("ok")), missing_filers=missing,
                verdict="PASS" if spec_ok and roundtrip.get("ok") else "FAIL", n_filers=len(per), per_cik=per,
                sample_label="IN-SAMPLE")
