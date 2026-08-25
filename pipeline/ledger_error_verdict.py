"""Verdict leaf schema + gate-side re-derivation for the ledger-error-classifier lane.

This module is the deterministic enforcement gate for ledger-error-classifier
adjudication leaves (``RVQ_BLK_*`` review IDs).  It mirrors the SHAPE and
conventions of ``pipeline/verdict_leaf.py`` but differs in three key ways:

Divergences from verdict_leaf.py
---------------------------------
1. Vocabulary: ADJUDICATIONS replaces VERDICTS; verdict values name ledger-error
   types (extraction_wrong, parser_drift, filer_error, amended, false_flag,
   ambiguous) rather than the B1 tripartite (real_error, false_alarm, ambiguous).
2. Re-derivation gate: ``rederive_citations`` checks every ``culprit_citations``
   entry against the provenance ledger (DuckDB parameterized read; injectable
   ``ledger_df`` for tests).  B1 verdict_leaf instead checks that citations carry
   a quoted_text or table/row coordinate; ledger-error citations must reproduce
   from the ledger, field by field, within rel-tol 1e-9.  A verdict whose
   citations do not reproduce is REFUSED regardless of schema validity.
3. Tight codes: citations MUST reference a ``reason_code`` that is a provenance
   tight-fail code.  The set is defined locally (PROV_TIGHT_FAIL_LOCAL) and an
   equality test asserts parity with ``scripts/shadow_adapter.PROV_TIGHT_FAIL``
   (the source of truth).  Cross-tree import from pipeline is not an established
   pattern in this repo so the local-copy + equality-test approach is used.

Same conventions kept:
- validation-result dict shape: {"ok": bool, "errors": [...], "warnings": [...]}
- confidence float in [0,1] (hard error)
- escalation sibling: {review_id}.escalation.json counts as coverage in validate_dir
- fail-closed everywhere: missing ledger -> re-derivation refuses with a clear error
- ASCII-only messages (Windows cp1252)

ASCII-only logs/messages (Windows cp1252).
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline import config
from pipeline.bdc_cik_review import normalize_cik

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADJUDICATIONS = (
    "extraction_wrong",
    "parser_drift",
    "filer_error",
    "amended",
    "false_flag",
    "ambiguous",
)

REQUIRED_KEYS = ("review_id", "verdict", "confidence")

# Provenance tight-fail reason codes.
# Source of truth: scripts/shadow_adapter.PROV_TIGHT_FAIL.
# Not imported directly (cross-tree import is not an established pattern here).
# An equality test in tests/test_ledger_error_verdict.py::test_tight_codes_match_shadow_adapter
# asserts this local copy stays in sync.
_PROV_TIGHT_FAIL_LOCAL = frozenset({
    "filing_mismatch",
    "anchor_missing",
    "provenance_wrong",
    "source_unavailable",
    "transform_drift",
})

PROV_TIGHT_FAIL = _PROV_TIGHT_FAIL_LOCAL  # public alias

# Ambiguity bases (mirrors verdict_leaf semantics)
_AMBIGUITY_BASES = ("evidence_insufficient", "source_unavailable")

# Relative tolerance for numeric citation matching
_REL_TOL = 1e-9

# Column names used when loading the provenance ledger via DuckDB
_LEDGER_KEEP_COLS = (
    "row_id", "field", "reason_code",
    "declared_raw", "instance_raw", "published",
    "cik", "report_date",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _near_equal(a: Any, b: Any) -> bool:
    """Return True if a and b are equal within rel-tol 1e-9, or both None/NaN."""
    a_none = a is None or (isinstance(a, float) and math.isnan(a))
    b_none = b is None or (isinstance(b, float) and math.isnan(b))
    if a_none and b_none:
        return True
    if a_none != b_none:
        return False
    if not (_is_number(a) and _is_number(b)):
        return a == b
    if a == 0.0 and b == 0.0:
        return True
    denom = max(abs(float(a)), abs(float(b)))
    if denom == 0.0:
        return True
    return abs(float(a) - float(b)) / denom <= _REL_TOL


def _valid_culprit_citation(c: Any) -> bool:
    """A culprit citation must have row_id (str) and field (str).
    declared_raw/instance_raw/published may be numeric or None."""
    if not isinstance(c, dict):
        return False
    if not isinstance(c.get("row_id"), str) or not c["row_id"].strip():
        return False
    if not isinstance(c.get("field"), str) or not c["field"].strip():
        return False
    for num_key in ("declared_raw", "instance_raw", "published"):
        v = c.get(num_key)
        if v is not None and not _is_number(v):
            return False
    return True


def _err(errors: list[str], msg: str) -> None:
    errors.append(msg)


def _warn(warnings: list[str], msg: str) -> None:
    warnings.append(msg)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def validate_ledger_verdict(leaf: dict) -> dict[str, Any]:
    """Pure schema validation for a ledger-error-classifier verdict leaf.

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    Does NOT perform re-derivation (call rederive_citations for that).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(leaf, dict):
        return {"ok": False, "errors": ["verdict is not a JSON object"], "warnings": []}

    for k in REQUIRED_KEYS:
        if k not in leaf:
            _err(errors, f"missing required key: {k}")

    review_id = str(leaf.get("review_id") or "").strip()
    if not review_id:
        _err(errors, "review_id is empty")

    verdict = leaf.get("verdict")
    if verdict not in ADJUDICATIONS:
        _err(errors, f"verdict must be one of {ADJUDICATIONS}, got {verdict!r}")

    conf = leaf.get("confidence")
    if not _is_number(conf):
        _err(errors, "confidence must be a number")
    elif not (0.0 <= float(conf) <= 1.0):
        _err(errors, f"confidence out of [0,1]: {conf}")

    # -- verdict-specific rules --

    # extraction_wrong: requires non-empty mechanism AND >=1 valid citation
    if verdict == "extraction_wrong":
        _check_mechanism_required(leaf, errors)
        _check_citations_required(leaf, errors)

    # parser_drift: same as extraction_wrong PLUS drift_fingerprint
    elif verdict == "parser_drift":
        _check_mechanism_required(leaf, errors)
        _check_citations_required(leaf, errors)
        _check_drift_fingerprint(leaf, errors)

    # filer_error: requires filer_error_basis + >=1 citation; warn if escalate != true
    elif verdict == "filer_error":
        basis = str(leaf.get("filer_error_basis") or "").strip()
        if not basis:
            _err(errors, "filer_error requires non-empty filer_error_basis")
        _check_citations_required(leaf, errors)
        if leaf.get("escalate") is not True:
            _warn(warnings, "filer_error is an escalation-shaped outcome; set escalate=true")

    # amended: requires superseding_accession
    elif verdict == "amended":
        acc = str(leaf.get("superseding_accession") or "").strip()
        if not acc:
            _err(errors, "amended requires non-empty superseding_accession")

    # false_flag: no additional required keys

    # ambiguous: requires ambiguity_basis in the allowed set; source_unavailable -> escalate warn
    elif verdict == "ambiguous":
        basis = leaf.get("ambiguity_basis")
        if basis not in _AMBIGUITY_BASES:
            _err(errors,
                 f"ambiguous requires ambiguity_basis in {_AMBIGUITY_BASES}, got {basis!r}")
        elif basis == "source_unavailable" and leaf.get("escalate") is not True:
            _warn(warnings, "ambiguity_basis=source_unavailable should set escalate=true")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _check_mechanism_required(leaf: dict, errors: list[str]) -> None:
    mech = str(leaf.get("mechanism") or "").strip()
    if not mech:
        _err(errors, f"{leaf.get('verdict')} requires a non-empty mechanism")


