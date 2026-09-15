"""Final holdings/identity serialization, after all value and identity writers.

Stage complete typed pairs in the destination directory, verify them, and only
then replace public paths. The finalizer is also used inside isolated candidate
workspaces; it does not grant permission to publish or refresh a baseline.
"""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import shutil
import tempfile

import duckdb
import pandas as pd

from pipeline.programme.artifacts import SCHEMAS, finalize_pair
from pipeline.programme.core import atomic_json,read_json,sha,digest


def project_artifact(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    schema = SCHEMAS[name]
    missing = set(schema) - set(frame.columns)
    if missing:
        raise ValueError("Final artifact missing columns (" + name + "): " + ", ".join(sorted(missing)))
    return frame[list(schema)]


def validate_holdings_identity(frame: pd.DataFrame, *, require_position_ids=True):
    from pipeline.unified_holdings import validate_final_holdings_schema
    validate_final_holdings_schema(frame)
    for name in ("row_id", "row_id_basis"):
        if name not in frame.columns or frame[name].fillna("").astype(str).str.strip().eq("").any():
            raise ValueError("Final holdings have missing " + name)
    if frame["row_id"].duplicated().any():
        raise ValueError("Final holdings row_id is not unique")
    if require_position_ids and frame["position_id"].fillna("").astype(str).str.strip().eq("").any():
        raise ValueError("Final holdings position IDs are incomplete; export is blocked")
    from pipeline.position_matching import _validate_unique_position_ids
    _validate_unique_position_ids(frame)


def write_final_identity(holdings: pd.DataFrame, matches: pd.DataFrame, *,
                         holdings_file: Path, matches_file: Path,
                         auxiliary_files: tuple[Path, ...] = ()):
    """Validate both completed frames and stage both pairs before any replacement.

    A serialization/parity failure leaves the previous paths intact. Publication
    coordination still owns the release lock and completion marker: two legacy
    filenames are not an atomic multi-file release pointer.
    """
    holdings_file, matches_file = Path(holdings_file).resolve(), Path(matches_file).resolve()
    if holdings_file == matches_file or holdings_file.parent != matches_file.parent:
        raise ValueError("Final identity artifacts must share one output directory")
    from pipeline.accounting_scope import annotate
    holdings = annotate(holdings)
    validate_holdings_identity(holdings)
    holdings = project_artifact(holdings, "private_markets_holdings.csv")
    matches = matches.copy()
    if matches.empty and "position_id" not in matches.columns:
        matches["position_id"] = pd.Series(dtype=str)
    matches = project_artifact(matches, "position_matches.csv")
    if not matches.empty and matches["position_id"].fillna("").astype(str).str.strip().eq("").any():
        raise ValueError("Final match rows have missing position IDs")
    destination = holdings_file.parent
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".final-identity-", dir=destination) as directory:
        staged = Path(directory).resolve()
        if not staged.is_relative_to(destination):
            raise ValueError("Finalizer staging escaped output directory")
        metadata = {}
        with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
            for name, frame in (("private_markets_holdings.csv",holdings),("position_matches.csv",matches)):
                path = staged / name
                frame.to_csv(path, index=False)
                metadata[name] = finalize_pair(path, con)
            for source in auxiliary_files:
                source = Path(source)
                if source.name in ("private_markets_holdings.csv", "position_matches.csv"):
                    raise ValueError("Auxiliary artifact conflicts with final identity")
                shutil.copy2(source, staged / source.name)
                if source.name in SCHEMAS:
                    metadata[source.name] = finalize_pair(staged / source.name, con)
        identity_path=staged/'identity_contract.json'
        if identity_path.is_file():
            identity=read_json(identity_path)
            if sha(staged/'identity_registry.duckdb')!=identity['output_registry_sha256']:
                raise ValueError('Staged identity registry differs from its contract')
            identity['holdings_sha256']=sha(staged/'private_markets_holdings.csv')
            identity['matches_sha256']=sha(staged/'position_matches.csv')
            atomic_json(identity_path,identity)
            atomic_json(staged/'holdings_release.json',dict(release_id=identity['release_id'],
                holdings_sha256=identity['holdings_sha256'],financial_contract=identity['financial_contract'],
                identity_contract=identity['identity_contract']))
            prior=destination/'identity_registry.duckdb'
            if prior.is_file():
                archive=destination/'identity_registry_history'/ (sha(prior)+'.duckdb')
                archive.parent.mkdir(exist_ok=True)
                if not archive.exists(): shutil.copy2(prior,archive)
                if sha(prior)!=sha(archive): raise ValueError('Prior registry archive differs')
        # All writers are closed and every pair is verified before replacement.
        for source, target in ((staged / "private_markets_holdings.csv",holdings_file),
                               (staged / "position_matches.csv",matches_file)):
            os.replace(source, target)
            os.replace(source.with_suffix(".parquet"), target.with_suffix(".parquet"))
        for source in auxiliary_files:
            source = staged / Path(source).name
            os.replace(source, destination / source.name)
            if source.name in SCHEMAS:
                os.replace(source.with_suffix(".parquet"), destination / source.with_suffix(".parquet").name)
        if (staged/'holdings_release.json').is_file():
            os.replace(staged/'holdings_release.json',destination/'holdings_release.json')
    return holdings, matches, metadata


