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
  - Unpaired keys (SUPERSEDED by owner ruling 1 of 2026-10-04, below): source_encodings.cash_identifiers and
    invariants.rate_sanity have NO profile_key counterpart anywhere in translate.TRANSLATIONS. Until the
    ruling they were emitted as always-insufficient_evidence key rows, which made "holds" unreachable.
  - Verdict naming: a filer with zero breaches, AT LEAST ONE COMPARED ROW and one or more
    insufficient_evidence keys reports "no_breach", not "holds"; the counts are always published.

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

Owner rulings of 2026-10-04 (rulings 1 and 3; ruling 2 lives in profile_inception):

  - Ruling 1, contract scope. cash_identifiers and rate_sanity are classified as PROCEDURE and are NOT key rows
    of the contract (they no longer count as insufficient_evidence). They are not dropped silently: every
    contract publishes them in `procedure_keys_outside_contract`, each with a NAMED guard.
      cash_identifiers  guard `independent_totals`: a disagreement in which rows are cash moves the
                        published-basis fair-value sum, which the totals check at the +/-0.5% band of ruling 2
                        catches and routes to B1/B2 review. The guard's own state for THIS filer at the report
                        date is published beside it (`guard_status_at_report_date`): a filer with no totals
                        outcome has a named guard that did not run, and the row says so.
      rate_sanity       guard `production_rate_rules` (owner correction of the same day; it replaced a first
                        reading of `none_claimed`): the production rate detectors named in
                        PRODUCTION_RATE_RULES. They are NAMED, not evaluated here -- this module does not read
                        their output, and the note states what they do not cover.
    "holds" is therefore reachable in principle: every counterpart key row of the filer holds.
  - Ruling 3, the gate needs a substantive comparison. Identity rows (IDENTITY_PROFILE_KEYS: the entity CIK and
    the registrant name; "CIK equals CIK") do not satisfy the gate. A filer passes the consistency leg only
    with zero breaches and at least MIN_SUBSTANTIVE_COMPARED_ROWS compared rows that are not identity rows.
    A breach on an identity row is still a breach. Both counts and the substantive keys are published per
    filer. MIN_SUBSTANTIVE_COMPARED_SHARE is the hook for a later minimum-share ruling; it is None (no
    threshold) and setting it without implementing the rule raises.