def _check_citations_required(leaf: dict, errors: list[str]) -> None:
    cites = leaf.get("culprit_citations")
    if not isinstance(cites, list) or not cites:
        _err(errors, f"{leaf.get('verdict')} requires >=1 culprit_citations entry")
        return
    invalid = [i for i, c in enumerate(cites) if not _valid_culprit_citation(c)]
    if len(invalid) == len(cites):
        _err(errors, "culprit_citations present but none have valid shape (row_id + field required)")
    elif invalid:
        for i in invalid:
            _err(errors, f"culprit_citations[{i}] missing row_id or field")


def _check_drift_fingerprint(leaf: dict, errors: list[str]) -> None:
    fp = leaf.get("drift_fingerprint")
    if not isinstance(fp, dict):
        _err(errors, "parser_drift requires drift_fingerprint object")
        return
    if not str(fp.get("field") or "").strip():
        _err(errors, "drift_fingerprint.field must be a non-empty string")
    if not str(fp.get("transform_code") or "").strip():
        _err(errors, "drift_fingerprint.transform_code must be a non-empty string")
    row_ids = fp.get("affected_row_ids")
    if not isinstance(row_ids, list) or not row_ids:
        _err(errors, "drift_fingerprint.affected_row_ids must be a non-empty list")


# ---------------------------------------------------------------------------
# Re-derivation gate
# ---------------------------------------------------------------------------


