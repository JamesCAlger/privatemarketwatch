"""The eight pilot CIKs, their fund-quarters, and pinned primary accessions.

Selection reuses the evidenced policy in scripts/run_context_census.py by reference
(its git blob is pinned). The pilot is stricter than that script in two ways, both
recorded in the inventory: it never settles a quarter by taking the latest of two
original filings, and a financially populated or incomplete amendment is ambiguous
evidence rather than a winner. Unsettled quarters are `unavailable` with every
candidate listed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess

from scripts.profile_pilot.paths import PilotPaths


@dataclass(frozen=True)
class CohortMember:
    cik: str
    filer: str
    q1: str
    q2: str
    rows_q1: int
    rows_q2: int
    spec_forms: str


# Spec section 5, verbatim. Form types in `spec_forms` are the spec's month-based
# expectation only; the recorded form always comes from the filings index.
PILOT_COHORT = (
    CohortMember("0001287750", "Ares Capital", "2022-09-30", "2022-12-31", 1037, 1059, "10-Q -> 10-K"),
    CohortMember("0001803498", "Blackstone Private Credit (BCRED)", "2022-09-30", "2022-12-31", 1099, 1354, "10-Q -> 10-K"),
    CohortMember("0001901037", "Stellus Private Credit", "2022-09-30", "2022-12-31", 62, 70, "10-Q -> 10-K"),
    CohortMember("0001715933", "TCW Direct Lending VII", "2023-03-31", "2023-06-30", 89, 84, "10-Q -> 10-Q"),
    CohortMember("0001920453", "Fidelity Private Credit", "2023-03-31", "2023-06-30", 26, 59, "10-Q -> 10-Q"),
    CohortMember("0001860424", "Onex Falcon Direct Lending", "2023-06-30", "2023-09-30", 80, 80, "10-Q -> 10-Q"),
    CohortMember("0001950803", "Stepstone Private Credit", "2023-09-30", "2023-12-31", 158, 282, "10-Q -> 10-K"),
    CohortMember("0001588272", "NexPoint Capital", "2023-09-30", "2023-12-31", 57, 54, "10-Q -> 10-K"),
)
PILOT_CIKS = tuple(m.cik for m in PILOT_COHORT)
LARGE_INSTANCE_CIKS = frozenset({"0001287750", "0001803498"})  # ruling R3

VERIFIED_ERA_QUARTER = "2026-03-31"
SIGNOFF_COMMIT = "eed082b"
VERIFIED_PASS_ID = "q1p3_20260831"
ATTESTATION = "data/reference/acceptance_attestations/2026-03-31.json"

CENSUS_SCRIPT = "scripts/run_context_census.py"
FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
AMENDMENTS = frozenset({"10-K/A", "10-Q/A"})


def fund_quarters(*, include_verified_era: bool = False) -> list[dict]:
    rows = []
    for member in PILOT_COHORT:
        rows.append(dict(cik=member.cik, quarter=member.q1, role="q1"))
        rows.append(dict(cik=member.cik, quarter=member.q2, role="q2"))
        if include_verified_era:
            rows.append(dict(cik=member.cik, quarter=VERIFIED_ERA_QUARTER, role="verified_era"))
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob(code_root: Path, relative: str) -> str:
    done = subprocess.run(["git", "hash-object", "--", relative], cwd=code_root,
                          capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError("git hash-object failed for " + relative + ": " + done.stderr.strip())
    return done.stdout.strip()


def load_index_candidates(paths: PilotPaths, *, ciks=PILOT_CIKS, quarters=None) -> list[dict]:
    """Distinct indexed 10-K/10-Q (and amendments) for the requested CIKs, CIK zero-padded.

    The index carries some filers twice (padded and unpadded CIK); identical rows
    collapse, conflicting metadata for one accession is kept and surfaces later.
    """
    from scripts.profile_pilot.paths import pilot_duckdb
    index = paths.output_root / "bdc_filings_index.csv"
    wanted = sorted(ciks)
    query = """SELECT DISTINCT lpad(cik, 10, '0') AS cik, accession_number, form_type,
                      filing_date, substr(report_date, 1, 10) AS report_date,
                      coalesce(xbrl_download_status, '') AS xbrl_download_status
               FROM read_csv(?, all_varchar=true, header=true)
               WHERE form_type IN ('10-K', '10-Q', '10-K/A', '10-Q/A')
                 AND lpad(cik, 10, '0') IN (SELECT unnest(?))"""
    params = [str(index), wanted]
    if quarters is not None:
        query += " AND substr(report_date, 1, 10) IN (SELECT unnest(?))"
        params.append(sorted(quarters))
    query += " ORDER BY 1, 5, 4, 2"
    con = pilot_duckdb(paths, memory_limit=None)
    try:
        cursor = con.execute(query, params)
        names = [d[0] for d in cursor.description]
        rows = [dict(zip(names, values)) for values in cursor.fetchall()]
    finally:
        con.close()
    if len(rows) > 5000:
        raise ValueError("pilot filing-index row bound exceeded")
    return [{k: (v or "") for k, v in row.items()} for row in rows]


def _instance_path(paths: PilotPaths, cik: str, accession: str) -> Path:
    return paths.cache_root / str(int(cik)) / (accession.replace("-", "") + ".xml")


def _candidate_record(paths: PilotPaths, row: dict) -> dict:
    path = _instance_path(paths, row["cik"], row["accession_number"])
    present = path.is_file()
    return dict(accession_number=row["accession_number"], form_type=row["form_type"],
                filing_date=row["filing_date"], report_date=row["report_date"],
                xbrl_download_status=row["xbrl_download_status"], path=str(path),
                cached=present, sha256=_sha256(path) if present else None,
                bytes=path.stat().st_size if present else None)


def _census():
    from scripts import run_context_census
    return run_context_census


def select_accession(paths: PilotPaths, cik: str, quarter: str, candidates: list[dict], *,
                     scanner=None, lease=None) -> dict:
    """Pin one primary accession for (cik, quarter) or return `unavailable` with evidence.

    `scanner(path, cik, quarter)` is only needed when amendments compete. It parses
    more than one instance (heavy under ruling R3), so passing a scanner requires a
    HELD shared-lease handle (`lease`, from protection.shared_heavy_lease); without
    one the call is refused before any work.
    """
    if scanner is not None:
        from scripts.profile_pilot.protection import assert_lease_held
        assert_lease_held(lease)
    exact = [r for r in candidates if r["cik"] == cik and r["report_date"] == quarter]
    records = [_candidate_record(paths, r) for r in exact]
    base = dict(cik=cik, quarter=quarter, candidates=records)
    if not exact:
        return dict(base, status="unavailable", reason="no_indexed_filing")
    if len({r["accession_number"] for r in exact}) != len(exact):
        return dict(base, status="unavailable", reason="conflicting_index_metadata")
    census = _census()
    obligation = dict(cik=cik, report_date=quarter, positive_source_accession="")
    if len(exact) == 1:
        accession, selection, _ = census.select_source(obligation, exact)
        chosen = records[0]
        if accession != chosen["accession_number"]:
            raise RuntimeError("census policy disagrees with the single indexed candidate")
        if not chosen["cached"]:
            return dict(base, status="unavailable", reason="source_not_cached")
        return dict(base, status="selected", selection=selection,
                    accession_number=chosen["accession_number"], form_type=chosen["form_type"],
                    filing_date=chosen["filing_date"], source_path=chosen["path"],
                    source_sha256=chosen["sha256"], source_bytes=chosen["bytes"])
    if scanner is None:
        return dict(base, status="unavailable", reason="selection_requires_amendment_scan")
    try:
        result = census.scan_selected_source(obligation, exact, cache_root=paths.cache_root,
                                             scanner=scanner)
    except (ValueError, OSError) as exc:
        return dict(base, status="unavailable", reason="selection_scan_failed",
                    error=type(exc).__name__ + ": " + str(exc))
    trace = result.get("source_selection", [])
    originals = [r for r in exact if r["form_type"] not in AMENDMENTS]
    chosen = next((r for r in records if r["accession_number"] == result["accession"]), None)
    settled = (chosen is not None and chosen["form_type"] not in AMENDMENTS
               and len(originals) == 1 and result.get("source_complete") is True
               and all(t["disposition"] == "amendment_without_target_instant" for t in trace[:-1]))
    if not settled:
        return dict(base, status="unavailable", reason="ambiguous_same_quarter_candidates",
                    source_selection=trace)
    return dict(base, status="selected", selection=result["selection"],
                accession_number=chosen["accession_number"], form_type=chosen["form_type"],
                filing_date=chosen["filing_date"], source_path=chosen["path"],
                source_sha256=chosen["sha256"], source_bytes=chosen["bytes"],
                source_selection=trace)


def primary_quarter_inventory(paths: PilotPaths, *, scanner=None, lease=None) -> dict:
    """Content of inventories/primary_quarter_inventory.json (16 primary + 8 verified-era)."""
    wanted = fund_quarters(include_verified_era=True)
    candidates = load_index_candidates(paths, quarters={r["quarter"] for r in wanted})
    entries = []
    for row in wanted:
        selected = select_accession(paths, row["cik"], row["quarter"], candidates,
                                    scanner=scanner, lease=lease)
        entries.append(dict(selected, role=row["role"]))
    counts = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    index = paths.output_root / "bdc_filings_index.csv"
    return dict(
        fund_quarters=entries, counts=counts,
        filings_index=dict(path=str(index), sha256=_sha256(index)),
        selection_policy=dict(
            reference=CENSUS_SCRIPT, git_blob=git_blob(paths.code_root, CENSUS_SCRIPT),
            functions=["select_source", "scan_selected_source"],
            pilot_restrictions=[
                "form_type is read from the filings index, never inferred from the month",
                "two same-quarter original filings are ambiguous, never settled by filing date",
                "an amendment is skipped only when the census scan proves it cover-only",
                "a populated or incomplete amendment makes the quarter unavailable",
                "multiple candidates without a scan are unavailable (scan may need the lease)",
            ]))