"""
from __future__ import annotations

from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot import profile_inception as pi
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
# Owner ruling 1 (2026-10-04): wrapper keys with no profile-side counterpart are PROCEDURE, outside the
# consistency contract. Published per filer in `procedure_keys_outside_contract`, each with a named guard.
GUARD_TOTALS, GUARD_RATE_RULES = "independent_totals", "production_rate_rules"
# The production rate detectors the owner named (correction to ruling 1, 2026-10-04). Each name was checked
# to exist in the code at the time of writing: the findings-ledger format rules (fmt_<column>, generated in
# scripts/shadow_weak_engine.py), scripts/shadow_agent_a_engine.py, pipeline/oracle_checks.py (check D07).
PRODUCTION_RATE_RULES = ("fmt_basis_spread", "fmt_pik_rate", "fmt_interest_rate", "agentA_spread_vs_xbrl",
                         "oracle_D07_median_rate_shift_gt_300bps")
PROCEDURE_KEYS_OUTSIDE_CONTRACT = (
    dict(wrapper_path=("source_encodings", "cash_identifiers"), guard=GUARD_TOTALS,
         guard_note=("published-basis fair-value totals check at the +/-%s%% band (owner ruling 2, 2026-10-04): a "
                     "disagreement in which rows are cash is caught downstream by the fair-value reconciliation "
                     "and routed to the B1/B2 review agents. It is caught only insofar as it moves the "
                     "published-basis fair-value sum outside that band."
                     % pi.PUBLISHED_BASIS_FV_TOLERANCE_PCT)),
    dict(wrapper_path=("invariants", "rate_sanity"), guard=GUARD_RATE_RULES,
         guard_rules=list(PRODUCTION_RATE_RULES),
         guard_note=("the pilot value_range contract itself detected 0 of 8 known cases in the back-test; D07 "
                     "cannot distinguish a portfolio shift from a change of meaning; rate problems that no "
                     "production rule flags remain unguarded")),
)
# Owner ruling 3 (2026-10-04): identity rows do not satisfy the inception gate ("CIK equals CIK" says nothing
# about meaning). A breach on one is still a breach.
IDENTITY_PROFILE_KEYS = frozenset({"fund_level_concepts.entity_cik", "fund_level_concepts.entity_registrant_name"})
MIN_SUBSTANTIVE_COMPARED_ROWS = 1
# Hook for a later owner ruling (a minimum share of a filer's counterpart keys that must be substantively
# compared). NOT implemented: None means no share threshold. Do not set it without implementing the rule in
# meets_substantive_minimum(), which refuses a non-None value rather than silently ignoring it.
MIN_SUBSTANTIVE_COMPARED_SHARE = None
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
                             "parity ok; zero breaches; no filer with verdict insufficient_evidence; every filer "
                             "has at least %d SUBSTANTIVE compared row(s) (identity rows -- entity CIK, registrant "
                             "name -- do not count; owner ruling 3, 2026-10-04; no minimum share yet); no missing "
                             "filer. The CLI exit code follows this field. A stub counts as an answer: this is "
                             "not the spec exit test." % MIN_SUBSTANTIVE_COMPARED_ROWS)


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


def substantive(contract: dict) -> dict:
    """Ruling 3: compared rows (holds + breach) split into identity rows and substantive rows, from the key
    rows themselves (so a hand-built contract is counted the same way as a real one)."""
    compared = [r for r in contract["keys"] if r["status"] in ("holds", "breach")]
    real = [r for r in compared if r.get("profile_key") not in IDENTITY_PROFILE_KEYS]
    return dict(compared_total=len(compared), compared_substantive=len(real),
                substantive_keys_compared=[r["pointer"] for r in real],
                identity_keys_compared=[r["pointer"] for r in compared
                                        if r.get("profile_key") in IDENTITY_PROFILE_KEYS])


def meets_substantive_minimum(compared_substantive: int) -> bool:
    if MIN_SUBSTANTIVE_COMPARED_SHARE is not None:
        raise NotImplementedError("MIN_SUBSTANTIVE_COMPARED_SHARE is a hook for a later owner ruling; the "
                                  "minimum-share rule is not implemented")
    return compared_substantive >= MIN_SUBSTANTIVE_COMPARED_ROWS


def _totals_guard_status(document: dict) -> str:
    """The independent_totals guard's own state for this filer: the owner-tolerance outcome recorded in the
    published_basis admission witness (within_tolerance | outside_tolerance | no_residual | no_outcome)."""
    ref = (document.get("partition_predicate") or {}).get("published_basis_entry_id")
    witness = ((document.get("admissions") or {}).get(ref) or {}).get("witness") or {}
    return (witness.get("owner_tolerance") or {}).get("outcome") or "not_recorded"


def procedure_keys(document: dict, content) -> list:
    """Ruling 1: the wrapper keys classified as procedure, outside the contract, each with its named guard.
    `content` is the live wrapper block's content, or None when there is no single live block."""
    out = []
    for spec in PROCEDURE_KEYS_OUTSIDE_CONTRACT:
        present, wvalue = (None, None) if content is None else _get(content, spec["wrapper_path"])
        row = dict(pointer=pointer(spec["wrapper_path"]), classification="procedure", guard=spec["guard"],
                   guard_note=spec["guard_note"], wrapper_present=present,
                   wrapper_value=wvalue if present else None)
        if spec["guard"] == GUARD_TOTALS:
            row["guard_status_at_report_date"] = _totals_guard_status(document)
        else:
            # Named, not evaluated: this module does not read the production rules' output for the filer.
            row.update(guard_rules=list(spec["guard_rules"]), guard_evaluated_here=False)
        out.append(row)
    return out


