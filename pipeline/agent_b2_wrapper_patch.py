"""Agent B2 wrapper-patch appliers (extraction-domain corrections).

For mechanisms the per-CIK BDC XBRL wrapper ALREADY owns (subtotal/aggregate detection,
classification), a B2 correction is not a row transform -- it is a PATCH to the wrapper
config, consumed by the existing ``bdc_xbrl_wrapper`` machinery. ``subtotal_filter`` adds
the leaked subtotal patterns to the wrapper's ``dispatch.aggregate_markers`` so the rows are
dispositioned as aggregates at STAGING (the correct layer), instead of dropping them
post-hoc in a parallel mechanism.

The patch is written to a TRIAL wrapper dir (never the production override); the trial
rebuild loads it via ``bdc_xbrl_wrapper.reload_wrapper_specs(override_dir=...)``, and B3
gates the result. Promotion (copying the trial wrapper to the production override) is the
driver's ``promote`` step. Templates are assumed validated by
``pipeline.correction_leaf.validate_correction``.

Audit/provenance: the trial wrapper carries a ``b2_provenance`` block so the *why* of a new
marker (source review_ids, evidence, confidence) is never lost -- the gap flagged when we
compared B2 corrections to the existing (provenance-free) wrappers. ASCII-only.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.bdc_xbrl_wrapper import normalize_cik

PROD_WRAPPER_DIR = Path(__file__).resolve().parent.parent / "data" / "overrides" / "bdc_xbrl_wrappers"


def apply_subtotal_filter(
    cik: str, template: dict, *, out_wrapper_dir: Path,
    source_wrapper_dir: Path = PROD_WRAPPER_DIR, provenance: dict | None = None,
) -> dict:
    """Merge ``template['patterns']`` into the CIK's wrapper ``dispatch.aggregate_markers``,
    writing a TRIAL wrapper to ``out_wrapper_dir/<cik>.json``. Returns an audit dict.

    Fails safe (status=error, no write) when the source wrapper is missing or is not a
    dispatch-style wrapper -- those CIKs need a different mechanism, not a silent no-op."""
    cik_norm = normalize_cik(cik)
    audit: dict = {"fix_class": "subtotal_filter", "cik": cik_norm}
    patterns = [str(p).strip() for p in (template.get("patterns") or []) if str(p).strip()]
    if not patterns:
        audit.update(status="error", message="no patterns to add")
        return audit

    src = Path(source_wrapper_dir) / f"{cik_norm}.json"
    if not src.exists():
        audit.update(status="error", message=f"no source wrapper for CIK {cik_norm}")
        return audit
    try:
        wrapper = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        audit.update(status="error", message=f"unreadable source wrapper: {exc}")
        return audit

    dispatch = wrapper.get("dispatch")
    if not isinstance(dispatch, dict):
        audit.update(status="error",
                     message="wrapper has no dispatch section (not a dispatch-style wrapper); "
                             "subtotal_filter does not apply -- use a different mechanism")
        return audit

    # aggregate_markers are matched as lowercased substrings (see _rollup_disposition);
    # normalize + dedup while preserving the existing order, then append the new ones.
    existing = list(dispatch.get("aggregate_markers") or [])
    existing_lower = {m.lower() for m in existing}
    added = []
    for p in patterns:
        pl = p.lower()
        if pl not in existing_lower:
            existing.append(pl)
            existing_lower.add(pl)
            added.append(pl)
    dispatch["aggregate_markers"] = existing
    wrapper["dispatch"] = dispatch

    # provenance block -- the audit trail the bare wrapper config lacks.
    prov = wrapper.setdefault("b2_provenance", [])
    prov.append({"fix_class": "subtotal_filter", "patterns_added": added,
                 **(provenance or {})})

    out_dir = Path(out_wrapper_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{cik_norm}.json"
    out_path.write_text(json.dumps(wrapper, indent=2), encoding="utf-8")

    audit.update(status="ok", patterns_added=added, n_markers_total=len(existing),
                 out_path=str(out_path),
                 match_mode_note=("applied as substring (contains); wrapper markers are "
                                  "substring-matched" if template.get("match_mode") == "exact" else "contains"))
    return audit
