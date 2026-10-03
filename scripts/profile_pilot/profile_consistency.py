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
    perfectly agreeing wrapper. A filer with zero breaches, AT LEAST ONE COMPARED ROW and one or more
    insufficient_evidence keys instead reports "no_breach", not "holds"; the counts are always published.

Final whole-branch review (2026-10-03), findings C1 and C2 -- the verdict vocabulary and the two exit fields:

  - Filer verdict, four words. "breach": any row breaches. "insufficient_evidence": the contract COMPARED NO
    ROW at all (no holds row and no breach row; also the no-live-wrapper-block case). A check does not pass
    when no comparison happened: NexPoint 0001588272 and TCW 0001715933 have no Q4-2025 census, so even /cik
    has no accepted entry to compare, and "zero breaches" there is "zero comparisons". "no_breach": at least
    one compared row, zero breaches, some insufficient rows. "holds": at least one compared row, zero
    breaches, zero insufficient rows.
  - exit_test publishes TWO separately named fields; they are different claims and must not be merged.
      inception_gate  what the CLI's exit code is gated on: every grid key answered by an entry or a stub
                      (criterion 1), resolver clean, round trip and loader parity ok, zero breaches, no filer
                      with verdict insufficient_evidence, no missing filer. A stub counts as an answer here.
      spec_exit       the spec's exit test (section 8 row 3; section 4.1: a counterpart wrapper key MUST have
                      an accepted entry): the above AND every filer's verdict is "holds". False with a
                      machine-readable reason (spec_exit_reasons) whenever any filer is not "holds".
    The spec's own wording (EXIT_TEST_TEXT) is published as spec_exit_statement ONLY when spec_exit is true;
    otherwise the statement says NOT MET with the counts. `verdict` (PASS/FAIL) follows inception_gate only.
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


VERDICTS = ("holds", "no_breach", "breach", "insufficient_evidence")
SPEC_EXIT_REFERENCE = "spec 2026-09-29 filer-profile programme design, section 8 row 3 (and section 4.1)"
INCEPTION_GATE_DEFINITION = ("every grid key answered by an entry or a stub; resolver clean; round trip and loader "
                             "parity ok; zero breaches; no filer with verdict insufficient_evidence; no missing "
                             "filer. The CLI exit code follows this field. A stub counts as an answer: this is "
                             "not the spec exit test.")


def _verdict(counts: dict) -> str:
    if counts["breach"]:
        return "breach"
    if not counts["holds"]:
        # C1: nothing was compared (no holds row, no breach row). Not a zero-breach outcome: no outcome.
        return "insufficient_evidence"
    if counts["insufficient_evidence"]:
        return "no_breach"
    return "holds"


def row_counts(contract: dict) -> dict:
    """Per-filer key-row counts; `compared` = rows where a comparison actually happened (holds + breach)."""
    c = contract["counts"]
    return dict(total=sum(c[s] for s in STATUSES), compared=c["holds"] + c["breach"], holds=c["holds"],
                breach=c["breach"], insufficient_evidence=c["insufficient_evidence"],
                not_applicable=c["not_applicable"])


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


def _grid_counts(cov: dict) -> dict:
    cells = list(cov["cells"].values())
    return dict(accepted=sum(1 for c in cells if c["accepted_entry_ids"]),
                candidate=sum(1 for c in cells if c["entry_ids"] and not c["accepted_entry_ids"]),
                stubs=sum(1 for c in cells if c["stub"]))


def _published_basis_state(doc: dict):
    ref = doc["partition_predicate"]["published_basis_entry_id"]
    return None if ref is None else doc["admissions"][ref]["state"]


