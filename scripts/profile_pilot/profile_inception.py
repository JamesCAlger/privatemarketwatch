"""SP3 proper: inception converter -- existing override files and the Q4-2025 census -> profile document v1.

Pure (no file access); the CLI (profile_document_run) reads the files and passes their parsed content. Spec 4
inception: the override file's value becomes the entry value, its citations the evidence, its content hash the
pre-image; a filer with no file on an axis gets a census-derived entry or an insufficient-evidence stub.
Dispositions (spec 7.1, plan decisions P1-P11): knowledge files -> entries (rate_convention, grammars, anchors) or
one-off corrections (B2, aggregate rows, oracle exceptions); executable files -> wrapper blocks (wrapper,
agent_investigate_rules). Key order inside override content is preserved everywhere (prefix_rules is first-match).

wrapper_block hashing: `content_sha256` and each source file's `ordered_sha256` are both `translate.value_sha256`
(order-preserving JSON serialisation, ensure_ascii, compact separators) of the parsed content -- the same hash
Task 7's round trip recomputes from the materialised override file to verify a block reproduces its source
byte-for-byte after canonical serialisation. The source file's raw-bytes `sha256` is carried separately (as given
by the caller) and is never recomputed here.
"""
from __future__ import annotations

import copy
import re

from scripts.profile_pilot import envelope, profile
from scripts.profile_pilot import profile_document as pd
from scripts.profile_pilot.profile_families import REPO_PREFIX, cik10
from scripts.profile_pilot.translate import _get, pointer, value_sha256

SIGNOFF_TAGS = ("signoff-2025-12-31", "signoff-2026-03-31")
PRE_IMAGE_REASON = ("criterion 5 pre-image check (row_id present, pre-image unchanged) runs on the rebuilt quarter "
                    "in sub-project 6")
SHARED_MECHANISM = {"bdc_aggregate_row_overrides.json": ("aggregate_row", "aggregate_row_exclusion"),
                    "bdc_xbrl_oracle_exceptions.json": ("oracle_exception", "reconciliation_scope_exception")}
_ROW_ID_SQL = re.compile(r"\brow_id\s+IN\s*\(", re.IGNORECASE)


class InceptionError(ValueError):
    """The override inputs cannot be converted without guessing."""


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def rule_expressibility(rule: dict) -> dict:
    """Fix round 1, item 15 (deferred, out of scope for this round): a list-shaped rule `content` or
    `template` (as opposed to the B2 list-shaped `row_selector` hardened in the prior round) still
    raises AttributeError here (e.g. `.get("quarters")` on a list) rather than InceptionError. No
    pilot filer's `agent_investigate_rules` file has that shape today.
    """
    quarters = (rule.get("scope") or {}).get("quarters") or []
    if (rule.get("rule_type") == "row_exclusion" and _ROW_ID_SQL.search(rule.get("predicate_sql") or "")
            and len(quarters) == 1):
        return dict(expressible_as="one_off_correction",
                    reason="row_id-keyed exclusion scoped to one quarter (spec 4.2); conversion is sub-project 6")
    return dict(expressible_as=None, reason="executable rule_type " + repr(rule.get("rule_type"))
                + " stays in the wrapper section (spec 7.1)")


def wrapper_block(cik, *, family, files, recorded_at, attested_under) -> dict:
    files = sorted(files, key=lambda x: x["path"])
    if family == "bdc_xbrl_wrapper":
        if len(files) != 1:
            raise InceptionError("exactly one wrapper file per filer: " + repr([x["path"] for x in files]))
        content = copy.deepcopy(files[0]["content"])
        if cik10(content.get("cik")) != cik:
            raise InceptionError("wrapper cik " + repr(content.get("cik")) + " is not " + cik)
        expressibility = None
    elif family == "agent_investigate_rules":
        for x in files:
            if cik10(x["content"].get("cik")) != cik:
                raise InceptionError("rule cik " + repr(x["content"].get("cik")) + " is not " + cik + ": "
                                     + x["path"])
        content = {"files": {x["path"]: copy.deepcopy(x["content"]) for x in files}}
        expressibility = {x["path"]: rule_expressibility(x["content"]) for x in files}
    else:
        raise InceptionError("unknown block family " + repr(family))
    sources = [dict(path=x["path"], sha256=x["sha256"], ordered_sha256=value_sha256(x["content"])) for x in files]
    evidence = [dict(kind="override_file", path=REPO_PREFIX + s["path"], sha256=s["sha256"],
                     ordered_sha256=s["ordered_sha256"]) for s in sources]
    evidence.append(dict(kind="attestation", tags=sorted(attested_under),
                         rule="tag lists the sign-off tags whose blob parses order-identical to the file read"))
    return dict(block_id=cik + ":wrapper:" + family + ":v1", family=family, version=1, content=content,
                content_sha256=value_sha256(content), source_files=sources, valid_from=None, valid_to=None,
                recorded_at=recorded_at, recorded_until=None, supersedes=None, supersession_kind=None,
                attested_under=sorted(attested_under), evidence=evidence, expressibility=expressibility)


def _b2_dates(leaf: dict) -> list:
    template = leaf.get("template") or {}
    selector = template.get("row_selector") or {}
    dates = set((leaf.get("scope") or {}).get("quarters") or [])
    for value in (template.get("report_date"), selector.get("report_date")):
        if value:
            dates.add(value)
    return sorted(dates)


