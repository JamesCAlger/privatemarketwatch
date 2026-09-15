"""Restore and verify a completed real bundle without using its original workspace."""
import argparse,json,shutil,time
from pathlib import Path
from scripts.programme_closeout.candidate import sha,atomic_json,read_bundle
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);a=p.parse_args()
    candidate=a.candidate.resolve();source=candidate/'attempts/unified-01/bundle'
    manifest=json.loads((candidate/'snapshot.json').read_text());read_bundle(source,manifest['input_fingerprint'])
    dest=ROOT/'data/programme/restores'/candidate.name/'unified-bundle'
    if dest.exists():raise ValueError('Choose a new restore, never overwrite it')
    total=sum(p.stat().st_size for p in source.iterdir() if p.is_file())
    started=time.monotonic();shutil.copytree(source,dest)
    restored=read_bundle(dest,manifest['input_fingerprint'])
    assert sha(source/'result.json')==sha(dest/'result.json')
    atomic_json(ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09/restore_proof.json',dict(
        result='pass',source=str(source.relative_to(ROOT)),restored=str(dest.relative_to(ROOT)),bytes=total,
        artifacts=len(restored['artifacts']),seconds=time.monotonic()-started,
        result_sha256=sha(dest/'result.json'),input_fingerprint=manifest['input_fingerprint'],
        mode='Physical copy, no hard links; independently verify every artifact and final manifest. No pipeline recomputation or adoption.',
        limits='Completed-result restore. Mid-SQL work is intentionally not resumable; restart that failed stage from frozen inputs.'))
    print('Real bundle restore verified',flush=True)
if __name__=='__main__':main()