def rederive_citations(
    leaf: dict,
    *,
    ledger_path: Path | None = None,
    ledger_df: pd.DataFrame | None = None,
    packet: "dict | None" = None,
) -> dict[str, Any]:
    """THE GATE (fail-closed).

    For every culprit_citations entry, confirm:
    - The (row_id, field) pair exists in the ledger.
    - Its reason_code is a tight fail code.
    - Every cited numeric (declared_raw / instance_raw / published) matches the
      ledger value within rel-tol 1e-9 (None matches NULL/NaN).
    - When ``packet`` is provided (keys: cik, report_date -- both normalized as
      elsewhere), every cited ledger row MUST match the packet's cik AND report_date.
      A citation whose ledger row belongs to a different (cik, report_date) is refused
      with "citation outside packet scope" even if all numeric values match.

    Any miss -> {"ok": False, "errors": [...]}. A verdict whose citations do not
    reproduce is REFUSED regardless of schema validity.

    ledger_df takes priority over ledger_path (injectable for tests).
    If neither is provided, config.PROVENANCE_LEDGER_FILE is used (DuckDB read).
    Missing ledger file -> fail-closed with a clear error (never passes silently).
    """
    errors: list[str] = []

    cites = leaf.get("culprit_citations")
    if not cites:
        # Verdicts without citations (false_flag, amended, ambiguous, etc.) pass trivially
        return {"ok": True, "errors": [], "warnings": []}

    # Normalise packet scope once (avoid repeating inside the loop)
    _packet_cik: str | None = None
    _packet_rd: str | None = None
    if packet is not None:
        _packet_cik = normalize_cik(str(packet.get("cik") or ""))
        _packet_rd = str(packet.get("report_date") or "").strip()

    # Collect cited (row_id, field) pairs to pass as filter to DuckDB path
    cited_pairs: list[tuple[str, str]] = []
    for c in cites:
        if isinstance(c, dict):
            rid = str(c.get("row_id") or "").strip()
            fld = str(c.get("field") or "").strip()
            if rid and fld:
                cited_pairs.append((rid, fld))

    # Build lookup: (row_id, field) -> ledger row dict.
    # Pass cited_pairs even when empty so _build_ledger_lookup/_duckdb_lookup can
    # refuse without doing a full ledger scan (all-malformed-citations guard).
    lookup = _build_ledger_lookup(
        ledger_path=ledger_path,
        ledger_df=ledger_df,
        errors=errors,
        cited_pairs=cited_pairs,
    )
    if errors:
        return {"ok": False, "errors": errors, "warnings": []}

    for i, cite in enumerate(cites):
        if not isinstance(cite, dict):
            _err(errors, f"culprit_citations[{i}] is not a dict")
            continue
        row_id = str(cite.get("row_id") or "").strip()
        field = str(cite.get("field") or "").strip()
        key = (row_id, field)

        if key not in lookup:
            _err(errors,
                 f"culprit_citations[{i}]: (row_id={row_id!r}, field={field!r}) not found in ledger")
            continue

        row = lookup[key]

        # Packet-scope check: cited ledger row must belong to the packet's (cik, report_date)
        if _packet_cik is not None:
            row_cik = normalize_cik(str(row.get("cik") or ""))
            row_rd = str(row.get("report_date") or "").strip()
            if row_cik != _packet_cik or row_rd != _packet_rd:
                _err(errors,
                     f"culprit_citations[{i}]: citation outside packet scope: "
                     f"cited (row_id={row_id!r}) belongs to "
                     f"cik={row_cik!r} report_date={row_rd!r} but packet is "
                     f"cik={_packet_cik!r} report_date={_packet_rd!r}")
                continue

        # reason_code must be a tight fail code
        rc = str(row.get("reason_code") or "").strip()
        if rc not in _PROV_TIGHT_FAIL_LOCAL:
            _err(errors,
                 f"culprit_citations[{i}]: reason_code {rc!r} is not a tight fail code"
                 f" (must be one of {sorted(_PROV_TIGHT_FAIL_LOCAL)})")

        # Check numerics
        for num_key in ("declared_raw", "instance_raw", "published"):
            cited_val = cite.get(num_key)
            ledger_val = _coerce_numeric(row.get(num_key))
            if not _near_equal(cited_val, ledger_val):
                _err(errors,
                     f"culprit_citations[{i}]: {num_key} mismatch: "
                     f"cited={cited_val!r} vs ledger={ledger_val!r}")

    # parser_drift: every cited citation row_id must appear in drift_fingerprint.affected_row_ids
    # (the fingerprint must cover its own evidence)
    if leaf.get("verdict") == "parser_drift" and not errors:
        fp = leaf.get("drift_fingerprint")
        if isinstance(fp, dict):
            affected = fp.get("affected_row_ids")
            if isinstance(affected, list):
                affected_set = set(str(x) for x in affected)
                for i, cite in enumerate(cites):
                    if not isinstance(cite, dict):
                        continue
                    row_id = str(cite.get("row_id") or "").strip()
                    if row_id and row_id not in affected_set:
                        _err(errors,
                             f"culprit_citations[{i}]: row_id {row_id!r} is not in "
                             f"drift_fingerprint.affected_row_ids; fingerprint must cover "
                             f"its own evidence")

    return {"ok": not errors, "errors": errors, "warnings": []}


