"""Bind existing deterministic legacy gate inputs to an isolated evaluation.

Source queues reuse the production residual adapter and queue builder. Staged
investigation state is copied for inspection only: no rule is applied, gated,
promoted, or represented as approved by this collector.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
from unittest.mock import patch

import duckdb

from pipeline.programme.core import ContractError, atomic_json, contained, now, read_json, sha


def _sealed_source(directory: Path, holdings: Path) -> dict:
    seal = read_json(directory / "complete.json")
    names = (
        "summary.json",
        "diagnostics/source_reconciliation_residual_classification.csv",
        "diagnostics/source_reconciliation_source_only_detail.csv",
    )
    for name in names:
        path = contained(directory, name)
        if seal.get(name) != sha(path):
            raise ContractError("Source gate input is absent or changed: " + name)
    summary = read_json(directory / "summary.json")
    if summary.get("holdings_sha256") != sha(holdings):
        raise ContractError("Source gate inputs belong to different holdings")
    return {name: seal[name] for name in names}


def collect_source_queue(holdings: Path, source_directory: Path, output: Path) -> dict:
    """Materialize the legacy source-blocker queue from fresh sealed results."""
    from scripts import shadow_adapter
    from pipeline import review_queue

    holdings, source_directory, output = map(Path, (holdings, source_directory, output))
    sources = _sealed_source(source_directory, holdings)
    holdings_hash = sha(holdings)
    code = {str(Path(module.__file__).resolve()): sha(Path(module.__file__))
            for module in (shadow_adapter, review_queue)}
    code[str(Path(__file__).resolve())] = sha(Path(__file__))
    output.mkdir(parents=True, exist_ok=False)
    ledger = output / "source_blocker_ledger.csv"
    with patch.multiple(shadow_adapter,
        SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE=source_directory / next(
            name for name in sources if name.endswith("residual_classification.csv")),
        SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE=source_directory / next(
            name for name in sources if name.endswith("source_only_detail.csv"))):
        query = shadow_adapter._source_recon_select()
    if query is None:
        raise ContractError("Fresh source residual inputs are unavailable")
    with duckdb.connect(config={"threads": 2, "memory_limit": "-1"}) as con:
        # Keep the existing at-risk calculation, confidence labels and queue
        # semantics. The source adapter already combines its two residual views.
        con.execute("CREATE TABLE source_ledger AS " + query)
        con.execute("""COPY (SELECT *,
            'source_blocking_' || coalesce(src_confidence,'na') AS confidence,
            coalesce(src_confidence IN ('high','medium'),false) AS surface
            FROM source_ledger ORDER BY cik,period,rule_name) TO ? (HEADER)""", [str(ledger)])
    result = review_queue.build_review_queue(ledger_path=ledger, output_dir=output,
        holdings_path=holdings)
    if _sealed_source(source_directory, holdings) != sources or sha(holdings) != holdings_hash:
        raise ContractError("Source gate inputs changed during collection")
    if any(sha(Path(path)) != value for path, value in code.items()):
        raise ContractError("Source queue collector changed during execution")
    result.update(holdings_sha256=holdings_hash, source_inputs=sources,
        source_directory=str(source_directory.resolve()), code_sha256=code,
        scope="Existing source-blocker metric; no source completeness certification or remediation campaign")
    atomic_json(output / "collection.json", result)
    atomic_json(output / "complete.json", {p.name: sha(p) for p in output.iterdir() if p.is_file()})
    return result


def _investigation_inventory(directory: Path, cohort: set[str]) -> dict:
    if not directory.exists():
        return dict(present=False, cik_directories=[], files={})
    if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
        raise ContractError("Investigation store is not a plain directory")
    folders, files, seen = [], {}, set()
    for child in sorted(directory.iterdir()):
        if not child.is_dir() or not re.fullmatch(r"\d{1,10}", child.name):
            continue
        cik = child.name.zfill(10)
        if cik not in cohort:
            continue
        if cik in seen:
            raise ContractError("Investigation store repeats a normalized CIK")
        seen.add(cik)
        if child.is_symlink() or child.is_junction():
            raise ContractError("Investigation CIK directory is aliased")
        folders.append(child.name)
        rules = child / "rules"
        if rules.exists() and (not rules.is_dir() or rules.is_symlink() or rules.is_junction()):
            raise ContractError("Investigation rules directory is aliased")
        selected = list(rules.glob("*.json")) + list(child.glob("gate.*.json"))
        if (child / "apply_audit.json").exists():
            selected.append(child / "apply_audit.json")
        for path in sorted(selected):
            name = path.relative_to(directory).as_posix()
            files[name] = sha(contained(directory, name))
    return dict(present=True, cik_directories=folders, files=files)


def snapshot_investigations(source: Path, output: Path, holdings: Path, cohort: set[str]) -> dict:
    """Capture existing apply/gate/rule records without conducting investigations."""
    source, output, holdings = map(Path, (source, output, holdings))
    cohort = {str(cik).zfill(10) for cik in cohort}
    before = _investigation_inventory(source, cohort)
    holdings_hash = sha(holdings)
    output.mkdir(parents=True, exist_ok=False)
    store = output / "store"
    if before["present"]:
        store.mkdir()
        for name in before["cik_directories"]:
            (store / name).mkdir()
        for name in before["files"]:
            destination = store / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
        if _investigation_inventory(store, cohort) != before:
            raise ContractError("Investigation snapshot differs from source")
    if _investigation_inventory(source, cohort) != before or sha(holdings) != holdings_hash:
        raise ContractError("Investigation inputs changed during capture")
    result = dict(format_version=1, captured_utc=now(), source_directory=str(source.resolve()),
        directory=str(store.resolve()), cohort=sorted(cohort), inventory=before,
        holdings_sha256=holdings_hash, collector_sha256=sha(Path(__file__)),
        scope="Observed staged operational state; no candidate application, gate approval or promotion is implied")
    atomic_json(output / "investigation_inputs.json", result)
    return result


def verify_investigations(manifest: Path, holdings: Path, cohort: set[str]) -> Path | None:
    manifest, holdings = Path(manifest), Path(holdings)
    result = read_json(manifest)
    if result.get("format_version") != 1 or result.get("holdings_sha256") != sha(holdings):
        raise ContractError("Investigation evidence belongs to different holdings or contract")
    expected_cohort = sorted({str(cik).zfill(10) for cik in cohort})
    if result.get("cohort") != expected_cohort:
        raise ContractError("Investigation evidence belongs to a different cohort")
    directory = Path(result["directory"]).resolve()
    if directory != (manifest.parent / "store").resolve():
        raise ContractError("Investigation evidence points outside its private snapshot")
    if _investigation_inventory(directory, set(result["cohort"])) != result["inventory"]:
        raise ContractError("Investigation evidence changed after capture")
    return directory if result["inventory"]["present"] else None


def bound_legacy_inputs(evidence, holdings: Path, cohort: set[str], paths: dict) -> set[str]:
    """A bound receipt must identify the input actually used by the legacy gate."""
    bound = set()
    for name in ("ledger", "queue", "audit", "investigate"):
        recorded = evidence.path("legacy_" + name, candidate_bound=True)
        if recorded is None:
            continue
        actual = Path(paths[name]).resolve()
        if name == "investigate":
            store = verify_investigations(recorded, holdings, cohort)
            if actual != (recorded.parent / "store").resolve():
                raise ContractError("Legacy investigation input differs from its evidence snapshot")
            if store is not None:
                bound.add(name)
        elif actual != recorded.resolve():
            raise ContractError("Legacy " + name + " input differs from its evidence record")
        else:
            bound.add(name)
    evidence.verify()
    return bound