def _correction(cik, n, tag, *, family, mechanism, fix_class, dates, target, row_keyed, value, source,
                recorded_at, run_id, author) -> dict:
    one_off = len(dates) == 1
    kind = "one_off" if one_off else ("multi_quarter" if dates else "undated")
    day = dates[0] if one_off else None
    return dict(correction_id="%s:corr:%s:%03d" % (cik, tag, n), kind=kind, family=family, mechanism=mechanism,
                fix_class=fix_class, report_date=day, valid_from=day, valid_to=day, report_dates=list(dates),
                target=target, row_keyed=row_keyed, value=copy.deepcopy(value), source=source,
                pre_image=dict(status="unchecked", reason=PRE_IMAGE_REASON), recurrence_group=None, promotion=None,
                state="accepted" if one_off else "candidate",
                admission_basis="inherited_production" if one_off else "not_one_off_at_inception",
                confidence=_number(value.get("confidence")),
                provenance=dict(who=pd.CONVERTER_VERSION, source_author=str(value.get("created_by") or author),
                                when=recorded_at, run_id=run_id, source=REPO_PREFIX + source["path"]),
                recorded_at=recorded_at, recorded_until=None, supersedes=None)


def correction_records(cik, *, b2_files, shared, recorded_at, run_id) -> list[dict]:
    out = []
    for n, item in enumerate(sorted(b2_files, key=lambda x: x["path"]), 1):
        leaf = item["content"]
        if cik10(leaf.get("cik")) != cik:
            raise InceptionError("B2 leaf cik differs from its filer: " + item["path"])
        selector = (leaf.get("template") or {}).get("row_selector")
        if selector is not None and not isinstance(selector, dict):
            raise InceptionError("row_selector must be an object, not " + type(selector).__name__ + ": "
                                 + item["path"])
        dates = _b2_dates(leaf)
        out.append(_correction(cik, n, "b2", family="agent_b2_corrections", mechanism=leaf.get("mechanism"),
                               fix_class=leaf.get("fix_class"), dates=dates,
                               target=dict(selector) if selector else {"report_dates": dates},
                               row_keyed=bool(selector and selector.get("row_id")), value=leaf,
                               source=dict(path=item["path"], sha256=item["sha256"], record_index=None),
                               recorded_at=recorded_at, run_id=run_id, author="agent"))
    for name in sorted(shared):
        tag, mechanism = SHARED_MECHANISM[name]
        for n, (index, record) in enumerate(shared[name]["records"], 1):
            if cik10(record.get("cik")) != cik:
                raise InceptionError(name + " record " + str(index) + " belongs to another filer")
            if tag == "aggregate_row":
                target = {k: record.get(k) for k in ("report_date", "accession_number", "match_text", "match_mode")}
                fix = record.get("action")
            else:
                target = {"report_date": record.get("report_date"), "oracle_reason": record.get("oracle_reason")}
                fix = record.get("oracle_reason")
            day = record.get("report_date")
            out.append(_correction(cik, n, tag, family=name, mechanism=mechanism, fix_class=fix,
                                   dates=[day] if day else [], target=target, row_keyed=False, value=record,
                                   source=dict(path=name, sha256=shared[name]["sha256"], record_index=index),
                                   recorded_at=recorded_at, run_id=run_id, author="agent"))
    return mark_recurrence(out)


def _signature(c: dict) -> str:
    if c["family"] == "bdc_aggregate_row_overrides.json":
        return str(c["target"].get("match_text"))
    if c["family"] == "bdc_xbrl_oracle_exceptions.json":
        return str(c["target"].get("oracle_reason"))
    return str(c["fix_class"])


INHERITED_FAMILIES = {"rate_convention": ("meaning.interest_rate", "agent"),
                      "identifier_rate_grammars": ("identifier_format.dialect", "agent"),
                      "identifier_anchors": ("identifier_format.anchors", "agent")}
PREDICATE_CODE_PATH = "scripts/profile_pilot/census_published.py"
REPORTING_ENTITY_POINTER = ("source_encodings", "reporting_entity_suffixes")
NO_CONTRACT = "none_available: no contract kind for this axis has reported (sub-project 2)"
# Fix round 1 (Task 6 review item 7): headings are quoted exactly as they appear in the named checkout's
# file (verified by hand against that file, not re-checked at runtime) and the checkout is named so a
# later reader can tell a worktree-only entry (not yet in main) from one already in main. The scratch
# table path is dropped (scratch is disposable); the worktree changelog entry is the durable citation.
PREDICATE_VERSION_DESCRIBED = "census-published.v2"
ADOPTION_EVIDENCE = (
    dict(kind="adoption_record", changelog="docs/agent_changelog.md", checkout="worktree",
         heading="2026-10-01 -- SP3 Task 0b: census published-basis predicate v2 (hierarchical rollups) adopted",
         commits=["2132a31", "8418644", "b2454c9", "c7a627f"],
         rule="anchor-aware adoption rule (controller rulings 3-4): 111 docs, 101 measured fund-quarters, "
              "31 improved, 0 worsened, 0 violations (IN-SAMPLE)"),
    dict(kind="owner_ruling", changelog="docs/agent_changelog.md", checkout="main",
         heading="2026-09-30 -- Published basis excludes underlying-schedule rows (owner ruling): "
                 "implementation and measurement"))
