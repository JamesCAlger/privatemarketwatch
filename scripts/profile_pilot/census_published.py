"""Census-side published-basis partition predicate. Current version census-published.v2 (adopted in Task 0b
fix round 2). census-published.v1 is reachable ONLY through a direct classify(..., version="census-published.v1")
call: the contracts path (contracts._check_frozen, exact match on applies_to) REFUSES frozen v1 roots, so a new
contracts run is needed for them. Pure functions, no I/O.

Ordered rules from the 2026-10-01 investigation (scratch/2026-10-01_census_published_basis,
reference implementation s21_predicate_v2.py) that reconcile the eight pilot filers' census positions
to production's published basis within 0.5%. R1-R5 (and R5b in v2) remove a position; R6 marks it
underlying (not published); R7 adds cash-equivalent-axis fair-value facts the census does not treat as
positions. The first rule that fires wins.

Final-review hardening (2026-10-01): with no period end (neither the DEI fact nor
document_period_end_dates) classify reports period_end=None and no_period_end=True, R1 fails closed
(every row is removed) and R7 emits nothing, so consumers must abstain (contracts_totals does, with cause
no_period_end). `near_misses` counts the FV-only parents that are a token prefix of >= 1 kept rows but fail
the R5 children-sum equality (rollups that would slip back into the sum stay visible). R7 needs every
InvestmentOwnedAtFairValue fact of a qualifying context to agree; a disagreeing context is skipped and
listed in `r7_conflicts` instead of taking the first fact in document order.

census-published.v2 (SP3 Task 0b): R5b_hierarchical_rollup, after R5 and before R6, catches subtotal rows
that also report cost/pct (the 2023 inception schedules of Onex, Fidelity and NexPoint: single-segment
identifiers, category -> industry -> issuer). The pool is the rows still kept after R1-R5. A pool row is a
rollup when
(a) its normalised identifier is a prefix of >= 1 other pool rows (its children): on a word boundary when the
    parent is not segmented, on a SEGMENT boundary when it is -- its raw identifier contains '|' anywhere,
    even trailing (ruling 1 + review item 8: '... | 5/30/2031' is not the parent of a duplicate tag
    '... | 5/30/2031 One', measured on 0001950803 2026-03-31; 'Debt Securities |' is not the parent of
    'Debt Securities Consumer Services ...');
(b) its fair value equals the sum of its DIRECT children (pool rows whose longest valid prefix is this row)
    within the R5 reported-decimals tolerance;
(c) its cost equals the children's cost sum the same way; a parent without cost and with pct is kept; a
    parent without cost and pct is judged on FV alone, plus the principal sum when it reports principal
    (review item 6);
(d) it reports none of NON_ADDITIVE_FIELDS (rate, spread, floor, PIK rate, maturity): a subtotal cannot carry
    them, so such a row is a position (fix round 1: TCW duplicate tags, Ares/BCRED single-child pairs);
(e) its fair value is non-zero (ruling 5, fix round 2): a zero-FV parent carries no sum evidence and stays
    published (BCRED WHCG / Pigments, Ares Eagle warrant). In v2 the same guard applies to R5; v1 R5 is
    frozen and unchanged.
Passes repeat to a fixed point, each removing only the rollups with no rollup below them (deepest first;
`r5b_passes` lists the context ids per pass). `near_misses_r5b` = {n, fv, by_reason} over the prefix parents
kept at the fixed point: fv_cost_mismatch, fv_principal_mismatch (one additive sum matched, the other did
not) and non_additive_terms ((d) abstained). `r5b_single_child` = {n, fv} counts removed rollups that had
exactly one direct child: they are ambiguous with duplicate tags. Measured (fix round 3,
scratch/2026-09-30_base_build/diag_r5b_single_child.py): 241 such removals over all quarters, 236 with a
child carrying position fields and 5 with an identical-FV/cost child without position fields, all Fidelity
industry/category headings over one holding; FV is conserved either way (the child stays), so no abstention.
The negated-cost alternative tried in 2132a31 was reverted (ruling 2).
Known limits (review item 7): hierarchy blocking -- a kept prefix row that is NOT a rollup (e.g. a near
miss) still absorbs its descendants as direct children, so its ancestors are summed at the wrong level and
are kept too (conservative: under-removal, never over-removal); R6 look-through rows are in the R5b child
pool (a JV row whose identifier extends a fund position's) -- no effect today, because v1's R6 splits on '|'
and BCRED's JV rows use a ', Emerald JV LP' suffix it does not mark, and (d)/(e) keep those pairs.

Adoption (rulings 3-6; re-measured in fix round 3 against CURRENT production after the Fidelity wrapper v2
fix, scratch/2026-09-30_base_build/diag_predicate_v2.py + .meta.json): 111 census documents of the 8 pilot
filers; 3 have neither production rows nor a fund_financials anchor and are skipped; 108 rows. The reference
for a fund-quarter is production's published total where production reconciles to
fund_financials.investments_at_fair_value within 0.5%, else that anchor (also when production has no rows);
7 fund-quarters (all 0001715933) have production rows but NO anchor at all and production cannot be checked,
so they are unmeasurable. Of the 101 measured: 0 violations of rule (a) (v2 below -0.5% where v1 was not),
0 worsenings by > 1 pp (rule b), 31 improvements by > 1 pp -> v2 is current. The v1 output shape has no R5b
keys.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

CENSUS_PUBLISHED_V1 = "census-published.v1"
CENSUS_PUBLISHED_V2 = "census-published.v2"
VERSIONS = (CENSUS_PUBLISHED_V1, CENSUS_PUBLISHED_V2)
# v2 passed the all-quarter adoption rule under ruling 4 (fix round 2, 2026-10-01); v1 via version=
CENSUS_PUBLISHED_VERSION = CENSUS_PUBLISHED_V2
# Code MIRROR of the profile entry partition_structure.reporting_entities (SP3 proper). The profile entry is
# authoritative; profile_consistency asserts entry == wrapper source_encodings == this constant. Removal is a
# consumer switch (sub-project 6/7), not done here.
REPORTING_ENTITIES = {"0001803498": ("Emerald JV LP", "Verdelite JV LP")}
RULES_V1 = ("R1_own_period_instant", "R2_fv_not_reported", "R3_label_or_heading", "R4_generic_cash_bucket",
            "R5_issuer_rollup_fv_only", "R6_reporting_entity_lookthrough")
RULES = RULES_V1[:5] + ("R5b_hierarchical_rollup",) + RULES_V1[5:]
R7_SOURCE = "R7_cash_equivalent_axis"

LABEL_SEGMENT = re.compile(r"^(sub-?\s*)?total\b|^net assets$")
CATEGORY_HEADING = re.compile(r"^(non-?)?controlled[\s,/-]*(non-?)?affiliated investments$")
CASH_BUCKET = re.compile(r"^(other )?cash and cash equivalents\b")
REPORTED = ("reported", "consistent_duplicate")
# R5b: terms a subtotal row never carries (not additive across positions); a parent reporting one is kept
NON_ADDITIVE_FIELDS = ("interest_rate", "basis_spread", "interest_rate_floor", "pik_rate", "maturity_date")
R5B_NEAR_MISS_REASONS = ("fv_cost_mismatch", "fv_principal_mismatch", "non_additive_terms")


def _segments(ident):
    return [s.strip().lower() for s in (ident or "").split("|")] if ident else []


def _norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _dec(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _fv(pos):
    return _dec(pos["fields"].get("fair_value", {}).get("value"))


def period_end(doc):
    """(date, source): the dei:DocumentPeriodEndDate fact value, else max(document_period_end_dates)."""
    vals = sorted({str(f.get("value")).strip() for f in doc.get("facts", ())
                   if f.get("qname") == "dei:DocumentPeriodEndDate" and f.get("value")})
    if vals:
        return vals[-1], "dei:DocumentPeriodEndDate"
    dates = (doc.get("document_metadata") or {}).get("document_period_end_dates") or []
    return (max(dates), "document_metadata.max") if dates else (None, "none")


def r1_own_period_instant(pos, pe):
    return (pos.get("period") or {}).get("instant") != pe


def r2_fv_not_reported(pos):
    return pos["fields"].get("fair_value", {}).get("value") in (None, "")


def r3_label_or_heading(pos):
    return any(LABEL_SEGMENT.search(s) or CATEGORY_HEADING.match(" ".join(s.split()))
               for s in _segments(pos["identity"].get("typed_identifier")))


def r4_generic_cash_bucket(pos):
    segs = _segments(pos["identity"].get("typed_identifier"))
    shares = pos["fields"].get("shares_held", {}).get("status") in REPORTED
    if any("money market" in s or ("fund" in s and shares) for s in segs):
        return False
    return any(CASH_BUCKET.match(s) for s in segs)


def _fv_only(pos):
    f = pos["fields"]
    return (f.get("fair_value", {}).get("status") == "reported"
            and sum(1 for v in f.values() if v.get("status") == "reported") == 1)


def _r5_scan(live, nonzero_parent=False):
    """(rollups, near_misses): context ids of FV-only rows whose normalised identifier is a token prefix of
    >=1 other live rows and whose FV equals their FV sum within half a unit of the reported decimals per
    summand (min 1); near_misses are the same prefix parents that FAIL that equality. nonzero_parent (v2,
    ruling 5) skips parents whose FV is zero or unparsable: they carry no sum evidence and stay published."""
    keys = [(_norm(p["identity"].get("typed_identifier")), p) for p in live]
    out, near = set(), []
    for key, parent in keys:
        if not key or not _fv_only(parent) or (nonzero_parent and not _fv(parent)):
            continue
        kids = [p for k, p in keys if p is not parent and k.startswith(key + " ")]
        if not kids:
            continue
        try:
            d = int(parent["fields"]["fair_value"].get("decimals"))
        except (TypeError, ValueError):
            d = 0
        tol = max(Decimal("0.5") * Decimal(10) ** (-d) * (len(kids) + 1), Decimal(1))
        if abs((_fv(parent) or Decimal(0)) - sum((_fv(k) or Decimal(0) for k in kids), Decimal(0))) <= tol:
            out.add(parent["context_id"])
        else:
            near.append(parent)
    return out, near


def r5_issuer_rollups(live):
    """Context ids of the R5 rollups (see _r5_scan)."""
    return _r5_scan(live)[0]


def _reports(pos, field):
    return pos["fields"].get(field, {}).get("status") in REPORTED


def _num_field(pos, field):
    return _dec(pos["fields"].get(field, {}).get("value"))


def _tol(pos, field, n_kids):
    try:
        d = int(pos["fields"][field].get("decimals"))
    except (KeyError, TypeError, ValueError):
        d = 0
    return max(Decimal("0.5") * Decimal(10) ** (-d) * (n_kids + 1), Decimal(1))


def _sum_matches(parent, kids, field):
    """True/False: parent's field equals the kids' sum within the reported-decimals tolerance (an unparsable or
    missing kid value counts 0); None when the parent's own value is unparsable."""
    own = _num_field(parent, field)
    if own is None:
        return None
    vals = [_num_field(k, field) or Decimal(0) for k in kids]
    return abs(own - sum(vals, Decimal(0))) <= _tol(parent, field, len(kids))


