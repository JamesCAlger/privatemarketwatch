"""Filer-profile pilot: explicit paths, run confinement and primary-quarter pinning."""
from __future__ import annotations

from contextlib import contextmanager
import csv
import hashlib
import os
import shutil
from pathlib import Path

import pytest

from scripts.profile_pilot import cohort, paths as pilot_paths
from scripts.profile_pilot.paths import PathError, resolve_paths

CODE_ROOT = Path(__file__).resolve().parents[1]
INDEX_COLUMNS = ["cik", "entity_name", "accession_number", "form_type", "filing_date",
                 "report_date", "primary_document", "xbrl_download_status", "xbrl_local_path"]


def build_fake_main(tmp_path: Path, *, index_rows=()) -> Path:
    """A separate fake main checkout: pipeline/, data/raw, data/output, frontend data."""
    main = tmp_path / "fake_main"
    (main / "pipeline" / "programme").mkdir(parents=True)
    shutil.copy2(CODE_ROOT / "pipeline" / "programme" / "runner.py",
                 main / "pipeline" / "programme" / "runner.py")
    (main / "data" / "raw" / "filings" / "bdc_xbrl").mkdir(parents=True)
    (main / "data" / "output").mkdir(parents=True)
    (main / "data" / "programme" / "candidates").mkdir(parents=True)
    (main / "frontend" / "public" / "data").mkdir(parents=True)
    (main / "data" / "output" / "existing.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (main / "frontend" / "public" / "data" / "site.json").write_text("{}", encoding="utf-8")
    write_index(main, index_rows)
    return main


def write_index(main: Path, rows) -> Path:
    path = main / "data" / "output" / "bdc_filings_index.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=INDEX_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in INDEX_COLUMNS})
    return path


def fake_paths(tmp_path: Path, *, index_rows=(), run_id="stagea-test"):
    main = build_fake_main(tmp_path, index_rows=index_rows)
    return resolve_paths(main_repo_root=main, data_root=main / "data",
                         code_root=CODE_ROOT, run_id=run_id)


def put_instance(main: Path, cik: str, accession: str, text: str = "<xbrl/>") -> Path:
    path = (main / "data" / "raw" / "filings" / "bdc_xbrl" / str(int(cik)) /
            (accession.replace("-", "") + ".xml"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@contextmanager
def held_lease(paths):
    """The REAL lease adapter against the fake main root, with discovery limited to self."""
    import psutil
    from scripts.profile_pilot.protection import shared_heavy_lease

    class Self:
        pid = os.getpid()
        info = dict(pid=os.getpid(), name="python.exe", cmdline=["python", "-m", "pytest"])

    original = psutil.process_iter
    psutil.process_iter = lambda attrs=None: iter([Self()])
    try:
        with shared_heavy_lease(paths, head="test") as lease:
            yield lease
    finally:
        psutil.process_iter = original


def index_row(cik, accession, form, filing_date, report_date, status="cached"):
    return dict(cik=cik, entity_name="Fake Fund", accession_number=accession, form_type=form,
                filing_date=filing_date, report_date=report_date, primary_document="x.htm",
                xbrl_download_status=status, xbrl_local_path="")


# ---------------------------------------------------------------- explicit paths

def test_resolve_paths_requires_every_root_explicitly(tmp_path):
    main = build_fake_main(tmp_path)
    for missing in ("main_repo_root", "data_root", "code_root", "run_id"):
        kwargs = dict(main_repo_root=main, data_root=main / "data", code_root=CODE_ROOT,
                      run_id="stagea-x")
        kwargs[missing] = None
        with pytest.raises(PathError):
            resolve_paths(**kwargs)


def test_resolve_paths_rejects_invalid_data_root_instead_of_falling_back(tmp_path):
    main = build_fake_main(tmp_path)
    empty = tmp_path / "empty_data"
    (empty / "raw").mkdir(parents=True)
    (empty / "output").mkdir()
    # raw/ and output/ exist but hold no filings index: not a dataset.
    with pytest.raises(PathError, match="bdc_filings_index"):
        resolve_paths(main_repo_root=main, data_root=empty, code_root=CODE_ROOT, run_id="stagea-x")
    with pytest.raises(PathError):
        resolve_paths(main_repo_root=main, data_root=tmp_path / "nope", code_root=CODE_ROOT,
                      run_id="stagea-x")


def test_resolve_paths_rejects_invalid_main_and_code_roots(tmp_path):
    main = build_fake_main(tmp_path)
    with pytest.raises(PathError, match="main_repo_root"):
        resolve_paths(main_repo_root=tmp_path, data_root=main / "data", code_root=CODE_ROOT,
                      run_id="stagea-x")
    with pytest.raises(PathError, match="code_root"):
        resolve_paths(main_repo_root=main, data_root=main / "data", code_root=main,
                      run_id="stagea-x")


@pytest.mark.parametrize("bad", ["", "StageA", "a/b", "..", "a b", "x" * 81, "a.b", "-lead"])
def test_run_id_must_be_a_valid_candidate_suffix(bad):
    with pytest.raises(PathError):
        pilot_paths.validate_run_id(bad)


def test_default_run_id_is_valid_and_lowercase():
    run_id = pilot_paths.default_run_id()
    assert pilot_paths.validate_run_id(run_id) == run_id
    assert run_id.startswith("stagea-") and run_id == run_id.lower()


def test_run_root_and_protected_roots_cover_main_and_worktree(tmp_path):
    paths = fake_paths(tmp_path)
    main = paths.main_repo_root
    assert paths.run_root == main / "data" / "pilot" / "filer_profile" / "stagea-test"
    assert paths.candidate_name == "pilot-filer-profile-stagea-test"
    roots = set(paths.protected_roots)
    assert main / "data" / "output" in roots
    assert main / "frontend" / "public" / "data" in roots
    assert CODE_ROOT / "data" / "output" in roots
    assert CODE_ROOT / "frontend" / "public" / "data" in roots


def test_discover_main_root_uses_git_common_dir_and_validates():
    main = pilot_paths.discover_main_root(CODE_ROOT)
    assert (main / "pipeline").is_dir() and (main / "data").is_dir()
    assert main != CODE_ROOT


# ---------------------------------------------------------------- confinement

@pytest.mark.parametrize("relative", ["../escape.json", "/abs.json", "a\\b.json", "c:x", "a/../b",
                                      "", "./a"])
def test_confined_rejects_escapes(tmp_path, relative):
    paths = fake_paths(tmp_path)
    with pytest.raises(PathError):
        pilot_paths.confined(paths, relative)


def test_confined_rejects_junction_inside_run_root(tmp_path):
    winapi = pytest.importorskip("_winapi")
    if not hasattr(winapi, "CreateJunction"):
        pytest.skip("junctions unavailable")
    paths = fake_paths(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.run_root.mkdir(parents=True)
    winapi.CreateJunction(str(outside), str(paths.run_root / "linked"))
    with pytest.raises(PathError):
        pilot_paths.write_json(paths, "linked/escape.json", {"a": 1})
    assert not (outside / "escape.json").exists()


def test_run_root_itself_reached_through_junction_is_rejected(tmp_path):
    winapi = pytest.importorskip("_winapi")
    if not hasattr(winapi, "CreateJunction"):
        pytest.skip("junctions unavailable")
    paths = fake_paths(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    winapi.CreateJunction(str(elsewhere), str(paths.data_root / "pilot"))
    with pytest.raises(PathError):
        pilot_paths.write_json(paths, "x.json", {"a": 1})
    assert not any(elsewhere.rglob("*.json"))


def test_write_json_is_ascii_and_write_once_refuses_overwrite(tmp_path):
    paths = fake_paths(tmp_path)
    target = pilot_paths.write_once_json(paths, "inventories/a.json", {"k": "v"})
    assert target.is_relative_to(paths.run_root)
    target.read_bytes().decode("ascii")
    with pytest.raises(PathError, match="overwrite"):
        pilot_paths.write_once_json(paths, "inventories/a.json", {"k": "other"})


# ---------------------------------------------------------------- cohort

def test_cohort_matches_spec_section_5():
    assert [m.cik for m in cohort.PILOT_COHORT] == [
        "0001287750", "0001803498", "0001901037", "0001715933",
        "0001920453", "0001860424", "0001950803", "0001588272"]
    by_cik = {m.cik: (m.q1, m.q2) for m in cohort.PILOT_COHORT}
    assert by_cik["0001287750"] == ("2022-09-30", "2022-12-31")
    assert by_cik["0001715933"] == ("2023-03-31", "2023-06-30")
    assert by_cik["0001860424"] == ("2023-06-30", "2023-09-30")
    assert by_cik["0001588272"] == ("2023-09-30", "2023-12-31")
    primary = cohort.fund_quarters()
    assert len(primary) == 16 and {r["role"] for r in primary} == {"q1", "q2"}
    everything = cohort.fund_quarters(include_verified_era=True)
    assert len(everything) == 24
    assert {r["quarter"] for r in everything if r["role"] == "verified_era"} == {"2026-03-31"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_single_candidate_pins_accession_actual_form_date_and_hash(tmp_path):
    # A September quarter filed as 10-K: the form comes from the index, not the month.
    rows = [index_row("1901037", "0000000001-22-000001", "10-K", "2022-11-04", "2022-09-30"),
            index_row("0001901037", "0000000001-22-000001", "10-K", "2022-11-04", "2022-09-30")]
    paths = fake_paths(tmp_path, index_rows=rows)
    xml = put_instance(paths.main_repo_root, "1901037", "0000000001-22-000001")
    candidates = cohort.load_index_candidates(paths, ciks=["0001901037"], quarters=["2022-09-30"])
    assert len(candidates) == 1  # padded and unpadded duplicate index rows collapse
    result = cohort.select_accession(paths, "0001901037", "2022-09-30", candidates)
    assert result["status"] == "selected"
    assert result["accession_number"] == "0000000001-22-000001"
    assert result["form_type"] == "10-K"
    assert result["filing_date"] == "2022-11-04"
    assert result["source_sha256"] == _sha(xml)
    assert result["candidates"][0]["sha256"] == _sha(xml)


def test_populated_primary_plus_cover_only_amendment_selects_primary(tmp_path):
    rows = [index_row("1287750", "0001287750-23-000010", "10-K", "2023-02-07", "2022-12-31"),
            index_row("1287750", "0001628280-23-010219", "10-K/A", "2023-03-31", "2022-12-31")]
    paths = fake_paths(tmp_path, index_rows=rows)
    original = put_instance(paths.main_repo_root, "1287750", "0001287750-23-000010", "<full/>")
    amendment = put_instance(paths.main_repo_root, "1287750", "0001628280-23-010219", "<cover/>")
    scanned = []

    def scanner(path, cik, quarter):
        scanned.append(Path(path).name)
        cover = Path(path) == amendment
        return dict(path=str(path), sha256=_sha(path), source_complete=True, errors=[],
                    document_period_ends=[quarter], target_instant_contexts=0 if cover else 900)

    candidates = cohort.load_index_candidates(paths, ciks=["0001287750"], quarters=["2022-12-31"])
    with held_lease(paths) as lease:
        result = cohort.select_accession(paths, "0001287750", "2022-12-31", candidates, scanner=scanner,
                                         lease=lease)
    assert result["status"] == "selected"
    assert result["accession_number"] == "0001287750-23-000010"
    assert result["form_type"] == "10-K"
    assert result["source_sha256"] == _sha(original)
    assert result["selection"] == "same_quarter_source_after_cover_only_amendment"
    assert [t["disposition"] for t in result["source_selection"]] == [
        "amendment_without_target_instant", "selected"]
    assert scanned[0] == amendment.name


def test_financially_populated_amendment_is_ambiguous_unavailable(tmp_path):
    rows = [index_row("1287750", "0001287750-23-000010", "10-K", "2023-02-07", "2022-12-31"),
            index_row("1287750", "0001628280-23-010219", "10-K/A", "2023-03-31", "2022-12-31")]
    paths = fake_paths(tmp_path, index_rows=rows)
    put_instance(paths.main_repo_root, "1287750", "0001287750-23-000010")
    put_instance(paths.main_repo_root, "1287750", "0001628280-23-010219")

    def scanner(path, cik, quarter):
        return dict(path=str(path), sha256=_sha(path), source_complete=True, errors=[],
                    document_period_ends=[quarter], target_instant_contexts=12)

    candidates = cohort.load_index_candidates(paths, ciks=["0001287750"], quarters=["2022-12-31"])
    with held_lease(paths) as lease:
        result = cohort.select_accession(paths, "0001287750", "2022-12-31", candidates, scanner=scanner,
                                         lease=lease)
    assert result["status"] == "unavailable"
    assert result["reason"] == "ambiguous_same_quarter_candidates"
    assert {c["accession_number"] for c in result["candidates"]} == {
        "0001287750-23-000010", "0001628280-23-010219"}
    assert "accession_number" not in result


def test_two_originals_are_not_resolved_by_picking_the_last(tmp_path):
    rows = [index_row("1715933", "0000950170-23-000001", "10-Q", "2023-05-10", "2023-03-31"),
            index_row("1715933", "0000950170-23-000002", "10-Q", "2023-05-20", "2023-03-31")]
    paths = fake_paths(tmp_path, index_rows=rows)
    for accession in ("0000950170-23-000001", "0000950170-23-000002"):
        put_instance(paths.main_repo_root, "1715933", accession)

    def scanner(path, cik, quarter):
        return dict(path=str(path), sha256=_sha(path), source_complete=True, errors=[],
                    document_period_ends=[quarter], target_instant_contexts=5)

    candidates = cohort.load_index_candidates(paths, ciks=["0001715933"], quarters=["2023-03-31"])
    with held_lease(paths) as lease:
        result = cohort.select_accession(paths, "0001715933", "2023-03-31", candidates, scanner=scanner,
                                         lease=lease)
    assert result["status"] == "unavailable"
    assert len(result["candidates"]) == 2


def test_multiple_candidates_without_a_scan_are_deferred_not_guessed(tmp_path):
    rows = [index_row("1287750", "0001287750-23-000010", "10-K", "2023-02-07", "2022-12-31"),
            index_row("1287750", "0001628280-23-010219", "10-K/A", "2023-03-31", "2022-12-31")]
    paths = fake_paths(tmp_path, index_rows=rows)
    put_instance(paths.main_repo_root, "1287750", "0001287750-23-000010")
    put_instance(paths.main_repo_root, "1287750", "0001628280-23-010219")
    candidates = cohort.load_index_candidates(paths, ciks=["0001287750"], quarters=["2022-12-31"])
    result = cohort.select_accession(paths, "0001287750", "2022-12-31", candidates)
    assert result["status"] == "unavailable"
    assert result["reason"] == "selection_requires_amendment_scan"
    assert all(c["sha256"] for c in result["candidates"])


@pytest.mark.parametrize("handle", ["none", "released", "forged"])
def test_scanner_without_a_held_lease_is_refused_before_parsing(tmp_path, handle):
    from scripts.profile_pilot.protection import LeaseInfo, LeaseRefused
    rows = [index_row("1287750", "0001287750-23-000010", "10-K", "2023-02-07", "2022-12-31"),
            index_row("1287750", "0001628280-23-010219", "10-K/A", "2023-03-31", "2022-12-31")]
    paths = fake_paths(tmp_path, index_rows=rows)
    put_instance(paths.main_repo_root, "1287750", "0001287750-23-000010")
    put_instance(paths.main_repo_root, "1287750", "0001628280-23-010219")
    scanned = []

    def scanner(path, cik, quarter):
        scanned.append(path)
        raise AssertionError("must not parse without the lease")

    lease = None
    if handle == "released":
        with held_lease(paths) as held:
            lease = held
    elif handle == "forged":
        lease = LeaseInfo(candidate=tmp_path / "c", lock_path=tmp_path / "heavy.lock",
                          acquired_utc="x")
    candidates = cohort.load_index_candidates(paths, ciks=["0001287750"], quarters=["2022-12-31"])
    with pytest.raises(LeaseRefused):
        cohort.select_accession(paths, "0001287750", "2022-12-31", candidates, scanner=scanner,
                                lease=lease)
    with pytest.raises(LeaseRefused):
        cohort.primary_quarter_inventory(paths, scanner=scanner, lease=lease)
    assert scanned == []


def test_uncached_or_unindexed_quarter_is_unavailable(tmp_path):
    rows = [index_row("1860424", "0000950170-22-024429", "10-Q", "2022-11-10", "2022-09-30",
                      status="not_found")]
    paths = fake_paths(tmp_path, index_rows=rows)
    candidates = cohort.load_index_candidates(paths, ciks=["0001860424"],
                                              quarters=["2022-09-30", "2022-12-31"])
    missing_cache = cohort.select_accession(paths, "0001860424", "2022-09-30", candidates)
    assert missing_cache["status"] == "unavailable"
    assert missing_cache["reason"] == "source_not_cached"
    no_filing = cohort.select_accession(paths, "0001860424", "2022-12-31", candidates)
    assert no_filing["reason"] == "no_indexed_filing"


def test_primary_quarter_inventory_records_policy_reference_and_every_fund_quarter(tmp_path):
    rows = [index_row("1901037", "0001558370-22-016375", "10-Q", "2022-11-04", "2022-09-30")]
    paths = fake_paths(tmp_path, index_rows=rows)
    put_instance(paths.main_repo_root, "1901037", "0001558370-22-016375")
    content = cohort.primary_quarter_inventory(paths)
    assert len(content["fund_quarters"]) == 24
    policy = content["selection_policy"]
    assert policy["reference"] == "scripts/run_context_census.py"
    assert len(policy["git_blob"]) == 40
    selected = [r for r in content["fund_quarters"] if r["status"] == "selected"]
    assert [(r["cik"], r["quarter"]) for r in selected] == [("0001901037", "2022-09-30")]
    assert content["counts"]["unavailable"] == 23
