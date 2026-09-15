"""Source-scoped interpretations of explicit investment context dimensions.

NexPoint 0001193125-23-145196, Q1-2023: investee LegalEntityAxis plus
instrument/type dimensions identifies 39 FV contexts totaling USD 48,731,529.
The rule is pinned to the observed CIK, period and extension namespace. It
does not admit fund legal-entity, generic category or duration contexts.
"""
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
