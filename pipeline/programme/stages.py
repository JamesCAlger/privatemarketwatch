"""Bounded compatibility stages; financial conventions remain unchanged."""
from __future__ import annotations

from contextlib import ExitStack
import logging
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

from pipeline.programme.artifacts import STAGE_CSVS, finalize_pair, verify_audit
from pipeline.programme.core import ContractError, atomic_json, read_json, sha


def execute(attempt, reads, *, preflight_stage=None):
    import duckdb
    import pandas as pd
    from pipeline import config, utils
    attempt = Path(attempt)
    workspace = attempt / 'workspace'
    inputs = read_json(attempt / 'inputs.json')
    stage = preflight_stage or inputs['stage']
    bundle = attempt / 'bundle' / stage if preflight_stage else attempt / 'bundle'
    bundle.mkdir(parents=True, exist_ok=True)
    if config.PROJECT_ROOT.resolve() != workspace.resolve():
        raise ContractError('Pipeline escaped frozen workspace')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    original_connect = duckdb.connect
    original_companion = utils.write_parquet_companion
    connections = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.execute('SET threads=' + ('4' if stage == 'unified' else '2'))
        connection.execute("SET memory_limit='" + ('6GB' if stage == 'unified' else '4GB') + "'")
        connection.execute("SET temp_directory='" + (attempt / 'temp').as_posix().replace("'", "''") + "'")
        # Closed native-read universe: frozen runtime workspace plus local outputs.
        # No HTTP/S3/extensions, parameterized path tricks, ATTACH or relation API bypass.
        connection.execute('SET allowed_directories=' + repr([workspace.as_posix(), (attempt / 'bundle').as_posix(), (attempt / 'temp').as_posix()]))
        connection.execute('SET autoinstall_known_extensions=false')
        connection.execute('SET autoload_known_extensions=false')
        connection.execute('SET enable_external_access=false')
        connection.execute('SET lock_configuration=true')
        connections.append(connection)
        return connection

    def strict_companion(path, strict=None):
        return original_companion(path, strict=True)

    started = time.monotonic()
    times = {}
    with ExitStack() as stack:
        stack.enter_context(patch.object(duckdb, 'connect', connect))
        stack.enter_context(patch.object(utils, 'write_parquet_companion', strict_companion))
        if stage == 'unified':
            from pipeline.unified_holdings import build_unified_holdings
            if preflight_stage:
                from pipeline.programme.preflight import sample_raw_inputs
                with connect() as connection:
                    bdc, nport, sampling = sample_raw_inputs(config, connection)
                empty_rules = attempt / 'temp/preflight-empty-rules'
                empty_rules.mkdir(exist_ok=True)
                frame = build_unified_holdings(bdc_df=bdc, nport_df=nport,
                    agent_rules_dir=empty_rules, b2_corrections_dir=empty_rules)
                times['sampling'] = sampling
            else:
                frame = build_unified_holdings()
            times['build_seconds'] = time.monotonic() - started
            row_count = len(frame)
            del frame
        elif stage == 'identity':
            from pipeline import entity_resolution, position_matching
            entity_resolution.build_entity_lookup(config.UNIFIED_HOLDINGS_FILE, enrich=True)
            times['entity_seconds'] = time.monotonic() - started
            frame = pd.read_csv(config.UNIFIED_HOLDINGS_FILE, dtype=str)
            tick = time.monotonic()
            matches = position_matching.match_positions(frame, contested_assignment=True)
            times['matching_seconds'] = time.monotonic() - tick
            tick = time.monotonic()
            frame, matches = position_matching.assign_position_ids(frame, matches,
                contested_assignment=True, use_registry=False)
            times['position_ids_seconds'] = time.monotonic() - tick
            frame.to_csv(config.UNIFIED_HOLDINGS_FILE, index=False)
            matches.to_csv(config.POSITION_MATCHES_FILE, index=False)
            row_count = len(frame)
            times['matches'] = len(matches)
            del frame, matches
        elif stage == 'evidence':
            from pipeline import pik_status
            status = pik_status.build_position_pik_status()
            if isinstance(status, tuple):
                status, _ = status
            summary, transitions = pik_status.build_pik_schedule_proxy_outputs(status)
            row_count = len(status)
            times.update(summary_rows=len(summary), terms_transitions=len(transitions))
            del status, summary, transitions
        else:
            raise ContractError('Unknown supported stage')
        if preflight_stage and not 0 < row_count <= 2000:
            raise ContractError('Preflight output outside its explicit 1-2000 row bound')
        for connection in connections:
            connection.close()
        metadata = {}
        with connect() as connection:
            if stage == 'unified' and not preflight_stage:
                verify_audit(config.OUTPUT_DIR / 'agent_fix_application_audit.csv', connection)
            names = ('private_markets_holdings.csv',) if preflight_stage and stage == 'unified' else STAGE_CSVS[stage]
            for name in names:
                source = config.OUTPUT_DIR / name
                if not source.is_file():
                    raise ContractError('Required output missing: ' + name)
                metadata[name] = finalize_pair(source, connection)
                shutil.copy2(source, bundle / name)
                shutil.copy2(source.with_suffix('.parquet'), bundle / Path(name).with_suffix('.parquet'))
        atomic_json(bundle / 'summary.json', dict(stage=stage, rows=row_count, times=times,
            input_fingerprint=inputs['identity']['fingerprint'], parents=inputs['identity']['parents'],
            artifacts_metadata=metadata, elapsed_seconds=time.monotonic() - started,
            identity_policy=dict(contested_assignment=True, use_registry=False),
            financial_convention='legacy cash leg; no income formula migration', quality='not_evaluated'))
    # Python imports that completed before the audit hook are included explicitly.
    imported = {str(Path(module.__file__).absolute()) for module in list(sys.modules.values())
                if getattr(module, '__file__', None)}
    actual_reads = sorted(reads | imported)
    atomic_json(attempt / 'bundle/read_ledger.json', dict(python_paths=actual_reads,
        native_read_universe='entire frozen workspace; DuckDB external access disabled with explicit directory allowlist',
        native_io_boundary='elevated command sandbox and Windows low-integrity token',
        note='Controller hashes external runtime dependencies and verifies frozen read assets before sealing.'))
    print('Stage worker finished; controller must verify and seal', flush=True)
