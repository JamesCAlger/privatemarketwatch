"""Run the prescribed full semantic CLI safely inside the diagnostic sandbox."""
import argparse
import os
from pathlib import Path
import sys
import threading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-name', required=True)
    args = parser.parse_args()
    if not args.job_name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.job_name):
        raise ValueError('Portable diagnostic job name required')
    root = Path(__file__).resolve().parents[2]
    job = root/'scratch/2026-09-10_verification_investigation'/args.job_name
    assert (job/'request.json').is_file()
    
    sys.stdout.reconfigure(encoding='ascii', errors='backslashreplace')
    sys.stderr.reconfigure(encoding='ascii', errors='backslashreplace')
    from scripts import diff_outputs
    diff_outputs.SEMANTIC_REPORT_FILE = job/'bundle/full_byte_semantic_report.json'
    sys.argv = ['scripts/diff_outputs.py', '--semantic']
    print('Running scripts/diff_outputs.py --semantic; report redirected to scratch', flush=True)
    code = diff_outputs.main()
    
    return code


if __name__ == '__main__':
    raise SystemExit(main())
