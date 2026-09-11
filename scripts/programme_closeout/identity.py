"""Small reference implementation of governed identity decisions and cost donors.

This allocates no production identifiers and performs no fuzzy matching.
Accepted source/identity decisions are inputs; inference quality is evaluated separately.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal
from uuid import UUID,uuid5

NAMESPACE=UUID('ca7c73a3-3108-5b79-bc8c-2852537f03b7')


def allocate(kind,creation_decision,scope):
    if kind not in ('entity','position') or not creation_decision or not scope:
        raise ValueError('An identity requires its kind, immutable creation decision and scope')
    return kind.upper()+'-'+str(uuid5(NAMESPACE,kind+'|'+scope+'|'+creation_decision))


def apply_decisions(registry,decisions):
    """Explicit source-anchor reassignment, with no implicit merges/splits."""
    result=deepcopy(registry)
    result.setdefault('identities',{});result.setdefault('assignments',{});result.setdefault('events',[])
    seen={e['decision_id'] for e in result['events']}
    for d in decisions:
        required=('decision_id','action','evidence','kind','scope')
        if any(not d.get(k) for k in required):raise ValueError('Incomplete governed decision')
        if d['decision_id'] in seen:
            old=next(e for e in result['events'] if e['decision_id']==d['decision_id'])
            if old!=d:raise ValueError('Decision identity reused with different contents')
            continue
        action=d['action']
        if action=='create':
            pid=allocate(d['kind'],d['decision_id'],d['scope'])
            result['identities'][pid]=dict(kind=d['kind'],scope=d['scope'],creation_decision=d['decision_id'],status='active')
        elif action=='assign':
            pid=d['identity_id']
            identity=result['identities'].get(pid)
            if not identity or identity['status']!='active' or identity['scope']!=d['scope'] or identity['kind']!=d['kind']:
                raise ValueError('Inactive, unknown or incompatible identity')
            for anchor in d['anchors']:
                prior=result['assignments'].get(anchor)
                if prior and prior!=pid:raise ValueError('Assignment conflict requires explicit merge/split/revision')
                result['assignments'][anchor]=pid
        elif action in ('merge','split','revision'):
            if not d.get('assignments'):raise ValueError('Explicit revised assignments required')
            touched=set()
            for anchor,pid in d['assignments'].items():
                identity=result['identities'].get(pid)
                if not identity or identity['status']!='active' or identity['scope']!=d['scope'] or identity['kind']!=d['kind']:
                    raise ValueError('Invalid revised identity')
                touched.add(result['assignments'].get(anchor))
                result['assignments'][anchor]=pid
            if action=='merge':
                survivor=d.get('survivor')
                if not survivor or set(d['assignments'].values())!={survivor}:
                    raise ValueError('Merge needs one explicit survivor')
                for retired in d.get('retire',[]):
                    if retired==survivor or retired not in touched:raise ValueError('Invalid retirement')
                    if retired in result['assignments'].values():raise ValueError('Merge left assigned anchors on retired identity')
                    result['identities'][retired]['status']='retired'
        else:raise ValueError('Unknown identity decision')
        result['events'].append(deepcopy(d));seen.add(d['decision_id'])
    return result


def cost_value(observation,position_observations):
    """Reference donor selector: reported zero wins; uncertainty never becomes missing."""
    state=observation.get('cost_reported_state')
    if state=='reported':
        return dict(value=str(Decimal(str(observation['cost_reported']))),method='reported',donor=None)
    if state!='not_disclosed':
        return dict(value=None,method='unresolved_reported_cost',donor=None)
    if not observation.get('position_id') or observation.get('position_status')!='established':
        return dict(value=None,method='unresolved_position',donor=None)
    eligible=[r for r in position_observations if r.get('position_id')==observation['position_id']
              and r.get('scope')==observation.get('scope') and r.get('fv_state')=='source_valid_USD'
              and r.get('fair_value') is not None and r.get('selected_source') is True]
    if not eligible:return dict(value=None,method='no_eligible_FV_donor',donor=None)
    first=min(r['report_date'] for r in eligible)
    donors=[r for r in eligible if r['report_date']==first]
    if len(donors)!=1:
        return dict(value=None,method='ambiguous_earliest_donor',donor=None)
    donor=donors[0]
    return dict(value=str(Decimal(str(donor['fair_value']))),method='first_observed_FV_proxy',
                donor=donor['source_anchor'],donor_date=first)
