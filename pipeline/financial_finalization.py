"""Prepare financial fields and their retained states before identity matching."""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

from pipeline.financial_conventions import prepare,VERSION
from pipeline.financial_context import compatible_nav
from pipeline.programme.core import atomic_json,sha


def prepare_artifact(frame,directory,*,prior_states_file=None,source_frame=False):
    from pipeline import config
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    prior=pd.read_csv(prior_states_file,dtype=str) if prior_states_file and Path(prior_states_file).is_file() else None
    nav,nav_audit=compatible_nav(frame,config.FUND_FINANCIALS_FILE,config.COMPANYFACTS_CACHE_DIR)
    path=config.GICS_HIERARCHY_FILE
    taxonomy_hash=sha(path) if path.is_file() else None
    taxonomy=json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    hierarchy=pd.DataFrame([(name,definition['sector']) for name,definition in taxonomy.items()],columns=['sub_industry','sector'])
    from pipeline.monetary_fx import load_inputs
    monetary=load_inputs(config.REFERENCE_DIR/'monetary_conversion')
    final,states=prepare(frame,nav=nav,hierarchy=hierarchy,prior_states=prior,source_frame=source_frame,
        fx_quotes=monetary['quotes'],unit_adjudications=monetary['decisions'])
    from pipeline.accounting_scope import annotate
    final=annotate(final)
    if taxonomy_hash and sha(path)!=taxonomy_hash: raise ValueError('Taxonomy changed during financial preparation')
    if any(sha(p)!=value for p,value in monetary['inputs'].items()):
        raise ValueError('Monetary input changed during financial preparation')
    states.to_csv(directory/'financial_state_audit.csv',index=False)
    nav_audit.to_csv(directory/'financial_nav_audit.csv',index=False)
    atomic_json(directory/'financial_contract.json',dict(version=VERSION,taxonomy_sha256=taxonomy_hash,
        state_sha256=sha(directory/'financial_state_audit.csv'),nav_audit_sha256=sha(directory/'financial_nav_audit.csv'),
        monetary_inputs={Path(p).relative_to(config.REFERENCE_DIR).as_posix():value
            for p,value in monetary['inputs'].items()}))
    return final,states
