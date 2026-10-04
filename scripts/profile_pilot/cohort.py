"""The eight pilot CIKs, their fund-quarters, and pinned primary accessions.

A single indexed candidate is pinned through scripts/run_context_census.py
`select_source` by reference (its git blob is pinned). Several same-quarter candidates
are settled by the pilot's own rule in scripts/profile_pilot/instance_select.py (owner
ruling 2026-10-04: prioritise the amendment unless it only carries the amended
datapoints), NOT by run_context_census.scan_selected_source: that function skips an
amendment only when it has no instant context at the report date, and a cover-only
10-K/A that dates dei:EntityPublicFloat at the period end has one, which left NexPoint
and TCW falsely ambiguous. The production-side script is left unchanged. The pilot
never settles a quarter by taking the latest of two original filings, and a partial
amendment is refused rather than chosen or skipped. Unsettled quarters are
`unavailable` with every candidate listed.
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
AMENDMENT_RULE_MODULE = "scripts/profile_pilot/instance_select.py"
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

    `scanner(path, cik, quarter)` is only needed when several candidates compete; it
    returns the instance_select.measure_instance fields. It parses more than one
    instance (heavy under ruling R3), so passing a scanner requires a HELD shared-lease
    handle (`lease`, from protection.shared_heavy_lease); without one the call is
    refused before any work. Every multi-candidate fund-quarter records each
    candidate's accession, form type, filing date, counts and ratio in
    `source_selection`, and the decision and its reason in `selection_rule`.
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
    from scripts.profile_pilot import instance_select
    measured = []
    try:
        for record in records:
            if record["cached"]:
                got = dict(scanner(Path(record["path"]), cik, quarter))
                if got.get("source_complete") and got.get("sha256") != record["sha256"]:
                    raise ValueError("measured bytes differ from the pinned candidate "
                                     + record["accession_number"])
            else:
                got = dict(source_complete=False, errors=["candidate instance is not cached"])
            measured.append(dict(got, accession_number=record["accession_number"],
                                 form_type=record["form_type"], filing_date=record["filing_date"],
                                 path=record["path"], sha256=record["sha256"], bytes=record["bytes"]))
        decision = instance_select.decide(quarter, measured)
    except (ValueError, OSError) as exc:
        return dict(base, status="unavailable", reason="selection_scan_failed",
                    error=type(exc).__name__ + ": " + str(exc))
    trace = decision.pop("candidates")
    if decision["status"] != "selected":
        return dict(base, status="unavailable", reason=decision["reason"],
                    source_selection=trace, selection_rule=decision)
    chosen = next(r for r in records if r["accession_number"] == decision["accession_number"])
    return dict(base, status="selected", selection=decision["reason"],
                accession_number=chosen["accession_number"], form_type=chosen["form_type"],
                filing_date=chosen["filing_date"], source_path=chosen["path"],
                source_sha256=chosen["sha256"], source_bytes=chosen["bytes"],
                source_selection=trace, selection_rule=decision)


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
        selection_policy=_selection_policy(paths))


def _selection_policy(paths: PilotPaths) -> dict:
    from scripts.profile_pilot import instance_select
    return dict(
        reference=CENSUS_SCRIPT, git_blob=git_blob(paths.code_root, CENSUS_SCRIPT),
        functions=["select_source"],
        amendment_rule=dict(
            module=AMENDMENT_RULE_MODULE, git_blob=git_blob(paths.code_root, AMENDMENT_RULE_MODULE),
            rule_version=instance_select.RULE_VERSION,
            full_candidate_min_pct=instance_select.FULL_CANDIDATE_MIN_PCT,
            threshold_basis="proxy in an empty gap: observed amendments carry 0% or >= 98% of the "
                            "original's target-quarter position facts; no partial amendment in sample",
            owner_ruling="2026-10-04: prioritise the amendment unless it only carries the amended "
                         "datapoints"),
        pilot_restrictions=[
            "form_type is read from the filings index, never inferred from the month",
            "amendment means the index form type; dei:AmendmentFlag is recorded, never read",
            "two same-quarter original filings are refused, never settled by filing date",
            "an amendment with zero target-quarter non-dei numeric facts is cover-only and skipped",
            "the latest-filed full candidate is selected; a full amendment beats the original",
            "a candidate strictly between 0% and the full threshold makes the quarter unavailable",
            "multiple candidates without a scan are unavailable (scan may need the lease)",
        ])


ALL_ROLE_PREFIX = "all:"
ALL_QUARTERS_THROUGH = VERIFIED_ERA_QUARTER
MAX_CACHED_FILES_PER_CIK = 500


def all_quarter_inventory(paths: PilotPaths, *, scanner=None, lease=None) -> dict:
    """Every indexed 10-K/10-Q fund-quarter of the eight pilot CIKs (Task B2-2a).

    Window per CIK: from its earliest quarter with a cached instance of an indexed
    filing through ALL_QUARTERS_THROUGH; the Stage B cohort quarters are always
    included (so q1 / q2 / verified_era stay identifiable), every other quarter has
    role `all:<report_date>`. Selection is `select_accession` unchanged: one instance
    per fund-quarter, amendments without a (leased) scan are unavailable with reason
    `selection_requires_amendment_scan`. Indexed quarters outside the window and
    cached instances that match no indexed accession are recorded, never dropped
    silently. Rows are sorted by (cik, quarter); (cik, role) is unique.
    """
    if scanner is not None:
        from scripts.profile_pilot.protection import assert_lease_held
        assert_lease_held(lease)
    candidates = load_index_candidates(paths)
    cohort_roles = {(r["cik"], r["quarter"]): r["role"] for r in fund_quarters(include_verified_era=True)}
    wanted, window, reconciliation = [], {}, {}
    for cik in sorted(PILOT_CIKS):
        mine = [r for r in candidates if r["cik"] == cik]
        indexed = sorted({r["report_date"] for r in mine})
        cached = sorted({r["report_date"] for r in mine
                         if _instance_path(paths, cik, r["accession_number"]).is_file()
                         and r["report_date"] <= ALL_QUARTERS_THROUGH})
        first = cached[0] if cached else None
        inside = {q for q in indexed if first is not None and first <= q <= ALL_QUARTERS_THROUGH}
        quarters = sorted(inside | {q for (c, q) in cohort_roles if c == cik})
        window[cik] = dict(first=first, last=ALL_QUARTERS_THROUGH,
                           rule="earliest quarter with a cached indexed instance through "
                                + ALL_QUARTERS_THROUGH + "; cohort quarters always included",
                           indexed_quarters_before_window=[q for q in indexed if first is None or q < first],
                           indexed_quarters_after_window=[q for q in indexed if q > ALL_QUARTERS_THROUGH])
        known = {_instance_path(paths, cik, r["accession_number"]).name for r in mine}
        folder = paths.cache_root / str(int(cik))
        files = sorted(folder.glob("*.xml")) if folder.is_dir() else []
        if len(files) > MAX_CACHED_FILES_PER_CIK:
            raise ValueError("pilot cached-instance bound exceeded for " + cik)
        reconciliation[cik] = dict(cached_files=len(files),
                                   unindexed_cached_files=[str(f) for f in files if f.name not in known])
        for quarter in quarters:
            wanted.append(dict(cik=cik, quarter=quarter,
                               role=cohort_roles.get((cik, quarter), ALL_ROLE_PREFIX + quarter)))
    entries = []
    for row in wanted:
        selected = select_accession(paths, row["cik"], row["quarter"], candidates,
                                    scanner=scanner, lease=lease)
        entries.append(dict(selected, role=row["role"]))
    keys = [(e["cik"], e["role"]) for e in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("all-quarter inventory produced a duplicate (cik, role)")
    counts = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    index = paths.output_root / "bdc_filings_index.csv"
    return dict(
        fund_quarters=entries, counts=counts, quarters_mode="all", window=window,
        cache_reconciliation=reconciliation,
        filings_index=dict(path=str(index), sha256=_sha256(index)),
        selection_policy=_selection_policy(paths))