def _key(pos):
    """Normalised identifier with ' | ' kept between non-empty segments (tokens; '|' is its own token)."""
    ident = pos["identity"].get("typed_identifier") or ""
    return " | ".join(s for s in (_norm(seg) for seg in ident.split("|")) if s)


def _segmented(pos):
    """True when the raw identifier contains '|' anywhere (a trailing or empty segment still counts)."""
    return "|" in (pos["identity"].get("typed_identifier") or "")


def _ancestor_keys(key, by_key, segmented):
    """Proper prefixes of `key` that are some kept row's key, longest first. A parent key whose rows are not
    segmented may end on any word boundary of the child; a segmented parent key (its key contains '|', or any
    row carrying it has a raw '|', see `segmented`) must end on a segment boundary (whole segments), so
    'Common Stocks | Real Estate' is not a parent of 'Common Stocks | Real Estate Investment Trust ...',
    '... | 5/30/2031' is not a parent of '... | 5/30/2031 One', and 'Debt Securities |' is not a parent of
    'Debt Securities Consumer Services ...'."""
    toks = key.split(" ")
    out = []
    for n in range(len(toks) - 1, 0, -1):
        cand = " ".join(toks[:n])
        if toks[n - 1] == "|" or cand not in by_key:
            continue
        if ("|" in toks[:n] or cand in segmented) and toks[n] != "|":
            continue
        out.append(cand)
    return out