# A10 (pre-flight ruling): the Stage B census cannot derive non_private_markers or prefix_rules (no detector
# produces them), so they are excluded even though their section (subtotals_and_headings) is otherwise
# census-derivable. Leaving them in would make an unavailable census wrongly "blamed" for their absence
# (grid_stubs would stub them census_unavailable instead of no_source).
CENSUS_KEYS = frozenset(k for k in pd.GRID_KEYS
                        if k.split(".", 1)[0] in ("column_contract", "subtotals_and_headings", "fund_level_concepts")
                        and k not in ("subtotals_and_headings.non_private_markers",
                                      "subtotals_and_headings.prefix_rules")
                        ) | {"identifier_format.delimiter"}
CLOSING_EVIDENCE = {
    "column_contract": "a complete-collection census of this report date deriving the field's carrying concepts",
    "scale_unit": "the declared unit on the census unit channel, or a reconciling independent total "
                  "(spec 6 scale witness)",
    "meaning": "an adjudicated rate-convention verdict with an income-reconciliation witness (spec 6; D-convention)",
    "identifier_format": "a resolved partition-detector outcome on the census, or an Agent A grammar/anchor file",
    "subtotals_and_headings": "a resolved subtotal-detector outcome on the census",
    "fund_level_concepts": "single DEI or fund-total facts at the document period end in the census",
    "partition_structure": "a wrapper source_encodings list or a LegalEntityAxis observation naming the filer's "
                           "reporting entities",
    "income_proofs": "the income-proof step entries of the redesigned income-yield kind (spec 5), each with its "
                     "contract",
}


# Final whole-branch review I3: partition_structure.published_basis is `accepted` only where the filer's
# independent-totals contract (fair_value: census published-basis FV sum vs the filed
# investments_at_fair_value anchor) holds at the inception report date under the SAME predicate version.
# "The predicate was adopted" says which version is in force; it does not say this filer reconciles on it.
# The outcome is READ from a pinned artifact (the back-test of the v2 re-measure chain, which evaluates the
# totals contracts at every census quarter including 2025-12-31), never recomputed here.
TOTALS_KIND, TOTALS_GATE_FIELD = "independent_totals", "fair_value"
TOTALS_OUTCOMES = ("holds", "breach", "insufficient_evidence", "none")
NO_TOTALS_OUTCOME = "no_totals_outcome_at_inception"
TOTALS_CANDIDATE_CAUSE = {"breach": "totals_breach_at_inception",
                          "insufficient_evidence": "totals_insufficient_evidence_at_inception",
                          "none": NO_TOTALS_OUTCOME}
TOTALS_RULE = ("holds only if at least one independent_totals fair_value result is evaluated at the report date "
               "and EVERY such result (all learn modes) is holds; any breach is breach; otherwise "
               "insufficient_evidence; no result at the date is none. The pct_of_net_assets contract is recorded "
               "in other_fields and does not gate (its [50, 250] band assumes percent units; open item).")
# Owner ruling 2 of 2026-10-04: partition_structure.published_basis is ACCEPTED only where the filer's
# fair-value totals residual at the inception date is within +/-0.5% (absolute value <= 0.5) in every learn
# mode that has a result, regardless of the totals contract's own 5% / 10% band. Outside it, or with no
# outcome, the entry is a candidate and the discrepancy is routed to B1/B2 review. This is the ONE place
# the 0.5 lives; profile_consistency reads it for the cash_identifiers guard note.
PUBLISHED_BASIS_FV_TOLERANCE_PCT = 0.5
TOLERANCE_BASIS = ("owner ruling 2026-10-04 (ruling 2): accepted only where the absolute fair-value totals "
                   "residual at the inception date is <= the band in every learn mode with a result, regardless "
                   "of the totals contract's own band")
TOLERANCE_OUTCOMES = ("within_tolerance", "outside_tolerance", "no_residual", "no_outcome")
NOT_RECORDED = "not_recorded_in_pinned_file"
OUTSIDE_TOLERANCE_CAUSE = "totals_outside_owner_tolerance_at_inception"
NO_RESIDUAL_CAUSE = "totals_no_residual_at_inception"
REVIEW_ROUTE = "B1/B2 review item (fair-value reconciliation flag)"


def totals_outcome(results: dict, cik: str, *, report_date: str, predicate_version: str) -> dict:
    """The filer's independent-totals outcome at `report_date`, read from pinned back-test results.

    `results` is the `results` object of m2_backtest's results/backtest_results.json: pair id
    "<mode>:<cik>:<learn_date>:<eval_date>" -> list of contract results. Pure; no file access. A totals
    result evaluated under another census published version is refused, not skipped."""
    cik = cik10(cik)
    rows, other = [], []
    for pair_id in sorted(results):
        parts = str(pair_id).split(":")
        if len(parts) != 4:
            raise InceptionError("totals results: unrecognised pair id " + repr(pair_id))
        mode, pair_cik, learn_date, eval_date = parts
        if cik10(pair_cik) != cik or eval_date != report_date:
            continue
        for r in results[pair_id]:
            if r.get("kind") != TOTALS_KIND:
                continue
            version = (r.get("applies_to") or {}).get("census_published")
            if version != predicate_version:
                raise InceptionError("totals result " + pair_id + " was evaluated under " + repr(version)
                                     + ", not " + predicate_version)
            observed = r.get("observed") or {}
            item = dict(pair_id=pair_id, mode=mode, learn_date=learn_date, field=r.get("field"),
                        status=r.get("status"), cause=r.get("cause"),
                        fv_residual_pct=observed.get("fv_residual_pct"), fv_anchor=observed.get("fv_anchor"),
                        fv_sum=observed.get("fv_sum"), pct_sum=observed.get("pct_sum"),
                        # Ruling 2: the contract's own band / tier, if the pinned row carries them (the
                        # back-test rows of record do not; that is recorded, not guessed).
                        contract_band=r["band"] if r.get("band") is not None else NOT_RECORDED,
                        contract_tier=r["tier"] if r.get("tier") is not None else NOT_RECORDED)
            (rows if r.get("field") == TOTALS_GATE_FIELD else other).append(item)
    statuses = [r["status"] for r in rows]
    if not rows:
        outcome = "none"
    elif "breach" in statuses:
        outcome = "breach"
    elif all(s == "holds" for s in statuses):
        outcome = "holds"
    else:
        outcome = "insufficient_evidence"
    return dict(outcome=outcome, cause=TOTALS_CANDIDATE_CAUSE.get(outcome), kind=TOTALS_KIND,
                field=TOTALS_GATE_FIELD, report_date=report_date, predicate_version=predicate_version,
                rule=TOTALS_RULE, rows=rows, other_fields=other)


