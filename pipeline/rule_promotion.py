"""Manifest-last rule publication with explicit recovery and legacy accounting.

The promoter supplies independently passing, input-bound evidence. Existing
unmanifested rules are inventoried as legacy_unverified, never approved by a
new promotion. Readers refuse a store while a transaction is incomplete.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from pipeline.programme.core import ContractError, atomic_json, contained, digest, read_json, sha

TRANSACTION = '_admission_transaction'


def assert_ready(base):
    if (Path(base)/TRANSACTION).exists():
        raise ContractError('Rule admission transaction requires recovery: '+str(base))


def _live_files(base):
    for path in sorted(base.rglob('*.json')):
        relative = path.relative_to(base)
        if (path.name=='admission_manifest.json' or '.proposed.' in path.name.lower()
            or any(p.startswith('_') for p in relative.parts)):
            continue
        yield contained(base, relative.as_posix())


def _clean(base):
    target=base/TRANSACTION
    if target.resolve().parent != base.resolve() or target.name != TRANSACTION or target.is_symlink():
        raise ContractError('Unsafe admission recovery directory')
    for path in target.rglob('*'):
        if path.is_file():
            contained(base, path.relative_to(base).as_posix())
    shutil.rmtree(target)


def recover(base):
    """Complete committed cleanup or restore a prepared transaction exactly.

    Unexpected edits cause a refusal; recovery cannot overwrite someone's
    later work. This is also the deterministic exception rollback path.
    """
    base=Path(base).resolve()
    directory=base/TRANSACTION
    state_path=contained(base, (Path(TRANSACTION)/'state.json').as_posix(),existing=False)
    if not state_path.exists():
        # Publication does not touch production paths before the journal is
        # durable. A crash while staging can therefore discard its workspace.
        _clean(base)
        return 'initialization_discarded'
    state=read_json(state_path)
    if state.get('format_version')!=1 or state.get('phase') not in ('prepared','committed'):
        raise ContractError('Invalid admission recovery state')
    records=state['files']
    # Validate the entire transaction before restoring its first file.
    for item in records:
        target=contained(base,item['path'],existing=False)
        current=sha(target) if target.exists() else None
        permitted={item['new_sha256']} if state['phase']=='committed' else {item['old_sha256'],item['new_sha256']}
        if current not in permitted:
            raise ContractError('Rule changed outside admission transaction: '+item['path'])
        if state['phase']=='prepared' and item['old_sha256'] is not None:
            backup=contained(directory,item['backup'])
            if sha(backup)!=item['old_sha256']:
                raise ContractError('Admission recovery backup changed')
    if state['phase']=='prepared':
        for item in reversed(records):
            target=contained(base,item['path'],existing=False)
            if item['old_sha256'] is None:
                if target.exists(): target.unlink()
            else:
                shutil.copyfile(contained(directory,item['backup']),target)
    _clean(base)
    return state['phase']


def publish(base, items, *, allow_overwrite=False):
    """Publish a validated set; each item names source, relative path, evidence.

    Evidence must contain a PASS gate and an exact source SHA captured by the
    caller after checking the gate's evaluated input identity. A later byte
    change is rejected. No independent evaluation is performed by this writer.
    """
    base=Path(base).resolve()
    base.mkdir(parents=True,exist_ok=True)
    assert_ready(base)
    items=list(items)
    if not items:
        return []
    prepared=[]
    names=set()
    for item in items:
        relative=item['path']
        target=contained(base,relative,existing=False)
        if (target.suffix!='.json' or target.name=='admission_manifest.json'
            or '.proposed.' in target.name.lower() or any(p.startswith('_') for p in Path(relative).parts)
            or relative.casefold() in names):
            raise ContractError('Invalid or repeated promotion path')
        names.add(relative.casefold())
        source=Path(item['source']).resolve()
        evidence=item.get('evidence',{})
        if not isinstance(evidence,dict) or evidence.get('gate',{}).get('verdict')!='PASS':
            raise ContractError('Promotion requires passing independent gate evidence')
        if not evidence.get('source_sha256') or sha(source)!=evidence['source_sha256']:
            raise ContractError('Staged rule changed after evaluation')
        if target.exists() and not allow_overwrite:
            raise ContractError('Promotion would overwrite an existing live rule')
        # Only parsed objects reach a production rule loader.
        if not isinstance(json.loads(source.read_text(encoding='utf-8-sig')),dict):
            raise ContractError('Promoted rule must be a JSON object')
        prepared.append(dict(item,source=source))
    directory=base/TRANSACTION
    directory.mkdir()  # Exclusive writer; loaders now fail closed.
    try:
        manifest_path=base/'admission_manifest.json'
        if manifest_path.exists():
            manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            if manifest.get('format_version') not in (1,2):
                raise ContractError('Unsupported admission manifest')
            for relative, entry in manifest.get('entries',{}).items():
                existing=contained(base,relative)
                if sha(existing)!=entry.get('sha256'):
                    raise ContractError('Existing admission manifest no longer matches live rules')
        else:
            manifest=dict(format_version=2,entries={p.relative_to(base).as_posix():
                dict(admission_status='legacy_unverified',sha256=sha(p),
                     reason='Inventoried without original admission evidence') for p in _live_files(base)})
        files=[]
        for index,item in enumerate(prepared):
            staged=directory/f'new-{index}.json'
            shutil.copyfile(item['source'],staged)
            if sha(staged)!=item['evidence']['source_sha256']:
                raise ContractError('Staged rule changed during publication')
            target=base/item['path']
            entry=dict(path=item['path'],new_sha256=sha(staged),
                       old_sha256=sha(target) if target.exists() else None,backup=f'old-{index}.json',
                       staged=staged.name)
            if target.exists(): shutil.copyfile(target,directory/entry['backup'])
            files.append(entry)
            manifest['entries'][item['path']]=dict(admission_status='promoted',sha256=entry['new_sha256'],
                evidence=item['evidence'],evidence_sha256=digest(item['evidence']))
        staged_manifest=directory/'new-manifest.json'
        atomic_json(staged_manifest,manifest)
        files.append(dict(path='admission_manifest.json',new_sha256=sha(staged_manifest),
            old_sha256=sha(manifest_path) if manifest_path.exists() else None,
            backup='old-manifest.json',staged=staged_manifest.name))
        if manifest_path.exists(): shutil.copyfile(manifest_path,directory/'old-manifest.json')
        state=dict(format_version=1,phase='prepared',files=files)
        atomic_json(directory/'state.json',state)
        for entry in files:
            target=contained(base,entry['path'],existing=False)
            target.parent.mkdir(parents=True,exist_ok=True)
            os.replace(directory/entry['staged'],target)
        state['phase']='committed'
        atomic_json(directory/'state.json',state)
    except Exception:
        if (directory/'state.json').exists():
            recover(base)
        else:
            _clean(base)  # No production file changed before the journal.
        raise
    recover(base)
    return [dict(path=item['path'],sha256=item['evidence']['source_sha256']) for item in prepared]
