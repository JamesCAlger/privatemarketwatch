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
    assert args.job_name == 'semantic-after-v1', 'This is a bounded investigation helper'
    root = Path(__file__).resolve().parents[2]
    job = root/'scratch/2026-09-10_verification_investigation'/args.job_name
    assert (job/'request.json').is_file()
    timer = threading.Timer(180, lambda: os._exit(124)); timer.daemon = True; timer.start()
    sys.stdout.reconfigure(encoding='ascii', errors='backslashreplace')
    sys.stderr.reconfigure(encoding='ascii', errors='backslashreplace')
    from scripts import diff_outputs
    diff_outputs.SEMANTIC_REPORT_FILE = job/'bundle/full_byte_semantic_report.json'
    sys.argv = ['scripts/diff_outputs.py', '--semantic']
    print('Running scripts/diff_outputs.py --semantic; 180-second cap; report redirected to scratch', flush=True)
    code = diff_outputs.main()
    timer.cancel()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
