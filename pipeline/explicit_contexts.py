"""Source-scoped interpretations of explicit investment context dimensions.

NexPoint 0001193125-23-145196, Q1-2023: investee LegalEntityAxis plus
instrument/type dimensions identifies 39 FV contexts totaling USD 48,731,529.
The rule is pinned to the observed CIK, period and extension namespace. It
does not admit fund legal-entity, generic category or duration contexts.

``EXPLICIT_MEMBER_RULES`` generalizes the same failure class as a per-CIK
table: filers whose position identity is an explicit member on some axis other
than a typed ``InvestmentIdentifierAxis``. Each entry is data; the evaluator
(``explicit_member_dimensions`` / ``explicit_member_position``) is shared by
the extractor (``bdc_filings._parse_xbrl_contexts``) and the context inventory
(``context_inventory.classify_context``) so both assign the same role.
"""
from dataclasses import dataclass, field
import re

XBRLI='http://www.xbrl.org/2003/instance'
XBRLDI='http://xbrl.org/2006/xbrldi'
NAMESPACE='http://www.npci.com/20230331'
AXES={'legalentityaxis','debtinstrumentaxis','investmenttypeaxis',
      'investmentsecondarycategorizationaxis','statementclassofstockaxis'}


def _qname(node,value):
    if ':' not in value: return '',value
    prefix,name=value.split(':',1)
    return node.nsmap.get(prefix,''),name


def _standard(namespace):
    return bool(re.match(r'https?://(?:fasb\.org/us-gaap|xbrl\.sec\.gov/dei)/',namespace))


def nexpoint_position(context):
    """Return exact member identities, or None when source scope is unproved."""
    identifier=context.findtext('{'+XBRLI+'}entity/{'+XBRLI+'}identifier','').strip()
    instants=context.findall('{'+XBRLI+'}period/{'+XBRLI+'}instant')
    if identifier.lstrip('0')!='1588272' or len(instants)!=1 or instants[0].text!='2023-03-31':
        return None
    dimensions={}
    for node in context.iter():
        if node.tag=='{'+XBRLDI+'}typedMember': return None
        if node.tag!='{'+XBRLDI+'}explicitMember': continue
        namespace,axis=_qname(node,node.get('dimension',''))
        member_namespace,member=_qname(node,(node.text or '').strip())
        axis=axis.lower()
        if axis not in AXES or axis in dimensions or not _standard(namespace): return None
        if member_namespace!=NAMESPACE and not _standard(member_namespace): return None
        if axis=='legalentityaxis' and (member_namespace!=NAMESPACE or
                not re.match(r'https?://xbrl\.sec\.gov/dei/',namespace)):
            return None
        dimensions[axis]=member
    if not {'legalentityaxis','investmenttypeaxis','investmentsecondarycategorizationaxis'} <= dimensions.keys():
        return None
    legal=dimensions['legalentityaxis']
    if not re.search('[a-zA-Z]',legal) or legal.lower() in {'total','totalinvestmentsmember','othermember','investmentsmember','nexpointcapitalincmember'}:
        return None
    # Preserve every explicit tranche/class discriminator in the working key.
    # Readable source wording and original dimensions remain separately stored.
    return dimensions


# ---------------------------------------------------------------------------
# Per-CIK explicit-member identity rules (table-driven)
#
# Axis names are lowercased local names. Members are matched by local name;
# the identity member (and the subsidiary member, when present) must live in
# the filer's extension namespace (``member_namespace_pattern``); other members
# may be extension or standard (us-gaap / dei / srt). Axis namespaces may be
# standard or extension. A context qualifies only when every explicit axis is
# one the rule names (identity, industry, subsidiary, instrument or other),
# no typed member is present, ``required_axes`` are all present, and the
# identity member is not in ``excluded_members``.
#
# Subsidiary/JV look-through contexts are RETAINED: the axis stays in the
# extractor's ``dimensions_raw`` and staging_bdc derives ``is_subsidiary`` from
# it (retain-and-flag contract). Nothing here drops them.
#
# Adding a filer is a data change: append an entry and a fixture test. Do not
# widen the global typed-identifier axis list for these filers.
# ---------------------------------------------------------------------------
_STANDARD_AXIS_RE=re.compile(r'https?://(?:fasb\.org/(?:us-gaap|srt)|xbrl\.sec\.gov/dei)/')


@dataclass(frozen=True)
class ExplicitMemberRule:
    name: str
    identity_axis: str
    member_namespace_pattern: str
    industry_axis: str | None = None
    subsidiary_axis: str | None = None
    instrument_axes: tuple[str, ...] = ()          # appended to the identifier, in order
    required_axes: frozenset = frozenset()          # beyond identity_axis
    other_axes: frozenset = frozenset()             # permitted, not used for identity
    excluded_members: frozenset = frozenset()       # lowercased identity member local names
    humanize: str = 'camel'                         # 'camel' (split CamelCase) | 'none'
    instant_only: bool = True
    periods: frozenset | None = None                # pin to these instants when set

    def allowed_axes(self):
        axes={self.identity_axis,*self.instrument_axes,*self.required_axes,*self.other_axes}
        if self.industry_axis: axes.add(self.industry_axis)
        if self.subsidiary_axis: axes.add(self.subsidiary_axis)
        return axes