def _finish_identity(working: Path, destination: Path, *, rebuild_entities: bool,
                     bdc_raw_df=None, use_registry=False, registry_path=None,
                     retirements_path=None):
    """Complete an isolated intermediate and send all final pairs to one writer."""
    from pipeline import entity_resolution, position_matching
    registry_outputs = []
    if use_registry:
        # Keep even the opt-in legacy registry private until final identity
        # validates. Explicit paths must never update a prior registry early.
        from pipeline import config
        registry_target = Path(registry_path or config.POSITION_ID_REGISTRY_FILE).resolve()
        retirement_target = Path(retirements_path or config.POSITION_ID_RETIREMENTS_FILE).resolve()
        registry_directory = working.parent / "registry"
        registry_directory.mkdir()
        registry_path = registry_directory / "registry.csv"
        retirements_path = registry_directory / "retirements.csv"
        if registry_target.exists():
            shutil.copy2(registry_target, registry_path)
        registry_outputs = [(registry_path, registry_target), (retirements_path, retirement_target)]
    if rebuild_entities:
        entity_resolution.build_entity_lookup(
            working, enrich=True, lookup_path=working.parent / "entity_lookup.csv",
            stats_path=working.parent / "entity_resolution_stats.csv")
    holdings = pd.read_csv(working, dtype=str)
    from pipeline import config
    if config.GICS_ENRICHMENT_DECISIONS_FILE.is_file():
        from pipeline.sector_enrichment import replay
        previous_audit=destination.parent/'sector_enrichment_audit.csv'
        holdings,sector_audit=replay(holdings,config.GICS_ENRICHMENT_DECISIONS_FILE,config.GICS_REFERENCE_FILE,
            prior_audit=pd.read_csv(previous_audit,dtype=str) if previous_audit.is_file() else None)
        sector_audit.to_csv(working.parent/"sector_enrichment_audit.csv",index=False)
    else:
        pd.DataFrame(columns=['row_id','decision_id','value','status','derivation']).to_csv(
            working.parent/'sector_enrichment_audit.csv',index=False)
    # An empty extraction still has the full final artifact contract.
    if holdings.empty:
        for name in ("row_id", "row_id_basis"):
            if name not in holdings:
                holdings[name] = pd.Series(dtype=str)
    # A v2 frame without retained source states cannot become legacy cash data.
    from pipeline.financial_finalization import prepare_artifact
    state_file=working.parent/'financial_state_audit.csv'
    if not state_file.is_file(): state_file=destination.parent/'financial_state_audit.csv'
    holdings,states=prepare_artifact(holdings,working.parent,prior_states_file=state_file)
    # Restrict matcher inputs to the physical contract. Incidental helper
    # columns such as quarter must not shadow the matcher's derived keys.
    holdings=project_artifact(holdings,'private_markets_holdings.csv')
    # Bind the release to the prepared values, including admitted enrichment.
    # The earlier intermediate file predates those writers.
    holdings.to_csv(working,index=False)
    prior_registry=destination.parent/'identity_registry.duckdb'
    if not prior_registry.is_file(): prior_registry=config.REFERENCE_DIR/'identity_registry.duckdb'
    if not prior_registry.is_file(): prior_registry=None
    input_fingerprint=digest(dict(working_sha256=sha(working),
        raw_matching_sha256=(digest(dict(columns=list(bdc_raw_df.columns),dtypes=[str(t) for t in bdc_raw_df.dtypes],
            values=hashlib.sha256(pd.util.hash_pandas_object(bdc_raw_df,index=True).values.tobytes()).hexdigest()))
            if bdc_raw_df is not None else sha(config.BDC_HOLDINGS_FILE) if config.BDC_HOLDINGS_FILE.is_file() else None),
        field_states_sha256=sha(working.parent/'financial_state_audit.csv'),
        prior_registry_sha256=sha(prior_registry) if prior_registry else None,
        implementation={name:sha(Path(__file__).parent/name) for name in (
            'holdings_finalizer.py','financial_conventions.py','financial_context.py','monetary_fx.py',
            'financial_finalization.py','identity_finalization.py','durable_identity.py',
            'matching_contract.py','position_matching.py','sector_enrichment.py')},
        fx_reference_sha256=sha(Path(__file__).parents[1]/'scripts/programme_closeout/fx.py'),
        contract='financial-contract.v2/durable-identity.v1'))
    release_id='holdings-'+input_fingerprint
    matches = position_matching.match_positions(
        holdings, bdc_raw_df=bdc_raw_df, output_file=working.parent / "position_matches.csv",
        contested_assignment=position_matching.CONTESTED_ASSIGNMENT_DEFAULT)
    holdings, matches = position_matching.assign_position_ids(
        holdings, matches, contested_assignment=position_matching.CONTESTED_ASSIGNMENT_DEFAULT,
        edges_file=working.parent / "position_id_edges.csv", use_registry=use_registry,
        registry_path=registry_path, retirements_path=retirements_path)
    from pipeline.identity_finalization import finish
    holdings,matches=finish(holdings,matches,states,directory=working.parent,release_id=release_id,
        build_fingerprint=input_fingerprint,input_registry=prior_registry)
    auxiliaries = tuple(p for p in working.parent.iterdir() if p.is_file()
                        and p.suffix in ('.csv','.json','.duckdb')
                        and p.name not in ('private_markets_holdings.csv', 'position_matches.csv'))
    holdings, matches, _ = write_final_identity(
        holdings, matches, holdings_file=destination,
        matches_file=destination.parent / "position_matches.csv", auxiliary_files=auxiliaries)
    for staged, target in registry_outputs:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, target)
    return holdings, matches