def published_basis_tolerance(totals: dict) -> dict:
    """Owner ruling 2 (2026-10-04): the fair-value residual of every totals row at the inception date against
    the +/-PUBLISHED_BASIS_FV_TOLERANCE_PCT band. Pure; reads only the rows totals_outcome() already kept.

    outcome: no_outcome (no row at the date), no_residual (a row without a numeric residual, e.g. an
    abstention), outside_tolerance (any row's absolute residual above the band), within_tolerance (every
    row inside it)."""
    band = PUBLISHED_BASIS_FV_TOLERANCE_PCT
    residuals = []
    for r in totals.get("rows") or []:
        value = _number(r.get("fv_residual_pct"))
        residuals.append(dict(mode=r.get("mode"), learn_date=r.get("learn_date"), fv_residual_pct=value,
                              within=value is not None and abs(value) <= band,
                              contract_status=r.get("status"),
                              contract_band=r.get("contract_band", NOT_RECORDED),
                              contract_tier=r.get("contract_tier", NOT_RECORDED)))
    if not residuals:
        outcome = "no_outcome"
    elif any(r["fv_residual_pct"] is None for r in residuals):
        outcome = "no_residual"
    elif all(r["within"] for r in residuals):
        outcome = "within_tolerance"
    else:
        outcome = "outside_tolerance"
    return dict(band_pct=band, basis=TOLERANCE_BASIS, outcome=outcome, residuals=residuals, route=REVIEW_ROUTE)


def published_basis_candidate_cause(totals: dict, tolerance: dict):
    """None when published_basis is accepted: the totals contract holds AND the residual is inside the owner
    tolerance in every mode. The contract outcome is kept as a condition (a breach or an abstention is never
    accepted on a small residual alone); the tolerance is the additional, stricter one."""
    if totals["outcome"] != "holds":
        return TOTALS_CANDIDATE_CAUSE[totals["outcome"]]
    if tolerance["outcome"] == "within_tolerance":
        return None
    return NO_RESIDUAL_CAUSE if tolerance["outcome"] == "no_residual" else OUTSIDE_TOLERANCE_CAUSE


def _checked_totals(cik, totals, pred) -> dict:
    if not isinstance(totals, dict) or totals.get("outcome") not in TOTALS_OUTCOMES:
        raise InceptionError("no pinned independent-totals outcome for " + cik + " (inputs['totals']): "
                             "published_basis cannot be admitted without one")
    source = totals.get("source")
    if not (isinstance(source, dict) and source.get("run_id") and source.get("sha256")):
        raise InceptionError("the totals outcome for " + cik + " names no pinned source (run_id, sha256)")
    if totals.get("predicate_version") != pred["version"] or totals.get("report_date") != pd.INCEPTION_REPORT_DATE:
        raise InceptionError("the totals outcome for " + cik + " is for "
                             + repr((totals.get("predicate_version"), totals.get("report_date"))) + ", not "
                             + repr((pred["version"], pd.INCEPTION_REPORT_DATE)))
    return totals


def _candidate_closing(entry: dict, admission: dict) -> tuple:
    """(closing evidence, stub detail) for a grid key whose only live entry is a candidate. F6 (final review):
    name what would actually close THIS candidate; "next-quarter confirmation" was printed for every cause,
    including ones a next-quarter census cannot close (it had already confirmed the value)."""
    eid, witness = entry["entry_id"], admission["witness"]
    tail = "; admission loop, sub-project 5"
    totals = witness.get("independent_totals")
    if totals is not None:
        cause = witness.get("candidate_cause")
        seen = "; ".join("%s %s%s" % (r["mode"], r["status"],
                                      "" if r["fv_residual_pct"] is None else " (%+.2f%%)" % r["fv_residual_pct"])
                         for r in totals["rows"]) or "no result evaluated at this date"
        # Owner ruling 2 (2026-10-04): name the band and the route. With no residual at the date there is no
        # measured discrepancy; the missing outcome is itself what goes to review.
        measured = bool(totals["rows"])
        route = ("route: the discrepancy is a " + REVIEW_ROUTE if measured else
                 "route: no residual could be computed at this date; the missing totals outcome is a "
                 + REVIEW_ROUTE)
        return ("an independent-totals " + totals["field"] + " contract outcome of holds for this filer at "
                + totals["report_date"] + " under " + totals["predicate_version"] + " with the fair-value "
                "residual within +/-" + str(PUBLISHED_BASIS_FV_TOLERANCE_PCT) + "% in every learn mode (owner "
                "ruling 2026-10-04) (inception: " + str(cause) + "; pinned run " + totals["source"]["run_id"]
                + ": " + seen + "); " + route + "; then admission of " + eid + tail,
                dict(independent_totals=cause))
    reason = witness.get("next_quarter", "not confirmed")
    detail = dict(next_quarter=reason)
    if reason == "open_census_outcomes":
        opened = witness.get("open_census_outcomes") or {}
        ids = ["%s %s (%s)" % (q, s["stub_id"], s["cause"]) for q in ("q4", "q1") for s in opened.get(q) or []]
        return ("resolution of the open census outcome(s) bearing on this key: " + ", ".join(ids) + "; "
                + eid + " stays a candidate until they are resolved, whatever the next quarter's value" + tail,
                detail)
    if reason == "q1_census_unavailable":
        return ("an authoritative next-quarter census for this filer whose value for this key equals " + eid
                + " (inception: " + reason + ")" + tail, detail)
    if reason in ("q1_value_differs", "q1_no_entry", "q1_ambiguous"):
        return ("adjudication of " + eid + " against the next-quarter census, which did not confirm it "
                "(inception: " + reason + "): which quarter's value is right, or whether the value changed"
                + tail, detail)
    return ("next-quarter confirmation of " + eid + " (inception: " + reason + ")" + tail, detail)