def _direct_children(kept):
    """({id(parent): [direct children]}, by_key, segmented) over the kept rows: a row's parent key is its
    longest valid ancestor key (see _ancestor_keys); every kept row carrying that key is a parent."""
    keyed = [(_key(p), p) for p in kept]
    by_key, segmented = {}, set()
    for key, p in keyed:
        if key:
            by_key.setdefault(key, []).append(p)
            if _segmented(p):
                segmented.add(key)
    kids = {}
    for key, p in keyed:
        anc = _ancestor_keys(key, by_key, segmented) if key else []
        if anc:
            for parent in by_key[anc[0]]:
                kids.setdefault(id(parent), []).append(p)
    return kids, by_key, segmented


def _paired(parent, kids, field, reason):
    """(ok, near_miss_reason) for FV plus one more additive field that must match too."""
    fv_ok = bool(_sum_matches(parent, kids, "fair_value"))
    other_ok = bool(_sum_matches(parent, kids, field))
    return (fv_ok and other_ok), (reason if fv_ok != other_ok else None)


def _r5b_test(parent, kids):
    """(rollup, near_miss_reason) for one prefix parent and its direct children. near_miss_reason is
    'fv_cost_mismatch' (FV matched and cost did not, or the reverse), 'fv_principal_mismatch' (same for the
    principal of a parent without cost and pct), 'non_additive_terms' (the sums matched but the parent reports
    a non-additive term a subtotal cannot carry: the row is a position, e.g. a duplicate tag of its only
    child), or None."""
    if not _fv(parent):
        return False, None                              # ruling 5: a zero-FV parent carries no sum evidence
    if _reports(parent, "cost"):
        ok, reason = _paired(parent, kids, "cost", "fv_cost_mismatch")
    elif _reports(parent, "pct_of_net_assets"):
        return False, None
    elif _reports(parent, "principal_amount"):
        ok, reason = _paired(parent, kids, "principal_amount", "fv_principal_mismatch")
    else:
        ok, reason = bool(_sum_matches(parent, kids, "fair_value")), None
    if reason:
        return False, reason
    if ok and any(_reports(parent, f) for f in NON_ADDITIVE_FIELDS):
        return False, "non_additive_terms"
    return ok, None


