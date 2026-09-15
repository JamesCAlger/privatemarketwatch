"""Explicitly carry a reviewed rule retirement into a new immutable candidate."""
from pathlib import Path
import shutil

from pipeline.programme.core import ContractError,contained,read_json,sha


def include_retirement(root,frozen,review_path):
    root,frozen=Path(root).resolve(),Path(frozen).resolve()
    review_path=Path(review_path).resolve()
    allowed=[root/'data/overrides'/name for name in ('agent_b2_corrections','agent_investigate_rules')]
    if not any(review_path.is_relative_to(folder) for folder in allowed) or not review_path.name.startswith('_retired_'):
        raise ContractError('Retirement must name a reviewed B2 or investigation retirement record')
    review_sha=sha(review_path)
    review=read_json(review_path)
    if review.get('status')!='retired' or not review.get('mechanism') or not review.get('sources'):
        raise ContractError('Retirement requires mechanism and source evidence')
    previous=review.get('previous_file','')
    archived=review.get('original_file','')
    if (not previous.endswith('.json') or Path(previous).name!=previous or previous.startswith('_')
        or not archived.startswith('_retired_') or Path(archived).name!=archived or not archived.endswith('.json')):
        raise ContractError('Invalid original or archived rule filename')
    relative=review_path.parent.relative_to(root)
    old=contained(frozen,(relative/previous).as_posix())
    source=contained(root,(relative/archived).as_posix())
    expected=review.get('original_sha256')
    if not expected or sha(old)!=expected or sha(source)!=expected:
        raise ContractError('Retirement does not match the exact frozen original rule')
    for evidence in review['sources']:
        path=contained(root,evidence.get('path',''))
        if sha(path)!=evidence.get('sha256'):
            raise ContractError('Retirement source evidence changed')
    decision=review.get('decision')
    decision_source=decision_destination=None
    if decision is not None:
        decision_source=contained(root,decision.get('path',''))
        if not decision.get('sha256') or sha(decision_source)!=decision['sha256']:
            raise ContractError('Retirement policy decision changed')
        decision_destination=contained(frozen,decision['path'],existing=False)
    destination=contained(frozen,(relative/archived).as_posix(),existing=False)
    record=contained(frozen,review_path.relative_to(root).as_posix(),existing=False)
    if destination.exists() or record.exists():
        raise ContractError('Retirement destination already exists')
    # Rename only this checked file in the newly copied, unsealed snapshot.
    old.rename(destination)
    shutil.copy2(review_path,record)
    if decision_source is not None:
        decision_destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(decision_source,decision_destination)
        if sha(decision_destination)!=decision['sha256']:
            raise ContractError('Retirement decision changed while freezing')
    if sha(destination)!=expected or sha(record)!=review_sha or sha(review_path)!=review_sha:
        raise ContractError('Retirement changed while freezing')
    return dict(path=(relative/archived).as_posix(),sha256=expected,
        retired_path=(relative/previous).as_posix(),review_path=review_path.relative_to(root).as_posix(),
        review_sha256=review_sha,role='source-reviewed retirement; original bytes preserved')
