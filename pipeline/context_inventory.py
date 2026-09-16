"""Cache-only source-context inventory for production-stack experiments E0-E3.

This is a diagnostic collector, not a production extraction rule or a position
roster. Source roles are independent of the legacy extractor's compatibility
flag. Unproved interpretations are retained, never excused as absent positions.
Only XML instances are read; no HTML parsing, network calls or output mutation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
import time

from lxml import etree

from pipeline.bdc_filings import CONCEPT_MAP, _parse_xbrl_contexts
from pipeline.explicit_contexts import explicit_member_dimensions


POLICY_VERSION = "context-inventory.v5"
XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
VALUE_FIELDS = frozenset({"fair_value", "cost", "principal_amount", "face_amount", "shares_held"})
VALUE_CONCEPTS = tuple((pattern, field) for pattern, field in CONCEPT_MAP if field in VALUE_FIELDS)
NEXPOINT_NAMESPACE = "http://www.npci.com/20230331"
NEXPOINT_AXES = frozenset({"legalentityaxis", "debtinstrumentaxis", "investmenttypeaxis",
    "investmentsecondarycategorizationaxis", "statementclassofstockaxis"})
FUND_BASIS_CONCEPTS = frozenset({"assets", "assetsnet", "liabilities", "stockholdersequity"})
STANDARD_CATEGORY_AXES = frozenset({
    "fairvaluebyfairvaluehierarchylevelaxis", "financialinstrumentaxis",
    "investmenttypeaxis", "investmentindustryaxis", "industryaxis",
    "investmentgeographicaldistributionaxis",
})
NON_IDENTITIES = frozenset({"", "total", "total investments", "investments", "various", "n/a",
    "none", "other", "debt", "equity", "software", "first lien", "second lien"})
# Cash-equivalent balance concepts (us-gaap local names, lowercase). A context
# whose ONLY captured monetary facts are these is a cash/money-market balance,
# not a position, even when a typed investment-identifier member names the
# sweep fund (Golub 0001930087-23-000010 context c-13: MMF carrying value
# 650,323,000 on "Morgan Stanley Institutional Liquidity Funds"). Owner
# decision 2026-09-15. Only the MoneyMarketFundsAt* names reach ``facts``
# today (CONCEPT_MAP maps them to fair_value/cost); the remaining names are
# listed so the rule stays correct if CONCEPT_MAP ever admits them. The
# extractor's cash-equivalents rescue (bdc_filings) is deliberately untouched.
CASH_EQUIVALENT_CONCEPTS = frozenset({
    "moneymarketfundsatfairvalue", "moneymarketfundsatcarryingvalue",
    "cashandcashequivalentsatcarryingvalue", "cashandcashequivalentsfairvaluedisclosure",
    "cashequivalentsatcarryingvalue", "cash", "restrictedcash",
    "restrictedcashandcashequivalents", "restrictedcashandcashequivalentsatcarryingvalue",
    "cashcashequivalentsrestrictedcashandrestrictedcashequivalents",
})
CASH_ONLY_PUBLIC_WORDING = "No portfolio positions disclosed; cash and money-market holdings only."


def local(value: str) -> str:
    return str(value).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _namespace(node, qname: str) -> str:
    if ":" in qname:
        return node.nsmap.get(qname.split(":", 1)[0], "")
    return node.nsmap.get(None, "")


def _is_standard(uri: str) -> bool:
    return bool(re.match(r"https?://(?:fasb\.org/us-gaap|xbrl\.sec\.gov/dei)/", uri))


def _field(concept: str) -> str | None:
    name = local(concept).lower()
    return next((field for pattern, field in VALUE_CONCEPTS if pattern in name), None)


def _identity_text(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    return normalized not in NON_IDENTITIES and bool(re.search(r"[a-z]", normalized))


def _concept_namespace(concept: str) -> str:
    return concept[1:].split("}", 1)[0] if concept.startswith("{") else ""


def _is_cash_equivalent_fact(fact: dict) -> bool:
    """Standard-taxonomy cash-equivalent concept; filer lookalikes are not excused."""
    concept = fact["concept"]
    return (local(concept).lower() in CASH_EQUIVALENT_CONCEPTS and
            _is_standard(_concept_namespace(concept)))


def classify_context(context: dict, cik: str, *, basis_concepts: set[str]) -> tuple[str, str]:
    """Return one source role and its mechanism; extractor recognition is not an input."""
    dims = context["dimensions"]
    if context["period_kind"] != "instant":
        return "unresolved", "non_instant_or_ambiguous_investment_period"
    if context["entity_cik"] != cik:
        return "unresolved", "reporting_entity_mismatch"
    # The same context carries the filer's balance sheet. This establishes a
    # fund accounting scope even if an investment amount concept is unmapped.
    if not dims and basis_concepts & FUND_BASIS_CONCEPTS:
        return "aggregate", "fund_balance_sheet_context"
    # A money-market/cash-equivalent carrying value alone is a balance, not an
    # investment fact (acceptance section 2). Any non-cash monetary fact in the
    # same context (e.g. InvestmentOwnedAtFairValue) keeps the context on the
    # ordinary position path below.
    if context["facts"] and all(_is_cash_equivalent_fact(f) for f in context["facts"]):
        return "aggregate", "cash_equivalent_balance"
    if context.get("unknown_concepts"):
        return "unresolved", "unmapped_investment_concept"
    typed_ids = [d for d in dims if d["kind"] == "typed" and
                 ("investmentidentifier" in local(d["axis"]).lower() or
                  "investmentcompany" in local(d["axis"]).lower())]
    if len(typed_ids) == 1 and _identity_text(typed_ids[0]["value"]):
        return "confirmed_position", "typed_investment_identifier"
    if typed_ids:
        return "unresolved", "ambiguous_or_category_typed_identifier"

    # Narrow evidence-backed diagnostic interpretation. This is NOT a global
    # LegalEntityAxis rescue: fund legal entities and category axes also exist.
    # Evidence: 0001193125-23-145196. Its 39 full-schedule contexts carry
    # investee + investment type; debt/class axes distinguish repeated tranches.
    # Their signed FV is 48,731,529, equal to the disclosed investments total.
    # Pin to this observed taxonomy instance: do not generalize to other years.
    legal = [d for d in dims if d["kind"] == "explicit" and
             local(d["axis"]).lower() == "legalentityaxis" and
             re.match(r"https?://xbrl\.sec\.gov/dei/", d["axis_namespace"])]
    axes = {local(d["axis"]).lower() for d in dims}
    if (cik == "0001588272" and context["period"] == "2023-03-31" and len(legal) == 1 and
            legal[0]["member_namespace"] == NEXPOINT_NAMESPACE and
            _identity_text(legal[0]["value"]) and
            {"investmenttypeaxis", "investmentsecondarycategorizationaxis"}.issubset(axes) and
            axes.issubset(NEXPOINT_AXES) and
            all(d["kind"] == "explicit" and _is_standard(d["axis_namespace"]) and
                (d["member_namespace"] == NEXPOINT_NAMESPACE or _is_standard(d["member_namespace"]))
                for d in dims)):
        return "confirmed_position", "nexpoint_explicit_investee_and_instrument"

    # Per-CIK explicit-member identity table (e.g. Lord Abbett on
    # srt:OwnershipAxis). JV look-through contexts on a subsidiary axis are
    # positions too and are flagged downstream, not dropped. Same predicate as
    # the extractor (pipeline.explicit_contexts.EXPLICIT_MEMBER_RULES).
    matched = explicit_member_dimensions(cik, [
        (d["kind"], d["axis_namespace"], local(d["axis"]), d["member_namespace"], local(d["value"]))
        for d in dims], period=context["period"])
    if matched:
        return "confirmed_position", matched[0].name

    # An undimensioned investment fact alone is not sufficient. Independent
    # balance-sheet concepts in the same reporting context establish its basis.
    if (dims and all(d["kind"] == "explicit" and
                    local(d["axis"]).lower() in STANDARD_CATEGORY_AXES and
                    _is_standard(d["axis_namespace"]) and
                    _is_standard(d["member_namespace"]) for d in dims)):
        return "aggregate", "standard_category_only_dimensions"
    return "unresolved", "unsupported_source_dimension_pattern"


def _positive(total: Decimal | None) -> bool:
    return total is not None and total.is_finite() and total > 0


def fund_quarter_class(*, complete: bool, positions: int, unresolved: int,
                       investment_total: Decimal | None,
                       cash_equivalent_total: Decimal | None = None) -> str:
    """Disjoint classification for an eligible fund-quarter with zero output.

    ``cash_equivalent_total`` is the fund-level cash/money-market balance
    resolved from the same instance (``scan_instance`` result key). It is
    consulted only when no positive investment total exists, so a fund that
    raised capital but holds only cash equivalents is
    ``eligible_no_position_facts`` (owner decision 2026-09-15, Golub Q2-2023).
    It is kept separate from the register's positive-investment concept, which
    the exclusion audit treats as a contradiction of lifecycle exclusions.
    """
    if positions < 0 or unresolved < 0:
        raise ValueError("Context counts cannot be negative")
    if not complete:
        return "source_unavailable"
    if positions:
        return "extraction_failure"
    if unresolved:
        return "unresolved_context_pattern"
    if _positive(investment_total) or _positive(cash_equivalent_total):
        return "eligible_no_position_facts"
    return "eligible_empty_candidate"


def _number(node) -> tuple[str | None, str]:
    if node.get("{http://www.w3.org/2001/XMLSchema-instance}nil") in {"true", "1"}:
        return None, "nil"
    try:
        value = Decimal((node.text or "").strip())
        return (str(value), "reported") if value.is_finite() else (None, "nonfinite")
    except InvalidOperation:
        return None, "invalid_numeric_lexical_value"


def scan_instance(path: Path, cik: str, quarter: str, *, max_bytes: int = 100_000_000,
                  max_contexts: int = 25_000, max_facts: int = 300_000,
                  timeout_seconds: float | None = None) -> dict:
    """Inspect one bounded XML source, preserving amounts/units without correction.

    XML element iteration is source parsing, not a DataFrame transform. Batch
    cross-document reductions belong in DuckDB. Result FV sums are per-context
    diagnostics by currency; they may repeat positions and are not portfolio FV.
    """
    started = time.monotonic()
    path = Path(path)
    cik = str(cik).zfill(10)
    result = dict(policy_version=POLICY_VERSION, path=str(path), cik=cik, quarter=quarter,
                  source_complete=False, errors=[], contexts=[], counts={}, sha256=None)

    def bounded():
        if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
            raise TimeoutError("Context inventory source time limit")

    try:
        before = path.stat()
        if before.st_size > max_bytes:
            raise ValueError("Source exceeds context inventory byte limit")
        with path.open("rb") as stream:
            result["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        # Legitimate cached instances embed >10 MB disclosure text blocks.
        # The file-byte/context/fact structural bounds remain in force; DTDs and
        # entity expansion are prohibited independently of libxml's text cap.
        parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False,
                                 recover=False, huge_tree=True)
        tree = etree.parse(str(path), parser)
        if tree.docinfo.doctype or tree.getroot().tag != f"{{{XBRLI}}}xbrl":
            raise ValueError("Expected a standalone XBRL instance without a DTD")
        bounded()
        raw_contexts = tree.findall(f"{{{XBRLI}}}context")
        if len(raw_contexts) > max_contexts:
            raise ValueError("Source exceeds context count limit")
        context_ids = [node.get("id", "") for node in raw_contexts]
        if not all(context_ids) or len(context_ids) != len(set(context_ids)):
            raise ValueError("Missing or duplicate context IDs")
        compatibility = _parse_xbrl_contexts(tree)
        contexts = {}
        for node in raw_contexts:
            dates = node.findall(f"{{{XBRLI}}}period/{{{XBRLI}}}instant")
            ends = node.findall(f"{{{XBRLI}}}period/{{{XBRLI}}}endDate")
            periods = dates + ends
            if len(periods) != 1:
                period, kind = None, "unresolved"
            else:
                period = (periods[0].text or "").strip()
                kind = "instant" if dates else "duration"
            identifier = node.find(f"{{{XBRLI}}}entity/{{{XBRLI}}}identifier")
            entity = (identifier.text or "").strip().zfill(10) if identifier is not None else ""
            dims = []
            for dim in node.iter():
                if dim.tag not in {f"{{{XBRLDI}}}typedMember", f"{{{XBRLDI}}}explicitMember"}:
                    continue
                axis = dim.get("dimension", "")
                value = " ".join(" ".join(dim.itertext()).split())
                explicit = dim.tag.endswith("explicitMember")
                dims.append(dict(axis=axis, axis_namespace=_namespace(dim, axis), value=value,
                                 kind="explicit" if explicit else "typed",
                                 member_namespace=_namespace(dim, value) if explicit else ""))
            context_id = node.get("id")
            contexts[context_id] = dict(context_id=context_id, period=period, period_kind=kind,
                entity_cik=entity, dimensions=dims, facts=[], unknown_concepts=[],
                extractor_recognized=bool(compatibility[context_id]["is_investment"]))
        units = {}
        currencies = {}
        for unit in tree.findall(f"{{{XBRLI}}}unit"):
            measures = unit.findall(f"{{{XBRLI}}}measure")
            units[unit.get("id")] = [" ".join(m.itertext()).strip() for m in measures]
            if len(measures) == 1:
                measure = measures[0]
                qname = (measure.text or "").strip()
                if (_namespace(measure, qname) == "http://www.xbrl.org/2003/iso4217" and
                        re.fullmatch(r"[A-Z]{3}", local(qname))):
                    currencies[unit.get("id")] = local(qname)
        basis = defaultdict(set)
        fact_count = 0
        for node in tree.getroot():
            context_ref = node.get("contextRef")
            if not context_ref:
                continue
            fact_count += 1
            if fact_count > max_facts:
                raise ValueError("Source exceeds fact count limit")
            if fact_count % 1000 == 0:
                bounded()
            concept = local(node.tag)
            field = _field(concept)
            suspicious = ("investment" in concept.lower() and node.get("unitRef") and
                          any(x in concept.lower() for x in ("fairvalue", "cost", "principal")))
            ctx = contexts.get(context_ref)
            if ctx is None:
                if field or suspicious:
                    result["errors"].append("Investment fact references missing context: " + context_ref)
                continue
            if ctx["period"] is None and (field or suspicious):
                result["errors"].append("Investment context has unresolved period: " + context_ref)
            if ctx["period"] != quarter:
                continue
            if _is_standard(etree.QName(node).namespace or ""):
                basis[context_ref].add(concept.lower())
            if not field and not suspicious:
                continue
            value, value_status = _number(node)
            unit_ref = node.get("unitRef", "")
            measures = units.get(unit_ref, [])
            currency = currencies.get(unit_ref)
            ctx["facts"].append(dict(field=field, concept=node.tag, fact_id=node.get("id"),
                raw_text=node.text, value=value, value_status=value_status, unit_ref=unit_ref,
                unit_measures=measures, currency=currency, decimals=node.get("decimals")))
            if not field:
                ctx["unknown_concepts"].append(concept)
        for ctx in contexts.values():
            if ctx["period"] != quarter or not ctx["facts"]:
                continue
            role, reason = classify_context(ctx, cik, basis_concepts=basis[ctx["context_id"]])
            ctx.update(role=role, role_reason=reason)
            # Distinct conflicting FV facts remain unassessable; never choose by order.
            fv = {(f["value"], f["currency"]) for f in ctx["facts"] if f["field"] == "fair_value"}
            if len(fv) == 1:
                ctx["fair_value"], ctx["fair_value_currency"] = next(iter(fv))
            else:
                ctx["fair_value"], ctx["fair_value_currency"] = None, None
            ctx["fair_value_status"] = "conflicting_facts" if len(fv) > 1 else (
                "reported" if ctx["fair_value"] is not None and ctx["fair_value_currency"] else "unavailable")
            result["contexts"].append(ctx)
        # Fund-level cash-equivalent balance: the single reported value carried
        # by undimensioned target-quarter cash facts. Distinct conflicting
        # values are unassessable; dimensioned sweep-fund rows are not totals.
        cash = {(f["value"], f["currency"]) for ctx in result["contexts"]
                if not ctx["dimensions"] and ctx["period_kind"] == "instant" and ctx["entity_cik"] == cik
                for f in ctx["facts"] if _is_cash_equivalent_fact(f)}
        if len(cash) == 1 and all(value is not None and currency for value, currency in cash):
            result["cash_equivalent_total"], result["cash_equivalent_currency"] = next(iter(cash))
            result["cash_equivalent_status"] = "reported"
        else:
            result["cash_equivalent_total"], result["cash_equivalent_currency"] = None, None
            result["cash_equivalent_status"] = "conflicting_facts" if len(cash) > 1 else "unavailable"
        result["cash_only_contexts"] = bool(result["contexts"]) and all(
            ctx["role"] == "aggregate" and all(_is_cash_equivalent_fact(f) for f in ctx["facts"])
            for ctx in result["contexts"])
        bounded()
        after = path.stat()
        with path.open("rb") as stream:
            after_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if (before.st_size, before.st_mtime_ns, result["sha256"]) != (
                after.st_size, after.st_mtime_ns, after_sha):
            raise ValueError("Source changed during inspection")
        result["source_complete"] = not result["errors"]
        result["document_contexts"] = len(raw_contexts)
        result["document_facts"] = fact_count
        result["document_period_ends"] = sorted({(n.text or "").strip() for n in tree.getroot()
            if local(n.tag) == "DocumentPeriodEndDate" and
            re.match(r"https?://xbrl\.sec\.gov/dei/", etree.QName(n).namespace or "")})
        result["target_instant_contexts"] = sum(
            c["period"] == quarter and c["period_kind"] == "instant" for c in contexts.values())
    except (OSError, ValueError, TimeoutError, etree.XMLSyntaxError) as exc:
        result["errors"].append(type(exc).__name__ + ": " + str(exc))
    counts = Counter(ctx["role"] for ctx in result["contexts"])
    result["counts"] = {role: counts[role] for role in ("confirmed_position", "aggregate", "unresolved")}
    result["candidate_context_count"] = len(result["contexts"])
    result["unrecognized_position_contexts"] = sum(
        c["role"] == "confirmed_position" and not c["extractor_recognized"] for c in result["contexts"])
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result