def _r5b_scan(kept):
    """(passes, near_misses, single_child) over the rows R1-R5 kept: each pass removes the R5b rollups that have
    no R5b rollup among their descendants (deepest first) and re-derives the direct children from what is
    left; near_misses are (row, reason) for the prefix parents still kept at the fixed point that _r5b_test
    labels; single_child are the removed rollups that had exactly one direct child when removed."""
    kept, passes, single = list(kept), [], []
    while True:
        kids, by_key, segmented = _direct_children(kept)
        found = [p for p in kept if id(p) in kids and _r5b_test(p, kids[id(p)])[0]]
        if not found:
            break
        above = set()
        for p in found:
            for a in _ancestor_keys(_key(p), by_key, segmented):
                above.update(id(q) for q in by_key[a])
        deepest = [p for p in found if id(p) not in above]
        passes.append(deepest)
        single += [p for p in deepest if len(kids[id(p)]) == 1]
        gone = {id(p) for p in deepest}
        kept = [p for p in kept if id(p) not in gone]
    kids, _, _ = _direct_children(kept)
    near = [(p, r) for p in kept if id(p) in kids for r in [_r5b_test(p, kids[id(p)])[1]] if r]
    return passes, near, single


def r6_reporting_entity(pos, cik, reporting_entities=None):
    source = REPORTING_ENTITIES.get(cik, ()) if reporting_entities is None else tuple(reporting_entities)
    names = {_norm(n) for n in source}
    return bool(names) and any(_norm(s) in names for s in _segments(pos["identity"].get("typed_identifier"))[1:])


def _r7_scan(doc, pe):
    """(facts, conflicts): one fact per qualifying context whose InvestmentOwnedAtFairValue facts all agree;
    contexts whose facts disagree are skipped and returned as conflicts. No period end -> nothing."""
    if pe is None:
        return [], []
    held = {p["context_id"] for p in doc.get("positions", ())}
    ctxs = {c["id"]: c for c in doc.get("contexts", ())
            if (c.get("period") or {}).get("instant") == pe and c["id"] not in held
            and not c.get("typed_dimensions") and len(c.get("dimensions") or ()) == 1
            and str(c["dimensions"][0][0]).endswith("CashAndCashEquivalentsAxis")}
    values = {}
    for f in doc.get("facts", ()):
        cid = f.get("context_id")
        if cid in ctxs and f.get("qname") == "us-gaap:InvestmentOwnedAtFairValue":
            v = _dec(f.get("value"))
            if v is not None:
                values.setdefault(cid, []).append(v)
    out, conflicts = [], []
    for cid, vs in values.items():
        if len(set(vs)) == 1:
            out.append(dict(context_id=cid, fair_value=vs[0], source=R7_SOURCE))
        else:
            conflicts.append(dict(context_id=cid, values=[str(v) for v in vs]))
    return out, conflicts


