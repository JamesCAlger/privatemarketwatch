"""Deterministic parent-side preflight for Agent B2 remediation worker dispatch.

The B2 analog of ``scripts/agent_b/dispatch_preflight.py``. Keyed on a ``(cik, fix_class)``
packet (from ``run_remediation discover``). For one batch it: reads the packet worklist,
validates each packet's source verdict(s) are real_error with grounding, resolves the
source bundles (the worker re-grounds the FIX against them), acquires a per-packet lock,
writes one blinded-to-nothing remediation prompt per packet, and emits the manifest the
dispatcher consumes.

Non-LLM, cache-only, read-only on production; writes only under the batch dir
(prompts/manifest). Reuses the B1 worker-env fixes (absolute interpreter + import dirs).
ASCII-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline import config
from pipeline.bdc_cik_review import normalize_cik
from pipeline.correction_leaf import TEMPLATE_REGISTRY
from scripts.agent_b import review_lock
from scripts.agent_b.dispatch_preflight import WORKER_PYTHON, EVIDENCE_CLI, _worker_read_dirs
from scripts.agent_b2.run_remediation import POLICY_FIX_CLASSES, implemented_fix_classes

DEFAULT_REVIEW_QUEUE = config.OUTPUT_DIR / "review_queue" / "review_queue.csv"

_CIK_RE = re.compile(r"^\d{1,10}$")

DEFAULT_BASE = config.OUTPUT_DIR / "agent_b2"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"
DEFAULT_CORRECTIONS = DEFAULT_BASE / "corrections"
DEFAULT_CONTRACT = "docs/adjudication_architecture/B2_remediation_contract.md"
VALIDATOR = config.PROJECT_ROOT / "scripts" / "agent_b2" / "validate_corrections.py"


class PreflightError(RuntimeError):
    pass


def _batch_dir(base_dir: Path, batch_id: str) -> Path:
    return base_dir / "batch" / batch_id


def _read_worklist(batch_dir: Path) -> list[dict]:
    path = batch_dir / "worklist.csv"
    if not path.exists():
        raise PreflightError(f"missing worklist: {path} (run run_remediation discover first)")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise PreflightError(f"empty worklist: {path}")
    return rows


def _load_verdict(rid: str, verdicts_dir: Path) -> dict:
    p = (verdicts_dir / f"{rid}.json").resolve()
    if not p.exists():
        raise PreflightError(f"{rid}: source verdict missing: {p}")
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{rid}: invalid verdict JSON: {exc}") from exc
    if v.get("verdict") != "real_error":
        raise PreflightError(f"{rid}: source verdict is {v.get('verdict')!r}, not real_error")
    return v


def _load_bundle(rid: str, bundles_dir: Path) -> tuple[Path, dict]:
    p = (bundles_dir / f"{rid}.json").resolve()
    if not p.exists():
        raise PreflightError(f"{rid}: source bundle missing: {p}")
    try:
        bundle = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{rid}: invalid bundle JSON: {exc}") from exc
    bundle_rid = str(bundle.get("review_id") or "").strip()
    if bundle_rid and bundle_rid != rid:
        raise PreflightError(f"{rid}: bundle review_id mismatch: {bundle_rid!r}")
    return p, bundle


def _has_coord(c: dict) -> bool:
    return c.get("table_index") is not None and c.get("row_index") is not None


def _citations_block(verdicts: list[dict]) -> str:
    # validate_corrections accepts a citation with a quote OR a table/row coordinate;
    # coordinate-only citations must survive into the prompt (q4b2t4b lesson: Ares'
    # coordinate-only verdict produced an empty block and a guaranteed-invalid leaf).
    lines = []
    for v in verdicts:
        for c in (v.get("culprit_citations") or []):
            q = str(c.get("quoted_text") or "").strip()
            coord = f"t{c.get('table_index')}/r{c.get('row_index')}"
            if q:
                lines.append(f"  - [{coord}] {q[:160]}")
            elif _has_coord(c):
                lines.append(f"  - [{coord}] (coordinate-only citation; no quote in verdict)")
    return "\n".join(lines) if lines else "  (no quoted citations; re-ground from source)"


def _citations_json(verdicts: list[dict]) -> str:
    cites = []
    seen = set()
    for v in verdicts:
        for c in (v.get("culprit_citations") or []):
            cite = {
                "table_index": c.get("table_index"),
                "row_index": c.get("row_index"),
                "quoted_text": str(c.get("quoted_text") or "").strip()[:240],
            }
            key = (cite["table_index"], cite["row_index"], cite["quoted_text"])
            if (cite["quoted_text"] or _has_coord(cite)) and key not in seen:
                cites.append(cite)
                seen.add(key)
    return json.dumps(cites[:8], indent=2)


def _bundle_identifier_rows(bundles: list[dict]) -> list[dict]:
    """Distinct holdings-side identifier candidates from the bundles' evidence items
    (e.g. the ``holdings_slice`` rows the flag fired on). These carry the UNIFIED
    holdings text a row_selector must equality-match -- filing-citation text often
    differs (normalization, suffixes) and produces a no-op selector (the 20
    selector-noop gate refusals of q4b2exp round 3)."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for b in bundles:
        for item in (b.get("evidence_items") or []):
            data = item.get("data")
            rows = data if isinstance(data, list) else [data]
            for r in rows:
                if not isinstance(r, dict):
                    continue
                name = str(r.get("issuer_name") or "").strip()
                ident = str(r.get("bdc_investment_identifier") or "").strip()
                rid = str(r.get("row_id") or "").strip()
                if not (name or ident or rid):
                    continue
                rec = {"issuer_name": name, "bdc_investment_identifier": ident,
                       "row_id": rid,
                       "report_date": str(r.get("report_date") or "").strip()}
                key = (name, ident, rid, rec["report_date"])
                if key not in seen:
                    seen.add(key)
                    out.append(rec)
    return out


