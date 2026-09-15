"""Stage durable identities and post-identity financial values in one packet."""
from __future__ import annotations
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.durable_identity import allocate,VERSION as IDENTITY_VERSION
from pipeline.financial_conventions import cost_proxies,synchronize_matches,VERSION as FINANCIAL_VERSION
from pipeline.programme.core import atomic_json,sha


def finish(holdings,matches,states,*,directory,release_id,build_fingerprint,input_registry=None,revisions=()):
    """Write only inside the finalizer's private staging directory.

    Input registry snapshots remain immutable. The caller publishes this whole
    packet only after final schema, identity and typed-pair verification.
    """
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    registry=directory/'identity_registry.duckdb'
    prior_hash=sha(input_registry) if input_registry is not None else None
    final,updated,mapping,counts=allocate(holdings,matches,input_registry=input_registry,output_registry=registry,
        release_id=release_id,build_fingerprint=build_fingerprint,revisions=revisions)
    final,donors=cost_proxies(final,states,release_id=release_id)
    updated=synchronize_matches(updated,final)
    states.to_csv(directory/'financial_state_audit.csv',index=False)
    donors.to_csv(directory/'cost_donor_audit.csv',index=False)
    mapping.to_csv(directory/'identity_aliases.csv',index=False)
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.register('identity_mapping',mapping)
        for name,kind in (('entity_lookup.csv','entity'),('position_id_edges.csv','position')):
            path=directory/name
            if not path.is_file(): continue
            frame=pd.read_csv(path,dtype=str)
            identity_column=kind+'_id'
            con.register('auxiliary',frame)
            if con.execute('SELECT count(*) FROM auxiliary a ANTI JOIN identity_mapping m ON m.kind=? AND CAST(a.'+
                identity_column+' AS VARCHAR)=m.legacy_id',[kind]).fetchone()[0]:
                raise ValueError('Auxiliary identity has no durable alias: '+name)
            result=con.execute('SELECT a.* REPLACE(m.identity_id AS '+identity_column+
                ') FROM auxiliary a JOIN identity_mapping m ON m.kind=? AND CAST(a.'+
                identity_column+' AS VARCHAR)=m.legacy_id',[kind]).fetchdf()
            if len(result)!=len(frame): raise ValueError('Auxiliary identity remapping changed grain: '+name)
            result.to_csv(path,index=False)
    if input_registry is not None and sha(input_registry)!=prior_hash:
        raise ValueError('Input registry changed during identity finalization')
    atomic_json(directory/'identity_contract.json',dict(release_id=release_id,build_fingerprint=build_fingerprint,
        financial_contract=FINANCIAL_VERSION,identity_contract=IDENTITY_VERSION,input_registry_sha256=prior_hash,
        output_registry_sha256=sha(registry),counts=counts,
        field_states_sha256=sha(directory/'financial_state_audit.csv'),cost_donors_sha256=sha(directory/'cost_donor_audit.csv')))
    return final,updated
