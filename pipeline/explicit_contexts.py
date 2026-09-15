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
    # (axis_local_lower, member_local_lower, instant) triples; instant '' means
    # every period. Excludes a context on any axis member, e.g. a whole member
    # family the filer mis-dated. Each triple needs a documented mechanism.
    excluded_axis_members: frozenset = frozenset()
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
    # AB Private Credit Investors Corp, first-year explicit-member quarters.
    # Position identity is the portfolio-company member on dei:LegalEntityAxis
    # (extension namespace http://www.abpcic.com/YYYYMMDD; the filer already
    # mints one member per tranche, e.g. AmerCareRoyalLlcFourMember) combined
    # with DebtInstrumentAxis (lien family, label carries the family's pct of
    # net assets), CreditFacilityAxis (term loan / DDTL / revolver),
    # InvestmentTypeAxis and StatementClassOfStockAxis (preferred vs warrant
    # of the same series, e.g. Vectra AI Series F). Industry is the filer's
    # abpcic:InvestmentServiceTypeAxis.
    # Evidence 0001193125-23-145163 (Q1-2023): 448 instant contexts (383 debt,
    # 65 equity) sum to 1,179,343,662 = the undimensioned
    # InvestmentOwnedAtFairValue exactly; the 440 2022-12-31 comparatives in
    # the same instance also reconcile exactly (1,122,517,095). Not admitted by
    # the axis set: 133 abpcic:InvesteeAxis/FacilityTypeAxis unfunded-
    # commitment contexts (-3,483,621, outside the total), 2 money-market
    # contexts on CashAndCashEquivalentsAxis (54,630,117, cash equivalents),
    # Bowline Topco srt:ConsolidatedEntitiesAxis affiliate rollups (173,837,
    # already a position), DebtInstrumentAxis-only / InvestmentTypeAxis-only
    # family subtotals, and the 65 duration equity contexts (share
    # descriptions).
    # Evidence 0001193125-23-212335 (Q2-2023): 499 contexts at 2023-06-30 sum
    # to 1,369,247,302 vs the filer total 1,227,572,852 (+141,674,450), while
    # the instance's own 2022-12-31 comparatives are short by exactly
    # -141,674,450. The 38 contexts on
    # DebtInstrumentAxis=FirstLienSeniorSecuredDebtAt234.31Member (the
    # 12/31/2022 lien-family label; 288 rows carry it at 12/31/2022) are the
    # 12/31/2022 rows of 38 positions tagged with the 6/30/2023 instant: 34
    # of 38 pair with a live 6/30 row of the same borrower and facility, same
    # face amount, cost/FV drifting the way OID accretion and revolver draws
    # do. Excluding that member family at 2023-06-30 only restores exact
    # conservation (461 contexts = 1,227,572,852). The same label is genuine
    # at 2023-03-31 (41 rows, inside the Q1 total), hence the period scope.
    # Pinned to the two evidenced instants; the FY2022 10-K and the 12/31
    # comparatives are a follow-up once checked against the FY2022 total.
    '0001634452': ExplicitMemberRule(
        name='abpcic_explicit_legal_entity_and_instrument',
        identity_axis='legalentityaxis',
        member_namespace_pattern=r'https?://www\.abpcic\.com/\d{8}$',
        industry_axis='investmentservicetypeaxis',
        instrument_axes=('debtinstrumentaxis','creditfacilityaxis',
                         'investmenttypeaxis','statementclassofstockaxis'),
        required_axes=frozenset({'investmenttypeaxis'}),
        excluded_members=frozenset({'abprivatecreditinvestorscorpmember',
                                    'abprivatecreditinvestorscorporationmember',
                                    'abpcicmember'}),
        excluded_axis_members=frozenset({
            ('debtinstrumentaxis','firstlienseniorsecureddebtat234.31member','2023-06-30'),
        }),
        periods=frozenset({'2023-03-31','2023-06-30'}),
    ),
    # Onex Direct Lending BDC Fund (Onex Falcon), Q1-2023. The filer put the
    # portfolio company on us-gaap:EquityMethodInvestmentNonconsolidatedInvesteeAxis
    # (extension namespace http://onexfalcondirectlending.com/YYYYMMDD) for its
    # own directly held loans -- not equity-method investees -- and the tranche
    # on us-gaap:LongtermDebtTypeAxis (InitialTermLoan / DelayedDrawTermLoan /
    # RevolvingLoan / CommonEquity / EquityUnits; one member is the standard
    # us-gaap:RevolvingCreditFacilityMember). DebtInstrumentAxis carries the
    # affiliation category (NonControlledAndNonAffiliatedInvestmentsMember)
    # and InvestmentTypeAxis the debt/equity split; neither is identity.
    # Evidence 0000950170-23-021345: 56 five-axis contexts at 2023-03-31 (53
    # with FV, 3 unfunded DDTL/revolver rows with cost only) sum to
    # 521,760,590 vs the undimensioned total 526,177,088 (-0.839%). The
    # residual is source omission: the Automotive (-479,070) and Healthcare
    # (-3,937,428) industry subtotals exceed their tagged tranche rows and no
    # context in the instance carries the difference. The 2022-12-31
    # comparatives in the same instance reconcile exactly (504,942,593).
    # Not admitted: the Foundation Risk Partners 4-axis context (19,065,681 =
    # its term loan + DDTL, a borrower subtotal; LongtermDebtTypeAxis is
    # required), 18 investee+tranche spread-only contexts (no industry axis),
    # 51 contexts that add VariableRateAxis (rate facts only; not an allowed
    # axis, so interest rates stay unattached for this quarter), industry /
    # type / fair-value-level subtotals. The axis name does not match the
    # staging is_subsidiary patterns (nonconsolidatedsubsidiar,
    # equitymethodinvestmentequitymethodinvesteenameaxis), so these rows are
    # own-book, not flagged. Pinned to the evidenced instant.
    '0001860424': ExplicitMemberRule(
        name='onex_explicit_investee_and_debt_type',
        identity_axis='equitymethodinvestmentnonconsolidatedinvesteeaxis',
        member_namespace_pattern=r'https?://onexfalcondirectlending\.com/\d{8}$',
        industry_axis='equitysecuritiesbyindustryaxis',
        instrument_axes=('longtermdebttypeaxis',),
        required_axes=frozenset({'longtermdebttypeaxis','equitysecuritiesbyindustryaxis',
                                 'investmenttypeaxis'}),
        other_axes=frozenset({'debtinstrumentaxis'}),
        excluded_members=frozenset({'onexdirectlendingbdcfundmember',
                                    'onexfalcondirectlendingbdcfundmember'}),
        periods=frozenset({'2023-03-31'}),
    ),
}


def rule_for(cik):
    """Return the explicit-member rule for a CIK (any zero-padding), or None."""
    digits=str(cik or '').strip().lstrip('0')
    return EXPLICIT_MEMBER_RULES.get(digits.zfill(10)) if digits else None


def explicit_member_dimensions(cik,dimensions,period=None):
    """Pure predicate shared by the extractor and the context inventory.

    ``dimensions`` is an iterable of ``(kind, axis_namespace, axis_local,
    member_namespace, member_local)`` tuples. ``period`` is the context instant
    (used only by period-scoped ``excluded_axis_members``; a None period never
    matches a period-scoped exclusion). Returns ``(rule, {axis_local_lower:
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
    if rule.excluded_axis_members:
        instant=str(period or '').strip()
        for axis,member in found.items():
            key=(axis,member.lower())
            if key+('',) in rule.excluded_axis_members or (instant and key+(instant,) in rule.excluded_axis_members):
                return None
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
    instant=(instants[0].text or '').strip() if len(instants)==1 else None
    matched=explicit_member_dimensions(identifier,dimensions,period=instant)
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