def file_evidence(rel, sha, content, *, value_is_file=True, pointer=None) -> list:
    item = dict(kind="override_file", path=REPO_PREFIX + rel, sha256=sha, ordered_sha256=value_sha256(content),
                value_is_file=value_is_file)
    if pointer is not None:
        item["pointer"] = pointer
    out = [item]
    if isinstance(content, dict):
        for k in ("citations", "evidence_citations", "evidence"):
            v = content.get(k)
            if isinstance(v, list) and v:
                out.append(dict(kind="source_citations", field=k, items=copy.deepcopy(v)))
        for k in ("target_quarter", "first_seen_quarter", "updated_at", "report_date"):
            if content.get(k):
                out.append(dict(kind="source_date", field=k, value=content[k]))
    return out


def _assert_inherited(events, cik, key, value, *, support_path, sha, evidence, author, recorded_at):
    before = {e["entry_id"] for e in envelope.materialize_entries(events)}
    events = envelope.make_assertion(
        events, cik=cik, key=key, value=copy.deepcopy(value), valid_from=None, recorded_at=recorded_at,
        support=dict(kind="inherited_file", path=support_path, sha256=sha), evidence=evidence,
        provenance="inherited", inherited_from=support_path + "@" + sha[:12], author=author, status="promoted")
    new = [e["entry_id"] for e in envelope.materialize_entries(events) if e["entry_id"] not in before]
    if len(new) != 1:
        raise InceptionError("expected one new entry for " + key + ", got " + repr(new))
    return events, new[0]


def census_entries(census, *, recorded_at):
    if census is None:
        return [], []
    derived = profile.derive_profile(census["doc"], source=census["source"], era=profile.INCEPTION_ERA,
                                     recorded_at=recorded_at, anchors=None)
    return list(derived["events"]), list(derived["packet_stubs"])


def _bearing_map(stubs) -> dict:
    out: dict = {}
    for s in stubs or []:
        for k in (s.get("bears_on") or []):
            out.setdefault(k, []).append({"stub_id": s["stub_id"], "cause": s["cause"]})
    return out


def confirmations(q4_entries, q1_census, *, census_stubs, recorded_at) -> dict:
    """entry_id -> dict(ok, reason, open).

    `open` is None unless unresolved census outcomes (packet stubs) bear on the key in Q4 or Q1
    (fix round 1, item 4, controller ruling): in that case the entry is forced to a candidate with
    reason "open_census_outcomes" regardless of what the Q1 value comparison would otherwise say,
    and `open` carries {"q4": [...], "q1": [...]}, each a list of {"stub_id", "cause"} for the
    bearing stubs of that quarter.
    """
    q4_bearing = _bearing_map(census_stubs)
    q1_entries_by_key: dict = {}
    q1_bearing: dict = {}
    if q1_census is not None:
        q1 = profile.derive_profile(q1_census["doc"], source=q1_census["source"], era=profile.INCEPTION_ERA,
                                    recorded_at=recorded_at, anchors=None)
        for e in q1["entries"]:
            q1_entries_by_key.setdefault(e["key"], []).append(e)
        q1_bearing = _bearing_map(q1["packet_stubs"])
    out = {}
    for e in q4_entries:
        open_q4, open_q1 = q4_bearing.get(e["key"]) or [], q1_bearing.get(e["key"]) or []
        if open_q4 or open_q1:
            out[e["entry_id"]] = dict(ok=False, reason="open_census_outcomes", open={"q4": open_q4, "q1": open_q1})
            continue
        if q1_census is None:
            out[e["entry_id"]] = dict(ok=False, reason="q1_census_unavailable", open=None)
            continue
        others = q1_entries_by_key.get(e["key"], [])
        if len(others) != 1:
            out[e["entry_id"]] = dict(ok=False, reason="q1_no_entry" if not others else "q1_ambiguous", open=None)
        elif (value_sha256(others[0]["value"]) == value_sha256(e["value"])
              and others[0]["applies_to"] == e["applies_to"]):
            out[e["entry_id"]] = dict(ok=True, reason="q1_value_equal", open=None)
        else:
            out[e["entry_id"]] = dict(ok=False, reason="q1_value_differs", open=None)
    return out