def exit_test(documents: dict, consistency: dict, roundtrip: dict, *, report_date: str, expected_ciks) -> dict:
    per = {}
    for cik in sorted(documents):
        doc = documents[cik]
        cov, res, con = coverage_report(doc, report_date), resolver_report(doc, report_date), consistency[cik]
        # `consistency` is the per-filer GATE criterion: a zero-breach outcome with at least one compared
        # row. "insufficient_evidence" (zero rows compared, or no live wrapper block) fails it (C1).
        per[cik] = dict(criterion_1=cov["ok"], resolver=res["ok"],
                        consistency=con["verdict"] in ("holds", "no_breach"),
                        consistency_verdict=con["verdict"], consistency_rows=row_counts(con),
                        coverage_missing=cov["missing"], resolver_no_entry=res["no_entry"],
                        resolver_ambiguous=res["ambiguous"], resolved=res["counts"]["resolved"],
                        stubs=res["counts"]["stub"], grid=_grid_counts(cov),
                        published_basis=_published_basis_state(doc), consistency_counts=con["counts"],
                        breaches=[r for r in con["keys"] if r["status"] == "breach"])
    missing = sorted(set(expected_ciks) - set(documents))
    roundtrip_ok = bool(roundtrip.get("ok"))
    verdicts = {cik: p["consistency_verdict"] for cik, p in per.items()}
    verdict_counts = {v: sum(1 for x in verdicts.values() if x == v) for v in VERDICTS}

    def where(test) -> list:
        return [cik for cik, p in per.items() if test(p)]

    # Reasons shared by both fields (structure), then the consistency reason each field adds on its own.
    structural = []
    if not per:
        structural.append(dict(code="no_filers", ciks=[]))
    if missing:
        structural.append(dict(code="missing_filers", ciks=missing))
    for code, hit in (("criterion_1_uncovered_keys", where(lambda p: not p["criterion_1"])),
                      ("resolver_not_clean", where(lambda p: not p["resolver"]))):
        if hit:
            structural.append(dict(code=code, ciks=hit))
    if not roundtrip_ok:
        structural.append(dict(code="roundtrip_or_loader_parity", ciks=[]))
    gate_reasons = list(structural)
    for code, word in (("consistency_breach", "breach"),
                       ("consistency_insufficient_evidence", "insufficient_evidence")):
        hit = where(lambda p, word=word: p["consistency_verdict"] == word)
        if hit:
            gate_reasons.append(dict(code=code, ciks=hit))
    not_holds = {cik: v for cik, v in verdicts.items() if v != "holds"}
    spec_reasons = list(structural)
    if not_holds:
        spec_reasons.append(dict(code="consistency_not_holds", ciks=sorted(not_holds), verdicts=not_holds,
                                 verdict_counts=verdict_counts))
    inception_gate, spec_ok = not gate_reasons, not spec_reasons
    compared = sum(p["consistency_rows"]["compared"] for p in per.values())
    total = sum(p["consistency_rows"]["total"] for p in per.values())
    if spec_ok:
        statement = EXIT_TEST_TEXT
    else:
        statement = ("NOT MET: consistency verdict is holds for %d of %d filers (no_breach %d, breach %d, "
                     "insufficient_evidence %d; %d of %d key rows compared); reasons: %s"
                     % (verdict_counts["holds"], len(per), verdict_counts["no_breach"], verdict_counts["breach"],
                        verdict_counts["insufficient_evidence"], compared, total,
                        ", ".join(r["code"] for r in spec_reasons)))
    return dict(report_date=report_date, verdict="PASS" if inception_gate else "FAIL",
                inception_gate=inception_gate, inception_gate_reasons=gate_reasons,
                inception_gate_definition=INCEPTION_GATE_DEFINITION,
                spec_exit=spec_ok, spec_exit_reasons=spec_reasons, spec_exit_reference=SPEC_EXIT_REFERENCE,
                spec_exit_statement=statement, consistency_verdict_counts=verdict_counts,
                consistency_rows=dict(compared=compared, total=total),
                precondition_roundtrip=roundtrip_ok, missing_filers=missing, n_filers=len(per), per_cik=per,
                sample_label="IN-SAMPLE")