def r7_cash_axis_facts(doc, pe):
    return _r7_scan(doc, pe)[0]


def _fv_total(positions):
    return float(sum((_fv(p) or Decimal(0) for p in positions), Decimal(0)))


def classify(doc, *, cik, version=CENSUS_PUBLISHED_VERSION, reporting_entities=None):
    """Partition the positions on the census published basis of `version` (v1 = R1-R7 without R5b; v2 adds
    R5b). An unknown version raises ValueError. `reporting_entities=None` reads the REPORTING_ENTITIES code
    mirror for `cik` (every existing caller); a tuple (possibly empty) replaces it for R6."""
    if version not in VERSIONS:
        raise ValueError("unknown census published version " + repr(version) + "; known " + repr(VERSIONS))
    v2 = version == CENSUS_PUBLISHED_V2
    pe, pe_source = period_end(doc)
    rows, live = {}, []
    for pos in doc.get("positions", ()):
        rule = ("R1_own_period_instant" if r1_own_period_instant(pos, pe) else
                "R2_fv_not_reported" if r2_fv_not_reported(pos) else
                "R3_label_or_heading" if r3_label_or_heading(pos) else
                "R4_generic_cash_bucket" if r4_generic_cash_bucket(pos) else None)
        rows[pos["context_id"]] = rule
        if rule is None:
            live.append(pos)
    rollups, near = _r5_scan(live, nonzero_parent=v2)
    for cid in rollups:
        rows[cid] = "R5_issuer_rollup_fv_only"
    passes, near_b, single_b = [], [], []
    if v2:
        pool = [p for p in live if rows[p["context_id"]] is None]
        passes, near_b, single_b = _r5b_scan(pool)
        for batch in passes:
            for pos in batch:
                rows[pos["context_id"]] = "R5b_hierarchical_rollup"
    for pos in live:
        if rows[pos["context_id"]] is None and r6_reporting_entity(pos, cik, reporting_entities):
            rows[pos["context_id"]] = "R6_reporting_entity_lookthrough"
    removed = {r: {"n": 0, "fv": Decimal(0)} for r in (RULES if v2 else RULES_V1)}
    for pos in doc.get("positions", ()):
        rule = rows[pos["context_id"]]
        if rule:
            removed[rule]["n"] += 1
            removed[rule]["fv"] += _fv(pos) or Decimal(0)
    r7, r7_conflicts = _r7_scan(doc, pe)
    out = {"version": version, "period_end": pe, "period_end_source": pe_source,
           "no_period_end": pe is None,
           "rows": {c: {"published": r is None, "underlying": r == "R6_reporting_entity_lookthrough", "rule": r}
                    for c, r in rows.items()},
           "extra_fv_facts": [dict(f, fair_value=float(f["fair_value"])) for f in r7],
           "r7_conflicts": r7_conflicts,
           "near_misses": {"n": len(near), "fv": _fv_total(near)},
           "removed_by_rule": {r: {"n": v["n"], "fv": float(v["fv"])} for r, v in removed.items()}}
    if v2:
        out["near_misses_r5b"] = dict(n=len(near_b), fv=_fv_total([p for p, _ in near_b]), by_reason={
            r: {"n": sum(1 for _, x in near_b if x == r), "fv": _fv_total([p for p, x in near_b if x == r])}
            for r in R5B_NEAR_MISS_REASONS})
        out["r5b_passes"] = [[p["context_id"] for p in batch] for batch in passes]
        out["r5b_single_child"] = {"n": len(single_b), "fv": _fv_total(single_b)}
    return out


def published_positions(doc, *, cik, version=CENSUS_PUBLISHED_VERSION, reporting_entities=None):
    rows = classify(doc, cik=cik, version=version, reporting_entities=reporting_entities)["rows"]
    return [p for p in doc.get("positions", ()) if rows[p["context_id"]]["published"]]


def published_fv_sum(doc, *, cik, version=CENSUS_PUBLISHED_VERSION, reporting_entities=None):
    out = classify(doc, cik=cik, version=version, reporting_entities=reporting_entities)
    total = sum((_fv(p) or Decimal(0) for p in doc.get("positions", ()) if out["rows"][p["context_id"]]["published"]),
                Decimal(0))
    return total + sum((f["fair_value"] for f in r7_cash_axis_facts(doc, out["period_end"])), Decimal(0))