def _check_census_inputs(cik, census_q4, census_q1):
    """Fix round 1, item 2: census inputs are never checked against the filer or each other."""
    if census_q4 is not None:
        src = census_q4["source"]
        if cik10(src.get("cik")) != cik or src.get("report_date") != pd.INCEPTION_REPORT_DATE:
            raise InceptionError("census_q4 does not match filer " + cik + " at " + pd.INCEPTION_REPORT_DATE
                                 + ": " + repr((src.get("cik"), src.get("report_date"))))
    if census_q1 is not None:
        src = census_q1["source"]
        if cik10(src.get("cik")) != cik:
            raise InceptionError("census_q1 belongs to another filer: " + repr(src.get("cik")))
        # Compared with the inception date itself (census_q4, when present, is already pinned to it above),
        # so a Q1 census is date-checked even for a filer with no Q4 census. ISO dates order as strings.
        day = src.get("report_date")
        if not isinstance(day, str) or not day > pd.INCEPTION_REPORT_DATE:
            raise InceptionError("census_q1 report_date " + repr(day) + " is not later than the inception "
                                 "report date " + pd.INCEPTION_REPORT_DATE)


def grid_stubs(cik, entries, admissions, census_stubs, *, report_date, census_ran, census_unavailable) -> list:
    # Fix round 1, item 10: this duplicates profile_document._live's filter (recorded_until is None and
    # valid_at(report_date)) rather than importing it. _live is underscore-private to that module and
    # this review round is scoped to profile_inception.py only, so the duplication is left as-is and
    # flagged here rather than importing a private name across the module boundary.
    live = [e for e in entries if e["recorded_until"] is None and pd.valid_at(e, report_date)]
    stubs = []
    for key in pd.GRID_KEYS:
        mine = [e for e in live if e["key"] == key]
        if any(admissions[e["entry_id"]]["state"] == "accepted" for e in mine):
            continue
        section = key.split(".", 1)[0]
        if mine:
            first = mine[0]
            closing, detail = _candidate_closing(first, admissions[first["entry_id"]])
            stubs.append(pd.stub(cik, key, "candidate_pending_confirmation", closing, entry_id=first["entry_id"],
                                 detail=detail))
            continue
        bearing = [s for s in census_stubs if key in (s.get("bears_on") or [])]
        if bearing:
            first = bearing[0]
            question = first.get("question") or ("census detector " + str(first.get("detector")) + " outcome "
                                                 + str(first.get("cause")))
            # Fix round 1, item 12 (deferred): census_stub_ids names Stage B packet-stub ids from THIS
            # build's derive_profile() call. Those stubs are never persisted anywhere in the document
            # (only their ids and cause/finding are copied here), so once this build's in-memory
            # census_stubs list is gone the ids are not a durable cross-reference -- re-running the
            # census derivation is the only way to look one back up.
            stubs.append(pd.stub(cik, key, "census_stub", question,
                                 detail=dict(census_stub_ids=[s["stub_id"] for s in bearing],
                                             cause=first.get("cause"), finding=first.get("finding"))))
            continue
        if census_unavailable and key in CENSUS_KEYS:
            stubs.append(pd.stub(cik, key, "census_unavailable",
                                 "an authoritative " + report_date + " census for " + cik + " ("
                                 + census_unavailable["census_run_id"] + " excluded it: "
                                 + str(census_unavailable.get("detail") or census_unavailable.get("reason")) + ")",
                                 detail=dict(census_unavailable)))
            continue
        if census_ran and key in CENSUS_KEYS:
            # Fix round 1, item 5: a complete Q4 census ran and derived no observation (no entry, no
            # bearing packet stub) for this key -- there is no missing census to blame, so say so
            # instead of reusing the generic "a complete-collection census ... would close it" prose.
            stubs.append(pd.stub(cik, key, "no_source",
                                 "the " + report_date + " census ran to completion and collected no "
                                 "observation for this key (nothing in the current census to attribute; "
                                 "not a missing-census question)", detail={"census": "collected_no_observation"}))
            continue
        stubs.append(pd.stub(cik, key, "no_source", CLOSING_EVIDENCE[section]))
    return stubs


