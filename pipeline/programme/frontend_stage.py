"""Run the actual public export inside the native candidate's output boundary."""
from contextlib import ExitStack
import json
from pathlib import Path
import time
from unittest.mock import patch
import zipfile

from pipeline.programme.core import atomic_json, record, sha


def export_candidate(attempt):
    from pipeline import config, export_frontend
    from pipeline.export import helpers, fund_exports
    attempt=Path(attempt)
    output=attempt/'temp/frontend-data'
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    with ExitStack() as stack:
        for module in (export_frontend,helpers,fund_exports):
            stack.enter_context(patch.object(module,'FRONTEND_DATA_DIR',output))
        export_frontend.export_all()
    history=json.loads((output/'holdings_history/manifest.json').read_text(encoding='utf-8'))
    files=[record(output,p.relative_to(output).as_posix()) for p in sorted(output.rglob('*')) if p.is_file()]
    archive=config.OUTPUT_DIR/'frontend_data.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as target:
        for item in files:
            info=zipfile.ZipInfo(item['path'],date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            with target.open(info,'w',force_zip64=True) as destination, (output/item['path']).open('rb') as source:
                import shutil
                shutil.copyfileobj(source,destination)
    result=dict(history=history,artifacts=files,archive_sha256=sha(archive),
        measurements=dict(export_seconds=time.monotonic()-started,files=len(files),
            total_bytes=sum(item['bytes'] for item in files)),adoption='not_adopted')
    atomic_json(config.OUTPUT_DIR/'frontend_export.json',result)
    return result