def build_final_holdings(bdc_df=None, nport_df=None, *, output_file=None,
                         agent_rules_dir=None, b2_corrections_dir=None,
                         use_registry=False, registry_path=None, retirements_path=None):
    """Cached unified rebuild, with entity/position assignment before publication.

    Intermediate holdings, orphan reports and correction audits stay in a private
    directory until final identity and all typed pairs validate. Candidate builds
    pass an isolated output path and frozen configuration for their inputs.
    """
    from pipeline import config
    from pipeline.unified_holdings import build_unified_holdings
    destination = Path(output_file or config.UNIFIED_HOLDINGS_FILE).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".holdings-build-", dir=destination.parent) as directory:
        working = Path(directory) / "private_markets_holdings.csv"
        build_unified_holdings(
            bdc_df, nport_df, output_file=working,
            orphan_file=working.parent / config.UNIVERSE_ORPHAN_HOLDINGS_FILE.name,
            agent_rules_dir=agent_rules_dir, b2_corrections_dir=b2_corrections_dir)
        return _finish_identity(working, destination, rebuild_entities=True,
            bdc_raw_df=bdc_df, use_registry=use_registry, registry_path=registry_path,
            retirements_path=retirements_path)


def finalize_existing_holdings(*, holdings_file=None, rebuild_entities=False,
                               bdc_raw_df=None, use_registry=False, registry_path=None,
                               retirements_path=None):
    """Entity/returns command path: isolate mutations and finalize both pairs."""
    from pipeline import config
    destination = Path(holdings_file or config.UNIFIED_HOLDINGS_FILE).resolve()
    with tempfile.TemporaryDirectory(prefix=".holdings-identity-", dir=destination.parent) as directory:
        working = Path(directory) / "private_markets_holdings.csv"
        shutil.copy2(destination, working)
        return _finish_identity(working, destination, rebuild_entities=rebuild_entities,
            bdc_raw_df=bdc_raw_df, use_registry=use_registry, registry_path=registry_path,
            retirements_path=retirements_path)


def finalize_enriched_holdings(frame, *, holdings_file=None):
    """Publish an enrichment through the same final identity/pair writer."""
    from pipeline import config
    destination=Path(holdings_file or config.UNIFIED_HOLDINGS_FILE).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".holdings-enrichment-",dir=destination.parent) as directory:
        working=Path(directory)/"private_markets_holdings.csv"
        frame.to_csv(working,index=False)
        return _finish_identity(working,destination,rebuild_entities=False)


def require_exportable_identity(*, holdings_file=None, returns_file=None):
    """Read-only export guard using the existing RI07 rule, without side effects."""
    from pipeline import config
    from pipeline.validation_rules import RULE_REGISTRY, _load_tables
    holdings_file = Path(holdings_file or config.UNIFIED_HOLDINGS_FILE)
    returns_file = Path(returns_file or config.POSITION_RETURNS_FILE)
    if not holdings_file.is_file():
        raise ValueError("Export blocked: final holdings are missing")
    with duckdb.connect(config={"threads": 2, "memory_limit": "-1"}) as con:
        blank = con.execute("""SELECT count(*) FROM read_csv(?,all_varchar=true)
            WHERE nullif(trim(position_id),'') IS NULL""", [str(holdings_file)]).fetchone()[0]
        if blank:
            raise ValueError("Export blocked: final holdings contain blank position IDs")
        if returns_file.exists():
            rule = RULE_REGISTRY["RI07"]
            missing = _load_tables(con, [rule], {"holdings": holdings_file, "position_returns": returns_file})
            if missing or con.execute("SELECT count(*) FROM (" + rule.sql + ")").fetchone()[0]:
                raise ValueError("Export blocked by RI07: rebuild returns from final holdings")