def build_document(cik: str, *, inputs: dict, recorded_at: str, run_id: str, git_head: str) -> dict:
    cik = cik10(cik)
    census_q4, census_q4_unavailable = inputs.get("census_q4"), inputs.get("census_q4_unavailable")
    census_q1 = inputs.get("census_q1")
    # Fix round 1, item 5: census_q4 and census_q4_unavailable describe the SAME fact (whether Stage B
    # produced an authoritative Q4 census for this filer) from two sides; exactly one must be set.
    if (census_q4 is None) == (census_q4_unavailable is None):
        raise InceptionError("exactly one of census_q4 and census_q4_unavailable must be set")
    _check_census_inputs(cik, census_q4, census_q1)
    pred = inputs["predicate"]
    if pred["version"] != PREDICATE_VERSION_DESCRIBED:
        raise InceptionError("predicate version " + repr(pred["version"]) + " does not match the adoption "
                             "evidence, which describes " + PREDICATE_VERSION_DESCRIBED)
    files = inputs["files"]
    events, census_stubs = census_entries(census_q4, recorded_at=recorded_at)
    admissions, targets = {}, {}
    q4_entries = envelope.materialize_entries(events)
    confirmed = confirmations(q4_entries, census_q1, census_stubs=census_stubs, recorded_at=recorded_at)
    for e in q4_entries:
        c = confirmed[e["entry_id"]]
        witness = {"next_quarter": c["reason"]}
        if c["open"] is not None:
            witness["open_census_outcomes"] = c["open"]
        admissions[e["entry_id"]] = pd.admission(
            "accepted" if c["ok"] else "candidate",
            "census_confirmed_next_quarter" if c["ok"] else "census_unconfirmed",
            source_kind="census", mechanism="census-derived (" + profile.PROFILE_VERSION + ")", confidence=None,
            source_author="census", recorded_at=recorded_at, run_id=run_id,
            source=census_q4["source"]["census_relative"], witness=witness,
            inception_evaluation="next_quarter_census_equality")
    for family in sorted(INHERITED_FAMILIES):
        found = files.get(family) or []
        if not found:
            continue
        if len(found) != 1:
            raise InceptionError("more than one " + family + " file for " + cik + ": "
                                 + repr([x["path"] for x in found]))
        key, author = INHERITED_FAMILIES[family]
        item, content = found[0], found[0]["content"]
        meta = content if isinstance(content, dict) else {}
        # Fix round 1, item 8: a knowledge file's own cik, when it carries one, must match the filer.
        if meta.get("cik") is not None and cik10(meta.get("cik")) != cik:
            raise InceptionError(family + " file cik " + repr(meta.get("cik")) + " is not " + cik + ": "
                                 + item["path"])
        events, eid = _assert_inherited(events, cik, key, content, support_path=REPO_PREFIX + item["path"],
                                        sha=item["sha256"], evidence=file_evidence(item["path"], item["sha256"], content),
                                        author=author, recorded_at=recorded_at)
        witness = {}
        if family == "rate_convention":
            # Fix round 1, item 13: carry the adjudicated reconciliation witness through, when present.
            for wk in ("verify_tier", "verify_n_reconciled"):
                if wk in meta:
                    witness[wk] = meta[wk]
        admissions[eid] = pd.admission(
            "accepted", "inherited_production", source_kind="override_file", mechanism=family + " override file",
            # Fix round 1, item 1: pass the raw confidence through -- a qualitative value ("high")
            # must reach pd.admission() unfiltered so it lands in witness.confidence_raw, not be
            # silently turned into None by _number() before admission() ever sees it.
            confidence=meta.get("confidence"), source_author=str(meta.get("created_by") or author),
            recorded_at=recorded_at, run_id=run_id, source=REPO_PREFIX + item["path"], witness=witness,
            inception_evaluation=NO_CONTRACT)
        targets.setdefault(item["path"], []).append(eid)
    # Final review I3: accepted only where this filer's pinned independent-totals outcome holds at the
    # inception date; otherwise a candidate carrying the outcome (or its absence) in the witness.
    # Owner ruling 2 (2026-10-04): and only where the residual is within +/-0.5% in every learn mode.
    totals = _checked_totals(cik, inputs.get("totals"), pred)
    tolerance = published_basis_tolerance(totals)
    basis_cause = published_basis_candidate_cause(totals, tolerance)
    totals_holds = basis_cause is None
    events, basis_id = _assert_inherited(
        events, cik, "partition_structure.published_basis", {"predicate": pred["version"]},
        support_path=PREDICATE_CODE_PATH, sha=pred["code_sha256"],
        evidence=[dict(kind="code_file", path=PREDICATE_CODE_PATH, sha256=pred["code_sha256"])]
        + [dict(e) for e in ADOPTION_EVIDENCE]
        + [dict(kind="contract_results", contract_kind=TOTALS_KIND, field=TOTALS_GATE_FIELD,
                report_date=totals["report_date"], outcome=totals["outcome"], **totals["source"])],
        author="human", recorded_at=recorded_at)
    basis_witness = {"adoption": "anchor-aware adoption rule, controller rulings 3-4",
                     "independent_totals": copy.deepcopy(totals),
                     "owner_tolerance": tolerance}
    if not totals_holds:
        basis_witness["candidate_cause"] = basis_cause
    admissions[basis_id] = pd.admission(
        "accepted" if totals_holds else "candidate", "adopted_predicate", source_kind="predicate_code",
        mechanism="census published-basis predicate " + pred["version"], confidence=None, source_author="human",
        recorded_at=recorded_at, run_id=run_id, source=PREDICATE_CODE_PATH, witness=basis_witness,
        inception_evaluation="adoption rule over 101 fund-quarters of the 8 filers (IN-SAMPLE); this filer's "
                             "independent_totals " + TOTALS_GATE_FIELD + " outcome at " + totals["report_date"]
                             + " (pinned run " + totals["source"]["run_id"] + "): " + totals["outcome"]
                             + "; owner tolerance +/-" + str(PUBLISHED_BASIS_FV_TOLERANCE_PCT)
                             + "% (ruling 2026-10-04): " + tolerance["outcome"])
    entities_id = None
    wrappers = files.get("bdc_xbrl_wrappers") or []
    if wrappers:
        w = wrappers[0]
        present, suffixes = _get(w["content"], REPORTING_ENTITY_POINTER)
        if present:
            # Fix round 1, item 11: the wrapper's own schema does not constrain this field's shape.
            if not (isinstance(suffixes, list) and all(isinstance(s, str) for s in suffixes)):
                raise InceptionError("source_encodings.reporting_entity_suffixes must be a list of strings: "
                                     + repr(suffixes))
            evidence = file_evidence(w["path"], w["sha256"], w["content"], value_is_file=False,
                                     pointer=pointer(REPORTING_ENTITY_POINTER))
            evidence.append(dict(kind="investigation", path="docs/investigations/conservation_shadow_engine.md",
                                 checkout="main",
                                 heading="2026-10-01 - Census-side published basis: a 7-rule predicate "
                                         "reconciles all 8 pilot filers within 0.5%",
                                 note="R6: mark reporting-entity look-through rows as underlying by "
                                      "typed-identifier suffix, since no LegalEntityAxis member exists in "
                                      "the census"))
            events, entities_id = _assert_inherited(events, cik, "partition_structure.reporting_entities",
                                                    list(suffixes), support_path=REPO_PREFIX + w["path"],
                                                    sha=w["sha256"], evidence=evidence, author="human",
                                                    recorded_at=recorded_at)
            admissions[entities_id] = pd.admission(
                "accepted", "inherited_production", source_kind="override_file",
                mechanism="wrapper source_encodings.reporting_entity_suffixes", confidence=None, source_author="human",
                recorded_at=recorded_at, run_id=run_id, source=REPO_PREFIX + w["path"], witness={},
                inception_evaluation="consistency contract vs wrapper and the census_published code mirror")
            targets.setdefault(w["path"], []).append(entities_id)
    entries = envelope.materialize_entries(events)
    live_keys = [e["key"] for e in entries if e["recorded_until"] is None]
    dup = sorted({k for k in live_keys if live_keys.count(k) > 1})
    if dup:
        raise InceptionError("two inception entries for one key: " + repr(dup))
    blocks = []
    for family, block_family in (("bdc_xbrl_wrappers", "bdc_xbrl_wrapper"),
                                 ("agent_investigate_rules", "agent_investigate_rules")):
        found = files.get(family) or []
        if not found:
            continue
        tags = sorted({t for x in found for t in (inputs.get("attested_under") or {}).get(x["path"], [])})
        block = wrapper_block(cik, family=block_family, files=found, recorded_at=recorded_at, attested_under=tags)
        blocks.append(block)
        for x in found:
            targets.setdefault(x["path"], []).append(block["block_id"])
    corrections = correction_records(cik, b2_files=files.get("agent_b2_corrections") or [],
                                     shared=inputs.get("shared") or {}, recorded_at=recorded_at, run_id=run_id)
    for c in corrections:
        targets.setdefault(c["source"]["path"], []).append(c["correction_id"])
    disposition = []
    for d in inputs["disposition"]:
        d = dict(d, targets=list(targets.get(d["path"], [])))
        if d["action"] in ("entry", "wrapper_block", "correction") and not d["targets"]:
            raise InceptionError("converted file produced nothing: " + d["path"])
        disposition.append(d)
    stubs = grid_stubs(cik, entries, admissions, census_stubs, report_date=pd.INCEPTION_REPORT_DATE,
                       census_ran=census_q4 is not None, census_unavailable=census_q4_unavailable)
    detection = {k: dict(claim="claimed" if v["verdict"] == "PASS" else "detection_not_claimed",
                         verdict=v["verdict"], replay_run_id=v["replay_run_id"])
                 for k, v in sorted((inputs.get("detection") or {}).items())}
    doc = dict(
        schema=pd.SCHEMA_NAME, schema_version=1, document_version=1, cik=cik,
        inception_report_date=pd.INCEPTION_REPORT_DATE, recorded_at=recorded_at, run_id=run_id,
        code=dict(git_head=git_head, converter_version=pd.CONVERTER_VERSION),
        events=events, entries=entries, admissions=admissions, stubs=stubs,
        wrapper_section=dict(blocks=blocks), corrections=corrections,
        partition_predicate=dict(census_published_version=pred["version"], published_basis_entry_id=basis_id,
                                 reporting_entities_entry_id=entities_id,
                                 code_mirror=dict(path=PREDICATE_CODE_PATH, constant="REPORTING_ENTITIES",
                                                  value=list(inputs.get("code_mirror") or []))),
        detection_claims=detection, disposition=disposition,
        ledger=[dict(event="document_created", at=recorded_at, run_id=run_id, detail=dict(
            converter_version=pd.CONVERTER_VERSION,
            census_q4=census_q4["source"]["census_relative"] if census_q4 else None,
            census_q1=census_q1["source"]["census_relative"] if census_q1 else None,
            census_q4_unavailable=census_q4_unavailable,
            overrides_root=inputs.get("overrides_root"), replay_run_id=inputs.get("replay_run_id"),
            # Fix round 1, item 9 (ruling P5): the MAIN checkout head inception actually read, distinct
            # from `code.git_head` (this worktree's HEAD, the converter code version).
            overrides_git_head=inputs.get("overrides_git_head")))])
    pd.validate_document(doc)
    return doc


def mark_recurrence(corrections: list[dict]) -> list[dict]:
    """Group one-off corrections by (family, mechanism, signature); flag groups spanning >= 2 report dates.

    Known limitation: for B2 corrections the signature is `fix_class` alone. Two genuinely unrelated
    one-off fixes that happen to share a fix_class (on different rows, different quarters) are grouped
    into one recurrence_group and flagged proposed_recurring_owner_tier. Nothing here promotes them;
    owner sign-off (SP6) must check target/row overlap before treating the group as a real recurrence.
    """
    groups: dict = {}
    for c in corrections:
        if c["kind"] == "one_off":
            groups.setdefault((c["family"], c["mechanism"], _signature(c)), []).append(c)
    for key, members in groups.items():
        if len({m["report_date"] for m in members}) >= 2:
            gid = members[0]["correction_id"].split(":corr:")[0] + ":recur:" + value_sha256(list(key))[:12]
            for m in members:
                m.update(recurrence_group=gid, promotion="proposed_recurring_owner_tier")
    return corrections