def consistency_contract(document: dict, *, report_date: str, code_mirror=()) -> dict:
    blocks = [b for b in document["wrapper_section"]["blocks"]
              if b["family"] == "bdc_xbrl_wrapper" and b["recorded_until"] is None]
    base = dict(cik=document["cik"], report_date=report_date, evaluated_dates=[report_date])
    if len(blocks) != 1:
        empty = dict(base, block_id=None, unevaluated=None, keys=[], counts={s: 0 for s in STATUSES},
                     verdict="insufficient_evidence",
                     procedure_keys_outside_contract=procedure_keys(document, None))
        return dict(empty, **substantive(empty))
    block = blocks[0]
    out_rows = []
    for spec in COUNTERPARTS:
        ptr = pointer(spec["wrapper_path"])
        present, wvalue = _get(block["content"], spec["wrapper_path"])
        res = pd.resolve(document, spec["profile_key"], report_date)
        row = dict(pointer=ptr, profile_key=spec["profile_key"], mode=COMPARE_MODE.get(ptr, "representation"),
                   identity=spec["profile_key"] in IDENTITY_PROFILE_KEYS, resolution=res["status"], entry_id=(res.get("entry") or {}).get("entry_id"),
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
    mirror = sorted(str(v) for v in code_mirror)
    res = pd.resolve(document, "partition_structure.reporting_entities", report_date)
    if res["status"] == "resolved":
        status = "holds" if sorted(map(str, res["entry"]["value"])) == mirror else "breach"
        reason = None if status == "holds" else "code mirror differs from the entry"
    else:
        status = "breach" if mirror else "not_applicable"
        reason = "code mirror carries per-filer knowledge with no accepted entry" if mirror else "no list anywhere"
    out_rows.append(dict(pointer=CODE_MIRROR_POINTER, profile_key="partition_structure.reporting_entities",
                         mode="exact_set", identity=False, resolution=res["status"],
                         entry_id=(res.get("entry") or {}).get("entry_id"),
                         stub_cause=(res.get("stub") or {}).get("cause"), status=status, reason=reason,
                         code_value=mirror))
    counts = {s: sum(r["status"] == s for r in out_rows) for s in STATUSES}
    out = dict(base, block_id=block["block_id"],
               unevaluated=dict(block_valid=[block["valid_from"], block["valid_to"]],
                                reason="inception entries start at " + report_date
                                       + "; other report dates of the block are not evaluated in sub-project 3"),
               keys=out_rows, counts=counts, verdict=_verdict(counts),
               procedure_keys_outside_contract=procedure_keys(document, block["content"]))
    return dict(out, **substantive(out))


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
        # `consistency` is the per-filer GATE criterion: a zero-breach outcome with at least one SUBSTANTIVE
        # compared row (ruling 3). "insufficient_evidence" (zero rows compared, or no live wrapper block)
        # fails it (C1); so does a filer whose only compared rows are identity rows.
        sub = substantive(con)
        sub_ok = meets_substantive_minimum(sub["compared_substantive"])
        per[cik] = dict(criterion_1=cov["ok"], resolver=res["ok"],
                        consistency=con["verdict"] in ("holds", "no_breach") and sub_ok,
                        substantive_comparison=sub_ok, compared_total=sub["compared_total"],
                        compared_substantive=sub["compared_substantive"],
                        substantive_keys_compared=sub["substantive_keys_compared"],
                        identity_keys_compared=sub["identity_keys_compared"],
                        procedure_keys_outside_contract=con.get("procedure_keys_outside_contract", []),
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
    # Ruling 3: compared, zero breaches, but nothing substantive (identity rows only). A zero-comparison filer
    # is already named by consistency_insufficient_evidence and a breaching one by consistency_breach.
    thin = where(lambda p: p["consistency_verdict"] in ("holds", "no_breach") and not p["substantive_comparison"])
    no_substantive = [dict(code="consistency_no_substantive_comparison", ciks=thin)] if thin else []
    gate_reasons += no_substantive
    not_holds = {cik: v for cik, v in verdicts.items() if v != "holds"}
    # spec_exit is never weaker than the gate: an all-identity "holds" does not meet it either.
    spec_reasons = list(structural) + no_substantive
    if not_holds:
        spec_reasons.append(dict(code="consistency_not_holds", ciks=sorted(not_holds), verdicts=not_holds,
                                 verdict_counts=verdict_counts))
    inception_gate, spec_ok = not gate_reasons, not spec_reasons
    compared = sum(p["consistency_rows"]["compared"] for p in per.values())
    total = sum(p["consistency_rows"]["total"] for p in per.values())
    compared_substantive = sum(p["compared_substantive"] for p in per.values())
    if spec_ok:
        statement = EXIT_TEST_TEXT
    else:
        statement = ("NOT MET: consistency verdict is holds for %d of %d filers (no_breach %d, breach %d, "
                     "insufficient_evidence %d; %d of %d key rows compared, %d of them substantive); reasons: %s"
                     % (verdict_counts["holds"], len(per), verdict_counts["no_breach"], verdict_counts["breach"],
                        verdict_counts["insufficient_evidence"], compared, total, compared_substantive,
                        ", ".join(r["code"] for r in spec_reasons)))
    return dict(report_date=report_date, verdict="PASS" if inception_gate else "FAIL",
                inception_gate=inception_gate, inception_gate_reasons=gate_reasons,
                inception_gate_definition=INCEPTION_GATE_DEFINITION,
                spec_exit=spec_ok, spec_exit_reasons=spec_reasons, spec_exit_reference=SPEC_EXIT_REFERENCE,
                spec_exit_statement=statement, consistency_verdict_counts=verdict_counts,
                consistency_rows=dict(compared=compared, compared_substantive=compared_substantive, total=total),
                identity_profile_keys=sorted(IDENTITY_PROFILE_KEYS),
                substantive_minimum=dict(rows=MIN_SUBSTANTIVE_COMPARED_ROWS, share=MIN_SUBSTANTIVE_COMPARED_SHARE),
                procedure_keys_outside_contract=[
                    {k: v for k, v in dict(pointer=pointer(s["wrapper_path"]), guard=s["guard"],
                                           guard_rules=s.get("guard_rules"), guard_note=s["guard_note"]).items()
                     if v is not None} for s in PROCEDURE_KEYS_OUTSIDE_CONTRACT],
                precondition_roundtrip=roundtrip_ok, missing_filers=missing, n_filers=len(per), per_cik=per,
                sample_label="IN-SAMPLE")