def _coerce_numeric(v: Any) -> Any:
    """Convert a ledger value (possibly string or NaN) to float or None.

    bool is intentionally mapped to None rather than 0.0/1.0: a boolean in a
    numeric ledger column signals a schema anomaly (e.g. pandas reading "True"
    from a CSV that should contain a number).  Treating it as None causes a
    mismatch rather than silently accepting a fabricated 0.0 or 1.0 value.
    """
    if v is None:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) else v
    if isinstance(v, (int, bool)):
        return float(v) if not isinstance(v, bool) else None
    # String from CSV
    s = str(v).strip()
    if s in ("", "nan", "NaN", "None", "null"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _build_ledger_lookup(
    *,
    ledger_path: Path | None,
    ledger_df: pd.DataFrame | None,
    errors: list[str],
    cited_pairs: list[tuple[str, str]] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return a dict keyed by (row_id, field).  Populates errors on failure."""
    # Empty cited_pairs means all citations were malformed -- refuse without scanning
    if isinstance(cited_pairs, list) and len(cited_pairs) == 0:
        _err(errors, "re-derivation refused: citations present but all are malformed "
             "(no valid row_id+field pairs found)")
        return {}

    if ledger_df is not None:
        # Pre-filter ledger_df to cited pairs (vectorized membership check),
        # mirroring the DuckDB post-filter in _duckdb_lookup.
        # This prevents duplicate-detection from running on uncited (row_id, field) pairs.
        if cited_pairs:
            cited_set = set(cited_pairs)
            pair_series = list(
                zip(ledger_df["row_id"].astype(str), ledger_df["field"].astype(str))
            )
            mask = pd.array([p in cited_set for p in pair_series], dtype="boolean")
            ledger_df = ledger_df[mask].reset_index(drop=True)
        return _df_to_lookup(ledger_df, errors)

    # Resolve file path
    if ledger_path is None:
        ledger_path = config.PROVENANCE_LEDGER_FILE

    if not ledger_path.exists():
        _err(errors,
             f"re-derivation refused: provenance ledger not found at {ledger_path}")
        return {}

    return _duckdb_lookup(ledger_path, errors, cited_pairs=cited_pairs)


def _df_to_lookup(
    df: pd.DataFrame,
    errors: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Build (row_id, field) -> row dict from a DataFrame.

    Duplicate (row_id, field) rows where ALL cited numeric columns agree -> keep one.
    Duplicate rows that DIFFER on any of declared_raw / instance_raw / published ->
    append an ambiguous-evidence error and return an empty lookup for that key so the
    caller's gate refuses the citation.
    """
    _CITED_NUMS = ("declared_raw", "instance_raw", "published")

    # Vectorized group-by build: collect all rows per (row_id, field)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in df.to_dict(orient="records"):
        key = (str(rec.get("row_id") or ""), str(rec.get("field") or ""))
        grouped.setdefault(key, []).append(rec)

    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in grouped.items():
        if len(rows) == 1:
            lookup[key] = rows[0]
            continue
        # Multiple rows -- check whether all cited numeric columns agree
        first = rows[0]
        all_agree = True
        conflicting_col: str | None = None
        for col in _CITED_NUMS:
            v0 = _coerce_numeric(first.get(col))
            for r in rows[1:]:
                if not _near_equal(v0, _coerce_numeric(r.get(col))):
                    all_agree = False
                    conflicting_col = col
                    break
            if not all_agree:
                break
        if all_agree:
            # Duplicates agree on all cited columns -- accept the first row
            lookup[key] = first
        else:
            # Ambiguous evidence: duplicates differ -- emit error, leave key absent
            _err(
                errors,
                f"ambiguous ledger evidence: duplicate (row_id={key[0]!r},"
                f" field={key[1]!r}) rows differ on {conflicting_col!r};"
                f" citation refused",
            )
    return lookup


def _duckdb_lookup(
    ledger_path: Path,
    errors: list[str],
    cited_pairs: list[tuple[str, str]] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """DuckDB parameterized filtered read -- loads only cited (row_id, field) pairs.

    When cited_pairs is provided a WHERE clause restricts the scan to those pairs
    so the full 676MB ledger is not read into memory.
    An empty cited_pairs list is refused upstream in _build_ledger_lookup before
    this function is reached.
    """
    try:
        import duckdb
    except ImportError:
        _err(errors, "duckdb not available; cannot perform re-derivation")
        return {}

    safe_path = str(ledger_path).replace("\\", "/")
    col_list = ", ".join(f'"{c}"' for c in _LEDGER_KEEP_COLS)

    if cited_pairs:
        # Build parameterized WHERE: row_id IN (...) AND field IN (...)
        # then exact-pair filter applied in Python (avoids cross-product).
        row_ids = list({p[0] for p in cited_pairs})
        fields = list({p[1] for p in cited_pairs})
        # DuckDB positional params via duckdb.execute(sql, params)
        row_id_placeholders = ", ".join("?" for _ in row_ids)
        field_placeholders = ", ".join("?" for _ in fields)
        sql = (
            f"SELECT {col_list}"
            f" FROM read_csv_auto('{safe_path}', header=true)"
            f' WHERE "row_id" IN ({row_id_placeholders})'
            f' AND "field" IN ({field_placeholders})'
        )
        params = row_ids + fields
    else:
        sql = (
            f"SELECT {col_list}"
            f" FROM read_csv_auto('{safe_path}', header=true)"
        )
        params = []

    try:
        df = duckdb.execute(sql, params).fetchdf()
    except Exception as exc:
        _err(errors, f"re-derivation refused: DuckDB read of ledger failed: {exc}")
        return {}

    # Exact-pair post-filter when we used IN(...) (avoids cross-product false matches).
    # Use a two-column tuple merge via pandas MultiIndex membership check.
    if cited_pairs and not df.empty:
        cited_set = set(cited_pairs)
        pair_series = list(
            zip(df["row_id"].astype(str), df["field"].astype(str))
        )
        mask = pd.array([p in cited_set for p in pair_series], dtype="boolean")
        df = df[mask].reset_index(drop=True)

    return _df_to_lookup(df, errors)


# ---------------------------------------------------------------------------
# validate_dir -- batch intake
# ---------------------------------------------------------------------------


def validate_dir(
    verdicts_dir: Path,
    worklist_path: Path,
    *,
    ledger_path: Path | None = None,
    ledger_df: "pd.DataFrame | None" = None,
) -> dict[str, Any]:
    """Batch intake for ledger-error-classifier verdicts.

    Checks:
    - Every worklist review_id has a verdict OR an {review_id}.escalation.json sibling.
    - No unknown or duplicate review_ids.
    - Each verdict passes schema + re-derivation.

    Returns per-file results + summary counts.
    Read-only.

    ledger_df is injectable for tests (same short-circuit as rederive_citations).
    """
    verdicts_dir = Path(verdicts_dir)
    worklist_path = Path(worklist_path)

    # Missing worklist -> refuse (fail-closed; never silently open)
    if not worklist_path.exists():
        return {
            "ok": False,
            "errors": [f"worklist not found: {worklist_path}"],
            "verdicts_dir": str(verdicts_dir),
            "n_files": 0,
            "n_valid": 0,
            "n_error_files": 0,
            "cross_errors": [],
            "per_file": [],
        }

    # Load worklist -- build expected set AND packet map (review_id -> {cik, report_date})
    expected: set[str] = set()
    packet_map: dict[str, dict[str, str]] = {}
    with worklist_path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rid = str(row.get("review_id") or "").strip()
            if rid:
                expected.add(rid)
                cik_raw = str(row.get("cik") or "").strip()
                rd_raw = str(row.get("report_date") or "").strip()
                if cik_raw and rd_raw:
                    packet_map[rid] = {"cik": cik_raw, "report_date": rd_raw}

    cross_errors: list[str] = []
    per_file: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Collect all JSON verdict files (not escalation files)
    json_files = sorted(verdicts_dir.glob("*.json")) if verdicts_dir.exists() else []
    verdict_files = [p for p in json_files if not p.stem.endswith(".escalation")]

    # Track which expected ids are covered by escalation siblings
    escalation_covered: set[str] = set()
    esc_files = [p for p in json_files if p.stem.endswith(".escalation")]
    for esc in esc_files:
        # {review_id}.escalation.json -> stem is "review_id.escalation"
        # strip the .escalation suffix
        base = esc.stem
        if base.endswith(".escalation"):
            esc_rid = base[: -len(".escalation")]
            escalation_covered.add(esc_rid)

    for path in verdict_files:
        try:
            leaf = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            per_file.append({
                "file": path.name,
                "review_id": path.stem,
                "ok": False,
                "errors": [f"unreadable/invalid JSON: {exc}"],
                "warnings": [],
            })
            seen.add(path.stem)
            continue

        rid = str(leaf.get("review_id") or "").strip() or path.stem

        if rid in seen:
            cross_errors.append(f"duplicate verdict for review_id: {rid}")
        seen.add(rid)

        if expected and rid not in expected:
            cross_errors.append(f"unknown review_id (not in worklist): {rid}")

        schema_result = validate_ledger_verdict(leaf)
        # Pass packet for scope binding when the worklist provides cik+report_date
        gate_result = rederive_citations(
            leaf,
            ledger_path=ledger_path,
            ledger_df=ledger_df,
            packet=packet_map.get(rid),
        )

        combined_errors = schema_result["errors"] + gate_result["errors"]
        combined_warnings = schema_result["warnings"] + gate_result["warnings"]
        per_file.append({
            "file": path.name,
            "review_id": rid,
            "ok": not combined_errors,
            "errors": combined_errors,
            "warnings": combined_warnings,
        })

    # Coverage: expected not seen in verdict files but covered by escalation sibling
    covered = seen | escalation_covered
    for missing in sorted(expected - covered):
        cross_errors.append(f"missing verdict for review_id: {missing}")

    n_valid = sum(1 for r in per_file if r["ok"])
    n_error_files = len(per_file) - n_valid
    ok = n_error_files == 0 and not cross_errors

    return {
        "verdicts_dir": str(verdicts_dir),
        "n_files": len(verdict_files),
        "n_valid": n_valid,
        "n_error_files": n_error_files,
        "cross_errors": cross_errors,
        "per_file": per_file,
        "ok": ok,
    }