def _verify_identifiers(rows: list[dict], cik: str,
                        holdings_path: Path | None) -> list[dict]:
    """Annotate each candidate with ``match_count`` against the CURRENT unified
    holdings for the CIK, using the applier's own selector semantics (strip + string
    equality, AND over provided keys). ``match_count`` is None when the holdings file
    is unavailable (candidates stay usable but unverified)."""
    if not rows:
        return rows
    if holdings_path is None or not Path(holdings_path).exists():
        for r in rows:
            r["match_count"] = None
        return rows
    import duckdb
    con = duckdb.connect()
    src = str(holdings_path).replace("'", "''")
    reader = ("read_parquet" if str(holdings_path).endswith(".parquet")
              else "read_csv_auto")
    # row_id only exists on holdings built >= 2026-08-21; select it when present
    # so candidates ground on the stable id, but stay usable on older frames.
    have = {r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM {reader}('{src}') LIMIT 0").fetchall()}
    sel = ["issuer_name", "bdc_investment_identifier", "report_date"]
    if "row_id" in have:
        sel.append("row_id")
    df = con.execute(
        f"SELECT {', '.join(sel)} FROM {reader}('{src}') "
        f"WHERE ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') = ?",
        [str(cik).lstrip("0")]).fetchdf()
    cols = {c: df[c].fillna("").astype(str).str.strip() for c in df.columns}
    for r in rows:
        mask = None
        for key in ("row_id", "issuer_name", "bdc_investment_identifier", "report_date"):
            want = r.get(key) or ""
            if not want or key not in cols:
                continue
            m = cols[key] == want.strip()
            mask = m if mask is None else (mask & m)
        r["match_count"] = int(mask.sum()) if mask is not None else 0
    return rows


def _stage_holdings_csv(cik: str, holdings_path: Path | None,
                        staging_dir: Path) -> Path | None:
    """Stage the per-CIK, ALL-quarters extracted holdings slice as a CSV the worker
    can read (analyst mode). Every column survives -- the worker needs the extracted
    values (fair_value, rates, principal, row_id) to compare against the filing, not
    just the identifiers. Returns None when the holdings frame is unavailable
    (workers then see an explicit 'unavailable' note, never a silent gap)."""
    if holdings_path is None or not Path(holdings_path).exists():
        return None
    staging_dir.mkdir(parents=True, exist_ok=True)
    out = staging_dir / f"{cik}_holdings.csv"
    import duckdb
    con = duckdb.connect()
    src = str(holdings_path).replace("'", "''")
    reader = ("read_parquet" if str(holdings_path).endswith(".parquet")
              else "read_csv_auto")
    dst = str(out).replace("'", "''")
    cik_digits = str(cik).lstrip("0")  # cik already validated against _CIK_RE upstream
    con.execute(
        f"COPY (SELECT * FROM {reader}('{src}') "
        f"WHERE ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') "
        f"= '{cik_digits}' ORDER BY report_date, issuer_name) "
        f"TO '{dst}' (HEADER, DELIMITER ',')")
    return out


def _filing_html_paths(bundles: list[dict]) -> list[str]:
    """Resolve the cached source filing HTML path(s) the bundles' evidence points at,
    so the analyst worker can open the raw document directly (the evidence CLI remains
    the preferred, parsed view). Path construction is deterministic and cache-only;
    a missing cache is annotated, not hidden."""
    from pipeline.html_soi_evidence import (
        _html_path, resolve_accessions_from_index, resolve_accessions_from_rows)
    from scripts.review_agent.evidence_cli import _ENGINE_SOURCE, _rows_from_bundle
    out: list[str] = []
    seen: set[str] = set()
    for b in bundles:
        source = _ENGINE_SOURCE.get(str(b.get("engine") or ""), "BDC")
        accs = resolve_accessions_from_rows(_rows_from_bundle(b))
        if not accs:
            accs = resolve_accessions_from_index(
                source, str(b.get("cik") or ""), str(b.get("report_date") or ""))
        for acc in accs[:2]:
            p = _html_path(source, str(b.get("cik") or ""), acc)
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(key if p.exists() else f"{key}  [NOT CACHED]")
    return out


_MAX_GROUNDED_IDENTIFIERS = 20


def _grounding_block(rows: list[dict]) -> str:
    if not rows:
        return ("  (no holdings-side identifier rows in the source bundles; copy selector "
                "text with extra care -- a selector that matches no holdings rows is "
                "refused by the gate as a no-op)")
    lines = []
    for r in rows[:_MAX_GROUNDED_IDENTIFIERS]:
        parts = []
        if r.get("row_id"):
            parts.append(f"row_id: {json.dumps(r['row_id'])}")
        if r.get("issuer_name"):
            parts.append(f"issuer_name: {json.dumps(r['issuer_name'])}")
        if r.get("bdc_investment_identifier"):
            parts.append(f"bdc_investment_identifier: {json.dumps(r['bdc_investment_identifier'])}")
        if r.get("report_date"):
            parts.append(f"report_date: {json.dumps(r['report_date'])}")
        mc = r.get("match_count")
        tag = ("UNVERIFIED: holdings file unavailable at preflight" if mc is None else
               f"matches {mc} current holdings row(s)" if mc else
               "NO MATCH in current holdings -- do NOT use as a selector")
        lines.append(f"  - {'; '.join(parts)} [{tag}]")
    if len(rows) > _MAX_GROUNDED_IDENTIFIERS:
        lines.append(f"  - ... {len(rows) - _MAX_GROUNDED_IDENTIFIERS} more not shown")
    return "\n".join(lines)


DEFAULT_PROMOTED = config.PROJECT_ROOT / "data" / "overrides" / "agent_b2_corrections"


def _example_leaf_block(fix_class: str, promoted_dir: Path = DEFAULT_PROMOTED) -> str:
    """One PROMOTED leaf of the same fix_class, embedded as a worked example.
    q4b2r4an trace lesson: workers spent 3-6 shell calls each hunting the repo for
    schema precedent despite the embedded contract excerpt. Deterministic pick
    (first by path); rationale truncated; the values belong to another CIK."""
    try:
        candidates = sorted(Path(promoted_dir).glob(f"*/{fix_class}.json"))
    except OSError:
        candidates = []
    for p in candidates:
        try:
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(leaf.get("fix_class") or "") != fix_class:
            continue
        rationale = str(leaf.get("rationale") or "")
        if len(rationale) > 240:
            leaf["rationale"] = rationale[:240] + " ..."
        return ("Worked example (a PROMOTED leaf of this fix_class from another CIK; "
                "match its SHAPE, not its values):\n" + json.dumps(leaf, indent=2))
    return ("Worked example: no promoted leaf of this fix_class exists yet; follow the "
            "contract excerpt above exactly.")


def _contract_excerpt(fix_class: str) -> str:
    """Schema-accurate template contract for the packet's fix_class, generated from the
    validator's own TEMPLATE_REGISTRY so prompt and validation can never disagree.
    (Regression: the excerpt was hard-coded to comparative_period_filter, so every other
    lane's worker authored that template shape and failed validate_corrections.)"""
    tpl = TEMPLATE_REGISTRY.get(fix_class)
    if tpl is None:
        return (f"Embedded contract excerpt for {fix_class}:\n"
                f"- No registered template; write the narrowest correction and set low confidence.")
    lines = [f"Embedded contract excerpt for {fix_class}:"]
    lines.append(f"- Required template param(s): {sorted(tpl.required)}")
    optional = sorted(tpl.allowed - tpl.required)
    if optional:
        lines.append(f"- Optional template param(s): {optional}")
    lines.append("- The template object may contain ONLY these params -- anything else is "
                 "rejected by the validator.")
    for k in sorted(getattr(tpl, "numeric", ()) or ()):
        lines.append(f"- template.{k} must be a number.")
    for k, vals in sorted((getattr(tpl, "enums", {}) or {}).items()):
        lines.append(f"- template.{k} must be one of {sorted(vals)}.")
    # Nested-structure contracts (the validator enforces these too).
    if "row_selector" in tpl.allowed:
        from pipeline.correction_leaf import ROW_SELECTOR_KEYS
        lines.append(f"- template.row_selector: ONE selector object, or a LIST of selector "
                     f"objects (OR-combined) to bind EVERY cited row -- use the list instead "
                     f"of widening scope or fixing one row and abandoning the rest. Object "
                     f"keys must be from {sorted(ROW_SELECTOR_KEYS)}; equality match, "
                     f"AND-combined within an object. Each object MUST include row_id, "
                     f"issuer_name, or bdc_investment_identifier. PREFER row_id when the "
                     f"grounded identifier list above shows one (it is the rebuild-stable "
                     f"ROW-... id and cannot drift with issuer-text normalization); "
                     f"otherwise copy the exact issuer/identifier string from that list "
                     f"(NOT the filing-citation text, which often differs and produces a "
                     f"no-op selector the gate refuses); table/row coordinates alone cannot "
                     f"select holdings rows.")
    if {"from_field", "to_field", "field"} & tpl.allowed:
        lines.append("- Field names refer to the UNIFIED HOLDINGS schema (the allowed "
                     "lists above), NEVER the filing table's own column headings.")
    from pipeline.correction_leaf import STAGE2_SCOPED_CLASSES
    if fix_class in STAGE2_SCOPED_CLASSES:
        lines.append("- The leaf MUST carry top-level scope.quarters: the explicit "
                     "YYYY-MM-DD list of quarters your cited evidence covers (never "
                     "'all'). The applier physically cannot touch other quarters, and "
                     "the gate proves they were left byte-identical. If the same "
                     "defect exists in another quarter, cite THAT quarter's filing "
                     "and add it to the scope.")
    if "positions" in tpl.allowed:
        lines.append("- Each template.positions[] entry REQUIRES issuer_name, fair_value "
                     "(number), report_date, source_row_id (the staging/source row id "
                     "being recovered -- copy it from the evidence; NEVER invent one; "
                     "current format src:{accession}:{context_id}), "
                     "and bdc_dimensions_raw. The gate re-verifies source_row_id and "
                     "fair_value against raw staging; a fabricated position cannot pass.")
    if "entities" in tpl.allowed:
        lines.append("- Each template.entities[] entry: {legal_entity, decision in "
                     "{use_equity, keep_lookthrough}}.")
    if "assertions" in tpl.allowed:
        lines.append(
            "- Each template.assertions[] entry: {row_selector (object or list, same "
            "rules as above), field (unified holdings numeric field), source "
            "{accession_number, table_index, row_index, cell_index, quoted_text (the "
            "cell as the grid shows it), value (the LITERAL number in that cell), "
            "unit_multiplier in {1, 1000, 1000000} (must be 1 for rate fields)}, "
            "witnesses: >= 2 entries {cell_index, field (!= the asserted field), "
            "value} naming OTHER cells in the SAME row whose values match the "
            "position's already-correct extracted fields. You never author a number: "
            "you point at the filing cell that contains it. The parent re-parses the "
            "cached filing and REFUSES the leaf if any cited cell, quoted text, or "
            "witness does not match exactly -- copy coordinates and values straight "
            "from the grid output, and pick witnesses whose extracted values you "
            "verified in the holdings CSV.")
    lines.append("- Do not emit code, SQL, file paths, or row-index deletions.")
    lines.append("- The prompt's CIK and fix_class are binding; do not switch fix_class.")
    return "\n".join(lines)


def _worker_prompt(row: dict, verdicts: list[dict], *, contract_abs: str, bundle_paths: list[str],
                   correction_path: Path, validator: str, py: str,
                   grounded_identifiers: list[dict] | None = None,
                   holdings_csv: Path | None = None,
                   filing_paths: list[str] | None = None,
                   example_block: str = "") -> str:
    cik = row["cik"]
    fix_class = row["fix_class"]
    mechanism = row.get("mechanism", "")
    quarters = str(row.get("quarters") or "").strip()
    correction_leaf = f"{fix_class}.json"
    srids = row.get("source_review_ids") or []
    if isinstance(srids, str):
        srids = [s for s in srids.split(";") if s.strip()]
    cli = EVIDENCE_CLI.resolve().as_posix()
    # The leading "& " is load-bearing: without the PowerShell call operator every
    # worker's first CLI attempt fails on quoting (q4b2r4an trace lesson -- workers
    # copy this line verbatim).
    bundle_lines = "\n".join(f"    & \"{py}\" \"{cli}\" --bundle \"{b}\" overview"
                             for b in bundle_paths) or "    (no bundles resolved)"
    holdings_line = (f"  \"{holdings_csv}\"" if holdings_csv is not None
                     else "  (holdings CSV unavailable at preflight)")
    filing_lines = "\n".join(f"  - {p}" for p in (filing_paths or [])) or \
        "  (no cached filing resolved from the source bundles at preflight)"
    return f"""Agent B2 remediation worker (analyst mode).

You author ONE constrained correction for ONE (cik, fix_class) packet that Agent B1 already
adjudicated as a real data error. You do NOT re-decide the error -- you propose the bounded
TEMPLATE that fixes it, and you GROUND every numeric and selector choice in the source
filing and the extracted holdings data before writing it. Do not launch nested Codex; no
tests, rebuilds, network, SEC downloads, git, or package installs.
Shell commands ARE allowed, but ONLY for the read-only analyst tools listed below.

The packet:
- CIK: {cik}    fix_class: {fix_class}    mechanism: {mechanism}
- target quarter(s): {quarters}
- source verdict(s): {', '.join(srids)}

The CIK and fix_class are binding. The JSON you write MUST keep:
- "cik": "{cik}"
- "fix_class": "{fix_class}"
Do not emit a different fix_class, even if the filing suggests another mechanism. If, after
grounding, the requested fix_class CANNOT express the defect you verified (wrong layer,
unsupported field, inexpressible row shape), do NOT author a plausible-looking correction.
Write `{fix_class}.escalation.json` INSTEAD (see Allowed write below) with: cik, fix_class
(keep "{fix_class}"), mechanism, diagnosis (the verified defect WITH the filing-vs-extracted
numbers), suggested_fix_class (free text; it may name a class that does not exist yet),
evidence_citations, confidence, rationale. An escalation routes the packet to the
template-authoring basket; it is never applied to data.

What B1 localized as the defect (re-ground these against source before trusting them):
{_citations_block(verdicts)}

Analyst workspace (READ-ONLY; all paths ABSOLUTE; your working directory is NOT the repo
root; invoke Python via the exact interpreter shown, "{py}"):
- Extracted holdings for CIK {cik} -- ALL quarters, ALL columns, including the
  rebuild-stable row_id (read with pandas or PowerShell Import-Csv):
{holdings_line}
- Source filing roam (the cached filing parsed to the SAME table grid the [tN/rM]
  citations index; run one line at a time):
{bundle_lines}
  Subcommands: overview (SOI-like tables), tables (all tables), grid --table N
  [--start M --count K] (read rows -- resolves a [tN/rM] citation exactly),
  roam --query "term1,term2" (search the whole filing), totals (the filing's own
  total/subtotal lines).
- Raw cached filing HTML (large; prefer the roam CLI above):
{filing_lines}

Holdings-side selector identifiers (the EXACT text in the unified holdings frame; any
template.row_selector must equality-match one of these strings -- filing-citation text
often differs and produces a no-op selector that the gate refuses):
{_grounding_block(grounded_identifiers or [])}

{_contract_excerpt(fix_class)}

{example_block or _example_leaf_block(fix_class)}

Allowed write (exactly ONE file -- the correction OR the escalation, never both):
- {correction_leaf}
- {fix_class}.escalation.json  (ONLY when the requested class cannot express the
  verified defect)

Your current working directory is the correction directory for CIK {cik}. Write the relative
file name `{correction_leaf}` only. Do not write an absolute path. The parent dispatcher will
validate the resulting file at:
- {correction_path}

Required workflow (analyst mode):
1. Resolve EVERY citation above with grid/roam and read the surrounding rows for context.
2. Find the corresponding extracted rows in the holdings CSV (by row_id, issuer_name, or
   bdc_investment_identifier) and note their values.
3. Compare the filing values with the extracted values. Every numeric template param
   (factor, rate, fair_value, ...) MUST be derived from that comparison, and the rationale
   must state it as "filing shows X, extracted shows Y". If you cannot derive a param this
   way, say so explicitly in the rationale and lower the confidence accordingly.
4. Choose template params that match the requested fix_class, using EXACTLY the params in
   the embedded contract excerpt above (required params present, no extras).
5. Write the correction leaf JSON to the one allowed path: cik, mechanism, fix_class,
   template (the bounded params), source_review_ids, evidence_citations (the cited rows),
   confidence (0..1), rationale. NO code, SQL, paths, or row-index deletions.
   Write the leaf with the FILE EDIT tool ONLY -- never via shell redirection
   (PowerShell Out-File/Set-Content stamps a UTF-8 BOM the validator rejects).
6. Do not run validation inside the worker. The parent dispatcher validates with:
   "{py}" "{validator}" --correction "{correction_path}" --expected-cik "{cik}" --expected-fix-class "{fix_class}"
7. Finish with a concise report: cik, fix_class, template, confidence, what you verified
   vs could not verify, residual risk, correction path.

Keep the investigation bounded: prefer roam/grid over dumping whole tables; you should
rarely need more than ~15 shell commands.

Evidence citations to copy into evidence_citations:
{_citations_json(verdicts)}

Nothing you write is applied until it passes this screen AND the B3 held-out gate (a
full-ledger re-run on all the CIK's quarters that you cannot see or game). Author for B3.
"""


def preflight_batch(
    batch_id: str, *, base_dir: Path = DEFAULT_BASE, verdicts_dir: Path = DEFAULT_VERDICTS,
    bundles_dir: Path = DEFAULT_BUNDLES, corrections_dir: Path = DEFAULT_CORRECTIONS,
    contract_rel: str = DEFAULT_CONTRACT, fix_class: str | None = None, reserve: bool = False,
    review_queue_path: Path | None = None,
    holdings_path: Path | None = config.UNIFIED_HOLDINGS_PARQUET_FILE,
    promoted_dir: Path = DEFAULT_PROMOTED,
) -> dict:
    batch_dir = _batch_dir(base_dir, batch_id)
    rows = _read_worklist(batch_dir)
    # only actionable packets (a registered fix_class), optionally restricted to one.
    rows = [r for r in rows if (r.get("fix_class") or "").strip()
            and (fix_class is None or r.get("fix_class") == fix_class)]
    if not rows:
        raise PreflightError("no actionable packets selected (need a fix_class; e.g. --fix-class subtotal_filter)")

    corrections_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = batch_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    contract_abs = (config.PROJECT_ROOT / contract_rel).resolve().as_posix()
    validator = VALIDATOR.resolve().as_posix()

    # Frame revalidation (2026-08-13): a packet exists because a finding fired. If its
    # source review_ids no longer appear in the CURRENT review queue, the target was
    # fixed by another route since B1 adjudicated it -- skip it with a recorded reason
    # (the q4b2t4b lesson: the wave's conservation targets had already been repaired
    # by the same-day rule re-keying).
    # Opt-in at the library level (tests use synthetic review ids); the CLI defaults
    # this to the production review queue.
    open_review_ids: set[str] | None = None
    if review_queue_path is not None and Path(review_queue_path).exists():
        with open(review_queue_path, newline="", encoding="utf-8-sig") as fh:
            open_review_ids = {r.get("review_id", "") for r in csv.DictReader(fh)}

    seen: set[tuple] = set()
    manifest_rows: list[dict] = []
    skipped_no_citations: list[dict] = []
    skipped_policy: list[dict] = []
    skipped_stale: list[dict] = []
    skipped_existing: list[dict] = []
    skipped_escalated: list[dict] = []
    supported_fix_classes = implemented_fix_classes()
    for row in rows:
        cik = str(row.get("cik") or "").strip()
        fc = str(row.get("fix_class") or "").strip()
        if not _CIK_RE.match(cik):
            raise PreflightError(f"invalid cik in worklist: {cik!r}")
        if fc in POLICY_FIX_CLASSES:
            skipped_policy.append({
                "cik": cik, "fix_class": fc,
                "source_review_ids": [s for s in (row.get("source_review_ids") or "").split(";") if s],
                "reason": "detector-policy fix_class (validation-rule scope change); "
                          "routed to the human escalation basket, not worker dispatch"})
            continue
        if fc not in supported_fix_classes:
            raise PreflightError(
                f"{cik}/{fc}: fix_class has no implemented trial applier; "
                f"supported={sorted(supported_fix_classes)}"
            )
        _rids_now = [s for s in (row.get("source_review_ids") or "").split(";") if s.strip()]
        if open_review_ids is not None and _rids_now and \
                not any(r in open_review_ids for r in _rids_now):
            skipped_stale.append({
                "cik": cik, "fix_class": fc, "source_review_ids": _rids_now,
                "reason": "stale target: no source finding still open in the current "
                          "review queue (fixed upstream since B1 adjudication)"})
            continue
        quarters = [q for q in str(row.get("quarters") or "").split(";") if q.strip()]
        if fc == "comparative_period_filter" and len(quarters) != 1:
            raise PreflightError(
                f"{cik}/{fc}: expected exactly one target quarter for comparative filter, "
                f"got {quarters}"
            )
        key = (cik, fc)
        if key in seen:
            raise PreflightError(f"duplicate packet in batch: {cik}/{fc}")
        seen.add(key)

        rids = [s for s in (row.get("source_review_ids") or "").split(";") if s.strip()]
        if not rids:
            raise PreflightError(f"{cik}/{fc}: no source_review_ids")
        verdicts = [_load_verdict(rid, verdicts_dir) for rid in rids]
        # validate_corrections requires >=1 citation (quote or table/row coordinate).
        # A packet whose source verdicts carry none can only produce a guaranteed-invalid
        # correction -- skip it with a recorded reason instead of burning a worker on it.
        n_usable_citations = sum(
            1 for v in verdicts for c in (v.get("culprit_citations") or [])
            if str(c.get("quoted_text") or "").strip()
            or (c.get("table_index") is not None and c.get("row_index") is not None))
        if n_usable_citations == 0:
            skipped_no_citations.append({
                "cik": cik, "fix_class": fc, "source_review_ids": rids,
                "reason": "source verdict(s) carry no usable culprit citations; "
                          "needs evidence re-enrichment before B2 dispatch"})
            continue
        bundles = [_load_bundle(rid, bundles_dir) for rid in rids]
        for rid, (_, bundle) in zip(rids, bundles):
            bundle_cik = normalize_cik(bundle.get("cik"))
            if not bundle_cik:
                raise PreflightError(f"{rid}: source bundle missing cik")
            if bundle_cik != normalize_cik(cik):
                raise PreflightError(
                    f"{cik}/{fc}: source bundle {rid} belongs to CIK {bundle_cik}"
                )
            if fc == "missing_position_add" and (bundle.get("integrity_errors") or []):
                raise PreflightError(
                    f"{cik}/{fc}: source bundle {rid} has identity-integrity failure: "
                    f"{bundle['integrity_errors']}"
                )
        bundle_paths = [str(path) for path, _ in bundles]

        correction_path = (corrections_dir / cik / f"{fc}.json").resolve()
        if correction_path.exists():
            # Iterative rounds (2026-08-13): a staged valid leaf from a prior round is
            # awaiting its gate -- skip the packet, do not halt the lane.
            skipped_existing.append({
                "cik": cik, "fix_class": fc,
                "reason": f"staged correction already exists at {correction_path}"})
            continue
        escalation_path = correction_path.with_name(f"{fc}.escalation.json")
        if escalation_path.exists():
            # An escalated packet needs template authoring / human review, not another
            # worker -- redispatching would just re-derive the same inexpressible defect.
            skipped_escalated.append({
                "cik": cik, "fix_class": fc,
                "reason": f"escalation already staged at {escalation_path}; awaiting "
                          "template-authoring/human basket"})
            continue
        correction_path.parent.mkdir(parents=True, exist_ok=True)
        # Lock key doubles as a lock filename ({lock_key}.lock); Windows forbids ':'
        # in filenames (reserved for drive letters / NTFS ADS), so use a safe separator.
        lock_key = f"B2__{cik}__{fc}"
        if review_lock.is_locked(lock_key):
            raise PreflightError(f"{cik}/{fc}: live lock already exists")

        prompt_path = prompts_dir / f"{cik}__{fc}.md"
        row["source_review_ids"] = ";".join(rids)
        manifest_rows.append({
            "cik": cik, "fix_class": fc, "mechanism": row.get("mechanism", ""),
            "quarters": row.get("quarters", ""),
            "source_review_ids": rids, "verdict_paths": [str((verdicts_dir / f"{r}.json").resolve()) for r in rids],
            "bundle_paths": bundle_paths, "prompt_path": str(prompt_path),
            "correction_path": str(correction_path), "lock_key": lock_key})

    acquired: list[str] = []
    if reserve:
        for r in manifest_rows:
            if not review_lock.acquire(r["lock_key"], owner=f"b2dispatch:{batch_id}"):
                for held in acquired:
                    review_lock.release(held)
                raise PreflightError(f"{r['lock_key']}: failed to acquire lock; released prior claims")
            acquired.append(r["lock_key"])

    staging_dir = batch_dir / "staging"
    staged_by_cik: dict[str, Path | None] = {}
    example_by_fc: dict[str, str] = {}
    for r in manifest_rows:
        verdicts = [json.loads(Path(p).read_text(encoding="utf-8")) for p in r["verdict_paths"]]
        bundles = [json.loads(Path(p).read_text(encoding="utf-8")) for p in r["bundle_paths"]]
        grounded = _verify_identifiers(_bundle_identifier_rows(bundles), r["cik"], holdings_path)
        r["n_grounded_identifiers"] = len(grounded)
        # Analyst mode: stage the per-CIK holdings slice once per CIK and resolve the
        # cached filing paths, so the worker can compare filing values against
        # extracted values instead of authoring numeric params blind.
        if r["cik"] not in staged_by_cik:
            staged_by_cik[r["cik"]] = _stage_holdings_csv(
                r["cik"], holdings_path, staging_dir)
        staged_csv = staged_by_cik[r["cik"]]
        filing_paths = _filing_html_paths(bundles)
        r["holdings_csv_path"] = str(staged_csv) if staged_csv is not None else None
        r["filing_html_paths"] = filing_paths
        if r["fix_class"] not in example_by_fc:
            example_by_fc[r["fix_class"]] = _example_leaf_block(r["fix_class"], promoted_dir)
        Path(r["prompt_path"]).write_text(
            _worker_prompt(r, verdicts, contract_abs=contract_abs, bundle_paths=r["bundle_paths"],
                           correction_path=Path(r["correction_path"]), validator=validator, py=WORKER_PYTHON,
                           grounded_identifiers=grounded, holdings_csv=staged_csv,
                           filing_paths=filing_paths,
                           example_block=example_by_fc[r["fix_class"]]),
            encoding="utf-8")

    if not manifest_rows:
        raise PreflightError(
            "no dispatchable packets after skips "
            f"(no_citations={len(skipped_no_citations)}, policy={len(skipped_policy)}, "
            f"stale={len(skipped_stale)}, existing={len(skipped_existing)}, "
            f"escalated={len(skipped_escalated)})")
    wave_path, wave = _next_manifest_path(batch_dir)
    manifest = {
        "batch_id": batch_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "wave": wave,
        "locks_reserved": reserve, "max_parallel_default": 2,
        "corrections_dir": str(corrections_dir), "worker_python": WORKER_PYTHON,
        "worker_read_dirs": _worker_read_dirs(), "n_dispatch": len(manifest_rows),
        "skipped_no_citations": skipped_no_citations,
        "skipped_policy": skipped_policy,
        "skipped_stale": skipped_stale,
        "skipped_existing": skipped_existing,
        "skipped_escalated": skipped_escalated,
        "rows": manifest_rows}
    # Wave-stamped manifest is the durable record (one per dispatch wave; the old
    # single manifest.json was overwritten by every wave, so q4b2exp recorded 2 rows
    # where 126 were dispatched). manifest.json remains as a latest-wave pointer for
    # tooling that globs the fixed name.
    payload = json.dumps(manifest, indent=2)
    wave_path.write_text(payload, encoding="utf-8")
    (batch_dir / "manifest.json").write_text(payload, encoding="utf-8")
    return {"manifest_path": str(wave_path),
            "manifest_latest": str(batch_dir / "manifest.json"),
            "wave": wave, "n_dispatch": len(manifest_rows),
            "n_skipped_no_citations": len(skipped_no_citations),
            "n_skipped_policy": len(skipped_policy),
            "n_skipped_stale": len(skipped_stale),
            "n_skipped_existing": len(skipped_existing),
            "n_skipped_escalated": len(skipped_escalated), "batch_id": batch_id}


def _next_manifest_path(batch_dir: Path) -> tuple[Path, int]:
    """Next wave-stamped manifest path (manifest.001.json, .002, ...)."""
    waves = []
    for p in batch_dir.glob("manifest.[0-9][0-9][0-9].json"):
        try:
            waves.append(int(p.name.split(".")[1]))
        except (IndexError, ValueError):
            continue
    n = (max(waves) + 1) if waves else 1
    return batch_dir / f"manifest.{n:03d}.json", n


def release_manifest(manifest_path: str) -> None:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    for row in manifest.get("rows", []):
        review_lock.release(row.get("lock_key", ""))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Agent B2 dispatch preflight ((cik, fix_class) keyed).")
    p.add_argument("--batch-id")
    p.add_argument("--fix-class", default=None, help="Restrict to one fix_class (e.g. subtotal_filter).")
    p.add_argument("--reserve", action="store_true")
    p.add_argument("--release-manifest")
    p.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE,
                   help="Current review queue for stale-target revalidation "
                        "(--no-revalidate to disable).")
    p.add_argument("--no-revalidate", action="store_true",
                   help="Skip stale-target revalidation against the review queue.")
    args = p.parse_args(argv)
    try:
        if args.release_manifest:
            release_manifest(args.release_manifest)
            print(json.dumps({"released_manifest": args.release_manifest}))
            return 0
        if not args.batch_id:
            raise PreflightError("--batch-id is required")
        print(json.dumps(preflight_batch(
            args.batch_id, fix_class=args.fix_class, reserve=args.reserve,
            review_queue_path=(None if args.no_revalidate else args.review_queue))))
        return 0
    except PreflightError as exc:
        print(f"PRECHECK_FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
