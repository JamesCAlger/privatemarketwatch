"""Shared correction order and observed-cell conflict guard.

Observation tokens exist only within a build; they are never public identity.
SQL records changed cells, so disjoint rows/quarters do not create conflicts.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import duckdb
import pandas as pd

from pipeline.programme.artifacts import literal

KEY='_correction_observation_id'
CURRENT=ContextVar('correction_execution',default=None)
NUMERIC={'fair_value','cost','principal_amount','shares_held','interest_rate','pik_rate','basis_spread',
    'pct_of_net_assets','floor_rate'}
FIELDS=NUMERIC|{'issuer_name','instrument_description','asset_category','issuer_category',
    'index_classification','exposure_type','asset_class','interest_rate_kind','maturity_date',
    'gics_sub_industry','lien_priority','non_accrual','bdc_investment_identifier','bdc_dimensions_raw'}


class CorrectionConflict(ValueError):
    pass


@contextmanager
def session():
    if CURRENT.get() is not None:
        yield False
        return
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.execute('CREATE TABLE claims(observation VARCHAR,field VARCHAR,writer VARCHAR)')
        token=CURRENT.set(dict(con=con,next_key=0,completed=set()))
        try: yield True
        finally: CURRENT.reset(token)


def keys(frame):
    state=CURRENT.get()
    if state is None: raise CorrectionConflict('Correction session is missing')
    frame=frame.copy()
    if KEY not in frame: frame[KEY]=pd.Series(pd.NA,index=frame.index,dtype='string')
    absent=frame[KEY].isna()
    count=int(absent.sum())
    frame.loc[absent,KEY]=pd.Series(range(state['next_key'],state['next_key']+count),dtype='string').to_numpy()
    state['next_key']+=count
    if frame[KEY].duplicated().any(): raise CorrectionConflict('Correction duplicated an observation token')
    return frame


def scoped(function):
    @wraps(function)
    def wrapped(frame,*args,**kwargs):
        with session() as owned:
            prepared=keys(frame)
            result=function(prepared,*args,**kwargs)
            if owned:
                if isinstance(result,tuple):
                    cleaned=result[0].drop(columns=[KEY],errors='ignore')
                    if result[0] is prepared and cleaned.equals(frame): cleaned=frame
                    return (cleaned,*result[1:])
                return result.drop(columns=[KEY],errors='ignore')
            return result
    return wrapped


def writer_id(rule):
    return str(rule.get('rule_id') or rule.get('fix_class') or '')


def dependencies(rule):
    deps=rule.get('depends_on',[])
    if not isinstance(deps,list) or any(not isinstance(d,str) or not d for d in deps):
        raise CorrectionConflict('depends_on must be a list of explicit writer IDs')
    return set(deps)


def ordered(rules,stage):
    """Topological order inside semantic stages; never use filenames as precedence."""
    pending=list(enumerate(rules));result=[];done=set()
    identifiers=[writer_id(r) for r in rules]
    if any(not value for value in identifiers): raise CorrectionConflict('Correction has no writer identity')
    available=set(identifiers)|((CURRENT.get() or {}).get('completed',set()))
    if any(dependencies(r)-available for r in rules):
        raise CorrectionConflict('Correction dependency is not in the admitted execution plan')
    # The same mechanism may have distinct quarter-scoped leaves. They retain
    # input order; actual overlap still fails at the observed-cell guard.
    while pending:
        candidates=[(i,r) for i,r in pending if not (dependencies(r)&set(identifiers)-done)]
        if not candidates: raise CorrectionConflict('Cyclic correction dependencies')
        i,rule=min(candidates,key=lambda item:(stage(item[1]),item[0]))
        if result and stage(rule)<stage(result[-1]):
            raise CorrectionConflict('Dependency reverses semantic correction stages')
        result.append(rule);done.add(writer_id(rule));pending=[p for p in pending if p[0]!=i]
    return result


def ordered_rules(rules):
    rank={'row_exclusion':0,'dedup':1,'row_add':2,'value_rescale':3,'value_expression':3}
    return ordered(rules,lambda r:rank.get(r.get('rule_type'),4))


def claim(before,after,rule):
    state=CURRENT.get()
    if state is None: raise CorrectionConflict('Correction write escaped its execution session')
    after=keys(after)
    writer=writer_id(rule);deps=dependencies(rule)
    con=state['con'];con.register('before_frame',before);con.register('after_frame',after)
    fields=sorted(FIELDS&set(before.columns)&set(after.columns))
    parts=[]
    for field in fields:
        sql_type='DOUBLE' if field in NUMERIC else 'VARCHAR'
        left='TRY_CAST(b."'+field+'" AS '+sql_type+')'
        right='TRY_CAST(a."'+field+'" AS '+sql_type+')'
        parts.append('SELECT a.'+KEY+' AS observation,'+literal(field)+' AS field FROM after_frame a '
            'LEFT JOIN before_frame b ON a.'+KEY+'=b.'+KEY+' WHERE '+left+' IS DISTINCT FROM '+right)
    if parts:
        con.execute('CREATE OR REPLACE TEMP TABLE changed AS '+' UNION ALL '.join(parts))
        # A previous write by the same named mechanism also requires an explicit
        # dependency; duplicate leaves must not silently multiply a value twice.
        allowed=','.join(literal(d) for d in deps) or "''"
        conflicts=con.execute('SELECT c.observation,c.field,p.writer FROM changed c JOIN claims p USING(observation,field) '
            'WHERE p.writer NOT IN ('+allowed+') LIMIT 10').fetchall()
        if conflicts: raise CorrectionConflict('Undeclared correction writer conflict: '+writer+' after '+repr(conflicts))
        con.execute('DELETE FROM claims USING changed c WHERE claims.observation=c.observation AND claims.field=c.field')
        con.execute('INSERT INTO claims SELECT observation,field,? FROM changed',[writer])
    state['completed'].add(writer)
    return after
