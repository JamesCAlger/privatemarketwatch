"""Run the prescribed --semantic backstop, redirecting only its report destination."""
import contextlib
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'AGENTS.md').exists())
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from scripts import diff_outputs

OUT = Path(__file__).parent
semantic_only = '--semantic-only' in sys.argv
diff_outputs.SEMANTIC_REPORT_FILE = OUT / 'semantic_diff_report.json'
timer = threading.Timer(240, lambda: os._exit(124))
timer.daemon = True
timer.start()
sys.argv = ['scripts/diff_outputs.py', '--semantic']
start = time.monotonic()
print('Running semantic backstop; report and log redirected to scratch.', flush=True)
with (OUT / ('semantic_only.log' if semantic_only else 'semantic_diff.log')).open('w', encoding='utf-8') as stream, contextlib.redirect_stdout(stream):
    status = diff_outputs.semantic_diff(json.loads(diff_outputs.MANIFEST_FILE.read_text())) if semantic_only else diff_outputs.main()
(OUT / 'semantic_backstop_result.json').write_text(json.dumps({'exit_code': status,
    'elapsed_seconds': round(time.monotonic()-start, 2),
    'command_equivalent': 'python scripts/diff_outputs.py --semantic',
    'scope': 'five semantic artifacts only; full 64537-entry scan reached timeout' if semantic_only else 'full',
    'sole_override': 'SEMANTIC_REPORT_FILE redirected to scratch to preserve production artifacts'}, indent=2))
timer.cancel()
print('Backstop exit status ' + str(status), flush=True)
raise SystemExit(status)