EXPLICIT_MEMBER_RULES={
    # Lord Abbett Private Credit Fund. Evidence 0000930413-26-001612 (Q1-2026):
    # 524 own-book contexts (OwnershipAxis + EquitySecuritiesByIndustryAxis)
    # and 140 SBLA Private Credit LLC look-through contexts that add
    # InvestmentCompanyNonconsolidatedSubsidiaryAxis. Not admitted: 145
    # Ownership-only contexts (UnfundedLoanCommitment/maturity only, no FV or
    # cost; these also carry the three fund-level counterparties), 108
    # industry-only subtotals, 34 typed InvestmentIdentifierAxis category
    # rollups (wrapper aggregates). Namespace is re-minted each quarter
    # (http://www.lordabbett.com/YYYYMMDD; prefix lordabbett or ck0002008748).
    '0002008748': ExplicitMemberRule(
        name='lordabbett_explicit_ownership_and_industry',
        identity_axis='ownershipaxis',
        member_namespace_pattern=r'https?://www\.lordabbett\.com/\d{8}$',
        industry_axis='equitysecuritiesbyindustryaxis',
        subsidiary_axis='investmentcompanynonconsolidatedsubsidiaryaxis',
        required_axes=frozenset({'equitysecuritiesbyindustryaxis'}),
        excluded_members=frozenset({'lordabbettandotherinvestmentcompaniesmember',
                                    'lordabbettprivatecreditfundmember',
                                    'stifelbanktrustmember'}),
    ),
}


def rule_for(cik):
    """Return the explicit-member rule for a CIK (any zero-padding), or None."""
    digits=str(cik or '').strip().lstrip('0')
    return EXPLICIT_MEMBER_RULES.get(digits.zfill(10)) if digits else None


def explicit_member_dimensions(cik,dimensions):
    """Pure predicate shared by the extractor and the context inventory.

    ``dimensions`` is an iterable of ``(kind, axis_namespace, axis_local,
    member_namespace, member_local)`` tuples. Returns ``(rule, {axis_local_lower:
    member_local})`` for a position context, else None.
    """
    rule=rule_for(cik)
    if rule is None: return None
    extension=re.compile(rule.member_namespace_pattern)
    allowed=rule.allowed_axes()
    found={}
    for kind,axis_namespace,axis,member_namespace,member in dimensions:
        if kind!='explicit': return None
        axis=str(axis or '').lower()
        axis_namespace=axis_namespace or ''
        member_namespace=member_namespace or ''
        if axis not in allowed or axis in found: return None
        if not (_STANDARD_AXIS_RE.match(axis_namespace) or extension.match(axis_namespace)):
            return None
        is_extension=bool(extension.match(member_namespace))
        if axis in (rule.identity_axis,rule.subsidiary_axis) and not is_extension: return None
        if not is_extension and not _standard(member_namespace): return None
        found[axis]=member
    if rule.identity_axis not in found or not rule.required_axes<=found.keys(): return None
    identity=found[rule.identity_axis]
    if not re.search('[a-zA-Z]',identity) or identity.lower() in rule.excluded_members: return None
    return rule,found


def humanize_member(rule,member):
    if rule.humanize=='camel':
        from pipeline.bdc_filings import _humanize_member_local_name
        return _humanize_member_local_name(member)
    text=str(member or '').strip()
    return text[:-len('Member')] if text.endswith('Member') else text


def explicit_member_position(context):
    """Evaluate ``EXPLICIT_MEMBER_RULES`` against one lxml context node.

    Returns ``{'rule', 'investment_identifier', 'industry', 'subsidiary',
    'dimensions'}`` for a position context, else None. ``industry`` and
    ``subsidiary`` are '' when the rule has no such axis or the context lacks
    it. The identifier is the humanized identity member followed by any
    instrument-axis members, joined with ' - ' (NexPoint convention).
    """
    identifier=context.findtext('{'+XBRLI+'}entity/{'+XBRLI+'}identifier','').strip()
    rule=rule_for(identifier)
    if rule is None: return None
    instants=context.findall('{'+XBRLI+'}period/{'+XBRLI+'}instant')
    if rule.instant_only and len(instants)!=1: return None
    if rule.periods is not None and (len(instants)!=1 or (instants[0].text or '').strip() not in rule.periods):
        return None
    dimensions=[]
    for node in context.iter():
        if node.tag=='{'+XBRLDI+'}typedMember': return None
        if node.tag!='{'+XBRLDI+'}explicitMember': continue
        axis_namespace,axis=_qname(node,node.get('dimension',''))
        member_namespace,member=_qname(node,(node.text or '').strip())
        dimensions.append(('explicit',axis_namespace,axis,member_namespace,member))
    matched=explicit_member_dimensions(identifier,dimensions)
    if matched is None: return None
    rule,found=matched
    parts=[found[rule.identity_axis]]+[found[axis] for axis in rule.instrument_axes if axis in found]
    return {
        'rule':rule.name,
        'investment_identifier':' - '.join(humanize_member(rule,part) for part in parts),
        'industry':humanize_member(rule,found[rule.industry_axis]) if rule.industry_axis in found else '',
        'subsidiary':found.get(rule.subsidiary_axis,'') if rule.subsidiary_axis else '',
        'dimensions':found,
    }
